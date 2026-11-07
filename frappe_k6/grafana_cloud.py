"""
Grafana Cloud integration for frappe_k6.

Needs only three settings (Monitor Settings → Grafana Cloud): the stack's Grafana URL,
a Grafana service account token, and a Cloud access policy token with metrics:write
and logs:write. Everything else — Prometheus/Loki endpoints, user IDs, datasource
UIDs — is discovered from the stack's own datasources.

What it does:
  * pushes Frappe metrics (every minute) and live load-test metrics (every 10 s) to
    Grafana Cloud Prometheus with the same names the bundled dashboards use, so no
    agent is needed for them (Prometheus remote write, no extra Python packages)
  * pushes run events to Grafana Cloud Loki
  * imports the bundled dashboards with datasource UIDs rewritten for the stack
  * provisions a "Frappe K6" contact point and the Grafana alert rules from settings
  * migrates run history into Grafana annotations
"""

import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import get_datetime, get_system_timezone, now_datetime

CLOUD_MODES = ("Grafana Cloud", "Hybrid")
CONTACT_POINT = "Frappe K6"
FOLDER_TITLE = "Frappe K6"
ANNOTATION_TAG = "frappe_k6"
CHANNEL_TYPES = ("email", "slack", "teams", "webhook")

SETUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup")
DASHBOARD_FILES = (
	"frappe_k6_dashboard.json",
	"frappe_k6_load_test_dashboard.json",
	"frappe_k6_multi_dashboard.json",
	"frappe_k6_remote_server_dashboard.json",
	"frappe_k6_node_dashboard.json",
	"frappe_k6_db_dashboard.json",
	"frappe_k6_redis_dashboard.json",
	"frappe_k6_worker_dashboard.json",
)

# {$site} becomes site="<site>" so one stack can serve several benches
DEFAULT_CLOUD_RULES = (
	("Load test p95 latency high", "max(frappe_k6_run_p95_ms{$site})", ">", 2000, "2m", "warning"),
	("Load test error rate high", "max(frappe_k6_run_error_rate{$site})", ">", 5, "1m", "critical"),
	("CPU usage high", "max(frappe_cpu_percent{$site})", ">", 85, "5m", "warning"),
	("Memory usage high", "max(frappe_memory_percent{$site})", ">", 90, "5m", "critical"),
	("Disk almost full", "max(frappe_disk_percent{$site})", ">", 90, "10m", "warning"),
	("Redis down", "min(frappe_redis_connected{$site})", "<", 1, "2m", "critical"),
	("Database down", "min(frappe_db_connected{$site})", "<", 1, "2m", "critical"),
	("RQ queue backlog", "sum(frappe_queue_depth{$site})", ">", 500, "10m", "warning"),
	("Frappe metrics stopped arriving", "absent_over_time(frappe_cpu_percent{$site}[10m])", ">", 0, "0s", "critical"),
)


class GrafanaCloudError(frappe.ValidationError):
	pass


# ─── Settings ────────────────────────────────────────────────────────────────

def get_config():
	s = frappe.get_single("Monitor Settings")
	return frappe._dict(
		mode=s.monitoring_mode or "Off",
		grafana_url=(s.gc_grafana_url or "").strip().rstrip("/"),
		sa_token=s.get_password("gc_service_account_token", raise_exception=False) or "",
		access_token=s.get_password("gc_access_policy_token", raise_exception=False) or "",
		prom_url=(s.gc_prometheus_url or "").strip().rstrip("/"),
		prom_user=(s.gc_prometheus_user or "").strip(),
		prom_ds=(s.gc_prometheus_datasource_uid or "").strip(),
		loki_url=(s.gc_loki_url or "").strip().rstrip("/"),
		loki_user=(s.gc_loki_user or "").strip(),
		loki_ds=(s.gc_loki_datasource_uid or "").strip(),
		folder_uid=(s.gc_folder_uid or "frappe-k6").strip(),
		native_k6=bool(s.gc_send_k6_native_metrics),
	)


def cloud_enabled(cfg=None):
	cfg = cfg or get_config()
	return cfg.mode in CLOUD_MODES and bool(cfg.prom_url)


def pushes_from_frappe(cfg=None):
	"""In Hybrid mode the local Prometheus forwards everything; Frappe pushes only in Grafana Cloud mode."""
	cfg = cfg or get_config()
	return cfg.mode == "Grafana Cloud" and bool(cfg.prom_url)


def prom_push_url(url):
	url = url.rstrip("/")
	return url + "/push" if url.endswith("/api/prom") else url + "/api/v1/write"


def loki_push_url(url):
	return url.rstrip("/") + "/loki/api/v1/push"


def _basic(user, token):
	if not (user and token):
		return {}
	return {"Authorization": "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()}


def _site_hash():
	return hashlib.sha1(frappe.local.site.encode()).hexdigest()[:6]


def base_labels():
	server = frappe.db.get_value("Remote Server", {"is_local": 1}, ["server_name", "environment"], as_dict=True)
	return {
		"site": frappe.local.site,
		"job": "frappe_k6",
		"instance": socket.gethostname(),
		"server_name": (server and server.server_name) or socket.gethostname(),
		"env": ((server and server.environment) or "production").lower(),
	}


# ─── HTTP ────────────────────────────────────────────────────────────────────

def _http(method, url, body=None, headers=None, timeout=20, raw=False):
	data = body if (raw or body is None) else json.dumps(body).encode()
	h = {"Accept": "application/json", "User-Agent": "frappe_k6"}
	if body is not None and not raw:
		h["Content-Type"] = "application/json"
	h.update(headers or {})
	req = urllib.request.Request(url, data=data, headers=h, method=method)
	try:
		with urllib.request.urlopen(req, timeout=timeout) as r:
			text = r.read()
			status = r.status
	except urllib.error.HTTPError as e:
		text, status = e.read(), e.code
	except (urllib.error.URLError, OSError) as e:
		raise GrafanaCloudError(_("Cannot reach {0}: {1}").format(url, e)) from e
	try:
		return status, json.loads(text) if text else None
	except ValueError:
		return status, text.decode(errors="replace")[:500]


class Grafana:
	"""Grafana HTTP API with a service account token (works for Grafana Cloud and self-managed)."""

	def __init__(self, url, token):
		if not url or not token:
			raise GrafanaCloudError(_("Set the Grafana Cloud URL and the service account token first."))
		self.url = url.rstrip("/")
		self.headers = {"Authorization": f"Bearer {token}", "X-Disable-Provenance": "true"}

	def call(self, method, path, body=None, allow=()):
		status, data = _http(method, self.url + path, body, self.headers)
		if 200 <= status < 300:
			return data
		if status in allow:
			return None
		raise GrafanaCloudError(_("Grafana {0} {1} returned HTTP {2}: {3}").format(method, path, status, data))


def client(cfg=None):
	cfg = cfg or get_config()
	return Grafana(cfg.grafana_url, cfg.sa_token)


# ─── Discovery ───────────────────────────────────────────────────────────────

def _pick_datasource(sources, ds_type, cloud_suffix):
	candidates = [d for d in sources if d.get("type") == ds_type]
	for d in candidates:
		name = d.get("name", "")
		if name.startswith("grafanacloud-") and name.endswith(cloud_suffix):
			return d
	for d in candidates:
		if not d.get("name", "").startswith("grafanacloud-"):
			return d  # self-managed Grafana
	return candidates[0] if candidates else None


def discover(grafana):
	"""Read Prometheus/Loki endpoints, user IDs and datasource UIDs from the stack."""
	sources = grafana.call("GET", "/api/datasources") or []
	prom = _pick_datasource(sources, "prometheus", "-prom")
	loki = _pick_datasource(sources, "loki", "-logs")
	if not prom:
		raise GrafanaCloudError(_("No Prometheus datasource found in this Grafana stack."))
	found = {
		"gc_prometheus_url": (prom.get("url") or "").rstrip("/"),
		"gc_prometheus_user": str(prom.get("basicAuthUser") or ""),
		"gc_prometheus_datasource_uid": prom.get("uid") or "",
	}
	if loki:
		found.update({
			"gc_loki_url": (loki.get("url") or "").rstrip("/"),
			"gc_loki_user": str(loki.get("basicAuthUser") or ""),
			"gc_loki_datasource_uid": loki.get("uid") or "",
		})
	return found


# ─── Prometheus remote write (protobuf + snappy, no dependencies) ────────────

def _varint(n):
	out = bytearray()
	while True:
		byte = n & 0x7F
		n >>= 7
		if n:
			out.append(byte | 0x80)
		else:
			out.append(byte)
			return bytes(out)


def _len_field(number, payload):
	return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def encode_write_request(series):
	"""
	Encode a prometheus.WriteRequest. `series` is a list of (labels, value, timestamp_ms);
	labels must include __name__.
	"""
	out = bytearray()
	for labels, value, ts_ms in series:
		ts = bytearray()
		for key in sorted(labels):
			ts += _len_field(1, _len_field(1, key.encode()) + _len_field(2, str(labels[key]).encode()))
		sample = b"\x09" + struct.pack("<d", float(value)) + b"\x10" + _varint(int(ts_ms))
		ts += _len_field(2, sample)
		out += _len_field(1, bytes(ts))
	return bytes(out)


def snappy_block(data):
	"""Snappy block format using literal elements only: valid for every decoder, no compression."""
	out = bytearray(_varint(len(data)))
	for i in range(0, len(data), 65536):
		chunk = data[i:i + 65536]
		n = len(chunk) - 1
		if n < 60:
			out.append(n << 2)
		elif n < 256:
			out += bytes([60 << 2, n])
		else:
			out += bytes([61 << 2]) + n.to_bytes(2, "little")
		out += chunk
	return bytes(out)


def push_samples(samples, cfg=None, extra_labels=None):
	"""samples: iterable of (name, labels, value). Adds the base labels and the current time."""
	cfg = cfg or get_config()
	if not cfg.prom_url:
		raise GrafanaCloudError(_("Grafana Cloud Prometheus URL is not set."))
	now_ms = int(time.time() * 1000)
	common = {**base_labels(), **(extra_labels or {})}
	series = [({**common, **labels, "__name__": name}, value, now_ms) for name, labels, value in samples]
	if not series:
		return 0
	headers = {
		"Content-Encoding": "snappy",
		"Content-Type": "application/x-protobuf",
		"X-Prometheus-Remote-Write-Version": "0.1.0",
		**_basic(cfg.prom_user, cfg.access_token),
	}
	status, data = _http("POST", prom_push_url(cfg.prom_url), snappy_block(encode_write_request(series)),
						 headers, raw=True)
	if not 200 <= status < 300:
		raise GrafanaCloudError(_("Metrics push returned HTTP {0}: {1}").format(status, data))
	return len(series)


def push_logs(lines, labels=None, cfg=None):
	cfg = cfg or get_config()
	if not cfg.loki_url:
		return 0
	stream = {"site": frappe.local.site, "job": "frappe_k6", **(labels or {})}
	now_ns = time.time_ns()
	body = {"streams": [{"stream": stream, "values": [[str(now_ns + i), line] for i, line in enumerate(lines)]}]}
	status, data = _http("POST", loki_push_url(cfg.loki_url), body, _basic(cfg.loki_user, cfg.access_token))
	if not 200 <= status < 300:
		raise GrafanaCloudError(_("Log push returned HTTP {0}: {1}").format(status, data))
	return len(lines)


def log_event(event, message, **fields):
	"""Best-effort run event to Grafana Cloud Loki."""
	cfg = get_config()
	if not (cloud_enabled(cfg) and cfg.loki_url):
		return
	try:
		push_logs([json.dumps({"event": event, "message": message, **fields}, default=str)],
				  {"event": event}, cfg)
	except Exception as e:
		_note_error("log_event", e)


def _note_error(where, exc):
	"""Record push failures in Monitor Settings → Status, and the Error Log at most hourly."""
	msg = f"{now_datetime():%Y-%m-%d %H:%M} {where}: {exc}"
	frappe.db.set_single_value("Monitor Settings", "gc_status", msg[:1000])
	key = f"frappe_k6:gc_error:{where}"
	if not frappe.cache().get_value(key):
		frappe.cache().set_value(key, 1, expires_in_sec=3600)
		frappe.log_error(msg, "frappe_k6 Grafana Cloud")


# ─── Scheduled push ──────────────────────────────────────────────────────────

def push_system_metrics():
	"""Scheduler (every minute): push Frappe metrics in Grafana Cloud mode."""
	cfg = get_config()
	if not pushes_from_frappe(cfg):
		return
	from frappe_k6.api.system_metrics import collect_samples

	try:
		push_samples([(name, labels, value) for name, _h, _k, labels, value in collect_samples()], cfg)
	except Exception as e:
		_note_error("push_system_metrics", e)


# ─── Dashboards ──────────────────────────────────────────────────────────────

def _map_datasource(value, mapping):
	if isinstance(value, dict):
		uid = value.get("uid")
		if mapping.get(uid):
			return {**value, "uid": mapping[uid]}
		return value
	if isinstance(value, str) and value.lower() in mapping and mapping[value.lower()]:
		return {"type": value.lower(), "uid": mapping[value.lower()]}
	return value


def _rewrite(node, mapping):
	if isinstance(node, dict):
		return {k: (_map_datasource(v, mapping) if k == "datasource" else _rewrite(v, mapping))
				for k, v in node.items()}
	if isinstance(node, list):
		return [_rewrite(v, mapping) for v in node]
	return node


def prepare_dashboard(dashboard, prom_uid, loki_uid=None):
	"""Point the bundled dashboard at the stack's datasources and show run annotations."""
	dash = _rewrite(dashboard, {"prometheus": prom_uid, "loki": loki_uid})
	dash["id"] = None
	annotations = dash.setdefault("annotations", {}).setdefault("list", [])
	if not any(a.get("name") == "Load test runs" for a in annotations):
		annotations.append({
			"name": "Load test runs",
			"datasource": {"type": "grafana", "uid": "-- Grafana --"},
			"enable": True,
			"iconColor": "purple",
			"target": {"type": "tags", "tags": [ANNOTATION_TAG], "matchAny": True, "limit": 200},
		})
	return dash


def ensure_folder(grafana, cfg):
	if not grafana.call("GET", f"/api/folders/{cfg.folder_uid}", allow=(404,)):
		grafana.call("POST", "/api/folders", {"uid": cfg.folder_uid, "title": FOLDER_TITLE})
	return cfg.folder_uid


def import_dashboards(grafana, cfg):
	if not cfg.prom_ds:
		raise GrafanaCloudError(_("Prometheus datasource UID is not set; run discovery first."))
	ensure_folder(grafana, cfg)
	urls = []
	for fname in DASHBOARD_FILES:
		path = os.path.join(SETUP_DIR, fname)
		if not os.path.isfile(path):
			continue
		with open(path) as f:
			dash = prepare_dashboard(json.load(f), cfg.prom_ds, cfg.loki_ds)
		res = grafana.call("POST", "/api/dashboards/db", {
			"dashboard": dash, "folderUid": cfg.folder_uid, "overwrite": True,
			"message": "Imported by frappe_k6",
		})
		urls.append(cfg.grafana_url + (res or {}).get("url", ""))
	return urls


# ─── Alerting ────────────────────────────────────────────────────────────────

def notification_channels():
	"""Configured channels shared by Grafana contact points and Frappe-side alerts."""
	s = frappe.get_single("Monitor Settings")
	emails = [e.strip() for e in (s.alert_emails or "").replace(",", "\n").splitlines() if e.strip()]
	channels = {}
	if emails:
		channels["email"] = emails
	for key, field in (("slack", "slack_webhook_url"), ("teams", "teams_webhook_url"),
					   ("webhook", "alert_webhook_url")):
		url = s.get_password(field, raise_exception=False) if s.get(field) else ""
		if url:
			channels[key] = url
	return channels


def _contact_uid(kind):
	return f"fk6-{_site_hash()}-{kind}"


def provision_contact_point(grafana):
	"""Create/update one 'Frappe K6' contact point with an integration per configured channel."""
	channels = notification_channels()
	existing = {cp.get("uid") for cp in (grafana.call("GET", "/api/v1/provisioning/contact-points") or [])}
	name = f"{CONTACT_POINT} ({frappe.local.site})"
	for kind in CHANNEL_TYPES:
		uid = _contact_uid(kind)
		if kind not in channels:
			if uid in existing:
				grafana.call("DELETE", f"/api/v1/provisioning/contact-points/{uid}", allow=(404,))
			continue
		value = channels[kind]
		settings = {"addresses": ";".join(value)} if kind == "email" else {"url": value}
		if kind == "webhook":
			settings["httpMethod"] = "POST"
		body = {"uid": uid, "name": name, "type": kind, "settings": settings, "disableResolveMessage": False}
		if uid in existing:
			grafana.call("PUT", f"/api/v1/provisioning/contact-points/{uid}", body)
		else:
			grafana.call("POST", "/api/v1/provisioning/contact-points", body)
	return name if channels else None


def ensure_default_cloud_rules(settings=None):
	settings = settings or frappe.get_single("Monitor Settings")
	if settings.cloud_alert_rules:
		return False
	for title, expr, op, threshold, for_duration, severity in DEFAULT_CLOUD_RULES:
		settings.append("cloud_alert_rules", {
			"enabled": 1, "title": title, "expr": expr, "operator": op,
			"threshold": threshold, "for_duration": for_duration, "severity": severity,
		})
	return True


def _rule_uid(title):
	slug = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
	return f"fk6-{_site_hash()}-{slug}"[:40].rstrip("-")


def build_alert_rule(rule, cfg, receiver):
	site = frappe.local.site
	expr = rule.expr.replace("{$site}", f'{{site="{site}"}}').replace("$site", f'site="{site}"')
	evaluator = "gt" if rule.operator == ">" else "lt"
	body = {
		"uid": _rule_uid(rule.title),
		"title": f"{rule.title} ({site})",
		"condition": "C",
		"folderUID": cfg.folder_uid,
		"ruleGroup": f"frappe-k6 {site}",
		"noDataState": "OK",
		"execErrState": "Error",
		"for": rule.for_duration or "5m",
		"labels": {"severity": rule.severity or "warning", "app": "frappe_k6", "site": site},
		"annotations": {
			"summary": f"{rule.title} on {site}",
			"description": "Value {{ $values.B.Value }} is " + f"{rule.operator} {rule.threshold:g}",
		},
		"data": [
			{"refId": "A", "relativeTimeRange": {"from": 600, "to": 0}, "datasourceUid": cfg.prom_ds,
			 "model": {"refId": "A", "expr": expr, "instant": True, "range": False,
					   "intervalMs": 1000, "maxDataPoints": 43200}},
			{"refId": "B", "relativeTimeRange": {"from": 0, "to": 0}, "datasourceUid": "__expr__",
			 "model": {"refId": "B", "type": "reduce", "expression": "A", "reducer": "last",
					   "settings": {"mode": "dropNN"}}},
			{"refId": "C", "relativeTimeRange": {"from": 0, "to": 0}, "datasourceUid": "__expr__",
			 "model": {"refId": "C", "type": "threshold", "expression": "B",
					   "conditions": [{"evaluator": {"type": evaluator, "params": [float(rule.threshold or 0)]}}]}},
		],
	}
	if receiver:
		body["notification_settings"] = {"receiver": receiver}
	return body


def provision_alert_rules(grafana, cfg, receiver):
	if not cfg.prom_ds:
		raise GrafanaCloudError(_("Prometheus datasource UID is not set; run discovery first."))
	ensure_folder(grafana, cfg)
	settings = frappe.get_single("Monitor Settings")
	wanted = {}
	for rule in settings.cloud_alert_rules:
		if rule.enabled:
			body = build_alert_rule(rule, cfg, receiver)
			wanted[body["uid"]] = body

	prefix = f"fk6-{_site_hash()}-"
	existing = {r["uid"] for r in (grafana.call("GET", "/api/v1/provisioning/alert-rules") or [])
				if r.get("uid", "").startswith(prefix)}
	for uid, body in wanted.items():
		if uid in existing:
			grafana.call("PUT", f"/api/v1/provisioning/alert-rules/{uid}", body)
		else:
			grafana.call("POST", "/api/v1/provisioning/alert-rules", body)
	for uid in existing - set(wanted):
		grafana.call("DELETE", f"/api/v1/provisioning/alert-rules/{uid}", allow=(404,))
	return sorted(wanted)


# ─── Run history → annotations ───────────────────────────────────────────────

def _epoch_ms(value):
	"""Frappe datetimes are naive, in the system time zone."""
	dt = get_datetime(value)
	if dt.tzinfo is None:
		tz = get_system_timezone()
		try:
			dt = dt.replace(tzinfo=ZoneInfo(tz))
		except Exception:
			# Legacy names such as Asia/Calcutta are missing from some tzdata installs
			try:
				import pytz

				dt = pytz.timezone(tz).localize(dt)
			except Exception:
				dt = dt.astimezone()  # server local time
	return int(dt.timestamp() * 1000)


def annotate_run(grafana, run):
	start = run.started_at or run.creation
	end = run.completed_at or start
	err = round((run.failed_requests or 0) / run.total_requests * 100, 2) if run.total_requests else 0
	text = (f"{run.config}: {run.status} · {run.total_requests or 0} requests · "
			f"p95 {run.p95_duration_ms or 0:g} ms · errors {err:g}% · thresholds {run.threshold_result or 'Unknown'} · "
			f"run {run.name}")
	res = grafana.call("POST", "/api/annotations", {
		"time": _epoch_ms(start), "timeEnd": _epoch_ms(end), "text": text,
		"tags": [ANNOTATION_TAG, f"site:{frappe.local.site}", f"config:{run.config}", f"status:{run.status}"],
	})
	annotation_id = (res or {}).get("id")
	if annotation_id:
		frappe.db.set_value("Load Test Run", run.name, "grafana_annotation_id", annotation_id,
							update_modified=False)
	return annotation_id


def migrate_run_history(grafana):
	runs = frappe.get_all(
		"Load Test Run",
		filters={"grafana_annotation_id": 0, "status": ["in", ("Completed", "Failed", "Stopped")]},
		fields=["name", "config", "status", "started_at", "completed_at", "creation", "total_requests",
				"failed_requests", "p95_duration_ms", "threshold_result"],
		order_by="creation asc",
	)
	done = 0
	for run in runs:
		if annotate_run(grafana, run):
			done += 1
	frappe.db.commit()
	return done


def on_run_finished(run_name):
	"""Called after a run is finalised: annotate it and log the event, when cloud is enabled."""
	cfg = get_config()
	if not cloud_enabled(cfg):
		return
	run = frappe.get_doc("Load Test Run", run_name)
	if cfg.grafana_url and cfg.sa_token:
		try:
			annotate_run(client(cfg), run)
		except Exception as e:
			_note_error("annotate_run", e)
	log_event("run_finished", f"{run.config} {run.status}", run=run.name, config=run.config,
			  status=run.status, thresholds=run.threshold_result, total_requests=run.total_requests,
			  p95_ms=run.p95_duration_ms)


# ─── Orchestration (Monitor Settings buttons and bench commands) ─────────────

def _set_status(results):
	lines = [f"{k}: {v}" for k, v in results.items()]
	frappe.db.set_single_value("Monitor Settings", {
		"gc_status": "\n".join(lines)[:1000],
		"gc_last_sync": now_datetime(),
	})


def _step(results, name, fn):
	try:
		results[name] = fn()
		return True
	except Exception as e:
		results[name] = f"FAILED: {e}"
		return False


@frappe.whitelist()
def connect(import_dash=1, sync_alerts=1, migrate_history=1):
	"""
	One-click setup: discover endpoints, verify both tokens, switch the monitoring mode,
	import dashboards, provision the contact point and alert rules, migrate run history.
	"""
	frappe.only_for("System Manager")
	results = {}
	cfg = get_config()
	grafana = client(cfg)

	def _discover():
		found = discover(grafana)
		settings = frappe.get_single("Monitor Settings")
		for field, value in found.items():
			if value and not settings.get(field):
				settings.set(field, value)  # keep values the user set by hand
		ensure_default_cloud_rules(settings)
		if settings.monitoring_mode in (None, "", "Off"):
			settings.monitoring_mode = "Grafana Cloud"
		elif settings.monitoring_mode == "Self-hosted":
			settings.monitoring_mode = "Hybrid"  # keep the local stack while migrating
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		return f"Prometheus {settings.gc_prometheus_url}, Loki {settings.gc_loki_url or 'not found'}, mode {settings.monitoring_mode}"

	if not _step(results, "Discovery", _discover):
		_set_status(results)
		return results
	cfg = get_config()

	_step(results, "Metrics write", lambda: f"ok ({push_samples([('frappe_k6_connected', {}, 1)], cfg)} sample)")
	if cfg.loki_url:
		_step(results, "Logs write", lambda: f"ok ({push_logs(['frappe_k6 connected'], {'event': 'connected'}, cfg)} line)")
	if int(import_dash):
		_step(results, "Dashboards", lambda: f"{len(import_dashboards(grafana, cfg))} imported")
	if int(sync_alerts):
		_step(results, "Alerts", lambda: _sync_alerts(grafana, cfg))
	if int(migrate_history):
		_step(results, "Run history", lambda: f"{migrate_run_history(grafana)} runs annotated")
	if cfg.mode == "Hybrid":
		from frappe_k6.frappe_k6.prometheus_manager import sync_prometheus_config

		_step(results, "Local Prometheus", lambda: (sync_prometheus_config(), "forwarding to Grafana Cloud")[1])

	_set_status(results)
	frappe.db.commit()
	return results


def _sync_alerts(grafana, cfg):
	receiver = provision_contact_point(grafana)
	rules = provision_alert_rules(grafana, cfg, receiver)
	where = receiver or "the stack's default notification policy (no channels set)"
	return f"{len(rules)} rules → {where}"


@frappe.whitelist()
def sync_dashboards():
	frappe.only_for("System Manager")
	cfg = get_config()
	results = {}
	_step(results, "Dashboards", lambda: f"{len(import_dashboards(client(cfg), cfg))} imported")
	_set_status(results)
	return results


@frappe.whitelist()
def sync_alerts():
	frappe.only_for("System Manager")
	cfg = get_config()
	settings = frappe.get_single("Monitor Settings")
	if ensure_default_cloud_rules(settings):
		settings.save(ignore_permissions=True)
	results = {}
	_step(results, "Alerts", lambda: _sync_alerts(client(cfg), cfg))
	_set_status(results)
	return results


@frappe.whitelist()
def migrate_history():
	frappe.only_for("System Manager")
	results = {}
	_step(results, "Run history", lambda: f"{migrate_run_history(client())} runs annotated")
	_set_status(results)
	return results


@frappe.whitelist()
def test_connection():
	frappe.only_for("System Manager")
	cfg = get_config()
	results = {}
	def _grafana():
		grafana = client(cfg)
		grafana.call("GET", "/api/search?limit=1")  # 401 here means the token is wrong
		return f"ok, Grafana {grafana.call('GET', '/api/health').get('version', '?')}"

	_step(results, "Grafana API", _grafana)
	if cfg.prom_url:
		_step(results, "Metrics write", lambda: f"ok ({push_samples([('frappe_k6_connected', {}, 1)], cfg)} sample)")
	if cfg.loki_url:
		_step(results, "Logs write", lambda: f"ok ({push_logs(['frappe_k6 connection test'], {'event': 'test'}, cfg)} line)")
	_set_status(results)
	return results


# ─── Alloy agent config (optional: host metrics and logs) ────────────────────

def render_alloy_config(server_name, environment, bench_path, cfg=None):
	"""
	Grafana Alloy config that sends node metrics (as job="node", matching the bundled
	host dashboards) and bench logs to Grafana Cloud. Credentials are read from the
	GRAFANA_CLOUD_TOKEN environment variable, never written into the file.
	"""
	cfg = cfg or get_config()
	if not cfg.prom_url:
		raise GrafanaCloudError(_("Connect to Grafana Cloud first (Prometheus URL is not set)."))
	logs = ""
	if cfg.loki_url:
		logs = f'''
local.file_match "bench_logs" {{
  path_targets = [{{"__path__" = "{bench_path}/logs/*.log", "job" = "frappe_bench", "server_name" = "{server_name}", "env" = "{environment}", "site" = "{frappe.local.site}"}}]
}}

loki.source.file "bench_logs" {{
  targets    = local.file_match.bench_logs.targets
  forward_to = [loki.write.grafana_cloud.receiver]
}}

loki.write "grafana_cloud" {{
  endpoint {{
    url = "{loki_push_url(cfg.loki_url)}"
    basic_auth {{
      username = "{cfg.loki_user}"
      password = sys.env("GRAFANA_CLOUD_TOKEN")
    }}
  }}
}}
'''
	return f'''// Generated by frappe_k6 for {frappe.local.site}. Run Alloy with GRAFANA_CLOUD_TOKEN set
// to the Cloud access policy token (metrics:write, logs:write).

prometheus.exporter.unix "host" {{ }}

discovery.relabel "host" {{
  targets = prometheus.exporter.unix.host.targets

  rule {{
    target_label = "job"
    replacement  = "node"
  }}
  rule {{
    target_label = "server_name"
    replacement  = "{server_name}"
  }}
  rule {{
    target_label = "env"
    replacement  = "{environment}"
  }}
  rule {{
    target_label = "site"
    replacement  = "{frappe.local.site}"
  }}
}}

prometheus.scrape "host" {{
  targets         = discovery.relabel.host.output
  scrape_interval = "15s"
  forward_to      = [prometheus.remote_write.grafana_cloud.receiver]
}}

prometheus.remote_write "grafana_cloud" {{
  endpoint {{
    url = "{prom_push_url(cfg.prom_url)}"
    basic_auth {{
      username = "{cfg.prom_user}"
      password = sys.env("GRAFANA_CLOUD_TOKEN")
    }}
  }}
}}
{logs}'''

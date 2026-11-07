"""
Load test execution API — start, stop, status, history.

A run is executed by a background job (`execute_run`, long queue) that starts k6,
waits for it, and finalises the Load Test Run from k6's own end-of-test summary.
"""

import json
import os
import signal
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import now_datetime

from frappe_k6.security import (
	check_metrics_access,
	is_k6_manager,
	require_k6_manager,
	require_k6_user,
	validate_target_url,
)

TREND_STATS = "avg,min,med,max,p(90),p(95),p(99)"
LIVE_TAIL_BYTES = 4 * 1024 * 1024  # live view reads at most the last 4 MB of k6 JSON output
ACTIVE_STATUSES = ("Queued", "Running")


def _k6_bin():
	try:
		settings = frappe.get_single("Monitor Settings")
		return settings.k6_binary_path or "k6"
	except Exception:
		return "k6"


def _reports_dir():
	try:
		settings = frappe.get_single("Monitor Settings")
		if settings.k6_reports_dir and os.path.isdir(settings.k6_reports_dir):
			return settings.k6_reports_dir
	except Exception:
		pass
	app_root = os.path.abspath(
		os.path.join(os.path.dirname(__file__), "../..")  # api/ → frappe_k6(pkg) → frappe_k6(app)
	)
	reports = os.path.join(app_root, "k6_tests", "reports")
	os.makedirs(reports, exist_ok=True)
	return reports


def _stop_key(run_name):
	return f"frappe_k6:stop:{run_name}"


def _heartbeat_key(run_name):
	return f"frappe_k6:heartbeat:{run_name}"


@frappe.whitelist()
def start_load_test(config_name: str):
	"""
	Validate the config and target, create a queued Load Test Run and hand it to
	a background job. Supports remote server targets via Load Test Config.remote_server.
	"""
	from frappe_k6.api.k6_generator import build_run_data, total_duration_seconds

	require_k6_manager()
	cfg = frappe.get_doc("Load Test Config", config_name)

	# ── Resolve base URL and target server ───────────────────────
	remote_server_name = None
	target_server_label = "local"
	base_url = None

	if getattr(cfg, "target_type", "Local Server") == "Remote Server" and getattr(cfg, "remote_server", None):
		rs = frappe.get_doc("Remote Server", cfg.remote_server)
		remote_server_name = rs.name
		target_server_label = rs.server_name
		base_url = (
			getattr(cfg, "target_base_url", None)
			or getattr(rs, "frappe_url", None)
			or f"http://{rs.host}:8000"
		)
	else:
		base_url = getattr(cfg, "target_base_url", None)
		if not base_url:
			port = frappe.get_site_config().get("webserver_port", 8000)
			base_url = f"http://localhost:{port}"

	base_url = base_url.rstrip("/")
	validate_target_url(base_url)
	# Fail fast on bad endpoints or missing credentials, before anything is queued
	data = build_run_data(cfg)

	run = frappe.get_doc({
		"doctype":            "Load Test Run",
		"config":             config_name,
		"status":             "Queued",
		"scenario_type":      cfg.scenario_type,
		"remote_server":      remote_server_name,
		"target_server_name": target_server_label,
		"target_base_url":    base_url,
	})
	run.insert(ignore_permissions=True)

	frappe.db.set_value("Load Test Config", config_name, {
		"status":    "Running",
		"last_run":  run.name,
	})
	frappe.db.commit()

	frappe.enqueue(
		"frappe_k6.api.load_test.execute_run",
		queue="long",
		timeout=int(total_duration_seconds(data["stages"])) + 900,
		run_name=run.name,
		now=frappe.flags.in_test,
	)

	return {
		"run_name":      run.name,
		"status":        "Queued",
		"target_server": target_server_label,
		"base_url":      base_url,
	}


def execute_run(run_name: str):
	"""Background job: run k6 for one Load Test Run and finalise it."""
	from frappe_k6.api.k6_generator import RUNNER_SCRIPT, build_run_data, write_run_data

	run = frappe.get_doc("Load Test Run", run_name)
	if run.status != "Queued":
		return

	cfg = frappe.get_doc("Load Test Config", run.config)
	stem = os.path.join(
		_reports_dir(),
		f"{cfg.test_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
	)
	out_file     = stem + ".json"
	data_file    = stem + ".data.json"
	summary_file = stem + ".summary.json"
	log_file     = stem + ".log"

	write_run_data(build_run_data(cfg), data_file)

	cmd = [
		_k6_bin(), "run",
		"--out", f"json={out_file}",
		"--summary-export", summary_file,
		"--summary-trend-stats", TREND_STATS,
		"-e", f"K6_DATA={data_file}",
		"-e", f"K6_BASE_URL={run.target_base_url}",
		"-e", f"TARGET_SERVER={run.target_server_name or 'local'}",
	]
	env = dict(os.environ)
	cloud = _cloud_config()
	if cloud and cloud.native_k6:
		# k6's own metrics (k6_*) straight to Grafana Cloud; credentials via env, not argv
		from frappe_k6.grafana_cloud import prom_push_url

		cmd += ["-o", "experimental-prometheus-rw",
				"--tag", f"testid={run_name}", "--tag", f"site={frappe.local.site}",
				"--tag", f"config={run.config}"]
		env.update({
			"K6_PROMETHEUS_RW_SERVER_URL": prom_push_url(cloud.prom_url),
			"K6_PROMETHEUS_RW_TREND_STATS": "p(50),p(90),p(95),p(99),min,max,avg",
		})
		if cloud.prom_user and cloud.access_token:
			env["K6_PROMETHEUS_RW_USERNAME"] = cloud.prom_user
			env["K6_PROMETHEUS_RW_PASSWORD"] = cloud.access_token
	cmd.append(RUNNER_SCRIPT)

	try:
		with open(log_file, "w") as log_fd:
			proc = subprocess.Popen(
				cmd, stdout=log_fd, stderr=log_fd, start_new_session=True, close_fds=True, env=env
			)
	except OSError as exc:
		_remove_file(data_file)
		frappe.db.set_value("Load Test Run", run_name, {
			"status": "Failed",
			"completed_at": now_datetime(),
			"error_message": f"Could not start k6 ({cmd[0]}): {exc}",
		})
		frappe.db.set_value("Load Test Config", run.config, {"status": "Failed", "last_run_status": "Failed"})
		frappe.db.commit()
		return

	frappe.db.set_value("Load Test Run", run_name, {
		"status":       "Running",
		"started_at":   now_datetime(),
		"pid":          proc.pid,
		"runner_host":  socket.gethostname(),
		"output_file":  out_file,
		"data_file":    data_file,
		"summary_file": summary_file,
		"log_file":     log_file,
	})
	frappe.db.commit()

	if cloud:
		from frappe_k6.grafana_cloud import log_event

		log_event("run_started", f"{run.config} started", run=run_name, config=run.config,
				  target=run.target_base_url, scenario=run.scenario_type)

	cache = frappe.cache()
	stop_sent = False
	last_push = 0
	while proc.poll() is None:
		cache.set_value(_heartbeat_key(run_name), 1, expires_in_sec=30)
		if not stop_sent and cache.get_value(_stop_key(run_name)):
			_signal_group(proc.pid, signal.SIGINT)  # k6 stops gracefully and still writes the summary
			stop_sent = True
		if cloud and cloud.mode == "Grafana Cloud" and time.time() - last_push >= 10:
			_push_live_metrics(run, out_file, cloud)
			last_push = time.time()
		time.sleep(2)

	_finalize_run(run_name, exit_code=proc.returncode)


@frappe.whitelist()
def stop_load_test(run_name: str):
	"""Ask the runner to stop k6. Works across hosts through a cache flag."""
	require_k6_manager()
	run = frappe.get_doc("Load Test Run", run_name)

	if run.status == "Queued":
		frappe.db.set_value("Load Test Run", run_name, {"status": "Stopped", "completed_at": now_datetime()})
		frappe.db.set_value("Load Test Config", run.config, "status", "Ready")
		frappe.db.commit()
		return {"status": "stopped"}

	frappe.cache().set_value(_stop_key(run_name), 1, expires_in_sec=86400)
	if run.pid and run.runner_host == socket.gethostname():
		_signal_group(run.pid, signal.SIGINT)
	return {"status": "stopping"}


@frappe.whitelist()
def get_test_status(run_name: str):
	"""
	Live metrics while running (from the recent k6 JSON output),
	final metrics from the stored k6 summary once finished.
	"""
	require_k6_user()
	run = frappe.get_doc("Load Test Run", run_name)
	is_running = run.status in ACTIVE_STATUSES

	if is_running or not run.summary_json:
		metrics = _parse_k6_output(run.output_file)
	else:
		metrics = json.loads(run.summary_json)

	return {
		"run_name":           run_name,
		"status":             run.status,
		"is_running":         is_running,
		"metrics":            metrics,
		"threshold_result":   run.threshold_result,
		"started_at":         str(run.started_at or ""),
		"target_server_name": run.target_server_name or "local",
		"remote_server":      run.remote_server,
		"target_base_url":    run.target_base_url,
	}


@frappe.whitelist()
def get_active_runs():
	"""Return all queued or running tests. Read-only: finalising is the runner's job."""
	require_k6_user()
	return frappe.get_all(
		"Load Test Run",
		filters={"status": ["in", ACTIVE_STATUSES]},
		fields=["name", "config", "status", "started_at", "pid", "output_file"]
	)


@frappe.whitelist()
def get_run_history(limit=20):
	"""Return recent load test runs."""
	require_k6_user()
	return frappe.get_all(
		"Load Test Run",
		fields=["name", "config", "status", "started_at", "completed_at",
				"total_requests", "failed_requests", "requests_per_sec",
				"avg_duration_ms", "p95_duration_ms", "scenario_type",
				"remote_server", "target_server_name", "threshold_result", "exit_code"],
		order_by="creation desc",
		limit=int(limit)
	)


@frappe.whitelist()
def get_remote_servers():
	"""Return all enabled remote servers for the Test Builder dropdown."""
	require_k6_user()
	return frappe.get_all(
		"Remote Server",
		filters={"enabled": 1},
		fields=["name", "server_name", "host", "frappe_url", "environment"],
		order_by="server_name asc"
	)


@frappe.whitelist(allow_guest=True)
def get_active_run_metrics():
	"""
	Return live K6 metrics for all running tests.
	Called by frappe_k6_exporter (X-Frappe-K6-Token header) to expose to Prometheus.
	"""
	check_metrics_access()
	runs = frappe.get_all(
		"Load Test Run",
		filters={"status": "Running"},
		fields=["name", "config", "pid", "output_file", "runner_host",
				"target_server_name", "scenario_type"]
	)
	result = []
	for run_data in runs:
		if run_data.get("runner_host") != socket.gethostname():
			continue
		if not _is_process_running(run_data.get("pid")):
			continue
		try:
			result.append(_live_row(run_data, _parse_k6_output(run_data.get("output_file", ""))))
		except Exception as e:
			frappe.log_error(str(e), f"get_active_run_metrics: {run_data['name']}")
	return result


# live row key → Prometheus metric name (same names as frappe_k6_exporter and the dashboards)
RUN_METRIC_NAMES = {
	"rps": "frappe_k6_run_rps", "avg_ms": "frappe_k6_run_avg_ms", "min_ms": "frappe_k6_run_min_ms",
	"p50_ms": "frappe_k6_run_p50_ms", "p90_ms": "frappe_k6_run_p90_ms", "p95_ms": "frappe_k6_run_p95_ms",
	"p99_ms": "frappe_k6_run_p99_ms", "max_ms": "frappe_k6_run_max_ms", "ttfb_ms": "frappe_k6_run_ttfb_ms",
	"ttfb_p95_ms": "frappe_k6_run_ttfb_p95_ms", "blocked_ms": "frappe_k6_run_blocked_ms",
	"connecting_ms": "frappe_k6_run_connecting_ms", "sending_ms": "frappe_k6_run_sending_ms",
	"receiving_ms": "frappe_k6_run_receiving_ms", "error_rate": "frappe_k6_run_error_rate",
	"failed_requests": "frappe_k6_run_failed", "status_2xx": "frappe_k6_run_status_2xx",
	"status_3xx": "frappe_k6_run_status_3xx", "status_4xx": "frappe_k6_run_status_4xx",
	"status_5xx": "frappe_k6_run_status_5xx", "vus": "frappe_k6_run_vus", "max_vus": "frappe_k6_run_max_vus",
	"total_requests": "frappe_k6_run_requests", "iterations": "frappe_k6_run_iterations",
	"checks_passed": "frappe_k6_run_checks_passed", "checks_failed": "frappe_k6_run_checks_failed",
	"data_recv_kb": "frappe_k6_run_data_recv_kb", "data_sent_kb": "frappe_k6_run_data_sent_kb",
}


def _live_row(run_data, metrics):
	dur  = metrics.get("http_req_duration", {})
	wait = metrics.get("http_req_waiting", {})
	vus  = metrics.get("vus", {})
	return {
		"run_name":        run_data["name"],
		"config":          run_data["config"],
		"target_server":   run_data.get("target_server_name") or "local",
		"scenario_type":   run_data.get("scenario_type") or "load",
		"rps":             metrics.get("rps", 0),
		"avg_ms":          dur.get("avg", 0),
		"min_ms":          dur.get("min", 0),
		"p50_ms":          dur.get("p50", 0),
		"p90_ms":          dur.get("p90", 0),
		"p95_ms":          dur.get("p95", 0),
		"p99_ms":          dur.get("p99", 0),
		"max_ms":          dur.get("max", 0),
		"ttfb_ms":         wait.get("avg", 0),
		"ttfb_p95_ms":     wait.get("p95", 0),
		"blocked_ms":      metrics.get("http_req_blocked", {}).get("avg", 0),
		"connecting_ms":   metrics.get("http_req_connecting", {}).get("avg", 0),
		"sending_ms":      metrics.get("http_req_sending", {}).get("avg", 0),
		"receiving_ms":    metrics.get("http_req_receiving", {}).get("avg", 0),
		"error_rate":      metrics.get("error_rate", 0),
		"vus":             vus.get("current", 0),
		"max_vus":         vus.get("max", 0),
		"total_requests":  metrics.get("http_reqs", {}).get("count", 0),
		"failed_requests": metrics.get("http_req_failed", {}).get("count", 0),
		"checks_passed":   metrics.get("checks_passed", 0),
		"checks_failed":   metrics.get("checks_failed", 0),
		"iterations":      metrics.get("iterations", 0),
		"data_recv_kb":    metrics.get("data_received_kb", 0),
		"data_sent_kb":    metrics.get("data_sent_kb", 0),
		"status_2xx":      metrics.get("status_2xx", 0),
		"status_3xx":      metrics.get("status_3xx", 0),
		"status_4xx":      metrics.get("status_4xx", 0),
		"status_5xx":      metrics.get("status_5xx", 0),
	}


def _cloud_config():
	"""Grafana Cloud settings when cloud mode is on, else None. Never raises."""
	try:
		from frappe_k6.grafana_cloud import cloud_enabled, get_config

		cfg = get_config()
		return cfg if cloud_enabled(cfg) else None
	except Exception:
		return None


def _push_live_metrics(run, out_file, cloud):
	from frappe_k6.grafana_cloud import _note_error, push_samples

	try:
		row = _live_row(
			{"name": run.name, "config": run.config, "target_server_name": run.target_server_name,
			 "scenario_type": run.scenario_type},
			_parse_k6_output(out_file),
		)
		labels = {"config": row["config"], "target_server": row["target_server"],
				  "scenario": row["scenario_type"]}
		push_samples([(metric, labels, row[key]) for key, metric in RUN_METRIC_NAMES.items()], cloud)
	except Exception as e:
		_note_error("push_live_metrics", e)


@frappe.whitelist()
def get_remote_server_live_metrics(server_name: str):
	"""
	Query Prometheus for live OS metrics of a remote server.
	Uses node_exporter metrics filtered by server_name label.
	"""
	require_k6_user()
	try:
		settings = frappe.get_single("Monitor Settings")
		prom_url = (settings.prometheus_url or "http://localhost:9090").rstrip("/")
	except Exception:
		prom_url = "http://localhost:9090"

	sn = server_name.replace('"', '')
	queries = {
		"cpu_percent": (
			f'100 - (avg(irate(node_cpu_seconds_total{{mode="idle",server_name="{sn}"}}[2m])) * 100)'
		),
		"memory_percent": (
			f'(1 - (node_memory_MemAvailable_bytes{{server_name="{sn}"}}'
			f' / node_memory_MemTotal_bytes{{server_name="{sn}"}})) * 100'
		),
		"disk_percent": (
			f'(1 - node_filesystem_avail_bytes{{server_name="{sn}",mountpoint="/",fstype!="tmpfs"}}'
			f' / node_filesystem_size_bytes{{server_name="{sn}",mountpoint="/",fstype!="tmpfs"}}) * 100'
		),
		"network_rx_kbps": (
			f'irate(node_network_receive_bytes_total{{server_name="{sn}",device!~"lo"}}[2m]) / 1024'
		),
		"network_tx_kbps": (
			f'irate(node_network_transmit_bytes_total{{server_name="{sn}",device!~"lo"}}[2m]) / 1024'
		),
		"load_avg_1m": f'node_load1{{server_name="{sn}"}}',
	}

	result = {}
	for key, query in queries.items():
		try:
			url = f"{prom_url}/api/v1/query?query={urllib.parse.quote(query)}"
			req = urllib.request.Request(url)
			with urllib.request.urlopen(req, timeout=5) as resp:
				data = json.loads(resp.read())
			res = data.get("data", {}).get("result", [])
			if res:
				result[key] = round(float(res[0]["value"][1]), 2)
			else:
				result[key] = None
		except Exception:
			result[key] = None

	return result


@frappe.whitelist()
def save_config(config_name, test_scenario="load", virtual_users=10, duration="5m",
				ramp_up="1m", ramp_down="30s", max_vus=100, think_time=1.0,
				endpoints=None, target_type="Local Server", remote_server=None,
				target_base_url=None):
	"""Create or update a Load Test Config from the builder form."""
	require_k6_manager()

	if isinstance(endpoints, str):
		endpoints = json.loads(endpoints)
	endpoints = endpoints or []

	if target_base_url:
		validate_target_url(target_base_url)

	exists = frappe.db.exists("Load Test Config", config_name)
	old_secrets = {}
	if exists:
		doc = frappe.get_doc("Load Test Config", config_name)
		# Rows are rebuilt below; keep stored secrets for rows sent back masked
		old_secrets = {
			(ep.api_name, ep.endpoint_url): ep.get_password("auth_value", raise_exception=False) or ""
			for ep in doc.endpoints
		}
		doc.endpoints = []
	else:
		doc = frappe.get_doc({
			"doctype":   "Load Test Config",
			"test_name": config_name,
		})

	doc.update({
		"scenario_type":  test_scenario,
		"virtual_users":  int(virtual_users),
		"duration":       duration,
		"ramp_up_time":   ramp_up,
		"ramp_down_time": ramp_down,
		"max_vus":        int(max_vus),
		"think_time":     float(think_time),
		"status":         "Ready",
		"target_type":    target_type or "Local Server",
		"remote_server":  remote_server or None,
		"target_base_url": target_base_url or None,
	})

	for ep in endpoints:
		api_name = ep.get("api_name") or ep.get("endpoint_label") or ep.get("endpoint_url", "")
		endpoint_url = ep.get("endpoint_url") or ep.get("api_path", "")
		auth_value = ep.get("auth_value", "")
		if auth_value and set(auth_value) == {"*"}:
			auth_value = old_secrets.get((api_name, endpoint_url), "")
		doc.append("endpoints", {
			"doctype":         "Load Test Endpoint",
			"api_name":        api_name,
			"http_method":     ep.get("http_method", "GET"),
			"endpoint_url":    endpoint_url,
			"expected_status": int(ep.get("expected_status", 200)),
			"weight":          int(ep.get("weight", 1)),
			"auth_type":       ep.get("auth_type", "None"),
			"auth_value":      auth_value,
			"headers":         ep.get("headers", ""),
			"query_params":    ep.get("query_params", ""),
			"payload":         ep.get("payload", ""),
		})

	if exists:
		doc.save()
	else:
		doc.insert()
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def get_configs():
	"""Return all load test configs for the builder."""
	require_k6_user()
	return frappe.get_all(
		"Load Test Config",
		fields=["name", "test_name", "scenario_type", "virtual_users",
				"duration", "status", "last_run", "last_run_status",
				"target_type", "remote_server"],
		order_by="modified desc"
	)


@frappe.whitelist()
def get_config(config_name: str):
	"""Return full config doc including all endpoint fields. Secrets only for managers."""
	require_k6_user()
	doc = frappe.get_doc("Load Test Config", config_name)
	show_secrets = is_k6_manager()
	eps = []
	for ep in doc.endpoints:
		eps.append({
			"api_name":        ep.api_name,
			"http_method":     ep.http_method,
			"endpoint_url":    ep.endpoint_url,
			"expected_status": ep.expected_status,
			"weight":          ep.weight,
			"auth_type":       ep.auth_type or "None",
			"auth_value":      (ep.get_password("auth_value", raise_exception=False) or "")
							   if show_secrets else (ep.auth_value or ""),
			"headers":         ep.headers or "",
			"query_params":    ep.query_params or "",
			"payload":         ep.payload or "",
		})
	return {
		"name":            doc.name,
		"test_name":       doc.test_name,
		"scenario_type":   doc.scenario_type,
		"virtual_users":   doc.virtual_users,
		"duration":        doc.duration,
		"ramp_up_time":    doc.ramp_up_time,
		"ramp_down_time":  doc.ramp_down_time,
		"max_vus":         doc.max_vus,
		"think_time":      doc.think_time,
		"target_type":     getattr(doc, "target_type", "Local Server") or "Local Server",
		"remote_server":   getattr(doc, "remote_server", None) or None,
		"target_base_url": getattr(doc, "target_base_url", None) or None,
		"endpoints":       eps,
	}


# ── Internal helpers ────────────────────────────────────────────

def _is_process_running(pid) -> bool:
	if not pid:
		return False
	try:
		os.kill(int(pid), 0)
		return True
	except (ProcessLookupError, OSError):
		return False


def _signal_group(pid, sig):
	try:
		os.killpg(os.getpgid(int(pid)), sig)
	except ProcessLookupError:
		pass
	except Exception as e:
		frappe.log_error(str(e), "frappe_k6: signal k6")


def _remove_file(path):
	if path and os.path.exists(path):
		try:
			os.remove(path)
		except OSError:
			pass


def _tail_lines(path, max_bytes=LIVE_TAIL_BYTES):
	"""Return the complete lines in the last `max_bytes` of a file, without reading the rest."""
	with open(path, "rb") as f:
		f.seek(0, os.SEEK_END)
		size = f.tell()
		start = max(0, size - max_bytes)
		f.seek(start)
		chunk = f.read()
	lines = chunk.decode("utf-8", errors="replace").splitlines()
	if start > 0 and lines:
		lines = lines[1:]  # first line is probably cut in half
	return lines


def _parse_k6_output(output_file: str) -> dict:
	"""
	Parse the recent tail of k6 JSON Lines output for the live view.
	Final results come from the k6 summary instead (see `_summary_metrics`).
	"""
	metrics = {
		"http_req_duration": {"values": [], "avg": 0, "min": 0, "p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0},
		"http_req_waiting":  {"avg": 0, "p95": 0},
		"http_req_blocked":  {"avg": 0},
		"http_req_connecting": {"avg": 0},
		"http_req_sending":  {"avg": 0},
		"http_req_receiving": {"avg": 0},
		"http_reqs":         {"count": 0},
		"http_req_failed":   {"count": 0, "rate": 0},
		"vus":               {"current": 0, "max": 0},
		"data_received_kb":  0,
		"data_sent_kb":      0,
		"checks_passed":     0,
		"checks_failed":     0,
		"iterations":        0,
		"status_2xx":        0,
		"status_3xx":        0,
		"status_4xx":        0,
		"status_5xx":        0,
		"rps":               0,
		"error_rate":        0,
		"timeline":          [],
	}

	if not output_file or not os.path.exists(output_file):
		return metrics

	try:
		durations   = []
		waitings    = []
		blockeds    = []
		connectings = []
		sendings    = []
		receivings  = []
		total_req = 0
		failed_req = 0
		current_vus = 0
		max_vus = 0
		data_recv = 0
		data_sent = 0
		checks_pass = 0
		checks_fail = 0
		iterations = 0
		status_2xx = status_3xx = status_4xx = status_5xx = 0
		timeline_buckets = {}

		for line in _tail_lines(output_file):
			line = line.strip()
			if not line:
				continue
			try:
				obj = json.loads(line)
			except json.JSONDecodeError:
				continue

			if obj.get("type") != "Point":
				continue

			metric = obj.get("metric", "")
			data   = obj.get("data", {})
			value  = data.get("value", 0)
			ts_str = data.get("time", "")
			tags   = data.get("tags", {})

			if metric == "http_req_duration":
				durations.append(value)
				# Status code distribution from tags
				status = str(tags.get("status", "0"))
				if status.startswith("2"):
					status_2xx += 1
				elif status.startswith("3"):
					status_3xx += 1
				elif status.startswith("4"):
					status_4xx += 1
				elif status.startswith("5"):
					status_5xx += 1
				# Build timeline (group by second)
				if ts_str:
					bucket = ts_str[:19]
					if bucket not in timeline_buckets:
						timeline_buckets[bucket] = {"count": 0, "total": 0}
					timeline_buckets[bucket]["count"] += 1
					timeline_buckets[bucket]["total"] += value

			elif metric == "http_req_waiting":
				waitings.append(value)

			elif metric == "http_req_blocked":
				if value > 0:
					blockeds.append(value)

			elif metric == "http_req_connecting":
				if value > 0:
					connectings.append(value)

			elif metric == "http_req_sending":
				sendings.append(value)

			elif metric == "http_req_receiving":
				receivings.append(value)

			elif metric == "http_reqs":
				total_req += 1

			elif metric == "http_req_failed":
				if value == 1:
					failed_req += 1

			elif metric == "vus":
				current_vus = int(value)
				max_vus = max(max_vus, current_vus)

			elif metric == "data_received":
				data_recv += value

			elif metric == "data_sent":
				data_sent += value

			elif metric == "checks":
				if value == 1:
					checks_pass += 1
				else:
					checks_fail += 1

			elif metric == "iterations":
				iterations += 1

		def _percentile(lst, pct):
			if not lst:
				return 0
			s = sorted(lst)
			return round(s[min(len(s) - 1, int(len(s) * pct))], 2)

		def _avg(lst):
			return round(sum(lst) / len(lst), 2) if lst else 0

		if durations:
			durations.sort()
			metrics["http_req_duration"].update({
				"avg": _avg(durations),
				"min": round(durations[0], 2),
				"p50": _percentile(durations, 0.50),
				"p90": _percentile(durations, 0.90),
				"p95": _percentile(durations, 0.95),
				"p99": _percentile(durations, 0.99),
				"max": round(durations[-1], 2),
			})

		metrics["http_req_waiting"].update({"avg": _avg(waitings), "p95": _percentile(waitings, 0.95)})
		metrics["http_req_blocked"]["avg"]    = _avg(blockeds)
		metrics["http_req_connecting"]["avg"] = _avg(connectings)
		metrics["http_req_sending"]["avg"]    = _avg(sendings)
		metrics["http_req_receiving"]["avg"]  = _avg(receivings)

		metrics["http_reqs"]["count"]       = total_req
		metrics["http_req_failed"]["count"] = failed_req
		metrics["http_req_failed"]["rate"]  = round(failed_req / total_req * 100, 2) if total_req else 0
		metrics["vus"]["current"]           = current_vus
		metrics["vus"]["max"]               = max_vus
		metrics["data_received_kb"]         = round(data_recv / 1024, 2)
		metrics["data_sent_kb"]             = round(data_sent / 1024, 2)
		metrics["checks_passed"]            = checks_pass
		metrics["checks_failed"]            = checks_fail
		metrics["iterations"]               = iterations
		metrics["status_2xx"]               = status_2xx
		metrics["status_3xx"]               = status_3xx
		metrics["status_4xx"]               = status_4xx
		metrics["status_5xx"]               = status_5xx
		metrics["error_rate"]               = round(failed_req / total_req * 100, 2) if total_req else 0

		# Timeline for chart (last 60 buckets)
		sorted_buckets = sorted(timeline_buckets.items())[-60:]
		metrics["timeline"] = [
			{
				"time":    k,
				"rps":     round(v["count"], 1),
				"avg_ms":  round(v["total"] / v["count"], 1) if v["count"] else 0,
			}
			for k, v in sorted_buckets
		]

		# Compute RPS from recent timeline buckets
		if len(metrics["timeline"]) > 1:
			recent = metrics["timeline"][-10:]
			metrics["rps"] = round(sum(b["rps"] for b in recent) / len(recent), 2)

	except Exception as e:
		frappe.log_error(str(e), "k6 parse error")

	return metrics


def _read_summary(path):
	if not path or not os.path.exists(path):
		return None
	try:
		with open(path) as f:
			return json.load(f)
	except (OSError, ValueError):
		return None


def _summary_metrics(summary: dict, live: dict) -> dict:
	"""
	Map k6's `--summary-export` JSON (whole run) onto the metrics dict the UI uses.
	Status-code counts and the timeline are not in the summary; they come from the live tail.
	"""
	m = summary.get("metrics", {})

	def trend(name):
		return m.get(name, {})

	def r2(v):
		return round(float(v or 0), 2)

	dur = trend("http_req_duration")
	failed = m.get("http_req_failed", {})
	checks = m.get("checks", {})
	vus_max = m.get("vus_max", {})

	metrics = dict(live)
	metrics.update({
		"http_req_duration": {
			"avg": r2(dur.get("avg")), "min": r2(dur.get("min")), "p50": r2(dur.get("med")),
			"p90": r2(dur.get("p(90)")), "p95": r2(dur.get("p(95)")), "p99": r2(dur.get("p(99)")),
			"max": r2(dur.get("max")),
		},
		"http_req_waiting":    {"avg": r2(trend("http_req_waiting").get("avg")),
								"p95": r2(trend("http_req_waiting").get("p(95)"))},
		"http_req_blocked":    {"avg": r2(trend("http_req_blocked").get("avg"))},
		"http_req_connecting": {"avg": r2(trend("http_req_connecting").get("avg"))},
		"http_req_sending":    {"avg": r2(trend("http_req_sending").get("avg"))},
		"http_req_receiving":  {"avg": r2(trend("http_req_receiving").get("avg"))},
		"http_reqs":           {"count": int(m.get("http_reqs", {}).get("count", 0))},
		# For a Rate metric, "passes" counts true values — failed requests here
		"http_req_failed":     {"count": int(failed.get("passes", 0)),
								"rate": r2(float(failed.get("value", 0)) * 100)},
		"vus":                 {"current": 0, "max": int(vus_max.get("max") or vus_max.get("value") or 0)},
		"data_received_kb":    r2(m.get("data_received", {}).get("count", 0) / 1024),
		"data_sent_kb":        r2(m.get("data_sent", {}).get("count", 0) / 1024),
		"checks_passed":       int(checks.get("passes", 0)),
		"checks_failed":       int(checks.get("fails", 0)),
		"iterations":          int(m.get("iterations", {}).get("count", 0)),
		"rps":                 r2(m.get("http_reqs", {}).get("rate", 0)),
		"error_rate":          r2(float(failed.get("value", 0)) * 100),
		"source":              "k6 end-of-test summary",
		"status_counts_scope": "recent window of the JSON output",
	})
	return metrics


def _threshold_result(summary, exit_code):
	"""Passed / Failed / Unknown. In the summary export, a threshold value of true means it failed."""
	if exit_code == 99:
		return "Failed"
	if not summary:
		return "Unknown"
	flags = [
		failed
		for metric in summary.get("metrics", {}).values()
		for failed in (metric.get("thresholds") or {}).values()
	]
	if not flags:
		return "Unknown"
	return "Failed" if any(flags) else "Passed"


def _finalize_run(run_name: str, exit_code=None):
	"""Persist final metrics to the Load Test Run. Idempotent; first caller wins."""
	status = frappe.db.get_value("Load Test Run", run_name, "status", for_update=True)
	if status not in ACTIVE_STATUSES:
		return

	run = frappe.get_doc("Load Test Run", run_name)
	cache = frappe.cache()
	stopped = bool(cache.get_value(_stop_key(run_name)))

	live = _parse_k6_output(run.output_file)
	summary = _read_summary(run.summary_file)
	metrics = _summary_metrics(summary, live) if summary else live
	threshold_result = _threshold_result(summary, exit_code)

	error_message = None
	if stopped:
		final_status = "Stopped"
	elif exit_code not in (None, 0, 99):
		final_status = "Failed"
		error_message = f"k6 exited with code {exit_code}; see {run.log_file}"
	elif threshold_result == "Failed":
		final_status = "Failed"
		error_message = "One or more k6 thresholds failed"
	elif not summary:
		final_status = "Failed"
		error_message = "No k6 summary was written (runner lost or k6 crashed)"
	else:
		final_status = "Completed"

	d = metrics.get("http_req_duration", {})
	values = {"exit_code": exit_code} if exit_code is not None else {}  # Int column is NOT NULL
	try:
		frappe.db.set_value("Load Test Run", run_name, {
			**values,
			"status":           final_status,
			"completed_at":     now_datetime(),
			"threshold_result": threshold_result,
			"error_message":    error_message,
			"total_requests":   metrics.get("http_reqs", {}).get("count", 0),
			"failed_requests":  metrics.get("http_req_failed", {}).get("count", 0),
			"requests_per_sec": metrics.get("rps", 0),
			"avg_duration_ms":  d.get("avg", 0),
			"p95_duration_ms":  d.get("p95", 0),
			"p99_duration_ms":  d.get("p99", 0),
			"summary_json":     json.dumps(metrics, indent=2),
		})
		frappe.db.set_value("Load Test Config", run.config, {
			"status":          "Ready" if final_status == "Stopped" else final_status,
			"last_run_status": final_status,
		})
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(str(e), "finalize_run")
	finally:
		_remove_file(run.data_file)  # holds credentials
		cache.delete_value(_stop_key(run_name))
		cache.delete_value(_heartbeat_key(run_name))

	_after_finish(run_name)


def _after_finish(run_name):
	"""Alerts and Grafana Cloud annotation for a finished run. Failures never affect the run."""
	try:
		from frappe_k6.alerts import evaluate_run

		evaluate_run(run_name)
	except Exception as e:
		frappe.log_error(str(e), f"frappe_k6 alerts: {run_name}")
	try:
		from frappe_k6.grafana_cloud import on_run_finished

		on_run_finished(run_name)
	except Exception as e:
		frappe.log_error(str(e), f"frappe_k6 Grafana Cloud: {run_name}")

"""
Alerts on finished load-test runs (K6 Alert Rule → K6 Alert) and notification delivery.

Channels come from Monitor Settings → Alerts and Notifications, the same ones the
Grafana contact point uses: email, Slack, Microsoft Teams, a generic webhook. Users
with the K6 Manager role always get an in-app notification.
"""

import json
import urllib.request

import frappe
from frappe import _
from frappe.utils import flt, get_url_to_form

from frappe_k6.security import K6_MANAGER, safe_urlopen

# metric → (value from a Load Test Run row, True if higher is worse)
METRICS = {
	"P95 latency (ms)":     (lambda r: flt(r.p95_duration_ms), True),
	"P99 latency (ms)":     (lambda r: flt(r.p99_duration_ms), True),
	"Average latency (ms)": (lambda r: flt(r.avg_duration_ms), True),
	"Error rate (%)":       (lambda r: flt(r.failed_requests) / r.total_requests * 100 if r.total_requests else 0, True),
	"Requests per second":  (lambda r: flt(r.requests_per_sec), False),
	"Thresholds failed":    (lambda r: 1 if r.threshold_result == "Failed" else 0, True),
	# k6 errors and crashes only; threshold failures have their own metric
	"Run failed":           (lambda r: 1 if r.status == "Failed" and r.threshold_result != "Failed" else 0, True),
}
BASELINE_METRICS = ("P95 latency (ms)", "P99 latency (ms)", "Average latency (ms)", "Error rate (%)",
					"Requests per second")
RUN_FIELDS = ["name", "config", "status", "threshold_result", "total_requests", "failed_requests",
			  "requests_per_sec", "avg_duration_ms", "p95_duration_ms", "p99_duration_ms", "completed_at"]

OPERATORS = {
	">":  lambda a, b: a > b,
	">=": lambda a, b: a >= b,
	"<":  lambda a, b: a < b,
	"<=": lambda a, b: a <= b,
}

DEFAULT_RULES = (
	{"rule_name": "Thresholds failed", "metric": "Thresholds failed", "operator": ">", "value": 0,
	 "severity": "critical"},
	{"rule_name": "Run failed", "metric": "Run failed", "operator": ">", "value": 0, "severity": "critical"},
	{"rule_name": "P95 latency regression", "metric": "P95 latency (ms)", "compare_to_baseline": 1,
	 "value": 25, "baseline_runs": 5, "severity": "warning"},
)


def ensure_default_rules():
	for rule in DEFAULT_RULES:
		if not frappe.db.exists("K6 Alert Rule", rule["rule_name"]):
			frappe.get_doc({"doctype": "K6 Alert Rule", "enabled": 1, **rule}).insert(ignore_permissions=True)


# ─── Evaluation ──────────────────────────────────────────────────────────────

def _baseline(rule, run):
	previous = frappe.get_all(
		"Load Test Run",
		filters={"config": run.config, "status": "Completed", "name": ["!=", run.name],
				 "completed_at": ["<", run.completed_at]},
		fields=RUN_FIELDS, order_by="completed_at desc", limit=int(rule.baseline_runs or 5),
	)
	if not previous:
		return None
	value_of = METRICS[rule.metric][0]
	return sum(value_of(r) for r in previous) / len(previous)


def check_rule(rule, run):
	"""Return (fired, actual, limit) for one rule against one run row."""
	value_of, higher_is_worse = METRICS[rule.metric]
	actual = value_of(run)

	if rule.compare_to_baseline and rule.metric in BASELINE_METRICS:
		base = _baseline(rule, run)
		if not base:
			return False, actual, None
		pct = flt(rule.value) / 100
		limit = base * (1 + pct) if higher_is_worse else base * (1 - pct)
		fired = actual > limit if higher_is_worse else actual < limit
		return fired, actual, limit

	limit = flt(rule.value)
	return OPERATORS.get(rule.operator or ">", OPERATORS[">"])(actual, limit), actual, limit


def evaluate_run(run_name):
	"""Check every enabled K6 Alert Rule against a finished run; create and send alerts."""
	run = frappe.db.get_value("Load Test Run", run_name, RUN_FIELDS, as_dict=True)
	if not run:
		return []
	rules = frappe.get_all(
		"K6 Alert Rule", filters={"enabled": 1},
		fields=["name", "metric", "operator", "value", "compare_to_baseline", "baseline_runs",
				"severity", "load_test_config"],
	)
	alerts = []
	for rule in rules:
		if rule.load_test_config and rule.load_test_config != run.config:
			continue
		fired, actual, limit = check_rule(rule, run)
		if not fired:
			continue
		if rule.compare_to_baseline:
			detail = f"{rule.metric} {actual:g} vs limit {limit:g} ({flt(rule.value):g}% from the baseline)"
		else:
			detail = f"{rule.metric} {actual:g} {rule.operator} {limit:g}"
		subject = f"[{(rule.severity or 'warning').upper()}] {rule.name}: {run.config}"
		message = f"{detail}. Run {run.name} ended {run.status} (thresholds {run.threshold_result or 'Unknown'})."
		alert = frappe.get_doc({
			"doctype": "K6 Alert", "alert_rule": rule.name, "load_test_run": run.name,
			"load_test_config": run.config, "severity": rule.severity, "metric": rule.metric,
			"actual_value": actual, "limit_value": limit or 0, "message": message,
		}).insert(ignore_permissions=True)
		delivery = notify(subject, message, {
			"rule": rule.name, "severity": rule.severity, "run": run.name, "config": run.config,
			"metric": rule.metric, "actual": actual, "limit": limit, "status": run.status,
			"thresholds": run.threshold_result, "site": frappe.local.site,
			"url": get_url_to_form("Load Test Run", run.name),
		}, reference=("Load Test Run", run.name))
		alert.db_set("delivery", "\n".join(f"{k}: {v}" for k, v in delivery.items()))
		alerts.append(alert.name)
	frappe.db.commit()
	return alerts


# ─── Delivery ────────────────────────────────────────────────────────────────

def _post_json(url, payload):
	req = urllib.request.Request(
		url, data=json.dumps(payload, default=str).encode(),
		headers={"Content-Type": "application/json", "User-Agent": "frappe_k6"}, method="POST",
	)
	with safe_urlopen(req, timeout=15) as resp:
		return resp.status


def _k6_managers():
	users = set(frappe.get_all("Has Role", filters={"role": K6_MANAGER, "parenttype": "User"}, pluck="parent"))
	users.add("Administrator")
	return [u for u in users if frappe.db.get_value("User", u, "enabled")]


def notify(subject, message, payload, reference=None):
	"""Send to every configured channel. Returns {channel: result}; never raises."""
	from frappe_k6.grafana_cloud import log_event, notification_channels

	results = {}
	channels = notification_channels()
	link = payload.get("url", "")

	def attempt(name, fn):
		try:
			results[name] = fn() or "sent"
		except Exception as e:
			results[name] = f"failed: {e}"

	if "email" in channels:
		attempt("email", lambda: frappe.sendmail(
			recipients=channels["email"], subject=subject,
			message=f"<p>{frappe.utils.escape_html(message)}</p><p><a href='{link}'>{link}</a></p>",
			reference_doctype=reference[0] if reference else None,
			reference_name=reference[1] if reference else None,
		) or "queued (needs an outgoing Email Account)")
	if "slack" in channels:
		attempt("slack", lambda: _post_json(channels["slack"], {"text": f"*{subject}*\n{message}\n{link}"}) and None)
	if "teams" in channels:
		attempt("teams", lambda: _post_json(channels["teams"], {"text": f"**{subject}**\n\n{message}\n\n{link}"}) and None)
	if "webhook" in channels:
		attempt("webhook", lambda: _post_json(channels["webhook"], {"subject": subject, "message": message, **payload}) and None)

	def in_app():
		for user in _k6_managers():
			frappe.get_doc({
				"doctype": "Notification Log", "subject": subject, "email_content": message,
				"for_user": user, "type": "Alert",
				"document_type": reference[0] if reference else None,
				"document_name": reference[1] if reference else None,
			}).insert(ignore_permissions=True)
		return f"{len(_k6_managers())} user(s)"

	attempt("in-app", in_app)
	log_event("alert", subject, **{k: v for k, v in payload.items() if k != "url"})
	return results


@frappe.whitelist()
def send_test_alert():
	"""Send a test message to every configured channel (Monitor Settings button)."""
	frappe.only_for(("System Manager", K6_MANAGER))
	results = notify(
		"[TEST] frappe_k6 alert channel check",
		f"Test alert from {frappe.local.site}. If you can read this, the channel works.",
		{"rule": "test", "severity": "info", "site": frappe.local.site, "url": frappe.utils.get_url("/k6-monitor")},
	)
	frappe.db.commit()
	return results

"""
Builds the JSON data file that drives the fixed k6 runner script
(`frappe_k6/k6_runner/frappe_k6_runner.js`) from a Load Test Config document.

No JavaScript is generated: user input only ever reaches k6 as JSON data.
"""

import base64
import json
import os
import re

import frappe
from frappe import _

RUNNER_SCRIPT = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "k6_runner", "frappe_k6_runner.js"
)

DEFAULT_THRESHOLDS = {
	"http_req_failed": ["rate<0.10"],
	"http_req_duration": ["p(95)<5000"],
	"frappe_api_errors": ["rate<0.10"],
}

_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")


def duration_seconds(value) -> float:
	"""Parse a k6 duration such as '1m30s' into seconds."""
	units = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
	return sum(float(n) * units[u] for n, u in _DURATION_RE.findall(str(value or "")))


def total_duration_seconds(stages) -> float:
	return sum(duration_seconds(s["duration"]) for s in stages)


def build_run_data(cfg) -> dict:
	"""Return the runner input for a Load Test Config document."""
	stages = _build_stages(cfg)
	data = {
		"test_name": cfg.test_name,
		"stages": stages,
		"thresholds": DEFAULT_THRESHOLDS,
		"think_time": float(cfg.think_time or 1.0),
		"login": None,
		"endpoints": [],
	}

	for ep in cfg.endpoints:
		auth = ep.auth_type or "None"
		secret = _endpoint_secret(ep)
		if auth == "Session (Frappe Login)" and data["login"] is None:
			usr, _sep, pwd = (secret or "").partition(":")
			if not usr or not pwd:
				frappe.throw(
					_("Endpoint {0} uses Session login but has no 'user:password' credentials").format(
						ep.api_name or ep.endpoint_url
					)
				)
			data["login"] = {"usr": usr, "pwd": pwd}
		data["endpoints"].append(_endpoint_data(ep, secret))

	return data


def write_run_data(data: dict, path: str) -> str:
	"""Write the data file readable only by the bench user (it may hold credentials)."""
	fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
	with os.fdopen(fd, "w") as f:
		json.dump(data, f)
	return path


def _endpoint_secret(ep):
	if not ep.auth_value:
		return ""
	if ep.name:
		return ep.get_password("auth_value", raise_exception=False) or ""
	return ep.auth_value


def _build_stages(cfg) -> list:
	scenario = cfg.scenario_type or "load"
	vus      = int(cfg.virtual_users or 10)
	duration = cfg.duration or "5m"
	ramp_up  = cfg.ramp_up_time or "1m"
	ramp_dn  = cfg.ramp_down_time or "30s"
	max_vus  = int(cfg.max_vus or vus * 3)

	presets = {
		"smoke":  [
			{"duration": "1m", "target": min(vus, 2)},
		],
		"load":   [
			{"duration": ramp_up,  "target": vus},
			{"duration": duration, "target": vus},
			{"duration": ramp_dn,  "target": 0},
		],
		"stress": [
			{"duration": ramp_up,  "target": vus},
			{"duration": "2m",     "target": max_vus // 2},
			{"duration": duration, "target": max_vus},
			{"duration": ramp_dn,  "target": 0},
		],
		"spike":  [
			{"duration": "1m",    "target": vus},
			{"duration": "30s",   "target": max_vus},
			{"duration": "2m",    "target": max_vus},
			{"duration": "30s",   "target": vus},
			{"duration": "2m",    "target": vus},
			{"duration": ramp_dn, "target": 0},
		],
		"soak":   [
			{"duration": ramp_up,  "target": vus},
			{"duration": duration, "target": vus},
			{"duration": ramp_dn,  "target": 0},
		],
	}
	return presets.get(scenario, presets["load"])


def _json_or(raw, default):
	if not raw:
		return default
	try:
		return json.loads(raw)
	except (TypeError, ValueError):
		return default


def _endpoint_data(ep, secret) -> dict:
	method = (ep.http_method or "GET").upper()
	url = ep.endpoint_url or "/"
	if not url.startswith("/"):
		frappe.throw(_("Endpoint URL must be a path starting with '/': {0}").format(url))

	auth = ep.auth_type or "None"
	headers = {"Content-Type": "application/json"}
	extra = _json_or(ep.headers, {})
	if isinstance(extra, dict):
		headers.update({str(k): str(v) for k, v in extra.items()})

	if auth == "Bearer Token":
		headers["Authorization"] = f"Bearer {secret}"
	elif auth == "Basic Auth":
		headers["Authorization"] = "Basic " + base64.b64encode(secret.encode()).decode()
	elif auth == "API Key":
		key, _sep, api_secret = secret.partition(":")
		if api_secret:
			headers["Authorization"] = f"token {key}:{api_secret}"
	elif auth == "Custom Header":
		custom = _json_or(secret, {})
		if isinstance(custom, dict):
			headers.update({str(k): str(v) for k, v in custom.items()})

	query = _json_or(ep.query_params, {})
	body = None
	if method in ("POST", "PUT", "PATCH") and ep.payload:
		body = _json_or(ep.payload, None)

	return {
		"name": ep.api_name or url,
		"method": method,
		"url": url,
		"query": query if isinstance(query, dict) else {},
		"body": body,
		"headers": headers,
		"session": auth == "Session (Frappe Login)",
		"expected_status": int(ep.expected_status or 200),
	}

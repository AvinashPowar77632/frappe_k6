"""
Bring sites installed before the security rework up to date:
roles, metrics token, monitoring mode, and encryption of stored credentials.
"""

import json
import os

import frappe
from frappe.utils.password import set_encrypted_password


def execute():
	from frappe_k6.install import ensure_metrics_token
	from frappe_k6.security import encrypt_auth_config, ensure_roles

	ensure_roles()
	ensure_metrics_token()

	# Sites that already run the local stack keep Prometheus config management on
	prom_cfg = os.path.join(os.path.expanduser("~"), "monitoring", "prometheus", "prometheus.yml")
	if not frappe.db.get_single_value("Monitor Settings", "monitoring_mode"):
		mode = "Self-hosted" if os.path.isfile(prom_cfg) else "Off"
		frappe.db.set_single_value("Monitor Settings", "monitoring_mode", mode)

	# Load Test Endpoint.auth_value is now a Password field: move plain text into __Auth
	for row in frappe.get_all(
		"Load Test Endpoint", filters={"auth_value": ["is", "set"]}, fields=["name", "auth_value"]
	):
		value = row.auth_value
		if set(value) == {"*"}:
			continue
		set_encrypted_password("Load Test Endpoint", row.name, value, "auth_value")
		frappe.db.set_value(
			"Load Test Endpoint", row.name, "auth_value", "*" * len(value), update_modified=False
		)

	# API Request auth configs: encrypt password/token/value keys
	for row in frappe.get_all("API Request", fields=["name", "auth_config_json"]):
		try:
			cfg = json.loads(row.auth_config_json or "{}")
		except ValueError:
			continue
		if not isinstance(cfg, dict) or not cfg:
			continue
		encrypted = encrypt_auth_config(cfg)
		if encrypted != cfg:
			frappe.db.set_value(
				"API Request", row.name, "auth_config_json", json.dumps(encrypted, indent=2),
				update_modified=False,
			)

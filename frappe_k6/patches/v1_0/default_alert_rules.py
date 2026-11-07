"""Create the default K6 Alert Rules and Grafana alert rule rows on existing sites."""

import frappe


def execute():
	from frappe_k6.alerts import ensure_default_rules
	from frappe_k6.grafana_cloud import ensure_default_cloud_rules

	ensure_default_rules()
	settings = frappe.get_single("Monitor Settings")
	if ensure_default_cloud_rules(settings):
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)

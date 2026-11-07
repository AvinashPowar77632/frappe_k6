"""
Defaults for the Grafana Cloud fields on existing sites: a Check added to an existing
Single is stored as 0 on the next save instead of taking its default.
"""

import frappe


def execute():
	frappe.db.set_single_value("Monitor Settings", "gc_send_k6_native_metrics", 1)
	if not frappe.db.get_single_value("Monitor Settings", "gc_folder_uid"):
		frappe.db.set_single_value("Monitor Settings", "gc_folder_uid", "frappe-k6")

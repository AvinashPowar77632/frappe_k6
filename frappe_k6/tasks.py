"""
Scheduled background tasks for frappe_k6.
"""

import os
import glob
import frappe
from frappe.utils import now_datetime


def sync_running_tests():
    """
    Periodically check all 'Running' Load Test Runs.
    If the k6 process is dead, finalize the record.
    """
    from frappe_k6.api.load_test import _is_process_running, _parse_k6_output, _finalize_run

    runs = frappe.get_all(
        "Load Test Run",
        filters={"status": "Running"},
        fields=["name", "pid", "output_file", "config"]
    )

    for run_data in runs:
        try:
            run = frappe.get_doc("Load Test Run", run_data["name"])
            if not _is_process_running(run.pid):
                metrics = _parse_k6_output(run.output_file)
                _finalize_run(run, metrics)
        except Exception as e:
            frappe.log_error(str(e), f"sync_running_tests: {run_data['name']}")


def cleanup_old_reports():
    """
    Delete k6 JSON report files older than retention_days (default 30).
    """
    try:
        settings = frappe.get_single("Monitor Settings")
        retention = int(settings.metrics_retention_days or 30)
        reports_dir = settings.k6_reports_dir
        if not reports_dir or not os.path.isdir(reports_dir):
            return

        import time
        cutoff = time.time() - (retention * 86400)
        deleted = 0
        for fpath in glob.glob(os.path.join(reports_dir, "*.json")):
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1

        if deleted:
            frappe.logger().info(f"frappe_k6: Cleaned {deleted} old report files.")
    except Exception as e:
        frappe.log_error(str(e), "cleanup_old_reports")

"""
Scheduled background tasks for frappe_k6.
"""

import glob
import os

import frappe
from frappe.utils import now_datetime


def sync_running_tests():
    """
    Recover runs whose runner job died: a 'Running' Load Test Run with no
    runner heartbeat, and (on the runner host) no live k6 process, is finalised.
    """
    import socket

    from frappe_k6.api.load_test import _finalize_run, _heartbeat_key, _is_process_running

    runs = frappe.get_all(
        "Load Test Run",
        filters={"status": "Running"},
        fields=["name", "pid", "runner_host"]
    )

    cache = frappe.cache()
    for run_data in runs:
        try:
            if cache.get_value(_heartbeat_key(run_data["name"])):
                continue  # the runner job is alive and will finalise the run itself
            on_this_host = run_data["runner_host"] == socket.gethostname()
            if on_this_host and _is_process_running(run_data["pid"]):
                continue  # k6 still running without its job; finalise when it exits
            _finalize_run(run_data["name"])
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
        for fpath in glob.glob(os.path.join(reports_dir, "*.json")) + glob.glob(os.path.join(reports_dir, "*.log")):
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1

        if deleted:
            frappe.logger().info(f"frappe_k6: Cleaned {deleted} old report files.")
    except Exception as e:
        frappe.log_error(str(e), "cleanup_old_reports")

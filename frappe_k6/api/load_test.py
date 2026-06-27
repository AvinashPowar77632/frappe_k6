"""
Load test execution API — start, stop, status, history.
"""

import json
import os
import signal
import subprocess
import tempfile
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import now_datetime


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


@frappe.whitelist()
def start_load_test(config_name: str):
    """
    Generate a k6 script from config, launch k6 as background process,
    create a Load Test Run record, return run_name.
    """
    from frappe_k6.api.k6_generator import generate_script

    cfg = frappe.get_doc("Load Test Config", config_name)

    # Build output file path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(
        _reports_dir(),
        f"{cfg.test_name.replace(' ', '_')}_{ts}.json"
    )

    # Detect base URL
    try:
        site_cfg = frappe.get_site_config()
        port = site_cfg.get("webserver_port", 8000)
        base_url = f"http://localhost:{port}"
    except Exception:
        base_url = "http://localhost:8000"

    # Generate script
    script_path = generate_script(config_name, out_file)

    # Build k6 command
    cmd = [
        _k6_bin(), "run",
        "--out", f"json={out_file}",
        "-e", f"K6_BASE_URL={base_url}",
        script_path
    ]

    # Launch k6 as detached subprocess — redirect stdout/stderr to log file
    log_file = out_file.replace(".json", ".log")
    log_fd = open(log_file, "w")
    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True,
        close_fds=True,
    )

    # Create Load Test Run record
    run = frappe.get_doc({
        "doctype":      "Load Test Run",
        "config":       config_name,
        "status":       "Running",
        "started_at":   now_datetime(),
        "pid":          proc.pid,
        "output_file":  out_file,
        "scenario_type": cfg.scenario_type,
    })
    run.insert(ignore_permissions=True)
    frappe.db.commit()

    # Update config status
    frappe.db.set_value("Load Test Config", config_name, {
        "status":    "Running",
        "last_run":  run.name,
    })
    frappe.db.commit()

    return {"run_name": run.name, "pid": proc.pid, "output_file": out_file, "log_file": log_file}


@frappe.whitelist()
def stop_load_test(run_name: str):
    """Kill the running k6 process for this run."""
    run = frappe.get_doc("Load Test Run", run_name)
    if run.pid:
        try:
            os.killpg(os.getpgid(run.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            frappe.log_error(str(e), "stop_load_test")

    frappe.db.set_value("Load Test Run", run_name, {
        "status":       "Stopped",
        "completed_at": now_datetime(),
    })
    frappe.db.set_value("Load Test Config", run.config, "status", "Ready")
    frappe.db.commit()
    return {"status": "stopped"}


@frappe.whitelist()
def get_test_status(run_name: str):
    """
    Parse the k6 JSON output file to compute live metrics.
    Returns aggregated metrics and whether the test is still running.
    """
    run = frappe.get_doc("Load Test Run", run_name)

    # Check if k6 process is still alive
    is_running = _is_process_running(run.pid)

    metrics = _parse_k6_output(run.output_file)

    if not is_running and run.status == "Running":
        _finalize_run(run, metrics)

    return {
        "run_name":    run_name,
        "status":      run.reload().status,
        "is_running":  is_running,
        "metrics":     metrics,
        "started_at":  str(run.started_at),
    }


@frappe.whitelist(allow_guest=True)
def get_active_runs():
    """Return all currently running tests."""
    runs = frappe.get_all(
        "Load Test Run",
        filters={"status": "Running"},
        fields=["name", "config", "started_at", "pid", "output_file"]
    )
    result = []
    for run in runs:
        alive = _is_process_running(run.get("pid"))
        if not alive:
            frappe.db.set_value("Load Test Run", run["name"], {
                "status":       "Completed",
                "completed_at": now_datetime(),
            })
            frappe.db.set_value("Load Test Config", run["config"], "status", "Ready")
            frappe.db.commit()
        else:
            result.append(run)
    return result


@frappe.whitelist()
def get_run_history(limit=20):
    """Return recent load test runs."""
    return frappe.get_all(
        "Load Test Run",
        fields=["name", "config", "status", "started_at", "completed_at",
                "total_requests", "failed_requests", "requests_per_sec",
                "avg_duration_ms", "p95_duration_ms", "scenario_type"],
        order_by="started_at desc",
        limit=int(limit)
    )


@frappe.whitelist()
def save_config(config_name, test_scenario="load", virtual_users=10, duration="5m",
                ramp_up="1m", ramp_down="30s", max_vus=100, think_time=1.0,
                endpoints=None):
    """Create or update a Load Test Config from the builder form."""
    import json

    if isinstance(endpoints, str):
        endpoints = json.loads(endpoints)
    endpoints = endpoints or []

    exists = frappe.db.exists("Load Test Config", config_name)
    if exists:
        doc = frappe.get_doc("Load Test Config", config_name)
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
    })

    for ep in endpoints:
        doc.append("endpoints", {
            "doctype":         "Load Test Endpoint",
            "api_name":        ep.get("api_name") or ep.get("endpoint_label") or ep.get("endpoint_url", ""),
            "http_method":     ep.get("http_method", "GET"),
            "endpoint_url":    ep.get("endpoint_url") or ep.get("api_path", ""),
            "expected_status": int(ep.get("expected_status", 200)),
            "weight":          int(ep.get("weight", 1)),
        })

    if exists:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name}


@frappe.whitelist()
def get_configs():
    """Return all load test configs for the builder."""
    return frappe.get_all(
        "Load Test Config",
        fields=["name", "test_name", "scenario_type", "virtual_users",
                "duration", "status", "last_run", "last_run_status"],
        order_by="modified desc"
    )


# ── Internal helpers ────────────────────────────────────────────

def _is_process_running(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def _parse_k6_output(output_file: str) -> dict:
    """
    Parse k6 JSONL output. Read last 5000 lines for live metrics.
    Returns aggregated metric dict.
    """
    metrics = {
        "http_req_duration": {"values": [], "avg": 0, "p95": 0, "p99": 0, "max": 0},
        "http_reqs":         {"count": 0},
        "http_req_failed":   {"count": 0, "rate": 0},
        "vus":               {"current": 0, "max": 0},
        "data_received_kb":  0,
        "data_sent_kb":      0,
        "checks_passed":     0,
        "checks_failed":     0,
        "rps":               0,
        "error_rate":        0,
        "timeline":          [],
    }

    if not output_file or not os.path.exists(output_file):
        return metrics

    try:
        durations = []
        total_req = 0
        failed_req = 0
        current_vus = 0
        max_vus = 0
        data_recv = 0
        data_sent = 0
        checks_pass = 0
        checks_fail = 0
        timeline_buckets = {}

        with open(output_file, "r") as f:
            lines = f.readlines()

        # Read last 5000 lines for performance
        for line in lines[-5000:]:
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

            if metric == "http_req_duration":
                durations.append(value)
                # Build timeline (group by second)
                if ts_str:
                    bucket = ts_str[:19]
                    if bucket not in timeline_buckets:
                        timeline_buckets[bucket] = {"count": 0, "total": 0}
                    timeline_buckets[bucket]["count"] += 1
                    timeline_buckets[bucket]["total"] += value

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

        if durations:
            durations.sort()
            n = len(durations)
            metrics["http_req_duration"]["avg"] = round(sum(durations) / n, 2)
            metrics["http_req_duration"]["p95"] = round(durations[int(n * 0.95)], 2)
            metrics["http_req_duration"]["p99"] = round(durations[int(n * 0.99)], 2)
            metrics["http_req_duration"]["max"] = round(durations[-1], 2)

        metrics["http_reqs"]["count"]       = total_req
        metrics["http_req_failed"]["count"] = failed_req
        metrics["http_req_failed"]["rate"]  = round(failed_req / total_req * 100, 2) if total_req else 0
        metrics["vus"]["current"]           = current_vus
        metrics["vus"]["max"]               = max_vus
        metrics["data_received_kb"]         = round(data_recv / 1024, 2)
        metrics["data_sent_kb"]             = round(data_sent / 1024, 2)
        metrics["checks_passed"]            = checks_pass
        metrics["checks_failed"]            = checks_fail
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

        # Compute RPS from timeline
        if len(metrics["timeline"]) > 1:
            recent = metrics["timeline"][-10:]
            metrics["rps"] = round(sum(b["rps"] for b in recent) / len(recent), 2)

    except Exception as e:
        frappe.log_error(str(e), "k6 parse error")

    return metrics


def _finalize_run(run, metrics: dict):
    """Persist final metrics to Load Test Run record."""
    d = metrics.get("http_req_duration", {})
    try:
        frappe.db.set_value("Load Test Run", run.name, {
            "status":          "Completed",
            "completed_at":    now_datetime(),
            "total_requests":  metrics.get("http_reqs", {}).get("count", 0),
            "failed_requests": metrics.get("http_req_failed", {}).get("count", 0),
            "requests_per_sec": metrics.get("rps", 0),
            "avg_duration_ms": d.get("avg", 0),
            "p95_duration_ms": d.get("p95", 0),
            "p99_duration_ms": d.get("p99", 0),
            "summary_json":    json.dumps(metrics, indent=2),
        })
        frappe.db.set_value("Load Test Config", run.config, {
            "status":          "Completed",
            "last_run_status": "Completed",
        })
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(str(e), "finalize_run")

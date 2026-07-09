"""
Load test execution API — start, stop, status, history.
"""

import json
import os
import signal
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
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
    Supports remote server targets via Load Test Config.remote_server.
    """
    from frappe_k6.api.k6_generator import generate_script

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
            try:
                site_cfg = frappe.get_site_config()
                port = site_cfg.get("webserver_port", 8000)
                base_url = f"http://localhost:{port}"
            except Exception:
                base_url = "http://localhost:8000"

    # Build output file path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(
        _reports_dir(),
        f"{cfg.test_name.replace(' ', '_')}_{ts}.json"
    )

    # Generate script
    script_path = generate_script(config_name, out_file, target_server=target_server_label)

    # Build k6 command
    cmd = [
        _k6_bin(), "run",
        "--out", f"json={out_file}",
        "-e", f"K6_BASE_URL={base_url}",
        "-e", f"TARGET_SERVER={target_server_label}",
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
        "doctype":            "Load Test Run",
        "config":             config_name,
        "status":             "Running",
        "started_at":         now_datetime(),
        "pid":                proc.pid,
        "output_file":        out_file,
        "scenario_type":      cfg.scenario_type,
        "remote_server":      remote_server_name,
        "target_server_name": target_server_label,
        "target_base_url":    base_url,
    })
    run.insert(ignore_permissions=True)
    frappe.db.commit()

    # Update config status
    frappe.db.set_value("Load Test Config", config_name, {
        "status":    "Running",
        "last_run":  run.name,
    })
    frappe.db.commit()

    return {
        "run_name":      run.name,
        "pid":           proc.pid,
        "output_file":   out_file,
        "log_file":      log_file,
        "target_server": target_server_label,
        "base_url":      base_url,
    }


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
        "run_name":           run_name,
        "status":             run.reload().status,
        "is_running":         is_running,
        "metrics":            metrics,
        "started_at":         str(run.started_at),
        "target_server_name": getattr(run, "target_server_name", None) or "local",
        "remote_server":      getattr(run, "remote_server", None),
        "target_base_url":    getattr(run, "target_base_url", None),
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
                "avg_duration_ms", "p95_duration_ms", "scenario_type",
                "remote_server", "target_server_name"],
        order_by="started_at desc",
        limit=int(limit)
    )


@frappe.whitelist()
def get_remote_servers():
    """Return all enabled remote servers for the Test Builder dropdown."""
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
    Called by frappe_k6_exporter to expose to Prometheus.
    """
    runs = frappe.get_all(
        "Load Test Run",
        filters={"status": "Running"},
        fields=["name", "config", "pid", "output_file",
                "target_server_name", "scenario_type"]
    )
    result = []
    for run_data in runs:
        if not _is_process_running(run_data.get("pid")):
            continue
        try:
            metrics = _parse_k6_output(run_data.get("output_file", ""))
            dur  = metrics.get("http_req_duration", {})
            wait = metrics.get("http_req_waiting", {})
            vus  = metrics.get("vus", {})
            result.append({
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
            })
        except Exception as e:
            frappe.log_error(str(e), f"get_active_run_metrics: {run_data['name']}")
    return result


@frappe.whitelist()
def get_remote_server_live_metrics(server_name: str):
    """
    Query Prometheus for live OS metrics of a remote server.
    Uses node_exporter metrics filtered by server_name label.
    """
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
        "target_type":    target_type or "Local Server",
        "remote_server":  remote_server or None,
        "target_base_url": target_base_url or None,
    })

    for ep in endpoints:
        doc.append("endpoints", {
            "doctype":         "Load Test Endpoint",
            "api_name":        ep.get("api_name") or ep.get("endpoint_label") or ep.get("endpoint_url", ""),
            "http_method":     ep.get("http_method", "GET"),
            "endpoint_url":    ep.get("endpoint_url") or ep.get("api_path", ""),
            "expected_status": int(ep.get("expected_status", 200)),
            "weight":          int(ep.get("weight", 1)),
            "auth_type":       ep.get("auth_type", "None"),
            "auth_value":      ep.get("auth_value", ""),
            "headers":         ep.get("headers", ""),
            "query_params":    ep.get("query_params", ""),
            "payload":         ep.get("payload", ""),
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
                "duration", "status", "last_run", "last_run_status",
                "target_type", "remote_server"],
        order_by="modified desc"
    )


@frappe.whitelist()
def get_config(config_name: str):
    """Return full config doc including all endpoint fields."""
    doc = frappe.get_doc("Load Test Config", config_name)
    eps = []
    for ep in doc.endpoints:
        eps.append({
            "api_name":        ep.api_name,
            "http_method":     ep.http_method,
            "endpoint_url":    ep.endpoint_url,
            "expected_status": ep.expected_status,
            "weight":          ep.weight,
            "auth_type":       ep.auth_type or "None",
            "auth_value":      ep.auth_value or "",
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


def _parse_k6_output(output_file: str) -> dict:
    """
    Parse k6 JSONL output. Read last 5000 lines for live metrics.
    Returns aggregated metric dict.
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

        with open(output_file, "r") as f:
            lines = f.readlines()

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
            return round(s[int(len(s) * pct)], 2)

        def _avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else 0

        if durations:
            durations.sort()
            n = len(durations)
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

#!/usr/bin/env python3
"""
Frappe K6 Prometheus Exporter
Translates Frappe's JSON metrics API → Prometheus text exposition format.
Runs on port 9200. Start via systemd or:  python3 frappe_k6_exporter.py

Config via environment variables:
  FRAPPE_URL   Base URL of the Frappe site  (default: http://localhost:8000)
  EXPORTER_PORT  Port to listen on           (default: 9200)
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

FRAPPE_URL    = os.environ.get("FRAPPE_URL",    "http://localhost:8000")
EXPORTER_PORT = int(os.environ.get("EXPORTER_PORT", "9200"))
SCRAPE_TIMEOUT = 10  # seconds


def _fetch_metrics():
    """Call Frappe's get_all_metrics API and return the parsed JSON dict."""
    url = f"{FRAPPE_URL}/api/method/frappe_k6.api.system_metrics.get_all_metrics"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=SCRAPE_TIMEOUT) as resp:
        data = json.loads(resp.read())
    return data.get("message", {})


def _fetch_k6_runs():
    """Call Frappe's get_active_runs API."""
    url = f"{FRAPPE_URL}/api/method/frappe_k6.api.load_test.get_active_runs"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=SCRAPE_TIMEOUT) as resp:
            data = json.loads(resp.read())
        return data.get("message", [])
    except Exception:
        return []


def _build_text(m, active_runs):
    lines = []

    def gauge(name, help_text, value, **labels):
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        tag = f"{{{label_str}}}" if label_str else ""
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        try:
            lines.append(f"{name}{tag} {float(value):.6g}")
        except (TypeError, ValueError):
            lines.append(f"{name}{tag} 0")

    cpu  = m.get("cpu",      {})
    mem  = m.get("memory",   {})
    disk = m.get("disk",     {})
    net  = m.get("network",  {})
    rds  = m.get("redis",    {})
    db   = m.get("database", {})
    wrk  = m.get("workers",  {})
    que  = m.get("queues",   {})

    # CPU
    gauge("frappe_cpu_percent",     "CPU usage %",              cpu.get("percent",  0))
    gauge("frappe_cpu_count",       "Number of CPU cores",      cpu.get("count",    1))
    load = cpu.get("load_avg", [0, 0, 0])
    gauge("frappe_load_average",    "System 1m load average",   load[0], interval="1m")
    gauge("frappe_load_average",    "System 5m load average",   load[1], interval="5m")
    gauge("frappe_load_average",    "System 15m load average",  load[2], interval="15m")

    # Memory
    gauge("frappe_memory_used_gb",  "Memory used GiB",          mem.get("used_gb",  0))
    gauge("frappe_memory_total_gb", "Memory total GiB",         mem.get("total_gb", 0))
    gauge("frappe_memory_percent",  "Memory usage %",           mem.get("percent",  0))

    # Disk
    gauge("frappe_disk_used_gb",    "Disk used GiB",            disk.get("used_gb",  0))
    gauge("frappe_disk_total_gb",   "Disk total GiB",           disk.get("total_gb", 0))
    gauge("frappe_disk_percent",    "Disk usage %",             disk.get("percent",  0))

    # Network
    gauge("frappe_network_sent_mb", "Network cumulative sent MiB",  net.get("bytes_sent_mb", 0))
    gauge("frappe_network_recv_mb", "Network cumulative recv MiB",  net.get("bytes_recv_mb", 0))

    # Redis
    gauge("frappe_redis_connected",    "Redis up (1=ok)",         1 if rds.get("status") == "connected" else 0)
    gauge("frappe_redis_memory_mb",    "Redis memory MB",         rds.get("memory_mb",         0))
    gauge("frappe_redis_hit_ratio",    "Redis hit ratio %",       rds.get("hit_ratio",          0))
    gauge("frappe_redis_clients",      "Redis connected clients", rds.get("connected_clients",  0))

    # Database
    gauge("frappe_db_connected",    "MariaDB up (1=ok)",          1 if db.get("status") == "connected" else 0)
    gauge("frappe_db_connections",  "Active DB connections",      db.get("connections",    0))
    gauge("frappe_db_slow_queries", "Cumulative slow queries",    db.get("slow_queries",   0))

    # Workers
    gauge("frappe_worker_count",    "Frappe worker count",        wrk.get("count", 0))

    # Queues
    for q in ("default", "long", "short"):
        gauge("frappe_queue_depth", f"RQ queue depth", que.get(q, 0), queue=q)

    # K6 active tests
    gauge("frappe_k6_active_runs",  "Currently running k6 tests", len(active_runs))

    # Exporter self-metrics
    gauge("frappe_k6_exporter_up",  "Exporter is running",        1)
    gauge("frappe_k6_scrape_time",  "Last scrape timestamp",       time.time())

    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return

        start = time.time()
        try:
            m = _fetch_metrics()
            runs = _fetch_k6_runs()
            body = _build_text(m, runs).encode("utf-8")
            duration = time.time() - start
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            print(f"[exporter] scrape OK  {duration:.3f}s  {len(body)} bytes", flush=True)
        except Exception as exc:
            err = f"# scrape error: {exc}\n".encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            print(f"[exporter] scrape FAIL: {exc}", flush=True)

    def log_message(self, fmt, *args):
        pass  # silence default access log


def main():
    print(f"[exporter] Frappe K6 exporter starting on :{EXPORTER_PORT}")
    print(f"[exporter] Frappe URL: {FRAPPE_URL}")
    server = HTTPServer(("0.0.0.0", EXPORTER_PORT), MetricsHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[exporter] stopped")


if __name__ == "__main__":
    main()

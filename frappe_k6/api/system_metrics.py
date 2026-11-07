"""
System metrics API — CPU, Memory, Disk, Network, Redis, DB, Gunicorn
"""

import subprocess

import frappe
from frappe import _

from frappe_k6.security import check_metrics_access


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def collect_samples():
    """
    Frappe/K6 metrics as a list of (name, help, kind, labels, value).
    Shared by the Prometheus endpoint and the Grafana Cloud push.
    Uses only fast (sub-second) collectors — no supervisorctl calls.
    """
    cpu  = _cpu_metrics()
    mem  = _memory_metrics()
    disk = _disk_metrics()
    net  = _network_metrics()
    rds  = _redis_metrics()
    db   = _database_metrics()
    que  = _queue_metrics()
    # Count gunicorn processes via psutil (fast) instead of supervisorctl
    wrk  = _safe(lambda: {"count": sum(
        1 for p in __import__("psutil").process_iter(["name"])
        if "gunicorn" in (p.info.get("name") or "").lower()
    )}, {"count": 0})

    samples = []

    def g(name, help_text, value, labels=None, kind="gauge"):
        samples.append((name, help_text, kind, labels or {}, value))

    def c(name, help_text, value, labels=None):
        g(name, help_text, value, labels, kind="counter")

    # ── CPU ──────────────────────────────────────────────────────────────────
    g("frappe_cpu_percent",       "CPU usage percentage",         cpu.get("percent", 0))
    g("frappe_cpu_count",         "Number of CPU cores",          cpu.get("count", 0))
    load = cpu.get("load_avg", [0, 0, 0])
    g("frappe_load_average",      "System load average",          load[0], {"interval": "1m"})
    g("frappe_load_average",      "System load average",          load[1], {"interval": "5m"})
    g("frappe_load_average",      "System load average",          load[2], {"interval": "15m"})

    # ── Memory ───────────────────────────────────────────────────────────────
    g("frappe_memory_used_gb",    "Memory used in GiB",           mem.get("used_gb", 0))
    g("frappe_memory_total_gb",   "Total memory in GiB",          mem.get("total_gb", 0))
    g("frappe_memory_percent",    "Memory usage percentage",      mem.get("percent", 0))

    # ── Disk ─────────────────────────────────────────────────────────────────
    g("frappe_disk_used_gb",      "Disk used in GiB",             disk.get("used_gb", 0))
    g("frappe_disk_total_gb",     "Total disk in GiB",            disk.get("total_gb", 0))
    g("frappe_disk_percent",      "Disk usage percentage",        disk.get("percent", 0))

    # ── Network (cumulative MiB) ──────────────────────────────────────────────
    c("frappe_network_sent_mb",   "Network bytes sent (MiB)",     net.get("bytes_sent_mb", 0))
    c("frappe_network_recv_mb",   "Network bytes received (MiB)", net.get("bytes_recv_mb", 0))

    # ── Redis ─────────────────────────────────────────────────────────────────
    g("frappe_redis_connected",   "Redis connection status",
      1 if rds.get("status") == "connected" else 0)
    g("frappe_redis_memory_mb",   "Redis memory used (MB)",       rds.get("memory_mb", 0))
    g("frappe_redis_hit_ratio",   "Redis cache hit ratio %",      rds.get("hit_ratio", 0))
    g("frappe_redis_clients",     "Redis connected clients",      rds.get("connected_clients", 0))

    # ── Database ──────────────────────────────────────────────────────────────
    g("frappe_db_connected",      "Database connection status",
      1 if db.get("status") == "connected" else 0)
    g("frappe_db_connections",    "Active DB connections",        db.get("connections", 0))
    c("frappe_db_slow_queries",   "Cumulative slow queries",      db.get("slow_queries", 0))

    # ── Workers ───────────────────────────────────────────────────────────────
    g("frappe_worker_count",      "Frappe/Gunicorn worker count", wrk.get("count", 0))

    # ── Queues ────────────────────────────────────────────────────────────────
    for q_name in ("default", "long", "short"):
        g("frappe_queue_depth", "RQ queue depth", que.get(q_name, 0), {"queue": q_name})

    # ── K6 active runs ────────────────────────────────────────────────────────
    try:
        active = frappe.db.count("Load Test Run", {"status": "Running"})
        total  = frappe.db.count("Load Test Run")
        g("frappe_k6_active_runs", "Currently running k6 tests", active)
        c("frappe_k6_total_runs",  "Total k6 test runs",         total)
    except Exception:
        pass

    return samples


@frappe.whitelist(allow_guest=True)
def prometheus_metrics():
    """Return all Frappe/K6 metrics in Prometheus text exposition format.

    Scraped by Prometheus at /api/method/frappe_k6.api.system_metrics.prometheus_metrics.
    Needs a K6 role session or the `X-Frappe-K6-Token: <frappe_k6_metrics_token>` header.
    """
    check_metrics_access()

    lines = []
    declared = set()
    for name, help_text, kind, labels, value in collect_samples():
        if name not in declared:  # HELP/TYPE once per metric family
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {kind}")
            declared.add(name)
        tag = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f"{name}{{{tag}}} {value}" if tag else f"{name} {value}")

    text = "\n".join(lines) + "\n"

    # Return as plain text — override Frappe's JSON envelope
    frappe.local.response.http_status_code = 200
    frappe.local.response["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8"
    frappe.local.response["message"] = text
    return text


@frappe.whitelist(allow_guest=True)
def get_all_metrics():
    """Returns all system + infra metrics in a single call (K6 role or metrics token)."""
    check_metrics_access()
    return {
        "cpu":        _cpu_metrics(),
        "memory":     _memory_metrics(),
        "disk":       _disk_metrics(),
        "network":    _network_metrics(),
        "redis":      _redis_metrics(),
        "database":   _database_metrics(),
        "gunicorn":   _gunicorn_metrics(),
        "workers":    _worker_metrics(),
        "queues":     _queue_metrics(),
    }


def _cpu_metrics():
    import psutil
    freq = _safe(lambda: psutil.cpu_freq())
    return {
        "percent":    _safe(lambda: psutil.cpu_percent(interval=0.2), 0),
        "count":      _safe(lambda: psutil.cpu_count(), 1),
        "freq_mhz":   round(freq.current, 0) if freq else 0,
        "load_avg":   _safe(lambda: [round(x, 2) for x in psutil.getloadavg()], [0, 0, 0]),
    }


def _memory_metrics():
    import psutil
    vm = _safe(lambda: psutil.virtual_memory())
    if not vm:
        return {}
    return {
        "total_gb":   round(vm.total / 1024**3, 2),
        "used_gb":    round(vm.used  / 1024**3, 2),
        "free_gb":    round(vm.available / 1024**3, 2),
        "percent":    vm.percent,
    }


def _disk_metrics():
    import psutil
    du = _safe(lambda: psutil.disk_usage("/"))
    if not du:
        return {}
    return {
        "total_gb":   round(du.total / 1024**3, 1),
        "used_gb":    round(du.used  / 1024**3, 1),
        "free_gb":    round(du.free  / 1024**3, 1),
        "percent":    du.percent,
    }


def _network_metrics():
    import psutil
    net = _safe(lambda: psutil.net_io_counters())
    if not net:
        return {}
    return {
        "bytes_sent_mb": round(net.bytes_sent / 1024**2, 2),
        "bytes_recv_mb": round(net.bytes_recv / 1024**2, 2),
        "packets_sent":  net.packets_sent,
        "packets_recv":  net.packets_recv,
    }


def _redis_metrics():
    try:
        import redis as redis_lib
        common_cfg = frappe.get_site_config()
        redis_url = common_cfg.get("redis_cache", "redis://127.0.0.1:6379")
        r = redis_lib.from_url(redis_url)
        info = r.info()
        used_memory = info.get("used_memory", 0)
        max_memory   = info.get("maxmemory", 0) or used_memory * 2
        hits   = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total  = hits + misses
        return {
            "status":             "connected",
            "memory_mb":          round(used_memory / 1024**2, 2),
            "memory_percent":     round(used_memory / max_memory * 100, 1) if max_memory else 0,
            "connected_clients":  info.get("connected_clients", 0),
            "hit_ratio":          round(hits / total * 100, 1) if total else 100,
            "total_commands":     info.get("total_commands_processed", 0),
            "uptime_days":        info.get("uptime_in_days", 0),
            "keys":               sum(v.get("keys", 0) for v in (info.get("db0") or {}).values() if isinstance(v, dict)) if isinstance(info.get("db0"), dict) else 0,
            "version":            info.get("redis_version", ""),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _database_metrics():
    try:
        if frappe.db.db_type == "postgres":
            return _postgres_metrics()
        status = frappe.db.sql(
            "SHOW GLOBAL STATUS WHERE Variable_name IN "
            "('Threads_connected','Slow_queries','Questions','Connections')",
            as_dict=True
        )
        row = {r["Variable_name"]: int(r["Value"]) for r in status}
        variables = frappe.db.sql(
            "SHOW GLOBAL VARIABLES WHERE Variable_name IN "
            "('max_connections','long_query_time')",
            as_dict=True
        )
        var = {r["Variable_name"]: r["Value"] for r in variables}
        return {
            "status":             "connected",
            "connections":        row.get("Threads_connected", 0),
            "max_connections":    int(var.get("max_connections", 100)),
            "slow_queries":       row.get("Slow_queries", 0),
            "total_queries":      row.get("Questions", 0),
            "long_query_time_s":  float(var.get("long_query_time", 1)),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _postgres_metrics():
    connections = frappe.db.sql("SELECT count(*) FROM pg_stat_activity")[0][0]
    max_connections = frappe.db.sql("SHOW max_connections")[0][0]
    total_queries = frappe.db.sql(
        "SELECT coalesce(sum(xact_commit + xact_rollback), 0) FROM pg_stat_database"
    )[0][0]
    return {
        "status":             "connected",
        "connections":        int(connections),
        "max_connections":    int(max_connections),
        "slow_queries":       0,  # needs pg_stat_statements; not assumed to be installed
        "total_queries":      int(total_queries),
        "long_query_time_s":  0,
    }


def _gunicorn_metrics():
    try:
        result = subprocess.run(
            ["supervisorctl", "status"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        workers = []
        for line in lines:
            lower = line.lower()
            if "web" in lower or "gunicorn" in lower or "frappe" in lower:
                parts = line.split()
                workers.append({
                    "name":   parts[0] if parts else line,
                    "status": parts[1] if len(parts) > 1 else "unknown",
                    "pid":    parts[3].rstrip(",") if len(parts) > 3 else "",
                })
        return {"workers": workers, "count": len(workers)}
    except Exception:
        try:
            import psutil
            count = sum(
                1 for p in psutil.process_iter(["name", "cmdline"])
                if "gunicorn" in (p.info.get("name") or "")
            )
            return {"count": count, "workers": []}
        except Exception:
            return {"count": 0, "workers": []}


def _worker_metrics():
    try:
        result = subprocess.run(
            ["supervisorctl", "status"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        workers = []
        for line in lines:
            lower = line.lower()
            if "worker" in lower or "scheduler" in lower:
                parts = line.split()
                workers.append({
                    "name":   parts[0] if parts else line,
                    "status": parts[1] if len(parts) > 1 else "unknown",
                })
        return {"workers": workers, "count": len(workers)}
    except Exception:
        return {"count": 0, "workers": []}


def _queue_metrics():
    try:
        import redis as redis_lib
        common_cfg = frappe.get_site_config()
        redis_url = common_cfg.get("redis_queue", "redis://127.0.0.1:11000")
        r = redis_lib.from_url(redis_url)
        queues = {}
        for q in ["default", "long", "short"]:
            key = f"rq:queue:{q}"
            queues[q] = _safe(lambda k=key: r.llen(k), 0)
        return queues
    except Exception:
        return {"default": 0, "long": 0, "short": 0}

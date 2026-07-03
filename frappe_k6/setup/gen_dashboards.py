#!/usr/bin/env python3
"""
gen_dashboards.py — Generate expert-level Grafana dashboard JSON files.

Dashboards generated:
  frappe_k6_db_dashboard.json      — Database (MariaDB/PostgreSQL)
  frappe_k6_redis_dashboard.json   — Redis cache
  frappe_k6_worker_dashboard.json  — Frappe workers & queues
  frappe_k6_node_dashboard.json    — Node / Server infrastructure

Run: python3 gen_dashboards.py
"""

import json
import os

SETUP_DIR = os.path.dirname(os.path.abspath(__file__))

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki",       "uid": "loki"}

NAV_LINKS = [
    {"title": "▶ Fleet Overview",  "url": "/d/frappe-k6-multi",   "type": "link", "icon": "dashboard"},
    {"title": "▶ Server Detail",   "url": "/d/frappe-k6-remote",  "type": "link", "icon": "dashboard"},
    {"title": "▶ Main",            "url": "/d/frappe-k6-monitor", "type": "link", "icon": "dashboard"},
    {"title": "▶ Database",        "url": "/d/frappe-k6-db",      "type": "link", "icon": "dashboard"},
    {"title": "▶ Redis",           "url": "/d/frappe-k6-redis",   "type": "link", "icon": "dashboard"},
    {"title": "▶ Workers",         "url": "/d/frappe-k6-workers", "type": "link", "icon": "dashboard"},
    {"title": "▶ Node",            "url": "/d/frappe-k6-node",    "type": "link", "icon": "dashboard"},
]

# ─── Template variables injected into every per-component dashboard ──────────

SERVER_VAR = {
    "name": "server",
    "label": "Server",
    "type": "query",
    "datasource": {"type": "prometheus", "uid": "prometheus"},
    "definition": "label_values(up{job=\"node\"}, server_name)",
    "query": {"query": "label_values(up{job=\"node\"}, server_name)", "refId": "A"},
    "refresh": 2,
    "includeAll": True,
    "multi": True,
    "allValue": ".+",
    "current": {"text": "All", "value": "$__all"},
    "sort": 1,
    "hide": 0,
}

ENV_VAR = {
    "name": "env",
    "label": "Environment",
    "type": "query",
    "datasource": {"type": "prometheus", "uid": "prometheus"},
    "definition": "label_values(up{job=\"node\"}, env)",
    "query": {"query": "label_values(up{job=\"node\"}, env)", "refId": "B"},
    "refresh": 2,
    "includeAll": True,
    "multi": True,
    "allValue": ".+",
    "current": {"text": "All", "value": "$__all"},
    "sort": 1,
    "hide": 0,
}


# ─── Low-level panel builders ─────────────────────────────────────────────────

def _pos(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def row_panel(pid, title, y, collapsed=False):
    return {
        "id": pid, "type": "row", "title": title, "collapsed": collapsed,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
    }


def stat_panel(pid, title, expr, x, y, w=4, h=4, unit="short",
               thresholds=None, mappings=None, ds=PROM, legend="",
               color_mode="background", graph_mode="area", desc=""):
    thresh = thresholds or [{"color": "green", "value": None}]
    p = {
        "id": pid, "type": "stat", "title": title, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "colorMode": color_mode, "graphMode": graph_mode,
            "orientation": "auto",
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit, "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": thresh},
            }
        },
        "targets": [{"datasource": ds, "expr": expr, "legendFormat": legend, "refId": "A"}],
        "datasource": ds,
    }
    if mappings:
        p["fieldConfig"]["defaults"]["mappings"] = mappings
    return p


def gauge_panel(pid, title, expr, x, y, w=4, h=6, unit="percent",
                min_val=0, max_val=100, thresholds=None, ds=PROM, desc=""):
    thresh = thresholds or [
        {"color": "green",  "value": None},
        {"color": "yellow", "value": 70},
        {"color": "red",    "value": 90},
    ]
    return {
        "id": pid, "type": "gauge", "title": title, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "showThresholdLabels": False, "showThresholdMarkers": True,
        },
        "fieldConfig": {
            "defaults": {
                "min": min_val, "max": max_val, "unit": unit,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": thresh},
            }
        },
        "targets": [{"datasource": ds, "expr": expr, "legendFormat": "", "refId": "A"}],
        "datasource": ds,
    }


def ts_panel(pid, title, targets, x, y, w=12, h=7, unit="short",
             ds=PROM, fill=10, min_val=None, stack=False, desc="",
             legend_calcs=None):
    calcs = legend_calcs or ["mean", "max", "last"]
    ts_targets = []
    for i, t in enumerate(targets):
        if isinstance(t, str):
            ts_targets.append({"datasource": ds, "expr": t,
                                "legendFormat": "__auto", "refId": chr(65 + i)})
        else:
            ts_targets.append({
                "datasource": t.get("ds", ds),
                "expr": t["expr"],
                "legendFormat": t.get("legend", "__auto"),
                "refId": chr(65 + i),
            })
    p = {
        "id": pid, "type": "timeseries", "title": title, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": {
            "tooltip": {"mode": "multi", "sort": "desc"},
            "legend": {
                "displayMode": "table", "placement": "bottom",
                "calcs": calcs, "showLegend": True,
            },
            "fillOpacity": fill,
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit, "color": {"mode": "palette-classic"},
                "custom": {
                    "fillOpacity": fill, "lineWidth": 2,
                    "lineInterpolation": "smooth",
                    "stacking": {"mode": "normal" if stack else "none"},
                },
            }
        },
        "targets": ts_targets,
        "datasource": ds,
    }
    if min_val is not None:
        p["fieldConfig"]["defaults"]["min"] = min_val
    return p


def logs_panel(pid, title, expr, x, y, w=24, h=8, desc=""):
    return {
        "id": pid, "type": "logs", "title": title, "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": {
            "dedupStrategy": "none", "enableLogDetails": True,
            "prettifyLogMessage": False, "showTime": True,
            "showLabels": True, "showCommonLabels": False,
            "wrapLogMessage": True, "sortOrder": "Descending",
        },
        "targets": [{"datasource": LOKI, "expr": expr, "refId": "A"}],
        "datasource": LOKI,
    }


def dashboard_wrapper(uid, title, panels, tags=None, refresh="30s", with_server_var=True):
    template_vars = [SERVER_VAR, ENV_VAR] if with_server_var else []
    return {
        "id": None, "uid": uid, "title": title,
        "tags": tags or ["frappe", "k6", "observability"],
        "timezone": "browser", "schemaVersion": 38,
        "version": 1, "refresh": refresh,
        "time": {"from": "now-3h", "to": "now"},
        "timepicker": {},
        "panels": panels,
        "links": NAV_LINKS,
        "templating": {"list": template_vars},
        "annotations": {"list": []},
    }


# ─── Multi-Server Overview Dashboard ─────────────────────────────────────────

def build_multi_server_dashboard():
    p = []

    # Row 1 — Fleet status
    p.append(row_panel(1, "🌐 Fleet Health — All Servers", y=0))
    p.append({
        "id": 2, "type": "stat",
        "title": "Servers Online",
        "description": "Number of servers where node_exporter is reachable",
        "gridPos": {"h": 4, "w": 4, "x": 0, "y": 1},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "graphMode": "none"},
        "fieldConfig": {"defaults": {"unit": "short",
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "red", "value": None},
                {"color": "yellow", "value": 1},
                {"color": "green", "value": 2},
            ]}}},
        "targets": [{"datasource": PROM, "expr": 'count(up{job="node"} == 1)',
                     "legendFormat": "Online", "refId": "A"}],
        "datasource": PROM,
    })
    p.append({
        "id": 3, "type": "stat",
        "title": "Servers Offline / Unreachable",
        "gridPos": {"h": 4, "w": 4, "x": 4, "y": 1},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "graphMode": "none"},
        "fieldConfig": {"defaults": {"unit": "short",
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 1},
                {"color": "red", "value": 2},
            ]}}},
        "targets": [{"datasource": PROM, "expr": 'count(up{job="node"} == 0) or vector(0)',
                     "legendFormat": "Offline", "refId": "A"}],
        "datasource": PROM,
    })
    p.append(stat_panel(4, "Total Servers Monitored",
        'count(up{job="node"})', x=8, y=1, w=4, h=4,
        thresholds=[{"color": "blue", "value": None}], color_mode="none",
        desc="Total node_exporter targets scraped by Prometheus"))
    p.append(stat_panel(5, "Alerts Firing (up == 0)",
        'count(up == 0) or vector(0)', x=12, y=1, w=4, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
        desc="Any exporter (node/redis/db) that is currently down"))
    p.append(stat_panel(6, "DB Exporter Targets Up",
        'count(up{job=~"mysqld_exporter|postgres_exporter"} == 1) or vector(0)',
        x=16, y=1, w=4, h=4,
        thresholds=[{"color": "green", "value": None}], color_mode="none"))
    p.append(stat_panel(7, "Redis Exporter Targets Up",
        'count(up{job="redis_exporter"} == 1) or vector(0)',
        x=20, y=1, w=4, h=4,
        thresholds=[{"color": "green", "value": None}], color_mode="none"))

    # Row 2 — Per-server CPU
    p.append(row_panel(10, "⚡ CPU per Server", y=5))
    p.append(ts_panel(11, "CPU Usage % per Server",
        [{"expr": '100 - (avg by(server_name)(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)',
          "legend": "{{server_name}}"}],
        x=0, y=6, w=24, h=7, unit="percent", min_val=0,
        desc="Per-server CPU utilisation — identify hot servers at a glance"))

    # Row 3 — Per-server Memory
    p.append(row_panel(20, "💾 Memory per Server", y=13))
    p.append(ts_panel(21, "Memory Usage % per Server",
        [{"expr": '(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100',
          "legend": "{{server_name}}"}],
        x=0, y=14, w=12, h=7, unit="percent", min_val=0,
        desc="Per-server memory utilisation"))
    p.append(ts_panel(22, "Memory Free per Server",
        [{"expr": 'node_memory_MemAvailable_bytes',
          "legend": "{{server_name}}"}],
        x=12, y=14, w=12, h=7, unit="bytes",
        desc="Absolute free memory — servers near zero are at risk of OOM"))

    # Row 4 — Per-server Disk
    p.append(row_panel(30, "💿 Disk per Server", y=21))
    p.append(ts_panel(31, "Disk Usage % per Server (root mount)",
        [{"expr": '(1 - node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}) * 100',
          "legend": "{{server_name}}"}],
        x=0, y=22, w=12, h=7, unit="percent", min_val=0,
        desc="Root filesystem fill level per server"))
    p.append(ts_panel(32, "Disk I/O Throughput per Server (bytes/s)",
        [
            {"expr": 'sum by(server_name)(rate(node_disk_read_bytes_total[2m]))',  "legend": "Read {{server_name}}"},
            {"expr": 'sum by(server_name)(rate(node_disk_written_bytes_total[2m]))', "legend": "Write {{server_name}}"},
        ],
        x=12, y=22, w=12, h=7, unit="Bps",
        desc="Aggregate disk throughput per server"))

    # Row 5 — Per-server Network
    p.append(row_panel(40, "🌐 Network per Server", y=29))
    p.append(ts_panel(41, "Network RX per Server (bytes/s)",
        [{"expr": 'sum by(server_name)(rate(node_network_receive_bytes_total{device!="lo"}[2m]))',
          "legend": "{{server_name}}"}],
        x=0, y=30, w=12, h=6, unit="Bps",
        desc="Inbound network traffic per server"))
    p.append(ts_panel(42, "Network TX per Server (bytes/s)",
        [{"expr": 'sum by(server_name)(rate(node_network_transmit_bytes_total{device!="lo"}[2m]))',
          "legend": "{{server_name}}"}],
        x=12, y=30, w=12, h=6, unit="Bps",
        desc="Outbound network traffic per server"))

    # Row 6 — Load Average comparison
    p.append(row_panel(50, "📊 Load Average per Server", y=36))
    p.append(ts_panel(51, "Load Average 1m — All Servers",
        [{"expr": 'node_load1', "legend": "{{server_name}}"}],
        x=0, y=37, w=12, h=6, unit="short", min_val=0,
        desc="1-minute load average per server"))
    p.append(ts_panel(52, "Load Average 15m — All Servers",
        [{"expr": 'node_load15', "legend": "{{server_name}}"}],
        x=12, y=37, w=12, h=6, unit="short", min_val=0,
        desc="15-minute load average — trend indicator"))

    # Row 7 — DB & Redis per server
    p.append(row_panel(60, "🗃️ DB & Redis per Server", y=43))
    p.append(ts_panel(61, "DB Active Connections per Server",
        [{"expr": 'frappe_db_connections', "legend": "{{instance}}"}],
        x=0, y=44, w=8, h=6, unit="short", min_val=0,
        desc="Active DB connections reported by frappe_k6 exporter"))
    p.append(ts_panel(62, "Redis Memory (MB) per Server",
        [{"expr": 'frappe_redis_memory_mb', "legend": "{{instance}}"}],
        x=8, y=44, w=8, h=6, unit="short", min_val=0,
        desc="Redis memory usage per exporter instance"))
    p.append(ts_panel(63, "Redis Hit Ratio % per Server",
        [{"expr": 'frappe_redis_hit_ratio', "legend": "{{instance}}"}],
        x=16, y=44, w=8, h=6, unit="percent", min_val=0,
        desc="Cache hit ratio per server"))

    # Row 8 — Log Error Rate per server
    p.append(row_panel(70, "🚨 Error Rate per Server (Loki)", y=50))
    p.append(ts_panel(71, "Application ERROR Log Rate per Server (lines/min)",
        [{"expr": 'sum by(server_name)(rate({job="frappe", level="ERROR"}[1m]))',
          "legend": "{{server_name}}", "ds": LOKI}],
        x=0, y=51, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Error-level log lines per minute, per server — identify the noisiest server"))
    p.append(ts_panel(72, "Worker Queue Depth per Server",
        [{"expr": 'sum by(instance)(frappe_queue_depth)', "legend": "{{instance}}"}],
        x=12, y=51, w=12, h=6, unit="short", min_val=0,
        desc="Total pending jobs per frappe_k6 exporter instance"))

    return dashboard_wrapper(
        uid="frappe-k6-multi",
        title="Frappe K6 — Multi-Server Overview",
        panels=p,
        tags=["frappe", "multi-server", "fleet", "k6"],
        refresh="30s",
        with_server_var=False,
    )


# ─── Database Dashboard ───────────────────────────────────────────────────────

def build_database_dashboard():
    p = []

    # Row 1 — KPIs
    p.append(row_panel(1, "🗃️ Database Overview — KPIs", y=0))
    p.append(stat_panel(2, "DB Status", "frappe_db_connected", x=0, y=1, w=3, h=4,
        thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
        mappings=[{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}],
        desc="MariaDB/PostgreSQL connectivity status"))
    p.append(stat_panel(3, "Active Connections", "frappe_db_connections", x=3, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 50}, {"color": "red", "value": 100}],
        desc="Current active database connections"))
    p.append(stat_panel(4, "Slow Queries/min", "rate(frappe_db_slow_queries[1m]) * 60", x=6, y=1, w=3, h=4, unit="ops",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 1}, {"color": "red", "value": 5}],
        desc="Rate of slow queries per minute"))
    p.append(stat_panel(5, "Slow Queries (Total)", "frappe_db_slow_queries", x=9, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 100}, {"color": "red", "value": 1000}],
        desc="Cumulative slow query count since last restart"))
    p.append(stat_panel(6, "Conn Growth /5m", "increase(frappe_db_connections[5m])", x=12, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 10}, {"color": "red", "value": 30}],
        desc="Connection count growth in last 5 minutes"))
    p.append(gauge_panel(7, "Connection Utilisation %",
        "(frappe_db_connections / 151) * 100", x=15, y=1, w=4, h=4,
        min_val=0, max_val=100, unit="percent",
        desc="% of max_connections used (assumes max=151)"))
    p.append(stat_panel(8, "DB Log Error Rate /min",
        'sum(rate({job="frappe", log_type="database", level="ERROR"}[1m]))',
        x=19, y=1, w=3, h=4, unit="ops", ds=LOKI,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 0.1}, {"color": "red", "value": 1}],
        desc="Database error log lines per minute"))
    p.append(stat_panel(9, "Slow Query Acceleration",
        "deriv(frappe_db_slow_queries[10m])", x=22, y=1, w=2, h=4, unit="ops",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 0.1}, {"color": "red", "value": 1}],
        desc="Rate of change of slow query rate — positive = getting worse"))

    # Row 2 — Connection Analysis
    p.append(row_panel(10, "📈 Connection & Query Analysis", y=5))
    p.append(ts_panel(11, "Active DB Connections Over Time",
        [{"expr": "frappe_db_connections", "legend": "Active Connections"}],
        x=0, y=6, w=12, h=7, unit="short", min_val=0,
        desc="Track connection count trends — spikes may indicate connection leaks"))
    p.append(ts_panel(12, "Slow Query Rate (per minute)",
        [
            {"expr": "rate(frappe_db_slow_queries[1m]) * 60", "legend": "Slow Queries/min"},
            {"expr": "increase(frappe_db_slow_queries[5m])", "legend": "Slow Queries (5m window)"},
        ],
        x=12, y=6, w=12, h=7, unit="ops", min_val=0,
        desc="Slow query rate trend — rising rate indicates query regression"))

    p.append(ts_panel(13, "Connection Utilisation % Over Time",
        [{"expr": "(frappe_db_connections / 151) * 100", "legend": "Utilisation %"}],
        x=0, y=13, w=8, h=7, unit="percent", min_val=0,
        desc="Connection pool utilisation — above 80% risks connection refusals"))
    p.append(ts_panel(14, "Slow Query Accumulation (cumulative)",
        [{"expr": "frappe_db_slow_queries", "legend": "Total Slow Queries"}],
        x=8, y=13, w=8, h=7, unit="short", min_val=0,
        desc="Ever-increasing counter — reset on DB restart"))
    p.append(ts_panel(15, "DB vs Redis Connection Comparison",
        [
            {"expr": "frappe_db_connections",    "legend": "DB Connections"},
            {"expr": "frappe_redis_clients",      "legend": "Redis Clients"},
        ],
        x=16, y=13, w=8, h=7, unit="short", min_val=0,
        desc="Correlation between DB and Redis load"))

    # Row 3 — Performance Indicators
    p.append(row_panel(20, "⚡ Performance Indicators", y=20))
    p.append(ts_panel(21, "Slow Query Rate Acceleration",
        [{"expr": "deriv(rate(frappe_db_slow_queries[5m])[10m:])", "legend": "Query Rate Δ"}],
        x=0, y=21, w=8, h=6, unit="ops",
        desc="Second derivative — positive = slow queries getting worse over time"))
    p.append(ts_panel(22, "DB Connection Volatility (std-dev 5m)",
        [{"expr": "stddev_over_time(frappe_db_connections[5m])", "legend": "Connection σ"}],
        x=8, y=21, w=8, h=6, unit="short", min_val=0,
        desc="High std-dev means connections are fluctuating rapidly"))
    p.append(ts_panel(23, "DB Health Score Over Time",
        [{"expr": "frappe_db_connected * (1 - clamp_max(frappe_db_slow_queries / 1000, 1))", "legend": "Health Score"}],
        x=16, y=21, w=8, h=6, unit="short", min_val=0,
        desc="Composite: 1 = healthy DB with no slow queries, 0 = degraded"))

    # Row 4 — Logs
    p.append(row_panel(30, "📋 Database Logs", y=27))
    p.append(logs_panel(31, "Slow Query & Database Log (Live)",
        '{job="frappe", log_type="database"}',
        x=0, y=28, w=24, h=9,
        desc="Real-time stream of all database.log entries (slow queries, errors, warnings)"))
    p.append(logs_panel(32, "Database ERROR Logs",
        '{job="frappe", log_type="database", level="ERROR"}',
        x=0, y=37, w=12, h=8,
        desc="Filtered view: only ERROR-level database log lines"))
    p.append(logs_panel(33, "Application Errors (all sources)",
        '{job="frappe", level="ERROR"}',
        x=12, y=37, w=12, h=8,
        desc="All ERROR-level lines across all Frappe log sources"))

    # Row 5 — Log Volume
    p.append(row_panel(40, "📊 Log Volume Analysis", y=45))
    p.append(ts_panel(41, "DB Log Rate by Level (lines/min)",
        [{"expr": 'sum by(level)(rate({job="frappe", log_type="database"}[1m]))', "legend": "{{level}}",
          "ds": LOKI}],
        x=0, y=46, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Lines/min per severity — rising ERROR rate = active problem"))
    p.append(ts_panel(42, "All Frappe Log Rate by Level (lines/min)",
        [{"expr": 'sum by(level)(rate({job="frappe"}[1m]))', "legend": "{{level}}", "ds": LOKI}],
        x=12, y=46, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Overall application log volume breakdown by severity"))

    return dashboard_wrapper(
        uid="frappe-k6-db",
        title="Frappe K6 — Database Dashboard (Expert)",
        panels=p,
        tags=["frappe", "database", "k6", "mariadb"],
        refresh="30s",
    )


# ─── Redis Dashboard ──────────────────────────────────────────────────────────

def build_redis_dashboard():
    p = []

    # Row 1 — KPIs
    p.append(row_panel(1, "🗄️ Redis Overview — KPIs", y=0))
    p.append(stat_panel(2, "Redis Status", "frappe_redis_connected", x=0, y=1, w=3, h=4,
        thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
        mappings=[{"type": "value", "options": {"0": {"text": "DOWN"}, "1": {"text": "UP"}}}],
        desc="Redis TCP connectivity check"))
    p.append(stat_panel(3, "Memory Used (MB)", "frappe_redis_memory_mb", x=3, y=1, w=3, h=4, unit="short",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 500}, {"color": "red", "value": 1500}],
        desc="Current Redis memory usage in megabytes"))
    p.append(gauge_panel(4, "Cache Hit Ratio %", "frappe_redis_hit_ratio", x=6, y=1, w=4, h=4,
        min_val=0, max_val=100, unit="percent",
        thresholds=[{"color": "red", "value": None}, {"color": "yellow", "value": 50}, {"color": "green", "value": 80}],
        desc="Cache hit ratio — below 50% means most requests miss cache"))
    p.append(stat_panel(5, "Connected Clients", "frappe_redis_clients", x=10, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 100}, {"color": "red", "value": 500}],
        desc="Current number of connected Redis clients"))
    p.append(stat_panel(6, "Memory Growth /5m (MB)",
        "increase(frappe_redis_memory_mb[5m])", x=13, y=1, w=3, h=4, unit="short",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 50}, {"color": "red", "value": 200}],
        desc="Memory consumed in the last 5 min — positive = growing, negative = keys evicted/expired"))
    p.append(stat_panel(7, "Client Growth /5m",
        "increase(frappe_redis_clients[5m])", x=16, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 20}, {"color": "red", "value": 100}],
        desc="Change in connected clients over 5 minutes"))
    p.append(stat_panel(8, "Redis Error Rate /min",
        'sum(rate({job="frappe", level="ERROR"} |= "redis"[1m]))',
        x=19, y=1, w=3, h=4, unit="ops", ds=LOKI,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 0.05}, {"color": "red", "value": 0.5}],
        desc="Application log lines per minute containing 'redis' at ERROR level"))
    p.append(stat_panel(9, "Exporter Up", "frappe_k6_exporter_up", x=22, y=1, w=2, h=4,
        thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
        mappings=[{"type": "value", "options": {"0": {"text": "DOWN"}, "1": {"text": "UP"}}}]))

    # Row 2 — Memory Analysis
    p.append(row_panel(10, "💾 Memory Analysis", y=5))
    p.append(ts_panel(11, "Redis Memory Usage (MB) Over Time",
        [{"expr": "frappe_redis_memory_mb", "legend": "Memory MB"}],
        x=0, y=6, w=12, h=7, unit="short", min_val=0,
        desc="Memory usage trend — sudden drops = restart or mass key eviction"))
    p.append(ts_panel(12, "Memory Change Rate (MB/min)",
        [{"expr": "rate(frappe_redis_memory_mb[1m]) * 60", "legend": "MB/min growth"}],
        x=12, y=6, w=12, h=7, unit="short",
        desc="Positive = memory growing (new keys), negative = keys expiring/evicted"))

    # Row 3 — Client & Hit Rate Analysis
    p.append(row_panel(20, "🔄 Client & Cache Performance", y=13))
    p.append(ts_panel(21, "Connected Clients Over Time",
        [{"expr": "frappe_redis_clients", "legend": "Clients"}],
        x=0, y=14, w=8, h=7, unit="short", min_val=0,
        desc="Client count trend — spikes correlate with traffic bursts"))
    p.append(ts_panel(22, "Cache Hit Ratio % Over Time",
        [{"expr": "frappe_redis_hit_ratio", "legend": "Hit Ratio %"}],
        x=8, y=14, w=8, h=7, unit="percent", min_val=0,
        desc="Sustained low hit ratio = cache not effective, consider key TTL tuning"))
    p.append(ts_panel(23, "Redis Memory vs System Memory %",
        [
            {"expr": "frappe_redis_memory_mb / 1024", "legend": "Redis (GB)"},
            {"expr": "node_memory_MemTotal_bytes / 1024 / 1024 / 1024", "legend": "Total RAM (GB)"},
            {"expr": "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100", "legend": "RAM Used %"},
        ],
        x=16, y=14, w=8, h=7, unit="short",
        desc="Redis memory consumption relative to total system RAM"))

    # Row 4 — Advanced Trends
    p.append(row_panel(30, "📊 Advanced Trend Analysis", y=21))
    p.append(ts_panel(31, "Redis Memory Delta (5m rolling)",
        [{"expr": "increase(frappe_redis_memory_mb[5m])", "legend": "Memory Δ (5m)"}],
        x=0, y=22, w=8, h=6, unit="short",
        desc="Rolling 5-minute memory change — negative = active eviction"))
    p.append(ts_panel(32, "Hit Ratio Degradation Trend",
        [
            {"expr": "frappe_redis_hit_ratio", "legend": "Hit Ratio %"},
            {"expr": "avg_over_time(frappe_redis_hit_ratio[30m])", "legend": "30m avg"},
        ],
        x=8, y=22, w=8, h=6, unit="percent", min_val=0,
        desc="Compare current hit ratio vs 30-min average to spot degradation"))
    p.append(ts_panel(33, "Redis Health Composite Score",
        [{"expr": "frappe_redis_connected * (frappe_redis_hit_ratio / 100)", "legend": "Health Score (0-1)"}],
        x=16, y=22, w=8, h=6, unit="short", min_val=0,
        desc="Composite: 1 = Redis up + perfect hit ratio, 0 = down or no cache hits"))

    # Row 5 — Logs
    p.append(row_panel(40, "📋 Redis Logs", y=28))
    p.append(logs_panel(41, "Application Logs Mentioning Redis (Live)",
        '{job="frappe"} |= "redis"',
        x=0, y=29, w=24, h=8,
        desc="All Frappe log lines containing 'redis' — connection errors, timeouts, etc."))
    p.append(logs_panel(42, "Redis ERROR Events",
        '{job="frappe", level="ERROR"} |= "redis"',
        x=0, y=37, w=12, h=7,
        desc="Error-level log lines mentioning redis"))
    p.append(logs_panel(43, "Cache / Session Warnings",
        '{job="frappe", level="WARNING"} |~ "redis|cache|session"',
        x=12, y=37, w=12, h=7,
        desc="Warning-level logs related to cache and session management"))

    # Row 6 — Log Volume
    p.append(row_panel(50, "📊 Log Volume", y=44))
    p.append(ts_panel(51, "Redis-related Log Rate by Level (lines/min)",
        [{"expr": 'sum by(level)(rate({job="frappe"} |= "redis"[1m]))', "legend": "{{level}}", "ds": LOKI}],
        x=0, y=45, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Lines per minute mentioning redis, broken down by severity"))
    p.append(ts_panel(52, "All Frappe Log Rate by Source",
        [{"expr": 'sum by(log_type)(rate({job="frappe"}[1m]))', "legend": "{{log_type}}", "ds": LOKI}],
        x=12, y=45, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Log volume by source — helps identify which component is loudest"))

    return dashboard_wrapper(
        uid="frappe-k6-redis",
        title="Frappe K6 — Redis Dashboard (Expert)",
        panels=p,
        tags=["frappe", "redis", "cache", "k6"],
        refresh="30s",
    )


# ─── Worker Dashboard ─────────────────────────────────────────────────────────

def build_worker_dashboard():
    p = []

    # Row 1 — KPIs
    p.append(row_panel(1, "⚙️ Worker & Queue Overview — KPIs", y=0))
    p.append(stat_panel(2, "Active Workers", "frappe_worker_count", x=0, y=1, w=3, h=4,
        thresholds=[{"color": "red", "value": None}, {"color": "yellow", "value": 1}, {"color": "green", "value": 3}],
        desc="Number of running Frappe background worker processes"))
    p.append(stat_panel(3, "K6 Active Tests", "frappe_k6_active_runs", x=3, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 3}, {"color": "red", "value": 10}],
        desc="Currently running K6 load test sessions"))
    p.append(stat_panel(4, "Queue: Default", 'frappe_queue_depth{queue="default"}', x=6, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 20}, {"color": "red", "value": 100}],
        desc="Pending jobs in the default queue"))
    p.append(stat_panel(5, "Queue: Long", 'frappe_queue_depth{queue="long"}', x=9, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 10}, {"color": "red", "value": 50}],
        desc="Pending jobs in the long queue (heavy tasks)"))
    p.append(stat_panel(6, "Queue: Short", 'frappe_queue_depth{queue="short"}', x=12, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 30}, {"color": "red", "value": 200}],
        desc="Pending jobs in the short queue (lightweight tasks)"))
    p.append(stat_panel(7, "Total Queue Depth",
        'sum(frappe_queue_depth)', x=15, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 50}, {"color": "red", "value": 200}],
        desc="Sum across all queues — total pending jobs"))
    p.append(stat_panel(8, "Queue / Worker Ratio",
        "sum(frappe_queue_depth) / clamp_min(frappe_worker_count, 1)", x=18, y=1, w=3, h=4,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 20}, {"color": "red", "value": 100}],
        desc="Jobs per worker — high ratio = workers are backlogged"))
    p.append(stat_panel(9, "Worker Error Rate /min",
        'sum(rate({job="frappe", log_type=~"worker|worker_error", level="ERROR"}[1m]))',
        x=21, y=1, w=3, h=4, unit="ops", ds=LOKI,
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 0.1}, {"color": "red", "value": 1}],
        desc="Worker error log lines per minute"))

    # Row 2 — Queue Analysis
    p.append(row_panel(10, "📈 Queue Depth Analysis", y=5))
    p.append(ts_panel(11, "Queue Depth Over Time (per queue)",
        [
            {"expr": 'frappe_queue_depth{queue="default"}', "legend": "Default"},
            {"expr": 'frappe_queue_depth{queue="long"}',    "legend": "Long"},
            {"expr": 'frappe_queue_depth{queue="short"}',   "legend": "Short"},
        ],
        x=0, y=6, w=12, h=7, unit="short", min_val=0,
        desc="Per-queue depth trend — identify which queue is backlogged"))
    p.append(ts_panel(12, "Total Queue vs Worker Count",
        [
            {"expr": "sum(frappe_queue_depth)", "legend": "Total Queue Depth"},
            {"expr": "frappe_worker_count * 10", "legend": "Workers × 10 (scaled)"},
        ],
        x=12, y=6, w=12, h=7, unit="short", min_val=0,
        desc="Visual correlation of queue load vs available worker capacity"))

    # Row 3 — Processing Rate & Efficiency
    p.append(row_panel(20, "⚡ Processing Rate & Worker Efficiency", y=13))
    p.append(ts_panel(21, "Queue Growth Rate (jobs/min)",
        [
            {"expr": 'rate(frappe_queue_depth{queue="default"}[1m]) * 60', "legend": "Default Δ/min"},
            {"expr": 'rate(frappe_queue_depth{queue="long"}[1m]) * 60',    "legend": "Long Δ/min"},
            {"expr": 'rate(frappe_queue_depth{queue="short"}[1m]) * 60',   "legend": "Short Δ/min"},
        ],
        x=0, y=14, w=8, h=7, unit="ops",
        desc="Rate of change — negative = workers consuming faster than producing"))
    p.append(ts_panel(22, "Worker Utilisation (Queue/Worker ratio)",
        [{"expr": "sum(frappe_queue_depth) / clamp_min(frappe_worker_count, 1)", "legend": "Jobs/Worker"}],
        x=8, y=14, w=8, h=7, unit="short", min_val=0,
        desc="Jobs per worker — sustained high value = need more workers"))
    p.append(ts_panel(23, "K6 Tests & Worker Activity Correlation",
        [
            {"expr": "frappe_k6_active_runs",  "legend": "K6 Active Tests"},
            {"expr": "frappe_worker_count",     "legend": "Active Workers"},
            {"expr": "sum(frappe_queue_depth)", "legend": "Total Queue"},
        ],
        x=16, y=14, w=8, h=7, unit="short", min_val=0,
        desc="How load tests impact queue depth and worker load"))

    # Row 4 — Scheduler Analysis
    p.append(row_panel(25, "🕐 Scheduler & Job Analysis", y=21))
    p.append(ts_panel(26, "Scheduler Log Rate (lines/min)",
        [{"expr": 'sum by(level)(rate({job="frappe", log_type="scheduler"}[1m]))', "legend": "{{level}}", "ds": LOKI}],
        x=0, y=22, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Scheduler activity — high rate at INFO = normal, ERROR rate = scheduler failures"))
    p.append(ts_panel(27, "Worker Log Rate by Level",
        [{"expr": 'sum by(level)(rate({job="frappe", log_type=~"worker.*"}[1m]))', "legend": "{{level}}", "ds": LOKI}],
        x=12, y=22, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Worker log volume by severity — rising ERROR rate = failed jobs"))

    # Row 5 — Live Worker Logs
    p.append(row_panel(30, "📋 Live Worker Logs", y=28))
    p.append(logs_panel(31, "Worker Logs (Live)",
        '{job="frappe", log_type="worker"}',
        x=0, y=29, w=12, h=9,
        desc="Real-time stream from worker.log — shows job execution and errors"))
    p.append(logs_panel(32, "Scheduler Logs (Live)",
        '{job="frappe", log_type="scheduler"}',
        x=12, y=29, w=12, h=9,
        desc="Real-time stream from scheduler.log — scheduled task execution"))
    p.append(logs_panel(33, "Worker ERROR Logs",
        '{job="frappe", log_type=~"worker.*", level="ERROR"}',
        x=0, y=38, w=12, h=8,
        desc="Filtered view: only ERROR-level lines from all worker log sources"))
    p.append(logs_panel(34, "Failed Job Indicators",
        '{job="frappe"} |~ "failed|Failed|traceback|Traceback|Exception"',
        x=12, y=38, w=12, h=8,
        desc="Log lines containing failure keywords — identify failed background jobs"))

    return dashboard_wrapper(
        uid="frappe-k6-workers",
        title="Frappe K6 — Worker & Queue Dashboard (Expert)",
        panels=p,
        tags=["frappe", "workers", "queue", "k6"],
        refresh="30s",
    )


# ─── Node Dashboard ───────────────────────────────────────────────────────────

def build_node_dashboard():
    p = []

    # Row 1 — KPI Overview
    p.append(row_panel(1, "🖥️ Server Overview — KPIs", y=0))
    p.append(gauge_panel(2, "CPU Usage %",
        "100 - (avg(rate(node_cpu_seconds_total{mode='idle'}[2m])) * 100)",
        x=0, y=1, w=4, h=5, unit="percent"))
    p.append(gauge_panel(3, "Memory Usage %",
        "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100",
        x=4, y=1, w=4, h=5, unit="percent"))
    p.append(gauge_panel(4, "Disk Usage %",
        "(1 - node_filesystem_avail_bytes{mountpoint='/',fstype!='tmpfs'} / node_filesystem_size_bytes{mountpoint='/',fstype!='tmpfs'}) * 100",
        x=8, y=1, w=4, h=5, unit="percent"))
    p.append(stat_panel(5, "Load Avg 1m", "node_load1", x=12, y=1, w=3, h=2, unit="short",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 2}, {"color": "red", "value": 4}]))
    p.append(stat_panel(6, "Load Avg 5m", "node_load5", x=15, y=1, w=3, h=2, unit="short",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 2}, {"color": "red", "value": 4}]))
    p.append(stat_panel(7, "Load Avg 15m", "node_load15", x=18, y=1, w=3, h=2, unit="short",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 2}, {"color": "red", "value": 4}]))
    p.append(stat_panel(8, "System Uptime",
        "time() - node_boot_time_seconds", x=21, y=1, w=3, h=2, unit="s",
        thresholds=[{"color": "green", "value": None}], color_mode="none", graph_mode="none"))
    p.append(stat_panel(9, "CPU Cores", "count(node_cpu_seconds_total{mode='idle'})",
        x=12, y=3, w=3, h=3, unit="short",
        thresholds=[{"color": "green", "value": None}], color_mode="none"))
    p.append(stat_panel(10, "Total RAM",
        "node_memory_MemTotal_bytes", x=15, y=3, w=3, h=3, unit="bytes",
        thresholds=[{"color": "green", "value": None}], color_mode="none"))
    p.append(stat_panel(11, "Memory Free",
        "node_memory_MemAvailable_bytes", x=18, y=3, w=3, h=3, unit="bytes",
        thresholds=[{"color": "red", "value": None}, {"color": "yellow", "value": 1073741824}, {"color": "green", "value": 2147483648}]))
    p.append(stat_panel(12, "Open File Descriptors",
        "node_filefd_allocated", x=21, y=3, w=3, h=3, unit="short",
        thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 65536}, {"color": "red", "value": 524288}]))

    # Row 2 — CPU Analysis
    p.append(row_panel(20, "⚡ CPU Deep Analysis", y=6))
    p.append(ts_panel(21, "CPU Usage by Mode (%)",
        [
            {"expr": "avg by(mode)(rate(node_cpu_seconds_total{mode!='idle'}[2m])) * 100",
             "legend": "{{mode}}"},
        ],
        x=0, y=7, w=12, h=7, unit="percent", min_val=0, stack=True,
        desc="CPU breakdown: user (app work), system (kernel), iowait (disk bottleneck), steal (VM), irq, softirq"))
    p.append(ts_panel(22, "Load Average Trend (1m / 5m / 15m)",
        [
            {"expr": "node_load1",  "legend": "Load 1m"},
            {"expr": "node_load5",  "legend": "Load 5m"},
            {"expr": "node_load15", "legend": "Load 15m"},
            {"expr": "count(node_cpu_seconds_total{mode='idle'})", "legend": "CPU Cores"},
        ],
        x=12, y=7, w=12, h=7, unit="short", min_val=0,
        desc="Load > CPU cores = overloaded. Load 1m > 15m = load increasing"))
    p.append(ts_panel(23, "CPU I/O Wait % (Disk Bottleneck Indicator)",
        [{"expr": "avg(rate(node_cpu_seconds_total{mode='iowait'}[2m])) * 100", "legend": "iowait %"}],
        x=0, y=14, w=8, h=6, unit="percent", min_val=0,
        desc="High iowait = CPU stalled waiting for disk I/O"))
    p.append(ts_panel(24, "Context Switches & Interrupts /s",
        [
            {"expr": "rate(node_context_switches_total[2m])", "legend": "Context Switches/s"},
            {"expr": "rate(node_intr_total[2m])",             "legend": "Interrupts/s"},
        ],
        x=8, y=14, w=8, h=6, unit="ops", min_val=0,
        desc="Very high context switches = many threads competing for CPU"))
    p.append(ts_panel(25, "CPU Steal & Throttle (VM/Cloud health)",
        [
            {"expr": "avg(rate(node_cpu_seconds_total{mode='steal'}[2m])) * 100",   "legend": "Steal %"},
            {"expr": "avg(rate(node_cpu_seconds_total{mode='softirq'}[2m])) * 100", "legend": "SoftIRQ %"},
            {"expr": "avg(rate(node_cpu_seconds_total{mode='irq'}[2m])) * 100",     "legend": "IRQ %"},
        ],
        x=16, y=14, w=8, h=6, unit="percent", min_val=0,
        desc="Steal % > 5% = noisy neighbour in VM environment"))

    # Row 3 — Memory Analysis
    p.append(row_panel(30, "💾 Memory Deep Analysis", y=20))
    p.append(ts_panel(31, "Memory Breakdown Over Time",
        [
            {"expr": "node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes", "legend": "Used"},
            {"expr": "node_memory_Buffers_bytes",  "legend": "Buffers"},
            {"expr": "node_memory_Cached_bytes",   "legend": "Cached"},
            {"expr": "node_memory_MemAvailable_bytes", "legend": "Available"},
        ],
        x=0, y=21, w=12, h=7, unit="bytes", min_val=0, stack=False,
        desc="Memory distribution — Buffers+Cached can be reclaimed. True free = Available"))
    p.append(ts_panel(32, "Swap Usage",
        [
            {"expr": "node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes", "legend": "Swap Used"},
            {"expr": "node_memory_SwapTotal_bytes", "legend": "Swap Total"},
        ],
        x=12, y=21, w=8, h=7, unit="bytes", min_val=0,
        desc="Swap usage — any swap = system is memory-constrained"))
    p.append(ts_panel(33, "Page Faults & Memory Pressure",
        [
            {"expr": "rate(node_vmstat_pgfault[2m])",    "legend": "Minor Faults/s"},
            {"expr": "rate(node_vmstat_pgmajfault[2m])", "legend": "Major Faults/s (slow)"},
        ],
        x=20, y=21, w=4, h=7, unit="ops", min_val=0,
        desc="Major page faults = process needed memory from disk (slow path)"))
    p.append(ts_panel(34, "Memory Pages In/Out /s",
        [
            {"expr": "rate(node_vmstat_pgpgin[2m])",  "legend": "Pages In/s"},
            {"expr": "rate(node_vmstat_pgpgout[2m])", "legend": "Pages Out/s"},
        ],
        x=0, y=28, w=8, h=6, unit="ops", min_val=0,
        desc="High pages-out while memory is full = active swapping"))

    # Row 4 — Disk Analysis
    p.append(row_panel(40, "💿 Disk & Filesystem Analysis", y=28))
    p.append(ts_panel(41, "Disk I/O Throughput (bytes/s)",
        [
            {"expr": "rate(node_disk_read_bytes_total[2m])",    "legend": "Read {{device}}"},
            {"expr": "rate(node_disk_written_bytes_total[2m])", "legend": "Write {{device}}"},
        ],
        x=8, y=29, w=8, h=7, unit="Bps", min_val=0,
        desc="Read/write throughput per disk device"))
    p.append(ts_panel(42, "Disk IOPS (operations/s)",
        [
            {"expr": "rate(node_disk_reads_completed_total[2m])",  "legend": "Reads/s {{device}}"},
            {"expr": "rate(node_disk_writes_completed_total[2m])", "legend": "Writes/s {{device}}"},
        ],
        x=16, y=29, w=8, h=7, unit="ops", min_val=0,
        desc="I/O operations per second — high IOPS with high latency = saturation"))
    p.append(ts_panel(43, "Filesystem Usage % per Mount",
        [{"expr": "(1 - node_filesystem_avail_bytes{fstype!~'tmpfs|overlay'} / node_filesystem_size_bytes{fstype!~'tmpfs|overlay'}) * 100",
          "legend": "{{mountpoint}}"}],
        x=0, y=29, w=8, h=7, unit="percent", min_val=0,
        desc="Disk space usage across all mounted filesystems"))
    p.append(ts_panel(44, "Disk I/O Latency (avg ms per op)",
        [
            {"expr": "rate(node_disk_read_time_seconds_total[2m]) / clamp_min(rate(node_disk_reads_completed_total[2m]), 1) * 1000",
             "legend": "Read Latency ms {{device}}"},
            {"expr": "rate(node_disk_write_time_seconds_total[2m]) / clamp_min(rate(node_disk_writes_completed_total[2m]), 1) * 1000",
             "legend": "Write Latency ms {{device}}"},
        ],
        x=0, y=36, w=12, h=6, unit="ms", min_val=0,
        desc="Average latency per I/O operation — above 20ms for HDD or 5ms for SSD is concerning"))
    p.append(ts_panel(45, "Disk Queue Depth (I/Os in flight)",
        [{"expr": "node_disk_io_now", "legend": "{{device}}"}],
        x=12, y=36, w=12, h=6, unit="short", min_val=0,
        desc="Concurrent I/Os — sustained > 1 per device = I/O saturation"))

    # Row 5 — Network Analysis
    p.append(row_panel(50, "🌐 Network Analysis", y=42))
    p.append(ts_panel(51, "Network Throughput (bytes/s)",
        [
            {"expr": "rate(node_network_receive_bytes_total{device!='lo'}[2m])",  "legend": "RX {{device}}"},
            {"expr": "rate(node_network_transmit_bytes_total{device!='lo'}[2m])", "legend": "TX {{device}}"},
        ],
        x=0, y=43, w=12, h=7, unit="Bps",
        desc="Network receive/transmit throughput excluding loopback"))
    p.append(ts_panel(52, "Network Packets /s",
        [
            {"expr": "rate(node_network_receive_packets_total{device!='lo'}[2m])",  "legend": "RX pkts/s {{device}}"},
            {"expr": "rate(node_network_transmit_packets_total{device!='lo'}[2m])", "legend": "TX pkts/s {{device}}"},
        ],
        x=12, y=43, w=12, h=7, unit="pps",
        desc="Packets per second — high packets with low bytes = many small transactions"))
    p.append(ts_panel(53, "Network Errors & Drops /s",
        [
            {"expr": "rate(node_network_receive_errs_total[2m])",   "legend": "RX Errors/s {{device}}"},
            {"expr": "rate(node_network_transmit_errs_total[2m])",  "legend": "TX Errors/s {{device}}"},
            {"expr": "rate(node_network_receive_drop_total[2m])",   "legend": "RX Drops/s {{device}}"},
            {"expr": "rate(node_network_transmit_drop_total[2m])",  "legend": "TX Drops/s {{device}}"},
        ],
        x=0, y=50, w=12, h=6, unit="ops", min_val=0,
        desc="Any persistent errors/drops indicate NIC or cable/driver issue"))
    p.append(ts_panel(54, "TCP Connection States",
        [
            {"expr": "node_sockstat_TCP_inuse",   "legend": "In Use"},
            {"expr": "node_sockstat_TCP_alloc",   "legend": "Allocated"},
            {"expr": "node_sockstat_TCP_tw",      "legend": "TIME_WAIT"},
            {"expr": "node_sockstat_TCP6_inuse",  "legend": "IPv6 In Use"},
        ],
        x=12, y=50, w=12, h=6, unit="short", min_val=0,
        desc="High TIME_WAIT = many short-lived connections (HTTP). High allocated = connection pressure"))

    # Row 6 — System Resources
    p.append(row_panel(60, "🔧 System Resources", y=56))
    p.append(ts_panel(61, "Open File Descriptors",
        [
            {"expr": "node_filefd_allocated", "legend": "Allocated FDs"},
            {"expr": "node_filefd_maximum",   "legend": "Max FDs"},
        ],
        x=0, y=57, w=8, h=6, unit="short", min_val=0,
        desc="Approaching max FDs causes EMFILE errors — tune fs.file-max if needed"))
    p.append(ts_panel(62, "Running & Blocked Processes",
        [
            {"expr": "node_procs_running", "legend": "Running"},
            {"expr": "node_procs_blocked", "legend": "Blocked (on I/O)"},
        ],
        x=8, y=57, w=8, h=6, unit="short", min_val=0,
        desc="Blocked processes = waiting for disk/network I/O. High blocked = I/O bottleneck"))
    p.append(ts_panel(63, "Network Sockets (TCP + UDP)",
        [
            {"expr": "node_sockstat_TCP_alloc",  "legend": "TCP Allocated"},
            {"expr": "node_sockstat_TCP_tw",     "legend": "TCP TIME_WAIT"},
            {"expr": "node_sockstat_UDP_inuse",  "legend": "UDP In Use"},
        ],
        x=16, y=57, w=8, h=6, unit="short", min_val=0,
        desc="Socket resource utilisation"))

    # Row 7 — Logs
    p.append(row_panel(70, "📋 System Logs", y=63))
    p.append(logs_panel(71, "System Log (syslog)",
        '{job="syslog"}',
        x=0, y=64, w=24, h=8,
        desc="System-level log stream — kernel messages, service starts/stops, OOM killer events"))
    p.append(logs_panel(72, "Application ERROR Logs",
        '{job="frappe", level="ERROR"}',
        x=0, y=72, w=12, h=7,
        desc="All application error logs across all Frappe components"))
    p.append(logs_panel(73, "Bench / Gunicorn Log",
        '{job="frappe", log_type="bench"}',
        x=12, y=72, w=12, h=7,
        desc="bench.log — Gunicorn worker output, HTTP access, startup messages"))

    # Row 8 — System Log Volume
    p.append(row_panel(80, "📊 System Log Volume", y=79))
    p.append(ts_panel(81, "Syslog Rate (lines/min)",
        [{"expr": 'rate({job="syslog"}[1m])', "legend": "syslog/min", "ds": LOKI}],
        x=0, y=80, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Syslog volume — spike = system event (OOM, service restart, etc.)"))
    p.append(ts_panel(82, "All Frappe Log Rate by Source (lines/min)",
        [{"expr": 'sum by(log_type)(rate({job="frappe"}[1m]))', "legend": "{{log_type}}", "ds": LOKI}],
        x=12, y=80, w=12, h=6, unit="short", min_val=0, ds=LOKI,
        desc="Log volume per source type"))

    return dashboard_wrapper(
        uid="frappe-k6-node",
        title="Frappe K6 — Node / Server Dashboard (Expert)",
        panels=p,
        tags=["frappe", "node", "system", "k6"],
        refresh="30s",
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def _build_remote_server_dashboard():
    from gen_dashboards import PROM, NAV_LINKS, row_panel, stat_panel, gauge_panel, ts_panel  # noqa
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "gen_remote",
        os.path.join(os.path.dirname(__file__), "gen_remote_dashboard.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_remote_server_dashboard()


DASHBOARDS = {
    "frappe_k6_remote_server_dashboard.json": _build_remote_server_dashboard,
    "frappe_k6_multi_dashboard.json":          build_multi_server_dashboard,
    "frappe_k6_db_dashboard.json":             build_database_dashboard,
    "frappe_k6_redis_dashboard.json":          build_redis_dashboard,
    "frappe_k6_worker_dashboard.json":         build_worker_dashboard,
    "frappe_k6_node_dashboard.json":           build_node_dashboard,
}


def main():
    for filename, builder in DASHBOARDS.items():
        dash = builder()
        path = os.path.join(SETUP_DIR, filename)
        with open(path, "w") as f:
            json.dump(dash, f, indent=2)
        panels = len(dash["panels"])
        print(f"  ✓  {filename}  ({panels} panels)")


if __name__ == "__main__":
    print("Generating expert-level Grafana dashboards …")
    main()
    print("Done.")

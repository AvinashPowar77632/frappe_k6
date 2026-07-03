#!/usr/bin/env python3
"""Generate frappe_k6_remote_server_dashboard.json — standalone runner."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from gen_dashboards import PROM, LOKI, NAV_LINKS, row_panel, stat_panel, gauge_panel, ts_panel

SETUP_DIR = os.path.dirname(os.path.abspath(__file__))


def build_remote_server_dashboard():
    p = []
    S = 'server_name=~"$server"'

    # ── Row 0: System Overview ────────────────────────────────────────────
    p.append(row_panel(1, "🖥️  $server  ·  System Overview", y=0))
    p.append(stat_panel(
        2, "$server — Status", f'up{{job="node",{S}}}',
        x=0, y=1, w=3, h=4,
        thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
        mappings=[{"type": "value", "options": {
            "0": {"text": "OFFLINE", "color": "red",   "index": 0},
            "1": {"text": "ONLINE",  "color": "green", "index": 1},
        }}],
        color_mode="background", graph_mode="none",
        desc="node_exporter reachability",
    ))
    for pid, title, legend, x, color in [
        (3, "Hostname",     "{{nodename}}",           3,  "semi-dark-blue"),
        (4, "OS & Kernel",  "{{sysname}} {{release}}", 7,  "purple"),
        (5, "Architecture", "{{machine}}",             12, "orange"),
    ]:
        p.append({
            "id": pid, "type": "stat", "title": title, "description": "",
            "gridPos": {"h": 4, "w": 4 if pid == 3 else (5 if pid == 4 else 3), "x": x, "y": 1},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"]},
                        "colorMode": "none", "graphMode": "none", "textMode": "name"},
            "fieldConfig": {"defaults": {"color": {"mode": "fixed", "fixedColor": color}}},
            "targets": [{"datasource": PROM, "expr": f'node_uname_info{{{S}}}',
                         "legendFormat": legend, "refId": "A"}],
            "datasource": PROM,
        })
    p.append(stat_panel(6, "Uptime",     f'time() - node_boot_time_seconds{{{S}}}',
                        x=15, y=1, w=4, h=4, unit="s",
                        thresholds=[{"color": "green", "value": None}],
                        color_mode="none", graph_mode="none"))
    p.append(stat_panel(7, "CPU Cores",  f'count(node_cpu_seconds_total{{mode="idle",{S}}})',
                        x=19, y=1, w=2, h=4,
                        thresholds=[{"color": "blue", "value": None}],
                        color_mode="none", graph_mode="none"))
    p.append(stat_panel(8, "Total RAM",  f'node_memory_MemTotal_bytes{{{S}}}',
                        x=21, y=1, w=3, h=4, unit="bytes",
                        thresholds=[{"color": "blue", "value": None}],
                        color_mode="none", graph_mode="none"))

    # ── Row 1: CPU Overview ───────────────────────────────────────────────
    p.append(row_panel(9, "⚡  CPU Overview  —  $server", y=5))
    p.append(gauge_panel(
        10, "CPU Utilization",
        f'100 - (avg(irate(node_cpu_seconds_total{{mode="idle",{S}}}[5m])) * 100)',
        x=0, y=6, w=4, h=8, unit="percent",
        desc="Average CPU utilisation across all cores",
    ))
    p.append(ts_panel(
        11, "CPU Usage by Mode",
        [
            {"expr": f'avg(irate(node_cpu_seconds_total{{mode="user",{S}}}[5m]))*100',    "legend": "User"},
            {"expr": f'avg(irate(node_cpu_seconds_total{{mode="system",{S}}}[5m]))*100',  "legend": "System"},
            {"expr": f'avg(irate(node_cpu_seconds_total{{mode="iowait",{S}}}[5m]))*100',  "legend": "I/O Wait"},
            {"expr": f'avg(irate(node_cpu_seconds_total{{mode="steal",{S}}}[5m]))*100',   "legend": "Steal"},
            {"expr": f'avg(irate(node_cpu_seconds_total{{mode="softirq",{S}}}[5m]))*100', "legend": "SoftIRQ"},
            {"expr": f'avg(irate(node_cpu_seconds_total{{mode="irq",{S}}}[5m]))*100',     "legend": "IRQ"},
            {"expr": f'avg(irate(node_cpu_seconds_total{{mode="nice",{S}}}[5m]))*100',    "legend": "Nice"},
        ],
        x=4, y=6, w=12, h=8, unit="percent", min_val=0, stack=True,
        desc="Stacked CPU breakdown — iowait+steal indicate external bottlenecks",
    ))
    p.append(ts_panel(
        12, "Load Average vs CPU Cores",
        [
            {"expr": f'node_load1{{{S}}}',  "legend": "1m"},
            {"expr": f'node_load5{{{S}}}',  "legend": "5m"},
            {"expr": f'node_load15{{{S}}}', "legend": "15m"},
            {"expr": f'count(node_cpu_seconds_total{{mode="idle",{S}}})', "legend": "CPU Cores"},
        ],
        x=16, y=6, w=8, h=8, unit="short", min_val=0,
        desc="Load above core count = overloaded; watch 15m trend",
    ))

    # ── Row 2: Per-Core ───────────────────────────────────────────────────
    p.append(row_panel(13, "🔲  Per-Core CPU  —  $server", y=14))
    p.append(ts_panel(
        14, "Per-Core CPU Utilization %",
        [{"expr": f'100-(irate(node_cpu_seconds_total{{mode="idle",{S}}}[5m])*100)',
          "legend": "Core {{cpu}}"}],
        x=0, y=15, w=24, h=7, unit="percent", min_val=0,
        desc="Hot spots on specific cores indicate single-threaded bottlenecks",
    ))

    # ── Row 3: CPU Detail Stats ───────────────────────────────────────────
    p.append(row_panel(15, "📊  CPU Detailed Metrics  —  $server", y=22))
    for pid, title, mode, x, thresh in [
        (16, "User %",     "user",    0,  [{"color":"green","value":None},{"color":"yellow","value":60},{"color":"red","value":85}]),
        (17, "System %",   "system",  4,  [{"color":"green","value":None},{"color":"yellow","value":30},{"color":"red","value":60}]),
        (18, "I/O Wait %", "iowait",  8,  [{"color":"green","value":None},{"color":"yellow","value":10},{"color":"red","value":25}]),
        (19, "Steal %",    "steal",   12, [{"color":"green","value":None},{"color":"yellow","value":5}, {"color":"red","value":15}]),
        (20, "Idle %",     "idle",    16, [{"color":"red","value":None},  {"color":"yellow","value":20},{"color":"green","value":40}]),
        (21, "SoftIRQ %",  "softirq", 20, [{"color":"green","value":None},{"color":"yellow","value":5}, {"color":"red","value":20}]),
    ]:
        p.append(stat_panel(pid, title,
                            f'avg(irate(node_cpu_seconds_total{{mode="{mode}",{S}}}[5m]))*100',
                            x=x, y=23, w=4, h=3, unit="percent",
                            thresholds=thresh, color_mode="background", graph_mode="area"))
    p.append(ts_panel(22, "CPU Frequency per Core",
        [{"expr": f'node_cpu_scaling_frequency_hertz{{{S}}}', "legend": "Core {{cpu}}"}],
        x=0, y=26, w=12, h=6, unit="hertz",
        desc="Sustained values below max indicate thermal throttling"))
    p.append(ts_panel(23, "Context Switches / s",
        [{"expr": f'rate(node_context_switches_total{{{S}}}[5m])', "legend": "ctx/s"}],
        x=12, y=26, w=12, h=6, unit="short", min_val=0,
        desc="High values indicate CPU scheduling pressure"))

    # ── Row 4: Memory ─────────────────────────────────────────────────────
    p.append(row_panel(24, "💾  Memory  —  $server", y=32))
    p.append(gauge_panel(
        25, "Memory Utilization",
        f'(1 - node_memory_MemAvailable_bytes{{{S}}} / node_memory_MemTotal_bytes{{{S}}}) * 100',
        x=0, y=33, w=4, h=8, unit="percent",
        desc="MemAvailable accounts for reclaimable cache — more accurate than MemFree",
    ))
    p.append(ts_panel(26, "Memory Breakdown",
        [
            {"expr": f'node_memory_MemTotal_bytes{{{S}}}-node_memory_MemFree_bytes{{{S}}}-node_memory_Buffers_bytes{{{S}}}-node_memory_Cached_bytes{{{S}}}',
             "legend": "Used"},
            {"expr": f'node_memory_Buffers_bytes{{{S}}}', "legend": "Buffers"},
            {"expr": f'node_memory_Cached_bytes{{{S}}}',  "legend": "Cached"},
            {"expr": f'node_memory_MemFree_bytes{{{S}}}', "legend": "Free"},
        ],
        x=4, y=33, w=12, h=8, unit="bytes", min_val=0, stack=True,
        desc="Linux allocates spare RAM for cache — watch Used, not Free"))
    p.append(ts_panel(27, "Swap Usage",
        [
            {"expr": f'node_memory_SwapTotal_bytes{{{S}}}-node_memory_SwapFree_bytes{{{S}}}',
             "legend": "Swap Used"},
            {"expr": f'node_memory_SwapTotal_bytes{{{S}}}', "legend": "Swap Total"},
        ],
        x=16, y=33, w=8, h=8, unit="bytes", min_val=0,
        desc="Active swapping indicates memory pressure"))
    for pid, title, expr, unit, x in [
        (28, "Total RAM",  f'node_memory_MemTotal_bytes{{{S}}}',     "bytes",  0),
        (29, "Used RAM",   f'node_memory_MemTotal_bytes{{{S}}}-node_memory_MemAvailable_bytes{{{S}}}', "bytes", 4),
        (30, "Available",  f'node_memory_MemAvailable_bytes{{{S}}}', "bytes",  8),
        (31, "Cached",     f'node_memory_Cached_bytes{{{S}}}',       "bytes", 12),
        (32, "Buffers",    f'node_memory_Buffers_bytes{{{S}}}',      "bytes", 16),
        (33, "Swap Used",  f'node_memory_SwapTotal_bytes{{{S}}}-node_memory_SwapFree_bytes{{{S}}}',
         "bytes", 20),
    ]:
        p.append(stat_panel(pid, title, expr, x=x, y=41, w=4, h=3, unit=unit,
                            thresholds=[{"color": "green", "value": None}],
                            color_mode="none", graph_mode="none"))

    # ── Row 5: Disk ───────────────────────────────────────────────────────
    p.append(row_panel(34, "💿  Disk  —  $server", y=44))
    p.append({
        "id": 35, "type": "bargauge",
        "title": "Disk Space Usage % by Mount",
        "description": "Fill level per filesystem",
        "gridPos": {"h": 10, "w": 8, "x": 0, "y": 45},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]},
                    "orientation": "horizontal", "displayMode": "gradient",
                    "showUnfilled": True, "valueMode": "color"},
        "fieldConfig": {"defaults": {
            "unit": "percent", "min": 0, "max": 100,
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "green",  "value": None},
                {"color": "yellow", "value": 70},
                {"color": "orange", "value": 85},
                {"color": "red",    "value": 95},
            ]},
        }},
        "targets": [{"datasource": PROM,
                     "expr": f'(1-node_filesystem_avail_bytes{{fstype!~"tmpfs|overlay|devtmpfs",{S}}}/node_filesystem_size_bytes{{fstype!~"tmpfs|overlay|devtmpfs",{S}}})*100',
                     "legendFormat": "{{mountpoint}}", "refId": "A", "instant": True}],
        "datasource": PROM,
    })
    p.append({
        "id": 36, "type": "bargauge",
        "title": "Free Disk Space by Mount",
        "description": "Available bytes per filesystem",
        "gridPos": {"h": 10, "w": 8, "x": 8, "y": 45},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]},
                    "orientation": "horizontal", "displayMode": "gradient",
                    "showUnfilled": True, "valueMode": "color"},
        "fieldConfig": {"defaults": {
            "unit": "bytes", "min": 0,
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "red",    "value": None},
                {"color": "orange", "value": 1073741824},
                {"color": "yellow", "value": 5368709120},
                {"color": "green",  "value": 10737418240},
            ]},
        }},
        "targets": [{"datasource": PROM,
                     "expr": f'node_filesystem_avail_bytes{{fstype!~"tmpfs|overlay|devtmpfs",{S}}}',
                     "legendFormat": "{{mountpoint}}", "refId": "A", "instant": True}],
        "datasource": PROM,
    })
    p.append(ts_panel(37, "Disk I/O Throughput",
        [
            {"expr": f'rate(node_disk_read_bytes_total{{{S}}}[5m])',    "legend": "↓ Read {{device}}"},
            {"expr": f'rate(node_disk_written_bytes_total{{{S}}}[5m])', "legend": "↑ Write {{device}}"},
        ],
        x=16, y=45, w=8, h=10, unit="Bps", min_val=0,
        desc="Disk throughput per block device"))
    p.append(ts_panel(38, "Disk IOPS",
        [
            {"expr": f'rate(node_disk_reads_completed_total{{{S}}}[5m])',  "legend": "Read {{device}}"},
            {"expr": f'rate(node_disk_writes_completed_total{{{S}}}[5m])', "legend": "Write {{device}}"},
        ],
        x=0, y=55, w=8, h=7, unit="iops", min_val=0,
        desc="I/O ops/s — SSD: >50k normal, HDD: >200 warrants attention"))
    p.append(ts_panel(39, "Disk Average Latency",
        [
            {"expr": f'rate(node_disk_read_time_seconds_total{{{S}}}[5m])/clamp_min(rate(node_disk_reads_completed_total{{{S}}}[5m]),1)',
             "legend": "Read {{device}}"},
            {"expr": f'rate(node_disk_write_time_seconds_total{{{S}}}[5m])/clamp_min(rate(node_disk_writes_completed_total{{{S}}}[5m]),1)',
             "legend": "Write {{device}}"},
        ],
        x=8, y=55, w=8, h=7, unit="s", min_val=0,
        desc="Average I/O latency — HDD>20ms, SSD>5ms, NVMe>1ms warrants investigation"))
    p.append(ts_panel(40, "Disk I/O Utilization %",
        [{"expr": f'rate(node_disk_io_time_seconds_total{{{S}}}[5m])*100', "legend": "{{device}}"}],
        x=16, y=55, w=8, h=7, unit="percent", min_val=0,
        desc="Disk busy time — sustained >80% is a storage bottleneck"))
    p.append(ts_panel(41, "Inode Usage % by Mount",
        [{"expr": f'(1-node_filesystem_files_free{{fstype!~"tmpfs|overlay|devtmpfs",{S}}}/node_filesystem_files{{fstype!~"tmpfs|overlay|devtmpfs",{S}}})*100',
          "legend": "{{mountpoint}}"}],
        x=0, y=62, w=12, h=7, unit="percent", min_val=0,
        desc="Inode exhaustion — can run out before disk space"))
    p.append(ts_panel(42, "Disk Reads/Writes Merged (ops/s)",
        [
            {"expr": f'rate(node_disk_reads_merged_total{{{S}}}[5m])',  "legend": "Merged Reads {{device}}"},
            {"expr": f'rate(node_disk_writes_merged_total{{{S}}}[5m])', "legend": "Merged Writes {{device}}"},
        ],
        x=12, y=62, w=12, h=7, unit="short", min_val=0,
        desc="Kernel merges adjacent I/O ops — high merge rate indicates sequential access patterns"))

    # ── Row 6: Network ────────────────────────────────────────────────────
    p.append(row_panel(43, "🌐  Network  —  $server", y=69))
    p.append(ts_panel(44, "Network Throughput (RX / TX)",
        [
            {"expr": f'rate(node_network_receive_bytes_total{{device=~"$interface",{S}}}[5m])',
             "legend": "↓ RX {{device}}"},
            {"expr": f'-rate(node_network_transmit_bytes_total{{device=~"$interface",{S}}}[5m])',
             "legend": "↑ TX {{device}}"},
        ],
        x=0, y=70, w=12, h=8, unit="Bps",
        desc="RX positive / TX negative mirrored — classic dual-sided bandwidth chart"))
    p.append(ts_panel(45, "Network Packet Rate",
        [
            {"expr": f'rate(node_network_receive_packets_total{{device=~"$interface",{S}}}[5m])',
             "legend": "↓ RX Pkts {{device}}"},
            {"expr": f'-rate(node_network_transmit_packets_total{{device=~"$interface",{S}}}[5m])',
             "legend": "↑ TX Pkts {{device}}"},
        ],
        x=12, y=70, w=12, h=8, unit="pps",
        desc="Packets per second per interface"))
    p.append(ts_panel(46, "Network Errors / s",
        [
            {"expr": f'rate(node_network_receive_errs_total{{device=~"$interface",{S}}}[5m])',
             "legend": "RX Err {{device}}"},
            {"expr": f'rate(node_network_transmit_errs_total{{device=~"$interface",{S}}}[5m])',
             "legend": "TX Err {{device}}"},
        ],
        x=0, y=78, w=8, h=7, unit="short", min_val=0,
        desc="Non-zero error rates indicate hardware or cabling issues"))
    p.append(ts_panel(47, "Packet Drops / s",
        [
            {"expr": f'rate(node_network_receive_drop_total{{device=~"$interface",{S}}}[5m])',
             "legend": "RX Drop {{device}}"},
            {"expr": f'rate(node_network_transmit_drop_total{{device=~"$interface",{S}}}[5m])',
             "legend": "TX Drop {{device}}"},
        ],
        x=8, y=78, w=8, h=7, unit="short", min_val=0,
        desc="RX drops = buffer overflow; TX drops = queue saturation"))
    p.append(stat_panel(48, "24h RX Total",
        f'sum(increase(node_network_receive_bytes_total{{device!="lo",{S}}}[24h]))',
        x=16, y=78, w=4, h=7, unit="bytes",
        thresholds=[{"color": "green", "value": None}],
        color_mode="none", graph_mode="area"))
    p.append(stat_panel(49, "24h TX Total",
        f'sum(increase(node_network_transmit_bytes_total{{device!="lo",{S}}}[24h]))',
        x=20, y=78, w=4, h=7, unit="bytes",
        thresholds=[{"color": "green", "value": None}],
        color_mode="none", graph_mode="area"))

    # ── Row 7: Processes ──────────────────────────────────────────────────
    p.append(row_panel(50, "⚙️  Processes  —  $server", y=85))
    for pid, title, expr, x, thresh in [
        (51, "Running",     f'node_procs_running{{{S}}}',   0,
         [{"color":"green","value":None}]),
        (52, "Blocked",     f'node_procs_blocked{{{S}}}',   4,
         [{"color":"green","value":None},{"color":"yellow","value":5},{"color":"red","value":20}]),
        (53, "Total PIDs",  f'node_processes_pids{{{S}}} or vector(0)', 8,
         [{"color":"green","value":None}]),
        (54, "Zombies",     f'sum(node_processes_state{{state="zombie",{S}}}) or vector(0)', 12,
         [{"color":"green","value":None},{"color":"yellow","value":1},{"color":"red","value":10}]),
        (55, "Fork Rate/s", f'rate(node_forks_total{{{S}}}[5m])', 16,
         [{"color":"green","value":None}]),
        (56, "Threads",     f'node_processes_threads{{{S}}} or vector(0)', 20,
         [{"color":"green","value":None}]),
    ]:
        p.append(stat_panel(pid, title, expr, x=x, y=86, w=4, h=4,
                            thresholds=thresh, color_mode="background", graph_mode="none"))
    p.append(ts_panel(57, "Process State Trend",
        [
            {"expr": f'node_procs_running{{{S}}}', "legend": "Running"},
            {"expr": f'node_procs_blocked{{{S}}}', "legend": "Blocked"},
        ],
        x=0, y=90, w=12, h=7, unit="short", min_val=0,
        desc="Running and blocked process counts over time"))
    p.append(ts_panel(58, "Fork Rate & Thread Count",
        [
            {"expr": f'rate(node_forks_total{{{S}}}[5m])',          "legend": "Fork Rate /s"},
            {"expr": f'node_processes_threads{{{S}}} or vector(0)', "legend": "Threads"},
        ],
        x=12, y=90, w=12, h=7, unit="short", min_val=0,
        desc="Fork rate and thread count over time"))

    # ── Row 8: File Descriptors & System Health ───────────────────────────
    p.append(row_panel(59, "🔧  File Descriptors & System Health  —  $server", y=97))
    for pid, title, expr, unit, x, thresh in [
        (60, "Open FDs",        f'node_filefd_allocated{{{S}}}', "short",   0,
         [{"color":"green","value":None},{"color":"yellow","value":10000},{"color":"red","value":65536}]),
        (61, "Max FDs",         f'node_filefd_maximum{{{S}}}',   "short",   4,
         [{"color":"blue","value":None}]),
        (62, "FD Usage %",
         f'node_filefd_allocated{{{S}}}/node_filefd_maximum{{{S}}}*100',
         "percent", 8,
         [{"color":"green","value":None},{"color":"yellow","value":70},{"color":"red","value":90}]),
        (63, "Interrupts /s",   f'rate(node_intr_total{{{S}}}[5m])',            "short", 12,
         [{"color":"green","value":None}]),
        (64, "Ctx Switches /s", f'rate(node_context_switches_total{{{S}}}[5m])','short', 16,
         [{"color":"green","value":None}]),
        (65, "Scheduled Thds",  f'node_processes_threads{{{S}}} or vector(0)',  "short", 20,
         [{"color":"green","value":None}]),
    ]:
        p.append(stat_panel(pid, title, expr, x=x, y=98, w=4, h=4, unit=unit,
                            thresholds=thresh, color_mode="background", graph_mode="none"))
    p.append(ts_panel(66, "File Descriptor Usage Trend",
        [
            {"expr": f'node_filefd_allocated{{{S}}}', "legend": "Open FDs"},
            {"expr": f'node_filefd_maximum{{{S}}}',   "legend": "Max FDs"},
        ],
        x=0, y=102, w=12, h=7, unit="short", min_val=0,
        desc="Steady FD growth indicates a leak"))
    p.append(ts_panel(67, "Kernel Interrupts & Context Switches",
        [
            {"expr": f'rate(node_intr_total{{{S}}}[5m])',             "legend": "Interrupts/s"},
            {"expr": f'rate(node_context_switches_total{{{S}}}[5m])', "legend": "Context Switches/s"},
        ],
        x=12, y=102, w=12, h=7, unit="short", min_val=0,
        desc="Kernel scheduling activity — useful when diagnosing high system CPU time"))

    # ── Template variables ─────────────────────────────────────────────────
    server_var = {
        "name": "server", "label": "Server", "type": "query",
        "datasource": PROM,
        "definition": 'label_values(up{job="node"}, server_name)',
        "query": {"query": 'label_values(up{job="node"}, server_name)', "refId": "A"},
        "refresh": 2, "includeAll": False, "multi": False,
        "allValue": None, "current": {}, "sort": 1, "hide": 0,
    }
    disk_var = {
        "name": "disk", "label": "Mount Point", "type": "query",
        "datasource": PROM,
        "definition": 'label_values(node_filesystem_size_bytes{fstype!~"tmpfs|overlay|devtmpfs",server_name=~"$server"}, mountpoint)',
        "query": {"query": 'label_values(node_filesystem_size_bytes{fstype!~"tmpfs|overlay|devtmpfs",server_name=~"$server"}, mountpoint)',
                  "refId": "C"},
        "refresh": 2, "includeAll": True, "multi": True,
        "allValue": ".+", "current": {"text": "All", "value": "$__all"}, "sort": 1, "hide": 0,
    }
    interface_var = {
        "name": "interface", "label": "Network Interface", "type": "query",
        "datasource": PROM,
        "definition": 'label_values(node_network_receive_bytes_total{device!="lo",server_name=~"$server"}, device)',
        "query": {"query": 'label_values(node_network_receive_bytes_total{device!="lo",server_name=~"$server"}, device)',
                  "refId": "D"},
        "refresh": 2, "includeAll": True, "multi": True,
        "allValue": ".+", "current": {"text": "All", "value": "$__all"}, "sort": 1, "hide": 0,
    }

    return {
        "id": None, "uid": "frappe-k6-remote",
        "title": "Frappe K6 — Remote Server: $server",
        "tags": ["frappe", "remote-server", "node-exporter", "infrastructure"],
        "timezone": "browser", "schemaVersion": 38,
        "version": 1, "refresh": "30s",
        "time": {"from": "now-3h", "to": "now"}, "timepicker": {},
        "panels": p,
        "links": NAV_LINKS,
        "templating": {"list": [server_var, disk_var, interface_var]},
        "annotations": {"list": []},
    }


if __name__ == "__main__":
    dash = build_remote_server_dashboard()
    out  = os.path.join(SETUP_DIR, "frappe_k6_remote_server_dashboard.json")
    with open(out, "w") as f:
        json.dump(dash, f, indent=2)
    print(f"✓  frappe_k6_remote_server_dashboard.json  ({len(dash['panels'])} panels)")

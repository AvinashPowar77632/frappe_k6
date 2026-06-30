"""
frappe_k6 — plug-and-play install
Automatically sets up k6, node_exporter, Prometheus, Grafana, Monitor Settings,
and sample Load Test Configs when the app is installed on any Frappe site.
"""

import os
import json
import shutil
import socket
import subprocess
import sys
import tarfile
import zipfile
import urllib.request
import urllib.parse

import frappe

# ── Paths ────────────────────────────────────────────────────────────────────
_APP_DIR      = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT     = os.path.abspath(os.path.join(_APP_DIR, ".."))
_BENCH_DIR    = os.path.abspath(os.path.join(_APP_DIR, "../../.."))
_SETUP_DIR    = os.path.join(_APP_DIR, "setup")
_MON_DIR      = os.path.join(os.path.expanduser("~"), "monitoring")
_PROM_DIR     = os.path.join(_MON_DIR, "prometheus")
_NODE_DIR     = os.path.join(_MON_DIR, "node_exporter")
_LOKI_DIR     = os.path.join(_MON_DIR, "loki")
_PROMTAIL_DIR = os.path.join(_MON_DIR, "promtail")

# ── Release versions ─────────────────────────────────────────────────────────
_PROM_VER      = "2.52.0"
_NODE_EXP_VER  = "1.8.1"
_LOKI_VER      = "2.9.10"
_PROMTAIL_VER  = "2.9.10"


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def after_install():
    """Full plug-and-play setup — called automatically by Frappe after install."""
    _log("=" * 62)
    _log("frappe_k6 — Auto-Setup Starting")
    _log("=" * 62)

    server_ip = _detect_server_ip()
    port      = frappe.get_site_config().get("webserver_port", 8000)

    steps = [
        ("Directories",             lambda: _setup_directories()),
        ("Monitor Settings",        lambda: _configure_monitor_settings(server_ip, port)),
        ("Sample Load Test Configs",lambda: _create_sample_configs()),
        ("k6",                      lambda: _install_k6()),
        ("node_exporter",           lambda: _setup_node_exporter()),
        ("Prometheus",              lambda: _setup_prometheus(server_ip, port)),
        ("K6 Exporter",             lambda: _setup_k6_exporter(server_ip, port)),
        ("Loki",                    lambda: _setup_loki()),
        ("Promtail",                lambda: _setup_promtail()),
        ("Grafana",                 lambda: _setup_grafana(server_ip)),
    ]

    results = {}
    for name, fn in steps:
        try:
            _log(f"  → {name} ...")
            fn()
            results[name] = "✅"
        except Exception as exc:
            results[name] = f"⚠️  {exc}"
            _log(f"     ⚠️  {exc}")

    try:
        frappe.db.commit()
    except Exception:
        pass

    _log("=" * 62)
    _log("Setup summary:")
    for name, status in results.items():
        _log(f"  {status}  {name}")
    _log("─" * 62)
    _log(f"  K6 Dashboard : http://{server_ip}:{port}/k6-monitor")
    _log(f"  Grafana      : http://{server_ip}:3000  (admin / admin)")
    _log(f"  Prometheus   : http://{server_ip}:9090")
    _log(f"  Loki         : http://{server_ip}:3100")
    _log(f"  Promtail     : http://{server_ip}:9080/metrics")
    _log("=" * 62)


# ─────────────────────────────────────────────────────────────────────────────
#  Step 1 — Directories
# ─────────────────────────────────────────────────────────────────────────────

def _setup_directories():
    reports_dir = os.path.join(_APP_ROOT, "k6_tests", "reports")
    for d in [
        reports_dir, _MON_DIR, _PROM_DIR, _NODE_DIR,
        os.path.join(_PROM_DIR, "data"),
        _LOKI_DIR,
        os.path.join(_LOKI_DIR, "chunks"),
        os.path.join(_LOKI_DIR, "rules"),
        os.path.join(_LOKI_DIR, "index"),
        os.path.join(_LOKI_DIR, "index_cache"),
        os.path.join(_LOKI_DIR, "compactor"),
        _PROMTAIL_DIR,
    ]:
        os.makedirs(d, exist_ok=True)
    _log(f"     reports → {reports_dir}")
    _log(f"     loki    → {_LOKI_DIR}")
    _log(f"     promtail→ {_PROMTAIL_DIR}")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 2 — Monitor Settings
# ─────────────────────────────────────────────────────────────────────────────

def _configure_monitor_settings(server_ip, port):
    reports_dir = os.path.join(_APP_ROOT, "k6_tests", "reports")
    s = frappe.get_single("Monitor Settings")
    s.site_name        = frappe.local.site
    s.base_url         = f"http://{server_ip}:{port}"
    s.k6_reports_dir   = reports_dir
    s.k6_binary_path   = shutil.which("k6") or "k6"
    s.grafana_enabled  = 1
    s.grafana_url      = f"http://{server_ip}:3000"
    s.prometheus_enabled = 1
    s.prometheus_url   = f"http://{server_ip}:9090"
    s.refresh_interval = 5
    try:
        s.loki_enabled = 1
        s.loki_url     = f"http://{server_ip}:3100"
        s.promtail_url = f"http://{server_ip}:9080"
    except Exception:
        pass
    s.save(ignore_permissions=True)
    frappe.db.commit()
    # Store Grafana password hint in site config for API auth during re-installs
    try:
        site_cfg_path = os.path.join(_BENCH_DIR, "sites", frappe.local.site, "site_config.json")
        if os.path.isfile(site_cfg_path):
            with open(site_cfg_path) as f:
                site_cfg = json.load(f)
            if "grafana_admin_password" not in site_cfg:
                site_cfg["grafana_admin_password"] = "admin"
                with open(site_cfg_path, "w") as f:
                    json.dump(site_cfg, f, indent=1)
    except Exception:
        pass
    _log(f"     site={frappe.local.site}  base_url={s.base_url}")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 3 — Sample Load Test Configs
# ─────────────────────────────────────────────────────────────────────────────

def _create_sample_configs():
    from frappe_k6.api.sample_data import create_sample_configs
    result = create_sample_configs()
    _log(f"     created={len(result['created'])}  skipped={len(result['skipped'])}")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 4 — k6
# ─────────────────────────────────────────────────────────────────────────────

def _install_k6():
    if shutil.which("k6"):
        _log("     already installed: " + _run_cmd(["k6", "version"])[1].split("\n")[0])
        return

    if not shutil.which("apt-get"):
        raise RuntimeError("apt-get not found — install k6 manually from https://k6.io/docs/get-started/installation/")

    _log("     installing k6 via APT …")
    keyrings = "/etc/apt/keyrings"
    _run_sudo(["mkdir", "-p", keyrings])
    rc, _, err = _run_cmd(
        "curl -fsSL https://dl.k6.io/key.gpg | sudo gpg --batch --yes --dearmor "
        f"-o {keyrings}/k6-archive-keyring.gpg",
        shell=True
    )
    if rc != 0:
        raise RuntimeError(f"GPG key import failed: {err}")
    _run_sudo(["bash", "-c",
        f"echo 'deb [signed-by={keyrings}/k6-archive-keyring.gpg] "
        "https://dl.k6.io/deb stable main' > /etc/apt/sources.list.d/k6.list"])
    _run_sudo(["apt-get", "update", "-qq"])
    rc, _, err = _run_sudo(["apt-get", "install", "-y", "k6"])
    if rc != 0:
        raise RuntimeError(f"apt-get install k6 failed: {err}")
    _log("     k6 installed: " + (_run_cmd(["k6", "version"])[1].split("\n")[0]))


# ─────────────────────────────────────────────────────────────────────────────
#  Step 5 — node_exporter
# ─────────────────────────────────────────────────────────────────────────────

def _setup_node_exporter():
    binary = os.path.join(_NODE_DIR, "node_exporter")

    if not os.path.isfile(binary):
        _log(f"     downloading node_exporter v{_NODE_EXP_VER} …")
        url = (f"https://github.com/prometheus/node_exporter/releases/download/"
               f"v{_NODE_EXP_VER}/node_exporter-{_NODE_EXP_VER}.linux-amd64.tar.gz")
        _download_and_extract(url, _NODE_DIR, f"node_exporter-{_NODE_EXP_VER}.linux-amd64/node_exporter")

    # systemd service
    svc_name = "node_exporter"
    if not _service_active(svc_name):
        svc_content = f"""[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
User={os.environ.get('USER', 'erpadmin')}
ExecStart={binary} --web.listen-address=0.0.0.0:9100
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
"""
        _install_systemd_service(svc_name, svc_content)

    _log(f"     node_exporter: {_service_status(svc_name)}")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 6 — Prometheus
# ─────────────────────────────────────────────────────────────────────────────

def _setup_prometheus(server_ip, port):
    binary = os.path.join(_PROM_DIR, "prometheus")

    if not os.path.isfile(binary):
        _log(f"     downloading Prometheus v{_PROM_VER} …")
        url = (f"https://github.com/prometheus/prometheus/releases/download/"
               f"v{_PROM_VER}/prometheus-{_PROM_VER}.linux-amd64.tar.gz")
        for member in [f"prometheus-{_PROM_VER}.linux-amd64/prometheus",
                       f"prometheus-{_PROM_VER}.linux-amd64/promtool"]:
            _download_and_extract(url, _PROM_DIR, member)
        for sub in ["consoles", "console_libraries"]:
            _download_and_extract(url, _PROM_DIR,
                                  f"prometheus-{_PROM_VER}.linux-amd64/{sub}",
                                  is_dir=True)

    # Write prometheus.yml
    cfg_path = os.path.join(_PROM_DIR, "prometheus.yml")
    prometheus_yml = f"""global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: [localhost:9090]

  - job_name: node
    static_configs:
      - targets: [localhost:9100]

  - job_name: frappe_k6
    static_configs:
      - targets: [localhost:9200]
"""
    with open(cfg_path, "w") as f:
        f.write(prometheus_yml)

    svc_name = "prometheus"
    if not _service_active(svc_name):
        user = os.environ.get("USER", "erpadmin")
        svc_content = f"""[Unit]
Description=Prometheus Monitoring
After=network.target

[Service]
User={user}
ExecStart={binary} \\
  --config.file={cfg_path} \\
  --storage.tsdb.path={_PROM_DIR}/data \\
  --web.listen-address=0.0.0.0:9090 \\
  --web.enable-lifecycle
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
"""
        _install_systemd_service(svc_name, svc_content)
    else:
        # Reload config if service already running
        _run_cmd(["curl", "-s", "-X", "POST", "http://localhost:9090/-/reload"])

    _log(f"     prometheus: {_service_status(svc_name)}")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 6b — Frappe K6 Prometheus Exporter (port 9200)
# ─────────────────────────────────────────────────────────────────────────────

def _setup_k6_exporter(server_ip, port):
    exporter_src = os.path.join(_SETUP_DIR, "frappe_k6_exporter.py")
    exporter_dst = os.path.join(_MON_DIR, "frappe_k6_exporter.py")
    shutil.copy2(exporter_src, exporter_dst)
    os.chmod(exporter_dst, 0o755)

    svc_name = "frappe_k6_exporter"
    if not _service_active(svc_name):
        user    = os.environ.get("USER", "erpadmin")
        python  = sys.executable
        base_url = f"http://{server_ip}:{port}"
        svc_content = f"""[Unit]
Description=Frappe K6 Prometheus Exporter
After=network.target

[Service]
User={user}
Environment=FRAPPE_URL={base_url}
Environment=EXPORTER_PORT=9200
ExecStart={python} {exporter_dst}
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
"""
        _install_systemd_service(svc_name, svc_content)

    _log(f"     k6_exporter: {_service_status(svc_name)}  (http://{server_ip}:9200/metrics)")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 7 — Loki  (binary download, config, systemd service)
# ─────────────────────────────────────────────────────────────────────────────

def _setup_loki():
    binary = os.path.join(_LOKI_DIR, "loki")

    if not os.path.isfile(binary):
        _log(f"     downloading Loki v{_LOKI_VER} …")
        url = (f"https://github.com/grafana/loki/releases/download/"
               f"v{_LOKI_VER}/loki-linux-amd64.zip")
        _download_zip_binary(url, _LOKI_DIR, "loki-linux-amd64", "loki")

    cfg_path    = os.path.join(_LOKI_DIR, "loki-config.yaml")
    chunks_dir  = os.path.join(_LOKI_DIR, "chunks")
    rules_dir   = os.path.join(_LOKI_DIR, "rules")
    loki_cfg = f"""auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096
  log_level: warn

common:
  path_prefix: {_LOKI_DIR}
  storage:
    filesystem:
      chunks_directory: {chunks_dir}
      rules_directory: {rules_dir}
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v12
      index:
        prefix: index_
        period: 24h

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  ingestion_rate_mb: 8
  ingestion_burst_size_mb: 16

analytics:
  reporting_enabled: false
"""
    with open(cfg_path, "w") as f:
        f.write(loki_cfg)

    svc_name = "loki"
    if not _service_active(svc_name):
        user = os.environ.get("USER", "erpadmin")
        svc_content = f"""[Unit]
Description=Grafana Loki Log Aggregation
After=network.target

[Service]
User={user}
ExecStart={binary} -config.file={cfg_path}
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
        _install_systemd_service(svc_name, svc_content)
    else:
        _log("     loki already active — config updated, service left running")

    _log(f"     loki: {_service_status(svc_name)}  (http://localhost:3100/ready)")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 8 — Promtail  (binary download, config, systemd service)
# ─────────────────────────────────────────────────────────────────────────────

def _setup_promtail():
    binary = os.path.join(_PROMTAIL_DIR, "promtail")

    if not os.path.isfile(binary):
        _log(f"     downloading Promtail v{_PROMTAIL_VER} …")
        url = (f"https://github.com/grafana/loki/releases/download/"
               f"v{_PROMTAIL_VER}/promtail-linux-amd64.zip")
        _download_zip_binary(url, _PROMTAIL_DIR, "promtail-linux-amd64", "promtail")

    positions_path = os.path.join(_PROMTAIL_DIR, "positions.yaml")
    cfg_path       = os.path.join(_PROMTAIL_DIR, "promtail-config.yaml")

    scrape_yaml = _build_promtail_scrape_configs()

    promtail_cfg = f"""server:
  http_listen_port: 9080
  grpc_listen_port: 0
  log_level: warn

positions:
  filename: {positions_path}

clients:
  - url: http://localhost:3100/loki/api/v1/push

{scrape_yaml}
"""
    with open(cfg_path, "w") as f:
        f.write(promtail_cfg)

    svc_name = "promtail"
    if not _service_active(svc_name):
        user = os.environ.get("USER", "erpadmin")
        svc_content = f"""[Unit]
Description=Grafana Promtail Log Collector
After=network.target loki.service

[Service]
User={user}
ExecStart={binary} -config.file={cfg_path}
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
        _install_systemd_service(svc_name, svc_content)
    else:
        _log("     promtail already active — config updated, service left running")

    _log(f"     promtail: {_service_status(svc_name)}  (http://localhost:9080/metrics)")


def _build_promtail_scrape_configs():
    """
    Build promtail scrape_configs YAML.
    Covers all Frappe/bench log files + optional system logs.
    Only includes paths that are readable by the current user.
    """
    bench_logs = os.path.join(_BENCH_DIR, "logs")

    level_pipeline = (
        "    pipeline_stages:\n"
        "      - regex:\n"
        "          expression: '.*(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL).*'\n"
        "      - labels:\n"
        "          level:\n"
    )

    def job_block(job_name, path, labels, pipeline="", check_path=None):
        """Return a scrape_config block if the path is accessible."""
        check = check_path or path
        # For glob paths, check the directory
        check_dir = os.path.dirname(check) if "*" not in check else os.path.dirname(check)
        if not os.access(check_dir, os.R_OK):
            return None
        label_lines = "".join(f"\n          {k}: {v}" for k, v in labels.items())
        label_lines += f"\n          __path__: {path}"
        block = (
            f"  - job_name: {job_name}\n"
            f"    static_configs:\n"
            f"      - targets:\n"
            f"          - localhost\n"
            f"        labels:{label_lines}\n"
        )
        if pipeline:
            block += pipeline
        return block

    blocks = []

    # ── Frappe application log ────────────────────────────────────
    b = job_block("frappe_app",
                  os.path.join(bench_logs, "frappe.log"),
                  {"job": "frappe", "log_type": "application", "app": "frappe_k6", "env": "production"},
                  level_pipeline, bench_logs)
    if b: blocks.append(b)

    # ── Bench / Gunicorn log ──────────────────────────────────────
    b = job_block("frappe_bench",
                  os.path.join(bench_logs, "bench.log"),
                  {"job": "frappe", "log_type": "bench", "app": "frappe_k6"},
                  level_pipeline, bench_logs)
    if b: blocks.append(b)

    # ── Scheduler log ─────────────────────────────────────────────
    b = job_block("frappe_scheduler",
                  os.path.join(bench_logs, "scheduler.log"),
                  {"job": "frappe", "log_type": "scheduler", "app": "frappe_k6"},
                  level_pipeline, bench_logs)
    if b: blocks.append(b)

    # ── Worker log ────────────────────────────────────────────────
    b = job_block("frappe_worker",
                  os.path.join(bench_logs, "worker.log"),
                  {"job": "frappe", "log_type": "worker", "app": "frappe_k6"},
                  level_pipeline, bench_logs)
    if b: blocks.append(b)

    # ── Worker error log ──────────────────────────────────────────
    b = job_block("frappe_worker_error",
                  os.path.join(bench_logs, "worker.error.log"),
                  {"job": "frappe", "log_type": "worker_error", "level": "ERROR", "app": "frappe_k6"},
                  "", bench_logs)
    if b: blocks.append(b)

    # ── Database / slow query log ─────────────────────────────────
    b = job_block("frappe_database",
                  os.path.join(bench_logs, "database.log"),
                  {"job": "frappe", "log_type": "database", "app": "frappe_k6"},
                  level_pipeline, bench_logs)
    if b: blocks.append(b)

    # ── Optional: Nginx ───────────────────────────────────────────
    b = job_block("nginx",
                  "/var/log/nginx/access.log",
                  {"job": "nginx", "log_type": "access"},
                  "", "/var/log/nginx")
    if b: blocks.append(b)

    # ── Optional: MySQL ───────────────────────────────────────────
    b = job_block("mysql",
                  "/var/log/mysql/error.log",
                  {"job": "mysql", "log_type": "database"},
                  "", "/var/log/mysql")
    if b: blocks.append(b)

    # ── Optional: PostgreSQL ──────────────────────────────────────
    for pg_log in ("/var/log/postgresql/postgresql-14-main.log",
                   "/var/log/postgresql/postgresql-15-main.log",
                   "/var/log/postgresql/postgresql-16-main.log"):
        if os.access(pg_log, os.R_OK):
            b = job_block("postgresql", pg_log,
                          {"job": "postgresql", "log_type": "database"},
                          "", os.path.dirname(pg_log))
            if b:
                blocks.append(b)
                break

    # ── Syslog ────────────────────────────────────────────────────
    b = job_block("syslog",
                  "/var/log/syslog",
                  {"job": "syslog", "log_type": "system"},
                  "", "/var/log")
    if b: blocks.append(b)

    # Fallback: if bench_logs dir doesn't exist yet, add a placeholder
    if not blocks:
        blocks.append(
            f"  - job_name: frappe_app\n"
            f"    static_configs:\n"
            f"      - targets:\n"
            f"          - localhost\n"
            f"        labels:\n"
            f"          job: frappe\n"
            f"          log_type: application\n"
            f"          app: frappe_k6\n"
            f"          __path__: {bench_logs}/frappe.log\n"
        )

    return "scrape_configs:\n\n" + "\n".join(b for b in blocks if b)


# ─────────────────────────────────────────────────────────────────────────────
#  Step 9 — Grafana
# ─────────────────────────────────────────────────────────────────────────────

def _setup_grafana(server_ip):
    # Install via APT if not present
    if not shutil.which("grafana-server") and not os.path.isfile("/usr/sbin/grafana-server"):
        _log("     installing Grafana via APT …")
        _run_sudo(["mkdir", "-p", "/etc/apt/keyrings"])
        _run_cmd(
            "wget -q -O - https://apt.grafana.com/gpg.key | "
            "sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/grafana.gpg",
            shell=True
        )
        _run_sudo(["bash", "-c",
            "echo 'deb [signed-by=/etc/apt/keyrings/grafana.gpg] "
            "https://apt.grafana.com stable main' > /etc/apt/sources.list.d/grafana.list"])
        _run_sudo(["apt-get", "update", "-qq"])
        _run_sudo(["apt-get", "install", "-y", "grafana"])

    # Provision Prometheus datasource
    _provision_grafana_datasource(server_ip)

    # Provision K6 + system dashboard
    _provision_grafana_dashboard()

    # Enable and start Grafana
    svc_name = "grafana-server"
    if not _service_active(svc_name):
        _run_sudo(["systemctl", "daemon-reload"])
        _run_sudo(["systemctl", "enable", svc_name])
        _run_sudo(["systemctl", "start", svc_name])
        import time; time.sleep(3)

    # Import dashboard via Grafana API (waits up to 20 s for Grafana to start)
    _import_dashboard_via_api()

    # Ensure Prometheus + Loki datasources exist via API (works on all Grafana versions)
    _ensure_grafana_datasources_via_api()

    _log(f"     grafana: {_service_status(svc_name)}")


def _provision_grafana_datasource(server_ip):
    """Write Prometheus + Loki datasource YAML to Grafana provisioning dir."""
    ds_dir = "/etc/grafana/provisioning/datasources"
    ds_yaml = f"""apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    uid: prometheus
    url: http://localhost:9090
    access: proxy
    isDefault: true
    editable: true

  - name: Loki
    type: loki
    uid: loki
    url: http://localhost:3100
    access: proxy
    isDefault: false
    editable: true
    jsonData:
      maxLines: 1000
      derivedFields:
        - name: TraceID
          matcherRegex: "traceID=(\\\\w+)"
          url: ""
"""
    dst = os.path.join(ds_dir, "frappe_k6_datasources.yaml")
    _write_with_sudo(ds_yaml, dst)


def _provision_grafana_dashboard():
    """Write dashboard provider YAML and copy the dashboard JSON."""
    # Dashboard provider
    provider_yaml = """apiVersion: 1
providers:
  - name: frappe_k6
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
"""
    _write_with_sudo(provider_yaml,
                     "/etc/grafana/provisioning/dashboards/frappe_k6_provider.yaml")

    # Dashboard JSON directory
    _run_sudo(["mkdir", "-p", "/var/lib/grafana/dashboards"])

    dashboard_src = os.path.join(_SETUP_DIR, "frappe_k6_dashboard.json")
    if os.path.isfile(dashboard_src):
        _run_sudo(["cp", dashboard_src, "/var/lib/grafana/dashboards/frappe_k6.json"])
        _run_sudo(["chown", "grafana:grafana",
                   "/var/lib/grafana/dashboards/frappe_k6.json"])
    # Trigger Grafana to reload provisioned dashboards (non-destructive)
    try:
        import urllib.request as ur, base64
        auth = _grafana_auth_header()
        if auth:
            req = ur.Request("http://localhost:3000/api/admin/provisioning/dashboards/reload",
                             data=b"", headers={"Authorization": auth}, method="POST")
            ur.urlopen(req, timeout=5)
    except Exception:
        pass


def _import_dashboard_via_api():
    """Wait for Grafana to be ready, then import the dashboard JSON via API."""
    import time
    import urllib.request as ur
    import urllib.error
    import base64

    dashboard_src = os.path.join(_SETUP_DIR, "frappe_k6_dashboard.json")
    if not os.path.isfile(dashboard_src):
        return

    grafana_url = "http://localhost:3000"
    # Try default password first, then common changed passwords
    passwords = ["admin", "Admin@123", "admin123", "grafana"]
    headers = {"Content-Type": "application/json"}
    for pwd in passwords:
        creds = base64.b64encode(f"admin:{pwd}".encode()).decode()
        try:
            test_req = ur.Request(f"{grafana_url}/api/org",
                headers={"Authorization": f"Basic {creds}"})
            with ur.urlopen(test_req, timeout=3) as r:
                if r.status == 200:
                    headers["Authorization"] = f"Basic {creds}"
                    break
        except Exception:
            continue

    # Wait up to 20 s for Grafana to respond
    for _ in range(10):
        try:
            req = ur.Request(f"{grafana_url}/api/health", headers=headers)
            with ur.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(2)

    with open(dashboard_src) as f:
        dashboard = json.load(f)

    payload = json.dumps({
        "dashboard": dashboard,
        "overwrite": True,
        "folderId": 0,
    }).encode()

    try:
        req = ur.Request(
            f"{grafana_url}/api/dashboards/db",
            data=payload,
            headers=headers,
            method="POST",
        )
        with ur.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
            _log(f"     dashboard imported: {result.get('url', 'ok')}")
    except Exception as exc:
        _log(f"     dashboard API import skipped: {exc}")


def _grafana_auth_header():
    """
    Return a Basic-auth header value for the Grafana admin user.
    Tries the site config password, then a list of common defaults.
    Returns None if Grafana is unreachable.
    """
    import base64
    import urllib.request as ur

    grafana_url = "http://localhost:3000"
    # Try passwords from site config first, then common defaults
    stored = frappe.conf.get("grafana_admin_password", "")
    candidates = ([stored] if stored else []) + [
        "admin", "Admin@123", "admin123", "grafana",
        "Avinash@77632", "Admin@k6",
    ]
    for pwd in candidates:
        creds = base64.b64encode(f"admin:{pwd}".encode()).decode()
        auth  = f"Basic {creds}"
        try:
            req = ur.Request(f"{grafana_url}/api/org",
                             headers={"Authorization": auth})
            with ur.urlopen(req, timeout=4) as r:
                if r.status == 200:
                    return auth
        except Exception:
            continue
    return None


def _ensure_grafana_datasources_via_api():
    """
    Create Prometheus and Loki datasources in Grafana via the REST API
    if they do not already exist.  Works on Grafana 9, 10, 11, 12.
    """
    import base64
    import urllib.request as ur
    import urllib.error

    grafana_url = "http://localhost:3000"
    auth = _grafana_auth_header()
    if not auth:
        _log("     ⚠ could not authenticate to Grafana — datasources skipped")
        return

    base_headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
    }

    # Fetch existing datasource names
    try:
        req = ur.Request(f"{grafana_url}/api/datasources", headers=base_headers)
        with ur.urlopen(req, timeout=6) as r:
            existing = {d["type"] + ":" + d["name"]: d["id"]
                        for d in json.loads(r.read())}
    except Exception as exc:
        _log(f"     ⚠ could not list Grafana datasources: {exc}")
        return

    desired = [
        {
            "name": "Prometheus",
            "type": "prometheus",
            "uid":  "prometheus",
            "url":  "http://localhost:9090",
            "access": "proxy",
            "isDefault": True,
            "jsonData": {"timeInterval": "15s"},
        },
        {
            "name": "Loki",
            "type": "loki",
            "uid":  "loki",
            "url":  "http://localhost:3100",
            "access": "proxy",
            "isDefault": False,
            "jsonData": {"maxLines": 1000},
        },
    ]

    for ds in desired:
        key = ds["type"] + ":" + ds["name"]
        if key in existing:
            _log(f"     datasource '{ds['name']}' already exists — skipping")
            continue
        payload = json.dumps(ds).encode()
        try:
            req = ur.Request(
                f"{grafana_url}/api/datasources",
                data=payload,
                headers=base_headers,
                method="POST",
            )
            with ur.urlopen(req, timeout=8) as r:
                result = json.loads(r.read())
                _log(f"     datasource '{ds['name']}' created: id={result.get('id','?')}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            _log(f"     datasource '{ds['name']}' error {exc.code}: {body[:120]}")
        except Exception as exc:
            _log(f"     datasource '{ds['name']}' failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _log(msg):
    print(f"[frappe_k6] {msg}")


def _run_cmd(cmd, shell=False, timeout=180):
    """Run a command; return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def _run_sudo(cmd, timeout=180):
    """Run a command with sudo -n (non-interactive). Falls back to sudo with tty."""
    rc, out, err = _run_cmd(["sudo", "-n"] + cmd, timeout=timeout)
    if rc != 0:
        rc, out, err = _run_cmd(["sudo"] + cmd, timeout=timeout)
    return rc, out, err


def _detect_server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def _download_and_extract(url, dest_dir, member_path, is_dir=False):
    """Download a .tar.gz and extract a single file or directory."""
    tmp = os.path.join("/tmp", os.path.basename(url))
    if not os.path.isfile(tmp):
        urllib.request.urlretrieve(url, tmp)
    with tarfile.open(tmp, "r:gz") as tf:
        if is_dir:
            prefix = member_path.rstrip("/") + "/"
            for m in tf.getmembers():
                if m.name.startswith(prefix):
                    m.name = os.path.relpath(m.name, os.path.dirname(member_path))
                    tf.extract(m, dest_dir)
        else:
            m = tf.getmember(member_path)
            m.name = os.path.basename(m.name)
            tf.extract(m, dest_dir)
            os.chmod(os.path.join(dest_dir, os.path.basename(member_path)), 0o755)


def _write_with_sudo(content, path):
    """Write content to a root-owned path using sudo tee."""
    tmp = f"/tmp/_k6_tmp_{os.path.basename(path)}"
    with open(tmp, "w") as f:
        f.write(content)
    _run_sudo(["mkdir", "-p", os.path.dirname(path)])
    _run_sudo(["cp", tmp, path])
    os.remove(tmp)


def _install_systemd_service(name, content):
    """Write systemd unit, reload, enable, start."""
    svc_path = f"/etc/systemd/system/{name}.service"
    _write_with_sudo(content, svc_path)
    _run_sudo(["systemctl", "daemon-reload"])
    _run_sudo(["systemctl", "enable", name])
    _run_sudo(["systemctl", "start", name])
    import time; time.sleep(2)


def _service_active(name):
    rc, out, _ = _run_cmd(["systemctl", "is-active", name])
    return rc == 0 and out.strip() == "active"


def _service_status(name):
    _, out, _ = _run_cmd(["systemctl", "is-active", name])
    return out.strip() or "unknown"


def _download_zip_binary(url, dest_dir, zip_entry_name, short_name):
    """Download a .zip archive and extract a single binary, rename to short_name."""
    tmp = os.path.join("/tmp", os.path.basename(url))
    if not os.path.isfile(tmp):
        _log(f"     fetching {url} …")
        urllib.request.urlretrieve(url, tmp)
    with zipfile.ZipFile(tmp, "r") as zf:
        # zip_entry_name is the name inside the archive (may or may not have extension)
        names = zf.namelist()
        match = next((n for n in names if os.path.basename(n) == zip_entry_name
                      or n == zip_entry_name), None)
        if match is None:
            # Try without suffix
            match = next((n for n in names if n.startswith(zip_entry_name)), None)
        if match is None:
            raise RuntimeError(f"Binary '{zip_entry_name}' not found in zip. Contents: {names}")
        data = zf.read(match)
    dest = os.path.join(dest_dir, short_name)
    with open(dest, "wb") as f:
        f.write(data)
    os.chmod(dest, 0o755)
    _log(f"     extracted {short_name} → {dest}")

"""
frappe_k6 installation.

`after_install` only touches the database and site config: roles, Monitor Settings,
a metrics token and sample configs. It needs no sudo and no network, so
`bench install-app frappe_k6` works on any bench.

Host-level setup is opt-in, through bench commands (see frappe_k6/commands.py):
  bench frappe-k6 install-k6                  # static k6 binary into <bench>/env/bin, no sudo
  bench --site X frappe-k6 setup-local-stack  # Prometheus, Loki, Grafana (needs sudo + systemd)
"""

import getpass
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile

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
_K6_VER        = "2.3.0"

_TOKEN_FILE    = os.path.join(_MON_DIR, ".frappe_k6_metrics_token")


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def after_install():
    """Database-only setup — called automatically by Frappe after install."""
    from frappe_k6.security import ensure_roles

    ensure_roles()
    _setup_slow_query_log()
    _setup_reports_dir()
    try:
        from frappe_k6.alerts import ensure_default_rules

        ensure_default_rules()
    except Exception as exc:
        _log(f"default alert rules skipped: {exc}")
    _configure_basic_settings()
    ensure_metrics_token()
    try:
        _create_sample_configs()
    except Exception as exc:
        _log(f"sample configs skipped: {exc}")
    frappe.db.commit()

    k6 = shutil.which("k6")
    _log("frappe_k6 installed.")
    _log(f"  k6 binary : {k6 or 'not found — run: bench frappe-k6 install-k6'}")
    _log("  Check     : bench frappe-k6 doctor")
    _log(f"  Optional  : bench --site {frappe.local.site} frappe-k6 setup-local-stack")
    _log("  Grant the 'K6 Manager' or 'K6 User' role to users who need access.")


def setup_local_stack(skip=()):
    """
    Install and start the self-hosted monitoring stack (node_exporter, Prometheus,
    the frappe_k6 exporter, Loki, Promtail, Grafana). Needs sudo, systemd and internet.
    `skip` holds step names (case-insensitive) to leave out.
    """
    server_ip = _detect_server_ip()
    port      = frappe.get_site_config().get("webserver_port", 8000)
    skip      = {name.lower() for name in skip}

    steps = [
        ("Directories",             lambda: _setup_monitoring_directories()),
        ("Monitor Settings",        lambda: _configure_stack_settings(server_ip)),
        ("Register Local Server",   lambda: _register_local_server(server_ip)),
        ("k6",                      lambda: install_k6_binary()),
        ("node_exporter",           lambda: _setup_node_exporter()),
        ("Prometheus",              lambda: _setup_prometheus(server_ip, port)),
        ("K6 Exporter",             lambda: _setup_k6_exporter(server_ip, port)),
        ("Loki",                    lambda: _setup_loki()),
        ("Promtail",                lambda: _setup_promtail()),
        ("Grafana",                 lambda: _setup_grafana(server_ip)),
    ]

    results = {}
    for name, fn in steps:
        if name.lower() in skip:
            results[name] = "skipped"
            continue
        try:
            _log(f"  → {name} ...")
            fn()
            results[name] = "ok"
        except Exception as exc:
            results[name] = f"FAILED: {exc}"
            _log(f"     FAILED: {exc}")

    frappe.db.commit()

    _log("=" * 62)
    _log("Setup summary:")
    for name, status in results.items():
        _log(f"  {name:<24} {status}")
    _log("─" * 62)
    _log(f"  K6 Dashboard : http://{server_ip}:{port}/k6-monitor")
    _log(f"  Grafana      : http://{server_ip}:3000")
    _log(f"  Prometheus   : http://{server_ip}:9090")
    _log("=" * 62)
    return results


def ensure_metrics_token():
    """Create the bearer token that Prometheus scrapers use for the metrics endpoints."""
    from frappe.installer import update_site_config

    token = frappe.conf.get("frappe_k6_metrics_token")
    if not token:
        token = frappe.generate_hash(length=40)
        update_site_config("frappe_k6_metrics_token", token)
        frappe.conf.frappe_k6_metrics_token = token
    return token


# ─────────────────────────────────────────────────────────────────────────────
#  Step 1 — Directories
# ─────────────────────────────────────────────────────────────────────────────

def _setup_reports_dir():
    reports_dir = os.path.join(_APP_ROOT, "k6_tests", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    return reports_dir


def _setup_monitoring_directories():
    for d in [
        _MON_DIR, _PROM_DIR, _NODE_DIR,
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
    _log(f"     monitoring → {_MON_DIR}")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 2 — Monitor Settings
# ─────────────────────────────────────────────────────────────────────────────

def _configure_basic_settings():
    """Defaults that need no host access. Existing values are kept."""
    s = frappe.get_single("Monitor Settings")
    s.site_name      = s.site_name or frappe.local.site
    s.base_url       = s.base_url or frappe.utils.get_url()
    s.k6_reports_dir = s.k6_reports_dir or _setup_reports_dir()
    s.k6_binary_path = s.k6_binary_path or shutil.which("k6") or "k6"
    s.monitoring_mode = s.monitoring_mode or "Off"
    s.refresh_interval = s.refresh_interval or 5
    from frappe_k6.grafana_cloud import ensure_default_cloud_rules

    ensure_default_cloud_rules(s)
    s.save(ignore_permissions=True)


def _setup_slow_query_log():
    """
    Set up Slow Query Log doctype and default settings.
    """
    # Ensure Slow Query Log doctype exists
    if not frappe.db.exists("DocType", "Slow Query Log"):
        frappe.get_doc({
            "doctype": "DocType",
            "module": "frappe_k6",
            "name": "Slow Query Log",
            "document_type": "System",
            "engine": "InnoDB",
            "fields": [
                {"fieldname": "timestamp", "fieldtype": "Datetime", "label": "Timestamp"},
                {"fieldname": "query_text", "fieldtype": "Long Text", "label": "Query Text"},
                {"fieldname": "execution_time", "fieldtype": "Float", "label": "Execution Time (seconds)", "default": "0.00"},
                {"fieldname": "seen", "fieldtype": "Check", "label": "Seen", "default": "0", "hidden": 1},
            ],
            "icon": "fa fa-hourglass",
            "module": "frappe_k6",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

    # Set default for enable_slow_query_logging if not already set
    if not frappe.db.exists("System Settings", "enable_slow_query_logging"):
        frappe.get_doc({
            "doctype": "System Settings",
            "enable_slow_query_logging": 1,
        }).insert(ignore_permissions=True)
        frappe.db.commit()


def _configure_stack_settings(server_ip):
    s = frappe.get_single("Monitor Settings")
    s.monitoring_mode  = "Self-hosted"
    s.grafana_enabled  = 1
    s.grafana_url      = f"http://{server_ip}:3000"
    s.prometheus_enabled = 1
    s.prometheus_url   = f"http://{server_ip}:9090"
    s.loki_enabled     = 1
    s.loki_url         = f"http://{server_ip}:3100"
    s.promtail_url     = f"http://{server_ip}:9080"
    s.save(ignore_permissions=True)
    frappe.db.commit()
    _log(f"     site={frappe.local.site}  mode=Self-hosted")


# ─────────────────────────────────────────────────────────────────────────────
#  Step 2b — Register localhost as a Remote Server record
# ─────────────────────────────────────────────────────────────────────────────

def _register_local_server(server_ip):
    """
    Create (or update) a Remote Server record for this machine so that
    Prometheus config is generated with proper server_name / env labels
    and the multi-server overview dashboard shows the local server.
    """
    try:
        if not frappe.db.exists("DocType", "Remote Server"):
            return  # DocType not yet migrated
        name = "local"
        if frappe.db.exists("Remote Server", name):
            doc = frappe.get_doc("Remote Server", name)
        else:
            doc = frappe.new_doc("Remote Server")
            doc.server_name = name
        doc.host                    = server_ip
        doc.environment             = "Production"
        doc.enabled                 = 1
        doc.is_local                = 1
        doc.tags                    = "local,frappe_k6"
        doc.node_exporter_enabled   = 1
        doc.node_exporter_port      = 9100
        doc.redis_exporter_enabled  = 0   # using frappe_k6 exporter for Redis
        doc.db_exporter_enabled     = 0   # using frappe_k6 exporter for DB
        doc.promtail_enabled        = 1
        doc.promtail_port           = 9080
        doc.notes                   = "Auto-registered by frappe_k6 installer"
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        _log(f"     registered local Remote Server: {name}")
    except Exception as exc:
        _log(f"     _register_local_server skipped: {exc}")


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

def install_k6_binary(version=_K6_VER, dest_dir=None, force=False):
    """
    Download the official static k6 release for this OS/CPU, verify its SHA-256
    against the release checksums, and install it into <bench>/env/bin. No sudo.
    """
    existing = shutil.which("k6")
    if existing and not force:
        _log(f"     already installed: {existing}")
        return existing

    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if platform.system() != "Linux" or not arch:
        raise RuntimeError(f"No k6 build for {platform.system()} {machine}; install it manually.")

    base = f"https://github.com/grafana/k6/releases/download/v{version}"
    asset = f"k6-v{version}-linux-{arch}.tar.gz"
    dest_dir = dest_dir or os.path.join(_BENCH_DIR, "env", "bin")
    os.makedirs(dest_dir, exist_ok=True)

    with urllib.request.urlopen(f"{base}/k6-v{version}-checksums.txt", timeout=60) as r:
        checksums = dict(
            reversed(line.split()) for line in r.read().decode().splitlines() if line.strip()
        )
    if asset not in checksums:
        raise RuntimeError(f"{asset} is not listed in the v{version} checksums")

    with urllib.request.urlopen(f"{base}/{asset}", timeout=300) as r:
        payload = r.read()
    if hashlib.sha256(payload).hexdigest() != checksums[asset]:
        raise RuntimeError(f"Checksum mismatch for {asset}")

    import io

    member = f"k6-v{version}-linux-{arch}/k6"
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
        data = tf.extractfile(member).read()
    target = os.path.join(dest_dir, "k6")
    with open(target, "wb") as f:
        f.write(data)
    os.chmod(target, 0o755)
    _log(f"     k6 v{version} installed: {target}")

    if frappe.db and frappe.db.exists("DocType", "Monitor Settings"):
        frappe.db.set_single_value("Monitor Settings", "k6_binary_path", target)
    return target


def _install_k6():
    """Kept for older docs that call it through `bench execute`."""
    return install_k6_binary()


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
User={getpass.getuser()}
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
        user = getpass.getuser()
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

    # The exporter authenticates to Frappe with this token (file readable by the bench user only)
    token = ensure_metrics_token()
    fd = os.open(_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)

    svc_name = "frappe_k6_exporter"
    if _service_active(svc_name):
        _run_sudo(["systemctl", "restart", svc_name])  # pick up the new exporter code
    else:
        user    = getpass.getuser()
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
        user = getpass.getuser()
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
        user = getpass.getuser()
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
        "      - regex:\n"
        "          expression: '.*(?P<query_time>Query_time:\\s+[\\d.]+)'\n"
        "      - labels:\n"
        "          level:\n"
        "      - labels:\n"
        "          query_time:\n"
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

    # Regenerate dashboards from gen_dashboards.py if available
    gen_script = os.path.join(_SETUP_DIR, "gen_dashboards.py")
    if os.path.isfile(gen_script):
        try:
            import subprocess
            subprocess.run([sys.executable, gen_script], check=True, timeout=30)
            _log("     dashboards regenerated via gen_dashboards.py")
        except Exception as exc:
            _log(f"     gen_dashboards.py skipped: {exc}")

    # Copy all dashboard JSON files
    _dashboard_files = [
        "frappe_k6_dashboard.json",
        "frappe_k6_remote_server_dashboard.json",
        "frappe_k6_multi_dashboard.json",
        "frappe_k6_db_dashboard.json",
        "frappe_k6_redis_dashboard.json",
        "frappe_k6_worker_dashboard.json",
        "frappe_k6_node_dashboard.json",
    ]
    for fname in _dashboard_files:
        src = os.path.join(_SETUP_DIR, fname)
        dst = f"/var/lib/grafana/dashboards/{fname}"
        if os.path.isfile(src):
            _run_sudo(["cp", src, dst])
            _run_sudo(["chown", "grafana:grafana", dst])

    # Trigger Grafana to reload provisioned dashboards (non-destructive)
    try:
        import base64
        import urllib.request as ur
        auth = _grafana_auth_header()
        if auth:
            req = ur.Request("http://localhost:3000/api/admin/provisioning/dashboards/reload",
                             data=b"", headers={"Authorization": auth}, method="POST")
            ur.urlopen(req, timeout=5)
    except Exception:
        pass


def _import_dashboard_via_api():
    """Wait for Grafana to be ready, then import all dashboard JSON files via API."""
    import base64
    import time
    import urllib.error
    import urllib.request as ur

    _all_dashboards = [
        "frappe_k6_dashboard.json",
        "frappe_k6_remote_server_dashboard.json",
        "frappe_k6_multi_dashboard.json",
        "frappe_k6_db_dashboard.json",
        "frappe_k6_redis_dashboard.json",
        "frappe_k6_worker_dashboard.json",
        "frappe_k6_node_dashboard.json",
    ]
    dashboard_files = [os.path.join(_SETUP_DIR, f) for f in _all_dashboards
                       if os.path.isfile(os.path.join(_SETUP_DIR, f))]
    if not dashboard_files:
        return
    dashboard_src = dashboard_files[0]  # used below for auth check

    grafana_url = "http://localhost:3000"
    headers = {"Content-Type": "application/json"}
    auth = _grafana_auth_header()
    if not auth:
        _log("     ⚠ Grafana credentials not configured or rejected — dashboard import skipped")
        return
    headers["Authorization"] = auth

    # Wait up to 20 s for Grafana to respond
    for _ in range(10):
        try:
            req = ur.Request(f"{grafana_url}/api/health", headers=headers)
            with ur.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(2)

    for dash_path in dashboard_files:
        try:
            with open(dash_path) as f:
                dashboard = json.load(f)
            payload = json.dumps({
                "dashboard": dashboard,
                "overwrite": True,
                "folderId": 0,
            }).encode()
            req = ur.Request(
                f"{grafana_url}/api/dashboards/db",
                data=payload,
                headers=headers,
                method="POST",
            )
            with ur.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
                _log(f"     dashboard imported: {result.get('url', os.path.basename(dash_path))}")
        except Exception as exc:
            _log(f"     dashboard {os.path.basename(dash_path)} import skipped: {exc}")


def _grafana_auth_header():
    """
    Authorization header for the local Grafana, from site config only:
    `grafana_api_token` (service account token, preferred) or `grafana_admin_password`.
    Returns None if neither is set or Grafana rejects it. Passwords are never guessed.
    """
    import base64
    import urllib.request as ur

    token = frappe.conf.get("grafana_api_token")
    password = frappe.conf.get("grafana_admin_password")
    if token:
        auth = f"Bearer {token}"
    elif password:
        auth = "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()
    else:
        return None

    try:
        req = ur.Request("http://localhost:3000/api/org", headers={"Authorization": auth})
        with ur.urlopen(req, timeout=4) as r:
            if r.status == 200:
                return auth
    except Exception:
        pass
    return None


def _ensure_grafana_datasources_via_api():
    """
    Create Prometheus and Loki datasources in Grafana via the REST API
    if they do not already exist.  Works on Grafana 9, 10, 11, 12.
    """
    import base64
    import urllib.error
    import urllib.request as ur

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

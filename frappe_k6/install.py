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
import tarfile
import urllib.request

import frappe

# ── Paths ────────────────────────────────────────────────────────────────────
_APP_DIR      = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT     = os.path.abspath(os.path.join(_APP_DIR, ".."))
_BENCH_DIR    = os.path.abspath(os.path.join(_APP_DIR, "../../.."))
_SETUP_DIR    = os.path.join(_APP_DIR, "setup")
_MON_DIR      = os.path.join(os.path.expanduser("~"), "monitoring")
_PROM_DIR     = os.path.join(_MON_DIR, "prometheus")
_NODE_DIR     = os.path.join(_MON_DIR, "node_exporter")

# ── Release versions ─────────────────────────────────────────────────────────
_PROM_VER      = "2.52.0"
_NODE_EXP_VER  = "1.8.1"


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
    _log("=" * 62)


# ─────────────────────────────────────────────────────────────────────────────
#  Step 1 — Directories
# ─────────────────────────────────────────────────────────────────────────────

def _setup_directories():
    reports_dir = os.path.join(_APP_ROOT, "k6_tests", "reports")
    for d in [reports_dir, _MON_DIR, _PROM_DIR, _NODE_DIR,
              os.path.join(_PROM_DIR, "data")]:
        os.makedirs(d, exist_ok=True)
    _log(f"     reports → {reports_dir}")


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
    s.save(ignore_permissions=True)
    frappe.db.commit()
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
#  Step 7 — Grafana
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

    _log(f"     grafana: {_service_status(svc_name)}")


def _provision_grafana_datasource(server_ip):
    """Write Prometheus datasource YAML to Grafana provisioning dir."""
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
"""
    dst = os.path.join(ds_dir, "frappe_k6_prometheus.yaml")
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

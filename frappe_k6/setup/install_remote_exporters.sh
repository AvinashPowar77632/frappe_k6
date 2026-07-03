#!/usr/bin/env bash
# =============================================================================
# install_remote_exporters.sh
# frappe_k6 — Remote Server Exporter Installer
#
# Installs on a remote server:
#   1. node_exporter  (port 9100)  — system metrics
#   2. redis_exporter (port 9121)  — Redis metrics  [optional]
#   3. mysqld_exporter or postgres_exporter          [optional]
#   4. Promtail                    (port 9080)        — log shipping
#
# Usage:
#   chmod +x install_remote_exporters.sh
#   sudo ./install_remote_exporters.sh \
#       --server-name  my-server-1 \
#       --loki-url     http://CENTRAL_IP:3100/loki/api/v1/push \
#       --env          production \
#       [--bench-dir   /home/frappe/frappe-bench] \
#       [--skip-redis] [--skip-db] [--db-type mariadb|postgresql]
# =============================================================================

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
SERVER_NAME=""
LOKI_URL=""
ENV_LABEL="production"
BENCH_DIR=""
SKIP_REDIS=0
SKIP_DB=0
DB_TYPE="mariadb"
INSTALL_DIR="/opt/monitoring"
NODE_VER="1.8.2"
REDIS_EXP_VER="1.62.0"
MYSQLD_EXP_VER="0.15.1"
PG_EXP_VER="0.15.0"
PROMTAIL_VER="3.0.0"
ARCH="amd64"

# ── Arg parsing ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-name)  SERVER_NAME="$2";  shift 2 ;;
    --loki-url)     LOKI_URL="$2";     shift 2 ;;
    --env)          ENV_LABEL="$2";    shift 2 ;;
    --bench-dir)    BENCH_DIR="$2";    shift 2 ;;
    --skip-redis)   SKIP_REDIS=1;      shift ;;
    --skip-db)      SKIP_DB=1;         shift ;;
    --db-type)      DB_TYPE="$2";      shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ -z "$SERVER_NAME" ]]; then
  echo "ERROR: --server-name is required"
  exit 1
fi
if [[ -z "$LOKI_URL" ]]; then
  echo "ERROR: --loki-url is required (e.g. http://CENTRAL_IP:3100/loki/api/v1/push)"
  exit 1
fi

echo "============================================================"
echo " frappe_k6 Remote Exporter Installer"
echo " Server: $SERVER_NAME  |  Env: $ENV_LABEL"
echo " Loki URL: $LOKI_URL"
echo "============================================================"

# ── Helper functions ──────────────────────────────────────────────────────────
_download() { wget -qO "$2" "$1"; }
_install_service() {
  local name="$1" content="$2"
  echo "$content" > "/etc/systemd/system/${name}.service"
  systemctl daemon-reload
  systemctl enable --now "$name"
  echo "  ✓  $name: $(systemctl is-active $name)"
}

mkdir -p "$INSTALL_DIR"

# ── 1. node_exporter ──────────────────────────────────────────────────────────
if ! command -v node_exporter &>/dev/null && [[ ! -f "$INSTALL_DIR/node_exporter" ]]; then
  echo ""
  echo "→ Installing node_exporter v${NODE_VER} …"
  TMP=$(mktemp -d)
  URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_VER}/node_exporter-${NODE_VER}.linux-${ARCH}.tar.gz"
  _download "$URL" "$TMP/ne.tar.gz"
  tar xzf "$TMP/ne.tar.gz" -C "$TMP"
  cp "$TMP/node_exporter-${NODE_VER}.linux-${ARCH}/node_exporter" "$INSTALL_DIR/"
  chmod +x "$INSTALL_DIR/node_exporter"
  rm -rf "$TMP"
fi

if ! systemctl is-active --quiet node_exporter 2>/dev/null; then
  _install_service node_exporter "[Unit]
Description=Node Exporter
After=network.target

[Service]
User=nobody
ExecStart=${INSTALL_DIR}/node_exporter --web.listen-address=0.0.0.0:9100
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target"
fi
echo "  node_exporter: $(systemctl is-active node_exporter)  (port 9100)"

# ── 2. redis_exporter (optional) ──────────────────────────────────────────────
if [[ $SKIP_REDIS -eq 0 ]]; then
  echo ""
  echo "→ Installing redis_exporter v${REDIS_EXP_VER} …"
  if [[ ! -f "$INSTALL_DIR/redis_exporter" ]]; then
    TMP=$(mktemp -d)
    URL="https://github.com/oliver006/redis_exporter/releases/download/v${REDIS_EXP_VER}/redis_exporter-v${REDIS_EXP_VER}.linux-${ARCH}.tar.gz"
    _download "$URL" "$TMP/re.tar.gz"
    tar xzf "$TMP/re.tar.gz" -C "$TMP"
    cp "$TMP/redis_exporter-v${REDIS_EXP_VER}.linux-${ARCH}/redis_exporter" "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/redis_exporter"
    rm -rf "$TMP"
  fi
  if ! systemctl is-active --quiet redis_exporter 2>/dev/null; then
    _install_service redis_exporter "[Unit]
Description=Redis Exporter
After=network.target

[Service]
User=nobody
ExecStart=${INSTALL_DIR}/redis_exporter --web.listen-address=0.0.0.0:9121
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target"
  fi
  echo "  redis_exporter: $(systemctl is-active redis_exporter)  (port 9121)"
fi

# ── 3. DB exporter (optional) ─────────────────────────────────────────────────
if [[ $SKIP_DB -eq 0 ]]; then
  echo ""
  if [[ "$DB_TYPE" == "mariadb" || "$DB_TYPE" == "mysql" ]]; then
    echo "→ Installing mysqld_exporter v${MYSQLD_EXP_VER} …"
    if [[ ! -f "$INSTALL_DIR/mysqld_exporter" ]]; then
      TMP=$(mktemp -d)
      URL="https://github.com/prometheus/mysqld_exporter/releases/download/v${MYSQLD_EXP_VER}/mysqld_exporter-${MYSQLD_EXP_VER}.linux-${ARCH}.tar.gz"
      _download "$URL" "$TMP/me.tar.gz"
      tar xzf "$TMP/me.tar.gz" -C "$TMP"
      cp "$TMP/mysqld_exporter-${MYSQLD_EXP_VER}.linux-${ARCH}/mysqld_exporter" "$INSTALL_DIR/"
      chmod +x "$INSTALL_DIR/mysqld_exporter"
      rm -rf "$TMP"
    fi
    # Create .my.cnf for auth if not exists
    if [[ ! -f /etc/.mysqld_exporter.cnf ]]; then
      cat > /etc/.mysqld_exporter.cnf <<'CNF'
[client]
user=exporter
password=CHANGE_ME
CNF
      echo "  ⚠  Edit /etc/.mysqld_exporter.cnf with the exporter DB credentials"
      echo "     CREATE USER 'exporter'@'localhost' IDENTIFIED BY 'CHANGE_ME';"
      echo "     GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'localhost';"
    fi
    if ! systemctl is-active --quiet mysqld_exporter 2>/dev/null; then
      _install_service mysqld_exporter "[Unit]
Description=MySQL/MariaDB Exporter
After=network.target

[Service]
User=nobody
ExecStart=${INSTALL_DIR}/mysqld_exporter --config.my-cnf=/etc/.mysqld_exporter.cnf --web.listen-address=0.0.0.0:9104
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target"
    fi
    echo "  mysqld_exporter: $(systemctl is-active mysqld_exporter)  (port 9104)"

  elif [[ "$DB_TYPE" == "postgresql" ]]; then
    echo "→ Installing postgres_exporter v${PG_EXP_VER} …"
    if [[ ! -f "$INSTALL_DIR/postgres_exporter" ]]; then
      TMP=$(mktemp -d)
      URL="https://github.com/prometheus-community/postgres_exporter/releases/download/v${PG_EXP_VER}/postgres_exporter-${PG_EXP_VER}.linux-${ARCH}.tar.gz"
      _download "$URL" "$TMP/pe.tar.gz"
      tar xzf "$TMP/pe.tar.gz" -C "$TMP"
      cp "$TMP/postgres_exporter-${PG_EXP_VER}.linux-${ARCH}/postgres_exporter" "$INSTALL_DIR/"
      chmod +x "$INSTALL_DIR/postgres_exporter"
      rm -rf "$TMP"
    fi
    if ! systemctl is-active --quiet postgres_exporter 2>/dev/null; then
      _install_service postgres_exporter "[Unit]
Description=PostgreSQL Exporter
After=network.target

[Service]
User=nobody
Environment=DATA_SOURCE_NAME=postgresql://exporter:CHANGE_ME@localhost:5432/postgres?sslmode=disable
ExecStart=${INSTALL_DIR}/postgres_exporter --web.listen-address=0.0.0.0:9187
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target"
    fi
    echo "  ⚠  Set DATA_SOURCE_NAME in /etc/systemd/system/postgres_exporter.service"
    echo "  postgres_exporter: $(systemctl is-active postgres_exporter)  (port 9187)"
  fi
fi

# ── 4. Promtail ───────────────────────────────────────────────────────────────
echo ""
echo "→ Installing Promtail v${PROMTAIL_VER} …"
if [[ ! -f "$INSTALL_DIR/promtail" ]]; then
  TMP=$(mktemp -d)
  URL="https://github.com/grafana/loki/releases/download/v${PROMTAIL_VER}/promtail-linux-${ARCH}.zip"
  _download "$URL" "$TMP/promtail.zip"
  cd "$TMP" && unzip -q promtail.zip
  cp "$TMP/promtail-linux-${ARCH}" "$INSTALL_DIR/promtail"
  chmod +x "$INSTALL_DIR/promtail"
  rm -rf "$TMP"
fi

BENCH_PATH="${BENCH_DIR:-/home/*/frappe-bench}"
BENCH_LOGS="${BENCH_PATH}/logs"

mkdir -p "$INSTALL_DIR/promtail"
cat > "$INSTALL_DIR/promtail/promtail-config.yaml" <<YAML
server:
  http_listen_port: 9080
  grpc_listen_port: 0
  log_level: warn

positions:
  filename: ${INSTALL_DIR}/promtail/positions.yaml

clients:
  - url: ${LOKI_URL}

scrape_configs:

  - job_name: frappe_app
    static_configs:
      - targets: [localhost]
        labels:
          job: frappe
          log_type: application
          server_name: ${SERVER_NAME}
          env: ${ENV_LABEL}
          __path__: ${BENCH_LOGS}/frappe.log
    pipeline_stages:
      - regex:
          expression: '.*(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL).*'
      - labels:
          level:

  - job_name: frappe_bench
    static_configs:
      - targets: [localhost]
        labels:
          job: frappe
          log_type: bench
          server_name: ${SERVER_NAME}
          env: ${ENV_LABEL}
          __path__: ${BENCH_LOGS}/bench.log
    pipeline_stages:
      - regex:
          expression: '.*(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL).*'
      - labels:
          level:

  - job_name: frappe_worker
    static_configs:
      - targets: [localhost]
        labels:
          job: frappe
          log_type: worker
          server_name: ${SERVER_NAME}
          env: ${ENV_LABEL}
          __path__: ${BENCH_LOGS}/worker.log
    pipeline_stages:
      - regex:
          expression: '.*(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL).*'
      - labels:
          level:

  - job_name: frappe_scheduler
    static_configs:
      - targets: [localhost]
        labels:
          job: frappe
          log_type: scheduler
          server_name: ${SERVER_NAME}
          env: ${ENV_LABEL}
          __path__: ${BENCH_LOGS}/scheduler.log
    pipeline_stages:
      - regex:
          expression: '.*(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL).*'
      - labels:
          level:

  - job_name: frappe_database
    static_configs:
      - targets: [localhost]
        labels:
          job: frappe
          log_type: database
          server_name: ${SERVER_NAME}
          env: ${ENV_LABEL}
          __path__: ${BENCH_LOGS}/database.log

  - job_name: syslog
    static_configs:
      - targets: [localhost]
        labels:
          job: syslog
          log_type: system
          server_name: ${SERVER_NAME}
          env: ${ENV_LABEL}
          __path__: /var/log/syslog
YAML

if ! systemctl is-active --quiet promtail 2>/dev/null; then
  _install_service promtail "[Unit]
Description=Grafana Promtail Log Collector (${SERVER_NAME})
After=network.target

[Service]
User=$(logname 2>/dev/null || echo nobody)
ExecStart=${INSTALL_DIR}/promtail -config.file=${INSTALL_DIR}/promtail/promtail-config.yaml
Restart=on-failure
RestartSec=5s
StandardError=journal

[Install]
WantedBy=multi-user.target"
fi
echo "  promtail: $(systemctl is-active promtail)  (port 9080)"

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Installation complete for: ${SERVER_NAME}"
echo "============================================================"
echo ""
echo " NEXT STEPS — on the CENTRAL monitoring server:"
echo " 1. Open Frappe → Frappe K6 → Remote Server → New"
echo "    server_name:          ${SERVER_NAME}"
echo "    host:                 $(hostname -I | awk '{print $1}')"
echo "    environment:          ${ENV_LABEL}"
echo "    node_exporter_port:   9100"
if [[ $SKIP_REDIS -eq 0 ]]; then
echo "    redis_exporter_port:  9121  (enabled)"
fi
if [[ $SKIP_DB -eq 0 ]]; then
echo "    db_exporter_port:     9104/9187  (enabled)"
fi
echo "    promtail_enabled:     yes"
echo ""
echo " 2. Save the Remote Server record."
echo "    Prometheus config will be rebuilt automatically."
echo ""
echo " 3. Click 'Ping / Check Connectivity' to verify."
echo ""
echo " Open ports required from central server:"
echo "   TCP 9100  — node_exporter"
[[ $SKIP_REDIS -eq 0 ]] && echo "   TCP 9121  — redis_exporter"
[[ $SKIP_DB -eq 0 ]]    && echo "   TCP 9104/9187  — db_exporter"
echo "   TCP 3100  — Loki (from this server to central, OUTBOUND already open)"
echo "============================================================"

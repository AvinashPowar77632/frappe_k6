#!/usr/bin/env bash
# ============================================================
# run_tests.sh — Dynamic k6 test runner for any Frappe bench site
# ============================================================
#
# Usage:
#   ./run_tests.sh --site erpv16.com --scenario smoke
#   ./run_tests.sh --site erpv16.com --bench /home/erpadmin/eduv16 --scenario load
#   ./run_tests.sh --site erpv16.com --scenario stress --user admin --password secret
#   ./run_tests.sh --site erpv16.com --scenario spike --protocol https
#   ./run_tests.sh --site erpv16.com --scenario soak --soak-duration 30m
#   ./run_tests.sh --site erpv16.com --scenario all    # run smoke → load → stress → spike
#
# Scenarios: smoke | load | stress | spike | soak | all
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORTS_DIR="$SCRIPT_DIR/reports"
mkdir -p "$REPORTS_DIR"

# Defaults
SITE=""
BENCH=""
SCENARIO="smoke"
API_USER="Administrator"
API_PASSWORD="admin"
PROTOCOL="http"
PORT=""
SOAK_DURATION="2h"
GRAFANA_OUTPUT=""
EXTRA_OPTS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --site)          SITE="$2";           shift 2 ;;
    --bench)         BENCH="$2";          shift 2 ;;
    --scenario)      SCENARIO="$2";       shift 2 ;;
    --user)          API_USER="$2";       shift 2 ;;
    --password)      API_PASSWORD="$2";   shift 2 ;;
    --protocol)      PROTOCOL="$2";       shift 2 ;;
    --port)          PORT="$2";           shift 2 ;;
    --soak-duration) SOAK_DURATION="$2";  shift 2 ;;
    --grafana-url)   GRAFANA_OUTPUT="$2"; shift 2 ;;
    --vus)           EXTRA_OPTS="$EXTRA_OPTS --vus $2"; shift 2 ;;
    --duration)      EXTRA_OPTS="$EXTRA_OPTS --duration $2"; shift 2 ;;
    *) echo "[WARN] Unknown option: $1"; shift ;;
  esac
done

# Validate required args
if [[ -z "$SITE" ]]; then
  echo "[ERROR] --site is required. Example: --site erpv16.com"
  exit 1
fi

if ! command -v k6 &>/dev/null; then
  echo "[ERROR] k6 is not installed. Run: bash install_k6.sh"
  exit 1
fi

# Auto-detect bench path from script location if not provided
if [[ -z "$BENCH" ]]; then
  BENCH="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
  if [[ ! -d "$BENCH/sites/$SITE" ]]; then
    echo "[ERROR] Cannot auto-detect bench. Use --bench /path/to/bench"
    exit 1
  fi
fi

echo "======================================================"
echo "  Frappe k6 Load Tester"
echo "  Site      : $SITE"
echo "  Bench     : $BENCH"
echo "  Scenario  : $SCENARIO"
echo "  User      : $API_USER"
echo "======================================================"

# Step 1: Generate dynamic site config
echo "[1/3] Generating site config..."
python3 "$SCRIPT_DIR/setup_config.py" \
  --site "$SITE" \
  --bench "$BENCH" \
  --user "$API_USER" \
  --password "$API_PASSWORD" \
  --protocol "$PROTOCOL" \
  ${PORT:+--port "$PORT"}

# Step 2: Build k6 env vars (for override support)
K6_ENVS="-e K6_BASE_URL=${PROTOCOL}://${SITE}${PORT:+:$PORT}"
K6_ENVS="$K6_ENVS -e K6_API_USER=$API_USER"
K6_ENVS="$K6_ENVS -e K6_API_PASSWORD=$API_PASSWORD"
K6_ENVS="$K6_ENVS -e K6_SITE_NAME=$SITE"
K6_ENVS="$K6_ENVS -e SOAK_DURATION=$SOAK_DURATION"

# Step 3: Build output flags
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
JSON_OUT="$REPORTS_DIR/${SCENARIO}_${SITE}_${TIMESTAMP}.json"
K6_OUT="--out json=$JSON_OUT"

if [[ -n "$GRAFANA_OUTPUT" ]]; then
  K6_OUT="$K6_OUT --out influxdb=$GRAFANA_OUTPUT"
fi

run_scenario() {
  local sc="$1"
  local script="$SCRIPT_DIR/scenarios/${sc}_test.js"

  if [[ ! -f "$script" ]]; then
    echo "[ERROR] Scenario script not found: $script"
    exit 1
  fi

  echo ""
  echo "[2/3] Running: $sc test → $script"
  echo "      Output  : $JSON_OUT"
  echo "------------------------------------------------------"

  # shellcheck disable=SC2086
  k6 run $K6_ENVS $K6_OUT $EXTRA_OPTS "$script"

  echo ""
  echo "[3/3] ✅ $sc test complete. Report: $JSON_OUT"
}

# Step 3: Run scenario(s)
case "$SCENARIO" in
  smoke|load|stress|spike|soak)
    run_scenario "$SCENARIO"
    ;;
  all)
    echo "[INFO] Running all scenarios: smoke → load → stress → spike"
    for sc in smoke load stress spike; do
      run_scenario "$sc"
      sleep 5
    done
    ;;
  *)
    echo "[ERROR] Unknown scenario: $SCENARIO"
    echo "        Valid: smoke | load | stress | spike | soak | all"
    exit 1
    ;;
esac

echo ""
echo "======================================================"
echo "  All done! JSON results saved in: $REPORTS_DIR/"
echo "  To visualize: open Grafana → import k6 dashboard"
echo "    Dashboard ID: 2587 (k6 Load Testing Results)"
echo "======================================================"

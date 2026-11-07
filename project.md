# frappe_k6 — K6 Load Testing for Frappe

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/frappe/frappe_k6/blob/main/LICENSE)

## Overview

**frappe_k6** is a performance testing and load testing suite for Frappe/ERPNext sites, built on [k6](https://grafana.com/docs/k6/). It provides dynamic API testing, load/stress/spike/soak scenarios, and optional Grafana monitoring integration.

The project is **bench-agnostic** — it can be installed on any Frappe bench and test any site.

---

## Features

### API Builder

- Construct and send API requests with assertions
- Save requests in collections
- Add to load tests

### Load Test Scenarios

| Scenario | VUs | Duration | Purpose |
|----------|-----|----------|---------|
| **smoke** | 1-2 | ~1 min | Baseline sanity check |
| **load** | up to 50 | ~11 min | Normal expected traffic |
| **stress** | up to 250 | ~16 min | Find breaking point |
| **spike** | 500 VU spike | ~10 min | Sudden burst (exam/admission day) |
| **soak** | 30 | 2h (configurable) | Memory leak / endurance |
| **all** | — | — | Run smoke → load → stress → spike sequentially |

### Monitoring (Optional)

- Prometheus metrics endpoints
- Grafana dashboards (ID: 2587)
- Loki logging for run events
- Alert rules and notifications (email, Slack, Teams, generic webhook)
- Hybrid mode with local Prometheus + remote write to Grafana Cloud

### EDU APIs Tested

- Academic Year, Program, Course, Student, Student Applicant
- Student Group, Fee Structure, Assessment Plan, Instructor
- Course Schedule, Guardian, Program Enrollment
- Fee Schedule, Assessment Result
- Frappe core: boot info, global search, notifications, user list, system settings

---

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench --site <site> install-app frappe_k6
```

### Install k6 binary

```bash
bench frappe-k6 install-k6
```

### Doctor check

```bash
bench --site <site> frappe-k6 doctor
```

### Setup local monitoring stack (optional, needs sudo)

```bash
bench --site <site> frappe-k6 setup-local-stack [--skip Grafana --skip Loki ...]
```

---

## Quick Start — Running Tests

```bash
# Smoke test (sanity check, ~1 min)
./run_tests.sh --site erpv16.com --bench /home/erpadmin/eduv16 --scenario smoke

# Load test (normal traffic, ~11 min)
./run_tests.sh --site erpv16.com --bench /home/erpadmin/eduv16 --scenario load

# Stress test (find breaking point, ~16 min)
./run_tests.sh --site erpv16.com --bench /home/erpadmin/eduv16 --scenario stress

# Spike test (sudden 500 VU burst, ~10 min)
./run_tests.sh --site erpv16.com --bench /home/erpadmin/eduv16 --scenario spike

# Soak test (2-hour endurance, or override duration)
./run_tests.sh --site erpv16.com --bench /home/erpadmin/eduv16 --scenario soak --soak-duration 30m

# Run all scenarios sequentially
./run_tests.sh --site erpv16.com --bench /home/erpadmin/eduv16 --scenario all
```

### With credentials

```bash
./run_tests.sh --site myschool.com --bench /home/erpadmin/bench-school \
    --user admin --password mysecret --scenario load
```

### HTTPS site

```bash
./run_tests.sh --site myschool.com --protocol https --scenario smoke
```

### Using ENV vars (no site.json needed, ideal for CI/CD)

```bash
K6_BASE_URL=http://othersite.com K6_API_USER=Administrator K6_API_PASSWORD=admin \
    k6 run scenarios/smoke_test.js
```

---

## Project Structure

```
frappe_k6/
├── pyproject.toml          # Python project metadata (ruff, bench dev-deps)
├── README.md               # Detailed documentation (installation, roles, CI)
├── k6_tests/               # k6 test runner and scenarios
│   ├── config/             # env.js — Dynamic config loader (ENV vars > site.json > defaults)
│   ├── scenarios/           # k6 test scripts
│   │   ├── smoke_test.js       # 2 VUs, 1 min — baseline sanity
│   │   ├── load_test.js        # up to 50 VUs, 11 min — normal traffic
│   │   ├── stress_test.js      # up to 250 VUs, 16 min — breaking point
│   │   ├── spike_test.js       # 500 VU spike — sudden burst
│   │   ├── soak_test.js        # 30 VUs, 2h — memory leak / endurance
│   │   └── quick_test.js       # Quick lightweight test
│   ├── tests/              # test modules imported by scenarios
│   │   ├── auth.js             # Login / logout / session validation
│   │   ├── common_apis.js      # Frappe core: boot, search, notifications, meta
│   │   └── edu_apis.js         # EDU doctypes: Student, Program, Course, Fee, etc.
│   ├── utils/              # shared helpers
│   │   └── helpers.js          # login, getList, callMethod, authHeaders, thinkTime, metrics
│   ├── reports/              # JSON result files (auto-generated)
│   ├── setup_config.py       # Reads bench site config → writes config/site.json
│   ├── install_k6.sh         # One-shot k6 installer (Ubuntu/macOS)
│   └── run_tests.sh          # Main runner — works for ANY bench site
├── frappe_k6/              # Frappe app source
│   ├── __init__.py           # Version: 0.0.1
│   ├── commands.py           # CLI commands for the app
│   ├── api/                  # API endpoints (builder, credentials, configs)
│   ├── k6_runner/            # k6 execution orchestration
│   ├── config/               # Default configs and patch files
│   ├── patches/              # Frappe patches
│   ├── security.py           # Security utilities
│   ├── hooks.py              # Frappe hooks
│   ├── tasks.py              # Background task handlers
│   ├── install.py            # Installation logic
│   ├── alerts.py             # Alert configuration
│   ├── grafana_cloud.py      # Grafana Cloud integration
│   ├── security.py           # Encryption/decryption
│   ├── modules.txt           # Frappe modules
│   ├── public/               # Static assets
│   ├── templates/            # Jinja2 templates
│   └── www/                  # WWW routes
├── setup/                  # Grafana dashboards, exporters, alerts
│   ├── dashboards/           # Pre-built Grafana dashboards
│   ├── exporters/            # Prometheus/Loki exporters
│   └── alerts/               # Alert rules configuration
├── k6_tests/scripts/       # Helper scripts
└── license.txt
```

---

## Configuration

### Dynamic Config (`k6_tests/config/env.js`)

Loads configuration in priority order:

1. Environment variables (highest priority)
2. `site.json` from bench site config
3. Defaults defined in the script

### Thresholds (Failure Criteria)

| Metric | Smoke/Load/Soak | Stress | Spike |
|--------|-----------------|--------|-------|
| Error rate | < 1% | < 10% | < 15% |
| P95 duration | < 2000 ms | < 5000 ms | < 10000 ms |
| P99 duration | < 5000 ms | — | — |

---

## API Authentication

Credentials are stored encrypted:

- **Load Test Endpoint credentials** → Password field
- **API Request auth configs** → Site encryption key

During a run, credentials are written to a data file readable only by the bench user, deleted when the run ends.

An endpoint using **Session (Frappe Login)** needs `user:password` set explicitly.

### API Token

```
X-Frappe-K6-Token: <frappe_k6_metrics_token from site_config.json>
```

Required for: `frappe_k6.api.system_metrics.prometheus_metrics`, `get_all_metrics`, `frappe_k6.api.load_test.get_active_run_metrics`

---

## Grafana Cloud Integration

1. Fill in **Monitor Settings → Grafana Cloud**:
   - Grafana Cloud URL (e.g., `https://yourstack.grafana.net`)
   - Grafana service account token (Admin role)
   - Cloud access policy token (`metrics:write` and `logs:write` scopes)

2. Click **Grafana Cloud → Connect & Migrate**

3. This imports 8 bundled dashboards, creates a Frappe K6 contact point, and syncs alert rules

### CLI

```bash
bench --site <site> frappe-k6 connect-cloud \
    --grafana-url https://yourstack.grafana.net \
    --sa-token "$GRAFANA_SA_TOKEN" \
    --access-token "$GRAFANA_CLOUD_TOKEN"

bench --site <site> frappe-k6 cloud-sync dashboards|alerts|history|test
```

---

## Contributing

This app uses `pre-commit` for code formatting and linting. Please install pre-commit and enable it:

```bash
cd apps/frappe_k6
pre-commit install
```

Pre-commit is configured to use:

- ruff (Python linting/formatting)
- eslint (JavaScript linting)
- prettier (JavaScript formatting)
- pyupgrade (Python version upgrades)

Run the tests:

```bash
bench --site <site> run-tests --app frappe_k6
```

---

## License

MIT
# frappe_k6 — Grafana k6 Load Testing for Frappe EDU

Dynamic API load/stress/spike/soak testing suite for any Frappe bench site.

---

## Structure

```
k6_tests/
├── config/
│   └── env.js              # Dynamic config loader (ENV vars > site.json > defaults)
├── scenarios/
│   ├── smoke_test.js       # 2 VUs, 1 min — baseline sanity
│   ├── load_test.js        # up to 50 VUs, 11 min — normal traffic
│   ├── stress_test.js      # up to 250 VUs, 16 min — breaking point
│   ├── spike_test.js       # 500 VU spike — sudden burst (exam/admission day)
│   └── soak_test.js        # 30 VUs, 2h — memory leak / endurance
├── tests/
│   ├── auth.js             # Login / logout / session validation
│   ├── edu_apis.js         # EDU doctypes: Student, Program, Course, Fee, etc.
│   └── common_apis.js      # Frappe core: boot, search, notifications, meta
├── utils/
│   └── helpers.js          # Shared: login, getList, callMethod, metrics
├── reports/                # JSON result files (auto-generated)
├── setup_config.py         # Reads bench site config → writes config/site.json
├── install_k6.sh           # One-shot k6 installer (Ubuntu/macOS)
└── run_tests.sh            # Main runner — works for ANY bench site
```

---

## Quick Start

### 1. Install k6

```bash
cd /path/to/any-bench/apps/frappe_k6/k6_tests
bash install_k6.sh
```

### 2. Run tests (any bench site)

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

### 3. Custom credentials

```bash
./run_tests.sh --site myschool.com --bench /home/erpadmin/bench-school \
    --user admin --password mysecret --scenario load
```

### 4. HTTPS site

```bash
./run_tests.sh --site myschool.com --protocol https --scenario smoke
```

---

## Use on ANY Bench Site

The app is **bench-agnostic**. Copy or symlink the `k6_tests/` folder, or install the `frappe_k6` app on any bench:

```bash
# Install on another bench
bench get-app frappe_k6 /home/erpadmin/eduv16/apps/frappe_k6
bench --site othersite.com install-app frappe_k6

# Then test that site
./run_tests.sh --site othersite.com --bench /home/erpadmin/other-bench --scenario smoke
```

Or use ENV vars (no site.json needed, ideal for CI/CD):

```bash
K6_BASE_URL=http://othersite.com K6_API_USER=Administrator K6_API_PASSWORD=admin \
    k6 run scenarios/smoke_test.js
```

---

## Grafana Dashboard (Optional)

Send results to InfluxDB → visualize in Grafana:

```bash
./run_tests.sh --site erpv16.com --scenario load \
    --grafana-url http://localhost:8086/mydb
```

Import Grafana dashboard **ID: 2587** (k6 Load Testing Results).

---

## Thresholds (What Counts as Failure)

| Metric          | Smoke/Load/Soak | Stress  | Spike   |
|-----------------|-----------------|---------|---------|
| Error rate      | < 1%            | < 10%   | < 15%   |
| P95 duration    | < 2000 ms       | < 5000 ms | < 10000 ms |
| P99 duration    | < 5000 ms       | —       | —       |

---

## EDU APIs Tested

- Academic Year, Program, Course, Student, Student Applicant
- Student Group, Fee Structure, Assessment Plan, Instructor
- Course Schedule, Guardian, Program Enrollment
- Fee Schedule, Assessment Result
- Frappe: boot info, global search, notifications, user list, system settings

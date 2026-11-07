### Frappe K6

API testing, load testing and performance monitoring for Frappe sites, built on [k6](https://grafana.com/docs/k6/).

- **API Builder** (`/api-builder`): build and send requests with assertions, save them in collections, and add them to a load test.
- **Load tests** (`/k6-monitor`, Load Test Config): smoke, load, stress, spike and soak scenarios against this site or a registered Remote Server. Each run is executed by a background job and records totals, latency percentiles and threshold pass/fail from k6's end-of-test summary.
- **Monitoring** (optional): Prometheus metrics endpoints, a Prometheus exporter, and Grafana dashboards in `frappe_k6/setup/`.

### Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench --site <site> install-app frappe_k6
```

Installing changes only the database and site config (roles, settings, a metrics token, sample configs). It needs no sudo and no network access.

Then:

```bash
bench frappe-k6 install-k6               # static k6 binary into <bench>/env/bin, checksum-verified, no sudo
bench --site <site> frappe-k6 doctor     # checks k6, workers, scheduler, roles, token
```

Load tests run on the `long` queue, so a worker must be running (`bench start`, or supervisor in production).

Optional self-hosted monitoring stack (node_exporter, Prometheus, Loki, Promtail, Grafana; needs sudo, systemd and internet):

```bash
bench --site <site> frappe-k6 setup-local-stack [--skip Grafana --skip Loki ...]
```

### Access

| Role | Can |
| --- | --- |
| K6 Manager | Create and run load tests, manage Remote Servers, see stored credentials |
| K6 User | Use the API Builder, view configs, runs and live metrics |
| System Manager | Everything, including Monitor Settings |

Credentials are stored encrypted: Load Test Endpoint credentials in a Password field, and API Request auth configs with the site encryption key. During a run they are written to a data file readable only by the bench user, which is deleted when the run ends. There are no default credentials. An endpoint using **Session (Frappe Login)** needs `user:password` set explicitly.

### Targets

The API Builder proxy and load tests refuse private, loopback and link-local addresses unless the target is one of these:

- this site
- an enabled Remote Server
- a host listed in **Monitor Settings → Allowed Target Hosts** (one `host` or `host:port` per line)

Public addresses are allowed.

### Metrics endpoints

`frappe_k6.api.system_metrics.prometheus_metrics`, `get_all_metrics` and `frappe_k6.api.load_test.get_active_run_metrics` need either a session with a K6 role, or the header

```
X-Frappe-K6-Token: <frappe_k6_metrics_token from site_config.json>
```

The bundled exporter (`frappe_k6/setup/frappe_k6_exporter.py`) reads the token from `FRAPPE_K6_METRICS_TOKEN` or `~/monitoring/.frappe_k6_metrics_token`, which `setup-local-stack` writes.

### Grafana Cloud

Fill these three fields in **Monitor Settings → Grafana Cloud**, then click **Grafana Cloud → Connect & Migrate**:

- **Grafana Cloud URL**, for example `https://yourstack.grafana.net`
- **Grafana service account token**, with the Admin role
- **Cloud access policy token**, with the `metrics:write` and `logs:write` scopes

Connect & Migrate does the following:

1. Discovers the stack's Prometheus and Loki endpoints, user IDs and datasource UIDs, so you don't copy them by hand.
2. Checks that both tokens can write, by sending one metric and one log line.
3. Switches **Monitoring Mode** to *Grafana Cloud*. If the local stack is running, it switches to *Hybrid* instead, which keeps the stack and forwards it to the cloud while you migrate.
4. Imports the 8 bundled dashboards into a *Frappe K6* folder, with datasources rewritten for the stack.
5. Creates a *Frappe K6* contact point from your alert channels and syncs the Grafana alert rules.
6. Turns past load-test runs into Grafana annotations.

The same steps from the shell:

```bash
bench --site <site> frappe-k6 connect-cloud --grafana-url https://yourstack.grafana.net \
    --sa-token "$GRAFANA_SA_TOKEN" --access-token "$GRAFANA_CLOUD_TOKEN"
bench --site <site> frappe-k6 cloud-sync dashboards|alerts|history|test
```

Once connected, in *Grafana Cloud* mode:

- Frappe pushes its own metrics every minute with Prometheus remote write. No agent or extra Python package is needed.
- Each load test pushes live metrics every 10 s. These use the names the dashboards expect.
- k6's native `k6_*` metrics are tagged with `testid`, `site` and `config`.
- Run start, finish and alert events go to Loki.

In *Hybrid* mode, the local Prometheus forwards everything with `remote_write` and adds an external `site` label.

Host metrics and bench logs are optional. They need [Grafana Alloy](https://grafana.com/docs/alloy/) on each server:

```bash
bench --site <site> frappe-k6 agent-config --output /etc/alloy/config.alloy
# run Alloy with GRAFANA_CLOUD_TOKEN set to the access policy token
```

### Alerts

Alerts are configured in **Monitor Settings → Alerts and Notifications**. Set any of: email addresses, a Slack webhook, a Microsoft Teams webhook, a generic JSON webhook. Users with the K6 Manager role always get in-app notifications.

There are two kinds of alert:

- **Grafana alert rules** (table in Monitor Settings) watch live metrics, such as p95 and error rate during a test, CPU, memory, disk, Redis, the database, the RQ backlog, and missing metrics. They are synced to Grafana Cloud and route to the *Frappe K6* contact point.
- **K6 Alert Rules** (DocType) check every finished run. The defaults are *Thresholds failed*, *Run failed* (k6 error or crash), and *P95 latency regression* (25% worse than the last 5 runs). Each hit is stored as a **K6 Alert** and sent to the channels above.

**Send Test Alert** checks every channel.

### Command-line suite

`k6_tests/` holds standalone scenarios for running k6 from the shell (`k6_tests/run_tests.sh`). Pass the password with `--password` or `K6_API_PASSWORD`; there is no default.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/frappe_k6
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

Run the tests with:

```bash
bench --site <site> run-tests --app frappe_k6
```

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit

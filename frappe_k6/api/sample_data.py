"""
Sample Load Test Configurations — one per scenario type.
Run via:  bench --site <site> execute frappe_k6.api.sample_data.create_sample_configs
"""
import frappe


SAMPLES = [
    {
        "test_name":    "Smoke Test – Sanity Check",
        "description":  "Quick sanity check. 2 VUs for 1 minute. Verifies the site is up and basic APIs respond.",
        "scenario_type": "smoke",
        "virtual_users": 2,
        "duration":      "1m",
        "ramp_up_time":  "30s",
        "ramp_down_time": "10s",
        "max_vus":       2,
        "think_time":    0.5,
        "endpoints": [
            {"api_name": "Health Check",       "http_method": "GET",  "endpoint_url": "/api/method/frappe.ping",                          "expected_status": 200, "weight": 1},
            {"api_name": "Get Logged In User", "http_method": "GET",  "endpoint_url": "/api/method/frappe.auth.get_logged_user",           "expected_status": 200, "weight": 1},
            {"api_name": "List DocTypes",      "http_method": "GET",  "endpoint_url": "/api/resource/DocType?limit=5",                    "expected_status": 200, "weight": 1},
        ],
    },
    {
        "test_name":    "Load Test – Normal Traffic",
        "description":  "Simulates expected production load. Ramps to 10 VUs over 1 min, sustains for 5 min.",
        "scenario_type": "load",
        "virtual_users": 10,
        "duration":      "5m",
        "ramp_up_time":  "1m",
        "ramp_down_time": "30s",
        "max_vus":       10,
        "think_time":    1.0,
        "endpoints": [
            {"api_name": "Ping",               "http_method": "GET",  "endpoint_url": "/api/method/frappe.ping",                          "expected_status": 200, "weight": 2},
            {"api_name": "Get Logged User",    "http_method": "GET",  "endpoint_url": "/api/method/frappe.auth.get_logged_user",           "expected_status": 200, "weight": 2},
            {"api_name": "List Users",         "http_method": "GET",  "endpoint_url": "/api/resource/User?limit=10",                      "expected_status": 200, "weight": 1},
            {"api_name": "List DocTypes",      "http_method": "GET",  "endpoint_url": "/api/resource/DocType?limit=10",                   "expected_status": 200, "weight": 1},
        ],
    },
    {
        "test_name":    "Stress Test – Find Breaking Point",
        "description":  "Incrementally ramps VUs to find the application's saturation point and failure threshold.",
        "scenario_type": "stress",
        "virtual_users": 50,
        "duration":      "10m",
        "ramp_up_time":  "3m",
        "ramp_down_time": "2m",
        "max_vus":       200,
        "think_time":    0.5,
        "endpoints": [
            {"api_name": "Ping",               "http_method": "GET",  "endpoint_url": "/api/method/frappe.ping",                          "expected_status": 200, "weight": 3},
            {"api_name": "Get Logged User",    "http_method": "GET",  "endpoint_url": "/api/method/frappe.auth.get_logged_user",           "expected_status": 200, "weight": 2},
            {"api_name": "List Users",         "http_method": "GET",  "endpoint_url": "/api/resource/User?limit=20",                      "expected_status": 200, "weight": 2},
            {"api_name": "List DocTypes",      "http_method": "GET",  "endpoint_url": "/api/resource/DocType?limit=20",                   "expected_status": 200, "weight": 1},
            {"api_name": "System Metrics API", "http_method": "GET",  "endpoint_url": "/api/method/frappe_k6.api.system_metrics.get_system_metrics", "expected_status": 200, "weight": 1},
        ],
    },
    {
        "test_name":    "Spike Test – Sudden Traffic Burst",
        "description":  "Simulates a sudden spike of 100 VUs followed by a rapid drop. Tests auto-scaling and resilience.",
        "scenario_type": "spike",
        "virtual_users": 100,
        "duration":      "3m",
        "ramp_up_time":  "10s",
        "ramp_down_time": "10s",
        "max_vus":       100,
        "think_time":    0.2,
        "endpoints": [
            {"api_name": "Ping",               "http_method": "GET",  "endpoint_url": "/api/method/frappe.ping",                          "expected_status": 200, "weight": 5},
            {"api_name": "Get Logged User",    "http_method": "GET",  "endpoint_url": "/api/method/frappe.auth.get_logged_user",           "expected_status": 200, "weight": 2},
            {"api_name": "List Users",         "http_method": "GET",  "endpoint_url": "/api/resource/User?limit=5",                       "expected_status": 200, "weight": 1},
        ],
    },
    {
        "test_name":    "Soak Test – 30-Min Endurance",
        "description":  "Long-running endurance test to detect memory leaks, resource exhaustion, and degradation over time.",
        "scenario_type": "soak",
        "virtual_users": 5,
        "duration":      "30m",
        "ramp_up_time":  "2m",
        "ramp_down_time": "2m",
        "max_vus":       5,
        "think_time":    2.0,
        "endpoints": [
            {"api_name": "Ping",               "http_method": "GET",  "endpoint_url": "/api/method/frappe.ping",                          "expected_status": 200, "weight": 2},
            {"api_name": "Get Logged User",    "http_method": "GET",  "endpoint_url": "/api/method/frappe.auth.get_logged_user",           "expected_status": 200, "weight": 2},
            {"api_name": "List DocTypes",      "http_method": "GET",  "endpoint_url": "/api/resource/DocType?limit=5",                    "expected_status": 200, "weight": 1},
            {"api_name": "System Metrics API", "http_method": "GET",  "endpoint_url": "/api/method/frappe_k6.api.system_metrics.get_system_metrics", "expected_status": 200, "weight": 1},
        ],
    },
    {
        "test_name":    "Custom Test – Frappe Core APIs",
        "description":  "Custom test targeting core Frappe REST APIs. Edit endpoints to match your actual workload.",
        "scenario_type": "custom",
        "virtual_users": 15,
        "duration":      "5m",
        "ramp_up_time":  "1m",
        "ramp_down_time": "30s",
        "max_vus":       30,
        "think_time":    1.0,
        "endpoints": [
            {"api_name": "Ping",               "http_method": "GET",  "endpoint_url": "/api/method/frappe.ping",                          "expected_status": 200, "weight": 1},
            {"api_name": "Get Logged User",    "http_method": "GET",  "endpoint_url": "/api/method/frappe.auth.get_logged_user",           "expected_status": 200, "weight": 2},
            {"api_name": "List Users",         "http_method": "GET",  "endpoint_url": "/api/resource/User?limit=10",                      "expected_status": 200, "weight": 2},
            {"api_name": "List DocTypes",      "http_method": "GET",  "endpoint_url": "/api/resource/DocType?limit=10",                   "expected_status": 200, "weight": 1},
            {"api_name": "Get DocType",        "http_method": "GET",  "endpoint_url": "/api/resource/DocType/User",                       "expected_status": 200, "weight": 1},
            {"api_name": "System Metrics API", "http_method": "GET",  "endpoint_url": "/api/method/frappe_k6.api.system_metrics.get_system_metrics", "expected_status": 200, "weight": 1},
        ],
    },
]


def create_sample_configs():
    """Insert sample Load Test Configs for all scenario types (skips existing)."""
    created = []
    skipped = []

    for cfg in SAMPLES:
        name = cfg["test_name"]
        if frappe.db.exists("Load Test Config", name):
            skipped.append(name)
            continue

        doc = frappe.get_doc({"doctype": "Load Test Config", **{
            k: v for k, v in cfg.items() if k != "endpoints"
        }})
        doc.status = "Ready"
        for ep in cfg["endpoints"]:
            doc.append("endpoints", {"doctype": "Load Test Endpoint", **ep})

        doc.insert(ignore_permissions=True)
        created.append(name)

    frappe.db.commit()
    print(f"\n✅ Created  ({len(created)}): {created}")
    print(f"⏭  Skipped  ({len(skipped)}): {skipped}")
    return {"created": created, "skipped": skipped}


def configure_monitor_settings(
    grafana_url="http://10.10.30.56:3000",
    prometheus_url="http://10.10.30.56:9090",
):
    """Set Grafana / Prometheus URLs in Monitor Settings.

    bench --site <site> execute frappe_k6.api.sample_data.configure_monitor_settings
    """
    doc = frappe.get_single("Monitor Settings")
    doc.grafana_url = grafana_url
    doc.prometheus_url = prometheus_url
    doc.grafana_enabled = 1
    doc.prometheus_enabled = 1
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"✅ Monitor Settings updated — Grafana: {grafana_url}  Prometheus: {prometheus_url}")
    return {"grafana_url": grafana_url, "prometheus_url": prometheus_url}

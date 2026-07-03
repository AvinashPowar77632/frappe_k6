import frappe

no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/k6-docs"
        raise frappe.Redirect

    context.no_cache = 1
    context.title = "Frappe K6 — User Manual"

    try:
        s = frappe.get_single("Monitor Settings")
        context.grafana_url    = s.grafana_url    or "http://localhost:3000"
        context.prometheus_url = s.prometheus_url or "http://localhost:9090"
        context.loki_url       = getattr(s, "loki_url", "") or "http://localhost:3100"
    except Exception:
        context.grafana_url    = "http://localhost:3000"
        context.prometheus_url = "http://localhost:9090"
        context.loki_url       = "http://localhost:3100"

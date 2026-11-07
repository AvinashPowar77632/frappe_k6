import frappe
from frappe import _

no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/k6-monitor"
        raise frappe.Redirect

    from frappe_k6.security import has_k6_access

    if not has_k6_access():
        raise frappe.PermissionError(_("You need the K6 Manager or K6 User role to open this page."))

    context.no_cache = 1
    context.title = "K6 Performance Monitor"

    try:
        settings = frappe.get_single("Monitor Settings")
        context.grafana_url = settings.grafana_url or ""
        context.prometheus_url = settings.prometheus_url or ""
        context.refresh_interval = (settings.refresh_interval or 5) * 1000
    except Exception:
        context.grafana_url = ""
        context.prometheus_url = ""
        context.refresh_interval = 5000

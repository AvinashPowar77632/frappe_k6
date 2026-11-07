import frappe
from frappe import _

no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/api-builder"
        raise frappe.Redirect

    from frappe_k6.security import has_k6_access

    if not has_k6_access():
        raise frappe.PermissionError(_("You need the K6 Manager or K6 User role to open this page."))

    context.no_cache = 1
    context.title = "API Builder"

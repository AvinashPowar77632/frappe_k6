import frappe
from frappe.model.document import Document


class MonitorSettings(Document):
    def on_update(self):
        frappe.cache().delete_value("monitor_settings")

import frappe
from frappe.model.document import Document


class LoadTestConfig(Document):
    def validate(self):
        if not self.endpoints:
            frappe.throw("Add at least one API endpoint before saving.")
        self.status = "Ready" if self.status == "Draft" else self.status

    def on_trash(self):
        runs = frappe.get_all("Load Test Run", filters={"config": self.name}, pluck="name")
        for run in runs:
            frappe.delete_doc("Load Test Run", run, force=True)

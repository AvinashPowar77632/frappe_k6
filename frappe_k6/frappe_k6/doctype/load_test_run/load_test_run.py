import frappe
from frappe.model.document import Document


class LoadTestRun(Document):
    def on_trash(self):
        import os
        if self.output_file and os.path.exists(self.output_file):
            try:
                os.remove(self.output_file)
            except Exception:
                pass

import frappe
from frappe.model.document import Document


class LoadTestRun(Document):
    def on_trash(self):
        import os
        for path in (self.output_file, self.summary_file, self.data_file, self.log_file):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

import json

import frappe
from frappe.model.document import Document

from frappe_k6.security import encrypt_auth_config


class APIRequest(Document):
    def validate(self):
        # Store passwords, tokens and key values encrypted with the site key
        try:
            cfg = json.loads(self.auth_config_json or "{}")
        except ValueError:
            frappe.throw("Auth config must be valid JSON.")
        if isinstance(cfg, dict):
            self.auth_config_json = json.dumps(encrypt_auth_config(cfg), indent=2)

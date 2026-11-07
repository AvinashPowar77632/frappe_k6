import frappe
from frappe.model.document import Document


class MonitorSettings(Document):
    def validate(self):
        url = (self.gc_grafana_url or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.gc_grafana_url = url

    def on_update(self):
        frappe.cache().delete_value("monitor_settings")
        forwarding_changed = any(
            self.has_value_changed(f)
            for f in ("monitoring_mode", "gc_prometheus_url", "gc_prometheus_user", "gc_access_policy_token")
        )
        if forwarding_changed and self.monitoring_mode in ("Self-hosted", "Hybrid"):
            # Hybrid adds/removes Grafana Cloud forwarding in the local Prometheus config
            try:
                from frappe_k6.frappe_k6.prometheus_manager import sync_prometheus_config

                sync_prometheus_config()
            except Exception as exc:
                frappe.log_error(f"prometheus_manager sync failed: {exc}", "Monitor Settings")

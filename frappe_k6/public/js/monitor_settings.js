/* Opens a URL in a new tab; bypasses popup blockers that block window.open in dropdowns */
function _open_url(url) {
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

/* Normalise a user-supplied URL — adds http:// if no protocol is present */
function _normalise_url(url) {
    if (!url) return "";
    url = url.trim();
    if (url && !/^https?:\/\//i.test(url)) {
        url = "http://" + url;
    }
    return url;
}

frappe.ui.form.on("Monitor Settings", {
    refresh(frm) {
        /* ── Open K6 Dashboard ─────────────────────────────── */
        frm.add_custom_button(__("🖥 Open Dashboard"), function () {
            _open_url("/k6-monitor");
        }).addClass("btn-primary");

        /* ── Grafana ───────────────────────────────────────── */
        frm.add_custom_button(__("📈 Open Grafana"), function () {
            /* Always read from DB so we get the saved value, not a stale frm.doc */
            frappe.db.get_single_value("Monitor Settings", "grafana_url").then(function (raw) {
                const url = _normalise_url(raw || frm.doc.grafana_url);
                if (url) {
                    _open_url(url);
                } else {
                    frappe.msgprint({
                        title: __("Grafana Not Configured"),
                        message: __(
                            "<p>No Grafana URL is set.</p>" +
                            "<ul style='margin-top:8px'>" +
                            "<li>View advanced dashboards and visualizations</li>" +
                            "<li>Analyze API performance metrics</li>" +
                            "<li>Monitor CPU, Memory, Disk, Network</li>" +
                            "<li>Track Redis, Database, and Application metrics</li>" +
                            "<li>Create custom charts and alerts</li>" +
                            "</ul>" +
                            "<p style='margin-top:10px'>Set the <strong>Grafana URL</strong> field above (e.g. <code>http://localhost:3000</code>) and save.</p>"
                        ),
                        indicator: "orange",
                    });
                }
            });
        }, __("External Links"));

        /* ── Prometheus ────────────────────────────────────── */
        frm.add_custom_button(__("📊 Open Prometheus"), function () {
            frappe.db.get_single_value("Monitor Settings", "prometheus_url").then(function (raw) {
                const url = _normalise_url(raw || frm.doc.prometheus_url);
                if (url) {
                    _open_url(url);
                } else {
                    frappe.msgprint({
                        title: __("Prometheus Not Configured"),
                        message: __(
                            "<p>No Prometheus URL is set.</p>" +
                            "<ul style='margin-top:8px'>" +
                            "<li>View collected metrics and targets</li>" +
                            "<li>Verify whether exporters are working correctly</li>" +
                            "<li>Query raw metrics using PromQL</li>" +
                            "<li>Troubleshoot monitoring and data collection issues</li>" +
                            "</ul>" +
                            "<p style='margin-top:10px'>Set the <strong>Prometheus URL</strong> field above (e.g. <code>http://localhost:9090</code>) and save.</p>"
                        ),
                        indicator: "orange",
                    });
                }
            });
        }, __("External Links"));
    },
});

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

/* Show a step → result table from the Grafana Cloud / alert endpoints */
function _show_results(title, results) {
    const rows = Object.entries(results || {}).map(([step, result]) => {
        const failed = String(result).startsWith("FAILED") || String(result).startsWith("failed");
        return `<tr><td>${frappe.utils.escape_html(step)}</td>` +
            `<td style="color:${failed ? "var(--red-600)" : "inherit"}">${frappe.utils.escape_html(String(result))}</td></tr>`;
    }).join("");
    frappe.msgprint({ title, message: `<table class="table table-bordered">${rows}</table>`, wide: true });
}

function _cloud_call(frm, method, title, freeze_message) {
    const run = () => frappe.call({
        method,
        freeze: true,
        freeze_message,
        callback(r) {
            _show_results(title, r.message);
            frm.reload_doc();
        },
    });
    /* Save first so the tokens just typed are used */
    if (frm.is_dirty()) {
        frm.save().then(run);
    } else {
        run();
    }
}

frappe.ui.form.on("Monitor Settings", {
    refresh(frm) {
        /* ── Grafana Cloud ─────────────────────────────────── */
        const gc = __("Grafana Cloud");
        frm.add_custom_button(__("Connect & Migrate"), () => {
            if (!frm.doc.gc_grafana_url || !frm.doc.gc_service_account_token) {
                frappe.msgprint(__("Fill the Grafana Cloud URL, the service account token and the access policy token first."));
                return;
            }
            frappe.confirm(
                __("Discover the stack, switch to Grafana Cloud (or Hybrid if the local stack runs), import dashboards, set up alert rules and annotate past runs?"),
                () => _cloud_call(frm, "frappe_k6.grafana_cloud.connect", __("Grafana Cloud setup"),
                    __("Connecting to Grafana Cloud…")),
            );
        }, gc);
        frm.add_custom_button(__("Test Connection"), () =>
            _cloud_call(frm, "frappe_k6.grafana_cloud.test_connection", __("Connection test"), __("Testing…")), gc);
        frm.add_custom_button(__("Import Dashboards"), () =>
            _cloud_call(frm, "frappe_k6.grafana_cloud.sync_dashboards", __("Dashboards"), __("Importing dashboards…")), gc);
        frm.add_custom_button(__("Sync Alert Rules"), () =>
            _cloud_call(frm, "frappe_k6.grafana_cloud.sync_alerts", __("Alert rules"), __("Syncing alert rules…")), gc);
        frm.add_custom_button(__("Migrate Run History"), () =>
            _cloud_call(frm, "frappe_k6.grafana_cloud.migrate_history", __("Run history"), __("Annotating past runs…")), gc);
        frm.add_custom_button(__("Send Test Alert"), () =>
            _cloud_call(frm, "frappe_k6.alerts.send_test_alert", __("Test alert"), __("Sending…")), gc);
        if (frm.doc.gc_grafana_url) {
            frm.add_custom_button(__("Open Grafana Cloud"), () =>
                _open_url(`${frm.doc.gc_grafana_url}/dashboards/f/${frm.doc.gc_folder_uid || "frappe-k6"}`), gc);
        }

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

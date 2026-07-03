frappe.ui.form.on("Remote Server", {
    refresh(frm) {
        frm.add_custom_button(__("Ping / Check Connectivity"), () => {
            frm.call({
                method: "frappe_k6.frappe_k6.doctype.remote_server.remote_server.ping_server",
                args: { server_name: frm.doc.name },
                callback(r) {
                    if (!r.exc && r.message) {
                        const { status, details } = r.message;
                        const rows = Object.entries(details)
                            .map(([k, v]) => `<tr><td>${k}</td><td>${v === "ok"
                                ? '<span style="color:green">✓ OK</span>'
                                : `<span style="color:red">✗ ${v}</span>`}</td></tr>`)
                            .join("");
                        frappe.msgprint({
                            title: `Server Status: ${status}`,
                            message: `<table class="table table-bordered table-sm">
                                <thead><tr><th>Exporter</th><th>Result</th></tr></thead>
                                <tbody>${rows}</tbody></table>`,
                            indicator: status === "Online" ? "green" : status === "Degraded" ? "orange" : "red",
                        });
                        frm.reload_doc();
                    }
                },
            });
        }, __("Actions"));

        frm.add_custom_button(__("Get Promtail Config Snippet"), () => {
            frm.call({
                method: "frappe_k6.frappe_k6.doctype.remote_server.remote_server.get_promtail_config_snippet",
                args: { server_name: frm.doc.name },
                callback(r) {
                    if (!r.exc && r.message) {
                        frappe.msgprint({
                            title: __("Promtail Config for {0}", [frm.doc.server_name]),
                            message: `<p>Copy this to <code>/etc/promtail/config.yaml</code> (or equivalent) on the remote server, then restart Promtail.</p>
                                <pre style="background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:6px;
                                            font-size:12px;max-height:400px;overflow:auto;">${frappe.utils.escape_html(r.message)}</pre>`,
                            wide: true,
                        });
                    }
                },
            });
        }, __("Actions"));

        if (frm.doc.host && !frm.doc.is_local) {
            const grafana_url = frappe.boot.sysdefaults && frappe.boot.sysdefaults.grafana_url
                || "http://localhost:3000";
            const server_filter = encodeURIComponent(frm.doc.server_name);
            frm.add_custom_button(__("View in Grafana"), () => {
                window.open(
                    `${grafana_url}/d/frappe-k6-multi?var-server=${server_filter}`,
                    "_blank"
                );
            }, __("Actions"));
        }
    },

    host(frm) {
        if (frm.doc.host === "localhost" || frm.doc.host === "127.0.0.1") {
            frm.set_value("is_local", 1);
        }
    },

    db_type(frm) {
        if (frm.doc.db_type === "None" || !frm.doc.db_type) {
            frm.set_value("db_exporter_enabled", 0);
            return;
        }
        const port = (frm.doc.db_type === "MariaDB" || frm.doc.db_type === "MySQL") ? 9104 : 9187;
        if (!frm.doc.db_exporter_port || frm.doc.db_exporter_port === 9104 || frm.doc.db_exporter_port === 9187) {
            frm.set_value("db_exporter_port", port);
        }
    },
});

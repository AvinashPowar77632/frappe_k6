frappe.ui.form.on("Load Test Config", {

    refresh(frm) {
        frm.trigger("_setup_buttons");
        frm.trigger("_render_last_run");
    },

    status(frm) {
        frm.trigger("_setup_buttons");
    },

    _setup_buttons(frm) {
        frm.clear_custom_buttons();

        const status = frm.doc.status;

        if (status === "Running") {
            frm.add_custom_button(__("⏹ Stop Test"), () => {
                frm.trigger("_stop_test");
            }).addClass("btn-danger");

            frm.add_custom_button(__("🔄 Refresh Status"), () => {
                frm.trigger("_refresh_status");
            });

        } else {
            frm.add_custom_button(__("▶ Run Test"), () => {
                frm.trigger("_run_test");
            }).addClass("btn-primary");

            frm.add_custom_button(__("🖥 Open Dashboard"), () => {
                window.open("/k6-monitor", "_blank");
            });
        }

        if (frm.doc.last_run) {
            frm.add_custom_button(__("📋 View Last Run"), () => {
                frappe.set_route("Form", "Load Test Run", frm.doc.last_run);
            });
        }
    },

    _run_test(frm) {
        if (frm.is_dirty()) {
            frappe.confirm(
                __("You have unsaved changes. Save and run?"),
                () => frm.save().then(() => frm.trigger("_do_run")),
            );
        } else {
            frm.trigger("_do_run");
        }
    },

    _do_run(frm) {
        frappe.show_alert({ message: __("Starting test…"), indicator: "blue" }, 3);

        frappe.call({
            method: "frappe_k6.api.load_test.start_load_test",
            args: { config_name: frm.docname },
            callback(r) {
                if (!r.message) return;
                const { run_name } = r.message;

                frappe.show_alert({
                    message: __("✅ Test started — Run: ") + run_name,
                    indicator: "green",
                }, 5);

                frm.reload_doc();

                /* auto-navigate to dashboard after short delay */
                setTimeout(() => {
                    frappe.confirm(
                        __("Test is running. Open the K6 Dashboard to see live metrics?"),
                        () => window.open("/k6-monitor", "_blank"),
                    );
                }, 1500);
            },
            error(r) {
                frappe.msgprint({
                    title: __("Failed to Start Test"),
                    message: r.message || __("Unknown error. Check server logs."),
                    indicator: "red",
                });
            },
        });
    },

    _stop_test(frm) {
        if (!frm.doc.last_run) {
            frappe.msgprint(__("No active run found."));
            return;
        }
        frappe.confirm(__("Stop the running test?"), () => {
            frappe.call({
                method: "frappe_k6.api.load_test.stop_load_test",
                args: { run_name: frm.doc.last_run },
                callback() {
                    frappe.show_alert({ message: __("Test stopped."), indicator: "orange" }, 4);
                    frm.reload_doc();
                },
            });
        });
    },

    _refresh_status(frm) {
        if (!frm.doc.last_run) return;
        frappe.call({
            method: "frappe_k6.api.load_test.get_test_status",
            args: { run_name: frm.doc.last_run },
            callback(r) {
                const s = r.message;
                if (!s) return;
                const m = s.metrics || {};
                const dur = m.http_req_duration || {};
                frappe.msgprint({
                    title: __("Live Status — ") + frm.doc.last_run,
                    message: `
                        <table class="table table-bordered" style="margin:0">
                          <tr><th>Running</th><td>${s.is_running ? "Yes ●" : "No"}</td></tr>
                          <tr><th>Requests</th><td>${(m.http_reqs || {}).count || 0}</td></tr>
                          <tr><th>RPS</th><td>${(m.rps || 0).toFixed(2)}</td></tr>
                          <tr><th>Avg Latency</th><td>${(dur.avg || 0).toFixed(0)} ms</td></tr>
                          <tr><th>P95 Latency</th><td>${(dur.p95 || 0).toFixed(0)} ms</td></tr>
                          <tr><th>Errors</th><td>${(m.http_req_failed || {}).count || 0}</td></tr>
                          <tr><th>VUs</th><td>${(m.vus || {}).current || 0}</td></tr>
                        </table>`,
                    indicator: s.is_running ? "blue" : "green",
                });
                if (!s.is_running) frm.reload_doc();
            },
        });
    },

    _render_last_run(frm) {
        const wrapper = frm.get_field("last_run")
            && frm.get_field("last_run").$wrapper;
        if (!wrapper) return;
        const badge = frm.doc.last_run_status;
        if (!badge) return;
        const color = {
            Completed: "green", Running: "blue",
            Failed: "red", Stopped: "orange",
        }[badge] || "gray";
        wrapper.find(".control-value").html(
            `${frm.doc.last_run || ""} &nbsp;<span class="indicator-pill ${color}">${badge}</span>`
        );
    },
});

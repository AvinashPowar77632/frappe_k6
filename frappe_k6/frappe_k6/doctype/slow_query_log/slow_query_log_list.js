// Copyright (c) 2026, Avinash and contributors
// For license information, please see license.txt

frappe.listview_settings["Slow Query Log"] = {
	hide_name_column: true,

	get_indicator(doc) {
		const t = doc.execution_time || 0;
		if (t >= 5) return [__("{0}s", [t.toFixed(2)]), "red", "execution_time,>=,5"];
		if (t >= 2) return [__("{0}s", [t.toFixed(2)]), "orange", "execution_time,>=,2"];
		return [__("{0}s", [t.toFixed(2)]), "yellow", "execution_time,<,2"];
	},

	onload(listview) {
		listview.page.add_inner_button(__("Clear All"), () => {
			frappe.confirm(__("Delete all Slow Query Log entries?"), () => {
				frappe.call({
					method: "frappe_k6.frappe_k6.doctype.slow_query_log.slow_query_log.clear_slow_query_logs",
					freeze: true,
					callback: () => listview.refresh(),
				});
			});
		});

		listview.page.add_inner_button(__("Settings"), () => {
			frappe.set_route("Form", "Monitor Settings");
		});
	},
};

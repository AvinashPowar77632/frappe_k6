/**
 * Common Frappe framework API tests.
 * Covers: boot info, doctype meta, search, report, desk page, etc.
 */

import http from "k6/http";
import { check, group } from "k6";
import { callMethod, thinkTime, apiDuration, apiErrors, apiCalls } from "../utils/helpers.js";

export function commonApiTests(baseUrl, headers) {
  group("Common: Boot Info", () => {
    const res = http.get(`${baseUrl}/api/method/frappe.client.get_boot_info`, {
      headers,
      tags: { name: "boot_info" },
    });

    apiDuration.add(res.timings.duration);
    apiCalls.add(1);
    apiErrors.add(res.status !== 200 ? 1 : 0);

    check(res, { "boot_info: 200": (r) => r.status === 200 });
    thinkTime();
  });

  group("Common: DocType Meta - Student", () => {
    callMethod(
      baseUrl,
      "frappe.desk.form.load.getdoc",
      { doctype: "Student", name: "Student" },
      headers
    );
    thinkTime();
  });

  group("Common: Global Search", () => {
    const res = http.get(
      `${baseUrl}/api/method/frappe.utils.global_search.search?text=student&doctype=Student`,
      { headers, tags: { name: "global_search" } }
    );

    apiDuration.add(res.timings.duration);
    apiCalls.add(1);
    apiErrors.add(res.status !== 200 ? 1 : 0);

    check(res, { "global_search: 200": (r) => r.status === 200 });
    thinkTime();
  });

  group("Common: Get Notification Count", () => {
    callMethod(baseUrl, "frappe.desk.notifications.get_notification_info", {}, headers);
    thinkTime();
  });

  group("Common: Get User List", () => {
    callMethod(
      baseUrl,
      "frappe.client.get_list",
      { doctype: "User", fields: ["name", "full_name", "email"], limit: 10 },
      headers
    );
    thinkTime();
  });

  group("Common: Get System Settings", () => {
    callMethod(
      baseUrl,
      "frappe.client.get",
      { doctype: "System Settings" },
      headers
    );
    thinkTime();
  });
}

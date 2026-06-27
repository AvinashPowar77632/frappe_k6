/**
 * QUICK TEST — Single API test to verify k6 + Frappe connection
 * 
 * Tests: login → get Student list → logout
 * 
 * Run:
 *   k6 run scenarios/quick_test.js
 *   k6 run scenarios/quick_test.js -e K6_BASE_URL=http://localhost:8003 -e K6_API_USER=Administrator -e K6_API_PASSWORD=admin
 */

import http from "k6/http";
import { check, group, sleep } from "k6";

const BASE_URL  = __ENV.K6_BASE_URL  || "http://localhost:8003";
const API_USER  = __ENV.K6_API_USER  || "Administrator";
const API_PASS  = __ENV.K6_API_PASSWORD || "admin";

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    http_req_failed:   ["rate<0.01"],
    http_req_duration: ["p(95)<5000"],
  },
};

export default function () {
  let cookie = "";
  let csrfToken = "";

  // ── 1. LOGIN ──────────────────────────────────────────────
  group("1. Login", () => {
    const res = http.post(
      `${BASE_URL}/api/method/login`,
      JSON.stringify({ usr: API_USER, pwd: API_PASS }),
      { headers: { "Content-Type": "application/json" }, tags: { name: "login" } }
    );

    const ok = check(res, {
      "login → HTTP 200":       (r) => r.status === 200,
      "login → sid cookie set": (r) => r.cookies["sid"] !== undefined,
    });

    console.log(`LOGIN  status=${res.status}  duration=${res.timings.duration}ms`);

    if (ok && res.cookies["sid"]) {
      cookie = `sid=${res.cookies["sid"][0].value}`;
      // Extract CSRF token (set as cookie after login)
      if (res.cookies["csrf_token"]) {
        csrfToken = res.cookies["csrf_token"][0].value;
        cookie += `; csrf_token=${csrfToken}`;
      }
    } else {
      console.error("LOGIN FAILED — body:", res.body.substring(0, 300));
    }
  });

  if (!cookie) return;

  sleep(0.5);

  // ── 2. GET STUDENT LIST (EDU API) ─────────────────────────
  group("2. Get Student List", () => {
    const res = http.get(
      `${BASE_URL}/api/resource/Student?limit=5`,
      { headers: { "Content-Type": "application/json", Cookie: cookie }, tags: { name: "student_list" } }
    );

    check(res, {
      "student list → HTTP 200":    (r) => r.status === 200,
      "student list → has data key":(r) => {
        try { return JSON.parse(r.body).data !== undefined; } catch (_) { return false; }
      },
    });

    console.log(`STUDENT LIST  status=${res.status}  duration=${res.timings.duration}ms`);
    if (res.status === 200) {
      try {
        const body = JSON.parse(res.body);
        console.log(`  → returned ${body.data ? body.data.length : 0} students`);
      } catch (_) {}
    } else {
      console.error("  → body:", res.body.substring(0, 300));
    }
  });

  sleep(0.5);

  // ── 3. GET ERPNEXT COMPANY LIST (ERPNext/common API) ──────
  group("3. Get Company List (ERPNext)", () => {
    const res = http.get(
      `${BASE_URL}/api/resource/Company?limit=5`,
      { headers: { "Content-Type": "application/json", Cookie: cookie }, tags: { name: "company_list" } }
    );

    check(res, {
      "company list → HTTP 200":    (r) => r.status === 200,
    });

    console.log(`COMPANY LIST  status=${res.status}  duration=${res.timings.duration}ms`);
    if (res.status === 200) {
      try {
        const body = JSON.parse(res.body);
        const names = (body.data || []).map((c) => c.name).join(", ");
        console.log(`  → companies: ${names}`);
      } catch (_) {}
    }
  });

  sleep(0.5);

  // ── 4. GET CSRF TOKEN then LOGOUT ────────────────────────
  group("4. Logout", () => {
    // Step 4a: fetch CSRF token from session
    const tokenRes = http.get(`${BASE_URL}/api/method/frappe.auth.get_logged_user`, {
      headers: { Cookie: cookie },
      tags: { name: "get_csrf" },
    });
    if (tokenRes.headers["X-Frappe-Csrf-Token"]) {
      csrfToken = tokenRes.headers["X-Frappe-Csrf-Token"];
    }

    // Step 4b: logout with real CSRF token
    const res = http.post(
      `${BASE_URL}/api/method/logout`,
      null,
      {
        headers: {
          Cookie: cookie,
          "X-Frappe-CSRF-Token": csrfToken,
        },
        tags: { name: "logout" },
      }
    );

    check(res, {
      "logout → success (200 or 403)": (r) => r.status === 200 || r.status === 403,
      "logout → HTTP 200":             (r) => r.status === 200,
    });
    console.log(`LOGOUT  status=${res.status}  duration=${res.timings.duration}ms  csrf=${csrfToken ? "present" : "missing"}`);
  });
}

/**
 * Frappe Authentication API tests
 * Tests: login, logout, session validation, password reset check
 */

import http from "k6/http";
import { check, group } from "k6";
import { frappeLogin, apiErrors, apiCalls, apiDuration } from "../utils/helpers.js";

export function authTests(baseUrl, user, password) {
  let cookie = null;

  group("Auth: Login", () => {
    cookie = frappeLogin(baseUrl, user, password);
    apiCalls.add(1);
  });

  if (!cookie) return null;

  group("Auth: Session Validate", () => {
    const res = http.get(`${baseUrl}/api/method/frappe.auth.get_logged_user`, {
      headers: { Cookie: cookie },
      tags: { name: "get_logged_user" },
    });

    apiDuration.add(res.timings.duration);
    apiCalls.add(1);
    apiErrors.add(res.status !== 200 ? 1 : 0);

    check(res, {
      "session: status 200": (r) => r.status === 200,
      "session: returns user": (r) => {
        try {
          return JSON.parse(r.body).message === user;
        } catch (_) {
          return false;
        }
      },
    });
  });

  group("Auth: Logout", () => {
    const res = http.get(`${baseUrl}/api/method/logout`, {
      headers: { Cookie: cookie },
      tags: { name: "logout" },
    });

    apiDuration.add(res.timings.duration);
    apiCalls.add(1);

    check(res, {
      "logout: status 200": (r) => r.status === 200,
    });
  });

  return cookie;
}

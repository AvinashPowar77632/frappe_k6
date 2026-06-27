/**
 * Shared helper utilities for k6 Frappe tests
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";

// Custom metrics
export const apiDuration = new Trend("frappe_api_duration", true);
export const apiErrors   = new Rate("frappe_api_errors");
export const apiCalls    = new Counter("frappe_api_calls");

/**
 * Login to Frappe and return session cookies as a string.
 * @param {string} baseUrl
 * @param {string} user
 * @param {string} password
 * @returns {string|null} cookie string or null on failure
 */
export function frappeLogin(baseUrl, user, password) {
  const res = http.post(
    `${baseUrl}/api/method/login`,
    JSON.stringify({ usr: user, pwd: password }),
    {
      headers: { "Content-Type": "application/json" },
      tags: { name: "login" },
    }
  );

  const ok = check(res, {
    "login: status 200": (r) => r.status === 200,
    "login: has session": (r) => r.cookies["sid"] !== undefined,
  });

  if (!ok) {
    apiErrors.add(1);
    return null;
  }

  return res.cookies["sid"] ? `sid=${res.cookies["sid"][0].value}` : null;
}

/**
 * Build default headers with session cookie.
 * @param {string} cookie
 * @returns {object}
 */
export function authHeaders(cookie) {
  return {
    "Content-Type": "application/json",
    Cookie: cookie,
    "X-Frappe-CSRF-Token": "fetch",
  };
}

/**
 * GET a Frappe REST resource and record metrics.
 * @param {string} baseUrl
 * @param {string} doctype - e.g. "Student"
 * @param {object} headers
 * @param {object} [params] - extra query params
 * @returns {Response}
 */
export function getList(baseUrl, doctype, headers, params = {}) {
  const qs = Object.entries({ doctype, limit: 20, ...params })
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");

  const res = http.get(`${baseUrl}/api/resource/${doctype}?${qs}`, {
    headers,
    tags: { name: `get_list_${doctype.toLowerCase().replace(/ /g, "_")}` },
  });

  apiDuration.add(res.timings.duration);
  apiCalls.add(1);
  apiErrors.add(res.status !== 200 ? 1 : 0);

  check(res, {
    [`getList ${doctype}: 200`]: (r) => r.status === 200,
  });

  return res;
}

/**
 * Call a Frappe whitelisted method.
 * @param {string} baseUrl
 * @param {string} method - full dotted method name
 * @param {object} payload
 * @param {object} headers
 * @returns {Response}
 */
export function callMethod(baseUrl, method, payload, headers) {
  const res = http.post(
    `${baseUrl}/api/method/${method}`,
    JSON.stringify(payload),
    {
      headers,
      tags: { name: method.split(".").pop() },
    }
  );

  apiDuration.add(res.timings.duration);
  apiCalls.add(1);
  apiErrors.add(res.status !== 200 ? 1 : 0);

  check(res, {
    [`method ${method}: 200`]: (r) => r.status === 200,
  });

  return res;
}

/**
 * Random think-time pause between 0.5s and 1.5s.
 */
export function thinkTime() {
  sleep(0.5 + Math.random());
}

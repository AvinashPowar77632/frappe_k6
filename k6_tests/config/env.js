/**
 * Dynamic environment config loader for k6 tests.
 * Priority: ENV vars > site.json > defaults
 * 
 * ENV vars override (useful for CI/CD):
 *   K6_BASE_URL       - e.g. http://erpv16.com
 *   K6_API_USER       - e.g. Administrator
 *   K6_API_PASSWORD   - e.g. admin
 *   K6_SITE_NAME      - e.g. erpv16.com
 */

import { open } from "k6/experimental/fs";

let siteConfig = {};

try {
  const f = open("./config/site.json");
  const raw = f.text();
  siteConfig = JSON.parse(raw);
} catch (_) {
  // site.json not found — rely on ENV vars
}

export const BASE_URL =
  __ENV.K6_BASE_URL || siteConfig.base_url || "http://localhost:8000";

export const SITE_NAME =
  __ENV.K6_SITE_NAME || siteConfig.site_name || "localhost";

export const API_USER =
  __ENV.K6_API_USER || siteConfig.api_user || "Administrator";

export const API_PASSWORD =
  __ENV.K6_API_PASSWORD || siteConfig.api_password || "admin";

export const THRESHOLDS = siteConfig.thresholds || {
  http_req_duration_p95_ms: 2000,
  http_req_duration_p99_ms: 5000,
  http_req_failed_rate: 0.01,
};

export default {
  BASE_URL,
  SITE_NAME,
  API_USER,
  API_PASSWORD,
  THRESHOLDS,
};

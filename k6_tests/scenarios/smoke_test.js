/**
 * SMOKE TEST — Baseline sanity check
 * 
 * Purpose : Verify the APIs work at minimal load (1-2 VUs).
 * Duration: ~1 minute
 * VUs     : 1-2
 * 
 * Run:
 *   k6 run scenarios/smoke_test.js
 *   k6 run scenarios/smoke_test.js -e K6_BASE_URL=http://erpv16.com -e K6_API_USER=Administrator -e K6_API_PASSWORD=admin
 */

import { sleep } from "k6";
import { BASE_URL, API_USER, API_PASSWORD, THRESHOLDS } from "../config/env.js";
import { frappeLogin, authHeaders } from "../utils/helpers.js";
import { commonApiTests } from "../tests/common_apis.js";
import { eduApiTests } from "../tests/edu_apis.js";
import { authTests } from "../tests/auth.js";

export const options = {
  vus: 2,
  duration: "1m",
  thresholds: {
    http_req_failed:                ["rate<0.01"],
    http_req_duration:              ["p(95)<2000"],
    frappe_api_errors:              ["rate<0.01"],
  },
};

export default function () {
  // Auth flow
  authTests(BASE_URL, API_USER, API_PASSWORD);
  sleep(1);

  // Re-login for subsequent tests
  const cookie = frappeLogin(BASE_URL, API_USER, API_PASSWORD);
  if (!cookie) return;

  const headers = authHeaders(cookie);

  commonApiTests(BASE_URL, headers);
  sleep(1);

  eduApiTests(BASE_URL, headers);
  sleep(1);
}

/**
 * SOAK TEST — Extended duration / endurance test
 * 
 * Purpose : Detect memory leaks, connection pool exhaustion, and
 *           slow degradation over long periods at steady load.
 * Duration: 2 hours (default) — adjust SOAK_DURATION env var
 * VUs     : 30 sustained
 * 
 * Run:
 *   k6 run scenarios/soak_test.js
 *   k6 run scenarios/soak_test.js -e K6_BASE_URL=http://erpv16.com -e K6_API_USER=Administrator -e K6_API_PASSWORD=admin
 *   # Short soak (30 min):
 *   k6 run scenarios/soak_test.js -e SOAK_DURATION=30m
 */

import { sleep } from "k6";
import { BASE_URL, API_USER, API_PASSWORD } from "../config/env.js";
import { frappeLogin, authHeaders } from "../utils/helpers.js";
import { commonApiTests } from "../tests/common_apis.js";
import { eduApiTests, eduMethodTests } from "../tests/edu_apis.js";

const SOAK_DURATION = __ENV.SOAK_DURATION || "2h";

export const options = {
  stages: [
    { duration: "5m",          target: 30 },   // ramp up
    { duration: SOAK_DURATION, target: 30 },   // hold for soak duration
    { duration: "5m",          target: 0  },   // ramp down
  ],
  thresholds: {
    http_req_failed:                ["rate<0.01"],
    http_req_duration:              ["p(95)<2000"],
    frappe_api_errors:              ["rate<0.01"],
    frappe_api_duration:            ["p(95)<2000"],
  },
};

export default function () {
  const cookie = frappeLogin(BASE_URL, API_USER, API_PASSWORD);
  if (!cookie) {
    sleep(5);
    return;
  }

  const headers = authHeaders(cookie);

  commonApiTests(BASE_URL, headers);
  sleep(1);

  eduApiTests(BASE_URL, headers);
  sleep(1);

  eduMethodTests(BASE_URL, headers);
  sleep(2);
}

/**
 * SPIKE TEST — Sudden extreme traffic burst
 * 
 * Purpose : Simulate sudden traffic spikes (e.g. exam results release,
 *           admission opening, fee due date) — goes 0 → 500 VUs instantly.
 * Duration: ~10 minutes
 * VUs     : 0 → 500 spike → back to 0 → spike again
 * 
 * Run:
 *   k6 run scenarios/spike_test.js
 *   k6 run scenarios/spike_test.js -e K6_BASE_URL=http://erpv16.com -e K6_API_USER=Administrator -e K6_API_PASSWORD=admin
 */

import { sleep } from "k6";
import { BASE_URL, API_USER, API_PASSWORD } from "../config/env.js";
import { frappeLogin, authHeaders } from "../utils/helpers.js";
import { eduApiTests } from "../tests/edu_apis.js";
import { commonApiTests } from "../tests/common_apis.js";

export const options = {
  stages: [
    { duration: "1m",   target: 10  },   // warm up — low traffic
    { duration: "30s",  target: 500 },   // 🔴 SPIKE: instant jump to 500 VUs
    { duration: "2m",   target: 500 },   // hold spike
    { duration: "30s",  target: 10  },   // 🟢 recovery: drop back to normal
    { duration: "2m",   target: 10  },   // hold normal
    { duration: "30s",  target: 500 },   // 🔴 second SPIKE
    { duration: "1m",   target: 500 },   // hold second spike
    { duration: "1m",   target: 0   },   // ramp down
  ],
  thresholds: {
    http_req_failed:                ["rate<0.15"],   // spikes may cause 15% errors — still detect
    http_req_duration:              ["p(99)<10000"], // allow up to 10s under spike
    frappe_api_errors:              ["rate<0.15"],
  },
};

export default function () {
  const cookie = frappeLogin(BASE_URL, API_USER, API_PASSWORD);
  if (!cookie) {
    sleep(2);
    return;
  }

  const headers = authHeaders(cookie);

  // Focus on the most critical EDU APIs during a spike
  eduApiTests(BASE_URL, headers);
  sleep(0.2);

  commonApiTests(BASE_URL, headers);
  sleep(0.2);
}

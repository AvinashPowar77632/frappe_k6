/**
 * LOAD TEST — Normal expected traffic
 * 
 * Purpose : Simulate normal concurrent users, sustained over time.
 * Duration: ~10 minutes
 * VUs     : Ramp up to 50 → hold → ramp down
 * 
 * Run:
 *   k6 run scenarios/load_test.js
 *   k6 run scenarios/load_test.js -e K6_BASE_URL=http://erpv16.com -e K6_API_USER=Administrator -e K6_API_PASSWORD=admin
 */

import { sleep } from "k6";
import { BASE_URL, API_USER, API_PASSWORD } from "../config/env.js";
import { frappeLogin, authHeaders } from "../utils/helpers.js";
import { commonApiTests } from "../tests/common_apis.js";
import { eduApiTests, eduMethodTests } from "../tests/edu_apis.js";

export const options = {
  stages: [
    { duration: "2m", target: 10 },   // ramp up to 10 VUs
    { duration: "2m", target: 25 },   // ramp up to 25 VUs
    { duration: "4m", target: 50 },   // ramp up to 50 VUs (peak load)
    { duration: "2m", target: 25 },   // scale back to 25 VUs
    { duration: "1m", target: 0 },    // ramp down
  ],
  thresholds: {
    http_req_failed:                ["rate<0.01"],
    http_req_duration:              ["p(90)<1500", "p(95)<2000", "p(99)<5000"],
    frappe_api_errors:              ["rate<0.01"],
    frappe_api_duration:            ["p(95)<2000"],
  },
};

export default function () {
  const cookie = frappeLogin(BASE_URL, API_USER, API_PASSWORD);
  if (!cookie) {
    sleep(2);
    return;
  }

  const headers = authHeaders(cookie);

  commonApiTests(BASE_URL, headers);
  sleep(1);

  eduApiTests(BASE_URL, headers);
  sleep(1);

  eduMethodTests(BASE_URL, headers);
  sleep(1);
}

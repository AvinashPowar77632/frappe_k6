/**
 * STRESS TEST — Above normal / breaking point
 * 
 * Purpose : Find the API's breaking point by pushing beyond normal capacity.
 * Duration: ~18 minutes
 * VUs     : Ramp up to 200+ VUs, find where errors start
 * 
 * Run:
 *   k6 run scenarios/stress_test.js
 *   k6 run scenarios/stress_test.js -e K6_BASE_URL=http://erpv16.com -e K6_API_USER=Administrator -e K6_API_PASSWORD=admin
 */

import { sleep } from "k6";
import { BASE_URL, API_USER, API_PASSWORD } from "../config/env.js";
import { frappeLogin, authHeaders } from "../utils/helpers.js";
import { commonApiTests } from "../tests/common_apis.js";
import { eduApiTests } from "../tests/edu_apis.js";

export const options = {
  stages: [
    { duration: "2m",  target: 50  },  // normal load
    { duration: "3m",  target: 100 },  // above normal
    { duration: "3m",  target: 150 },  // high stress
    { duration: "3m",  target: 200 },  // very high stress
    { duration: "3m",  target: 250 },  // breaking point search
    { duration: "2m",  target: 0   },  // recovery
  ],
  thresholds: {
    http_req_failed:                ["rate<0.10"],   // allow up to 10% errors under stress
    http_req_duration:              ["p(95)<5000"],  // 5s P95 under stress
    frappe_api_errors:              ["rate<0.10"],
  },
};

export default function () {
  const cookie = frappeLogin(BASE_URL, API_USER, API_PASSWORD);
  if (!cookie) {
    sleep(3);
    return;
  }

  const headers = authHeaders(cookie);

  commonApiTests(BASE_URL, headers);
  sleep(0.5);

  eduApiTests(BASE_URL, headers);
  sleep(0.5);
}

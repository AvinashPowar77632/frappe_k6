// frappe_k6 runner — one fixed script for every Load Test Config.
// All test-specific input (stages, thresholds, endpoints, credentials) comes from the
// JSON data file named by K6_DATA, so no user input is ever turned into code.
import http from "k6/http";
import { check, sleep, group } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";

const data = JSON.parse(open(__ENV.K6_DATA));
const BASE_URL = __ENV.K6_BASE_URL;
const TARGET = __ENV.TARGET_SERVER || "local";

const apiDuration = new Trend("frappe_api_duration", true);
const apiErrors = new Rate("frappe_api_errors");
const apiCalls = new Counter("frappe_api_calls");

export const options = {
  stages: data.stages,
  thresholds: data.thresholds,
};

function withQuery(url, query) {
  const keys = Object.keys(query || {});
  if (!keys.length) return url;
  const qs = keys
    .map((k) => encodeURIComponent(k) + "=" + encodeURIComponent(String(query[k])))
    .join("&");
  return url + (url.indexOf("?") === -1 ? "?" : "&") + qs;
}

// Log in once for all VUs instead of on every iteration.
export function setup() {
  if (!data.login) return { sid: "" };
  const res = http.post(
    BASE_URL + "/api/method/login",
    JSON.stringify({ usr: data.login.usr, pwd: data.login.pwd }),
    { headers: { "Content-Type": "application/json" }, tags: { name: "login" } }
  );
  check(res, { "login: 200": (r) => r.status === 200 });
  const sid = res.cookies.sid;
  return { sid: sid && sid.length ? sid[0].value : "" };
}

export default function (ctx) {
  for (const ep of data.endpoints) {
    group(ep.name, () => {
      const headers = Object.assign({}, ep.headers);
      if (ep.session && ctx.sid) headers.Cookie = "sid=" + ctx.sid;
      const body = ep.body === null || ep.body === undefined ? null : JSON.stringify(ep.body);
      const res = http.request(ep.method, BASE_URL + withQuery(ep.url, ep.query), body, {
        headers: headers,
        tags: { name: ep.name, target_server: TARGET },
      });
      apiDuration.add(res.timings.duration);
      apiCalls.add(1);
      apiErrors.add(res.status >= 400 ? 1 : 0);
      check(res, { [ep.name + ": " + ep.expected_status]: (r) => r.status === ep.expected_status });
    });
  }
  sleep(data.think_time);
}

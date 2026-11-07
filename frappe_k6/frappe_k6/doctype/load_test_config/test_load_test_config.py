# Copyright (c) 2026, Avinash and Contributors
# See license.txt

import json
import os
import tempfile
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_k6.api import load_test
from frappe_k6.api.k6_generator import build_run_data, duration_seconds, write_run_data

CONFIG_NAME = "_Test K6 Config"


def _config(endpoints=None, insert=False):
	doc = frappe.get_doc({
		"doctype": "Load Test Config",
		"test_name": CONFIG_NAME,
		"scenario_type": "load",
		"virtual_users": 5,
		"duration": "1m",
		"ramp_up_time": "30s",
		"ramp_down_time": "10s",
		"endpoints": endpoints or [
			{"api_name": "Ping", "http_method": "GET", "endpoint_url": "/api/method/ping",
			 "expected_status": 200, "auth_type": "Bearer Token", "auth_value": "s3cret-token"},
		],
	})
	if insert:
		doc.insert(ignore_permissions=True)
	return doc


def _summary(failed_threshold=False):
	return {"metrics": {
		"http_reqs": {"count": 12000, "rate": 200.5},
		"http_req_duration": {"avg": 120.0, "min": 5.0, "med": 100.0, "max": 900.0,
							  "p(90)": 250.0, "p(95)": 310.0, "p(99)": 700.0,
							  "thresholds": {"p(95)<5000": False}},
		"http_req_failed": {"passes": 60, "fails": 11940, "value": 0.005,
							"thresholds": {"rate<0.10": failed_threshold}},
		"checks": {"passes": 11900, "fails": 100},
		"iterations": {"count": 4000},
		"vus_max": {"value": 5, "min": 5, "max": 5},
		"data_received": {"count": 2048, "rate": 1.0},
		"data_sent": {"count": 1024, "rate": 1.0},
	}}


class TestRunData(FrappeTestCase):
	def test_endpoints_become_data_not_code(self):
		payload = '{"note": "\\"); http.get(\\"http://evil\\"); ("}'
		cfg = _config([
			{"api_name": 'Create "x"', "http_method": "POST", "endpoint_url": "/api/resource/ToDo",
			 "payload": payload, "query_params": '{"a b": "c&d"}', "auth_type": "None"},
		])
		data = build_run_data(cfg)
		ep = data["endpoints"][0]
		self.assertEqual(ep["name"], 'Create "x"')
		self.assertEqual(ep["body"], json.loads(payload))
		self.assertEqual(ep["query"], {"a b": "c&d"})  # encoded by the runner, not concatenated
		self.assertEqual(data["stages"][1], {"duration": "1m", "target": 5})

	def test_endpoint_must_be_a_path(self):
		cfg = _config([{"api_name": "x", "http_method": "GET", "endpoint_url": "@evil.example/x"}])
		self.assertRaises(frappe.ValidationError, build_run_data, cfg)

	def test_session_login_needs_credentials(self):
		cfg = _config([{"api_name": "x", "http_method": "GET", "endpoint_url": "/api/method/ping",
						"auth_type": "Session (Frappe Login)", "auth_value": ""}])
		self.assertRaises(frappe.ValidationError, build_run_data, cfg)

		cfg.endpoints[0].auth_value = "tester@example.com:pw:with:colons"
		data = build_run_data(cfg)
		self.assertEqual(data["login"], {"usr": "tester@example.com", "pwd": "pw:with:colons"})
		self.assertTrue(data["endpoints"][0]["session"])

	def test_data_file_is_private(self):
		with tempfile.TemporaryDirectory() as d:
			path = write_run_data({"x": 1}, os.path.join(d, "run.data.json"))
			self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

	def test_duration_parsing(self):
		self.assertEqual(duration_seconds("1m30s"), 90)
		self.assertEqual(duration_seconds("2h"), 7200)
		self.assertEqual(duration_seconds("500ms"), 0.5)


class TestResults(FrappeTestCase):
	def test_summary_covers_whole_run(self):
		m = load_test._summary_metrics(_summary(), load_test._parse_k6_output(""))
		self.assertEqual(m["http_reqs"]["count"], 12000)
		self.assertEqual(m["http_req_failed"]["count"], 60)
		self.assertEqual(m["http_req_failed"]["rate"], 0.5)
		self.assertEqual(m["http_req_duration"]["p99"], 700.0)
		self.assertEqual(m["http_req_duration"]["p50"], 100.0)
		self.assertEqual(m["rps"], 200.5)
		self.assertEqual(m["vus"]["max"], 5)

	def test_threshold_result(self):
		self.assertEqual(load_test._threshold_result(_summary(), 0), "Passed")
		self.assertEqual(load_test._threshold_result(_summary(failed_threshold=True), 0), "Failed")
		self.assertEqual(load_test._threshold_result(None, 99), "Failed")
		self.assertEqual(load_test._threshold_result(None, None), "Unknown")

	def test_tail_reads_only_the_end(self):
		with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
			for i in range(1000):
				f.write(json.dumps({"type": "Point", "metric": "http_reqs", "data": {"value": 1, "i": i}}) + "\n")
			path = f.name
		try:
			lines = load_test._tail_lines(path, max_bytes=2000)
			self.assertTrue(0 < len(lines) < 1000)
			self.assertEqual(json.loads(lines[-1])["data"]["i"], 999)
			json.loads(lines[0])  # the cut first line was dropped
		finally:
			os.remove(path)


class TestFinalize(FrappeTestCase):
	def setUp(self):
		# alerts and Grafana Cloud have their own tests; don't send or store them here
		after = patch("frappe_k6.api.load_test._after_finish")
		after.start()
		self.addCleanup(after.stop)
		self.tmp = tempfile.mkdtemp()
		if frappe.db.exists("Load Test Config", CONFIG_NAME):
			frappe.delete_doc("Load Test Config", CONFIG_NAME, force=True)
		self.cfg = _config(insert=True)

	def tearDown(self):
		frappe.delete_doc("Load Test Config", CONFIG_NAME, force=True)
		frappe.db.commit()

	def _run(self, summary):
		summary_file = os.path.join(self.tmp, "s.json")
		data_file = os.path.join(self.tmp, "d.json")
		if summary is not None:
			with open(summary_file, "w") as f:
				json.dump(summary, f)
		write_run_data({"login": {"usr": "u", "pwd": "p"}}, data_file)
		run = frappe.get_doc({
			"doctype": "Load Test Run", "config": CONFIG_NAME, "status": "Running",
			"summary_file": summary_file, "data_file": data_file,
			"output_file": os.path.join(self.tmp, "missing.json"),
		}).insert(ignore_permissions=True)
		return run, data_file

	def test_completed_run_uses_summary_and_removes_secrets(self):
		run, data_file = self._run(_summary())
		load_test._finalize_run(run.name, exit_code=0)
		run.reload()
		self.assertEqual(run.status, "Completed")
		self.assertEqual(run.threshold_result, "Passed")
		self.assertEqual(run.total_requests, 12000)
		self.assertEqual(run.p99_duration_ms, 700.0)
		self.assertFalse(os.path.exists(data_file))

	def test_failed_threshold_marks_run_failed(self):
		run, _data = self._run(_summary(failed_threshold=True))
		load_test._finalize_run(run.name, exit_code=99)
		run.reload()
		self.assertEqual(run.status, "Failed")
		self.assertEqual(run.exit_code, 99)
		self.assertEqual(run.threshold_result, "Failed")

	def test_missing_summary_is_a_failure(self):
		run, _data = self._run(None)
		load_test._finalize_run(run.name)
		self.assertEqual(frappe.db.get_value("Load Test Run", run.name, "status"), "Failed")

	def test_finalize_is_idempotent(self):
		run, _data = self._run(_summary())
		load_test._finalize_run(run.name, exit_code=0)
		load_test._finalize_run(run.name, exit_code=1)
		self.assertEqual(frappe.db.get_value("Load Test Run", run.name, "status"), "Completed")


class TestCredentialStorage(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_endpoint_secret_is_encrypted(self):
		cfg = _config(insert=True)
		row = cfg.endpoints[0]
		stored = frappe.db.get_value("Load Test Endpoint", row.name, "auth_value")
		self.assertNotIn("s3cret", stored)
		self.assertEqual(set(stored), {"*"})
		self.assertEqual(row.get_password("auth_value"), "s3cret-token")
		self.assertEqual(
			build_run_data(frappe.get_doc("Load Test Config", cfg.name))["endpoints"][0]["headers"]["Authorization"],
			"Bearer s3cret-token",
		)

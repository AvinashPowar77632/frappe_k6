# Copyright (c) 2026, Avinash and Contributors
# See license.txt

import json
import os
import struct
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_k6 import alerts, grafana_cloud

CONFIG_NAME = "_Test K6 Alert Config"


# ─── minimal decoders, used only to check the encoders ───────────────────────

def _read_varint(buf, i):
	shift = result = 0
	while True:
		b = buf[i]
		i += 1
		result |= (b & 0x7F) << shift
		if not b & 0x80:
			return result, i
		shift += 7


def _snappy_decode(buf):
	length, i = _read_varint(buf, 0)
	out = bytearray()
	while i < len(buf):
		tag = buf[i]
		i += 1
		self_len = tag >> 2
		assert tag & 3 == 0, "only literals are expected"
		if self_len < 60:
			n = self_len + 1
		else:
			nbytes = self_len - 59
			n = int.from_bytes(buf[i:i + nbytes], "little") + 1
			i += nbytes
		out += buf[i:i + n]
		i += n
	assert len(out) == length
	return bytes(out)


def _fields(buf):
	i, out = 0, []
	while i < len(buf):
		key, i = _read_varint(buf, i)
		num, wire = key >> 3, key & 7
		if wire == 2:
			n, i = _read_varint(buf, i)
			out.append((num, buf[i:i + n]))
			i += n
		elif wire == 1:
			out.append((num, struct.unpack("<d", buf[i:i + 8])[0]))
			i += 8
		elif wire == 0:
			v, i = _read_varint(buf, i)
			out.append((num, v))
	return out


class TestRemoteWriteEncoding(FrappeTestCase):
	def test_round_trip(self):
		series = [({"__name__": "frappe_cpu_percent", "site": "a.test", "job": "frappe_k6"}, 12.5, 1793359309000)]
		decoded = _fields(_snappy_decode(grafana_cloud.snappy_block(grafana_cloud.encode_write_request(series))))
		self.assertEqual(len(decoded), 1)
		ts = _fields(decoded[0][1])
		labels = [dict((k, v.decode()) for k, v in _fields(lab)) for num, lab in ts if num == 1]
		self.assertEqual([lab[1] for lab in labels], ["__name__", "job", "site"])  # sorted by name
		sample = dict(_fields(next(v for num, v in ts if num == 2)))
		self.assertEqual(sample, {1: 12.5, 2: 1793359309000})

	def test_snappy_large_payload(self):
		data = os.urandom(70000)
		self.assertEqual(_snappy_decode(grafana_cloud.snappy_block(data)), data)

	def test_push_urls(self):
		self.assertEqual(grafana_cloud.prom_push_url("https://p.grafana.net/api/prom"),
						 "https://p.grafana.net/api/prom/push")
		self.assertEqual(grafana_cloud.prom_push_url("http://localhost:9090/"), "http://localhost:9090/api/v1/write")
		self.assertEqual(grafana_cloud.loki_push_url("https://l.grafana.net"),
						 "https://l.grafana.net/loki/api/v1/push")


class TestGrafanaPayloads(FrappeTestCase):
	def test_dashboard_datasources_rewritten(self):
		dash = {"panels": [{"datasource": {"type": "prometheus", "uid": "prometheus"},
							"targets": [{"datasource": {"type": "loki", "uid": "loki"}}]},
						   {"datasource": "Prometheus"}],
				"templating": {"list": [{"datasource": {"uid": "prometheus"}}]}}
		out = grafana_cloud.prepare_dashboard(dash, "cloud-prom", "cloud-logs")
		text = json.dumps(out)
		self.assertNotIn('"uid": "prometheus"', text)
		self.assertEqual(out["panels"][0]["targets"][0]["datasource"]["uid"], "cloud-logs")
		self.assertEqual(out["panels"][1]["datasource"], {"type": "prometheus", "uid": "cloud-prom"})
		again = grafana_cloud.prepare_dashboard(out, "cloud-prom", "cloud-logs")
		self.assertEqual(len(again["annotations"]["list"]), 1)  # annotation added once

	def test_alert_rule_payload(self):
		rule = frappe._dict(title="A very long alert rule title that keeps going", expr="max(frappe_cpu_percent{$site})",
							operator=">", threshold=85, for_duration="5m", severity="warning")
		cfg = frappe._dict(folder_uid="frappe-k6", prom_ds="cloud-prom")
		body = grafana_cloud.build_alert_rule(rule, cfg, "Frappe K6 (x)")
		self.assertLessEqual(len(body["uid"]), 40)
		self.assertEqual(body["data"][0]["model"]["expr"], f'max(frappe_cpu_percent{{site="{frappe.local.site}"}})')
		self.assertEqual(body["data"][2]["model"]["conditions"][0]["evaluator"], {"type": "gt", "params": [85.0]})
		self.assertEqual(body["notification_settings"], {"receiver": "Frappe K6 (x)"})
		self.assertNotIn("notification_settings", grafana_cloud.build_alert_rule(rule, cfg, None))

	def test_alloy_config_has_no_secret(self):
		cfg = frappe._dict(prom_url="https://p.grafana.net/api/prom", prom_user="111", loki_url="https://l.grafana.net",
						   loki_user="222", access_token="SECRET")
		text = grafana_cloud.render_alloy_config("web-1", "production", "/bench", cfg)
		self.assertNotIn("SECRET", text)
		self.assertIn('sys.env("GRAFANA_CLOUD_TOKEN")', text)
		self.assertIn('replacement  = "node"', text)
		self.assertIn("https://p.grafana.net/api/prom/push", text)


class TestRunAlerts(FrappeTestCase):
	def setUp(self):
		for name in frappe.get_all("Load Test Config", filters={"name": CONFIG_NAME}, pluck="name"):
			frappe.delete_doc("Load Test Config", name, force=True)
		frappe.get_doc({
			"doctype": "Load Test Config", "test_name": CONFIG_NAME, "scenario_type": "load",
			"endpoints": [{"api_name": "Ping", "http_method": "GET", "endpoint_url": "/api/method/ping",
						   "auth_type": "None"}],
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def _run(self, minutes_ago, **values):
		return frappe.get_doc({
			"doctype": "Load Test Run", "config": CONFIG_NAME, "status": "Completed",
			"threshold_result": "Passed", "total_requests": 1000,
			"completed_at": frappe.utils.add_to_date(None, minutes=-minutes_ago), **values,
		}).insert(ignore_permissions=True)

	def test_thresholds_vs_run_failed(self):
		run = self._run(0, status="Failed", threshold_result="Failed")
		row = frappe.db.get_value("Load Test Run", run.name, alerts.RUN_FIELDS, as_dict=True)
		thr = frappe._dict(metric="Thresholds failed", operator=">", value=0)
		crash = frappe._dict(metric="Run failed", operator=">", value=0)
		self.assertTrue(alerts.check_rule(thr, row)[0])
		self.assertFalse(alerts.check_rule(crash, row)[0])  # no duplicate alert for the same failure

	def test_baseline_regression(self):
		for i, p95 in enumerate((100, 110, 90)):
			self._run(30 - i, p95_duration_ms=p95)
		run = self._run(0, p95_duration_ms=140)
		row = frappe.db.get_value("Load Test Run", run.name, alerts.RUN_FIELDS, as_dict=True)
		rule = frappe._dict(metric="P95 latency (ms)", compare_to_baseline=1, value=25, baseline_runs=5)
		fired, actual, limit = alerts.check_rule(rule, row)
		self.assertTrue(fired)
		self.assertEqual((actual, limit), (140, 125))
		rule.value = 50
		self.assertFalse(alerts.check_rule(rule, row)[0])

	def test_rps_baseline_lower_is_worse(self):
		for i in range(3):
			self._run(30 - i, requests_per_sec=100)
		run = self._run(0, requests_per_sec=70)
		row = frappe.db.get_value("Load Test Run", run.name, alerts.RUN_FIELDS, as_dict=True)
		rule = frappe._dict(metric="Requests per second", compare_to_baseline=1, value=20, baseline_runs=5)
		self.assertTrue(alerts.check_rule(rule, row)[0])

	def test_evaluate_creates_alert_and_notifies(self):
		alerts.ensure_default_rules()
		run = self._run(0, status="Failed", threshold_result="Failed")
		with patch("frappe_k6.grafana_cloud.notification_channels", return_value={}), \
				patch("frappe_k6.grafana_cloud.log_event"), \
				patch.object(frappe.db, "commit"):
			names = alerts.evaluate_run(run.name)
		self.assertEqual(len(names), 1)
		alert = frappe.get_doc("K6 Alert", names[0])
		self.assertEqual(alert.alert_rule, "Thresholds failed")
		self.assertIn("in-app", alert.delivery)
		self.assertTrue(frappe.db.exists("Notification Log", {"document_name": run.name, "for_user": "Administrator"}))

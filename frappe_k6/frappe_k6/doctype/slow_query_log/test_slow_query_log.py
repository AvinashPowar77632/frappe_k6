# Copyright (c) 2026, Avinash and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_k6 import slow_query


class TestSlowQueryLog(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_value(slow_query.REDIS_KEY)
		frappe.db.delete("Slow Query Log")

	def tearDown(self):
		frappe.local.k6_slow_query_threshold = None
		frappe.cache().delete_value(slow_query.REDIS_KEY)

	def _enable(self, threshold):
		settings = frappe.get_single("Monitor Settings")
		settings.enable_slow_query_log = 1
		settings.slow_query_threshold = threshold
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		slow_query.on_job_start(method="tests.slow_query")

	def test_slow_query_is_captured_and_flushed(self):
		self._enable(0.2)
		frappe.db.sql("select sleep(0.3)")
		frappe.db.sql("select 1")  # fast, must not be logged

		self.assertEqual(slow_query.flush_slow_queries(), 1)
		log = frappe.get_last_doc("Slow Query Log")
		self.assertIn("sleep", log.query_text)
		self.assertEqual(log.query_type, "SELECT")
		self.assertEqual(log.source, "tests.slow_query")
		self.assertGreaterEqual(log.execution_time, 0.2)

	def test_disabled_logs_nothing(self):
		frappe.db.set_single_value("Monitor Settings", "enable_slow_query_log", 0)
		slow_query.on_job_start(method="tests.slow_query")
		frappe.db.sql("select sleep(0.3)")
		self.assertEqual(slow_query.flush_slow_queries(), 0)

	def test_clear_old_logs(self):
		self._enable(0.2)
		frappe.db.sql("select sleep(0.3)")
		slow_query.flush_slow_queries()
		frappe.db.sql("update `tabSlow Query Log` set creation = now() - interval 2 day")
		from frappe_k6.frappe_k6.doctype.slow_query_log.slow_query_log import SlowQueryLog

		SlowQueryLog.clear_old_logs(days=1)
		self.assertEqual(frappe.db.count("Slow Query Log"), 0)

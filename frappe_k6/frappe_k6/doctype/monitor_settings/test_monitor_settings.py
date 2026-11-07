# Copyright (c) 2026, Avinash and Contributors
# See license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_k6.security import (
	check_metrics_access,
	decrypt_auth_config,
	encrypt_auth_config,
	strip_auth_config,
	validate_target_url,
)


class TestTargetValidation(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_internal_addresses_are_refused(self):
		for url in ("http://10.0.0.5:9090/api/v1/query", "http://169.254.169.254/latest/meta-data/",
					"http://127.0.0.1:3000/api/org"):
			self.assertRaises(frappe.PermissionError, validate_target_url, url)

	def test_non_http_is_refused(self):
		self.assertRaises(frappe.ValidationError, validate_target_url, "file:///etc/passwd")

	def test_own_site_is_allowed(self):
		validate_target_url(frappe.utils.get_url() + "/api/method/ping")

	def test_allow_list(self):
		frappe.db.set_single_value("Monitor Settings", "allowed_target_hosts", "10.0.0.5:8000")
		validate_target_url("http://10.0.0.5:8000/api/method/ping")
		self.assertRaises(frappe.PermissionError, validate_target_url, "http://10.0.0.5:9090/")


class TestMetricsAccess(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_guest_without_token_is_refused(self):
		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, check_metrics_access)

	def test_k6_session_is_allowed(self):
		check_metrics_access()


class TestSecrets(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_auth_config_round_trip(self):
		cfg = {"username": "u", "password": "p@ss", "token": "t"}
		enc = encrypt_auth_config(cfg)
		self.assertEqual(enc["username"], "u")
		self.assertNotEqual(enc["password"], "p@ss")
		self.assertEqual(encrypt_auth_config(enc), enc)  # no double encryption
		self.assertEqual(decrypt_auth_config(enc), cfg)
		self.assertEqual(strip_auth_config(enc), {"username": "u", "password": "", "token": ""})

	def test_api_request_stores_encrypted_auth(self):
		doc = frappe.get_doc({
			"doctype": "API Request", "request_name": "_Test K6 Request", "method": "GET",
			"url": "/api/method/ping", "auth_type": "Basic Auth",
			"auth_config_json": json.dumps({"username": "u", "password": "p@ss"}),
		}).insert(ignore_permissions=True)
		stored = json.loads(frappe.db.get_value("API Request", doc.name, "auth_config_json"))
		self.assertNotIn("p@ss", json.dumps(stored))
		self.assertEqual(decrypt_auth_config(stored)["password"], "p@ss")

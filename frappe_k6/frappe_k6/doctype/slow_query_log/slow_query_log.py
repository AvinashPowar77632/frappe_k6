# Copyright (c) 2026, Avinash and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now

from frappe_k6.security import K6_MANAGER


class SlowQueryLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		execution_time: DF.Float
		query_text: DF.Code | None
		query_type: DF.Data | None
		seen: DF.Check
		source: DF.Data | None
		timestamp: DF.Datetime | None
		user: DF.Link | None
	# end: auto-generated types

	def onload(self):
		if not self.seen and not frappe.flags.read_only:
			self.db_set("seen", 1, update_modified=False)
			frappe.db.commit()

	@staticmethod
	def clear_old_logs(days=7):
		"""Delete logs older than `days`. Called daily by Log Settings
		(retention is configured there, default from hooks.default_log_clearing_doctypes)."""
		table = frappe.qb.DocType("Slow Query Log")
		frappe.db.delete(table, filters=(table.creation < (Now() - Interval(days=days))))


@frappe.whitelist(methods=["POST"])
def clear_slow_query_logs():
	"""Delete every Slow Query Log entry and drop anything still buffered in Redis."""
	frappe.only_for(["System Manager", K6_MANAGER])

	from frappe_k6.slow_query import REDIS_KEY

	frappe.db.truncate("Slow Query Log")
	frappe.cache().delete_value(REDIS_KEY)

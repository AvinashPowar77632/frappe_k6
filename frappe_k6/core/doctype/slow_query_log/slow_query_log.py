# Copyright (c) 2015, Frappe Technologies and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class SlowQueryLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		execution_time: DF.Float
		query_text: DF.LongText
		seen: DF.Check
		timestamp: DF.Datetime

	# end: auto-generated types

	def onload(self):
		if not self.seen and not frappe.flags.read_only:
			self.db_set("seen", 1, update_modified=0)
			frappe.db.commit()

	@staticmethod
	def clear_old_logs(days=1/24):
		"""Clear slow query logs older than specified days.
		Default: 1 hour (1/24 days)
		"""
		table = frappe.qb.DocType("Slow Query Log")
		frappe.db.delete(table, filters=(table.modified < (Now() - Interval(days=days))))


@frappe.whitelist()
def clear_slow_query_logs():
	"""Flush all Slow Query Logs"""
	frappe.only_for("System Manager")
	frappe.db.truncate("Slow Query Log")

"""
Slow Query Log capture for frappe_k6.

Frappe core is never modified. Instead:

1. `install_hook` (before_request / before_job) wraps `Database.sql` once per
   process and, per request/job, reads the threshold from Monitor Settings
   into `frappe.local`. When logging is disabled the wrapper is a plain
   pass-through.
2. A query that takes longer than the threshold is pushed to a capped Redis
   list. Nothing is written to the database inside the request, so the
   request's transaction is never touched.
3. `flush_slow_queries` (scheduler, every minute) moves buffered entries into
   the `Slow Query Log` doctype.

Only the parametrised query text is stored (values are not), so passwords or
other secrets passed as query parameters never end up in the log.
"""

import json
from functools import wraps
from time import perf_counter

import frappe
from frappe.utils import cstr, flt, now_datetime

DOCTYPE = "Slow Query Log"
REDIS_KEY = "frappe_k6:slow_query_buffer"
MAX_BUFFER = 5000          # cap on queued entries between flushes
MAX_QUERY_LENGTH = 10000   # characters of query text kept per entry
FLUSH_BATCH = 1000         # entries written per flush run

_LOCAL_THRESHOLD = "k6_slow_query_threshold"
_LOCAL_SOURCE = "k6_slow_query_source"
_LOCAL_BUSY = "k6_slow_query_busy"


# ─────────────────────────────────────────────────────────────────────────────
#  Hooks
# ─────────────────────────────────────────────────────────────────────────────

def on_request_start():
	"""before_request hook."""
	source = ""
	try:
		source = cstr(frappe.request.path) if getattr(frappe, "request", None) else ""
	except Exception:
		pass
	_activate(source)


def on_job_start(method=None, **kwargs):
	"""before_job hook."""
	_activate(cstr(method))


def _activate(source):
	setattr(frappe.local, _LOCAL_THRESHOLD, None)
	try:
		threshold = get_threshold()
	except Exception:
		# Settings table missing (e.g. mid-install) - never break the request.
		return
	if threshold is None:
		return
	_patch_database_class()
	setattr(frappe.local, _LOCAL_THRESHOLD, threshold)
	setattr(frappe.local, _LOCAL_SOURCE, source[:140])


def get_threshold():
	"""Return the threshold in seconds, or None when logging is disabled."""
	if not frappe.db.get_single_value("Monitor Settings", "enable_slow_query_log", cache=True):
		return None
	threshold = flt(frappe.db.get_single_value("Monitor Settings", "slow_query_threshold", cache=True))
	return threshold if threshold > 0 else 1.0


# ─────────────────────────────────────────────────────────────────────────────
#  Database.sql wrapper
# ─────────────────────────────────────────────────────────────────────────────

def _patch_database_class():
	from frappe.database.database import Database

	if getattr(Database.sql, "_k6_slow_query_wrapped", False):
		return

	original_sql = Database.sql

	@wraps(original_sql)
	def sql(self, query, *args, **kwargs):
		threshold = getattr(frappe.local, _LOCAL_THRESHOLD, None)
		if threshold is None or getattr(frappe.local, _LOCAL_BUSY, False):
			return original_sql(self, query, *args, **kwargs)

		start = perf_counter()
		try:
			return original_sql(self, query, *args, **kwargs)
		finally:
			elapsed = perf_counter() - start
			if elapsed >= threshold:
				_record(query, elapsed)

	sql._k6_slow_query_wrapped = True
	Database.sql = sql


def _record(query, elapsed):
	"""Queue one slow query in Redis. Must never raise into the caller."""
	setattr(frappe.local, _LOCAL_BUSY, True)
	try:
		text = cstr(query).strip()
		if not text or "tabSlow Query Log" in text:
			return
		entry = {
			"timestamp": str(now_datetime()),
			"execution_time": round(elapsed, 4),
			"query_text": text[:MAX_QUERY_LENGTH],
			"query_type": text.split(None, 1)[0].upper()[:20],
			"source": getattr(frappe.local, _LOCAL_SOURCE, "") or "",
			"user": getattr(getattr(frappe.local, "session", None), "user", None),
		}
		cache = frappe.cache()
		cache.rpush(REDIS_KEY, json.dumps(entry, default=str))
		cache.ltrim(REDIS_KEY, -MAX_BUFFER, -1)
	except Exception:
		pass
	finally:
		setattr(frappe.local, _LOCAL_BUSY, False)


# ─────────────────────────────────────────────────────────────────────────────
#  Scheduler: Redis buffer -> Slow Query Log
# ─────────────────────────────────────────────────────────────────────────────

def flush_slow_queries():
	"""Move buffered slow queries from Redis into the Slow Query Log doctype."""
	if not frappe.db.table_exists(DOCTYPE):
		return 0

	cache = frappe.cache()
	written = 0
	for _ in range(FLUSH_BATCH):
		raw = cache.lpop(REDIS_KEY)
		if not raw:
			break
		try:
			entry = json.loads(raw)
			doc = frappe.new_doc(DOCTYPE)
			doc.update({
				"timestamp": entry.get("timestamp"),
				"execution_time": flt(entry.get("execution_time")),
				"query_text": entry.get("query_text"),
				"query_type": entry.get("query_type"),
				"source": entry.get("source"),
				"user": entry.get("user") if entry.get("user") and frappe.db.exists("User", entry.get("user")) else None,
			})
			doc.insert(ignore_permissions=True)
			written += 1
		except Exception:
			frappe.log_error(title="Slow Query Log flush failed", message=cstr(raw)[:2000])
	if written:
		frappe.db.commit()
	return written

"""
Access control, target validation and secret handling for frappe_k6.
"""

import hmac
import ipaddress
import socket
import urllib.parse
import urllib.request

import frappe
from frappe import _

K6_MANAGER = "K6 Manager"
K6_USER = "K6 User"

MANAGER_ROLES = ("System Manager", K6_MANAGER)
USER_ROLES = ("System Manager", K6_MANAGER, K6_USER)

# Keys inside an auth config dict that hold secrets
SECRET_KEYS = ("password", "token", "value", "client_secret")
METRICS_TOKEN_HEADER = "X-Frappe-K6-Token"
_ENC_PREFIX = "enc:v1:"


# ─── Roles ────────────────────────────────────────────────────────────────────

def require_k6_user():
	frappe.only_for(USER_ROLES, message=True)


def require_k6_manager():
	frappe.only_for(MANAGER_ROLES, message=True)


def is_k6_manager() -> bool:
	if frappe.session.user == "Administrator":
		return True
	return not set(MANAGER_ROLES).isdisjoint(frappe.get_roles())


def has_k6_access() -> bool:
	if frappe.session.user == "Administrator":
		return True
	return not set(USER_ROLES).isdisjoint(frappe.get_roles())


def ensure_roles():
	"""Create the K6 roles if they do not exist. Safe to call repeatedly."""
	for role in (K6_MANAGER, K6_USER):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


# ─── Metrics endpoint access ──────────────────────────────────────────────────

def check_metrics_access():
	"""
	Allow K6 users with a session, or a scraper presenting
	`X-Frappe-K6-Token: <frappe_k6_metrics_token>` from site config.
	(Not `Authorization: Bearer`, which Frappe's auth layer treats as an OAuth token.)
	"""
	if frappe.session.user != "Guest" and has_k6_access():
		return

	expected = frappe.conf.get("frappe_k6_metrics_token")
	request = getattr(frappe.local, "request", None)
	presented = ((request.headers.get(METRICS_TOKEN_HEADER) if request else None) or "").strip()
	if expected and presented and hmac.compare_digest(presented, expected):
		return

	raise frappe.PermissionError(_("Not permitted to read frappe_k6 metrics"))


# ─── Target validation (SSRF guard) ──────────────────────────────────────────

def _host_port(netloc_or_url):
	parsed = urllib.parse.urlsplit(
		netloc_or_url if "//" in netloc_or_url else "//" + netloc_or_url
	)
	host = (parsed.hostname or "").lower()
	port = parsed.port
	if port is None and parsed.scheme:
		port = 443 if parsed.scheme == "https" else 80
	return host, port


def _allowed_targets():
	"""(host, port) pairs that may be reached even on private addresses; port None = any."""
	allowed = set()

	site_host, site_port = _host_port(frappe.utils.get_url())
	allowed.add((site_host, site_port))
	webserver_port = frappe.conf.get("webserver_port")
	if webserver_port:
		for local in ("localhost", "127.0.0.1"):
			allowed.add((local, int(webserver_port)))

	if frappe.db.exists("DocType", "Remote Server"):
		for rs in frappe.get_all(
			"Remote Server", filters={"enabled": 1}, fields=["host", "frappe_url", "is_local"]
		):
			if rs.frappe_url:
				allowed.add(_host_port(rs.frappe_url))
			elif rs.host and not rs.is_local:
				allowed.add((rs.host.lower(), None))

	extra = frappe.db.get_single_value("Monitor Settings", "allowed_target_hosts") or ""
	for line in extra.replace(",", "\n").splitlines():
		line = line.strip()
		if line:
			allowed.add(_host_port(line) if ":" in line else (line.lower(), None))

	return allowed


def _is_private(host):
	try:
		infos = socket.getaddrinfo(host, None)
	except socket.gaierror:
		return False  # unresolvable — the request itself will fail
	for info in infos:
		ip = ipaddress.ip_address(info[4][0])
		if (
			ip.is_private
			or ip.is_loopback
			or ip.is_link_local
			or ip.is_reserved
			or ip.is_multicast
			or ip.is_unspecified
		):
			return True
	return False


def validate_target_url(url):
	"""
	Raise if `url` points at a private, loopback or link-local address that is not
	this site, an enabled Remote Server, or listed in Monitor Settings → Allowed Target Hosts.
	Public addresses are allowed.
	"""
	parsed = urllib.parse.urlsplit(url)
	if parsed.scheme not in ("http", "https") or not parsed.hostname:
		frappe.throw(_("Only http(s) URLs are allowed: {0}").format(url))

	host, port = _host_port(url)
	allowed = _allowed_targets()
	if (host, port) in allowed or (host, None) in allowed:
		return
	if _is_private(host):
		frappe.throw(
			_(
				"Target {0} resolves to a private address. Add it to Monitor Settings → "
				"Allowed Target Hosts or register it as a Remote Server."
			).format(f"{host}:{port}"),
			frappe.PermissionError,
		)


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
	"""Re-validate every redirect target so a public URL cannot bounce to an internal one."""

	def redirect_request(self, req, fp, code, msg, headers, newurl):
		validate_target_url(newurl)
		return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(req, timeout=30):
	validate_target_url(req.full_url)
	return urllib.request.build_opener(ValidatingRedirectHandler).open(req, timeout=timeout)


# ─── Secrets ─────────────────────────────────────────────────────────────────

def encrypt_value(value):
	from frappe.utils.password import encrypt

	if not value or str(value).startswith(_ENC_PREFIX):
		return value
	return _ENC_PREFIX + encrypt(str(value))


def decrypt_value(value):
	from frappe.utils.password import decrypt

	if not value or not str(value).startswith(_ENC_PREFIX):
		return value
	return decrypt(str(value)[len(_ENC_PREFIX):])


def encrypt_auth_config(cfg):
	return {k: (encrypt_value(v) if k in SECRET_KEYS else v) for k, v in (cfg or {}).items()}


def decrypt_auth_config(cfg):
	return {k: (decrypt_value(v) if k in SECRET_KEYS else v) for k, v in (cfg or {}).items()}


def strip_auth_config(cfg):
	"""Blank out secret values (for exports)."""
	return {k: ("" if k in SECRET_KEYS else v) for k, v in (cfg or {}).items()}

"""
bench commands for frappe_k6.

  bench frappe-k6 doctor [--site X]
  bench frappe-k6 install-k6 [--version 2.3.0] [--force]
  bench --site X frappe-k6 setup-local-stack [--skip Grafana --skip Loki ...]
  bench --site X frappe-k6 connect-cloud --grafana-url URL --sa-token T --access-token T
  bench --site X frappe-k6 cloud-sync dashboards|alerts|history|test
  bench --site X frappe-k6 agent-config [--output alloy.config]
  bench --site X frappe-k6 send-test-alert
"""

import os
import shutil
import subprocess

import click
import frappe
from frappe.commands import get_site, pass_context


@click.group("frappe-k6")
def frappe_k6():
	"""frappe_k6 setup and diagnostics."""


@frappe_k6.command("install-k6")
@click.option("--version", default=None, help="k6 release to install, e.g. 2.3.0")
@click.option("--force", is_flag=True, help="Reinstall even if k6 is already on PATH")
@pass_context
def install_k6(context, version=None, force=False):
	"""Install the static k6 binary into <bench>/env/bin (no sudo)."""
	from frappe_k6.install import _K6_VER, install_k6_binary

	site = context.sites[0] if context.sites else None
	if site:
		frappe.init(site)
		frappe.connect()
	try:
		install_k6_binary(version or _K6_VER, force=force)
		if site:
			frappe.db.commit()
	finally:
		if site:
			frappe.destroy()


@frappe_k6.command("setup-local-stack")
@click.option("--skip", multiple=True, help="Step to skip (repeatable), e.g. --skip Grafana")
@pass_context
def setup_local_stack(context, skip=()):
	"""Install the self-hosted Prometheus/Loki/Grafana stack (needs sudo and systemd)."""
	from frappe_k6.install import setup_local_stack as _setup

	site = get_site(context)
	frappe.init(site)
	frappe.connect()
	try:
		_setup(skip=skip)
	finally:
		frappe.destroy()


@frappe_k6.command("doctor")
@pass_context
def doctor(context):
	"""Check k6, worker and scheduler, roles, settings and the metrics token."""
	site = context.sites[0] if context.sites else None
	problems = 0

	def report(ok, label, hint=""):
		nonlocal problems
		problems += 0 if ok else 1
		click.echo(f"  [{'ok' if ok else '!!'}] {label}" + ("" if ok or not hint else f"\n       → {hint}"))

	click.echo("frappe_k6 doctor")

	k6 = None
	if site:
		frappe.init(site)
		frappe.connect()
		k6 = frappe.db.get_single_value("Monitor Settings", "k6_binary_path")
	k6 = shutil.which(k6 or "k6") or (k6 if k6 and os.path.isfile(k6) else None)
	version = ""
	if k6:
		try:
			version = subprocess.run([k6, "version"], capture_output=True, text=True, timeout=10).stdout.strip()
		except Exception:
			k6 = None
	report(bool(k6), f"k6 binary: {version or k6 or 'not found'}", "bench frappe-k6 install-k6")

	if not site:
		click.echo("  (pass --site to check site settings, roles and workers)")
		raise SystemExit(1 if problems else 0)

	try:
		from frappe.utils.background_jobs import get_workers
		from frappe.utils.scheduler import is_scheduler_disabled

		workers = get_workers()
		report(bool(workers), f"RQ workers running: {len(workers)}",
			   "Load tests run as background jobs on the 'long' queue; start `bench worker` or supervisor")
		long_ok = any("long" in w.queue_names() for w in workers) if workers else False
		report(long_ok, "a worker listens on the 'long' queue", "bench worker --queue long,default,short")
		report(not is_scheduler_disabled(), "scheduler enabled", "bench --site X enable-scheduler")
	except Exception as exc:
		report(False, f"could not reach Redis queue: {exc}", "start Redis (bench start or supervisor)")

	for role in ("K6 Manager", "K6 User"):
		report(bool(frappe.db.exists("Role", role)), f"role '{role}' exists", "bench --site X migrate")

	report(bool(frappe.conf.get("frappe_k6_metrics_token")), "metrics token in site config",
		   "bench --site X execute frappe_k6.install.ensure_metrics_token")

	mode = frappe.db.get_single_value("Monitor Settings", "monitoring_mode") or "Off"
	click.echo(f"  [..] monitoring mode: {mode}")
	if mode == "Self-hosted":
		from frappe_k6.frappe_k6.prometheus_manager import _CFG_PATH

		report(os.path.isfile(_CFG_PATH), f"Prometheus config at {_CFG_PATH}",
			   f"bench --site {site} frappe-k6 setup-local-stack")

	frappe.destroy()
	raise SystemExit(1 if problems else 0)


def _print_results(results):
	failed = False
	for step, result in (results or {}).items():
		failed |= str(result).startswith(("FAILED", "failed"))
		click.echo(f"  {step:<18} {result}")
	return failed


@frappe_k6.command("connect-cloud")
@click.option("--grafana-url", help="Grafana Cloud stack URL, e.g. https://yourstack.grafana.net")
@click.option("--sa-token", envvar="GRAFANA_SA_TOKEN", help="Grafana service account token (or GRAFANA_SA_TOKEN)")
@click.option("--access-token", envvar="GRAFANA_CLOUD_TOKEN",
			  help="Cloud access policy token with metrics:write, logs:write (or GRAFANA_CLOUD_TOKEN)")
@click.option("--mode", type=click.Choice(["cloud", "hybrid"]), default=None,
			  help="cloud: Frappe pushes directly. hybrid: keep the local stack and forward it. Default: picked from the current mode")
@click.option("--no-dashboards", is_flag=True)
@click.option("--no-alerts", is_flag=True)
@click.option("--no-history", is_flag=True)
@pass_context
def connect_cloud(context, grafana_url=None, sa_token=None, access_token=None, mode=None,
				  no_dashboards=False, no_alerts=False, no_history=False):
	"""Connect a site to Grafana Cloud and migrate dashboards, alerts and run history."""
	from frappe_k6.grafana_cloud import connect

	site = get_site(context)
	frappe.init(site)
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		settings = frappe.get_single("Monitor Settings")
		if grafana_url:
			settings.gc_grafana_url = grafana_url
		if sa_token:
			settings.gc_service_account_token = sa_token
		if access_token:
			settings.gc_access_policy_token = access_token
		if mode:
			settings.monitoring_mode = "Grafana Cloud" if mode == "cloud" else "Hybrid"
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		failed = _print_results(connect(int(not no_dashboards), int(not no_alerts), int(not no_history)))
	finally:
		frappe.destroy()
	raise SystemExit(1 if failed else 0)


@frappe_k6.command("cloud-sync")
@click.argument("what", type=click.Choice(["dashboards", "alerts", "history", "test"]))
@pass_context
def cloud_sync(context, what):
	"""Re-run one Grafana Cloud step: dashboards, alerts, history or test."""
	from frappe_k6 import grafana_cloud

	site = get_site(context)
	frappe.init(site)
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		fn = {"dashboards": grafana_cloud.sync_dashboards, "alerts": grafana_cloud.sync_alerts,
			  "history": grafana_cloud.migrate_history, "test": grafana_cloud.test_connection}[what]
		failed = _print_results(fn())
		frappe.db.commit()
	finally:
		frappe.destroy()
	raise SystemExit(1 if failed else 0)


@frappe_k6.command("agent-config")
@click.option("--server-name", default=None, help="Label for this host (default: the local Remote Server or hostname)")
@click.option("--env", "environment", default=None, help="Environment label (default: from the local Remote Server)")
@click.option("--output", type=click.Path(dir_okay=False), default=None, help="Write to a file instead of stdout")
@pass_context
def agent_config(context, server_name=None, environment=None, output=None):
	"""Print a Grafana Alloy config that ships this host's metrics and bench logs to Grafana Cloud."""
	from frappe.utils import get_bench_path

	from frappe_k6.grafana_cloud import base_labels, render_alloy_config

	site = get_site(context)
	frappe.init(site)
	frappe.connect()
	try:
		labels = base_labels()
		text = render_alloy_config(server_name or labels["server_name"], environment or labels["env"],
								   get_bench_path())
	finally:
		frappe.destroy()
	if output:
		with open(output, "w") as f:
			f.write(text)
		click.echo(f"Wrote {output}. Start Alloy with GRAFANA_CLOUD_TOKEN set to the access policy token.")
	else:
		click.echo(text)


@frappe_k6.command("send-test-alert")
@pass_context
def send_test_alert(context):
	"""Send a test alert to every configured channel."""
	from frappe_k6.alerts import send_test_alert as _send

	site = get_site(context)
	frappe.init(site)
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		failed = _print_results(_send())
	finally:
		frappe.destroy()
	raise SystemExit(1 if failed else 0)


commands = [frappe_k6]

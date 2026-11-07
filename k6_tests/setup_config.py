#!/usr/bin/env python3
"""
Dynamic site config generator for k6 tests.
Run this before k6 tests to generate config/site.json from bench site settings.

Usage:
    python3 setup_config.py --site <site_name> --bench <bench_path> [--user <api_user>] [--password <api_password>]

Example:
    python3 setup_config.py --site erpv16.com --bench /home/erpadmin/eduv16
"""

import argparse
import json
import os
import sys


def get_bench_path(bench_arg):
    if bench_arg:
        return os.path.abspath(bench_arg)
    # auto-detect: walk up from this file's location looking for sites/ directory
    current = os.path.abspath(os.path.dirname(__file__))
    for _ in range(10):
        if os.path.isdir(os.path.join(current, "sites")) and os.path.isfile(
            os.path.join(current, "sites", "common_site_config.json")
        ):
            return current
        current = os.path.dirname(current)
    return None


def read_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser(description="Generate k6 site config from bench settings")
    parser.add_argument("--site", required=True, help="Site name (e.g. erpv16.com)")
    parser.add_argument("--bench", help="Bench root path (auto-detected if not given)")
    parser.add_argument("--user", default="Administrator", help="Frappe user for API auth")
    parser.add_argument("--password", default="", help="Ignored: the password is passed to k6 through K6_API_PASSWORD, not written to disk")
    parser.add_argument("--protocol", default="http", choices=["http", "https"])
    parser.add_argument("--port", default="", help="Port if non-standard (e.g. 8000)")
    args = parser.parse_args()

    bench_path = get_bench_path(args.bench)
    if not bench_path:
        print("ERROR: Cannot detect bench path. Use --bench /path/to/bench", file=sys.stderr)
        sys.exit(1)

    sites_path = os.path.join(bench_path, "sites")
    site_path = os.path.join(sites_path, args.site)

    if not os.path.isdir(site_path):
        print(f"ERROR: Site '{args.site}' not found in {sites_path}", file=sys.stderr)
        available = [
            d for d in os.listdir(sites_path)
            if os.path.isdir(os.path.join(sites_path, d)) and not d.startswith("assets")
        ]
        print(f"Available sites: {available}", file=sys.stderr)
        sys.exit(1)

    common_cfg = read_json(os.path.join(sites_path, "common_site_config.json"))
    site_cfg = read_json(os.path.join(site_path, "site_config.json"))

    # Determine base URL
    port_part = f":{args.port}" if args.port else ""
    base_url = f"{args.protocol}://{args.site}{port_part}"

    # Build output config
    config = {
        "base_url": base_url,
        "site_name": args.site,
        "bench_path": bench_path,
        "api_user": args.user,
        "db_name": site_cfg.get("db_name", ""),
        "frappe_version": 16,
        "thresholds": {
            "http_req_duration_p95_ms": 2000,
            "http_req_duration_p99_ms": 5000,
            "http_req_failed_rate": 0.01
        }
    }

    out_path = os.path.join(os.path.dirname(__file__), "config", "site.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"✅ Config written to: {out_path}")
    print(f"   base_url  : {config['base_url']}")
    print(f"   site_name : {config['site_name']}")
    print(f"   api_user  : {config['api_user']}")
    print(f"   bench_path: {config['bench_path']}")


if __name__ == "__main__":
    main()

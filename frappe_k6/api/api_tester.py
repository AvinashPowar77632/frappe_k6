"""
frappe_k6.api.api_tester
Server-side proxy and persistence layer for the API Builder.
"""

import json
import time
import base64
import urllib.request
import urllib.error
import urllib.parse

import frappe


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse(raw, default=None):
    if not raw:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _resolve_variables(text, variables):
    """Replace {{varName}} placeholders in text using the variables dict."""
    if not text or not variables:
        return text
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


# ──────────────────────────────────────────────────────────────────────────────
# Send Request (proxy)
# ──────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def send_request(config_json):
    """
    Proxy an HTTP request from the server side.
    Returns status, headers, body, timing, size, and assertion results.

    config_json keys:
      method, url, headers (list of {key,value,enabled}),
      params (list of {key,value,enabled}),
      path_params (dict),
      body_type (none|json|xml|text|html|form-data|urlencoded),
      body_content (str),
      auth_type, auth_config (dict),
      variables (list of {key,value}),
      expected_status (int),
      response_time_threshold_ms (int),
      assertions (list of {type,path,operator,value})
    """
    cfg = _parse(config_json, {})

    # ── Build variable map ───────────────────────────────────────────────────
    var_map = {v["key"]: v["value"] for v in (cfg.get("variables") or []) if v.get("key")}
    # Built-in dynamic vars
    import uuid as _uuid
    var_map.setdefault("timestamp", str(int(time.time())))
    var_map.setdefault("uuid", str(_uuid.uuid4()))
    var_map.setdefault("random_int", str(int(time.time()) % 10000))

    # ── Build URL ────────────────────────────────────────────────────────────
    url = _resolve_variables(cfg.get("url", ""), var_map)
    path_params = cfg.get("path_params") or {}
    for k, v in path_params.items():
        url = url.replace(":" + k, str(v)).replace("{" + k + "}", str(v))

    enabled_params = [p for p in (cfg.get("params") or []) if p.get("enabled", True) and p.get("key")]
    if enabled_params:
        qs = urllib.parse.urlencode(
            [(p["key"], _resolve_variables(str(p.get("value", "")), var_map)) for p in enabled_params]
        )
        url = url + ("&" if "?" in url else "?") + qs

    # ── Build headers ────────────────────────────────────────────────────────
    headers = {}
    for h in (cfg.get("headers") or []):
        if h.get("enabled", True) and h.get("key"):
            headers[h["key"]] = _resolve_variables(str(h.get("value", "")), var_map)

    # ── Apply auth ───────────────────────────────────────────────────────────
    auth_type = (cfg.get("auth_type") or "None").strip()
    auth_cfg  = cfg.get("auth_config") or {}

    if auth_type == "Basic Auth":
        user = auth_cfg.get("username", "")
        pwd  = auth_cfg.get("password", "")
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    elif auth_type == "Bearer Token":
        tok = auth_cfg.get("token", "")
        headers["Authorization"] = f"Bearer {_resolve_variables(tok, var_map)}"

    elif auth_type == "API Key":
        hdr = auth_cfg.get("header", "X-API-Key")
        val = auth_cfg.get("value", "")
        headers[hdr] = _resolve_variables(val, var_map)

    elif auth_type == "JWT Token":
        tok = auth_cfg.get("token", "")
        headers["Authorization"] = f"Bearer {_resolve_variables(tok, var_map)}"

    elif auth_type == "Session (Frappe Login)":
        # Use current session cookies — client sends them automatically via same-origin
        pass

    elif auth_type == "Custom Header":
        hdr = auth_cfg.get("header", "Authorization")
        val = auth_cfg.get("value", "")
        headers[hdr] = _resolve_variables(val, var_map)

    # ── Build body ───────────────────────────────────────────────────────────
    body_type    = (cfg.get("body_type") or "none").lower()
    body_content = _resolve_variables(cfg.get("body_content") or "", var_map)
    body_bytes   = None

    if body_type == "json":
        headers.setdefault("Content-Type", "application/json")
        body_bytes = body_content.encode("utf-8") if body_content else None
    elif body_type in ("xml", "html", "text"):
        ct_map = {"xml": "application/xml", "html": "text/html", "text": "text/plain"}
        headers.setdefault("Content-Type", ct_map[body_type])
        body_bytes = body_content.encode("utf-8") if body_content else None
    elif body_type == "urlencoded":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        parsed = _parse(body_content, {})
        body_bytes = urllib.parse.urlencode(parsed).encode("utf-8") if parsed else None
    elif body_type == "form-data":
        # Simple form-data (no file upload from server proxy)
        parsed = _parse(body_content, {})
        if parsed:
            boundary = "----FormBoundary" + str(int(time.time()))
            parts = []
            for k, v in parsed.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}')
            body_bytes = ("\r\n".join(parts) + f"\r\n--{boundary}--\r\n").encode("utf-8")
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    # ── Send ─────────────────────────────────────────────────────────────────
    method = (cfg.get("method") or "GET").upper()
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

    start_ts = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed_ms  = int((time.time() - start_ts) * 1000)
            resp_body   = resp.read()
            resp_status = resp.status
            resp_headers = dict(resp.headers)
    except urllib.error.HTTPError as e:
        elapsed_ms  = int((time.time() - start_ts) * 1000)
        resp_body   = e.read() or b""
        resp_status = e.code
        resp_headers = dict(e.headers) if e.headers else {}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "elapsed_ms": int((time.time() - start_ts) * 1000)}

    resp_size = len(resp_body)
    content_type = resp_headers.get("Content-Type", resp_headers.get("content-type", ""))

    try:
        resp_text = resp_body.decode("utf-8", errors="replace")
    except Exception:
        resp_text = repr(resp_body)

    # ── Assertions ───────────────────────────────────────────────────────────
    expected_status = int(cfg.get("expected_status") or 200)
    rt_threshold    = int(cfg.get("response_time_threshold_ms") or 2000)
    assertions      = cfg.get("assertions") or []

    assertion_results = []

    def _eval_assertion(a):
        atype = a.get("type", "")
        aval  = str(a.get("value", ""))
        op    = a.get("operator", "equals")

        if atype == "status_code":
            actual = str(resp_status)
        elif atype == "response_time":
            actual = str(elapsed_ms)
        elif atype == "header":
            hname  = a.get("path", "")
            actual = resp_headers.get(hname, resp_headers.get(hname.lower(), ""))
        elif atype == "json_path":
            try:
                body_json = json.loads(resp_text)
                path_parts = a.get("path", "").lstrip("$.").split(".")
                node = body_json
                for part in path_parts:
                    if part.isdigit():
                        node = node[int(part)]
                    else:
                        node = node[part]
                actual = str(node)
            except Exception as ex:
                return {"type": atype, "path": a.get("path"), "passed": False,
                        "message": f"JSON path error: {ex}"}
        elif atype == "body_contains":
            passed = aval in resp_text
            return {"type": atype, "passed": passed,
                    "message": f"Body {'contains' if passed else 'does not contain'} '{aval}'"}
        else:
            return {"type": atype, "passed": True, "message": "Unknown assertion type — skipped"}

        if op == "equals":
            passed = actual == aval
        elif op == "not_equals":
            passed = actual != aval
        elif op == "contains":
            passed = aval in actual
        elif op == "less_than":
            passed = float(actual) < float(aval)
        elif op == "greater_than":
            passed = float(actual) > float(aval)
        else:
            passed = True

        return {"type": atype, "path": a.get("path"), "expected": aval,
                "actual": actual, "operator": op, "passed": passed}

    for a in assertions:
        try:
            assertion_results.append(_eval_assertion(a))
        except Exception as ex:
            assertion_results.append({"type": a.get("type"), "passed": False, "message": str(ex)})

    # Built-in checks
    status_ok = (resp_status == expected_status)
    time_ok   = (elapsed_ms <= rt_threshold)

    all_passed = status_ok and time_ok and all(ar.get("passed", True) for ar in assertion_results)

    result = {
        "ok":           True,
        "status":       resp_status,
        "elapsed_ms":   elapsed_ms,
        "size_bytes":   resp_size,
        "content_type": content_type,
        "headers":      resp_headers,
        "body":         resp_text,
        "status_ok":    status_ok,
        "time_ok":      time_ok,
        "all_passed":   all_passed,
        "assertions":   assertion_results,
    }
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Collections CRUD
# ──────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_collections():
    cols = frappe.get_all("API Collection",
        fields=["name", "collection_name", "description", "base_url"],
        order_by="collection_name asc")
    for c in cols:
        c["request_count"] = frappe.db.count("API Request", {"collection": c["name"]})
    return cols


@frappe.whitelist()
def save_collection(name, collection_name, description="", base_url=""):
    if name and frappe.db.exists("API Collection", name):
        doc = frappe.get_doc("API Collection", name)
        doc.collection_name = collection_name
        doc.description = description
        doc.base_url = base_url
        doc.save()
    else:
        doc = frappe.get_doc({
            "doctype": "API Collection",
            "collection_name": collection_name,
            "description": description,
            "base_url": base_url,
        })
        doc.insert()
    frappe.db.commit()
    return doc.name


@frappe.whitelist()
def delete_collection(name):
    frappe.db.delete("API Request", {"collection": name})
    frappe.delete_doc("API Collection", name, force=True)
    frappe.db.commit()
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Requests CRUD
# ──────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_requests(collection=None):
    filters = {}
    if collection:
        filters["collection"] = collection
    reqs = frappe.get_all("API Request",
        filters=filters,
        fields=["name", "request_name", "collection", "method", "url",
                "auth_type", "expected_status"],
        order_by="request_name asc")
    return reqs


@frappe.whitelist()
def get_request(name):
    if not frappe.db.exists("API Request", name):
        return None
    doc = frappe.get_doc("API Request", name)
    return doc.as_dict()


@frappe.whitelist()
def save_api_request(config_json):
    cfg = _parse(config_json, {})
    name = cfg.get("name")
    if name and frappe.db.exists("API Request", name):
        doc = frappe.get_doc("API Request", name)
    else:
        doc = frappe.new_doc("API Request")

    doc.request_name           = cfg.get("request_name") or "Untitled Request"
    doc.collection             = cfg.get("collection") or None
    doc.method                 = cfg.get("method") or "GET"
    doc.url                    = cfg.get("url") or ""
    doc.auth_type              = cfg.get("auth_type") or "None"
    doc.auth_config_json       = json.dumps(cfg.get("auth_config") or {}, indent=2)
    doc.headers_json           = json.dumps(cfg.get("headers") or [], indent=2)
    doc.params_json            = json.dumps(cfg.get("params") or [], indent=2)
    doc.path_params_json       = json.dumps(cfg.get("path_params") or {}, indent=2)
    doc.body_type              = cfg.get("body_type") or "none"
    doc.body_content           = cfg.get("body_content") or ""
    doc.variables_json         = json.dumps(cfg.get("variables") or [], indent=2)
    doc.expected_status        = int(cfg.get("expected_status") or 200)
    doc.response_time_threshold_ms = int(cfg.get("response_time_threshold_ms") or 2000)
    doc.assertions_json        = json.dumps(cfg.get("assertions") or [], indent=2)

    if cfg.get("last_response"):
        doc.last_response_json = json.dumps(cfg["last_response"], indent=2)

    if doc.name:
        doc.save()
    else:
        doc.insert()
    frappe.db.commit()
    return doc.name


@frappe.whitelist()
def delete_api_request(name):
    frappe.delete_doc("API Request", name, force=True)
    frappe.db.commit()
    return True


@frappe.whitelist()
def duplicate_api_request(name):
    src = frappe.get_doc("API Request", name)
    new_doc = frappe.copy_doc(src)
    new_doc.request_name = src.request_name + " (Copy)"
    new_doc.last_response_json = None
    new_doc.insert()
    frappe.db.commit()
    return new_doc.name


# ──────────────────────────────────────────────────────────────────────────────
# Integration with Load Test Config
# ──────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def add_to_load_test(request_name_or_config, config_name=None):
    """
    Add an API Request (by doc name or inline config JSON) to a Load Test Config.
    Creates a new Load Test Config if config_name is None or blank.
    Returns the Load Test Config name.
    """
    cfg = _parse(request_name_or_config)
    if cfg is None:
        # It's a doc name, not inline JSON
        doc = frappe.get_doc("API Request", request_name_or_config)
        cfg = {
            "request_name": doc.request_name,
            "method":       doc.method,
            "url":          doc.url,
            "auth_type":    doc.auth_type,
            "auth_config":  _parse(doc.auth_config_json, {}),
            "headers":      _parse(doc.headers_json, []),
            "params":       _parse(doc.params_json, []),
            "body_type":    doc.body_type,
            "body_content": doc.body_content,
            "expected_status": doc.expected_status,
        }

    # Build header JSON for the endpoint
    extra_headers = {h["key"]: h["value"] for h in (cfg.get("headers") or [])
                     if h.get("enabled", True) and h.get("key")}
    query_params  = {p["key"]: p["value"] for p in (cfg.get("params") or [])
                     if p.get("enabled", True) and p.get("key")}

    # Auth → auth_value field
    auth_type = cfg.get("auth_type", "None")
    auth_cfg  = cfg.get("auth_config") or {}
    auth_value = ""
    if auth_type == "Basic Auth":
        auth_value = f"{auth_cfg.get('username','')}:{auth_cfg.get('password','')}"
    elif auth_type in ("Bearer Token", "JWT Token"):
        auth_value = auth_cfg.get("token", "")
    elif auth_type == "API Key":
        auth_value = auth_cfg.get("value", "")
    elif auth_type == "Session (Frappe Login)":
        auth_value = f"{auth_cfg.get('username','')}:{auth_cfg.get('password','')}"
    elif auth_type == "Custom Header":
        extra_headers[auth_cfg.get("header", "Authorization")] = auth_cfg.get("value", "")

    endpoint_row = {
        "doctype":         "Load Test Endpoint",
        "api_name":        cfg.get("request_name", "API"),
        "http_method":     cfg.get("method", "GET"),
        "endpoint_url":    cfg.get("url", ""),
        "expected_status": int(cfg.get("expected_status") or 200),
        "auth_type":       auth_type if auth_type in (
            "None", "Session (Frappe Login)", "Bearer Token", "Basic Auth",
            "API Key", "Custom Header") else "None",
        "auth_value":      auth_value,
        "headers":         json.dumps(extra_headers) if extra_headers else "",
        "query_params":    json.dumps(query_params) if query_params else "",
        "payload":         cfg.get("body_content") or "",
        "weight":          100,
    }

    if config_name and frappe.db.exists("Load Test Config", config_name):
        lt = frappe.get_doc("Load Test Config", config_name)
        lt.append("endpoints", endpoint_row)
        lt.save()
        frappe.db.commit()
        return lt.name
    else:
        lt = frappe.new_doc("Load Test Config")
        lt.test_name    = cfg.get("request_name", "API Test")
        lt.scenario_type = "load"
        lt.virtual_users = 10
        lt.duration     = "5m"
        lt.ramp_up_time = "1m"
        lt.append("endpoints", endpoint_row)
        lt.insert()
        frappe.db.commit()
        return lt.name


@frappe.whitelist()
def get_load_test_configs():
    return frappe.get_all("Load Test Config",
        fields=["name", "test_name", "scenario_type", "status"],
        order_by="test_name asc")


# ──────────────────────────────────────────────────────────────────────────────
# Import / Export
# ──────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def export_collection(collection_name):
    """Return full collection + requests as a JSON dict (for download)."""
    if not frappe.db.exists("API Collection", collection_name):
        frappe.throw("Collection not found")
    col = frappe.get_doc("API Collection", collection_name)
    requests = frappe.get_all("API Request",
        filters={"collection": collection_name},
        fields=["*"])
    return {"collection": col.as_dict(), "requests": requests}


@frappe.whitelist()
def import_collection(json_data):
    """Import a collection + requests from exported JSON."""
    data = _parse(json_data, {})
    col_data  = data.get("collection", {})
    reqs_data = data.get("requests", [])

    col_name = col_data.get("collection_name", "Imported Collection")
    if not frappe.db.exists("API Collection", col_name):
        col = frappe.get_doc({
            "doctype": "API Collection",
            "collection_name": col_name,
            "description": col_data.get("description", ""),
            "base_url": col_data.get("base_url", ""),
        })
        col.insert()
        frappe.db.commit()
        col_name = col.name

    for r in reqs_data:
        new_req = frappe.new_doc("API Request")
        for field in ["request_name", "method", "url", "auth_type", "auth_config_json",
                       "headers_json", "params_json", "path_params_json", "body_type",
                       "body_content", "variables_json", "expected_status",
                       "response_time_threshold_ms", "assertions_json"]:
            if r.get(field) is not None:
                setattr(new_req, field, r[field])
        new_req.collection = col_name
        new_req.insert()

    frappe.db.commit()
    return {"collection": col_name, "imported": len(reqs_data)}

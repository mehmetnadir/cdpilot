#!/usr/bin/env python3
"""Fake-CDP harness for WebMCP bridge tests.

Imports cdpilot.py with a mocked websockets module and exercises the WebMCP
polyfill/hook logic, argument validation, and tool listing/calling via
simulated CDP responses.  No real browser needed.

Usage:
    python3 test/webmcp_fake_cdp.py src/cdpilot.py

Output: JSON with scenario results (read by test/test.js).

The pattern follows test/frames_fake_cdp.py — see that file for the
general approach.
"""

import sys, os, json, importlib.util, asyncio, types

PY_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'src', 'cdpilot.py')

# ── Fake websockets ──────────────────────────────────────────────────────────

class FakeWS:
    """Minimal WebSocket stand-in that answers CDP commands."""

    def __init__(self, responses=None):
        self.sent = []
        self.responses = responses or {}  # id -> result
        self._queue = asyncio.Queue()

    async def send(self, data):
        msg = json.loads(data)
        self.sent.append(msg)
        mid = msg.get("id")
        if mid in self.responses:
            await self._queue.put(json.dumps({"id": mid, "result": self.responses[mid]}))
        else:
            await self._queue.put(json.dumps({"id": mid, "result": {}}))

    async def recv(self):
        return await asyncio.wait_for(self._queue.get(), timeout=2)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


_fake_ws_instance = None

async def fake_connect(url, **kw):
    global _fake_ws_instance
    return _fake_ws_instance


def install_fake_websockets():
    """Install a fake 'websockets' module into sys.modules."""
    mod = types.ModuleType("websockets")
    mod.connect = fake_connect
    sys.modules["websockets"] = mod
    return mod


# ── Load cdpilot module ─────────────────────────────────────────────────────

def load_cdpilot():
    install_fake_websockets()
    # Isolate environment
    os.environ["CDPILOT_HOME"] = os.environ.get("CDPILOT_HOME", "/tmp/cdpilot-webmcp-test")
    os.environ["CDP_PORT"] = os.environ.get("CDP_PORT", "19225")
    os.environ["CDPILOT_LOG"] = "0"
    os.environ["CDPILOT_WEBMCP"] = "1"

    spec = importlib.util.spec_from_file_location("cdpilot", PY_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Prevent __main__ execution
    mod.__name__ = "cdpilot"
    spec.loader.exec_module(mod)
    return mod


# ── Scenarios ────────────────────────────────────────────────────────────────

def run_scenario(name, fn):
    try:
        result = fn()
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def test_validate_args(mod):
    """Test _webmcp_validate_args — pure function, no CDP needed."""
    results = []

    schema = {
        "type": "object",
        "properties": {
            "sku": {"type": "string"},
            "qty": {"type": "integer"},
        },
        "required": ["sku", "qty"],
    }

    # Valid
    ok, err = mod._webmcp_validate_args(schema, {"sku": "A1", "qty": 2})
    results.append({"case": "valid", "ok": ok, "err": err})

    # Missing required
    ok, err = mod._webmcp_validate_args(schema, {"sku": "A1"})
    results.append({"case": "missing_required", "ok": ok, "err": err})

    # Wrong type
    ok, err = mod._webmcp_validate_args(schema, {"sku": "A1", "qty": "two"})
    results.append({"case": "wrong_type", "ok": ok, "err": err})

    # Not a dict
    ok, err = mod._webmcp_validate_args(schema, "not-a-dict")
    results.append({"case": "not_dict", "ok": ok, "err": err})

    # Empty schema (anything goes)
    ok, err = mod._webmcp_validate_args({}, {"foo": "bar"})
    results.append({"case": "empty_schema", "ok": ok, "err": err})

    # Number allows int
    schema2 = {"type": "object", "properties": {"val": {"type": "number"}}}
    ok, err = mod._webmcp_validate_args(schema2, {"val": 42})
    results.append({"case": "number_int", "ok": ok, "err": err})

    return results


def test_webmcp_config(mod):
    """Test get_webmcp_config reads env var."""
    results = []

    os.environ["CDPILOT_WEBMCP"] = "1"
    results.append({"val": "1", "active": mod.get_webmcp_config()})

    os.environ["CDPILOT_WEBMCP"] = "0"
    results.append({"val": "0", "active": mod.get_webmcp_config()})

    os.environ["CDPILOT_WEBMCP"] = "true"
    results.append({"val": "true", "active": mod.get_webmcp_config()})

    os.environ["CDPILOT_WEBMCP"] = ""
    results.append({"val": "empty", "active": mod.get_webmcp_config()})

    # Restore
    os.environ["CDPILOT_WEBMCP"] = "1"
    return results


def test_hook_js_content(mod):
    """Verify the hook JS contains expected patterns."""
    js = mod.WEBMCP_HOOK_JS
    checks = {
        "has_registry": "__cdpilot_webmcp_tools" in js,
        "has_registerTool": "registerTool" in js,
        "has_form_scan": "toolname" in js,
        "has_abort_signal": "AbortSignal" in js or "abort" in js,
        "has_polyfill": "modelContext" in js,
        "has_declarative": "tooldescription" in js,
    }
    return checks


def test_redact_tools_call(mod):
    """Test that _slog_redact_args redacts secret-named fields in tools call."""
    results = []

    # Normal args — no secrets
    args_normal = ["call", "add_to_cart", '{"sku":"A1","qty":2}']
    red, secrets = mod._slog_redact_args("tools", args_normal)
    results.append({"case": "normal", "secrets": secrets, "has_sku": "A1" in str(red)})

    # Secret field (password)
    args_secret = ["call", "login", '{"username":"alice","password":"hunter2"}']
    red, secrets = mod._slog_redact_args("tools", args_secret)
    results.append({
        "case": "secret",
        "password_redacted": "hunter2" not in str(red),
        "username_kept": "alice" in str(red),
        "secrets_has_hunter": "hunter2" in secrets,
    })

    # Secret field (api_key)
    args_key = ["call", "config", '{"api_key":"sk-1234","mode":"fast"}']
    red, secrets = mod._slog_redact_args("tools", args_key)
    results.append({
        "case": "api_key",
        "key_redacted": "sk-1234" not in str(red),
        "mode_kept": "fast" in str(red),
    })

    return results


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mod = load_cdpilot()

    results = {}
    results["validate_args"] = run_scenario("validate_args", lambda: test_validate_args(mod))
    results["webmcp_config"] = run_scenario("webmcp_config", lambda: test_webmcp_config(mod))
    results["hook_js_content"] = run_scenario("hook_js_content", lambda: test_hook_js_content(mod))
    results["redact_tools_call"] = run_scenario("redact_tools_call", lambda: test_redact_tools_call(mod))

    print(json.dumps(results))

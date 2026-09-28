"""Fake-CDP harness for the WebMCP tests in test.js (no browser needed).

    python webmcp_fake_cdp.py <path/to/cdpilot.py> <node>

Loads cdpilot.py with a stand-in `websockets` module. The real
`tools list` / `tools call` code, cdp_send and the WS pool run unchanged;
only the wire is fake. Every Runtime.evaluate expression cdpilot sends is
run by test/webmcp_fake_page.js inside a Node vm whose document.modelContext
is a recording fake, so the tests see what the expression actually did
(getTools / executeTool, the input and the options it passed), not its text.
Also covers the pure helpers: argument validation, the "why no tools"
diagnosis, launch flags, mode persistence and session-log redaction.

Prints one JSON object {scenario: result}; a scenario that raises reports
{"error": traceback}.
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
import types

HERE = os.path.dirname(os.path.abspath(__file__))
WS = "ws://fake/devtools/page/1"
STATE = {"browser": None}


class Browser:
    """Answers CDP: Runtime.evaluate goes to the fake page; the rest is logged."""

    def __init__(self, node, scenario):
        self.node, self.scenario = node, scenario
        self.log, self.calls = [], []

    WORLD = 77  # executionContextId of cdpilot's isolated world

    def handle(self, msg):
        method, params = msg["method"], msg.get("params") or {}
        if method == "Page.getFrameTree":
            return {"id": msg["id"], "result": {"frameTree": {"frame": {"id": "TOP"}}}}
        if method == "Page.createIsolatedWorld":
            ok = params.get("frameId") == "TOP" and self.scenario != "noworld"
            return {"id": msg["id"], "result": {"executionContextId": self.WORLD} if ok else {}}
        if method != "Runtime.evaluate":
            return {"id": msg["id"], "result": {}}
        ctx = params.get("contextId")
        if ctx not in (None, self.WORLD):
            return {"id": msg["id"], "error": {"code": -32000,
                                                "message": "Cannot find context with specified id"}}
        run = subprocess.run(
            [self.node, os.path.join(HERE, "webmcp_fake_page.js")],
            input=json.dumps({"expression": params.get("expression", ""),
                              "scenario": "spec" if self.scenario == "noworld" else self.scenario,
                              "world": "isolated" if ctx == self.WORLD else "main"}),
            capture_output=True, text=True, timeout=30)
        page = json.loads(run.stdout or "{}")
        self.calls.append(page.get("calls", []))
        if "exception" in page:
            return {"id": msg["id"], "result": {
                "result": {"type": "object"},
                "exceptionDetails": {"text": "Uncaught", "exception": {
                    "description": page["exception"]}}}}
        return {"id": msg["id"], "result": {"result": {"type": "object",
                                                       "value": page.get("value")}}}


class FakeWS:
    def __init__(self, browser):
        self.b = browser
        self.q = asyncio.Queue()
        self.closed = False

    async def send(self, text):
        msg = json.loads(text)
        self.b.log.append(msg)
        reply = await asyncio.get_running_loop().run_in_executor(None, self.b.handle, msg)
        self.q.put_nowait(json.dumps(reply))

    async def recv(self):
        return await self.q.get()

    async def close(self):
        self.closed = True


class Connect:
    def __await__(self):
        return self._open().__await__()

    async def _open(self):
        return FakeWS(STATE["browser"])

    async def __aenter__(self):
        self.ws = await self._open()
        return self.ws

    async def __aexit__(self, *exc):
        await self.ws.close()
        return False


def load(path):
    fake = types.ModuleType("websockets")
    fake.connect = lambda url, **kw: Connect()
    sys.modules["websockets"] = fake
    spec = importlib.util.spec_from_file_location("cdpilot_webmcp_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.get_page_ws = lambda *a, **k: (WS, {"url": "https://shop.test/index.html"})
    mod._slog_note_page = lambda page: None
    mod.cdp_get = lambda *a, **k: {"Browser": "HeadlessChrome/154.0.8037.58"}
    return mod


def run(mod, node, scenario, coro_factory):
    """Run a command coroutine against the fake page: wire, page calls, output, exit."""
    b = Browser(node, scenario)
    STATE["browser"] = b
    mod._WS_POOL.clear()
    mod._WS_LOCKS.clear()
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            asyncio.run(coro_factory())
        except SystemExit as e:
            code = 0 if e.code is None else e.code
    wire = [{"method": m["method"],
             "params": {k: v for k, v in (m.get("params") or {}).items() if k != "expression"}}
            for m in b.log]
    return {"wire": wire, "calls": b.calls, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "exit": code}


def scenario_list_routing(mod, node):
    """tools list --json: one main-world Runtime.evaluate that calls getTools()."""
    return {s: run(mod, node, s, lambda: mod.cmd_tools_list(as_json=True))
            for s in ("spec", "legacy")}


def scenario_call_routing(mod, node):
    """tools call: getTools() then executeTool(tool, input, {signal}) in the main world."""
    res = {}
    for s in ("spec", "legacy"):
        res[s] = run(mod, node, s,
                     lambda: mod.cmd_tools_call("add_to_cart", {"sku": "A1", "qty": 2}))
    res["frame"] = run(mod, node, "spec",
                       lambda: mod.cmd_tools_call("frame_echo", {"text": "hi"}))
    res["frame_filter"] = run(mod, node, "spec",
                              lambda: mod.cmd_tools_call("frame_echo", {}, "frame.html"))
    return res


def scenario_hostile_page(mod, node):
    """A page that wrapped getTools/executeTool in its main world."""
    return {
        "list": run(mod, node, "patched", lambda: mod.cmd_tools_list(as_json=True)),
        "call": run(mod, node, "patched",
                    lambda: mod.cmd_tools_call("add_to_cart", {"sku": "A1", "qty": 2})),
        "fake": run(mod, node, "patched", lambda: mod.cmd_tools_call("fake_tool", {})),
    }


def scenario_world_fallback(mod, node):
    """No isolated world, or one without document.modelContext: main world + note."""
    return {s: {"list": run(mod, node, s, lambda: mod.cmd_tools_list(as_json=True)),
                "call": run(mod, node, s,
                            lambda: mod.cmd_tools_call("add_to_cart", {"sku": "A1", "qty": 2}))}
            for s in ("isoblind", "noworld")}


def scenario_two_frames(mod, node):
    """One tool name in two frames: ambiguous without --frame, --frame picks."""
    return {
        "list": run(mod, node, "twoframes", lambda: mod.cmd_tools_list(as_json=True)),
        "ambiguous": run(mod, node, "twoframes",
                         lambda: mod.cmd_tools_call("frame_echo", {"text": "x"})),
        "right": run(mod, node, "twoframes",
                     lambda: mod.cmd_tools_call("frame_echo", {"text": "x"}, "who=right")),
        "left": run(mod, node, "twoframes", lambda: mod.cmd_tools_call(
            "frame_echo", {"text": "x"}, "https://shop.test/frame.html")),
        "both": run(mod, node, "twoframes",
                    lambda: mod.cmd_tools_call("frame_echo", {"text": "x"}, "frame.html")),
        "nomatch": run(mod, node, "twoframes",
                       lambda: mod.cmd_tools_call("frame_echo", {"text": "x"}, "nowhere")),
    }


def scenario_call_timeout(mod, node):
    """The command's time budget aborts the execution through the signal."""
    saved = mod.WEBMCP_CALL_TIMEOUT
    mod.WEBMCP_CALL_TIMEOUT = 0.3
    try:
        return run(mod, node, "hang",
                   lambda: mod.cmd_tools_call("add_to_cart", {"sku": "A1", "qty": 1}))
    finally:
        mod.WEBMCP_CALL_TIMEOUT = saved


def scenario_call_refusals(mod, node):
    """Bad args and unknown tools stop before executeTool; no API -> diagnosis."""
    return {
        "missing": run(mod, node, "spec", lambda: mod.cmd_tools_call("add_to_cart", {"sku": "A"})),
        "bool_int": run(mod, node, "spec",
                        lambda: mod.cmd_tools_call("add_to_cart", {"sku": "A", "qty": True})),
        "unknown": run(mod, node, "spec", lambda: mod.cmd_tools_call("nope", {})),
        "noapi": run(mod, node, "noapi", lambda: mod.cmd_tools_call("add_to_cart", {})),
    }


def scenario_list_diagnosis(mod, node):
    """tools list with no usable tools: exit 0 with the reason."""
    os.environ["CDPILOT_WEBMCP"] = "0"
    try:
        return {s: run(mod, node, s, lambda: mod.cmd_tools_list(as_json=True))
                for s in ("noapi", "insecure", "refused")}
    finally:
        del os.environ["CDPILOT_WEBMCP"]


def scenario_validate(mod, node):
    """_webmcp_validate_args over a table of (schema, args) -> [ok, error]."""
    obj = {"type": "object", "properties": {
        "n": {"type": "integer"}, "x": {"type": "number"}, "b": {"type": "boolean"},
        "s": {"type": "string", "enum": ["a", "b"]}, "u": {"type": ["string", "null"]},
        "one": {"enum": [1, "1"]}, "c": {"const": True},
        "arr": {"type": "array", "items": {"type": "integer"}},
        "o": {"type": "object", "properties": {"k": {"type": "string"}}, "required": ["k"]},
        "p": {"type": "string", "pattern": "^z", "minLength": 5}},
        "required": ["n"]}
    cases = {
        "ok": (obj, {"n": 1}),
        "missing_required": (obj, {}),
        "bool_not_integer": (obj, {"n": True}),
        "bool_not_number": (obj, {"n": 1, "x": False}),
        "int_is_number": (obj, {"n": 1, "x": 3}),
        "float_integral_is_integer": (obj, {"n": 2.0}),
        "float_not_integer": (obj, {"n": 2.5}),
        "string_not_integer": (obj, {"n": "1"}),
        "enum_ok": (obj, {"n": 1, "s": "a"}),
        "enum_bad": (obj, {"n": 1, "s": "c"}),
        "enum_true_is_not_1": (obj, {"n": 1, "one": True}),
        "enum_1_ok": (obj, {"n": 1, "one": 1.0}),
        "const_ok": (obj, {"n": 1, "c": True}),
        "const_bad": (obj, {"n": 1, "c": 1}),
        "union_null_ok": (obj, {"n": 1, "u": None}),
        "union_bad": (obj, {"n": 1, "u": 3}),
        "items_bad": (obj, {"n": 1, "arr": [1, "2"]}),
        "nested_required": (obj, {"n": 1, "o": {}}),
        "nested_type": (obj, {"n": 1, "o": {"k": 5}}),
        "unsupported_keywords_deferred": (obj, {"n": 1, "p": "a"}),
        "not_object": (obj, [1]),
        "no_schema": (None, {"anything": 1}),
        "empty_schema": ({}, {"anything": 1}),
    }
    return {k: list(mod._webmcp_validate_args(s, a)) for k, (s, a) in cases.items()}


def scenario_diagnose(mod, node):
    """_webmcp_diagnose -> reason for each failure mode."""
    d = mod._webmcp_diagnose
    chrome = "HeadlessChrome/154.0.8037.58"
    return {
        "no_tools": d({"api": True, "secure": True}, browser=chrome),
        "insecure": d({"api": False, "secure": False}, browser=chrome),
        "old": d({"api": False, "secure": True}, browser="Chrome/140.0.1.2"),
        "legacy": d({"api": False, "secure": True, "legacy": True}, browser=chrome),
        "flag_off_mode_off": d({"api": False, "secure": True}, mode_on=False, browser=chrome),
        "flag_off_mode_on": d({"api": False, "secure": True}, mode_on=True, browser=chrome),
        "not_origin_keyed": d({"api": True, "secure": True, "originKeyed": False},
                              {"name": "SecurityError", "message": "x"}, browser=chrome),
        "policy": d({"api": True, "secure": True}, {"name": "NotAllowedError", "message": "x"}),
    }


def scenario_mode_and_flags(mod, node):
    """webmcp.json persistence, env override, launch flag parsing and merge."""
    tmp = tempfile.mkdtemp(prefix="cdpilot-webmcp-mode-")
    path = os.path.join(tmp, "webmcp.json")
    g = mod.get_webmcp_config
    res = {"absent": g(env={}, path=path)}
    mod.set_webmcp_config(True, path=path)
    res["saved_on"] = g(env={}, path=path)
    res["env_off_wins"] = g(env={"CDPILOT_WEBMCP": "0"}, path=path)
    mod.set_webmcp_config(False, path=path)
    res["saved_off"] = g(env={}, path=path)
    res["env_on_wins"] = g(env={"CDPILOT_WEBMCP": "true"}, path=path)
    with open(path, "w") as f:
        f.write("{not json")
    res["corrupt"] = g(env={}, path=path)
    res["flag"] = [mod._webmcp_launch_flag(a) for a in
                   (["--webmcp"], ["--no-webmcp"], [], ["--idle-close", "5"])]
    res["args_plain"] = mod._webmcp_launch_args(["chrome", "--disable-features=Translate"])
    res["args_merge"] = mod._webmcp_launch_args(["chrome", "--enable-features=Foo"])
    res["args_dedup"] = mod._webmcp_launch_args(["chrome", "--enable-features=WebMCP"])
    return res


def scenario_redaction(mod, node):
    """Session log: secret-named fields redacted in tools call args and results."""
    args, secrets = mod._slog_redact_args("tools", [
        "call", "login",
        '{"user": "ann", "password": "hunter2", "nested": {"api_key": "sk-abc"}}',
        "--arg", "token=t0ps3cret", "--arg=qty=2", "--frame", "frame.html"])
    result = json.dumps({"ok": True, "user": "ann", "session_token": "zz-9876543",
                         "profile": {"secret": "s3cr3t-value", "name": "Ann"},
                         "items": [{"auth": "abc-123"}]}, indent=2)
    summary = mod._slog_summary("tools", ["call", "login"], result, [])
    plain = mod._slog_summary("tools", ["call", "add"], json.dumps({"ok": True, "qty": 2}), [])
    return {"args": args, "secrets": secrets, "summary": summary, "plain": plain}


SCENARIOS = {
    "list_routing": scenario_list_routing,
    "call_routing": scenario_call_routing,
    "call_timeout": scenario_call_timeout,
    "hostile_page": scenario_hostile_page,
    "world_fallback": scenario_world_fallback,
    "two_frames": scenario_two_frames,
    "call_refusals": scenario_call_refusals,
    "list_diagnosis": scenario_list_diagnosis,
    "validate": scenario_validate,
    "diagnose": scenario_diagnose,
    "mode_and_flags": scenario_mode_and_flags,
    "redaction": scenario_redaction,
}


def main():
    mod = load(sys.argv[1])
    node = sys.argv[2] if len(sys.argv) > 2 else "node"
    results = {}
    for name, fn in SCENARIOS.items():
        try:
            results[name] = fn(mod, node)
        except BaseException:  # noqa: BLE001 - report, keep going
            results[name] = {"error": traceback.format_exc()}
    sys.stdout.write(json.dumps(results) + "\n")


if __name__ == "__main__":
    main()

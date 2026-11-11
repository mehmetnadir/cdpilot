"""Fake-CDP harness for the missing / failed browser reply tests in test.js (no browser needed).

    python eval_reply_fake.py <path/to/cdpilot.py>

Loads cdpilot.py with a stand-in `websockets` module whose socket answers
Runtime.evaluate by marker in the expression: "DROP" gets no reply (cdp_send's
own timeout ends it, cut to 0.4 s here), "ERROR" a CDP error reply
({code, message}), "EMPTY" a real empty object value, anything else the string
"ok:<expression>". Network.getCookies answers a cookie list, or nothing while
STATE["cookies"] is "drop". The real cdp_send (pooled and not), cmd_eval,
cmd_eval_batch, cmd_content, cmd_html, cmd_storage, cmd_cookies, cmd_observe,
the frame `eval` and the warm paths (_daemon_execute, MCPServer._execute_tool
under CDPILOT_DAEMON=1) run unchanged. Prints one JSON object {scenario: result}.
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import traceback
import types

HOME = tempfile.mkdtemp(prefix="cdpilot-evalreply-")
os.environ.update({"CDPILOT_HOME": HOME, "CDPILOT_PROFILE": os.path.join(HOME, "profile"),
                   "CDP_PORT": "19311", "CDPILOT_LOG": "0", "CDPILOT_NO_AUTOLAUNCH": "1",
                   "CDPILOT_PROJECT_ID": "eval-reply", "CHROME_BIN": "/no/such/browser"})
for _k in ("CDPILOT_TARGET", "CDPILOT_DAEMON", "CDPILOT_TIMEOUT", "CDPILOT_WS_POOL"):
    os.environ.pop(_k, None)

WS = "ws://fake/devtools/page/1"
STATE = {"cookies": "ok", "marker": ""}  # marker: put in front of every evaluated expression


class Transport:
    closed = False

    def is_closing(self):
        return self.closed

    def close(self):
        self.closed = True


class FakeWS:
    def __init__(self):
        self.q = asyncio.Queue()
        self.transport = Transport()
        self._closed = False

    @property
    def closed(self):
        return self._closed or self.transport.closed

    async def send(self, text):
        msg = json.loads(text)
        method, p = msg.get("method"), msg.get("params") or {}
        expr = STATE["marker"] + (p.get("expression") or "")
        mid = msg.get("id")
        if method == "Runtime.evaluate":
            if "DROP" in expr:
                return
            if "ERROR" in expr:
                reply = {"id": mid, "error": {"code": -32000, "message": "Cannot find context with specified id"}}
            elif "EMPTY" in expr:
                reply = {"id": mid, "result": {"result": {"type": "object", "value": {}}}}
            else:
                reply = {"id": mid, "result": {"result": {"type": "string", "value": "ok:" + expr[:40]}}}
        elif method == "Network.getCookies":
            if STATE["cookies"] == "drop":
                return
            reply = {"id": mid, "result": {"cookies": [{"name": "a", "value": "1", "domain": "x.test"}]}}
        else:
            reply = {"id": mid, "result": {}}
        self.q.put_nowait(json.dumps(reply))

    async def recv(self):
        return await self.q.get()

    async def close(self):
        self._closed = True
        self.transport.close()


class Connect:
    def __await__(self):
        return self._open().__await__()

    async def _open(self):
        return FakeWS()

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
    spec = importlib.util.spec_from_file_location("cdpilot_evalreply_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.get_page_ws = lambda *a, **k: (WS, {})
    real = mod.cdp_send

    async def short(ws, commands, timeout=15):  # a dropped reply must not cost the real 15 s
        return await real(ws, commands, min(timeout, 0.4))
    mod.cdp_send = short
    return mod


def run(mod, coro_fn, *args, pool=True):
    """res = ['ok', None] or ['exit', code]; what the command printed."""
    mod._WS_POOL.clear()
    mod._WS_LOCKS.clear()
    mod._WS_POOL_ENABLED = pool
    out, err = io.StringIO(), io.StringIO()
    res = ["ok", None]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            asyncio.run(coro_fn(*args))
        except SystemExit as e:
            res = ["exit", e.code]
    return {"res": res, "stdout": out.getvalue(), "stderr": err.getvalue()}


def scenario_eval(mod):
    """eval and eval-batch: a dropped reply, a CDP error and a real {} value, pooled and not."""
    out = {}
    for tag, pool in (("pooled", True), ("unpooled", False)):
        out[tag] = {
            "drop": run(mod, mod.cmd_eval, "DROP", pool=pool),
            "error": run(mod, mod.cmd_eval, "ERROR", pool=pool),
            "empty": run(mod, mod.cmd_eval, "EMPTY", pool=pool),
            "value": run(mod, mod.cmd_eval, "1+1", pool=pool),
            "batch_drop": run(mod, mod.cmd_eval_batch, '["DROP"]', pool=pool),
            "batch_error": run(mod, mod.cmd_eval_batch, '["ERROR"]', pool=pool),
            "batch_empty": run(mod, mod.cmd_eval_batch, '["EMPTY"]', pool=pool),
            "batch_value": run(mod, mod.cmd_eval_batch, '["1+1"]', pool=pool),
        }
    return out


def scenario_helper(mod):
    """_cdp_reply called directly."""
    def call(r, cid=1, method="Runtime.evaluate", timeout=15):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                return {"res": ["ok", mod._cdp_reply(r, cid, method, timeout)], "stderr": err.getvalue()}
            except SystemExit as e:
                return {"res": ["exit", e.code], "stderr": err.getvalue()}
    return {
        "missing": call({}),
        "missing_other_id": call({2: {"result": {}}}, 1, "Page.captureScreenshot", 30),
        "error": call({1: {"code": -32601, "message": "'Foo.bar' wasn't found"}}),
        "empty_result": call({1: {}}),  # Page.enable and friends reply {}
        "value": call({1: {"result": {"type": "string", "value": "x"}}}),
        "code_only": call({1: {"code": 5}}),  # not an error object: passes through
        "result_with_message": call({1: {"result": {}, "code": 1, "message": "m"}}),
    }


def scenario_commands(mod):
    """The other value-printing commands the sweep fixed, with the reply dropped / failed."""
    out = {}
    evaluating = (("content", mod.cmd_content, ()), ("html", mod.cmd_html, ()),
                  ("storage", mod.cmd_storage, ()), ("observe", mod.cmd_observe, ()))
    for tag, marker in (("drop", "DROP"), ("error", "ERROR")):
        STATE["marker"] = marker
        for name, fn, args in evaluating:
            out[f"{name}_{tag}"] = run(mod, fn, *args)
    STATE["marker"] = ""
    STATE["cookies"] = "drop"
    out["cookies_list_drop"] = run(mod, mod.cmd_cookies)
    out["cookies_save_all_drop"] = run(mod, mod.cmd_cookies, "save", os.path.join(HOME, "c.json"))
    out["cookies_save_host_drop"] = run(mod, mod.cmd_cookies, "save", "--host", "x.test")
    out["saved_file_exists"] = os.path.exists(os.path.join(HOME, "c.json"))
    STATE["cookies"] = "ok"
    out["content_ok"] = run(mod, mod.cmd_content)
    out["cookies_ok"] = run(mod, mod.cmd_cookies)
    return out


def scenario_frame_eval(mod):
    """`frame eval` with no frame selected: the top document."""
    out = {}
    for tag, js in (("drop", "DROP"), ("error", "ERROR"), ("value", "1+1")):
        out[tag] = run(mod, mod.cmd_frame, "eval", js)
    return out


def scenario_daemon(mod):
    """_daemon_execute (the warm CLI and MCP path): exit code and streams of a failed eval."""
    out = {}
    os.environ["CDPILOT_DAEMON"] = "1"
    try:
        for tag, js in (("drop", "DROP"), ("error", "ERROR"), ("empty", "EMPTY")):
            o, e = io.StringIO(), io.StringIO()
            refused = []
            code = mod._daemon_execute({"argv": ["eval", js], "cwd": os.getcwd(), "env": dict(os.environ),
                                        "stdin": ""}, o, e, refused.append)
            out[tag] = {"code": code, "stdout": o.getvalue(), "stderr": e.getvalue(), "refused": refused}
        server = mod.MCPServer()
        mcp = {}
        for tag, js in (("drop", "DROP"), ("error", "ERROR"), ("empty", "EMPTY"), ("value", "1+1")):
            with contextlib.redirect_stderr(io.StringIO()):
                mcp[tag] = server._execute_tool(1, "browser_eval", {"expression": js})["result"]
        out["mcp"] = mcp
        batch = {}
        for tag, js in (("drop", "DROP"), ("error", "ERROR")):
            with contextlib.redirect_stderr(io.StringIO()):
                batch[tag] = server._execute_tool(1, "browser_eval_batch", {"expressions": [js]})["result"]
        out["mcp_batch"] = batch
    finally:
        os.environ.pop("CDPILOT_DAEMON", None)
    return out


SCENARIOS = {
    "eval": scenario_eval,
    "helper": scenario_helper,
    "commands": scenario_commands,
    "frame_eval": scenario_frame_eval,
    "daemon": scenario_daemon,
}


def main():
    mod = load(sys.argv[1])
    results = {}
    for name in (sys.argv[2:] or list(SCENARIOS)):
        try:
            results[name] = SCENARIOS[name](mod)
        except BaseException:  # noqa: BLE001 - report, keep going
            results[name] = {"error": traceback.format_exc()}
    sys.stdout.write(json.dumps(results) + "\n")


if __name__ == "__main__":
    main()

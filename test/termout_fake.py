"""Fake-CDP harness for the terminal-output tests in test.js (no browser needed).

    python termout_fake.py <path/to/cdpilot.py>

Page text that carries ESC, other C0 controls, DEL and C1 (0x80-0x9F) reaches the
page-text commands (content, html, go, network, a11y, a11y-snapshot, describe, tabs,
console, debug, storage, eval, the assert family, check, WebMCP tools list / call, the
test reporter). Every command
runs twice: once with stdout and stderr that say they are a terminal (isatty() is
True) and once piped (plain text streams). A third pass writes `content` to a real
pseudo-terminal (Unix), and the warm path (_daemon_execute) runs with the
launcher's tty / etty flags on and off. cdp_send, get_page_ws, get_tabs,
navigate_collect and the WebMCP page calls are stand-ins; the commands run
unchanged. Prints one JSON object {scenario: result}.
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

HOME = tempfile.mkdtemp(prefix="cdpilot-termout-")
os.environ.update({"CDPILOT_HOME": HOME, "CDPILOT_PROFILE": os.path.join(HOME, "profile"),
                   "CDP_PORT": os.environ.get("CDP_PORT") or "19579", "CDPILOT_LOG": "0",
                   "CDPILOT_NO_AUTOLAUNCH": "1", "CDPILOT_PROJECT_ID": "termout",
                   "CHROME_BIN": "/no/such/browser"})
for _k in ("CDPILOT_TARGET", "CDPILOT_DAEMON", "CDPILOT_TIMEOUT", "CDPILOT_WS_POOL", "CDPILOT_JSON",
           "CDPILOT_MCP_SESSION"):
    os.environ.pop(_k, None)

WS = "ws://fake/devtools/page/1"
ESC = "\x1b"
# What a hostile page writes: SGR conceal, OSC 52 (clipboard) ended by BEL, DEL, C1 CSI, a lone CR,
# U+2028, and the characters that stay: tab, CRLF, Turkish letters, an emoji.
CONTENT = "A" + ESC + "[8mB\x07C\x7fD\x9b2JE\u2028F\tG\r\nH\rIşğ🙂"
STATE = {"value": None, "exception": None}


class TTYText(io.StringIO):
    """A text stream that says it is a terminal."""

    def isatty(self):
        return True


def load(path):
    fake = types.ModuleType("websockets")
    fake.connect = lambda url, **kw: None
    sys.modules["websockets"] = fake
    spec = importlib.util.spec_from_file_location("cdpilot_termout_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    async def cdp_send(ws, commands, timeout=15):
        out = {}
        for cid, method, _params in commands:
            if method == "Runtime.evaluate":
                if STATE["exception"] is not None:
                    out[cid] = {"result": {"type": "object", "subtype": "error"},
                                "exceptionDetails": STATE["exception"]}
                else:
                    v = STATE["value"]
                    out[cid] = {"result": {"type": "string" if isinstance(v, str) else "object", "value": v}}
            elif method == "Accessibility.getFullAXTree":
                out[cid] = {"nodes": [{"nodeId": "1", "role": {"value": "button"}, "backendDOMNodeId": 5,
                                       "name": {"value": "Buy" + ESC + "[8mhidden\x9b"}, "properties": []}]}
            else:
                out[cid] = {}
        return out

    async def navigate_collect(ws, url, network=False, console=False, glow=True, har=False):
        events = {"console": [{"type": "log", "text": "c" + ESC + "]0;pwned\x07!"},
                  {"type": "error", "text": "e" + ESC + "[2K\x9b8m"}],
                  "network": [{"status": 404, "url": "https://x.test/" + ESC + "[8m", "type": "XHR"}]}
        return "body " + ESC + "[8mhidden", events

    async def post_nav_probe(ws):
        return {"host": "x.test", "friction": None, "captcha": None}

    async def capture(*a, **k):
        return None

    mod.cdp_send = cdp_send
    mod.get_page_ws = lambda *a, **k: (WS, {"url": "https://x.test/", "title": "Pg" + ESC + "]0;pwned\x07"})
    mod.get_tabs = lambda *a, **k: [
        {"type": "page", "id": "T1", "title": "Tab" + ESC + "[8mhidden\x9b", "url": "https://x.test/a" + ESC + "[2J"}]
    mod.navigate_collect = navigate_collect
    mod._post_nav_probe = post_nav_probe
    mod._capture = capture
    return mod


def run(mod, fn, *args, tty=True):
    """{res, stdout, stderr}: res = ['ok', None] or ['exit', code]."""
    cls = TTYText if tty else io.StringIO
    out, err = cls(), cls()
    mod._SHADOW_NOTES_PRINTED.clear()  # one note per selector and process: each run is its own process
    res = ["ok", None]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            r = fn(*args)
            if asyncio.iscoroutine(r):
                asyncio.run(r)
        except SystemExit as e:
            res = ["exit", e.code]
    return {"res": res, "stdout": out.getvalue(), "stderr": err.getvalue()}


def both(mod, fn, *args, setup=None):
    """The same call on a terminal and piped."""
    got = {}
    for tag, tty in (("tty", True), ("pipe", False)):
        if setup:
            setup()
        got[tag] = run(mod, fn, *args, tty=tty)
    STATE.update(value=None, exception=None)
    return got


def scenario_commands(mod):
    out = {}

    def val(v):
        return lambda: STATE.update(value=v, exception=None)

    out["content"] = both(mod, mod.cmd_content, setup=val(CONTENT))
    out["html"] = both(mod, mod.cmd_html, setup=val("<p>" + ESC + "]52;c;aGk=\x07x</p>"))
    out["go"] = both(mod, mod.cmd_go, "https://x.test/")
    out["network"] = both(mod, mod.cmd_network, "https://x.test/")
    out["a11y"] = both(mod, mod.cmd_a11y, "")
    out["a11y_find"] = both(mod, mod.cmd_a11y, "find button")
    out["a11y_snapshot"] = both(mod, mod.cmd_a11y_snapshot)
    out["describe"] = both(mod, mod.cmd_describe, setup=val(CONTENT))
    out["tabs"] = both(mod, mod.cmd_tabs)
    out["console"] = both(mod, mod.cmd_console, "https://x.test/")
    out["debug"] = both(mod, mod.cmd_debug, "https://x.test/")
    out["storage"] = both(mod, mod.cmd_storage,
                          setup=val(json.dumps({"k" + ESC + "[8m": "v" + ESC + "]52;c;eA==\x07"})))
    out["eval_str"] = both(mod, mod.cmd_eval, "x", setup=val("e" + ESC + "[8mhidden"))
    obj = {"a": "x" + ESC + "y\x7fz\x85w\u2028v", "ş": [1, "🙂"]}
    out["eval_obj"] = both(mod, mod.cmd_eval, "x", setup=val(obj))
    out["eval_obj_expected_pipe"] = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    out["eval_obj_value"] = obj
    out["eval_throw"] = both(mod, mod.cmd_eval, "x", setup=lambda: STATE.update(
        value=None, exception={"text": "Uncaught " + ESC + "[8m", "exception": {"description": "Error: \x9b2J"}}))
    msg = {"msg": "FAIL: Expected text \"ok\" not found in: " + ESC + "[8mhidden", "shadowHost": "div#h" + ESC + "[8m"}
    out["assert"] = both(mod, mod.cmd_assert, "#x", "ok", setup=val(msg))
    out["assert_title"] = both(mod, mod.cmd_assert_title, "t", setup=val("FAIL: Title \"" + ESC + "]0;x\x07\""))
    out["assert_url"] = both(mod, mod.cmd_assert_url, "u", setup=val("FAIL: URL https://x.test/" + ESC + "[8m"))
    out["assert_count"] = both(mod, mod.cmd_assert_count, "#x", "1", setup=val("FAIL: " + ESC + "[8m"))
    out["assert_value"] = both(mod, mod.cmd_assert_value, "#x", "v", setup=val({"msg": "FAIL: got \"" + ESC + "[8m\""}))
    out["assert_attr"] = both(mod, mod.cmd_assert_attr, "#x", "a", "v", setup=val({"msg": "FAIL: " + ESC + "[8m"}))
    out["assert_visible"] = both(mod, mod.cmd_assert_visible, "#x", setup=val({"msg": "FAIL: " + ESC + "[8m"}))
    out["check"] = both(mod, mod.cmd_check, '[{"selector": "#a"}]', setup=val({"msg": "FAIL: Not found: " + ESC + "[8m"}))
    return out


def scenario_webmcp(mod):
    out = {}
    tools = [{"name": "buy" + ESC + "[8m", "title": "Buy" + ESC + "]0;pwned\x07", "description": "d\x9b2J",
              "inputSchema": None}]
    facts = {"url": "https://shop.test/" + ESC + "[8m", "api": True}
    reply = {}

    async def wlist(ws):
        return tools, facts, None, True

    async def weval(ws, js, timeout=15, isolated=True):
        return dict(reply), None
    mod._webmcp_list = wlist
    mod._webmcp_eval = weval
    out["list"] = both(mod, mod.cmd_tools_list)
    out["list_json"] = both(mod, mod.cmd_tools_list, True)
    name = tools[0]["name"]
    reply.update(status="ok", result="plain " + ESC + "[8mhidden")
    out["call_text"] = both(mod, mod.cmd_tools_call, name, {})
    reply.update(status="ok", result=json.dumps({"r": "x\x7fy\x9bz"}, ensure_ascii=False))
    out["call_json"] = both(mod, mod.cmd_tools_call, name, {})
    reply.clear()
    reply.update(status="error", name="E" + ESC + "[8m", message="m" + ESC + "]52;c;eA==\x07")
    out["call_error"] = both(mod, mod.cmd_tools_call, name, {})
    out["not_found"] = both(mod, mod.cmd_tools_call, "nope", {})
    return out


def scenario_reporter(mod):
    """cmd_test's default reporter: the test file's error text comes from the page."""
    import subprocess
    d = tempfile.mkdtemp(prefix="cdpilot-termout-t-")
    f = os.path.join(d, "a.cdpt.js")
    with open(f, "w") as fh:
        fh.write("// fake\n")
    data = {"passed": 1, "failed": 1, "tests": [
        {"name": "ok", "status": "passed", "duration_ms": 1},
        {"name": "t" + ESC + "[8m", "status": "failed", "duration_ms": 2,
         "error": "FAIL: " + ESC + "]52;c;aGk=\x07 got " + ESC + "[8mhidden"}]}
    real = subprocess.run
    subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout=json.dumps(data), stderr="", returncode=1)
    try:
        return both(mod, mod.cmd_test, [f])
    finally:
        subprocess.run = real


def scenario_pty(mod):
    """`content` written to a real pseudo-terminal (no isatty stand-in)."""
    if sys.platform == "win32":
        return {"skipped": True}
    import pty
    import termios
    import threading
    import tty
    master, slave = pty.openpty()
    tty.setraw(slave)  # no CRLF translation: read back the bytes as written
    attrs = termios.tcgetattr(slave)
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    chunks = []

    def drain():
        while True:
            try:
                b = os.read(master, 65536)
            except OSError:
                return
            if not b:
                return
            chunks.append(b)
    t = threading.Thread(target=drain, daemon=True)
    t.start()
    stream = open(slave, "w", encoding="utf-8", closefd=False, newline="")
    STATE.update(value=CONTENT, exception=None)
    with contextlib.redirect_stdout(stream):
        asyncio.run(mod.cmd_content())
        stream.flush()
    stream.close()
    os.close(slave)
    t.join(3)
    with contextlib.suppress(OSError):
        os.close(master)
    STATE.update(value=None)
    return {"isatty": True, "stdout": b"".join(chunks).decode("utf-8", "replace")}


def scenario_daemon(mod):
    """The warm path: the launcher's tty (stdout) and etty (stderr) flags decide."""
    if sys.platform == "win32":
        return {"skipped": True}
    os.environ["CDPILOT_DAEMON"] = "1"
    out = {}
    try:
        STATE.update(value=CONTENT, exception=None)
        for tag, flags in (("tty", {"tty": True, "etty": True}), ("pipe", {"tty": False, "etty": False}),
                           ("none", {})):
            o, e = io.StringIO(), io.StringIO()
            code = mod._daemon_execute(dict(flags, argv=["content"], cwd=os.getcwd(), env=dict(os.environ),
                                            stdin=""), o, e, lambda r: None)
            out["content_" + tag] = {"code": code, "stdout": o.getvalue(), "stderr": e.getvalue()}
        for tag, flags in (("tty", {"tty": True}), ("pipe", {"tty": False})):
            o, e = io.StringIO(), io.StringIO()
            code = mod._daemon_execute(dict(flags, argv=["go", "https://x.test/"], cwd=os.getcwd(),
                                            env=dict(os.environ), stdin=""), o, e, lambda r: None)
            out["go_" + tag] = {"code": code, "stdout": o.getvalue(), "stderr": e.getvalue()}

        async def wlist(ws):
            return [{"name": "t", "inputSchema": None}], {"url": "https://x.test/", "api": True}, None, True

        async def weval(ws, js, timeout=15, isolated=True):
            return {"status": "error", "name": "E", "message": "m" + ESC + "[8mhidden"}, None
        mod._webmcp_list = wlist
        mod._webmcp_eval = weval
        for tag, flags in (("etty", {"tty": False, "etty": True}), ("no_etty", {"tty": True, "etty": False})):
            o, e = io.StringIO(), io.StringIO()
            code = mod._daemon_execute(dict(flags, argv=["tools", "call", "t"], cwd=os.getcwd(),
                                            env=dict(os.environ), stdin=""), o, e, lambda r: None)
            out["tools_" + tag] = {"code": code, "stdout": o.getvalue(), "stderr": e.getvalue()}
        out["flags_left"] = [mod._OUT_TTY, getattr(mod, "_ERR_TTY", None)]
    finally:
        os.environ.pop("CDPILOT_DAEMON", None)
        STATE.update(value=None)
    return out


def scenario_agent_json(mod):
    """_agent_json: DEL, C1 and U+2028 escaped in the JSON text, which still parses to the same value."""
    obj = {"v": "a\x7fb\x85c\x9bd\u2028e\u2029f" + ESC + "g", "t": "Arşivle ✓"}
    out = {"value": obj}
    for tag, mode in (("compact", "compact"), ("pretty", "pretty")):
        os.environ["CDPILOT_JSON"] = mode
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            mod._agent_json(dict(obj))
        out[tag] = o.getvalue()
    os.environ.pop("CDPILOT_JSON", None)
    return out


def scenario_helper(mod):
    """_term_text on its own."""
    f = getattr(mod, "_term_text", None)
    if f is None:
        return {"missing": True}
    cases = {"content": CONTENT, "plain": "Arşivle ✓ 🙂\ttab\nline", "nul": "a\x00b\x1fc\x80d\x9fe",
             "crlf": "a\r\nb\rc\r", "num": 42}
    return {k: f(v) for k, v in cases.items()}


SCENARIOS = {
    "commands": scenario_commands,
    "webmcp": scenario_webmcp,
    "reporter": scenario_reporter,
    "pty": scenario_pty,
    "daemon": scenario_daemon,
    "agent_json": scenario_agent_json,
    "helper": scenario_helper,
}


def main():
    mod = load(sys.argv[1])
    results = {}
    for name in (sys.argv[2:] or list(SCENARIOS)):
        try:
            results[name] = SCENARIOS[name](mod)
        except BaseException:  # noqa: BLE001 - report, keep going
            results[name] = {"error": traceback.format_exc()}
    sys.stdout.write(json.dumps(results, ensure_ascii=True) + "\n")


if __name__ == "__main__":
    main()

"""Fake-CDP harness for the terminal-output tests in test.js (no browser needed).

    python termout_fake.py <path/to/cdpilot.py>

Page text that carries ESC, other C0 controls, DEL and C1 (0x80-0x9F) reaches the
page-text commands (content, html, go, network, a11y, a11y-snapshot, describe, tabs,
console, debug, storage, eval, the assert family, check, wait, wait-for, wait-for-text,
extract, observe, frame eval / shadow, WebMCP tools list / call, the test reporter
and its JUnit output; click, fill, submit, smart-click, dismiss, smart-fill, smart-select,
tab switch / close, the pointer-click note, cookies, eval-batch, multi-eval, tls-check,
friction, captcha-check, twitter analytics, intercept, run and replay). Every command
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


class Utf8Stream(io.TextIOWrapper):
    """A strict UTF-8 text stream, like a real stdout: writing a lone surrogate raises."""

    def __init__(self, tty=False):
        super().__init__(io.BytesIO(), encoding="utf-8", errors="strict", newline="")
        self._tty = tty

    def isatty(self):
        return self._tty

    def getvalue(self):
        self.flush()
        return self.buffer.getvalue().decode("utf-8")


class FakeWS:
    """websockets.connect stand-in: `async with`, send() records, recv() pops `replies`
    (empty: a short wait, then asyncio.TimeoutError, as a quiet socket under wait_for)."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if self.replies:
            r = self.replies.pop(0)
            return r(self.sent) if callable(r) else r
        await asyncio.sleep(0.02)
        raise asyncio.TimeoutError()


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
            elif method == "Network.getCookies":
                out[cid] = {"cookies": [{"name": "sid" + ESC + "[8m", "value": "v" + ESC + "]52;c;eA==\x07\x9b",
                                         "domain": "x.test", "secure": True}]}
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


def run(mod, fn, *args, tty=True, utf8=False):
    """{res, stdout, stderr}: res = ['ok', None] or ['exit', code]. utf8: strict UTF-8 streams."""
    if utf8:
        out, err = Utf8Stream(tty), Utf8Stream(tty)
    else:
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


def both(mod, fn, *args, setup=None, utf8=False):
    """The same call on a terminal and piped."""
    got = {}
    for tag, tty in (("tty", True), ("pipe", False)):
        if setup:
            setup()
        got[tag] = run(mod, fn, *args, tty=tty, utf8=utf8)
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


def scenario_followup(mod):
    """wait, wait-for, wait-for-text, extract, observe, frame eval / shadow."""
    out = {}

    def val(v):
        return lambda: STATE.update(value=v, exception=None)

    out["wait"] = both(mod, mod.cmd_wait, "#x", setup=val({"out": "Found: DIV " + ESC + "[8mhidden"}))
    out["wait_for"] = both(mod, mod.cmd_wait_for, "#x", setup=val({"out": "FOUND: DIV \"" + ESC + "[8m\x9b\""}))
    out["wait_for_text"] = both(mod, mod.cmd_wait_for_text, "t", setup=val("FOUND: \"" + ESC + "]0;x\x07\""))
    out["extract"] = both(mod, mod.cmd_extract, "p", setup=val("row " + ESC + "[8m\x9b2J"))
    out["extract_list"] = both(mod, mod.cmd_extract, "p", "list", setup=val("1. " + ESC + "[2K"))
    rows = [{"tag": "p", "text": "x" + ESC + "y\x7fz\x9bw"}]
    out["extract_json"] = both(mod, mod.cmd_extract, "p", "json", setup=val(json.dumps(rows, ensure_ascii=False)))
    out["extract_json_expected_pipe"] = json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    out["extract_json_value"] = rows
    out["observe"] = both(mod, mod.cmd_observe, setup=val("CLICK  #b  \"" + ESC + "[8mBuy\""))
    out["frame_eval"] = both(mod, mod.cmd_frame, "eval", "x", setup=val("v" + ESC + "[8mhidden"))
    out["frame_shadow"] = both(mod, mod.cmd_frame, "shadow", "#h", setup=val("<p>" + ESC + "]52;c;eA==\x07</p>"))
    return out


EVIL = "Pay" + ESC + "]52;c;eA==\x07" + ESC + "[8m hidden\x9b"
TABS = [{"type": "page", "id": "T1", "title": "Tab" + ESC + "[8mhidden\x9b",
         "url": "https://x.test/a" + ESC + "[2J", "webSocketDebuggerUrl": WS}]


def _stub(mod, **kw):
    """Replace module attributes; returns the function that puts them back."""
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)

    def restore():
        for k, v in old.items():
            setattr(mod, k, v)
    return restore


async def _nothing(*a, **k):
    return None


def scenario_act(mod):
    """click (fast path, frame path, their error lines), fill, submit, smart-click, dismiss,
    smart-fill, smart-select, tab switch / close and the pointer-click note."""
    out = {}

    def val(v):
        return lambda: STATE.update(value=v, exception=None)

    async def ladder(ws, sel, lad):
        return sel, [{"hit": True}]

    frame = {}

    async def frame_cdp(route, commands, timeout=10):
        res = {}
        for cmd in commands:
            cid, method, params = cmd[0], cmd[1], cmd[2]
            decl = params.get("functionDeclaration")
            if method == "Runtime.evaluate":
                res[cid] = {"result": frame["found"]}
            elif decl == mod._CLICK_LABEL_FN:
                res[cid] = {"result": {"value": json.dumps({"res": frame["res"], "box": False})}}
            elif decl == mod._CENTER_FN:
                res[cid] = {"result": {"value": [10, 10, 20, 20]}}
            elif decl == mod._HIT_TEST_FN:  # what covers the target: tag#id.class, page text
                res[cid] = {"result": {"value": "div#x" + ESC + "[8m.c\x9b"}}
            else:
                res[cid] = {"result": {}}
        return res

    ws_mod = sys.modules["websockets"]
    old_connect = ws_mod.connect
    restore = _stub(mod, _resolve_selector_ladder=ladder, _frame_cdp=frame_cdp, cdp_get=lambda *a, **k: [],
                    activate_tab=lambda *a, **k: None, get_tabs=lambda *a, **k: [dict(t) for t in TABS],
                    _frame_route_settle=_nothing, _blocker_pointer=_nothing)
    ws_mod.connect = lambda url, **kw: FakeWS(['{"id": 1, "result": {}}'])
    try:
        # cmd_click(selector, ladder, no_heal, entropy): entropy off = the fast path
        out["click"] = both(mod, mod.cmd_click, "#b", None, False, False, setup=val("Clicked: BUTTON " + EVIL))
        out["click_error"] = both(mod, mod.cmd_click, "#b", None, False, False, setup=lambda: STATE.update(
            value=None, exception={"text": "Uncaught", "exception": {"description": "Error: " + EVIL}}))
        out["click_timeout"] = both(mod, mod.cmd_click, "#b", None, False, False,
                                    setup=val("Timeout waiting for: " + EVIL))
        frame.update(found={"objectId": "o1"}, res="Clicked: BUTTON " + EVIL)
        out["click_frame"] = both(mod, mod.cmd_click, "#b", None, False, True)  # entropy on: the frame path
        frame.update(found={"type": "string", "value": "Timeout waiting for: " + EVIL})
        out["click_frame_missing"] = both(mod, mod.cmd_click, "#b", None, False, True)
        out["fill"] = both(mod, mod.cmd_fill, "#f", "v", None, False, False, setup=val("Filled: INPUT = " + EVIL))
        out["submit"] = both(mod, mod.cmd_submit, "form", setup=val("Submit clicked: " + EVIL))
        out["smart_click"] = both(mod, mod.cmd_smart_click, "Pay", setup=val(json.dumps({
            "found": True, "tag": "button", "text": EVIL, "score": 100, "x": 1, "y": 2,
            "alternatives": ['a "' + EVIL + '" (score:60)']})))
        out["dismiss"] = both(mod, mod.cmd_dismiss, setup=val(json.dumps({
            "found": True, "tag": "button", "text": EVIL, "pattern": "no thanks", "score": 85})))
        out["smart_fill"] = both(mod, mod.cmd_smart_fill, "Email", "v", setup=val(json.dumps({
            "found": True, "tag": "input", "type": "text", "score": 100, "placeholder": EVIL, "name": ""})))
        out["smart_select"] = both(mod, mod.cmd_smart_select, "Size", "L", setup=val(json.dumps({
            "found": True, "optionFound": True, "selected": EVIL, "value": "v" + ESC + "[8m"})))
        out["smart_select_missing"] = both(mod, mod.cmd_smart_select, "Size", "L", setup=val(json.dumps({
            "found": True, "optionFound": False, "available": [EVIL, "M"]})))
        out["tab_switch"] = both(mod, mod.cmd_switch_tab, "0")
        out["tab_close"] = both(mod, mod.cmd_close_tab, "0")
        out["pointer_note"] = both(mod, mod._pointer_click, mod._FrameRoute(WS), "o1", "#b")
    finally:
        restore()
        ws_mod.connect = old_connect
    return out


def scenario_sweep(mod):
    """eval-batch, cookies, multi-eval, tls-check, friction, captcha-check, twitter analytics,
    intercept, run (a script's step output) and replay (a step's error output)."""
    import subprocess
    out = {}

    def val(v):
        return lambda: STATE.update(value=v, exception=None)

    rows = [{"ok": True, "value": "x" + ESC + "y\x7fz\x9bw\u2028v"}]
    out["eval_batch"] = both(mod, mod.cmd_eval_batch, '["document.title"]', setup=val(rows))
    out["eval_batch_value"] = rows
    out["cookies"] = both(mod, mod.cmd_cookies)

    ws_mod = sys.modules["websockets"]
    old_connect = ws_mod.connect
    d = tempfile.mkdtemp(prefix="cdpilot-termout-s-")
    mock = os.path.join(d, "mock.json")
    with open(mock, "w") as fh:
        fh.write("{}")
    script = os.path.join(d, "steps.txt")
    with open(script, "w") as fh:
        fh.write("content\nclick #b\nclick #c\n")
    flow = os.path.join(d, "flow.json")
    with open(flow, "w") as fh:
        json.dump({"cdpilot_flow": 1, "steps": [{"cmd": "click", "args": ["#r"]}]}, fh)
    tw = {"impressions": "1\x9b2", "followers": "5\x7f", "_raw_metrics": ["post " + ESC + "[8m\u2028x"]}

    async def tw_eval(ws, js, *a, **k):
        return dict(tw)

    async def friction(ws, *a, **k):
        return {"level": "none", "signals": [], "detail": "", "error": "TypeError: " + ESC + "[8m\x9b"}

    async def captcha(ws, *a, **k):
        return {"detected": True, "types": ["amazon-classic"],
                "details": [{"type": "amazon-classic", "img_src": "https://x.test/c\x9b\x7f.jpg", "input_id": "c\u2028"}]}

    def paused(url, n):
        return json.dumps({"method": "Fetch.requestPaused",
                           "params": {"requestId": f"r{n}", "request": {"url": url}}})
    real_run = subprocess.run
    steps = {("content",): (0, "body " + ESC + "[8mhidden\x9b", ""),
             ("click", "#b"): (mod.CLICK_MISSED_EXIT_CODE, "", "note: covered by div#x" + ESC + "[8m"),
             ("click", "#c"): (1, "", "Error: " + ESC + "]0;x\x07")}
    restore = _stub(mod, get_tabs=lambda *a, **k: [dict(t) for t in TABS], _tw_navigate=_nothing,
                    _tw_pause=_nothing, _tw_eval=tw_eval, _detect_friction=friction, _detect_captcha=captcha)
    try:
        ws_mod.connect = lambda url, **kw: FakeWS([json.dumps(
            {"id": 1, "result": {"result": {"type": "string", "value": "v" + ESC + "[8m\x9b"}}})])
        out["multi_eval"] = both(mod, mod.cmd_multi_eval, "document.title")
        tls = json.dumps({"tls": {"ja3": "771," + ESC + "[8m", "ja3_hash": "h\x9b", "ja4": "x13d\x7f"},
                          "http2": {"akamai_fingerprint": "2:0\x9b"}}, ensure_ascii=False)
        out["tls_json"] = both(mod, mod.cmd_tls_check, "--json", setup=val(tls))
        out["tls_json_value"] = json.loads(tls)
        out["tls_text"] = both(mod, mod.cmd_tls_check, "--json", setup=val("not json " + ESC + "[8m\x9b"))
        out["tls"] = both(mod, mod.cmd_tls_check, setup=val(tls))
        out["friction"] = both(mod, mod.cmd_friction)
        out["captcha_check"] = both(mod, mod.cmd_captcha_check)
        out["twitter_analytics"] = both(mod, mod.cmd_twitter_analytics)
        mod.INTERCEPT_RULES[:] = [("block", "*blocked*", None), ("headers", "*hdr*", "X-A: 1"),
                                  ("mock", "*mock*", mock)]
        ws_mod.connect = lambda url, **kw: FakeWS([
            '{"id": 1, "result": {}}', paused("https://x.test/blocked" + ESC + "[8m", 1),
            paused("https://x.test/hdr\x9b", 2), paused("https://x.test/mock" + ESC + "]0;x\x07", 3)])
        out["intercept"] = both(mod, mod._run_intercept_session, WS, 0.3)
        mod.INTERCEPT_RULES[:] = []

        def fake_run(cmd, **k):
            code, so, se = steps.get(tuple(cmd[2:]), (1, "", "Error: " + ESC + "[8mhidden\x9b"))
            return types.SimpleNamespace(returncode=code, stdout=so, stderr=se)
        subprocess.run = fake_run
        out["run_script"] = both(mod, mod.cmd_run_script, script)
        out["replay"] = both(mod, mod.cmd_replay, flow)
    finally:
        subprocess.run = real_run
        mod.INTERCEPT_RULES[:] = []
        ws_mod.connect = old_connect
        restore()
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


def _reporter(mod, reporter, tail="", name="t" + ESC + "[8m", utf8=False):
    """cmd_test with one reporter: the test file's error text comes from the page."""
    import subprocess
    d = tempfile.mkdtemp(prefix="cdpilot-termout-t-")
    f = os.path.join(d, "a.cdpt.js")
    with open(f, "w") as fh:
        fh.write("// fake\n")
    data = {"passed": 1, "failed": 1, "tests": [
        {"name": "ok", "status": "passed", "duration_ms": 1},
        {"name": name, "status": "failed", "duration_ms": 2,
         "error": "FAIL: " + ESC + "]52;c;aGk=\x07 got " + ESC + "[8mhidden" + tail}]}
    real = subprocess.run
    subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout=json.dumps(data), stderr="", returncode=1)
    try:
        return both(mod, mod.cmd_test, [f], False, 1, reporter, utf8=utf8)
    finally:
        subprocess.run = real


def scenario_reporter(mod):
    """The default reporter."""
    return _reporter(mod, "default")


def scenario_reporter_junit(mod):
    """The JUnit reporter: XML 1.0 has no control characters, so its output must parse either way."""
    import xml.etree.ElementTree as ET
    # the test name is the test author's (not page text) and stays as it is
    got = _reporter(mod, "junit", "\x9b\x7f\x01 & <b>", name="checkout works")
    for tag in ("tty", "pipe"):
        try:
            root = ET.fromstring(got[tag]["stdout"])
            got[tag]["failure"] = [e.text for e in root.iter("failure")]
            got[tag]["xml_ok"] = True
        except ET.ParseError as e:
            got[tag]["xml_ok"] = str(e)
    return got


def scenario_reporter_junit_name(mod):
    """A test name with ", & and < (the author's text) is escaped as an XML attribute."""
    import xml.etree.ElementTree as ET
    got = _reporter(mod, "junit", name='checkout "a" & <b>')
    out = {"stdout": got["pipe"]["stdout"]}
    try:
        root = ET.fromstring(got["pipe"]["stdout"])
        out["names"] = [e.get("name") for e in root.iter("testcase")]
        out["xml_ok"] = True
    except ET.ParseError as e:
        out["xml_ok"] = str(e)
    return out


def scenario_reporter_junit_codepoints(mod):
    """JUnit: U+FFFE, U+FFFF and lone surrogates (invalid in XML 1.0) in the error text and the
    name, written to strict UTF-8 streams (a real stdout raises on a lone surrogate)."""
    import xml.etree.ElementTree as ET
    # surrogates apart: an adjacent high + low pair would decode as one character
    odd = "\ufffe" + "a" + "\uffff" + "b" + chr(0xD800) + "c" + chr(0xDFFF)
    try:
        got = _reporter(mod, "junit", odd, name="n" + odd, utf8=True)
    except Exception as e:  # noqa: BLE001 - the old writer raised UnicodeEncodeError in print
        return {"raised": f"{type(e).__name__}: {e}"}
    for tag in ("tty", "pipe"):
        try:
            root = ET.fromstring(got[tag]["stdout"])
            got[tag]["failure"] = [e.text for e in root.iter("failure")]
            got[tag]["names"] = [e.get("name") for e in root.iter("testcase")]
            got[tag]["xml_ok"] = True
        except (ET.ParseError, UnicodeError) as e:
            got[tag]["xml_ok"] = f"{type(e).__name__}: {e}"
    return got


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
    "followup": scenario_followup,
    "act": scenario_act,
    "sweep": scenario_sweep,
    "webmcp": scenario_webmcp,
    "reporter": scenario_reporter,
    "reporter_junit": scenario_reporter_junit,
    "reporter_junit_name": scenario_reporter_junit_name,
    "reporter_junit_codepoints": scenario_reporter_junit_codepoints,
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

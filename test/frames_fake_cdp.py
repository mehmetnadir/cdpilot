"""Fake-CDP harness for the iframe tests in test.js (no browser needed).

    python frames_fake_cdp.py <path/to/cdpilot.py>

Loads cdpilot.py with a stand-in `websockets` module whose sockets answer
CDP from an in-memory frame tree (same-process frames with their own
execution contexts, out-of-process frames reached through flat sessions).
The real cdp_send, WS pool, frame route, rewrite and frame-search code run
unchanged; only the wire is fake. Prints one JSON object {scenario: result};
a scenario that raises reports {"error": traceback}.
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import re
import sys
import time
import traceback
import types

WS = "ws://fake/devtools/page/1"
STATE = {"browser": None}


class Frame:
    """A document in a frame, plus the <iframe> element that owns it."""

    def __init__(self, fid, origin="http://a.test", oop=False, elem_id="", name="",
                 src="", visible=True, box=(0, 0), finder=None, slow=False, children=()):
        self.fid, self.origin, self.oop = fid, origin, oop
        self.elem_id, self.name, self.src, self.visible = elem_id, name, src, visible
        self.box, self.finder, self.slow = box, finder or {}, slow
        self.children = list(children)
        self.ctx = None


class Transport:
    def __init__(self):
        self.closed = False

    def is_closing(self):
        return self.closed

    def close(self):
        self.closed = True


class Browser:
    def __init__(self, mod, top):
        self.mod, self.top = mod, top
        self.frames, self.ctx, self.sessions = {}, {}, {}
        self.log, self.finder, self.mouse = [], [], []
        self.attached, self.detached, self.sockets = [], [], []
        self.cancel_on = None
        seq = [100]

        def walk(f):
            seq[0] += 1
            f.ctx = seq[0]
            self.frames[f.fid], self.ctx[f.ctx] = f, f
            for c in f.children:
                walk(c)
        walk(top)

    def process(self, root):
        """Frames sharing root's renderer (children that are not OOPIFs)."""
        out = [root]
        for c in root.children:
            if not c.oop:
                out.extend(self.process(c))
        return out

    def owner(self, oid):
        if isinstance(oid, str) and oid.startswith("owner:"):
            return self.frames.get(oid[len("owner:"):])
        return None

    def find_owner(self, frame, kind, value):
        kids = frame.children
        if kind == "index":
            return kids[value] if 0 <= value < len(kids) else None
        for c in kids:
            if value == "iframe" or (c.elem_id and value in ("#" + c.elem_id, "iframe#" + c.elem_id)):
                return c
        for c in kids:
            if value and value in (c.name, c.elem_id):
                return c
        if kind != "sel":
            for c in kids:
                if c.src and value in c.src:
                    return c
        return None

    def handle(self, msg):
        mid, method = msg["id"], msg["method"]
        p = msg.get("params") or {}
        sid = msg.get("sessionId")
        tag = {"sessionId": sid} if sid else {}

        def ok(result):
            return [dict({"id": mid, "result": result}, **tag)]

        def err(text):
            return [dict({"id": mid, "error": {"code": -32000, "message": text}}, **tag)]

        if sid and sid not in self.sessions:
            return err("Session with given id not found.")
        root = self.sessions[sid] if sid else self.top
        if method == "Runtime.enable":
            events = [dict({"method": "Runtime.executionContextCreated", "params": {"context": {
                "id": f.ctx, "origin": f.origin, "auxData": {"frameId": f.fid, "isDefault": True}}}}, **tag)
                for f in self.process(root)]
            return events + ok({})
        if method == "Target.attachToTarget":
            f = self.frames.get(p.get("targetId"))
            if f is None or not f.oop:
                return err("No target with given id found")
            new = "S-" + f.fid
            self.sessions[new] = f
            self.attached.append(f.fid)
            return ok({"sessionId": new})
        if method == "Target.detachFromTarget":
            self.detached.append(p.get("sessionId"))
            self.sessions.pop(p.get("sessionId"), None)
            return ok({})
        if method == "DOM.describeNode":
            f = self.owner(p.get("objectId"))
            if f is None:
                return err("Could not find node with given id")
            return ok({"node": {"nodeName": "IFRAME", "frameId": f.fid,
                                "attributes": ["id", f.elem_id, "src", f.src]}})
        if method == "Runtime.callFunctionOn":
            f = self.owner(p.get("objectId"))
            if f is None:
                return err("Could not find object with given id")
            return ok({"result": {"type": "object", "value": list(f.box)}})
        if method == "Input.dispatchMouseEvent":
            self.mouse.append([p.get("type"), p.get("x"), p.get("y")])
            return ok({})
        if method == "Runtime.evaluate":
            frame = root
            if "contextId" in p:
                frame = self.ctx.get(p["contextId"])
                if frame is None or frame not in self.process(root):
                    return err("Cannot find context with specified id")
            return self.evaluate(frame, p.get("expression", ""), ok)
        return ok({})

    def evaluate(self, frame, expr, ok):
        def value(v):
            return ok({"result": {"type": "object" if isinstance(v, list) else "string", "value": v}})

        owner_call = "(" + self.mod._FRAME_OWNER_JS + ")("
        if expr.startswith(owner_call):
            kind, val, _scroll = json.loads("[" + expr[len(owner_call):-1] + "]")
            f = self.find_owner(frame, kind, val)
            if f is None:
                return ok({"result": {"type": "object", "subtype": "null", "value": None}})
            return ok({"result": {"type": "object", "subtype": "node", "className": "HTMLIFrameElement",
                                  "description": "iframe#" + f.elem_id if f.elem_id else "iframe",
                                  "objectId": "owner:" + f.fid}})
        if expr == self.mod._FRAME_LIST_JS:
            return value([{"index": i, "src": c.src or "(no source)", "name": c.name, "id": c.elem_id,
                           "visible": c.visible} for i, c in enumerate(frame.children)])
        if "var iframes = document.querySelectorAll('iframe');" in expr:  # `frame list`, top page
            return value([{"index": i, "src": c.src or "(no source)", "name": c.name, "id": c.elem_id}
                          for i, c in enumerate(frame.children)])
        if expr == "location.origin":
            return value(frame.origin)
        if "FINDER" in expr:  # a smart-* finder script
            m = re.match(r'\(location\.origin === ("(?:[^"\\]|\\.)*")\) \? ', expr)
            if m and json.loads(m.group(1)) != frame.origin:
                self.finder.append([frame.fid, "guarded"])
                return value(json.dumps({"found": False, "crossOrigin": True}))
            mode = "strict" if "__cdpilotMinScore" in expr else "loose"
            self.finder.append([frame.fid, mode])
            if frame.slow:
                return []  # never answers
            return value(json.dumps(frame.finder.get(mode, {"found": False})))
        if expr == "HANG":
            return []
        if expr.startswith("WHERE:"):
            return value(frame.fid + "|" + expr[len("WHERE:"):])
        return ok({"result": {"type": "undefined"}})


class FakeWS:
    def __init__(self, browser):
        self.b = browser
        self._closed = False
        self.transport = Transport()
        self.q = asyncio.Queue()
        browser.sockets.append(self)

    @property
    def closed(self):
        return self._closed or self.transport.closed

    async def send(self, text):
        msg = json.loads(text)
        self.b.log.append(msg)
        if self.b.cancel_on == msg.get("method"):
            raise asyncio.CancelledError()
        for payload in self.b.handle(msg):
            self.q.put_nowait(json.dumps(payload))

    async def recv(self):
        return await self.q.get()

    async def close(self):
        self._closed = True
        self.transport.close()


class Connect:
    """websockets.connect(): awaitable, or an async context manager."""

    def __init__(self):
        self.ws = None

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
    spec = importlib.util.spec_from_file_location("cdpilot_frames_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.get_page_ws = lambda *a, **k: (WS, {})
    return mod


def run(mod, top, body, pool=True):
    """Run coroutine factory `body(browser)` against a fresh fake page."""
    b = Browser(mod, top)
    STATE["browser"] = b
    mod._WS_POOL.clear()
    mod._WS_LOCKS.clear()
    mod._FRAME_FLAG = None
    mod._WS_POOL_ENABLED = pool
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        res = asyncio.run(body(b))
    mod._FRAME_FLAG = None
    return b, res, out.getvalue(), err.getvalue()


async def call(fn, *args):
    """Await fn(*args): ['ok', value] or ['exit', code] / ['raise', name]."""
    try:
        return ["ok", await fn(*args)]
    except SystemExit as e:
        return ["exit", e.code]
    except BaseException as e:  # noqa: BLE001 - CancelledError is the point
        return ["raise", type(e).__name__]


def probe_command(mod, seen):
    """A frame-aware element command: evaluates, then clicks at (1, 2)."""
    async def probe(target):
        seen.append({"target": target, "routed": mod._FRAME_ROUTE.get() is not None,
                     "pool": mod._WS_POOL_ENABLED})
        ws, _ = mod.get_page_ws()
        r = await mod.cdp_send(ws, [
            (1, "Runtime.evaluate", {"expression": "WHERE:" + target, "returnByValue": True}),
            (2, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": 1, "y": 2, "button": "left"}),
        ])
        return r.get(1, {}).get("result", {}).get("value")
    return mod._frame_aware("css")(probe)


def failing_command(mod, seen, how):
    async def fail(target):
        seen.append({"target": target, "routed": mod._FRAME_ROUTE.get() is not None,
                     "pool": mod._WS_POOL_ENABLED})
        ws, _ = mod.get_page_ws()
        await mod.cdp_send(ws, [(1, "Runtime.evaluate", {"expression": "WHERE:" + target})])
        if how == "exit1":
            print(f"Error: selector '{target}' not resolved.", file=sys.stderr)
            sys.exit(1)
        if how == "exit3":
            sys.exit(3)
        raise RuntimeError("boom")
    return mod._frame_aware("css")(fail)


def page_tree():
    return Frame("top", children=[
        Frame("card", elem_id="card", name="card-frame", src="http://a.test/inner.html",
              box=(100, 1000), children=[Frame("nested", elem_id="nested", box=(10, 20))]),
        Frame("pay", origin="http://b.test", oop=True, elem_id="pay",
              src="http://b.test/pay.html", box=(5, 7)),
    ])


def scenario_routing(mod):
    """>>> and --frame reach same-process and out-of-process frames."""
    seen = []
    cmd = probe_command(mod, seen)

    async def body(b):
        out = {}
        for key, target, flag in [
            ("css", "#card >>> #btn", None),
            ("nested", "iframe#card >>> #nested >>> #deep", None),
            ("oopif", "#pay >>> #cc", None),
            ("flag_index", "#cc", "1"),
            ("flag_src", "#cc", "pay.html"),
            ("arrow_src_word", "pay.html >>> #cc", None),
        ]:
            mod._FRAME_FLAG = flag
            start = len(b.log)
            res = await call(cmd, target)
            where = [m for m in b.log[start:] if str(m.get("params", {}).get("expression", "")).startswith("WHERE:")]
            out[key] = {"res": res, "mouse": b.mouse[-1], "session": where[-1].get("sessionId"),
                        "context": where[-1]["params"].get("contextId")}
        mod._FRAME_FLAG = None
        out["attached"], out["detached"], out["open_sessions"] = b.attached, b.detached, sorted(b.sessions)
        out["contexts"] = {f: b.frames[f].ctx for f in ("card", "nested")}
        return out

    _, res, _, err = run(mod, page_tree(), body)
    res["stderr"] = err
    res["seen"] = seen
    return res


def scenario_literal(mod):
    """A `>>>` whose first hop is no iframe is a plain selector / text."""
    seen = []
    ok_cmd, fail_cmd = probe_command(mod, seen), failing_command(mod, seen, "exit1")

    async def body(b):
        out = {}
        for key, fn, target, flag in [
            ("next", ok_cmd, "Next >>>", None),
            ("home", ok_cmd, "Home >>> Products", None),
            ("page_of", ok_cmd, "Page 1 of 3 >>> Next page", None),
            ("fail_nope", fail_cmd, "#nope >>> #x", None),
            ("fail_plain", fail_cmd, "Next >>>", None),
            ("flag_strict", ok_cmd, "#x", "#nope"),
            ("later_hop_strict", ok_cmd, "#card >>> #missing >>> #x", None),
        ]:
            mod._FRAME_FLAG = flag
            start, err_start = len(b.log), len(sys.stderr.getvalue())
            res = await call(fn, target)
            out[key] = {"res": res, "messages": [m["method"] for m in b.log[start:]],
                        "stderr": sys.stderr.getvalue()[err_start:]}
        mod._FRAME_FLAG = None
        return out

    _, res, _, _ = run(mod, page_tree(), body)
    res["seen"] = seen
    return res


def scenario_pool_restore(mod):
    """CDPILOT_WS_POOL=0: the route pins the pool on, then restores it."""
    seen = []
    cases = [
        ("exception", failing_command(mod, seen, "raise"), "#card >>> #x", None, None),
        ("system_exit", failing_command(mod, seen, "exit3"), "#pay >>> #x", None, None),
        ("frame_error", probe_command(mod, seen), "#x", "#nope", None),
        ("cancel_in_close", probe_command(mod, seen), "#pay >>> #cc", None, "Target.detachFromTarget"),
        ("literal", probe_command(mod, seen), "Home >>> Products", None, None),
    ]
    out = {}
    for key, fn, target, flag, cancel_on in cases:
        async def body(b, fn=fn, target=target, flag=flag, cancel_on=cancel_on):
            mod._FRAME_FLAG = flag
            b.cancel_on = cancel_on
            res = await call(fn, target)
            mod._FRAME_FLAG = None
            return res
        b, res, _, err = run(mod, page_tree(), body, pool=False)
        out[key] = {"res": res, "pool_after": mod._WS_POOL_ENABLED, "pooled_after": WS in mod._WS_POOL,
                    "sockets": len(b.sockets), "all_closed": all(s.closed for s in b.sockets),
                    "stderr": err}
    out["pool_inside"] = [s["pool"] for s in seen]
    return out


def two_level_page(finders, same_site_xo=True):
    """top + card (same origin) + xo (other origin, same process) + pay (OOPIF)."""
    return Frame("top", finder=finders.get("top"), children=[
        Frame("card", elem_id="card", src="http://a.test/inner.html", box=(100, 1000),
              finder=finders.get("card")),
        Frame("xo", origin="http://c.test", oop=not same_site_xo, elem_id="xo",
              src="http://c.test/widget.html", box=(300, 50), finder=finders.get("xo")),
        Frame("pay", origin="http://b.test", oop=True, elem_id="pay", src="http://b.test/pay.html",
              box=(5, 7), finder=finders.get("pay")),
    ])


def scenario_smart_order(mod):
    """_smart_eval: page real match > page disabled-only > frames > page weak."""
    found = {"found": True, "x": 5, "y": 6}
    weak = {"found": False, "weakScore": 35}
    page_loose = {"found": True, "x": 1, "y": 1, "weak": True}
    cases = {
        "c_page_real": ({"top": {"strict": {"found": True, "x": 9, "y": 9}}, "card": {"strict": found}}, False),
        "d_disabled_only": ({"top": {"strict": {"found": False, "disabledReal": 1},
                                     "loose": {"found": False, "disabled": 1}},
                             "card": {"strict": found}}, False),
        "e_frame_real": ({"top": {"strict": weak, "loose": page_loose}, "card": {"strict": found}}, False),
        "e_nothing": ({"top": {"strict": weak, "loose": page_loose}}, False),
        "e_oopif_all": ({"top": {"strict": weak, "loose": page_loose}, "pay": {"strict": found}}, False),
        "fill_same_origin": ({"top": {"strict": {"found": False}}, "card": {"strict": found}}, True),
        "fill_cross_origin": ({"top": {"strict": {"found": False}, "loose": {"found": False}},
                               "xo": {"strict": found}, "pay": {"strict": found}}, True),
    }
    out = {}
    for key, (finders, same_origin_only) in cases.items():
        async def body(b, same_origin_only=same_origin_only):
            raw = await mod._smart_eval(WS, "FINDER", "smart-x", same_origin_only=same_origin_only)
            return json.loads(raw) if raw else raw
        b, res, _, err = run(mod, two_level_page(finders), body)
        lists = sum(1 for m in b.log if m.get("params", {}).get("expression") == mod._FRAME_LIST_JS)
        out[key] = {"res": res, "finder": b.finder, "attached": b.attached, "frame_lists": lists,
                    "stderr": err, "open_sessions": sorted(b.sessions)}
    return out


def scenario_budget(mod):
    """A frame that never answers costs the budget, not 10 s per call."""
    top = Frame("top", finder={"strict": {"found": False, "weakScore": 35},
                               "loose": {"found": True, "x": 1, "y": 1, "weak": True}}, children=[
        Frame("slow", elem_id="slow", slow=True, box=(0, 0)),
        Frame("a", elem_id="a", finder={"strict": {"found": True, "x": 1, "y": 1}}),
        Frame("b", elem_id="b"),
    ])
    calls = []
    real_send = mod.cdp_send

    async def spy(ws_url, commands, timeout=15):
        calls.append({"methods": [c[1] for c in commands], "timeout": timeout,
                      "finder": any("FINDER" in str((c[2] or {}).get("expression", "")) for c in commands)})
        return await real_send(ws_url, commands, timeout)

    out = {}
    mod.cdp_send = spy
    try:
        async def direct(b):
            strict = f"(function () {{ var __cdpilotMinScore = {mod.SMART_STRONG_SCORE}; return (FINDER); }})()"
            t0 = time.monotonic()
            hit = await mod._frame_search(WS, strict, "smart-x", budget_s=0.5)
            return {"hit": hit, "elapsed": time.monotonic() - t0,
                    "socket_kept": WS in mod._WS_POOL and not mod._WS_POOL[WS].closed}
        b, res, _, err = run(mod, top, direct)
        res.update({"stderr": err, "finder": b.finder, "calls": calls[:]})
        out["direct"] = res

        del calls[:]

        async def via_smart_eval(b):
            t0 = time.monotonic()
            raw = await mod._smart_eval(WS, "FINDER", "smart-x")
            return {"res": json.loads(raw), "elapsed": time.monotonic() - t0}
        b, res, _, err = run(mod, top, via_smart_eval)
        res.update({"stderr": err, "finder": b.finder,
                    "max_search_timeout": max(c["timeout"] for c in calls[1:-1])})
        out["default_budget"] = res
    finally:
        mod.cdp_send = real_send
    return out


def scenario_keep_socket(mod):
    """_frame_cdp timeouts keep the pooled socket; plain cdp_send drops it."""
    async def body(b):
        route = mod._FrameRoute(WS)
        await mod._frame_cdp(route, [(1, "Runtime.evaluate", {"expression": "WHERE:prime"})])
        sock = mod._WS_POOL[WS]
        t0 = time.monotonic()
        await mod._frame_cdp(route, [(1, "Runtime.evaluate", {"expression": "HANG"})], timeout=0.3)
        frame_elapsed = time.monotonic() - t0
        kept = mod._WS_POOL.get(WS) is sock and not sock.closed
        again = await mod._frame_cdp(route, [(1, "Runtime.evaluate", {"expression": "WHERE:again"})])
        t0 = time.monotonic()
        await mod.cdp_send(WS, [(1, "Runtime.evaluate", {"expression": "HANG"})], timeout=0.3)
        plain_elapsed = time.monotonic() - t0
        return {"frame_elapsed": frame_elapsed, "kept": kept,
                "again": again.get(1, {}).get("result", {}).get("value"),
                "plain_elapsed": plain_elapsed, "dropped": WS not in mod._WS_POOL, "closed": sock.closed}
    b, res, _, _ = run(mod, Frame("top"), body)
    res["sockets"] = len(b.sockets)
    return res


def scenario_frame_list(mod):
    """`frame list` without --frame keeps its old output; --frame lists inside."""
    top = Frame("top", children=[
        Frame("hidden", elem_id="hidden-frame", src="about:blank", visible=False),
        Frame("card", elem_id="card", name="card-frame", src="http://a.test/inner.html", children=[
            Frame("nested", elem_id="nested", src="http://a.test/nested.html"),
            Frame("ghost", elem_id="ghost", visible=False),
        ]),
    ])
    out = {}
    for key, args in [("top", ("list",)), ("inside", ("list", "--frame", "#card")),
                      ("eval_inside", ("eval", "--frame", "card-frame", "WHERE:z")),
                      ("eval_top", ("eval", "WHERE:z"))]:
        async def body(b, args=args):
            return await call(mod.cmd_frame, *args)
        _, res, stdout, err = run(mod, top, body)
        out[key] = {"res": res, "stdout": stdout, "stderr": err}
    return out


def scenario_commands(mod):
    """Which loaded commands resolve `>>>` / `--frame`, and how."""
    names = ["cmd_click", "cmd_fill", "cmd_submit", "cmd_hover", "cmd_dblclick", "cmd_rightclick",
             "cmd_smart_click", "cmd_smart_fill", "cmd_smart_select"]
    return {"kinds": {n: getattr(getattr(mod, n), "frame_aware", None) for n in names},
            "cli": sorted(mod.FRAME_AWARE_CMDS),
            "limits": [mod.FRAME_SEARCH_MAX_FRAMES, mod.FRAME_SEARCH_BUDGET_S, mod.SMART_STRONG_SCORE]}


SCENARIOS = {
    "commands": scenario_commands,
    "routing": scenario_routing,
    "literal": scenario_literal,
    "pool_restore": scenario_pool_restore,
    "smart_order": scenario_smart_order,
    "budget": scenario_budget,
    "keep_socket": scenario_keep_socket,
    "frame_list": scenario_frame_list,
}


def main():
    mod = load(sys.argv[1])
    wanted = sys.argv[2:] or list(SCENARIOS)
    results = {}
    for name in wanted:
        try:
            results[name] = SCENARIOS[name](mod)
        except BaseException:  # noqa: BLE001 - report, keep going
            results[name] = {"error": traceback.format_exc()}
    sys.stdout.write(json.dumps(results) + "\n")


if __name__ == "__main__":
    main()

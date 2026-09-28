"""Fake-CDP harness for the iframe tests in test.js (no browser needed).

    python frames_fake_cdp.py <path/to/cdpilot.py>

Loads cdpilot.py with a stand-in `websockets` module whose sockets answer
CDP from an in-memory frame tree (same-process frames with their own
execution contexts, out-of-process frames reached through flat sessions).
The real cdp_send, WS pool, frame route, rewrite and frame-search code run
unchanged; only the wire is fake. A smart-* finder is the expression
"FINDER" (wrapped by _smart_wrap): the fake answers per frame and mode
(probe / strict / loose) and records an "act" whenever a non-probe finder
reports found (the real finder clicks or types right there). cmd_click's
own script (the `__cdpilot_waitFor(` one) finds one element "el:<frame>:<sel>"
with its centre at (40, 50) of its frame ("#nobox": no box); the real-click
helpers (_CENTER_FN, _HIT_TEST_FN, _SCRIPT_CLICK_FN, cdpilot's input blocker,
the settle wait) are answered from per-frame settings. Prints one JSON object
{scenario: result}; a scenario that raises reports {"error": traceback}.
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
STATE = {"browser": None, "methods": {}, "released": {}}  # every CDP method sent / object
# group released, over all scenarios


class Frame:
    """A document in a frame, plus the <iframe> element that owns it."""

    def __init__(self, fid, origin="http://a.test", oop=False, elem_id="", name="",
                 src="", visible=True, box=(0, 0), finder=None, slow=False, children=(),
                 wrappers=(), scale=1.0):
        self.fid, self.origin, self.oop = fid, origin, oop
        self.wrappers = list(wrappers)  # selectors of elements around the <iframe>
        self.elem_id, self.name, self.src, self.visible = elem_id, name, src, visible
        self.box, self.finder, self.slow = box, finder or {}, slow
        self.children = list(children)
        self.ctx = None
        self.scale = scale        # the <iframe>'s rendered / layout size
        self.covered = ""         # what covers this frame's <iframe> at the click point
        self.target_cover = ""    # what covers the click target inside this frame
        self.settle_hang = False  # the settle wait in this frame never answers


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
        self.log, self.finder, self.mouse, self.acts = [], [], [], []
        self.act_real = []        # per act: did the finder get __cdpilotRealClick?
        self.clicks = []          # [frame, "script"]: an el.click() cdpilot caused
        self.leaks = []           # scripts that put a helper on window
        self.hits = []            # hit-tests: [objectId, x, y]
        self.settles = []         # settle waits: [frame, context is an isolated world]
        self.blocker = False      # the top page has cdpilot's input blocker
        self.blocker_log = []     # pointer-events values set on it, in order
        self.fail_on = None       # a CDP method whose send raises RuntimeError
        self.arrays = {}          # smart-click real-click results: [JSON, element]
        self.attached, self.detached, self.sockets = [], [], []
        self.cancel_on = None
        self.opaque_ids = False   # remote-object ids without "<isolate>.<context>.<n>"
        self.isolated = set()     # context ids made by Page.createIsolatedWorld
        self.next_ctx = [900]
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
        """(child frame or None, matched through a wrapper element?)"""
        kids = frame.children
        if kind == "index":
            return (kids[value] if 0 <= value < len(kids) else None), False
        for c in kids:
            if value == "iframe" or (c.elem_id and value in ("#" + c.elem_id, "iframe#" + c.elem_id)):
                return c, False
        for c in kids:
            if value in c.wrappers:
                return c, True
        for c in kids:
            if value and value in (c.name, c.elem_id):
                return c, False
        if kind != "sel":
            for c in kids:
                if c.src and value in c.src:
                    return c, False
        return None, False

    def answer(self, frame, mode):
        f = frame.finder
        if mode == "probe" and "probe" not in f:
            s = f.get("strict", {"found": False})
            return {"found": True, "probe": True, "score": 100} if s.get("found") else s
        return f.get(mode, {"found": False})

    def handle(self, msg):
        mid, method = msg["id"], msg["method"]
        p = msg.get("params") or {}
        sid = msg.get("sessionId")
        tag = {"sessionId": sid} if sid else {}

        def ok(result):
            return [dict({"id": mid, "result": result}, **tag)]

        def err(text):
            return [dict({"id": mid, "error": {"code": -32000, "message": text}}, **tag)]

        STATE["methods"][method] = STATE["methods"].get(method, 0) + 1
        if sid and sid not in self.sessions:
            return err("Session with given id not found.")
        root = self.sessions[sid] if sid else self.top
        if method == "DOM.resolveNode":  # the frame document, in its main world
            f = self.ctx.get(p.get("backendNodeId", 0) - 5000)
            if f is None or f not in self.process(root):
                return err("No node with given id found")
            oid = ("opaque-" + f.fid) if self.opaque_ids else "-77.%d.1" % f.ctx
            return ok({"object": {"type": "object", "subtype": "node", "className": "HTMLDocument",
                                  "description": "#document", "objectId": oid}})
        if method == "Page.createIsolatedWorld":
            f = self.frames.get(p.get("frameId"))
            if f is None or f not in self.process(root):
                return err("No frame for given id found")
            self.next_ctx[0] += 1
            self.ctx[self.next_ctx[0]], self.isolated = f, self.isolated | {self.next_ctx[0]}
            return ok({"executionContextId": self.next_ctx[0]})
        if method == "Runtime.releaseObjectGroup":
            g = p.get("objectGroup")
            STATE["released"][g] = STATE["released"].get(g, 0) + 1
            return ok({})
        if method == "Page.getFrameTree":
            return ok({"frameTree": {"frame": {"id": root.fid}}})
        if method == "Runtime.evaluate" and p.get("expression") == "document":
            ctx = p.get("contextId", root.ctx)
            f = self.ctx.get(ctx)
            if f is None or f not in self.process(root):
                return err("Cannot find context with specified id")
            return ok({"result": {"type": "object", "subtype": "node", "objectId": "doc.%d" % ctx}})
        if method == "Runtime.callFunctionOn" and "this === d" in p.get("functionDeclaration", ""):
            main = str(p.get("objectId", "")).split(".")
            arg = str(((p.get("arguments") or [{}])[0]).get("objectId", "")).split(".")
            if len(main) != 3 or len(arg) != 2:
                return err("Could not find object with given id")
            if main[1] != arg[1]:  # another context: another world or frame
                return err("Argument should belong to the same JavaScript world as target object")
            return ok({"result": {"type": "boolean", "value": True}})
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
            node = {"nodeName": "IFRAME", "frameId": f.fid, "attributes": ["id", f.elem_id, "src", f.src]}
            if not f.oop:  # a local frame's document is part of the node
                node["contentDocument"] = {"nodeName": "#document", "backendNodeId": 5000 + f.ctx}
            return ok({"node": node})
        if method == "Runtime.callFunctionOn":
            return self.call_function(p, ok, err)
        if method == "Input.dispatchMouseEvent":
            self.mouse.append([p.get("type"), p.get("x"), p.get("y")])
            return ok({})
        if method == "Runtime.evaluate":
            frame = root
            if "contextId" in p:
                frame = self.ctx.get(p["contextId"])
                if frame is None or frame not in self.process(root):
                    return err("Cannot find context with specified id")
            return self.evaluate(frame, p.get("expression", ""), ok, p)
        return ok({})

    def element(self, oid):
        """(frame, selector) of an "el:<frame>:<selector>" object id, else None."""
        parts = str(oid).split(":", 2)
        if len(parts) == 3 and parts[0] == "el" and parts[1] in self.frames:
            return self.frames[parts[1]], parts[2]
        return None

    def call_function(self, p, ok, err):
        fd, oid, mod = p.get("functionDeclaration", ""), p.get("objectId"), self.mod
        args = [a.get("value") for a in p.get("arguments") or []]

        def value(v):
            return ok({"result": {"type": "object" if isinstance(v, list) else "string", "value": v}})
        if fd == mod._HIT_TEST_FN:
            self.hits.append([oid] + args)
            f = self.owner(oid)
            if f is not None:
                return value(f.covered)
            el = self.element(oid)
            return value(el[0].target_cover) if el else err("Could not find object with given id")
        el = self.element(oid)
        if el is not None:
            f, sel = el
            if fd == mod._CENTER_FN:
                return value([40, 50, 20, 10])
            if fd == mod._CLICK_LABEL_FN:
                return value(json.dumps({"res": "Clicked: BUTTON " + sel, "box": not sel.endswith("#nobox")}))
            if fd == mod._SCRIPT_CLICK_FN:
                self.clicks.append([f.fid, "script"])
                return ok({"result": {"type": "undefined"}})
            return err("unexpected function on an element")
        if oid in self.arrays:
            raw, hit = self.arrays[oid]
            if "this[0]" in fd:
                return value(raw)
            if hit is None:
                return ok({"result": {"type": "object", "subtype": "null", "value": None}})
            return ok({"result": {"type": "object", "subtype": "node", "objectId": hit}})
        f = self.owner(oid)
        if f is None:
            return err("Could not find object with given id")
        return ok({"result": {"type": "object", "value": [f.box[0], f.box[1], 0, 0, f.scale, f.scale]}})

    def evaluate(self, frame, expr, ok, params=None):
        params = params or {}
        def value(v):
            return ok({"result": {"type": "object" if isinstance(v, list) else "string", "value": v}})

        owner_call = "(" + self.mod._FRAME_OWNER_JS + ")("
        if expr.startswith(owner_call):
            args = json.loads("[" + expr[len(owner_call):-1] + "]")
            f, wrapped = self.find_owner(frame, args[0], args[1])
            if len(args) > 3 and args[3]:  # wrappedOnly
                return ok({"result": {"type": "boolean", "value": bool(f is not None and wrapped)}})
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
            mode = ("probe" if "__cdpilotProbe" in expr
                    else "strict" if "__cdpilotMinScore" in expr else "loose")
            self.finder.append([frame.fid, mode])
            if frame.slow:  # never answers; a non-probe finder would still act
                if mode != "probe":
                    self.acts.append([frame.fid, mode])
                return []
            ans = self.answer(frame, mode)
            if mode != "probe" and ans.get("found"):
                self.acts.append([frame.fid, mode])
                self.act_real.append("__cdpilotRealClick" in expr)
            if "__cdpilotHit" in expr:  # _smart_wrap(real_click=True): [JSON, element]
                hit = None
                if ans.get("found") and mode != "probe":
                    ans, hit = dict(ans, realClick=True), "el:%s:finder" % frame.fid
                oid = "arr:%d" % len(self.arrays)
                self.arrays[oid] = (json.dumps(ans), hit)
                return ok({"result": {"type": "object", "subtype": "array", "objectId": oid}})
            return value(json.dumps(ans))
        if expr == self.mod._TWO_PAGE_FRAMES_JS:  # the settle wait before mouse input
            self.settles.append([frame.fid, params.get("contextId") in self.isolated])
            return [] if frame.settle_hang else ok({"result": {"type": "undefined"}})
        if "cdpilot-input-blocker" in expr:  # _BLOCKER_POINTER_JS
            pe = json.loads(expr[expr.rindex("(") + 1:-1])
            if frame is self.top and self.blocker:
                self.blocker_log.append(pe)
                return ok({"result": {"type": "boolean", "value": True}})
            return ok({"result": {"type": "boolean", "value": False}})
        if expr.startswith("!!document.querySelector("):  # selector ladder, css step
            return ok({"result": {"type": "boolean", "value": True}})
        if "__cdpilot_waitFor(" in expr:  # cmd_click / cmd_fill script
            return self.click_script(frame, expr, params, ok)
        if expr == "HANG":
            return []
        if expr == "NOISY":  # events interleaved before the reply, as a live page sends them
            ev = {"method": "Page.frameNavigated", "params": {"frame": {"id": frame.fid}}}
            return [dict(ev), dict(ev, method="Network.requestWillBeSent")] + value(frame.fid + "|noisy")
        if expr.startswith("LATE:"):  # answers after LATE:<seconds>
            out = value(frame.fid + "|late")
            out[0]["_delay"] = float(expr[len("LATE:"):])
            return out
        if expr.startswith("WHERE:"):
            return value(frame.fid + "|" + expr[len("WHERE:"):])
        return ok({"result": {"type": "undefined"}})

    def click_script(self, frame, expr, params, ok):
        """cmd_click's script: the element "el:<frame>:<sel>", or (plain page
        path, returnByValue) its "Clicked:" line after the script's el.click()."""
        if "window.__cdpilot_waitFor" in expr:
            self.leaks.append(frame.fid)
        sel = json.loads(re.search(r'__cdpilot_waitFor\(("(?:[^"\\]|\\.)*"), ', expr).group(1))
        if params.get("returnByValue") is False:
            if "el.click()" in expr:
                self.clicks.append([frame.fid, "script"])
            return ok({"result": {"type": "object", "subtype": "node",
                                  "objectId": "el:%s:%s" % (frame.fid, sel)}})
        for _ in range(expr.count("el.click();")):
            self.clicks.append([frame.fid, "script"])
        return ok({"result": {"type": "string", "value": "Clicked: BUTTON " + sel}})


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
        if self.b.fail_on == msg.get("method"):
            raise RuntimeError("boom")
        for payload in self.b.handle(msg):
            delay = payload.pop("_delay", 0)
            if delay:
                asyncio.get_running_loop().call_later(delay, self.q.put_nowait, json.dumps(payload))
            else:
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
    if hasattr(mod, "_FRAME_ISOLATED_NOTED"):
        mod._FRAME_ISOLATED_NOTED[0] = False  # once per process: a run is a process
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


def probe_command(mod, seen, kind="css"):
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
    return mod._frame_aware(kind)(probe)


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
        # The probe saw a real match, the DOM changed before the act ran.
        "act_changed": ({"top": {"strict": weak, "loose": page_loose},
                         "card": {"probe": {"found": True, "probe": True, "score": 100},
                                  "strict": {"found": False, "weakScore": 20}}}, False),
    }
    out = {}
    for key, (finders, same_origin_only) in cases.items():
        async def body(b, same_origin_only=same_origin_only):
            raw = await mod._smart_eval(WS, "FINDER", "smart-x", same_origin_only=same_origin_only)
            return json.loads(raw) if raw else raw
        b, res, _, err = run(mod, two_level_page(finders), body)
        lists = sum(1 for m in b.log if m.get("params", {}).get("expression") == mod._FRAME_LIST_JS)
        out[key] = {"res": res, "finder": b.finder, "acts": b.acts, "attached": b.attached,
                    "frame_lists": lists, "stderr": err, "open_sessions": sorted(b.sessions)}
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
            t0 = time.monotonic()
            hit = await mod._frame_search(WS, mod._smart_wrap("FINDER", probe=True), mod._smart_wrap("FINDER"),
                                          "smart-x", budget_s=0.5)
            return {"hit": hit, "elapsed": time.monotonic() - t0,
                    "socket_kept": WS in mod._WS_POOL and not mod._WS_POOL[WS].closed}
        b, res, _, err = run(mod, top, direct)
        res.update({"stderr": err, "finder": b.finder, "acts": b.acts, "calls": calls[:]})
        out["direct"] = res

        del calls[:]

        async def via_smart_eval(b):
            t0 = time.monotonic()
            raw = await mod._smart_eval(WS, "FINDER", "smart-x")
            return {"res": json.loads(raw), "elapsed": time.monotonic() - t0}
        b, res, _, err = run(mod, top, via_smart_eval)
        res.update({"stderr": err, "finder": b.finder, "acts": b.acts,
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


def scenario_probe_timeout(mod):
    """A probe cut off by the budget acted nowhere: the page fallback is the one act."""
    def page(fill):
        top_finder = ({"strict": {"found": False}, "loose": {"found": False}} if fill else
                      {"strict": {"found": False, "weakScore": 35},
                       "loose": {"found": True, "x": 1, "y": 1, "weak": True}})
        # The slow frame holds a real match: were it acted on, it would click/type.
        return Frame("top", finder=top_finder, children=[
            Frame("slow", elem_id="slow", slow=True, finder={"strict": {"found": True, "x": 1, "y": 1}}),
            Frame("later", elem_id="later", finder={"strict": {"found": True, "x": 1, "y": 1}}),
        ])
    out = {}
    saved = mod.FRAME_SEARCH_BUDGET_S
    mod.FRAME_SEARCH_BUDGET_S = 0.5
    try:
        for key, fill in [("click", False), ("fill_same_origin", True)]:
            async def body(b, fill=fill):
                t0 = time.monotonic()
                raw = await mod._smart_eval(WS, "FINDER", "smart-x", same_origin_only=fill)
                return {"res": json.loads(raw), "elapsed": time.monotonic() - t0}
            b, res, _, err = run(mod, page(fill), body)
            res.update({"stderr": err, "finder": b.finder, "acts": b.acts})
            out[key] = res
    finally:
        mod.FRAME_SEARCH_BUDGET_S = saved
    return out


def scenario_late_reply(mod):
    """Plain cdp_send reads a reply landing just after its timeout (flat 2 s recv)."""
    async def body(b):
        t0 = time.monotonic()
        r = await mod.cdp_send(WS, [(1, "Runtime.evaluate", {"expression": "LATE:0.4"})], timeout=0.3)
        plain = {"value": r.get(1, {}).get("result", {}).get("value"), "elapsed": time.monotonic() - t0}
        t0 = time.monotonic()
        r = await mod._frame_cdp(mod._FrameRoute(WS), [(1, "Runtime.evaluate", {"expression": "LATE:0.4"})],
                                 timeout=0.3)
        framed = {"value": r.get(1, {}).get("result", {}).get("value"), "elapsed": time.monotonic() - t0}
        return {"plain": plain, "frame": framed}
    _, res, _, _ = run(mod, Frame("top"), body)
    return res


def scenario_text_hops(mod):
    """smart-*: a first hop of plain words is text; wrappers work with a note."""
    seen = []
    text_cmd, css_cmd = probe_command(mod, seen, "text"), probe_command(mod, seen, "css")
    top = Frame("top", children=[
        Frame("card", elem_id="card", src="http://a.test/inner.html", box=(100, 1000),
              wrappers=["main", "Main", "#card-element"]),
    ])

    async def body(b):
        out = {}
        for key, fn, target, flag in [
            ("text_main", text_cmd, "Main >>> Settings", None),
            ("text_main_lower", text_cmd, "main >>> Settings", None),
            ("text_page_of", text_cmd, "Page 1 of 3 >>> Next page", None),
            ("text_selector", text_cmd, "iframe#card >>> Pay now", None),
            ("text_wrapper", text_cmd, "#card-element >>> Pay now", None),
            ("text_url", text_cmd, "url=inner.html >>> Pay now", None),
            ("css_wrapper", css_cmd, "main >>> #btn", None),
            ("css_frame", css_cmd, "#card >>> #btn", None),
            ("flag_wrapper", css_cmd, "#btn", "#card-element"),
        ]:
            mod._FRAME_FLAG = flag
            start, err_start = len(b.log), len(sys.stderr.getvalue())
            res = await call(fn, target)
            out[key] = {"res": res, "messages": [m["method"] for m in b.log[start:]],
                        "stderr": sys.stderr.getvalue()[err_start:]}
        mod._FRAME_FLAG = None
        return out

    _, res, _, _ = run(mod, top, body)
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


def scenario_isolated_fallback(mod):
    """No usable main-world id: an isolated world (same DOM), and every command says so."""
    top = Frame("top", children=[Frame("card", elem_id="card", src="http://a.test/inner.html")])
    seen = []
    probe = probe_command(mod, seen)
    out = {}
    for key, steps in [("eval", [(mod.cmd_frame, ("eval", "--frame", "#card", "WHERE:z"))]),
                       ("list", [(mod.cmd_frame, ("list", "--frame", "#card"))]),
                       ("click", [(probe, ("#card >>> #btn",))]),
                       # two frame commands in one process: one note
                       ("twice", [(probe, ("#card >>> #btn",)), (probe, ("#card >>> #cc",))])]:
        async def body(b, steps=steps):
            b.opaque_ids = True
            res = [await call(fn, *args) for fn, args in steps]
            ctxs = [m["params"].get("contextId") for m in b.log
                    if m["method"] == "Runtime.evaluate" and "WHERE:" in m["params"].get("expression", "")]
            return {"res": res, "contexts": ctxs, "isolated": sorted(b.isolated)}
        _, res, stdout, err = run(mod, top, body)
        res.update({"stdout": stdout, "stderr": err})
        out[key] = res
    return out


def click_page(**cfg):
    """page_tree() with the real-click settings `cfg` applied:
    "<frame>.<attr>": value (frame "top", "card", "nested", "pay")."""
    top = page_tree()
    frames = {"top": top, "card": top.children[0], "nested": top.children[0].children[0],
              "pay": top.children[1]}
    for key, v in cfg.items():
        fid, attr = key.split(".")
        setattr(frames[fid], attr, v)
    return top


def run_click(mod, top, target, entropy=False, blocker=False, fail_on=None):
    async def body(b):
        b.blocker, b.fail_on = blocker, fail_on
        t0 = time.monotonic()
        res = await call(lambda: mod.cmd_click(target, None, False, entropy))
        return {"res": res, "elapsed": time.monotonic() - t0}
    b, res, stdout, err = run(mod, top, body)
    res.update({"stdout": stdout, "stderr": err, "clicks": b.clicks, "leaks": b.leaks, "hits": b.hits,
                "settles": b.settles, "blocker": b.blocker_log,
                "pressed": [m[1:] for m in b.mouse if m[0] == "mousePressed"],
                "released": [m[1:] for m in b.mouse if m[0] == "mouseReleased"]})
    return res


def scenario_click_input(mod):
    """cmd_click: one click per command; real mouse input with entropy and in frames,
    only where the hit-test passes; cdpilot's input blocker opened and restored."""
    out = {}
    # The entropy cases take ~0.5 s each: the humanized pauses are real.
    for key, target, entropy in [
        ("page_plain", "#btn", False),
        ("page_entropy", "#btn", True),
        ("frame", "#card >>> #btn", False),
        ("frame_entropy", "#card >>> #nested >>> #btn", True),
        ("oopif", "#pay >>> #btn", False),
        ("frame_nobox", "#card >>> #nobox", False),
    ]:
        out[key] = run_click(mod, click_page(), target, entropy)
    # A cookie banner over the <iframe>, and one over the target inside the frame.
    out["covered_frame"] = run_click(mod, click_page(**{"card.covered": "div#cookie.banner"}), "#card >>> #btn")
    out["covered_target"] = run_click(mod, click_page(**{"nested.target_cover": "div.overlay"}),
                                      "#card >>> #nested >>> #btn")
    out["covered_page"] = run_click(mod, click_page(**{"top.target_cover": "div#cookie"}), "#btn", True)
    # transform: scale(.5) on #card, zoom: 2 on #nested inside it.
    out["scaled"] = run_click(mod, click_page(**{"card.scale": 0.5, "nested.scale": 2.0}),
                              "#card >>> #nested >>> #btn")
    # cdpilot's input blocker on the top page (visual feedback on).
    out["blocker"] = run_click(mod, click_page(), "#card >>> #btn", blocker=True)
    out["blocker_entropy"] = run_click(mod, click_page(), "#btn", True, blocker=True)
    out["blocker_error"] = run_click(mod, click_page(), "#card >>> #btn", blocker=True,
                                     fail_on="Input.dispatchMouseEvent")
    # The settle wait never answers, in the frame and in the top page.
    out["settle_hang"] = run_click(mod, click_page(**{"card.settle_hang": True, "top.settle_hang": True}),
                                   "#card >>> #btn")
    out["settle_ok"] = run_click(mod, click_page(), "#card >>> #btn")
    out["settle_timeout"] = mod.FRAME_SETTLE_TIMEOUT_S
    return out


def scenario_smart_real_click(mod):
    """smart-click in a frame: the finder picks, the mouse clicks (hit-tested)."""
    out = {}
    for key, finders, cover in [
        ("smart_frame", {"top": {"strict": {"found": False}, "loose": {"found": False}},
                         "card": {"strict": {"found": True, "x": 5, "y": 6}}}, ""),
        ("smart_covered", {"top": {"strict": {"found": False}, "loose": {"found": False}},
                           "card": {"strict": {"found": True, "x": 5, "y": 6}}}, "div#cookie"),
        ("smart_page", {"top": {"strict": {"found": True, "x": 9, "y": 9}}}, ""),
    ]:
        async def body(b):
            return json.loads(await mod._smart_eval(WS, "FINDER", "smart-click", real_click='"Pay"'))
        page = two_level_page(finders)
        page.children[0].covered = cover
        b, res, _, err = run(mod, page, body)
        out[key] = {"res": res, "acts": b.acts, "act_real": b.act_real, "clicks": b.clicks, "stderr": err,
                    "pressed": [m[1:] for m in b.mouse if m[0] == "mousePressed"]}

    async def routed(b):
        mod._FRAME_FLAG = "#card"
        try:
            return await call(mod._frame_aware("text")(
                lambda t: mod._smart_eval(WS, "FINDER", "smart-click", real_click='"Pay"')), "Pay")
        finally:
            mod._FRAME_FLAG = None
    b, res, _, _ = run(mod, two_level_page({"card": {"loose": {"found": True, "x": 5, "y": 6}}}), routed)
    out["smart_routed"] = {"res": res, "acts": b.acts, "act_real": b.act_real,
                           "pressed": [m[1:] for m in b.mouse if m[0] == "mousePressed"]}
    return out


def scenario_plain_wire(mod):
    """Plain (unrouted) cdp_send: exact wire messages, events ignored, same result."""
    out = {}
    for key, pool in [("pooled", True), ("unpooled", False)]:
        async def body(b):
            r = await mod.cdp_send(WS, [(1, "Runtime.evaluate", {"expression": "NOISY", "returnByValue": True}),
                                        (2, "Runtime.evaluate", {"expression": "WHERE:x"})])
            return {"result": r, "wire": list(b.log)}
        _, res, _, _ = run(mod, Frame("top"), body, pool=pool)
        out[key] = res
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
    "probe_timeout": scenario_probe_timeout,
    "late_reply": scenario_late_reply,
    "text_hops": scenario_text_hops,
    "isolated_fallback": scenario_isolated_fallback,
    "plain_wire": scenario_plain_wire,
    "click_input": scenario_click_input,
    "smart_real_click": scenario_smart_real_click,
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
    results["_methods"] = STATE["methods"]  # CDP methods sent, summed over all scenarios run
    results["_released"] = STATE["released"]  # Runtime.releaseObjectGroup per group
    sys.stdout.write(json.dumps(results) + "\n")


if __name__ == "__main__":
    main()

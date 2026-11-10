#!/usr/bin/env python3.13
"""tuval-sizinti.py - canlı tuval (plan-canli-tuval-uygulama.md §2.1, §3, §7) için 5 sızıntı ölçümü.

Ham CDP (websockets) ile paylaşılan başsız Chrome'a (127.0.0.1:9333) bağlanır; tarayıcı AÇMAZ,
Browser.close ÇAĞIRMAZ. Yalnız kendi açtığı sekmeleri/bağlamları kapatır.

Kullanım (tek JSON özeti stdout'a; ilerleme stderr'e):
  python3.13 -I tuval-sizinti.py [--only M1,M2,M3,M4,M5] [--vec a,b,...] [--tablo]
  --tablo  JSON yerine kısa markdown satırları basar.
Gizli: --host page|context  (M3/M4'te ayrı süreç olarak koşan "host"; elle çağrılmaz).

M1 yan kanallar (WebRTC STUN/TURN, dns-prefetch/preconnect, a ping, sendBeacon, CSS url, img)
M2 üst düzey gezinme: blob:/data:/about:blank (location= ve window.open), CSP/sandbox mirası
M3 host ölümü: SIGKILL / SIGSTOP sonrası sekme + location= (kontrol: host canlı)
M4 Target.createBrowserContext{disposeOnDetach:true}: host SIGKILL sonrası bağlam/sekme
M5 yalıtım: tuval oturumunda Fetch.enable{*} başka sekmeye dokunuyor mu
"""
import asyncio
import base64
import http.server
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request

import websockets.asyncio.client as wsc

CDP_HOST = "127.0.0.1:9333"
CANVAS_URL = "http://cdpilot-canvas.invalid/m/"
CSP = ("default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; "
       "img-src data: blob:; form-action 'none'; base-uri 'none'; frame-src 'none'; "
       "sandbox allow-scripts")
SKELETON = b"<!doctype html><meta charset=utf-8><html><head></head><body></body></html>"
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
# Chrome'un erişimi engellediği ("unsafe") portlar + yasaklı portlar
UNSAFE = {1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95,
          101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143, 161,
          179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563,
          587, 601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3000, 3659, 4045, 4190,
          5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6679, 6697, 9222, 10080}

CREATED_TABS: set[str] = set()
CREATED_CTX: set[str] = set()
LOADS: list[int] = []


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load1() -> int:
    v = round(os.getloadavg()[0])
    LOADS.append(v)
    return v


# ───────────────────────── HTTP yardımcıları ─────────────────────────
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_text(path: str, method: str = "GET", timeout: float = 20) -> str:
    req = urllib.request.Request(f"http://{CDP_HOST}{path}", method=method)
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def list_pages() -> list[dict]:
    return [t for t in json.loads(http_text("/json/list")) if t.get("type") == "page"]


def browser_ws() -> str:
    return json.loads(http_text("/json/version"))["webSocketDebuggerUrl"]


def chrome_version() -> str:
    return json.loads(http_text("/json/version"))["Browser"]


async def new_tab() -> tuple[str, str]:
    t = json.loads(await asyncio.to_thread(http_text, "/json/new?about:blank", "PUT"))
    CREATED_TABS.add(t["id"])
    return t["id"], t["webSocketDebuggerUrl"]


async def close_tab(tid: str) -> None:
    try:
        await asyncio.to_thread(http_text, f"/json/close/{tid}", "GET", 10)
    except Exception:
        pass
    CREATED_TABS.discard(tid)


# ───────────────────────── Dinleyiciler ─────────────────────────
class _Handler(http.server.BaseHTTPRequestHandler):
    timeout = 2
    protocol_version = "HTTP/1.0"

    def _rec(self) -> None:
        with self.server.L.lock:  # type: ignore[attr-defined]
            self.server.L.http.append(f"{self.command} {self.path.split('?')[0]}")  # type: ignore

    def _send(self, code: int, body: bytes = b"", ct: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._rec()
        if self.path.startswith("/img"):
            self._send(200, GIF, "image/gif")
        elif self.path.startswith("/other"):
            self._send(200, b'<!doctype html><img src="/other-img"><p>other</p>', "text/html")
        else:
            self._send(200, b"ok")

    def _drain_post(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(min(n, 65536))
        self._rec()
        self._send(204)

    do_POST = _drain_post
    do_PUT = _drain_post
    do_OPTIONS = _drain_post
    do_DELETE = _drain_post
    do_HEAD = do_GET

    def log_message(self, *a: object) -> None:
        return


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):  # type: ignore[no-untyped-def]
        r = super().get_request()
        with self.L.lock:  # type: ignore[attr-defined]
            self.L.http_accepts += 1  # type: ignore[attr-defined]
        return r


class Listeners:
    """HTTP (istek + TCP kabul sayar), ham TCP (yalnız kabul), UDP (STUN/TURN datagram)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.http: list[str] = []
        self.http_accepts = 0
        self.raw_accepts = 0
        self.udp4 = 0
        self.udp6 = 0
        self.stun = 0
        self.stop_flag = False
        self.conns: list[socket.socket] = []
        self.threads: list[threading.Thread] = []

    @staticmethod
    def _free(kind: int) -> tuple[socket.socket, int]:
        for _ in range(200):
            s = socket.socket(socket.AF_INET, kind)
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
            if p not in UNSAFE:
                return s, p
            s.close()
        raise RuntimeError("güvenli port bulunamadı")

    def start(self) -> "Listeners":
        for _ in range(200):
            srv = _Server(("127.0.0.1", 0), _Handler)
            if srv.server_address[1] not in UNSAFE:
                break
            srv.server_close()
        srv.L = self  # type: ignore[attr-defined]
        self.srv = srv
        self.http_port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.threads.append(t)
        # ham TCP: yalnız kabul sayar
        self.raw_sock, self.raw_port = self._free(socket.SOCK_STREAM)
        self.raw_sock.listen(32)
        self.raw_sock.settimeout(0.2)
        t = threading.Thread(target=self._raw_loop, daemon=True)
        t.start()
        self.threads.append(t)
        # UDP v4 (+ aynı portta v6 varsa)
        self.u4, self.udp_port = self._free(socket.SOCK_DGRAM)
        self.u4.settimeout(0.2)
        self.u6 = None
        try:
            u6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            u6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            u6.bind(("::1", self.udp_port))
            u6.settimeout(0.2)
            self.u6 = u6
        except OSError:
            self.u6 = None
        for sock, fam in ((self.u4, 4), (self.u6, 6)):
            if sock is not None:
                t = threading.Thread(target=self._udp_loop, args=(sock, fam), daemon=True)
                t.start()
                self.threads.append(t)
        return self

    def _raw_loop(self) -> None:
        while not self.stop_flag:
            try:
                c, _ = self.raw_sock.accept()
            except (TimeoutError, OSError):
                continue
            with self.lock:
                self.raw_accepts += 1
                self.conns.append(c)

    def _udp_loop(self, sock: socket.socket, fam: int) -> None:
        while not self.stop_flag:
            try:
                data, _ = sock.recvfrom(4096)
            except (TimeoutError, OSError):
                continue
            with self.lock:
                if fam == 4:
                    self.udp4 += 1
                else:
                    self.udp6 += 1
                if len(data) >= 20 and data[4:8] == b"\x21\x12\xa4\x42":
                    self.stun += 1

    def snap(self) -> dict:
        with self.lock:
            return {"http": list(self.http), "http_acc": self.http_accepts,
                    "raw_acc": self.raw_accepts, "udp4": self.udp4, "udp6": self.udp6,
                    "stun": self.stun}

    def stop(self) -> None:
        self.stop_flag = True
        threading.Thread(target=self.srv.shutdown, daemon=True).start()
        time.sleep(0.3)
        for s in [self.srv.socket, self.raw_sock, self.u4, self.u6, *self.conns]:
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass


# ───────────────────────── CDP istemcisi ─────────────────────────
class CDPError(Exception):
    pass


class CDP:
    def __init__(self, url: str) -> None:
        self.url = url
        self.n = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.handlers: dict[str, list] = {}
        self.dead: str | None = None

    async def open(self) -> "CDP":
        self.ws = await wsc.connect(self.url, max_size=None, ping_interval=None,
                                    open_timeout=30, proxy=None)
        self.task = asyncio.ensure_future(self._rx())
        return self

    async def _rx(self) -> None:
        try:
            async for m in self.ws:
                d = json.loads(m)
                if "id" in d:
                    f = self.pending.pop(d["id"], None)
                    if f and not f.done():
                        f.set_result(d)
                else:
                    for h in self.handlers.get(d.get("method", ""), []):
                        h(d.get("params", {}), d.get("sessionId"))
        except Exception as e:  # bağlantı koptu
            self.dead = repr(e)[:80]
        finally:
            self.dead = self.dead or "closed"
            for f in self.pending.values():
                if not f.done():
                    f.set_exception(CDPError("ws-closed"))

    def on(self, method: str, cb) -> None:  # type: ignore[no-untyped-def]
        self.handlers.setdefault(method, []).append(cb)

    async def send(self, method: str, params: dict | None = None, session: str | None = None,
                   timeout: float = 30) -> dict:
        self.n += 1
        i = self.n
        msg: dict = {"id": i, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        fut = asyncio.get_running_loop().create_future()
        self.pending[i] = fut
        await self.ws.send(json.dumps(msg))
        d = await asyncio.wait_for(fut, timeout)
        if "error" in d:
            raise CDPError(f"{method}: {d['error'].get('message')}")
        return d.get("result", {})

    async def evaluate(self, expr: str, session: str | None = None, gesture: bool = False,
                       await_promise: bool = False, timeout: float = 30):  # type: ignore
        r = await self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                 "userGesture": gesture,
                                                 "awaitPromise": await_promise},
                            session, timeout)
        if "exceptionDetails" in r:
            raise CDPError("js: " + str(r["exceptionDetails"].get("text"))[:80])
        return r.get("result", {}).get("value")

    async def close(self) -> None:
        try:
            await self.ws.close()
        except Exception:
            pass


# ───────────────────────── Tuval (plan K2) ─────────────────────────
class Canvas:
    """K2 Fetch işleyicisi: tam canvas URL'si → 200 + başlık; öteki → 204 (ya da 'continue')."""

    def __init__(self, c: CDP, session: str | None, csp: bool = True, other: str = "204") -> None:
        self.c, self.session, self.csp, self.other = c, session, csp, other
        self.paused: list[str] = []
        self.docs = 0
        self.errors: list[str] = []
        c.on("Fetch.requestPaused", self._on)

    def _on(self, p: dict, sid: str | None) -> None:
        if sid != self.session:
            return
        asyncio.ensure_future(self._handle(p))

    async def _handle(self, p: dict) -> None:
        rid, url, rt = p["requestId"], p["request"]["url"], p.get("resourceType")
        try:
            if url == CANVAS_URL and rt == "Document":
                self.docs += 1
                hdr = [{"name": "Content-Type", "value": "text/html; charset=utf-8"}]
                if self.csp:
                    hdr.append({"name": "Content-Security-Policy", "value": CSP})
                await self.c.send("Fetch.fulfillRequest", {
                    "requestId": rid, "responseCode": 200, "responseHeaders": hdr,
                    "body": base64.b64encode(SKELETON).decode()}, self.session)
                return
            self.paused.append(f"{p['request']['method']} {rt} {url[:70]}")
            if self.other == "continue":
                await self.c.send("Fetch.continueRequest", {"requestId": rid}, self.session)
            else:
                await self.c.send("Fetch.fulfillRequest", {"requestId": rid, "responseCode": 204,
                                                           "responseHeaders": []}, self.session)
        except Exception as e:
            self.errors.append(repr(e)[:80])

    async def enable_and_open(self) -> None:
        s = self.session
        await self.c.send("Page.enable", {}, s)
        await self.c.send("Runtime.enable", {}, s)
        await self.c.send("Fetch.enable", {"patterns": [{"urlPattern": "*",
                                                          "requestStage": "Request"}]}, s)
        await self.c.send("Page.navigate", {"url": CANVAS_URL}, s)
        await self.wait_ready()

    async def wait_ready(self, timeout: float = 20) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                v = await self.c.evaluate(
                    "location.href+'|'+document.readyState", self.session, timeout=10)
                if v == CANVAS_URL + "|complete":
                    return
            except CDPError:
                pass
            await asyncio.sleep(0.1)
        raise CDPError("tuval belgesi hazır olmadı")

    async def set_html(self, html: str) -> None:
        s = self.session
        fid = (await self.c.send("Page.getFrameTree", {}, s))["frameTree"]["frame"]["id"]
        await self.c.send("Page.setDocumentContent", {"frameId": fid, "html": html}, s)


# ───────────────────────── M1 ─────────────────────────
PRELUDE = ("<script>window.__r={};window.__v=[];"
           "document.addEventListener('securitypolicyviolation',e=>__v.push("
           "e.effectiveDirective+':'+String(e.blockedURI).slice(0,40)));"
           "window.addEventListener('error',e=>__r.onerror=String(e.message).slice(0,60));"
           "window.addEventListener('unhandledrejection',e=>__r.unhandled="
           "String(e.reason).slice(0,60));</script>")


def m1_html(vec: str, L: Listeners) -> tuple[str, bool]:
    hp, rp, up = L.http_port, L.raw_port, L.udp_port
    H = f"http://127.0.0.1:{hp}"

    def rtc(urls: str, extra: str = "") -> str:
        return ("<script>(async()=>{try{const pc=new RTCPeerConnection({iceServers:[{urls:'"
                + urls + "'" + extra + "}]});window.__pc=pc;pc.createDataChannel('x');"
                "pc.onicecandidate=e=>{__r.cand=(__r.cand||0)+1};"
                "pc.onicegatheringstatechange=()=>{__r.gather=pc.iceGatheringState};"
                "const o=await pc.createOffer();await pc.setLocalDescription(o);__r.rtc='ok'}"
                "catch(e){__r.rtc='EXC:'+e.name+':'+String(e.message).slice(0,50)}})()</script>")
    click = False
    if vec == "a":
        body = rtc(f"stun:127.0.0.1:{up}")
    elif vec == "a-turn":
        body = rtc(f"turn:127.0.0.1:{up}?transport=udp", ",username:'u',credential:'p'")
    elif vec == "b":
        body = rtc(f"stun:localhost:{up}")
    elif vec == "c-dns":
        body = (f"<link rel=dns-prefetch href=//127.0.0.1:{hp}>"
                f"<link rel=dns-prefetch href=//127.0.0.1:{rp}>")
    elif vec == "c-pre":
        body = (f"<link rel=preconnect href=http://127.0.0.1:{hp}>"
                f"<link rel=preconnect href=http://127.0.0.1:{rp}>")
    elif vec == "c-pre-x":
        body = (f"<link rel=preconnect crossorigin href=http://127.0.0.1:{hp}>"
                f"<link rel=preconnect crossorigin href=http://127.0.0.1:{rp}>")
    elif vec == "c-prefetch":
        body = (f"<link rel=prefetch href=http://127.0.0.1:{hp}/prefetch>"
                f"<link rel=preload as=fetch crossorigin href=http://127.0.0.1:{hp}/preload>")
    elif vec == "d":
        body = (f"<a id=a ping={H}/ping href=# style='display:block;width:120px;height:40px'>x</a>")
        click = True
    elif vec == "d2":
        body = (f"<a id=a ping={H}/ping2 href=http://cdpilot-canvas.invalid/next "
                "style='display:block;width:120px;height:40px'>x</a>")
        click = True
    elif vec == "e":
        body = (f"<script>try{{__r.beacon=String(navigator.sendBeacon('{H}/beacon','x'))}}"
                "catch(e){__r.beacon='EXC:'+e.name}</script>")
    elif vec == "f":
        body = f"<style>body{{background:url({H}/css)}}</style><p>css</p>"
    elif vec == "g":
        body = f"<img src={H}/img onload=\"__r.img='load'\" onerror=\"__r.img='error'\">"
    else:
        raise ValueError(vec)
    return f"<!doctype html><html><head>{PRELUDE}</head><body>{body}</body></html>", click


def m1_marks(L: Listeners) -> list[str]:
    return [f"127.0.0.1:{L.http_port}", f":{L.raw_port}", f":{L.udp_port}", "localhost"]


async def m1_run(vec: str, variant: str) -> dict:
    """variant: csp | nocsp_204 | nocsp_cont | nocsp_bare"""
    L = Listeners().start()
    tid, ws = await new_tab()
    c = await CDP(ws).open()
    exc: list[str] = []
    row: dict = {"v": vec, "var": variant}
    try:
        c.on("Runtime.exceptionThrown",
             lambda p, s: exc.append(str(p.get("exceptionDetails", {}).get("text"))[:50]))
        cv: Canvas | None = None
        if variant == "nocsp_bare":
            await c.send("Page.enable")
            await c.send("Runtime.enable")
        else:
            cv = Canvas(c, None, csp=(variant == "csp"),
                        other="continue" if variant == "nocsp_cont" else "204")
            await cv.enable_and_open()
        html, click = m1_html(vec, L)
        fid = (await c.send("Page.getFrameTree"))["frameTree"]["frame"]["id"]
        await c.send("Page.setDocumentContent", {"frameId": fid, "html": html})
        if click:
            await asyncio.sleep(1)
            rect = json.loads(await c.evaluate(
                "JSON.stringify(document.getElementById('a').getBoundingClientRect())"))
            x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
            for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
                await c.send("Input.dispatchMouseEvent", {
                    "type": typ, "x": x, "y": y, "button": "left", "clickCount": 1})
        await asyncio.sleep(3)
        pg = json.loads(await c.evaluate("JSON.stringify({r:window.__r,v:window.__v,"
                                         "u:location.href.slice(0,40)})") or "{}")
        s = L.snap()
        marks = m1_marks(L)
        fetch_hits = [p for p in (cv.paused if cv else []) if any(m in p for m in marks)]
        row.update({
            "http": [h for h in s["http"]], "http_acc": s["http_acc"], "raw_acc": s["raw_acc"],
            "udp4": s["udp4"], "udp6": s["udp6"], "stun": s["stun"],
            "fetch": fetch_hits, "fetch_n": len(cv.paused) if cv else None,
            "docs": cv.docs if cv else None, "page": pg.get("r"), "viol": pg.get("v"),
            "url": pg.get("u"), "exc": exc[:3], "ferr": (cv.errors[:2] if cv else []),
            "load": load1()})
        leak = bool(s["http"] or s["raw_acc"] or s["udp4"] or s["udp6"] or s["http_acc"])
        row["listener_hit"] = leak
    except Exception as e:
        row["error"] = repr(e)[:120]
    finally:
        await c.close()
        await close_tab(tid)
        L.stop()
    return row


async def m1() -> list[dict]:
    vecs = ["a", "a-turn", "b", "c-dns", "c-pre", "c-pre-x", "c-prefetch", "d", "d2", "e", "f",
            "g"]
    if "--vec" in sys.argv:
        vecs = sys.argv[sys.argv.index("--vec") + 1].split(",")
    variants = ["csp", "nocsp_204", "nocsp_cont", "nocsp_bare"]
    rows = []
    for vec in vecs:
        for var in variants:
            log(f"M1 {vec}/{var}")
            rows.append(await m1_run(vec, var))
    return rows


# ───────────────────────── M2 ─────────────────────────
PROBE_JS = """(async()=>{const r={href:location.href.slice(0,40),origin:String(location.origin)};
const v=[];document.addEventListener('securitypolicyviolation',e=>v.push(e.effectiveDirective));
try{localStorage.length;r.ls='ok'}catch(e){r.ls=e.name}
try{await fetch('%(H)s/fetch-new',{mode:'no-cors'});r.fetch='ok'}catch(e){r.fetch='EXC:'+e.name}
r.img=await new Promise(res=>{const i=new Image();i.onload=()=>res('load');i.onerror=()=>res('error');
i.src='%(H)s/img-new';setTimeout(()=>res('timeout'),1500)});
try{r.beacon=String(navigator.sendBeacon('%(H)s/beacon-new','x'))}catch(e){r.beacon='EXC:'+e.name}
await new Promise(res=>setTimeout(res,1000));
r.viol=v;return JSON.stringify(r)})()"""


async def m2_run(target: str, method: str, mode: str) -> dict:
    """target blob|data|about; method loc|open; mode F (Fetch açık) | N (Fetch kapalı) | C (kontrol)."""
    L = Listeners().start()
    tid, ws = await new_tab()
    c = await CDP(ws).open()
    row: dict = {"t": target, "m": method, "mode": mode}
    frames: list[str] = []
    popups: list[str] = []
    bc: CDP | None = None
    try:
        c.on("Page.frameNavigated", lambda p, s: frames.append(p["frame"]["url"][:36]))
        cv = Canvas(c, None, csp=(mode != "C"), other="204")
        await cv.enable_and_open()
        await cv.set_html("<!doctype html><p id=x>canvas</p>")
        bc = await CDP(browser_ws()).open()
        before = {t["targetId"] for t in (await bc.send("Target.getTargets"))["targetInfos"]}
        if target == "blob":
            url = await c.evaluate(
                "window.__u=URL.createObjectURL(new Blob(['<p>blob-doc</p>'],"
                "{type:'text/html'}));window.__u")
        elif target == "data":
            url = "data:text/html,<p>data-doc</p>"
        else:
            url = "about:blank"
        if mode in ("N", "C"):
            await c.send("Fetch.disable")
        n_before = len(cv.paused)
        if method == "loc":
            await c.evaluate(f"location.href={json.dumps(url)}", gesture=True)
            ret = "n/a"
        else:
            ret = await c.evaluate(f"String(window.open({json.dumps(url)}))", gesture=True)
        await asyncio.sleep(2)
        # yalnız bu tuval sekmesinin açtığı hedefler (openerId); başkasının sekmesine dokunulmaz
        new = [{"id": t["targetId"], "url": t["url"],
                "webSocketDebuggerUrl": f"ws://{CDP_HOST}/devtools/page/{t['targetId']}"}
               for t in (await bc.send("Target.getTargets"))["targetInfos"]
               if t["targetId"] not in before and t.get("openerId") == tid
               and t["type"] == "page"]
        foreign = [t for t in (await bc.send("Target.getTargets"))["targetInfos"]
                   if t["targetId"] not in before and t.get("openerId") != tid
                   and t["type"] == "page"]
        row["foreign_new_ignored"] = len(foreign)
        for t in new:
            CREATED_TABS.add(t["id"])
        row["ret"] = ret
        row["popups"] = [f"{t['url'][:30]}" for t in new]
        probe = PROBE_JS % {"H": f"http://127.0.0.1:{L.http_port}"}
        if method == "open" and new:
            pc = await CDP(new[0]["webSocketDebuggerUrl"]).open()
            popups.append(new[0]["id"])
            try:
                row["probe"] = json.loads(await pc.evaluate(probe, await_promise=True))
            finally:
                await pc.close()
        else:
            row["probe"] = json.loads(await c.evaluate(probe, await_promise=True))
        await asyncio.sleep(0.5)
        s = L.snap()
        row["listener"] = [h for h in s["http"]]
        row["acc"] = s["http_acc"]
        row["fetch_nav"] = [p for p in cv.paused[:n_before + 20]
                            if p.split(" ", 2)[2].startswith(("blob:", "data:", "about:"))]
        row["fetch_all"] = [p[:60] for p in cv.paused[n_before:]]
        row["frames"] = frames[-3:]
        for t in new:
            await close_tab(t["id"])
        row["load"] = load1()
    except Exception as e:
        row["error"] = repr(e)[:120]
    finally:
        if bc:
            await bc.close()
        await c.close()
        await close_tab(tid)
        L.stop()
    return row


async def m2() -> list[dict]:
    rows = []
    for target in ("blob", "data", "about"):
        for method in ("loc", "open"):
            for mode in ("F", "N", "C"):
                log(f"M2 {target}/{method}/{mode}")
                rows.append(await m2_run(target, method, mode))
    return rows


# ───────────────────────── M3 / M4 host ─────────────────────────
async def host_main(kind: str) -> None:
    """Ayrı süreç: tuval sekmesinde Fetch kurar, hazır satırını basar, olayları işlemeye sürer."""
    out: dict = {}
    try:
        if kind == "page":
            tid, ws = await new_tab()
            c = await CDP(ws).open()
            session = None
            out = {"tid": tid}
        else:
            c = await CDP(browser_ws()).open()
            ctx = (await c.send("Target.createBrowserContext", {"disposeOnDetach": True}))[
                "browserContextId"]
            tid = (await c.send("Target.createTarget", {"url": "about:blank",
                                                        "browserContextId": ctx}))["targetId"]
            session = (await c.send("Target.attachToTarget", {"targetId": tid,
                                                              "flatten": True}))["sessionId"]
            out = {"tid": tid, "ctx": ctx}
        cv = Canvas(c, session, csp=True, other="204")
        await cv.enable_and_open()
        await cv.set_html("<!doctype html><p id=x>canvas</p>")
        out["ok"] = True
    except Exception as e:
        out["error"] = repr(e)[:160]
    print(json.dumps(out), flush=True)
    if "error" in out:
        return
    await asyncio.Event().wait()


def spawn_host(kind: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "--host", kind],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


async def host_ready(p: subprocess.Popen, timeout: float = 60) -> dict:
    line = await asyncio.wait_for(asyncio.to_thread(p.stdout.readline), timeout)  # type: ignore
    return json.loads(line) if line else {"error": "host çıktı vermedi"}


async def observe_after(tid: str, L: Listeners, secs: float) -> dict:
    """Yanıt bekler: sekme var mı, URL, dinleyici istekleri."""
    end = time.monotonic() + secs
    url = None
    while time.monotonic() < end:
        pg = [t for t in list_pages() if t["id"] == tid]
        url = pg[0]["url"][:70] if pg else None
        if url and "127.0.0.1" in url:
            break
        await asyncio.sleep(0.1)
    s = L.snap()
    return {"tab": bool(url), "url": url, "listener": s["http"], "http_acc": s["http_acc"]}


async def m3_run(kind: str) -> dict:
    """kind: alive (kontrol) | kill | stop"""
    L = Listeners().start()
    row: dict = {"kind": kind}
    p = spawn_host("page")
    tid = None
    try:
        info = await host_ready(p)
        if "error" in info:
            row["error"] = info["error"]
            return row
        tid = info["tid"]
        pre = [t for t in list_pages() if t["id"] == tid]
        row["pre_url"] = pre[0]["url"][:40] if pre else None
        if kind == "kill":
            p.send_signal(signal.SIGKILL)
            p.wait()
        elif kind == "stop":
            p.send_signal(signal.SIGSTOP)
        await asyncio.sleep(0.5)
        pg = [t for t in list_pages() if t["id"] == tid]
        row["tab_after_host"] = bool(pg)
        if not pg:
            return row
        c2 = await CDP(pg[0]["webSocketDebuggerUrl"]).open()
        try:
            await c2.evaluate(
                f"location='http://127.0.0.1:{L.http_port}/after-kill?x=secret'", gesture=True)
        finally:
            await c2.close()
        row["obs"] = await observe_after(tid, L, 4)
        if kind == "stop":
            p.send_signal(signal.SIGCONT)
            await asyncio.sleep(2.5)
            row["after_cont"] = await observe_after(tid, L, 1)
        row["load"] = load1()
    except Exception as e:
        row["error"] = repr(e)[:120]
    finally:
        try:
            p.send_signal(signal.SIGCONT)
        except Exception:
            pass
        try:
            p.kill()
            p.wait()
        except Exception:
            pass
        if tid:
            await close_tab(tid)
        L.stop()
    return row


async def m3() -> list[dict]:
    rows = []
    for kind in ("alive", "kill", "stop"):
        log(f"M3 {kind}")
        rows.append(await m3_run(kind))
    return rows


async def m4_run(i: int) -> dict:
    row: dict = {"i": i}
    p = spawn_host("context")
    ctx = tid = None
    c2 = None
    try:
        info = await host_ready(p)
        if "error" in info:
            row["error"] = info["error"]
            row["createBrowserContext"] = "hata" if "createBrowserContext" in info["error"] else "?"
            return row
        row["createBrowserContext"] = "available"
        tid, ctx = info["tid"], info["ctx"]
        CREATED_CTX.add(ctx)
        c2 = await CDP(browser_ws()).open()

        async def listing() -> tuple[bool, bool]:
            ts = (await c2.send("Target.getTargets"))["targetInfos"]
            in_ctx = [t for t in ts if t.get("browserContextId") == ctx]
            return any(t["targetId"] == tid for t in ts), bool(in_ctx)
        row["pre"] = await listing()
        ctxs = (await c2.send("Target.getBrowserContexts"))["browserContextIds"]
        row["ctx_listed_by_2nd_conn"] = ctx in ctxs
        t0 = time.monotonic()
        p.send_signal(signal.SIGKILL)
        p.wait()
        t_kill = time.monotonic()
        polls = 0
        gone_ms = None
        while time.monotonic() - t_kill < 15:
            polls += 1
            tab_present, ctx_has = await listing()
            if not tab_present:
                gone_ms = round((time.monotonic() - t_kill) * 1000)
                break
            await asyncio.sleep(0.02)
        row["tab_gone_ms"] = gone_ms
        row["polls"] = polls
        row["kill_wait_ms"] = round((t_kill - t0) * 1000)
        if gone_ms is not None:
            row["ctx_after"] = ctx in (await c2.send("Target.getBrowserContexts"))[
                "browserContextIds"]
            CREATED_CTX.discard(ctx)
            tid = None
        row["load"] = load1()
    except Exception as e:
        row["error"] = repr(e)[:120]
    finally:
        try:
            p.kill()
            p.wait()
        except Exception:
            pass
        if ctx and ctx in CREATED_CTX:
            try:
                if c2 is None:
                    c2 = await CDP(browser_ws()).open()
                await c2.send("Target.disposeBrowserContext", {"browserContextId": ctx})
                CREATED_CTX.discard(ctx)
                row["disposed_by_us"] = True
            except Exception as e:
                row["dispose_err"] = repr(e)[:60]
        if tid:
            await close_tab(tid)
        if c2:
            await c2.close()
    return row


async def m4() -> list[dict]:
    rows = []
    for i in range(3):
        log(f"M4 #{i}")
        rows.append(await m4_run(i))
    return rows


# ───────────────────────── M5 ─────────────────────────
async def m5() -> dict:
    L = Listeners().start()
    row: dict = {}
    tid, ws = await new_tab()
    c = await CDP(ws).open()
    bc = other = None
    try:
        cv = Canvas(c, None, csp=True, other="204")
        await cv.enable_and_open()
        await cv.set_html("<!doctype html><p id=x>canvas</p>")
        H = f"http://127.0.0.1:{L.http_port}"
        # kontrol: tuvalin kendi gezinmesi Fetch'e takılır, dinleyiciye ulaşmaz
        await c.evaluate(f"location='{H}/ctl-canvas'", gesture=True)
        await asyncio.sleep(1.5)
        row["control_paused"] = [p for p in cv.paused if "ctl-canvas" in p]
        row["control_listener"] = [h for h in L.snap()["http"] if "ctl-canvas" in h]
        # öteki sekme: Target.createTarget about:blank → Page.navigate
        bc = await CDP(browser_ws()).open()
        otid = (await bc.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        CREATED_TABS.add(otid)
        other = otid
        ows = f"ws://{CDP_HOST}/devtools/page/{otid}"
        oc = await CDP(ows).open()
        try:
            await oc.send("Page.enable")
            await oc.send("Page.navigate", {"url": f"{H}/other"})
            await asyncio.sleep(3)
            row["other_title_html"] = await oc.evaluate("document.body?document.body.innerText:null")
            row["other_url"] = await oc.evaluate("location.href")
        finally:
            await oc.close()
        s = L.snap()
        row["listener"] = [h for h in s["http"] if "ctl-canvas" not in h]
        row["canvas_paused_after"] = [p for p in cv.paused if "/other" in p]
        row["canvas_paused_n"] = len(cv.paused)
        row["canvas_session_errors"] = cv.errors[:2]
        row["load"] = load1()
    except Exception as e:
        row["error"] = repr(e)[:120]
    finally:
        if bc:
            await bc.close()
        await c.close()
        await close_tab(tid)
        if other:
            await close_tab(other)
        L.stop()
    return row


# ───────────────────────── Çıktı ─────────────────────────
def brief(h: list[str]) -> str:
    return ",".join(h) if h else "0"


def tablo(sm: dict) -> str:
    o: list[str] = [f"Chrome {sm['chrome']} · yük başı {sm['load_start']} sonu {sm['load_end']}"]
    for r in sm.get("M1", []):
        o.append(f"M1|{r['v']}|{r['var']}|http={brief(r.get('http', []))}|acc={r.get('http_acc')}"
                 f"|raw={r.get('raw_acc')}|udp4={r.get('udp4')}|udp6={r.get('udp6')}"
                 f"|stun={r.get('stun')}|fetch={r.get('fetch')}|page={r.get('page')}"
                 f"|viol={r.get('viol')}|exc={r.get('exc')}|y={r.get('load')}|{r.get('error', '')}")
    for r in sm.get("M2", []):
        pr = r.get("probe", {})
        o.append(f"M2|{r['t']}|{r['m']}|{r['mode']}|ret={r.get('ret')}|popup={r.get('popups')}"
                 f"|href={pr.get('href')}|org={pr.get('origin')}|ls={pr.get('ls')}"
                 f"|fetch={pr.get('fetch')}|img={pr.get('img')}|bcn={pr.get('beacon')}|viol={pr.get('viol')}"
                 f"|lst={r.get('listener')}|acc={r.get('acc')}|foreign={r.get('foreign_new_ignored')}|fnav={r.get('fetch_nav')}|fall={r.get('fetch_all')}"
                 f"|fr={r.get('frames')}|y={r.get('load')}|{r.get('error', '')}")
    for r in sm.get("M3", []):
        o.append("M3|" + json.dumps(r, ensure_ascii=False))
    for r in sm.get("M4", []):
        o.append("M4|" + json.dumps(r, ensure_ascii=False))
    if "M5" in sm:
        o.append("M5|" + json.dumps(sm["M5"], ensure_ascii=False))
    o.append(f"temizlik: {sm['cleanup']}")
    return "\n".join(o)


async def cleanup() -> dict:
    left_t, left_c = [], []
    for t in list(CREATED_TABS):
        await close_tab(t)
    if CREATED_CTX:
        try:
            c = await CDP(browser_ws()).open()
            for ctx in list(CREATED_CTX):
                try:
                    await c.send("Target.disposeBrowserContext", {"browserContextId": ctx})
                except Exception:
                    left_c.append(ctx)
                CREATED_CTX.discard(ctx)
            await c.close()
        except Exception:
            left_c += list(CREATED_CTX)
    return {"tabs_left": left_t, "ctx_left": left_c, "pages_now": len(list_pages())}


async def main(only: set[str], md: bool) -> None:
    pages_before = len(list_pages())
    sm: dict = {"chrome": chrome_version(), "load_start": load1(), "pages_before": pages_before,
                "uptime": subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()}
    try:
        for name, fn in (("M1", m1), ("M2", m2), ("M3", m3), ("M4", m4), ("M5", m5)):
            if name in only:
                sm[name] = await fn()
    finally:
        sm["cleanup"] = await cleanup()
        sm["load_end"] = load1()
        sm["load_min_max"] = [min(LOADS), max(LOADS)]
    print(tablo(sm) if md else json.dumps(sm, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--host":
        asyncio.run(host_main(sys.argv[2]))
    else:
        sel = {"M1", "M2", "M3", "M4", "M5"}
        if "--only" in sys.argv:
            sel = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        asyncio.run(main(sel, "--tablo" in sys.argv))

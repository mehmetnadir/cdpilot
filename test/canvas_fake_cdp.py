#!/usr/bin/env python3
"""Fake-CDP and E2E harness for `cdpilot canvas` lane B tests (`canvas host:`).

Modes:
  python3 test/canvas_fake_cdp.py <path/to/cdpilot.py>
      Runs all browser-free fake-CDP and unit scenarios, prints one JSON object.
  python3 test/canvas_fake_cdp.py --e2e <path/to/cdpilot.py> <path/to/bin/cdpilot.js>
      Runs the K9 / C1 e2e gate against shared Chrome on 127.0.0.1:9333.
"""
import asyncio
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class FakeWS:
    """In-process fake browser WebSocket recording CDP traffic and emitting events."""

    def __init__(self, patch_value=None, patch_missing=False):
        self.sent = []
        self.q = asyncio.Queue()
        self.closed = False
        self.patch_value = patch_value or {
            "ok": True,
            "ops": {"add": 2, "del": 1, "move": 0, "upd": 1},
            "ms": 3.2,
            "t_paint": 1700000000123,
        }
        self.patch_missing = patch_missing
        self.frame_tree_url = None

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        cid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        sid = msg.get("sessionId")

        if method == "Target.createBrowserContext":
            self._reply(cid, {"browserContextId": "CTX-1"})
        elif method == "Target.createTarget":
            self._reply(cid, {"targetId": "TGT-1"})
        elif method == "Target.attachToTarget":
            self._reply(cid, {"sessionId": "SES-1"})
        elif method in (
            "Page.enable",
            "Runtime.enable",
            "Runtime.addBinding",
            "Fetch.enable",
            "Emulation.setFocusEmulationEnabled",
            "Page.setDocumentContent",
        ):
            self._reply(cid, {}, sid=sid)
        elif method == "Page.navigate":
            url = params.get("url") or ""
            # Emit Fetch.requestPaused for the document before completing navigate
            self.emit_event("Fetch.requestPaused", {
                "requestId": f"REQ-NAV-{cid}",
                "request": {"url": url, "method": "GET", "headers": {}},
                "frameId": "FRM-1",
                "resourceType": "Document",
            }, sid=sid or "SES-1")
            self._reply(cid, {"frameId": "FRM-1", "loaderId": "LDR-1"}, sid=sid)
        elif method == "Page.getFrameTree":
            u = self.frame_tree_url or "http://cdpilot-canvas.invalid/main/"
            self._reply(cid, {"frameTree": {"frame": {"id": "FRM-1", "url": u}}}, sid=sid)
        elif method == "Runtime.evaluate":
            expr = params.get("expression") or ""
            if "__cdpilotCanvas.patch(" in expr:
                if self.patch_missing:
                    self._reply(cid, {"result": {"type": "undefined"}}, sid=sid)
                else:
                    self._reply(cid, {
                        "result": {"type": "object", "value": self.patch_value}
                    }, sid=sid)
            elif "requestAnimationFrame" in expr:
                self._reply(cid, {"result": {"type": "number", "value": 1700000000999}}, sid=sid)
            else:
                self._reply(cid, {"result": {"type": "undefined"}}, sid=sid)
        elif method in ("Target.closeTarget", "Target.disposeBrowserContext"):
            self._reply(cid, {"success": True})
        elif method in ("Fetch.fulfillRequest", "Fetch.failRequest", "Fetch.continueRequest"):
            self._reply(cid, {}, sid=sid)
        else:
            self._reply(cid, {}, sid=sid)

    def _reply(self, cid, result, sid=None):
        msg = {"id": cid, "result": result}
        if sid:
            msg["sessionId"] = sid
        self.q.put_nowait(json.dumps(msg))

    def emit_event(self, method, params, sid="SES-1"):
        msg = {"method": method, "params": params}
        if sid:
            msg["sessionId"] = sid
        self.q.put_nowait(json.dumps(msg))

    async def recv(self):
        return await self.q.get()

    async def close(self):
        self.closed = True


class FakeCDPServer:
    """Real TCP + WebSocket fake CDP server on 127.0.0.1:0 for subprocess CLI tests."""

    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(32)
        self.port = self.srv.getsockname()[1]
        self.lock = threading.Lock()
        self.log = []
        self.contexts = set()
        self.targets = {}
        self.seq = 0
        self.running = True
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        try:
            self.srv.close()
        except OSError:
            pass

    def _record(self, item):
        with self.lock:
            self.log.append(item)

    def _accept_loop(self):
        while self.running:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                break
            threading.Thread(target=self._serve_conn, args=(conn,), daemon=True).start()

    @staticmethod
    def _recv_exact(conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    @staticmethod
    def _ws_send(conn, obj):
        data = json.dumps(obj).encode("utf-8")
        head = bytearray([0x81])
        if len(data) < 126:
            head.append(len(data))
        elif len(data) < 65536:
            head.append(126)
            head.extend(struct.pack(">H", len(data)))
        else:
            head.append(127)
            head.extend(struct.pack(">Q", len(data)))
        conn.sendall(bytes(head) + data)

    def _ws_frames(self, conn):
        while self.running:
            b1, b2 = self._recv_exact(conn, 2)
            opcode, length = b1 & 0x0F, b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(conn, 2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(conn, 8))[0]
            mask = self._recv_exact(conn, 4) if (b2 & 0x80) else b"\x00\x00\x00\x00"
            payload = bytes(c ^ mask[i % 4] for i, c in enumerate(self._recv_exact(conn, length)))
            if opcode == 0x8:
                return
            if opcode == 0x9:
                conn.sendall(bytes([0x8A, len(payload)]) + payload)
                continue
            if opcode == 0x1:
                yield payload.decode("utf-8", "replace")

    def _serve_conn(self, conn):
        conn_contexts = set()
        try:
            conn.settimeout(30.0)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            lines = head.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
            parts = lines[0].split(" ")
            path = parts[1] if len(parts) > 1 else "/"
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            if headers.get("upgrade", "").lower() != "websocket":
                if path.split("?", 1)[0] == "/json/version":
                    body = json.dumps({
                        "Browser": "FakeChrome/152.0.0.0",
                        "Protocol-Version": "1.3",
                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/browser/FAKE-GUID",
                    }).encode("utf-8")
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
                        + body
                    )
                else:
                    conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                return

            key = headers.get("sec-websocket-key", "")
            accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
            ).decode()
            conn.sendall((
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode("ascii"))

            for text in self._ws_frames(conn):
                msg = json.loads(text)
                cid = msg.get("id")
                method = msg.get("method")
                params = msg.get("params") or {}
                sid = msg.get("sessionId")
                self._record({"method": method, "params": params, "sessionId": sid})
                res = {}
                if method == "Target.createBrowserContext":
                    with self.lock:
                        self.seq += 1
                        ctx_id = f"CTX-{self.seq}"
                        self.contexts.add(ctx_id)
                        if params.get("disposeOnDetach"):
                            conn_contexts.add(ctx_id)
                    res = {"browserContextId": ctx_id}
                elif method == "Target.createTarget":
                    with self.lock:
                        self.seq += 1
                        tid = f"TARGET-{self.seq}"
                        self.targets[tid] = {
                            "targetId": tid,
                            "browserContextId": params.get("browserContextId"),
                            "url": params.get("url") or "about:blank",
                        }
                    res = {"targetId": tid}
                elif method == "Target.attachToTarget":
                    with self.lock:
                        self.seq += 1
                        new_sid = f"SESSION-{self.seq}"
                    res = {"sessionId": new_sid}
                elif method == "Page.navigate":
                    url = params.get("url") or ""
                    self._ws_send(conn, {
                        "sessionId": sid,
                        "method": "Fetch.requestPaused",
                        "params": {
                            "requestId": f"PAUSED-{cid}",
                            "request": {"url": url, "method": "GET", "headers": {}},
                            "frameId": "FRAME-1",
                            "resourceType": "Document",
                        },
                    })
                    res = {"frameId": "FRAME-1"}
                elif method == "Page.getFrameTree":
                    res = {"frameTree": {"frame": {"id": "FRAME-1", "url": "http://cdpilot-canvas.invalid/main/"}}}
                elif method == "Runtime.evaluate":
                    expr = params.get("expression") or ""
                    if "__cdpilotCanvas.patch(" in expr:
                        res = {
                            "result": {
                                "type": "object",
                                "value": {
                                    "ok": True,
                                    "ops": {"add": 3, "del": 1, "move": 2, "upd": 4},
                                    "ms": 4.5,
                                    "t_paint": 1700000000500,
                                },
                            }
                        }
                    elif "requestAnimationFrame" in expr:
                        res = {"result": {"type": "number", "value": 1700000000400}}
                    else:
                        res = {"result": {"type": "undefined"}}
                elif method == "Target.closeTarget":
                    with self.lock:
                        self.targets.pop(params.get("targetId"), None)
                    res = {"success": True}
                elif method == "Target.disposeBrowserContext":
                    with self.lock:
                        c_id = params.get("browserContextId")
                        self.contexts.discard(c_id)
                        for k in [k for k, v in self.targets.items() if v.get("browserContextId") == c_id]:
                            self.targets.pop(k, None)
                    res = {"success": True}
                reply = {"id": cid, "result": res}
                if sid:
                    reply["sessionId"] = sid
                self._ws_send(conn, reply)
        except Exception:
            pass
        finally:
            with self.lock:
                for c_id in conn_contexts:
                    self.contexts.discard(c_id)
                    for k in [k for k, v in self.targets.items() if v.get("browserContextId") == c_id]:
                        self.targets.pop(k, None)
            try:
                conn.close()
            except OSError:
                pass


def load_cdpilot(path):
    spec = importlib.util.spec_from_file_location("cdpilot_canvas_b_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scenario_setup_and_guards(mod):
    """Test 1-6: exact method order, fulfillRequest CSP + meta, 204 other doc, subresource block, allow-net, error path."""

    async def _run():
        ws = FakeWS()
        host = mod._CanvasHost(ws, "main", allow_net=("api.example.com",))
        reader = asyncio.create_task(host.ws_reader_loop())
        try:
            await host.setup()
            # Give reader loop a tick to process Fetch.fulfillRequest from setup's Page.navigate
            await asyncio.sleep(0.02)
            setup_methods = [
                (m["method"], m.get("sessionId"), m.get("params"))
                for m in ws.sent
            ]

            # 3. Other document URLs (other name, path, query, scheme) -> 204 + host blocked event
            before_other = len(ws.sent)
            for idx, bad_url in enumerate([
                "http://cdpilot-canvas.invalid/other/",
                "http://cdpilot-canvas.invalid/main/sub",
                "http://cdpilot-canvas.invalid/main/?q=1",
                "https://cdpilot-canvas.invalid/main/",
                "http://127.0.0.1:9333/json/version",
            ]):
                ws.emit_event("Fetch.requestPaused", {
                    "requestId": f"OTHER-DOC-{idx}",
                    "request": {"url": bad_url, "method": "GET"},
                    "resourceType": "Document",
                })
            await asyncio.sleep(0.02)
            other_doc_replies = ws.sent[before_other:]

            # 4 & 5. Subresources: blocked by default; allow-net https host -> continueRequest; http same host -> failRequest
            before_sub = len(ws.sent)
            for idx, (rtype, surl) in enumerate([
                ("Script", "https://evil.example.com/app.js"),
                ("Fetch", "https://api.example.com/v1/data"),
                ("Fetch", "http://api.example.com/v1/data"),
                ("Image", "http://127.0.0.1:8080/beacon.png"),
            ]):
                ws.emit_event("Fetch.requestPaused", {
                    "requestId": f"SUB-{idx}",
                    "request": {"url": surl, "method": "GET"},
                    "resourceType": rtype,
                })
            await asyncio.sleep(0.02)
            sub_replies = ws.sent[before_sub:]

            # 6. Error inside requestPaused handler -> 204 for Document, failRequest for Subresource, NEVER continueRequest
            before_err = len(ws.sent)
            host._error_on_paused = True
            ws.emit_event("Fetch.requestPaused", {
                "requestId": "ERR-DOC",
                "request": {"url": "https://api.example.com/doc", "method": "GET"},
                "resourceType": "Document",
            })
            ws.emit_event("Fetch.requestPaused", {
                "requestId": "ERR-SUB",
                "request": {"url": "https://api.example.com/v1/data", "method": "GET"},
                "resourceType": "Fetch",
            })
            await asyncio.sleep(0.02)
            # Also malformed request dict (request=None)
            host._error_on_paused = False
            ws.emit_event("Fetch.requestPaused", {
                "requestId": "ERR-MALFORMED-DOC",
                "request": None,
                "resourceType": "Document",
            })
            ws.emit_event("Fetch.requestPaused", {
                "requestId": "ERR-MALFORMED-SUB",
                "request": None,
                "resourceType": "XHR",
            })
            await asyncio.sleep(0.02)
            err_replies = ws.sent[before_err:]

            ev_resp = await host.handle_op({"op": "events", "after": 0, "max": 100})
            return {
                "setup_methods": setup_methods,
                "base_csp": mod._canvas_csp_header(()),
                "allow_csp": mod._canvas_csp_header(("api.example.com",)),
                "other_doc_replies": other_doc_replies,
                "sub_replies": sub_replies,
                "err_replies": err_replies,
                "events": ev_resp,
            }
        finally:
            reader.cancel()
            with contextlib.suppress(BaseException):
                await reader

    return asyncio.run(_run())


def scenario_set_patch_and_doc_loss(mod):
    """Test 7 & 8: set -> setDocumentContent; frameNavigated away -> next patch re-navigates first; empty runtime -> runtime missing."""

    async def _run():
        # Part A: with runtime responder
        ws = FakeWS()
        host = mod._CanvasHost(ws, "main")
        reader = asyncio.create_task(host.ws_reader_loop())
        try:
            await host.setup()
            await asyncio.sleep(0.01)
            ws.sent.clear()

            # set
            set_res = await host.handle_op({"op": "set", "html": "<h1>Hello</h1>"})
            set_calls = list(ws.sent)
            ws.sent.clear()

            # frameNavigated to another URL -> next patch must re-navigate first and emit 'nav' host event
            ws.emit_event("Page.frameNavigated", {
                "frame": {"id": "FRM-1", "url": "about:blank"},
            })
            await asyncio.sleep(0.01)

            patch_res = await host.handle_op({
                "op": "patch",
                "html": '<div id="x">World & "quotes"</div>',
                "final": True,
            })
            await asyncio.sleep(0.01)
            patch_calls = list(ws.sent)
            ev_res = await host.handle_op({"op": "events", "after": 0, "max": 100})
        finally:
            reader.cancel()
            with contextlib.suppress(BaseException):
                await reader

        # Part B: with empty runtime (patch_missing=True, CANVAS_RUNTIME_JS == '')
        ws_empty = FakeWS(patch_missing=True)
        host_empty = mod._CanvasHost(ws_empty, "main")
        reader_empty = asyncio.create_task(host_empty.ws_reader_loop())
        try:
            await host_empty.setup()
            await asyncio.sleep(0.01)
            saved_rt = mod.CANVAS_RUNTIME_JS
            mod.CANVAS_RUNTIME_JS = ""
            try:
                missing_res = await host_empty.handle_op({
                    "op": "patch",
                    "html": "<p>test</p>",
                    "final": True,
                })
            finally:
                mod.CANVAS_RUNTIME_JS = saved_rt
        finally:
            reader_empty.cancel()
            with contextlib.suppress(BaseException):
                await reader_empty

        return {
            "set_res": set_res,
            "set_calls": set_calls,
            "patch_res": patch_res,
            "patch_calls": patch_calls,
            "events_after_nav": ev_res,
            "missing_res": missing_res,
        }

    return asyncio.run(_run())


def scenario_bindings_and_limits(mod):
    """Test 9, 10, 12: bindingCalled filtering/rate/truncation, unknown op -> code 2, html over limit -> code 2."""

    async def _run():
        ws = FakeWS()
        host = mod._CanvasHost(ws, "main")
        reader = asyncio.create_task(host.ws_reader_loop())
        try:
            await host.setup()
            await asyncio.sleep(0.01)

            # Spoofed host/paint types from bindingCalled must be dropped (K5)
            for bad_type in ("blocked", "paint", "nav", "closed", "keydown", ""):
                ws.emit_event("Runtime.bindingCalled", {
                    "name": mod.CANVAS_BINDING,
                    "payload": json.dumps({"type": bad_type, "action": "spoof", "id": "b1", "data": "x"}),
                })
            # Bad action name (contains space / special chars) must be dropped
            ws.emit_event("Runtime.bindingCalled", {
                "name": mod.CANVAS_BINDING,
                "payload": json.dumps({"type": "click", "action": "bad action!", "id": "b2", "data": "x"}),
            })
            # Valid click, submit, input events (with oversized >1KB data on input)
            ws.emit_event("Runtime.bindingCalled", {
                "name": mod.CANVAS_BINDING,
                "payload": json.dumps({"type": "click", "action": "save_item", "id": "btn-1", "data": {"k": 1}}),
            })
            ws.emit_event("Runtime.bindingCalled", {
                "name": mod.CANVAS_BINDING,
                "payload": json.dumps({"type": "submit", "action": "form_sub", "id": "f-1", "data": "ok"}),
            })
            ws.emit_event("Runtime.bindingCalled", {
                "name": mod.CANVAS_BINDING,
                "payload": json.dumps({"type": "input", "action": "edit", "id": "in-1", "data": "A" * 2048}),
            })
            await asyncio.sleep(0.02)
            ev1 = await host.handle_op({"op": "events", "after": 0, "max": 100})

            # Rate limit: send 110 valid events in the same second -> excess dropped
            for i in range(110):
                ws.emit_event("Runtime.bindingCalled", {
                    "name": mod.CANVAS_BINDING,
                    "payload": json.dumps({"type": "click", "action": "burst", "id": f"b-{i}", "data": i}),
                })
            await asyncio.sleep(0.02)
            ev_burst = await host.handle_op({"op": "events", "after": ev1["next"], "max": 100})

            # Unknown op -> code 2
            bad_op = await host.handle_op({"op": "eval", "expression": "1+1"})
            non_dict_op = await host.handle_op("not-a-dict")

            # HTML over CANVAS_HTML_MAX -> refused by host with code 2
            oversized = "a" * (mod.CANVAS_HTML_MAX + 10)
            over_set = await host.handle_op({"op": "set", "html": oversized})
            over_patch = await host.handle_op({"op": "patch", "html": oversized, "final": True})

            return {
                "ev1": ev1,
                "burst_count": len(ev_burst["events"]),
                "burst_dropped": ev_burst["dropped"],
                "bad_op": bad_op,
                "non_dict_op": non_dict_op,
                "over_set": over_set,
                "over_patch": over_patch,
            }
        finally:
            reader.cancel()
            with contextlib.suppress(BaseException):
                await reader

    return asyncio.run(_run())


def scenario_cli_and_socket_integration(mod):
    """Test 10, 11, 12, 13, 15, 16: real detached host over fake CDP server, perms 0700/0600, bad names, slog, Windows."""
    fake_cdp = FakeCDPServer()
    tmp_home = tempfile.mkdtemp(prefix="cdpilot-canvas-b-")
    tmp_profile = os.path.join(tmp_home, "profile")
    os.makedirs(tmp_profile, mode=0o700, exist_ok=True)
    py_file = os.path.join(ROOT, "src", "cdpilot.py")
    env = {
        **os.environ,
        "CDPILOT_HOME": tmp_home,
        "CDPILOT_PROFILE": tmp_profile,
        "CDP_PORT": str(fake_cdp.port),
        "CDPILOT_NO_AUTOLAUNCH": "1",
        "CDPILOT_LOG": "0",
    }

    def run_py(*args, input_text=None, extra_env=None):
        e = {**env, **(extra_env or {})}
        return subprocess.run(
            [sys.executable, py_file, *args],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=15,
            env=e,
        )

    try:
        # 11. Bad canvas names and bad --allow-net values -> exit 2
        bad_names = []
        for bn in ("../evil", "bad/name", "UPPER", "a" * 33, "", "bad.dot"):
            r = run_py("canvas", "open", f"--name={bn}")
            bad_names.append({"name": bn, "code": r.returncode, "stderr": r.stderr.strip()})

        bad_allow_net = []
        for bh in ("https://api.example.com", "api.example.com:443", "api.example.com/path",
                   "*.example.com", "127.0.0.1", "evil.com; script-src *"):
            r = run_py("canvas", "open", "--allow-net", bh)
            bad_allow_net.append({"host": bh, "code": r.returncode, "stderr": r.stderr.strip()})

        # Pre-existing canvas dir with group/other bits (0755) -> host/open refuses with exit 2
        bad_home = tempfile.mkdtemp(prefix="cdpilot-canvas-baddir-")
        bad_prof = os.path.join(bad_home, "profile")
        bad_cdir = os.path.join(bad_prof, "canvas")
        os.makedirs(bad_cdir, mode=0o755, exist_ok=True)
        os.chmod(bad_cdir, 0o755)
        r_baddir = run_py("canvas", "open", extra_env={
            "CDPILOT_HOME": bad_home,
            "CDPILOT_PROFILE": bad_prof,
        })
        shutil.rmtree(bad_home, ignore_errors=True)

        # Open canvas `main` against FakeCDPServer
        r_open1 = run_py("canvas", "open", "--allow-net", "api.example.com")
        # Second open on same name pings and exits 0 with same line
        r_open2 = run_py("canvas", "open")

        cdir = os.path.join(tmp_profile, "canvas")
        sock_path = os.path.join(cdir, "main.sock")
        reg_path = os.path.join(cdir, "main.json")
        dir_mode = os.lstat(cdir).st_mode & 0o777
        sock_mode = os.lstat(sock_path).st_mode & 0o777
        with open(reg_path, "r", encoding="utf-8") as f:
            reg_data = json.load(f)

        # Raw socket test: unknown op -> {ok: false, code: 2}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5.0)
            s.connect(sock_path)
            s.sendall(b'{"op":"eval","code":"alert(1)"}\n')
            raw_unknown = json.loads(s.recv(4096).decode("utf-8"))

        # set & patch via stdin ('-') and file
        r_set = run_py("canvas", "set", "-", input_text="<h1>Hello Canvas</h1>")
        r_patch = run_py("canvas", "patch", "-", input_text="<h1>Hello Updated</h1>")
        r_list = run_py("canvas", "list")

        # Close
        r_close = run_py("canvas", "close")
        files_after_close = os.listdir(cdir) if os.path.isdir(cdir) else []

        # Long PROFILE_DIR > 100 bytes -> socket moves to short runtime dir
        long_prof = os.path.join(tmp_home, "p" * 95, "profile")
        os.makedirs(long_prof, mode=0o700, exist_ok=True)
        r_long_open = run_py("canvas", "open", "--name", "longtest", extra_env={"CDPILOT_PROFILE": long_prof})
        long_reg_path = os.path.join(long_prof, "canvas", "longtest.json")
        long_sock = None
        if os.path.exists(long_reg_path):
            with open(long_reg_path, "r", encoding="utf-8") as f:
                long_sock = json.load(f).get("sock")
        r_long_close = run_py("canvas", "close", "--name", "longtest", extra_env={"CDPILOT_PROFILE": long_prof})

        # stop-all closes active canvas hosts
        r_open_stop = run_py("canvas", "open", "--name", "forstop")
        r_stop_all = run_py("stop-all")
        stop_all_cleaned = not os.path.exists(os.path.join(cdir, "forstop.sock"))

        # 15. _slog_redact_args redacts HTML arguments and --html
        slog_pos, _ = mod._slog_redact_args("canvas", ["set", "  <div>secret token</div>", "--name", "main"])
        slog_flag, _ = mod._slog_redact_args("canvas", ["patch", "--html=<p>hello</p>", "--html", "<span>world</span>"])
        slog_file, _ = mod._slog_redact_args("canvas", ["set", "page.html", "--name", "main"])

        # 16. Windows check (simulate missing socket.AF_UNIX for every subcommand)
        win_results = {}
        saved_af = getattr(mod.socket, "AF_UNIX", None)
        try:
            if hasattr(mod.socket, "AF_UNIX"):
                delattr(mod.socket, "AF_UNIX")
            for sub in ("open", "set", "patch", "close", "list", "stream", "watch", "events"):
                err_buf = io.StringIO()
                code = 0
                with contextlib.redirect_stderr(err_buf):
                    try:
                        mod.cmd_canvas_dispatch([sub])
                    except SystemExit as e:
                        code = e.code
                win_results[sub] = {"code": code, "stderr": err_buf.getvalue().strip()}
        finally:
            if saved_af is not None:
                setattr(mod.socket, "AF_UNIX", saved_af)

        return {
            "bad_names": bad_names,
            "bad_allow_net": bad_allow_net,
            "baddir_code": r_baddir.returncode,
            "open1": {"code": r_open1.returncode, "out": r_open1.stdout.strip(), "err": r_open1.stderr.strip()},
            "open2": {"code": r_open2.returncode, "out": r_open2.stdout.strip()},
            "dir_mode": dir_mode,
            "sock_mode": sock_mode,
            "reg_data": reg_data,
            "raw_unknown": raw_unknown,
            "set": {"code": r_set.returncode, "out": r_set.stdout.strip()},
            "patch": {"code": r_patch.returncode, "out": r_patch.stdout.strip()},
            "list": {"code": r_list.returncode, "out": r_list.stdout.strip()},
            "close": {"code": r_close.returncode, "out": r_close.stdout.strip()},
            "files_after_close": files_after_close,
            "long_open": {
                "code": r_long_open.returncode,
                "out": r_long_open.stdout.strip(),
                "sock": long_sock,
                "sock_len": len((long_sock or "").encode("utf-8")),
                "close_code": r_long_close.returncode,
            },
            "stop_all": {
                "open_code": r_open_stop.returncode,
                "stop_code": r_stop_all.returncode,
                "cleaned": stop_all_cleaned,
            },
            "slog": {
                "pos": slog_pos,
                "flag": slog_flag,
                "file": slog_file,
            },
            "windows": win_results,
        }
    finally:
        fake_cdp.stop()
        shutil.rmtree(tmp_home, ignore_errors=True)


def run_e2e(py_path, cli_js_path):
    """K9 + C1 e2e gate against shared Chrome on 127.0.0.1:9333."""
    import urllib.request
    import websockets

    ver = json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/version", timeout=5).read())
    browser_ws = ver["webSocketDebuggerUrl"]
    browser_ver = ver.get("Browser", "unknown")

    # Start loopback HTTP/TCP listener and UDP listener on port 0
    http_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    http_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    http_srv.bind(("127.0.0.1", 0))
    http_srv.listen(64)
    http_port = http_srv.getsockname()[1]

    udp_srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_srv.bind(("127.0.0.1", 0))
    udp_port = udp_srv.getsockname()[1]

    lock = threading.Lock()
    phase = ["guarded"]
    counts = {
        "guarded": {"http_paths": {}, "raw_tcp": 0, "udp": 0},
        "counter": {"http_paths": {}, "raw_tcp": 0, "udp": 0},
    }
    running = [True]

    def _handle_http_conn(conn, cur_phase):
        try:
            conn.settimeout(3.0)
            data = conn.recv(2048)
            first = data.decode("latin-1", "replace").split("\r\n", 1)[0] if data else ""
            parts = first.split(" ")
            path = (parts[1] if len(parts) > 1 else "/raw_tcp").lstrip("/") or "root"
            with lock:
                cur = counts[cur_phase]
                if first:
                    cur["http_paths"][path] = cur["http_paths"].get(path, 0) + 1
                else:
                    cur["raw_tcp"] += 1
            conn.sendall(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            with lock:
                counts[cur_phase]["raw_tcp"] += 1
        finally:
            with contextlib.suppress(OSError):
                conn.close()

    def _http_loop():
        while running[0]:
            try:
                conn, _ = http_srv.accept()
            except OSError:
                break
            threading.Thread(
                target=_handle_http_conn,
                args=(conn, phase[0]),
                daemon=True,
            ).start()

    def _udp_loop():
        while running[0]:
            try:
                data, _ = udp_srv.recvfrom(2048)
                if data:
                    with lock:
                        counts[phase[0]]["udp"] += 1
            except OSError:
                break

    t_http = threading.Thread(target=_http_loop, daemon=True)
    t_udp = threading.Thread(target=_udp_loop, daemon=True)
    t_http.start()
    t_udp.start()

    tmp_home = tempfile.mkdtemp(prefix="cdpilot-canvas-e2e-")
    tmp_prof = os.path.join(tmp_home, "profile")
    os.makedirs(tmp_prof, mode=0o700, exist_ok=True)
    fixture_src = os.path.join(HERE, "fixtures", "canvas", "exfil.html")
    with open(fixture_src, "r", encoding="utf-8") as f:
        exfil_html = (
            f.read()
            .replace("__HTTP_PORT__", str(http_port))
            .replace("__UDP_PORT__", str(udp_port))
        )
    rendered_path = os.path.join(tmp_home, "exfil_rendered.html")
    with open(rendered_path, "w", encoding="utf-8") as f:
        f.write("<script>window.__EXFIL_BLOB_DELAY__=60000;</script>\n" + exfil_html)

    env = {
        **os.environ,
        "CDPILOT_HOME": tmp_home,
        "CDPILOT_PROFILE": tmp_prof,
        "CDP_PORT": "9333",
        "CDPILOT_NO_AUTOLAUNCH": "1",
        "CDPILOT_LOG": "0",
        "CDPILOT_DAEMON": "0",
    }

    def cli(*args):
        return subprocess.run(
            ["node", cli_js_path, *args],
            capture_output=True,
            text=True,
            timeout=25,
            env=env,
        )

    os.environ["CDPILOT_HOME"] = tmp_home
    os.environ["CDPILOT_PROFILE"] = tmp_prof
    os.environ["CDP_PORT"] = "9333"
    os.environ["CDPILOT_NO_AUTOLAUNCH"] = "1"
    os.environ["CDPILOT_LOG"] = "0"

    try:
        # Connect to shared Chrome 9333
        r_conn = cli("connect", "9333")
        if r_conn.returncode != 0:
            raise RuntimeError(f"connect 9333 failed: {r_conn.stderr or r_conn.stdout}")

        mod = load_cdpilot(py_path)

        # (a) Guarded canvas leak test
        phase[0] = "guarded"
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cmd_canvas_open(["--name", "e2e"])
            mod.cmd_canvas_set([rendered_path, "--name", "e2e"])

        # Poll events until NetworkService processes at least one blocked navigation/request
        host_blocked = []
        poll_deadline = time.monotonic() + 12.0
        while time.monotonic() < poll_deadline:
            ev_reply = mod._canvas_request(
                "e2e",
                {"op": "events", "after": 0, "max": 100, "wait_ms": 400},
                timeout=15.0,
            )
            host_blocked = [
                e for e in (ev_reply.get("events") or [])
                if e.get("src") == "host" and e.get("type") == "blocked"
            ]
            if host_blocked:
                break
            time.sleep(0.05)

        # Also exercise blob: and about:blank top-level navigation in the guarded canvas
        r_blob = mod._canvas_request(
            "e2e",
            {
                "op": "set",
                "html": "<script>window.__EXFIL_BLOB_DELAY__=10;</script>\n" + exfil_html,
            },
            timeout=20.0,
        )
        time.sleep(0.25)
        ev_reply = mod._canvas_request("e2e", {"op": "events", "after": 0, "max": 100}, timeout=15.0)
        host_blocked = [
            e for e in (ev_reply.get("events") or [])
            if e.get("src") == "host" and e.get("type") == "blocked"
        ]

        # Read registry for SIGKILL test (c)
        reg_path = os.path.join(tmp_prof, "canvas", "e2e.json")
        with open(reg_path, "r", encoding="utf-8") as f:
            reg = json.load(f)
        host_pid = int(reg["pid"])
        canvas_tid = reg["targetId"]
        canvas_ctx = reg["browserContextId"]

        # (c) SIGKILL host pid -> within 5 s canvas target and browser context are gone
        async def _verify_sigkill():
            async with websockets.connect(browser_ws, max_size=16 * 1024 * 1024) as ws:
                seq = 0

                async def bcall(m, p=None):
                    nonlocal seq
                    seq += 1
                    cid = seq
                    await ws.send(json.dumps({"id": cid, "method": m, "params": p or {}}))
                    while True:
                        msg = json.loads(await ws.recv())
                        if msg.get("id") == cid:
                            return msg.get("result") or {}

                t_before = await bcall("Target.getTargets")
                c_before = await bcall("Target.getBrowserContexts")
                tid_present_before = any(
                    t.get("targetId") == canvas_tid for t in (t_before.get("targetInfos") or [])
                )
                ctx_present_before = canvas_ctx in (c_before.get("browserContextIds") or [])

                t0 = time.monotonic()
                os.kill(host_pid, signal.SIGKILL)
                deadline = t0 + 5.0
                tid_gone = False
                ctx_gone = False
                while time.monotonic() < deadline:
                    t_now = await bcall("Target.getTargets")
                    c_now = await bcall("Target.getBrowserContexts")
                    tid_alive = any(
                        t.get("targetId") == canvas_tid for t in (t_now.get("targetInfos") or [])
                    )
                    ctx_alive = canvas_ctx in (c_now.get("browserContextIds") or [])
                    if not tid_alive and not ctx_alive:
                        tid_gone = True
                        ctx_gone = True
                        break
                    await asyncio.sleep(0.05)
                elapsed_ms = round((time.monotonic() - t0) * 1000.0, 1)
                return {
                    "tid_present_before": tid_present_before,
                    "ctx_present_before": ctx_present_before,
                    "tid_gone": tid_gone,
                    "ctx_gone": ctx_gone,
                    "elapsed_ms": elapsed_ms,
                }

        sigkill_res = asyncio.run(_verify_sigkill())

        # (b) Counter-experiment: plain tab in our own isolated browser context without the guard
        phase[0] = "counter"

        async def _run_counter():
            async with websockets.connect(browser_ws, max_size=16 * 1024 * 1024) as ws:
                seq = 0

                async def bcall(m, p=None, sid=None):
                    nonlocal seq
                    seq += 1
                    cid = seq
                    payload = {"id": cid, "method": m, "params": p or {}}
                    if sid:
                        payload["sessionId"] = sid
                    await ws.send(json.dumps(payload))
                    while True:
                        msg = json.loads(await ws.recv())
                        if msg.get("id") == cid:
                            return msg.get("result") or {}

                c_res = await bcall("Target.createBrowserContext", {"disposeOnDetach": True})
                c_ctx = c_res["browserContextId"]
                try:
                    t_res = await bcall("Target.createTarget", {
                        "url": "about:blank",
                        "browserContextId": c_ctx,
                    })
                    c_tid = t_res["targetId"]
                    a_res = await bcall("Target.attachToTarget", {"targetId": c_tid, "flatten": True})
                    c_sid = a_res["sessionId"]
                    await bcall("Page.enable", {}, sid=c_sid)
                    await asyncio.sleep(0.15)
                    ft = await bcall("Page.getFrameTree", {}, sid=c_sid)
                    fid = ft["frameTree"]["frame"]["id"]
                    await bcall(
                        "Page.setDocumentContent",
                        {
                            "frameId": fid,
                            "html": "<script>window.__EXFIL_BLOB_DELAY__=60000;</script>\n" + exfil_html,
                        },
                        sid=c_sid,
                    )
                    c_deadline = time.monotonic() + 8.0
                    while time.monotonic() < c_deadline:
                        with lock:
                            c_http = sum(counts["counter"]["http_paths"].values()) + counts["counter"]["raw_tcp"]
                            c_udp = counts["counter"]["udp"]
                        if c_http >= 4 and c_udp > 0:
                            await asyncio.sleep(0.25)
                            break
                        await asyncio.sleep(0.05)
                finally:
                    with contextlib.suppress(Exception):
                        await bcall("Target.disposeBrowserContext", {"browserContextId": c_ctx})

        asyncio.run(_run_counter())
        time.sleep(0.1)

        with lock:
            g_counts = json.loads(json.dumps(counts["guarded"]))
            c_counts = json.loads(json.dumps(counts["counter"]))

        g_total = sum(g_counts["http_paths"].values()) + g_counts["raw_tcp"] + g_counts["udp"]
        c_total = sum(c_counts["http_paths"].values()) + c_counts["raw_tcp"] + c_counts["udp"]
        uptime_out = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5).stdout.strip()

        return {
            "browser": browser_ver,
            "uptime": uptime_out,
            "guarded": {
                "total_hits": g_total,
                "http_paths": g_counts["http_paths"],
                "raw_tcp": g_counts["raw_tcp"],
                "udp": g_counts["udp"],
                "host_blocked_count": len(host_blocked),
                "host_blocked_sample": host_blocked[:5],
                "blob_nav_set_ok": bool(r_blob.get("ok")),
            },
            "counter": {
                "total_hits": c_total,
                "http_paths": c_counts["http_paths"],
                "raw_tcp": c_counts["raw_tcp"],
                "udp": c_counts["udp"],
            },
            "sigkill": sigkill_res,
        }
    finally:
        running[0] = False
        with contextlib.suppress(Exception):
            reg_p = os.path.join(tmp_prof, "canvas", "e2e.json")
            if os.path.exists(reg_p):
                with open(reg_p, "r", encoding="utf-8") as rf:
                    os.kill(int(json.load(rf)["pid"]), signal.SIGKILL)
        with contextlib.suppress(OSError):
            http_srv.close()
        with contextlib.suppress(OSError):
            udp_srv.close()
        shutil.rmtree(tmp_home, ignore_errors=True)


SCENARIOS = {
    "setup_and_guards": scenario_setup_and_guards,
    "set_patch_and_doc_loss": scenario_set_patch_and_doc_loss,
    "bindings_and_limits": scenario_bindings_and_limits,
    "cli_and_socket": scenario_cli_and_socket_integration,
}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--e2e":
        py_path = sys.argv[2]
        cli_js = sys.argv[3]
        try:
            res = run_e2e(py_path, cli_js)
        except BaseException:
            res = {"error": traceback.format_exc()}
        sys.stdout.write(json.dumps(res) + "\n")
        return

    py_path = sys.argv[1]
    mod = load_cdpilot(py_path)
    out = {}
    for name, fn in SCENARIOS.items():
        try:
            out[name] = fn(mod)
        except BaseException:
            out[name] = {"error": traceback.format_exc()}
    sys.stdout.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()

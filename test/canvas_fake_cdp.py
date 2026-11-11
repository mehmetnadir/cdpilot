#!/usr/bin/env python3
"""Fake-CDP and E2E harness for `cdpilot canvas` lane B tests (`canvas host:`).

Modes:
  python3 test/canvas_fake_cdp.py <path/to/cdpilot.py>
      Runs all browser-free fake-CDP and unit scenarios, prints one JSON object.
  python3 test/canvas_fake_cdp.py --e2e <path/to/cdpilot.py> <path/to/bin/cdpilot.js> <127.0.0.1:port>
      Runs the K9 / C1 e2e gate against the browser at <127.0.0.1:port> (test.js passes
      CDPILOT_CANVAS_E2E_CDP or the port of its own headless Chrome; this script never launches one).
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

    def __init__(self, patch_value=None, patch_missing=False, nav_error_text=None, swap_ctx_on=None,
                 swap_reply_ok=False):
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
        self.frame_tree_url = None        # override: Page.getFrameTree lies about the main frame URL
        self.nav_error_text = nav_error_text
        self.swap_ctx_on = swap_ctx_on    # 'reset' | 'patch': swap the document when that write arrives
        self.swap_reply_ok = swap_reply_ok
        self.cur_url = "about:blank"
        self.ctx_seq = 0
        self.cur_ctx = self._new_ctx_id()
        self.ctx_log = []                 # (method, uniqueContextId sent, current ctx at arrival)

    def _new_ctx_id(self):
        self.ctx_seq += 1
        return f"UCTX-{self.ctx_seq}"

    def swap_document(self, url="about:blank"):
        """The page replaced the document: old context destroyed, new one created (real order)."""
        old = self.cur_ctx
        self.emit_event("Runtime.executionContextDestroyed", {
            "executionContextId": self.ctx_seq, "executionContextUniqueId": old})
        self.emit_event("Runtime.executionContextsCleared", {})
        self.emit_event("Page.frameNavigated", {"frame": {"id": "FRM-1", "url": url}})
        self.cur_url = url
        self.cur_ctx = self._new_ctx_id()
        self.emit_event("Runtime.executionContextCreated", {"context": {
            "id": self.ctx_seq, "uniqueId": self.cur_ctx, "origin": "null",
            "auxData": {"isDefault": True, "type": "default", "frameId": "FRM-1"}}})

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
            "Page.resetNavigationHistory",
        ):
            self._reply(cid, {}, sid=sid)
        elif method == "Page.addScriptToEvaluateOnNewDocument":
            self._reply(cid, {"identifier": "1"}, sid=sid)
        elif method == "Page.navigate":
            url = params.get("url") or ""
            if self.nav_error_text:
                self._reply(cid, {"frameId": "FRM-1", "errorText": self.nav_error_text}, sid=sid)
                return
            # Emit Fetch.requestPaused for the document before completing navigate
            self.emit_event("Fetch.requestPaused", {
                "requestId": f"REQ-NAV-{cid}",
                "request": {"url": url, "method": "GET", "headers": {}},
                "frameId": "FRM-1",
                "resourceType": "Document",
            }, sid=sid or "SES-1")
            self._reply(cid, {"frameId": "FRM-1", "loaderId": "LDR-1"}, sid=sid)
            self.swap_document(url)
            self.emit_event("Page.loadEventFired", {"timestamp": 1.0}, sid=sid or "SES-1")
        elif method == "Page.getFrameTree":
            u = self.frame_tree_url or self.cur_url
            self._reply(cid, {"frameTree": {"frame": {"id": "FRM-1", "url": u}}}, sid=sid)
        elif method == "Runtime.evaluate":
            expr = params.get("expression") or ""
            ucid = params.get("uniqueContextId")
            self.ctx_log.append((expr[:40], ucid, self.cur_ctx))
            kind = "patch" if "__cdpilotCanvas.patch(" in expr else ("reset" if ".reset()" in expr else "")
            if self.swap_ctx_on and kind == self.swap_ctx_on:
                self.swap_ctx_on = None
                self.swap_document("about:blank")
                if not self.swap_reply_ok:
                    self.q.put_nowait(json.dumps({"id": cid, "sessionId": sid, "error": {
                        "code": -32000, "message": "Cannot find context with specified id"}}))
                    return
            elif ucid is not None and ucid != self.cur_ctx:
                self.q.put_nowait(json.dumps({"id": cid, "sessionId": sid, "error": {
                    "code": -32000, "message": "Cannot find context with specified id"}}))
                return
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
        doc = {"url": "about:blank", "ctx": "UCTX-0", "n": 0}
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
                    if "/naverr/" in url:
                        # B2 ORTA-1b: the navigation failed -> errorText, no document
                        self._ws_send(conn, {"id": cid, "sessionId": sid, "result": {
                            "frameId": "FRAME-1", "errorText": "net::ERR_ABORTED"}})
                        continue
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
                    self._ws_send(conn, {"id": cid, "sessionId": sid,
                                         "result": {"frameId": "FRAME-1", "loaderId": "L-1"}})
                    doc["n"] += 1
                    doc["url"] = url
                    doc["ctx"] = f"UCTX-{doc['n']}"
                    for ev, pr in (
                        ("Runtime.executionContextsCleared", {}),
                        ("Page.frameNavigated", {"frame": {"id": "FRAME-1", "url": url}}),
                        ("Runtime.executionContextCreated", {"context": {
                            "id": doc["n"], "uniqueId": doc["ctx"], "origin": "null",
                            "auxData": {"isDefault": True, "type": "default", "frameId": "FRAME-1"}}}),
                        ("Page.loadEventFired", {"timestamp": 1.0}),
                    ):
                        self._ws_send(conn, {"sessionId": sid, "method": ev, "params": pr})
                    continue
                elif method == "Page.getFrameTree":
                    res = {"frameTree": {"frame": {"id": "FRAME-1", "url": doc["url"]}}}
                elif method == "Runtime.evaluate":
                    expr = params.get("expression") or ""
                    if params.get("uniqueContextId") not in (None, doc["ctx"]):
                        self._ws_send(conn, {"id": cid, "sessionId": sid, "error": {
                            "code": -32000, "message": "Cannot find context with specified id"}})
                        continue
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


async def _start_host(mod, ws, name="main", allow_net=()):
    host = mod._CanvasHost(ws, name, allow_net=allow_net)
    reader = asyncio.create_task(host.ws_reader_loop())
    return host, reader


async def _stop_reader(reader):
    reader.cancel()
    with contextlib.suppress(BaseException):
        await reader


def _host_events(host):
    return [ev for ev, _ in host.events]


def scenario_proof_and_binding(mod):
    """B2 ORTA-1b/c + D1: errorText fails closed; document proven before every write; writes bound
    to the proven context; refuse + reload on any change; resetNavigationHistory after load."""

    async def _run():
        out = {}
        # (1) Page.navigate errorText -> setup raises code 1, nothing proven, tab and context closed
        ws = FakeWS(nav_error_text="net::ERR_BLOCKED_BY_CLIENT")
        host, reader = await _start_host(mod, ws)
        try:
            try:
                await host.setup()
                out["err_setup"] = {"code": 0}
            except mod.CanvasError as e:
                out["err_setup"] = {"code": e.code, "msg": str(e)}
            await host.close_cdp()
            out["err_frame_url"] = host.frame_url
            out["err_ctx"] = host.ctx_unique_id
            out["err_methods"] = [m["method"] for m in ws.sent]
        finally:
            await _stop_reader(reader)

        # (2) setup: navigate -> load -> getFrameTree -> resetNavigationHistory; frame_url None until proof
        ws = FakeWS()
        host, reader = await _start_host(mod, ws)
        try:
            out["frame_url_before"] = host.frame_url
            await host.setup()
            await asyncio.sleep(0.01)
            out["setup_methods"] = [m["method"] for m in ws.sent]
            out["addscript"] = next((m["params"] for m in ws.sent
                                     if m["method"] == "Page.addScriptToEvaluateOnNewDocument"), None)
            out["proven"] = {"frame_url": host.frame_url, "ctx": host.ctx_unique_id, "fake_ctx": ws.cur_ctx}

            # (3) frame tree URL differs (no event at all) -> set refused, no write, reload + new reset
            ws.sent.clear()
            ws.frame_tree_url = "about:blank"
            out["mismatch_set"] = await host.handle_op({"op": "set", "html": "<p>secret</p>"})
            out["mismatch_methods"] = [m["method"] for m in ws.sent]
            ws.frame_tree_url = None
            ws.sent.clear()
            ws.ctx_log.clear()
            out["after_set"] = await host.handle_op({
                "op": "set",
                "html": "<!doctype html><html><head><meta http-equiv='refresh' content='0;url=http://x/'>"
                        "<base href='http://evil.example/'></head><body><p>ok</p></body></html>",
            })
            out["after_patch"] = await host.handle_op({"op": "patch", "html": "<p>ok2</p>", "final": True})
            out["after_methods"] = [m["method"] for m in ws.sent]
            out["after_setdoc_html"] = next((m["params"]["html"] for m in ws.sent
                                             if m["method"] == "Page.setDocumentContent"), None)
            out["after_ctx_log"] = list(ws.ctx_log)
            out["nav_events"] = [e for e in _host_events(host) if e["type"] == "nav"]
        finally:
            await _stop_reader(reader)

        # (4) the document changes between the check and the write
        for label, kw, op in (
            ("reset_err", {"swap_ctx_on": "reset"}, "set"),
            ("reset_ok", {"swap_ctx_on": "reset", "swap_reply_ok": True}, "set"),
            ("patch_err", {"swap_ctx_on": "patch"}, "patch"),
            ("patch_ok", {"swap_ctx_on": "patch", "swap_reply_ok": True}, "patch"),
        ):
            ws = FakeWS(**kw)
            host, reader = await _start_host(mod, ws)
            try:
                await host.setup()
                await asyncio.sleep(0.01)
                ws.sent.clear()
                res = await host.handle_op({"op": op, "html": "<p>secret</p>", "final": True})
                methods = [m["method"] for m in ws.sent]
                out["swap_" + label] = {
                    "res": res,
                    "methods": methods,
                    "reloaded": "Page.navigate" in methods,
                    "reset_after_reload": "Page.resetNavigationHistory" in methods,
                    "nav_event": any(e["type"] == "nav" for e in _host_events(host)),
                    "proven_again": host.ctx_unique_id == ws.cur_ctx and host.frame_url == host.canvas_url,
                }
            finally:
                await _stop_reader(reader)

        # (5) D6: every field the page returns is untrusted
        junk_ok = {"ok": True, "ops": {"add": "5", "del": 2.5, "move": True, "upd": 3, "evil": 9},
                   "ms": "NaN", "t_paint": 1e300}
        junk_err = {"ok": False, "error": "E" * 500, "code": 7}
        junk_err2 = {"ok": False, "error": {"nested": [1, 2]}, "code": 2}
        junk_err3 = {"ok": 0, "error": "x", "code": True}
        for label, pv in (("ok", junk_ok), ("err", junk_err), ("err2", junk_err2), ("err3", junk_err3)):
            ws = FakeWS(patch_value=pv)
            host, reader = await _start_host(mod, ws)
            try:
                await host.setup()
                await asyncio.sleep(0.01)
                out["d6_" + label] = await host.handle_op({"op": "patch", "html": "<p>a</p>", "final": True})
            finally:
                await _stop_reader(reader)
        return out

    return asyncio.run(_run())


def scenario_hardening(mod):
    """B2 D2-D5, D7, ORTA-1a, ORTA-2d in-process: sanitiser, binding payloads, op types,
    allow-net ports, URL event rate, whitelist fullmatch, response headers."""

    async def _run():
        out = {}
        # D2: the set sanitiser
        san_in = (
            "<!DOCTYPE html>\n<html><head>"
            "<META HTTP-EQUIV=\"Refresh\" CONTENT=\"0;url=http://127.0.0.1:1/r\">"
            "<meta http-equiv=' content-security-policy ' content=\"default-src *\">"
            "<base href=\"http://evil.example/\"><base/>"
            "<meta data-cdpilot-csp content=\"fake\">"
            "<meta charset=\"utf-8\"></head><body><p id=k>keep</p>"
            "<script>var s = '<meta http-equiv=refresh content=1>';</script></body></html>"
        )
        out["san_out"] = mod._canvas_sanitize_set_html(san_in)
        out["san_plain"] = mod._canvas_sanitize_set_html("<h1>Hi</h1>")
        out["meta_tag"] = mod._canvas_meta_csp_tag(())

        ws = FakeWS()
        host, reader = await _start_host(mod, ws, allow_net=("api.example.com",))
        try:
            await host.setup()
            await asyncio.sleep(0.01)
            out["fulfill_headers"] = next(
                (m["params"]["responseHeaders"] for m in ws.sent
                 if m["method"] == "Fetch.fulfillRequest" and m["params"].get("responseCode") == 200), None)
            # D5: allow-net continues only https on the default port
            before = len(ws.sent)
            for idx, surl in enumerate([
                "https://api.example.com/v1",
                "https://api.example.com:443/v1",
                "https://api.example.com:8443/v1",
                "http://api.example.com:443/v1",
                "https://api.example.com:99999/v1",
            ]):
                ws.emit_event("Fetch.requestPaused", {
                    "requestId": f"PORT-{idx}", "request": {"url": surl, "method": "GET"},
                    "resourceType": "Fetch"})
            await asyncio.sleep(0.03)
            out["port_replies"] = [m["method"] for m in ws.sent[before:]]

            # D3: 60 KB nested payload, a non-string payload, then a valid event: the host lives on
            nested = "[" * 30000 + "]" * 30000
            dropped0 = host.dropped
            for payload in (nested, 12345, "{bad json"):
                ws.emit_event("Runtime.bindingCalled", {"name": mod.CANVAS_BINDING, "payload": payload})
            ws.emit_event("Runtime.bindingCalled", {
                "name": mod.CANVAS_BINDING,
                "payload": json.dumps({"type": "click", "action": "after_bad", "id": "z"})})
            await asyncio.sleep(0.05)
            out["d3"] = {
                "reader_alive": not reader.done(),
                "bad_payloads": host.bad_payloads,
                "dropped_delta": host.dropped - dropped0,
                "stopped": host.stop_event.is_set(),
                "after_event": any(e.get("action") == "after_bad" for e in _host_events(host)),
            }
            out["d3_ping"] = await host.handle_op({"op": "ping"})

            # D4: op of a wrong type -> code 2, never an exception
            out["d4"] = [await host.handle_op({"op": v}) for v in (["set"], {"a": 1}, 5, None, True)]
            out["d4_events_overflow"] = await host.handle_op({"op": "events", "after": 1e309})

            # D7: page-chosen URLs share one rate limit; url <= 256 chars; every request still answered
            await asyncio.sleep(max(0.0, 1.02 - (time.monotonic() % 1.0)))
            ev0 = host.seq
            dropped0 = host.dropped
            before = len(ws.sent)
            ws.emit_event("Fetch.requestPaused", {
                "requestId": "LONG", "request": {"url": "http://x.example/" + "a" * 1000},
                "resourceType": "Document"})
            for i in range(149):
                ws.emit_event("Fetch.requestPaused", {
                    "requestId": f"BURST-{i}", "request": {"url": f"http://x.example/{i}"},
                    "resourceType": "Document"})
            await asyncio.sleep(0.2)
            replies = ws.sent[before:]
            url_events = [e for e in _host_events(host) if e["seq"] > ev0 and e["type"] in ("blocked", "nav")]
            out["d7"] = {
                "replies": len(replies),
                "all_204": all(r["method"] == "Fetch.fulfillRequest" and r["params"]["responseCode"] == 204
                               for r in replies),
                "url_events": len(url_events),
                "dropped_delta": host.dropped - dropped0,
                "max_url_len": max((len(e["data"]["url"]) for e in url_events), default=0),
            }
        finally:
            await _stop_reader(reader)

        # ORTA-1a: whitelists use fullmatch
        bad = ["main\n", "main\r", " main", "MAIN", "main\n\n", "ma in"]
        out["names"] = {}
        for n in bad:
            try:
                mod._canvas_check_name(n)
                out["names"][repr(n)] = "accepted"
            except mod.CanvasError as e:
                out["names"][repr(n)] = e.code
        try:
            mod._CanvasHost(FakeWS(), "main\n")
            out["host_ctor_bad_name"] = "accepted"
        except mod.CanvasError as e:
            out["host_ctor_bad_name"] = e.code
        out["hosts"] = {}
        for h in ("api.example.com\n", "api.example.com\r", " api.example.com", "api.example.com"):
            try:
                out["hosts"][repr(h)] = mod._canvas_check_allow_net(h)
            except mod.CanvasError as e:
                out["hosts"][repr(h)] = e.code
        out["action_nl"] = bool(mod._CANVAS_ACTION_RE.fullmatch("save\n"))
        return out

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

        # B2 ORTA-1a: a trailing newline / CR, a leading space, upper case -> exit 2 on every entry
        # point, and the name never reaches a file path or the canvas URL.
        nl_names = []
        for bn in ("main\n", "main\r", " main", "MAIN"):
            item = {"name": bn}
            item["open"] = run_py("canvas", "open", "--name", bn).returncode
            item["open_eq"] = run_py("canvas", "open", f"--name={bn}").returncode
            item["set"] = run_py("canvas", "set", "-", "--name", bn, input_text="<p>x</p>").returncode
            item["close"] = run_py("canvas", "close", "--name", bn).returncode
            item["host"] = run_py("--_canvas-host", bn).returncode
            nl_names.append(item)
        cdir0 = os.path.join(tmp_profile, "canvas")
        nl_files = sorted(os.listdir(cdir0)) if os.path.isdir(cdir0) else []
        with fake_cdp.lock:
            nl_nav_urls = [m["params"].get("url") for m in fake_cdp.log if m["method"] == "Page.navigate"]

        bad_allow_net = []
        for bh in ("https://api.example.com", "api.example.com:443", "api.example.com/path",
                   "*.example.com", "127.0.0.1", "evil.com; script-src *", "api.example.com\n",
                   "api.example.com\r"):
            r = run_py("canvas", "open", "--allow-net", bh)
            bad_allow_net.append({"host": bh, "code": r.returncode, "stderr": r.stderr.strip()})

        # B2 ORTA-1b: Page.navigate errorText -> open exit 1, host gone, tab + context closed, no files
        with fake_cdp.lock:
            log_mark = len(fake_cdp.log)
        r_naverr = run_py("canvas", "open", "--name", "naverr")
        time.sleep(0.3)
        with fake_cdp.lock:
            naverr_log = [m["method"] for m in fake_cdp.log[log_mark:]]
            naverr_targets_left = [t for t in fake_cdp.targets.values()
                                   if t.get("browserContextId") in fake_cdp.contexts]
        cdir_now = os.path.join(tmp_profile, "canvas")
        naverr_files = [f for f in (os.listdir(cdir_now) if os.path.isdir(cdir_now) else [])
                        if f.startswith("naverr")]

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
        # B2 D4: a non-string op gets {ok:false, code:2}, never a silent socket
        raw_bad_ops = []
        for line in (b'{"op":["set"]}\n', b'{"op":{"a":1}}\n', b'{"op":7}\n', b'[1,2]\n'):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect(sock_path)
                s.sendall(line)
                raw_bad_ops.append(json.loads(s.recv(4096).decode("utf-8") or "null"))

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

        # B2: project-stop closes canvases only when the stopped project is the current one
        def _free_port():
            with socket.socket() as fp:
                fp.bind(("127.0.0.1", 0))
                return fp.getsockname()[1]
        reg_file = os.path.join(tmp_home, "registry.json")
        reg_backup = open(reg_file, "r", encoding="utf-8").read() if os.path.exists(reg_file) else None
        with open(reg_file, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "projects": {
                "projcur": {"port": _free_port(), "profile_dir": tmp_profile, "cwd": "/x/projcur",
                            "status": "stopped", "pid": None},
                "projother": {"port": _free_port(), "profile_dir": tmp_profile + "-o", "cwd": "/x/projother",
                              "status": "stopped", "pid": None},
            }}, f)
        proj_env = {"CDPILOT_PROJECT_ID": "projcur"}
        r_open_ps = run_py("canvas", "open", "--name", "pstop", extra_env=proj_env)
        r_ps_other = run_py("project-stop", "projother", extra_env=proj_env)
        ps_alive_after_other = os.path.exists(os.path.join(cdir, "pstop.sock"))
        r_ps_cur = run_py("project-stop", "projcur", extra_env=proj_env)
        ps_closed_after_cur = not os.path.exists(os.path.join(cdir, "pstop.sock"))
        if reg_backup is None:
            with contextlib.suppress(OSError):
                os.replace(reg_file, reg_file + ".b2-test")
        else:
            with open(reg_file, "w", encoding="utf-8") as f:
                f.write(reg_backup)

        # B2 D8: the pid in a reg file is signalled only when `ps` shows it is that canvas's host
        own_procs = []
        try:
            stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            own_procs.append(stranger)
            fake_host = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                          "--_canvas-host", "d8live"])
            own_procs.append(fake_host)
            time.sleep(0.3)
            for nm, pid in (("d8stranger", stranger.pid), ("d8live", fake_host.pid)):
                with open(os.path.join(cdir, f"{nm}.json"), "w", encoding="utf-8") as f:
                    json.dump({"name": nm, "pid": pid, "targetId": "T", "sock": os.path.join(cdir, f"{nm}.sock")}, f)
            r_d8_close_stranger = run_py("canvas", "close", "--name", "d8stranger")
            d8_stranger_alive = stranger.poll() is None
            d8_stranger_files = os.path.exists(os.path.join(cdir, "d8stranger.json"))
            r_d8_open_live = run_py("canvas", "open", "--name", "d8live")
            d8_live_files_kept = os.path.exists(os.path.join(cdir, "d8live.json"))
            d8_live_alive_after_open = fake_host.poll() is None
            r_d8_close_live = run_py("canvas", "close", "--name", "d8live")
            with contextlib.suppress(subprocess.TimeoutExpired):
                fake_host.wait(timeout=3)
            d8_live_gone = fake_host.poll() is not None
        finally:
            for pr in own_procs:
                if pr.poll() is None:
                    pr.kill()
                with contextlib.suppress(Exception):
                    pr.wait(timeout=3)

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
        # B2 D9: os.name == 'nt' with AF_UNIX present (Python 3.13+ on Windows) is still unsupported
        win_nt = {}
        saved_os_name = mod.os.name
        try:
            mod.os.name = "nt"
            for sub in ("open", "set", "list"):
                err_buf = io.StringIO()
                code = 0
                with contextlib.redirect_stderr(err_buf):
                    try:
                        mod.cmd_canvas_dispatch([sub])
                    except SystemExit as e:
                        code = e.code
                win_nt[sub] = {"code": code, "stderr": err_buf.getvalue().strip()}
            err_buf = io.StringIO()
            code = 0
            with contextlib.redirect_stderr(err_buf):
                try:
                    mod._canvas_host_entry(["main"])
                except SystemExit as e:
                    code = e.code
            win_nt["host"] = {"code": code, "stderr": err_buf.getvalue().strip()}
        finally:
            mod.os.name = saved_os_name

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
            "windows_nt": win_nt,
            "nl_names": nl_names,
            "nl_files": nl_files,
            "nl_nav_urls": nl_nav_urls,
            "naverr": {
                "code": r_naverr.returncode,
                "stderr": r_naverr.stderr.strip(),
                "log": naverr_log,
                "targets_left": naverr_targets_left,
                "files": naverr_files,
            },
            "raw_bad_ops": raw_bad_ops,
            "project_stop": {
                "open_code": r_open_ps.returncode,
                "other_code": r_ps_other.returncode,
                "alive_after_other": ps_alive_after_other,
                "cur_code": r_ps_cur.returncode,
                "closed_after_cur": ps_closed_after_cur,
            },
            "d8": {
                "close_stranger_code": r_d8_close_stranger.returncode,
                "stranger_alive": d8_stranger_alive,
                "stranger_files_left": d8_stranger_files,
                "open_live_code": r_d8_open_live.returncode,
                "open_live_stderr": r_d8_open_live.stderr.strip(),
                "live_files_kept": d8_live_files_kept,
                "live_alive_after_open": d8_live_alive_after_open,
                "close_live_code": r_d8_close_live.returncode,
                "live_gone": d8_live_gone,
            },
        }
    finally:
        fake_cdp.stop()
        shutil.rmtree(tmp_home, ignore_errors=True)


# ── K9 e2e (B2): per-vector counter-experiment ──────────────────────────────────────────────
# Every vector of test/fixtures/canvas/exfil.html has a name and its own listener channel:
# HTTP path /<name>, own TCP port (preconnect) or own UDP port (WebRTC). The unguarded run
# (same fixture served from the listener, no canvas guard) must hit every vector > 0 unless the
# vector is listed here with the reason it cannot be measured; the guarded run must be 0 for all.
E2E_HTTP_VECTORS = (
    "fetch", "img", "script", "prefetch", "prefetch_static", "iframe", "ws", "window_open",
    "ping", "a_nav", "form", "location", "meta_refresh", "data_nav", "blob_nav", "history_back",
)
E2E_TCP_VECTORS = ("preconnect", "preconnect_static")
E2E_UDP_VECTORS = ("webrtc_stun", "webrtc_turn", "webrtc_iframe")
E2E_DNS_VECTORS = ("dns_prefetch", "dns_prefetch_static")
E2E_VECTORS = E2E_HTTP_VECTORS + E2E_TCP_VECTORS + E2E_UDP_VECTORS + E2E_DNS_VECTORS
UNMEASURABLE = {
    "dns_prefetch": "DNS sorgusu sistem çözücüsüne gider; yerel dinleyici onu göremez",
    "dns_prefetch_static": "DNS sorgusu sistem çözücüsüne gider; yerel dinleyici onu göremez",
    "data_nav": "Chrome sayfanın başlattığı üst düzey data: gezinmesini kendisi engeller",
    # Measured 11.11 on the shared Chrome 152 headless: 0 connections in 2 of 2 unguarded runs.
    # If a CI browser opens them, the test prints the entry as stale and it can be removed.
    "preconnect": "Chrome 152 headless ipucuna rağmen bağlantı açmadı (karşı deney 2/2 koşuda 0)",
    "preconnect_static": "Chrome 152 headless ipucuna rağmen bağlantı açmadı (karşı deney 2/2 koşuda 0)",
}


def e2e_listen_ip():
    """(ip, why). Non-loopback IPv4 when one exists (WebRTC and Chrome treat loopback
    specially), loopback otherwise. CDPILOT_CANVAS_E2E_LISTEN=<ip> overrides. macOS: the
    browser needs the Local Network permission to reach a LAN address (measured 11.11 on
    Chrome 152: TCP to 192.168.x hung, UDP was not delivered), so loopback is used there."""
    forced = os.environ.get("CDPILOT_CANVAS_E2E_LISTEN")
    if forced:
        return forced, "CDPILOT_CANVAS_E2E_LISTEN"
    if sys.platform == "darwin":
        return "127.0.0.1", "macOS: tarayıcı LAN adresine Yerel Ağ izni olmadan ulaşamıyor (11.11 ölçümü)"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))      # TEST-NET-1: no packet is sent for a UDP connect
            ip = s.getsockname()[0]
        if ip and not ip.startswith("127.") and ip != "0.0.0.0":
            return ip, "yerel ağ IPv4"
    except OSError:
        pass
    return "127.0.0.1", "loopback dışı IPv4 yok"


class E2EListeners:
    """Per-vector counting listeners on one IPv4 address; counts go to the current phase."""

    def __init__(self, ip, pages):
        self.ip = ip
        self.pages = pages               # path -> bytes served 200 text/html, never counted
        self.lock = threading.Lock()
        self.phase = "counter"
        self.counts = {"counter": {}, "guarded": {}}
        self.first_hit = {}              # (phase, vector) -> monotonic time
        self.t0 = {"counter": time.monotonic(), "guarded": time.monotonic()}
        self.running = True
        self.socks = []
        self.http_port = self._tcp(self._serve_http)
        self.tcp_ports = {v: self._tcp(self._tcp_hit(v)) for v in E2E_TCP_VECTORS}
        self.udp_ports = {v: self._udp(v) for v in E2E_UDP_VECTORS}

    def hit(self, vector):
        with self.lock:
            cur = self.counts[self.phase]
            cur[vector] = cur.get(vector, 0) + 1
            self.first_hit.setdefault((self.phase, vector), time.monotonic())

    def snapshot(self, phase):
        with self.lock:
            return dict(self.counts[phase])

    def set_phase(self, phase):
        with self.lock:
            self.phase = phase
            self.t0[phase] = time.monotonic()

    def _tcp(self, handler):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.ip, 0))
        s.listen(64)
        self.socks.append(s)

        def loop():
            while self.running:
                try:
                    conn, _ = s.accept()
                except OSError:
                    return
                threading.Thread(target=handler, args=(conn,), daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()
        return s.getsockname()[1]

    def _tcp_hit(self, vector):
        def handler(conn):
            self.hit(vector)
            with contextlib.suppress(OSError):
                conn.close()
        return handler

    def _udp(self, vector):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((self.ip, 0))
        self.socks.append(s)

        def loop():
            while self.running:
                try:
                    data, _ = s.recvfrom(4096)
                except OSError:
                    return
                if data:
                    self.hit(vector)
        threading.Thread(target=loop, daemon=True).start()
        return s.getsockname()[1]

    def _serve_http(self, conn):
        try:
            # Chrome may open a socket early and write the request much later on a loaded
            # machine (seen 11.11: ERR_SOCKET_NOT_CONNECTED after a 5 s read timeout).
            conn.settimeout(60.0)
            data = b""
            while b"\r\n" not in data and len(data) < 8192:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                self.hit("_raw_http")        # a connection without a request: unattributed
                return
            first = data.decode("latin-1", "replace").split("\r\n", 1)[0]
            parts = first.split(" ")
            path = parts[1] if len(parts) > 1 else ""
            name = path.split("?", 1)[0].lstrip("/").split("/", 1)[0]
            if path in self.pages:
                body = self.pages[path]
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                             + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
                             + body)
                return
            self.hit(name if name in E2E_HTTP_VECTORS else "_other_http")
            conn.sendall(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                conn.close()

    def close(self):
        self.running = False
        for s in self.socks:
            with contextlib.suppress(OSError):
                s.close()


def e2e_render_fixture(lst, blob_delay_ms):
    with open(os.path.join(HERE, "fixtures", "canvas", "exfil.html"), "r", encoding="utf-8") as f:
        html = f.read()
    for k, v in (("__HOST__", lst.ip), ("__HTTP_PORT__", lst.http_port),
                 ("__PC_PORT__", lst.tcp_ports["preconnect"]),
                 ("__PCS_PORT__", lst.tcp_ports["preconnect_static"]),
                 ("__UDP_STUN__", lst.udp_ports["webrtc_stun"]),
                 ("__UDP_TURN__", lst.udp_ports["webrtc_turn"]),
                 ("__UDP_IFRAME__", lst.udp_ports["webrtc_iframe"])):
        html = html.replace(k, str(v))
    return f"<script>window.__EXFIL_BLOB_DELAY__={int(blob_delay_ms)};</script>\n" + html


class E2EBrowser:
    """One browser-level CDP connection for the test's own targets/contexts only."""

    def __init__(self, ws):
        self.ws = ws
        self.seq = 0
        self.pending = {}
        self.net_failed = []             # diagnostics: Network.loadingFailed of the test's own tabs
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("method") == "Network.loadingFailed" and len(self.net_failed) < 50:
                p = msg.get("params") or {}
                self.net_failed.append(f"{p.get('type')}: {p.get('errorText')} {p.get('blockedReason') or ''}".strip())
                continue
            fut = self.pending.pop(msg.get("id"), None)
            if fut is not None and not fut.done():
                fut.set_result(msg)

    async def call(self, method, params=None, sid=None, timeout=60.0):
        self.seq += 1
        cid = self.seq
        fut = asyncio.get_running_loop().create_future()
        self.pending[cid] = fut
        payload = {"id": cid, "method": method, "params": params or {}}
        if sid:
            payload["sessionId"] = sid
        await self.ws.send(json.dumps(payload))
        msg = await asyncio.wait_for(fut, timeout)
        if msg.get("error"):
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result") or {}

    async def grant_local_network(self, ctx):
        """Both runs get the same Local Network Access grant, so a 0 in the guarded run is not
        Chrome's LNA prompt being denied in headless mode."""
        with contextlib.suppress(Exception):
            await self.call("Browser.grantPermissions", {
                "permissions": ["localNetworkAccess", "localNetwork", "loopbackNetwork"],
                "browserContextId": ctx})


def run_e2e(py_path, cli_js_path, cdp_hostport):
    """K9 + C1 e2e gate against the browser at cdp_hostport (CDPILOT_CANVAS_E2E_CDP or the
    test's own headless Chrome; never launched here)."""
    import urllib.request
    import websockets

    host, _, port_s = cdp_hostport.rpartition(":")
    if host not in ("127.0.0.1", "localhost") or not port_s.isdigit():
        raise RuntimeError(f"CDP must be 127.0.0.1:<port>, got {cdp_hostport!r}")
    cdp_port = port_s
    ver = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=10).read())
    browser_ws = ver["webSocketDebuggerUrl"]
    listen_ip, listen_why = e2e_listen_ip()
    hist_start = (b"<!doctype html><html><body><p>hist</p>"
                  b"<script>setTimeout(function(){history.back();},50);</script></body></html>")
    lst = E2EListeners(listen_ip, {"/hist_start.html": hist_start})
    lst.pages["/counter.html"] = e2e_render_fixture(lst, 3000).encode("utf-8")
    measurable = [v for v in E2E_VECTORS if v not in UNMEASURABLE]
    hist_payload = (f'<script>location.href="http://{listen_ip}:{lst.http_port}/history_back";</script>'
                    "<p>history payload</p>")

    tmp_home = tempfile.mkdtemp(prefix="cdpilot-canvas-e2e-")
    tmp_prof = os.path.join(tmp_home, "profile")
    os.makedirs(tmp_prof, mode=0o700, exist_ok=True)
    env = {
        **os.environ,
        "CDPILOT_HOME": tmp_home,
        "CDPILOT_PROFILE": tmp_prof,
        "CDP_PORT": cdp_port,
        "CDPILOT_NO_AUTOLAUNCH": "1",
        "CDPILOT_LOG": "0",
        "CDPILOT_DAEMON": "0",
    }

    def cli(*args):
        return subprocess.run(["node", cli_js_path, *args], capture_output=True, text=True,
                              timeout=60, env=env)

    for k in ("CDPILOT_HOME", "CDPILOT_PROFILE", "CDP_PORT", "CDPILOT_NO_AUTOLAUNCH", "CDPILOT_LOG"):
        os.environ[k] = env[k]
    out = {"browser": ver.get("Browser", "unknown"), "listen_ip": listen_ip, "listen_why": listen_why,
           "unmeasurable": UNMEASURABLE}
    try:
        r_conn = cli("connect", cdp_port)
        if r_conn.returncode != 0:
            raise RuntimeError(f"connect {cdp_port} failed: {r_conn.stderr or r_conn.stdout}")
        mod = load_cdpilot(py_path)

        # (1) Counter-experiment: the same fixture, served by the listener, no canvas guard.
        async def _counter():
            async with websockets.connect(browser_ws, max_size=64 * 1024 * 1024, ping_interval=None) as ws:
                b = E2EBrowser(ws)
                ctx = (await b.call("Target.createBrowserContext", {"disposeOnDetach": True}))["browserContextId"]
                res = {}
                try:
                    await b.grant_local_network(ctx)
                    want = [v for v in measurable if v != "history_back"]
                    # Two attempts: a loaded machine can stall one page load (seen 11.11, load ~100).
                    for attempt in (1, 2):
                        tid = (await b.call("Target.createTarget", {"url": "about:blank", "browserContextId": ctx}))["targetId"]
                        sid = (await b.call("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
                        await b.call("Page.enable", {}, sid)
                        await b.call("Runtime.enable", {}, sid)
                        await b.call("Network.enable", {}, sid)
                        await b.call("Page.navigate", {"url": f"http://{listen_ip}:{lst.http_port}/counter.html"}, sid)
                        deadline = time.monotonic() + 45.0
                        while time.monotonic() < deadline:
                            snap = lst.snapshot("counter")
                            if all(snap.get(v, 0) > 0 for v in want):
                                break
                            with contextlib.suppress(Exception):
                                pr = await b.call("Runtime.evaluate", {
                                    "expression": "JSON.stringify(window.__r||null)", "returnByValue": True},
                                    sid, timeout=5)
                                res["page"] = json.loads((pr.get("result") or {}).get("value") or "null") or res.get("page")
                            await asyncio.sleep(0.3)
                        res["attempts"] = attempt
                        snap = lst.snapshot("counter")
                        if all(snap.get(v, 0) > 0 for v in want):
                            break
                    # history.back() to the CSP-less about:blank entry, then an unguarded write into it
                    tid2 = (await b.call("Target.createTarget", {"url": "about:blank", "browserContextId": ctx}))["targetId"]
                    sid2 = (await b.call("Target.attachToTarget", {"targetId": tid2, "flatten": True}))["sessionId"]
                    await b.call("Page.enable", {}, sid2)
                    await b.call("Page.navigate", {"url": f"http://{listen_ip}:{lst.http_port}/hist_start.html"}, sid2)
                    back_url, fid = None, None
                    t_end = time.monotonic() + 15.0
                    while time.monotonic() < t_end:
                        await asyncio.sleep(0.2)
                        ft = (await b.call("Page.getFrameTree", {}, sid2))["frameTree"]["frame"]
                        if ft.get("url") == "about:blank":
                            back_url, fid = ft["url"], ft["id"]
                            break
                    res["history_back_url"] = back_url
                    if fid:
                        await b.call("Page.setDocumentContent", {"frameId": fid, "html": hist_payload}, sid2)
                        t_end = time.monotonic() + 10.0
                        while time.monotonic() < t_end and not lst.snapshot("counter").get("history_back"):
                            await asyncio.sleep(0.2)
                finally:
                    res["net_failed"] = list(b.net_failed)
                    with contextlib.suppress(Exception):
                        await b.call("Target.disposeBrowserContext", {"browserContextId": ctx})
                    b.reader.cancel()
                return res

        lst.set_phase("counter")
        counter_res = asyncio.run(_counter())
        time.sleep(0.5)
        counter = lst.snapshot("counter")
        lat = [lst.first_hit[k] - lst.t0["counter"] for k in lst.first_hit if k[0] == "counter"]
        wait_s = min(15.0, max(3.0, 2.0 * (max(lat) if lat else 3.0)))

        # (2) Guarded run: the same vectors inside a canvas.
        lst.set_phase("guarded")
        rendered_path = os.path.join(tmp_home, "exfil_rendered.html")
        with open(rendered_path, "w", encoding="utf-8") as f:
            f.write(e2e_render_fixture(lst, 60000))
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cmd_canvas_open(["--name", "e2e"])
        reg_path = os.path.join(tmp_prof, "canvas", "e2e.json")
        with open(reg_path, "r", encoding="utf-8") as f:
            reg = json.load(f)

        async def _grant_canvas():
            async with websockets.connect(browser_ws, max_size=16 * 1024 * 1024, ping_interval=None) as ws:
                b = E2EBrowser(ws)
                try:
                    await b.grant_local_network(reg["browserContextId"])
                finally:
                    b.reader.cancel()
        asyncio.run(_grant_canvas())

        def req(msg, timeout=60.0):
            return mod._canvas_request("e2e", msg, timeout=timeout)

        set1 = req({"op": "set", "html": e2e_render_fixture(lst, 60000)})
        time.sleep(wait_s)
        set2 = req({"op": "set", "html": e2e_render_fixture(lst, 10)})
        time.sleep(wait_s)
        # D1: history.back() must not leave the canvas; the next write must land in the canvas.
        benign = req({"op": "set", "html": "<p>benign</p>"})
        if not benign.get("ok"):
            benign = req({"op": "set", "html": "<p>benign</p>"})
        hist_set = req({"op": "set", "html": "<script>setTimeout(function(){history.back();},20);</script>"})
        time.sleep(2.0)
        hist_payload_set = req({"op": "set", "html": hist_payload})
        time.sleep(max(3.0, wait_s / 2))
        ev_reply = req({"op": "events", "after": 0, "max": 100})
        events = ev_reply.get("events") or []
        nxt = ev_reply.get("next") or 0
        while len(events) < 2000:
            more = req({"op": "events", "after": nxt, "max": 100})
            if not more.get("events"):
                break
            events.extend(more["events"])
            nxt = more.get("next") or nxt
        guarded = lst.snapshot("guarded")
        host_blocked = [e for e in events if e.get("src") == "host" and e.get("type") == "blocked"]
        page_guarded = {}
        for e in events:
            if e.get("src") == "page" and e.get("action") == "exfil":
                page_guarded[e.get("id")] = e.get("data")

        # (3) C1: SIGKILL the host -> its target and browser context are gone within 5 s
        host_pid, canvas_tid, canvas_ctx = int(reg["pid"]), reg["targetId"], reg["browserContextId"]

        async def _verify_sigkill():
            async with websockets.connect(browser_ws, max_size=16 * 1024 * 1024, ping_interval=None) as ws:
                b = E2EBrowser(ws)
                try:
                    t_b = await b.call("Target.getTargets")
                    c_b = await b.call("Target.getBrowserContexts")
                    r = {
                        "tid_present_before": any(t.get("targetId") == canvas_tid for t in t_b.get("targetInfos") or []),
                        "ctx_present_before": canvas_ctx in (c_b.get("browserContextIds") or []),
                        "tid_gone": False, "ctx_gone": False,
                    }
                    t0 = time.monotonic()
                    os.kill(host_pid, signal.SIGKILL)
                    while time.monotonic() < t0 + 5.0:
                        t_n = await b.call("Target.getTargets")
                        c_n = await b.call("Target.getBrowserContexts")
                        r["tid_gone"] = not any(t.get("targetId") == canvas_tid for t in t_n.get("targetInfos") or [])
                        r["ctx_gone"] = canvas_ctx not in (c_n.get("browserContextIds") or [])
                        if r["tid_gone"] and r["ctx_gone"]:
                            break
                        await asyncio.sleep(0.05)
                    r["elapsed_ms"] = round((time.monotonic() - t0) * 1000.0, 1)
                    return r
                finally:
                    b.reader.cancel()

        sigkill_res = asyncio.run(_verify_sigkill())
        vectors = {}
        for v in E2E_VECTORS:
            vectors[v] = {
                "counter": counter.get(v, 0),
                "guarded": guarded.get(v, 0),
                "unmeasurable": UNMEASURABLE.get(v),
                "page_counter": (counter_res.get("page") or {}).get(v),
                "page_guarded": page_guarded.get(v),
            }
        out.update({
            "vectors": vectors,
            "counter_other": {k: n for k, n in counter.items() if k not in E2E_VECTORS},
            "guarded_other": {k: n for k, n in guarded.items() if k not in E2E_VECTORS},
            "counter_history_back_url": counter_res.get("history_back_url"),
            "counter_attempts": counter_res.get("attempts"),
            "counter_net_failed": counter_res.get("net_failed"),
            "wait_s": round(wait_s, 1),
            "guarded": {
                "set1_ok": bool(set1.get("ok")), "set2_ok": bool(set2.get("ok")),
                "benign": benign, "hist_set": hist_set, "hist_payload_set": hist_payload_set,
                "host_blocked_count": len(host_blocked),
                "host_blocked_sample": host_blocked[:5],
                "csp_violations": sorted(k for k in page_guarded if k.startswith("csp:")),
            },
            "sigkill": sigkill_res,
            "uptime": subprocess.run(["uptime"], capture_output=True, text=True, timeout=5).stdout.strip(),
        })
        return out
    finally:
        lst.close()
        with contextlib.suppress(Exception):
            reg_p = os.path.join(tmp_prof, "canvas", "e2e.json")
            if os.path.exists(reg_p):
                with open(reg_p, "r", encoding="utf-8") as rf:
                    pid = int(json.load(rf)["pid"])
                # only our own host process (started by cmd_canvas_open above)
                if mod._canvas_live_host_pid("e2e", mod._canvas_paths("e2e")) == pid:
                    os.kill(pid, signal.SIGKILL)
        shutil.rmtree(tmp_home, ignore_errors=True)


SCENARIOS = {
    "setup_and_guards": scenario_setup_and_guards,
    "set_patch_and_doc_loss": scenario_set_patch_and_doc_loss,
    "bindings_and_limits": scenario_bindings_and_limits,
    "proof_and_binding": scenario_proof_and_binding,
    "hardening": scenario_hardening,
    "cli_and_socket": scenario_cli_and_socket_integration,
}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--e2e":
        py_path = sys.argv[2]
        cli_js = sys.argv[3]
        cdp = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("CDPILOT_CANVAS_E2E_CDP", "")
        try:
            res = run_e2e(py_path, cli_js, cdp)
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

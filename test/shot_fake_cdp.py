"""Fake CDP endpoint for shot HiDPI / CSS pixel tests.
Listens on 127.0.0.1:<port>, answers /json/version, /json, and records Page.captureScreenshot params.
"""
import base64
import hashlib
import json
import os
import signal
import socket
import struct
import sys
import threading
import time

signal.signal(signal.SIGTERM, lambda s, f: os._exit(0))
signal.signal(signal.SIGINT, lambda s, f: os._exit(0))

PORT_FILE = sys.argv[1] if len(sys.argv) > 1 else None
LOG = sys.argv[2] if len(sys.argv) > 2 else "shot_fake.log"
LOCK = threading.Lock()

def png_header(w, h):
    """Minimal PNG (signature + IHDR + IEND): enough for the size read in cdpilot._image_dimensions."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", w, h)
        + b"\x08\x02\x00\x00\x00\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def shot_size(params):
    """Image size the way Chrome derives it: clip x scale x DPR, or the 800x600 viewport x DPR."""
    dpr = float(os.environ.get("FAKE_DPR", "1"))
    clip = params.get("clip")
    if clip:
        f = float(clip.get("scale", 1)) * dpr
        return round(clip["width"] * f), round(clip["height"] * f)
    return round(800 * dpr), round(600 * dpr)


def log(entry):
    with LOCK:
        with open(LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def ws_send(conn, text):
    data = text.encode()
    head = bytes([0x81])
    if len(data) < 126:
        head += bytes([len(data)])
    elif len(data) < 65536:
        head += bytes([126]) + struct.pack(">H", len(data))
    else:
        head += bytes([127]) + struct.pack(">Q", len(data))
    conn.sendall(head + data)


def ws_frames(conn):
    while True:
        b1, b2 = recv_exact(conn, 2)
        opcode, length = b1 & 0x0F, b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", recv_exact(conn, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", recv_exact(conn, 8))[0]
        mask = recv_exact(conn, 4) if b2 & 0x80 else b"\0\0\0\0"
        payload = bytes(c ^ mask[i % 4] for i, c in enumerate(recv_exact(conn, length)))
        if opcode == 0x8:  # close
            try:
                conn.sendall(bytes([0x88, 0]))
            except OSError:
                pass
            return
        if opcode == 0x9:  # ping -> pong
            conn.sendall(bytes([0x8A, len(payload)]) + payload)
            continue
        if opcode == 0x1:
            yield payload.decode("utf-8", "replace")


def handle_ws(conn, path, headers, bound_port):
    key = headers.get("sec-websocket-key", "")
    accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode()
    conn.sendall(
        (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode()
    )

    try:
        for raw in ws_frames(conn):
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            mid = msg.get("id")
            method = msg.get("method", "")
            p = msg.get("params", {})
            log({"ws": path, "method": method, "params": p})

            if method == "Runtime.evaluate":
                expr = p.get("expression", "")
                if "devicePixelRatio" in expr:
                    # the page's main world may lie (FAKE_MAIN_DPR); cdpilot's isolated world
                    # (contextId 77) sees the real value; FAKE_NO_WORLD=1: the world is unusable
                    dpr = float(os.environ.get("FAKE_DPR", "1"))
                    if p.get("contextId") is None:
                        dpr = float(os.environ.get("FAKE_MAIN_DPR", dpr))
                    if p.get("contextId") is not None and os.environ.get("FAKE_NO_WORLD") == "1":
                        reply = {"id": mid, "error": {"code": -32000, "message": "Cannot find context"}}
                    else:
                        reply = {"id": mid, "result": {"result": {"type": "number", "value": dpr}}}
                elif "resolveSelector" in expr:
                    # element crop: the page's main world may lie (FAKE_MAIN_RECT=1); cdpilot's isolated
                    # world (contextId 77) sees the real rect; FAKE_NO_WORLD=1: the world is unusable;
                    # missing / not found selector returns null
                    if (
                        os.environ.get("FAKE_NO_ELEM") == "1"
                        or "missing" in expr.lower()
                        or "notfound" in expr.lower()
                        or "not-found" in expr.lower()
                    ):
                        reply = {"id": mid, "result": {"result": {"type": "object", "subtype": "null", "value": None}}}
                    elif p.get("contextId") is not None and os.environ.get("FAKE_NO_WORLD") == "1":
                        reply = {"id": mid, "error": {"code": -32000, "message": "Cannot find context"}}
                    else:
                        rect = {"x": 100, "y": 200, "width": 200, "height": 200, "shadowHost": None}
                        if p.get("contextId") is None and os.environ.get("FAKE_MAIN_RECT") == "1":
                            rect = {"x": 999, "y": 999, "width": 50, "height": 50, "shadowHost": None}
                        reply = {"id": mid, "result": {"result": {"type": "string", "value": json.dumps(rect)}}}
                else:
                    reply = {"id": mid, "result": {"result": {"type": "string", "value": "ok"}}}
            elif method == "Page.getLayoutMetrics":
                dpr = float(os.environ.get("FAKE_DPR", "1"))
                reply = {
                    "id": mid,
                    "result": {
                        # as Chrome reports it: both sizes in CSS pixels, whatever the DPR (T1 15.11)
                        "contentSize": {"x": 0, "y": 0, "width": 800, "height": 600},
                        "cssContentSize": {"x": 0, "y": 0, "width": 800, "height": 600},
                        "cssLayoutViewport": {"pageX": 0, "pageY": 0, "clientWidth": 800, "clientHeight": 600},
                        "cssVisualViewport": {"pageX": 0, "pageY": 0, "clientWidth": 800, "clientHeight": 600},
                    },
                }
            elif method == "Page.getFrameTree":
                reply = {"id": mid, "result": {"frameTree": {"frame": {"id": "TOPFRAME"}}}}
            elif method == "Page.createIsolatedWorld":
                reply = {"id": mid, "result": {"executionContextId": 77}}
            elif method == "Page.captureScreenshot":
                reply = {"id": mid, "result": {"data": base64.b64encode(png_header(*shot_size(p))).decode()}}
            elif method == "Target.getTargets":
                reply = {
                    "id": mid,
                    "result": {
                        "targetInfos": [
                            {
                                "targetId": "p1",
                                "type": "page",
                                "url": "about:blank",
                                "title": "blank",
                                "attached": False,
                            }
                        ]
                    },
                }
            elif method == "Target.createTarget":
                reply = {"id": mid, "result": {"targetId": "p1"}}
            elif method == "Target.closeTarget":
                reply = {"id": mid, "result": {"success": True}}
            else:
                reply = {"id": mid, "result": {}}
            ws_send(conn, json.dumps(reply))
    except (ConnectionError, OSError):
        pass


def serve():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    bound_port = s.getsockname()[1]
    s.listen(16)
    if PORT_FILE:
        with open(PORT_FILE, "w") as f:
            f.write(str(bound_port))
    print(f"READY:{bound_port}", flush=True)

    while True:
        try:
            conn, _ = s.accept()
        except OSError:
            break
        t = threading.Thread(target=handle_client, args=(conn, bound_port), daemon=True)
        t.start()


def handle_client(conn, bound_port):
    with conn:
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                head += chunk
            first_line, rest = head.split(b"\r\n", 1)
            parts = first_line.decode().split()
            if len(parts) < 2:
                return
            verb, path = parts[0], parts[1]
            headers = {}
            for line in rest.split(b"\r\n\r\n")[0].split(b"\r\n"):
                if b":" in line:
                    k, v = line.decode().split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            if headers.get("upgrade", "").lower() == "websocket":
                handle_ws(conn, path, headers, bound_port)
                return

            # HTTP endpoints
            log({"http": path, "verb": verb})
            if path == "/json/version":
                data = json.dumps({
                    "Browser": "HeadlessChrome/152.0.0.0",
                    "Protocol-Version": "1.3",
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{bound_port}/devtools/browser/fake",
                }).encode()
            elif path in ("/json", "/json/list", "/json/new"):
                data = json.dumps([
                    {
                        "id": "p1",
                        "type": "page",
                        "url": "about:blank",
                        "title": "blank",
                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{bound_port}/devtools/page/p1",
                    }
                ] if path != "/json/new" else {
                    "id": "p1",
                    "type": "page",
                    "url": "about:blank",
                    "title": "blank",
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{bound_port}/devtools/page/p1",
                }).encode()
            else:
                data = b"{}"

            conn.sendall(
                (
                    f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n"
                ).encode()
                + data
            )
        except Exception:
            pass


if __name__ == "__main__":
    serve()

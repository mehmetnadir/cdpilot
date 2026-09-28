"""Fake CDP endpoint for the connect tests in test.js (no browser needed).

    python connect_fake_cdp.py <port> <log.jsonl> <mode> <guid> --remote-debugging-port=<port>

Stands in for a browser the user started: listens on 127.0.0.1:<port>, answers
the CDP HTTP endpoints (/json/version, /json, /json/new, /json/close/<id>) and
WebSocket connections on /devtools/browser/<guid> and /devtools/page/<id>, and
appends one JSON line per request to <log.jsonl>:
    {"http": "/json/close/PAGE1"}  or  {"ws": "/devtools/page/PAGE1", "method": "Page.navigate"}
so a test can prove what cdpilot sent (e.g. no Browser.close, no
Page.addScriptToEvaluateOnNewDocument). Browser.close is recorded and answered,
but the process keeps running; a test checks the log AND that it is alive.

mode "full"    — a normal --remote-debugging-port browser.
mode "ws-only" — Chrome's chrome://inspect remote-debugging mode as reported:
                 every HTTP path answers 404, only the WebSocket upgrade works.

The last argument carries --remote-debugging-port=<port> on purpose: cdpilot's
kill path (_debug_port_pids) matches exactly that flag, so a missing guard
would signal this process. Standard library only.
"""
import base64
import hashlib
import json
import socket
import struct
import sys
import threading

PORT = int(sys.argv[1])
LOG = sys.argv[2]
MODE = sys.argv[3]
GUID = sys.argv[4]
LOCK = threading.Lock()
PAGES = [{"id": "PAGE1", "type": "page", "url": "https://user.example/inbox",
          "title": "The user's own tab"}]
SEQ = [1]


def log(entry):
    with LOCK:
        with open(LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")


def page_json(p):
    return dict(p, webSocketDebuggerUrl=f"ws://127.0.0.1:{PORT}/devtools/page/{p['id']}",
                devtoolsFrontendUrl="")


def http_reply(conn, status, body):
    data = json.dumps(body).encode() if body is not None else b""
    reason = {200: "OK", 404: "Not Found", 405: "Method Not Allowed"}.get(status, "OK")
    conn.sendall((f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
                  f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n").encode() + data)


def handle_http(conn, path, verb="GET"):
    log({"http": path, "verb": verb})
    if MODE == "ws-only":
        return http_reply(conn, 404, None)
    base = path.split("?", 1)[0]
    if base == "/json/version":
        return http_reply(conn, 200, {
            "Browser": "FakeChrome/144.0.0.0", "Protocol-Version": "1.3",
            "User-Agent": "Mozilla/5.0 FakeChrome/144.0.0.0",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:{PORT}/devtools/browser/{GUID}"})
    if base in ("/json", "/json/list"):
        with LOCK:
            return http_reply(conn, 200, [page_json(p) for p in PAGES])
    if base == "/json/new":
        if verb != "PUT":  # current Chrome: "Using unsafe HTTP verb GET to invoke /json/new"
            return http_reply(conn, 405, None)
        with LOCK:
            SEQ[0] += 1
            p = {"id": f"PAGE{SEQ[0]}", "type": "page", "url": "about:blank", "title": ""}
            PAGES.append(p)
        return http_reply(conn, 200, page_json(p))
    if base.startswith("/json/close/"):
        with LOCK:
            PAGES[:] = [x for x in PAGES if x["id"] != base.rsplit("/", 1)[1]]
        return http_reply(conn, 200, None)
    if base.startswith("/json/activate/"):
        return http_reply(conn, 200, None)
    return http_reply(conn, 404, None)


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


def answer(msg, path):
    method, p = msg.get("method", ""), msg.get("params") or {}
    events = []
    result = {}
    if method == "Runtime.evaluate":
        expr = p.get("expression", "")
        if "readyState" in expr:
            value = "complete"
        elif "location.href" in expr:
            value = "https://user.example/inbox"
        elif "location.hostname" in expr or "location.host" in expr:
            value = "user.example"
        elif "innerText" in expr:
            value = "The user's own tab"
        else:
            value = None
        result = {"result": {"type": "string", "value": value} if value is not None
                  else {"type": "undefined"}}
    elif method == "Page.navigate":
        with LOCK:  # the tab this socket is attached to now shows the new URL
            for pg in PAGES:
                if path.endswith("/" + pg["id"]):
                    pg["url"], pg["title"] = p.get("url", ""), "navigated by cdpilot"
        result = {"frameId": "F1", "loaderId": "L1"}
        events = [{"method": "Page.frameStartedLoading", "params": {"frameId": "F1"}},
                  {"method": "Page.loadEventFired", "params": {"timestamp": 1}},
                  {"method": "Page.frameStoppedLoading", "params": {"frameId": "F1"}}]
    elif method == "Target.createTarget":
        with LOCK:
            SEQ[0] += 1
            new = {"id": f"PAGE{SEQ[0]}", "type": "page", "url": p.get("url") or "about:blank",
                   "title": "", "background": bool(p.get("background")),
                   "newWindow": bool(p.get("newWindow"))}
            PAGES.append(new)
        result = {"targetId": new["id"]}
    elif method == "Target.closeTarget":
        with LOCK:
            PAGES[:] = [x for x in PAGES if x["id"] != p.get("targetId")]
        result = {"success": True}
    elif method == "Page.addScriptToEvaluateOnNewDocument":
        result = {"identifier": "1"}
    elif method == "Target.getTargets":
        with LOCK:
            result = {"targetInfos": [{"targetId": x["id"], "type": "page", "url": x["url"],
                                       "title": x["title"], "attached": False}
                                      for x in PAGES]}
    elif method == "Page.getFrameTree":
        result = {"frameTree": {"frame": {"id": "F1", "url": "https://user.example/inbox"}}}
    elif method == "DOM.getDocument":
        result = {"root": {"nodeId": 1, "backendNodeId": 1}}
    reply = {"id": msg.get("id"), "result": result}
    if msg.get("sessionId"):
        reply["sessionId"] = msg["sessionId"]
    return reply, events


def handle_ws(conn, path, headers):
    key = headers.get("sec-websocket-key", "")
    accept = base64.b64encode(hashlib.sha1(
        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
    log({"ws_open": path})
    for text in ws_frames(conn):
        try:
            msg = json.loads(text)
        except ValueError:
            continue
        entry = {"ws": path, "method": msg.get("method")}
        # What an injection would carry, by the markers in cdpilot's scripts.
        params = msg.get("params") or {}
        text = str(params.get("expression") or "") + str(params.get("source") or "")
        tags = [tag for tag, marker in (("glow", "cdpilot-glow-overlay"),
                                        ("input-blocker", "overlay.id = 'cdpilot-input-blocker'"),
                                        ("stealth", "__cdpilot_stealth"))
                if marker in text]
        if tags:
            entry["tags"] = tags
        log(entry)
        reply, events = answer(msg, path)
        ws_send(conn, json.dumps(reply))
        for ev in events:
            ws_send(conn, json.dumps(ev))


def serve_one(conn):
    try:
        conn.settimeout(30)
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
        if headers.get("upgrade", "").lower() == "websocket":
            handle_ws(conn, path, headers)
        else:
            handle_http(conn, path, parts[0])
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(32)
    log({"ready": PORT})
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=serve_one, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()

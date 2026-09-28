#!/usr/bin/env python3
"""Web Bot Auth fixture origin for the bot-auth e2e test (test/test.js).

    python bot_auth_server.py --port PORT --jwks-file PATH --log-file PATH

Serves a page that, on its own, keeps making requests after the cdpilot
command that opened it has exited, and records every request it receives
as one JSON line: method, path, the three Web Bot Auth headers and the
result of verifying them against the JWKS (the output of
`cdpilot bot-auth directory`).

The verifier is written from the drafts, independently of cdpilot's
signing code: draft-meunier-web-bot-auth-architecture-05 §4.2 and RFC 9421
§2.5/§3.2 (signature base from the received Host header and the
Signature-Agent dictionary member named by `key`).

Pages:
  /start?late=MS&popup=MS   fetch("/sub.json") and fetch("/redirect") (302 to
           /after-redirect: each hop must be signed) now; after `late` ms
           fetch("/late"); after `popup` ms window.open("/popup") (a new tab)
  /start?...&worker=1 also starts a dedicated Worker (/worker.js) that
           fetches /from-worker
  /popup   a document with an <img src="/popup.png">
Anything else answers 200 with an empty body.
"""
import argparse
import base64
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START_HTML = """<!doctype html><title>bot-auth start</title>
<script>
const q = new URLSearchParams(location.search);
fetch('/sub.json');
fetch('/redirect');
setTimeout(() => fetch('/late?x=1'), Number(q.get('late') || 2500));
setTimeout(() => window.open('/popup', '_blank'), Number(q.get('popup') || 3000));
if (q.get('worker')) new Worker('/worker.js');
</script><p>start</p>"""
WORKER_JS = "fetch('/from-worker');"
POPUP_HTML = """<!doctype html><title>bot-auth popup</title>
<p>popup</p><img src="/popup.png" alt="">"""
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def parse_members(value):
    """Tiny RFC 8941 dictionary split for our headers: {label: raw member value}."""
    out, i = {}, 0
    while value and i < len(value):
        m = re.match(r'\s*([a-z*][a-z0-9_.*-]*)=', value[i:])
        if not m:
            raise ValueError(f"bad dictionary at {value[i:]!r}")
        label, i = m.group(1), i + m.end()
        start, depth, quoted = i, 0, False
        while i < len(value):
            c = value[i]
            if quoted:
                if c == "\\":
                    i += 1
                elif c == '"':
                    quoted = False
            elif c == '"':
                quoted = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 0:
                break
            i += 1
        out[label] = value[start:i].strip()
        i += 1
    return out


def verify(method, headers, jwks, now=None):
    """(ok, detail). Checks every member of Signature-Input tagged web-bot-auth."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    sig_input, sig, agent = (headers.get("Signature-Input"), headers.get("Signature"),
                             headers.get("Signature-Agent"))
    if not sig_input or not sig:
        return False, "unsigned"
    inputs, sigs = parse_members(sig_input), parse_members(sig)
    agents = parse_members(agent) if agent else {}
    now = time.time() if now is None else now
    for label, member in inputs.items():
        m = re.match(r"^\(([^)]*)\)(.*)$", member)
        if not m:
            return False, f"{label}: no component list"
        params = dict(re.findall(r';([a-z]+)=("[^"]*"|-?\d+)', m.group(2)))
        params = {k: v.strip('"') for k, v in params.items()}
        if params.get("tag") != "web-bot-auth":
            continue
        for need in ("created", "expires", "keyid", "alg", "nonce"):
            if need not in params:
                return False, f"{label}: missing {need}"
        if params["alg"] != "ed25519":
            return False, f"{label}: alg {params['alg']}"
        if not int(params["created"]) - 5 <= now <= int(params["expires"]):
            return False, f"{label}: outside created/expires"
        if len(base64.b64decode(params["nonce"])) != 64:
            return False, f"{label}: nonce is not 64 bytes"
        lines = []
        comps = re.findall(r'"([^"]+)"((?:;[a-z]+="[^"]*")*)', m.group(1))
        names = [c[0] for c in comps]
        if "@authority" not in names:
            return False, f"{label}: @authority not covered"
        for name, cparams in comps:
            if name == "@authority" and not cparams:
                value = headers.get("Host", "").lower()
            elif name == "signature-agent":
                key = re.fullmatch(r';key="([^"]+)"', cparams)
                if not key or key.group(1) not in agents:
                    return False, f"{label}: signature-agent member not found"
                value = agents[key.group(1)]
            else:
                return False, f"{label}: unexpected component {name}{cparams}"
            lines.append(f'"{name}"{cparams}: {value}')
        if agent and "signature-agent" not in names:
            return False, f"{label}: Signature-Agent present but not signed"
        lines.append(f'"@signature-params": {member}')
        jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == params["keyid"]), None)
        if jwk is None:
            return False, f"{label}: keyid not in the directory"
        pub = ed25519.Ed25519PublicKey.from_public_bytes(
            base64.urlsafe_b64decode(jwk["x"] + "=" * (-len(jwk["x"]) % 4)))
        raw = sigs.get(label, "")
        if not (raw.startswith(":") and raw.endswith(":")):
            return False, f"{label}: no signature"
        try:
            pub.verify(base64.b64decode(raw[1:-1]), "\n".join(lines).encode("utf-8"))
        except Exception:
            return False, f"{label}: signature does not verify"
        return True, label
    return False, "no web-bot-auth signature"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_any()

    def do_POST(self):
        self.handle_any()

    def handle_any(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        try:
            ok, detail = verify(self.command, self.headers, self.server.jwks)
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        entry = {"t": time.time(), "method": self.command, "path": self.path,
                 "verified": ok, "detail": detail,
                 "signature_agent": self.headers.get("Signature-Agent"),
                 "signature_input": self.headers.get("Signature-Input"),
                 "host": self.headers.get("Host")}
        with self.server.lock, open(self.server.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        path = self.path.split("?", 1)[0]
        body, ctype = b"", "text/plain"
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/after-redirect")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/start":
            body, ctype = START_HTML.encode(), "text/html; charset=utf-8"
        elif path == "/popup":
            body, ctype = POPUP_HTML.encode(), "text/html; charset=utf-8"
        elif path == "/worker.js":
            body, ctype = WORKER_JS.encode(), "text/javascript"
        elif path == "/popup.png":
            body, ctype = PNG_1PX, "image/png"
        elif path.endswith(".json") or path == "/late":
            body, ctype = b"{}", "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--jwks-file", required=True)
    ap.add_argument("--log-file", required=True)
    a = ap.parse_args()
    with open(a.jwks_file) as f:
        jwks = json.load(f)
    open(a.log_file, "w").close()
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    httpd.jwks, httpd.log_file, httpd.lock = jwks, a.log_file, threading.Lock()
    print(f"listening on 127.0.0.1:{a.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Minimal HTTP server that verifies Web Bot Auth (RFC 9421) signatures.

Logs every request's Signature/Signature-Input/Signature-Agent headers to
a JSON-lines file and verifies Ed25519 signatures against a JWKS file.
Serves a simple HTML page with verification status.

Usage:
  python3 test/fixtures/bot_auth_server.py \
      --port PORT --jwks-file PATH --log-file PATH
"""
import sys, os, json, base64, re, signal, argparse
from http.server import HTTPServer, BaseHTTPRequestHandler


class BotAuthHandler(BaseHTTPRequestHandler):
    """Verify Signature header on every request and log results."""

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        sig = self.headers.get("Signature")
        sig_input = self.headers.get("Signature-Input")
        sig_agent = self.headers.get("Signature-Agent")

        entry = {"method": method, "path": self.path, "host": self.headers.get("Host", ""),
                 "Signature": sig, "Signature-Input": sig_input,
                 "Signature-Agent": sig_agent, "verified": False, "error": None}

        if sig and sig_input:
            try:
                entry["verified"] = self._verify(method, sig, sig_input, sig_agent)
            except Exception as e:
                entry["error"] = str(e)

        with open(self.server.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

        code = 200 if (not sig or entry["verified"]) else 401
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        body = (f"<html><body><h1>Bot Auth Test</h1>"
                f"<p>Verified: {entry['verified']}</p>"
                f"<p>Error: {entry['error']}</p></body></html>")
        self.wfile.write(body.encode("utf-8"))

    def _verify(self, method, sig_header, sig_input_header, sig_agent_header):
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.exceptions import InvalidSignature

        # Parse  Signature: sig1=:base64:
        m = re.match(r"sig1=:([A-Za-z0-9+/=]+):", sig_header)
        if not m:
            raise ValueError("Bad Signature header format")
        sig_bytes = base64.b64decode(m.group(1))

        # Parse  Signature-Input: sig1=(<components>);<params>
        m2 = re.match(r"sig1=(\(.+?\);.*)", sig_input_header)
        if not m2:
            raise ValueError("Bad Signature-Input header format")
        params_str = m2.group(1)

        # Extract keyid
        m3 = re.search(r'keyid="([^"]+)"', params_str)
        if not m3:
            raise ValueError("No keyid")
        keyid = m3.group(1)

        # Find key in JWKS
        jwk = next((k for k in self.server.jwks["keys"]
                     if k.get("kid") == keyid), None)
        if not jwk:
            raise ValueError(f"keyid {keyid} not in JWKS")
        x_bytes = base64.urlsafe_b64decode(jwk["x"] + "===")
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(x_bytes)

        # Extract signed component names: ("@authority" "@method" ...)
        comp_m = re.search(r'\((.+?)\)', params_str)
        if not comp_m:
            raise ValueError("No component list")
        components = [c.strip('"') for c in comp_m.group(1).split()]

        # Reconstruct signature base
        host = self.headers.get("Host", "localhost")
        lines = []
        for comp in components:
            if comp == "@authority":
                lines.append(f'"@authority": {host}')
            elif comp == "@method":
                lines.append(f'"@method": {method}')
            elif comp == "@path":
                lines.append(f'"@path": {self.path}')
            elif comp == "signature-agent":
                lines.append(f'"signature-agent": {sig_agent_header or ""}')
            else:
                val = self.headers.get(comp)
                if val is not None:
                    lines.append(f'"{comp}": {val}')
        lines.append(f'"@signature-params": {params_str}')
        sig_base = "\n".join(lines).encode("utf-8")

        try:
            pub_key.verify(sig_bytes, sig_base)
            return True
        except InvalidSignature:
            return False

    def log_message(self, format, *a):
        pass  # suppress default stderr logging


def main():
    parser = argparse.ArgumentParser(description="Bot Auth verification server")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--jwks-file", required=True)
    parser.add_argument("--log-file", required=True)
    args = parser.parse_args()

    with open(args.jwks_file) as f:
        jwks = json.load(f)
    with open(args.log_file, "w"):
        pass  # truncate

    httpd = HTTPServer(("127.0.0.1", args.port), BotAuthHandler)
    httpd.jwks = jwks
    httpd.log_file = args.log_file

    signal.signal(signal.SIGTERM, lambda *_: (httpd.shutdown(), sys.exit(0)))
    print(f"bot-auth-server listening on 127.0.0.1:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    main()

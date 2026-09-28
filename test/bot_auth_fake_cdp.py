"""Web Bot Auth harness for test.js (no browser needed).

    python bot_auth_fake_cdp.py <path/to/cdpilot.py>

Loads cdpilot.py and runs its Web Bot Auth code against the draft's test
vectors and a fake browser socket: the signer helper's CDP loop
(_BotAuthSigner) sees Target.attachedToTarget / Fetch.requestPaused and
answers with Fetch.continueRequest, exactly as over the real wire. Prints one
JSON object {scenario: result}; a scenario that raises reports
{"error": traceback}. Scenarios that need the optional `cryptography`
package report {"skipped": "cryptography not installed"} without it.

Vectors: draft-meunier-web-bot-auth-architecture-05 Appendix A.2 and
github.com/cloudflare/web-bot-auth packages/web-bot-auth/test/test_data/
web_bot_auth_architecture_v2.json (Ed25519 key of RFC 9421 B.1.4; Ed25519
is deterministic, so the Signature values must match byte for byte).
"""
import asyncio
import base64
import contextlib
import importlib.util
import io
import json
import os
import statistics
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import bot_auth_server  # noqa: E402  the fixture origin's independent verifier

VECTOR_KEY = {"kty": "OKP", "crv": "Ed25519", "kid": "test-key-ed25519",
              "d": "n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU",
              "x": "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"}
VECTOR_KEYID = "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"
VECTORS = [  # web_bot_auth_architecture_v2.json, the two Ed25519 entries
    {"label": "sig1", "agent": None, "agent_key": None,
     "nonce": "zIW8+cdmA3vdYagbxojpONwa/l0EKJ/O3/wD486VvsQjO/RxPaSt6ZxvQaMcQzNnqKN/mQ6hpGiFro2L2qkz5A==",
     "signature": "sig1=:QKN4fTdIYfh82fvoZCQiQA1weuozfCS/Led2zTMbewMMqH8PI2Wsy/5c4ao6B6D09nraNQdBNOADg8aM1MqfCg==:",
     "signature_input": 'sig1=("@authority");created=1735689600;keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=4889289600;nonce="zIW8+cdmA3vdYagbxojpONwa/l0EKJ/O3/wD486VvsQjO/RxPaSt6ZxvQaMcQzNnqKN/mQ6hpGiFro2L2qkz5A==";tag="web-bot-auth"'},
    {"label": "sig2", "agent": "https://signature-agent.test", "agent_key": "agent2",
     "nonce": "n9p433xm+NJ3ph3upfBIGmsuwHw387YV7Q/F+6BSpGCVjYCqQw6rznNA8PVVLySrAWsv0hQtFioQb6E1YsauiA==",
     "signature": "sig2=:RdNFx5Bj6au3YgAMQL/RzmUlZE8QZLIaXGRpw985hWnwPfMxT228NMk6ehRS1PSl4e8PhbNZACSanGdhEwYCCg==:",
     "signature_input": 'sig2=("@authority" "signature-agent";key="agent2");created=1735689600;keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=4889289600;nonce="n9p433xm+NJ3ph3upfBIGmsuwHw387YV7Q/F+6BSpGCVjYCqQw6rznNA8PVVLySrAWsv0hQtFioQb6E1YsauiA==";tag="web-bot-auth"',
     "signature_agent": 'agent2="https://signature-agent.test"'},
]
# The draft's A.2.2 signature base, written out (RFC 8792 unwrapped).
DRAFT_A22_BASE = (
    '"@authority": example.com\n'
    '"signature-agent";key="agent2": "https://signature-agent.test"\n'
    '"@signature-params": ("@authority" "signature-agent";key="agent2");created=1735689600'
    ';keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=4889289600'
    ';nonce="XeP72svPKNiGEg3aDE7WJuTpN69H08oMFqC8NLFy1MptpENAT3WZTYwK+MYdsFMlaqHCJGo9ZAhqer1NWY9Epg=="'
    ';tag="web-bot-auth"')
# Its printed Signature ("DGiW2Erl…") does not verify against this base with the
# RFC 9421 B.1.4 key (A.2.1 and A.2.3 do); the v2 JSON above is the vector
# the draft points to (B.3) and it is reproduced byte for byte. So A.2.2 is
# checked for its base only; A.2.1 and the legacy A.2.3 also for the signature.
DRAFT_TEXT_VECTORS = [
    ("draft_a21", None,
     '("@authority");created=1735689600;keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"'
     ';alg="ed25519";expires=4889289600'
     ';nonce="g0iqFa9e1ffijlyOScDkXpfSmTbYpRNSGPJrQ1It20ahwgzB3jOUcdgLgFxUg7RMtW4V8IILaKKtA+YuSyIgJQ=="'
     ';tag="web-bot-auth"',
     "FFASViSdcgsyaqqYiCnkHreeZzbNKcTzDvZC5uVlP/dn9IbWj8j0o4wKFTH3rBnUiSUBduwm1Gp5VlIPCp01Ag=="),
    ("draft_a23_legacy", "https://signature-agent.test",
     '("@authority" "signature-agent");created=1735689600'
     ';keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=1735693200'
     ';nonce="e8N7S2MFd/qrd6T2R3tdfAuuANngKI7LFtKYI/vowzk4lAZYadIX6wW25MwG7DCT9RUKAJ0qVkU0mEeLElW1qg=="'
     ';tag="web-bot-auth"',
     "jdq0SqOwHdyHr9+r5jw3iYZH6aNGKijYp/EstF4RQTQdi5N5YYKrD+mCT1HA1nZDsi6nJKuHxUi/5Syp3rLWBA=="),
]


def have_crypto():
    try:
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
        return True
    except ImportError:
        return False


def vector_private_key():
    from cryptography.hazmat.primitives.asymmetric import ed25519
    d = base64.urlsafe_b64decode(VECTOR_KEY["d"] + "=")
    return ed25519.Ed25519PrivateKey.from_private_bytes(d)


def load(path):
    spec = importlib.util.spec_from_file_location("cdpilot_botauth_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeSocket:
    """A browser-level CDP socket: records what the signer sends, replays events."""

    def __init__(self):
        self.sent, self.inbox, self.closed = [], asyncio.Queue(), False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        item = await self.inbox.get()
        if item is None:
            raise ConnectionError("browser gone")
        return json.dumps(item)

    def push(self, item):
        self.inbox.put_nowait(item)

    async def settle(self):
        for _ in range(20):  # let the signer drain the inbox
            await asyncio.sleep(0)


def paused(rid, url, session="S1", method="GET", headers=None):
    return {"method": "Fetch.requestPaused", "sessionId": session,
            "params": {"requestId": rid, "resourceType": "Document",
                       "request": {"url": url, "method": method,
                                   "headers": headers or {"Accept": "text/html"}}}}


def sc_vectors(mod):
    """The draft / Cloudflare Ed25519 vectors, base and (with crypto) signature."""
    out = {}
    for v in VECTORS:
        params = v["signature_input"].split("=", 1)[1]
        base = mod._bot_auth_signature_base("GET", "example.com", "/path/to/resource",
                                            v["agent"], params).decode()
        want = ('"@authority": example.com\n'
                + (f'"signature-agent";key="{v["agent_key"]}": "{v["agent"]}"\n' if v["agent"] else "")
                + f'"@signature-params": {params}')
        out[v["label"] + "_base"] = base == want
    a22_params = DRAFT_A22_BASE.rsplit('"@signature-params": ', 1)[1]
    out["draft_a22_base"] = mod._bot_auth_signature_base(
        "GET", "example.com", "/", "https://signature-agent.test", a22_params).decode() == DRAFT_A22_BASE
    if not have_crypto():
        out["signatures"] = "skipped: cryptography not installed"
        return out
    key = vector_private_key()
    for name, agent, params, signature in DRAFT_TEXT_VECTORS:
        base = mod._bot_auth_signature_base("GET", "example.com", "/", agent, params)
        out[name + "_signature"] = base64.b64encode(key.sign(base)).decode() == signature
    for v in VECTORS:
        h = mod._bot_auth_sign_request(
            "GET", "https://example.com/path/to/resource", v["agent"], key, VECTOR_KEYID,
            now=1735689600, expires=4889289600, nonce=v["nonce"], label=v["label"],
            agent_key=v["agent_key"])
        out[v["label"] + "_headers"] = (
            h.get("Signature-Input") == v["signature_input"]
            and h.get("Signature") == v["signature"]
            and h.get("Signature-Agent") == v.get("signature_agent"))
    return out


def sc_thumbprint(mod):
    """RFC 7638 thumbprint of an OKP key (RFC 8037 A.3 example + the vector key)."""
    return {
        "rfc8037_a3": mod._bot_auth_jwk_thumbprint_raw(
            "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo") == "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k",
        "vector_key": mod._bot_auth_jwk_thumbprint_raw(VECTOR_KEY["x"]) == VECTOR_KEYID,
        "authority": [mod._bot_auth_authority(u) for u in (
            "https://Example.COM/a?b", "http://example.com:80/", "https://example.com:443/",
            "http://127.0.0.1:8080/x", "https://user:pw@example.com:8443/", "http://[::1]:9000/")],
    }


def sc_helper(mod):
    """The signer loop over a fake socket: attach, sign, skip, fail, exit."""
    signs, logs, ready = [], [], []

    def sign(method, url):
        signs.append((method, url))
        if "boom" in url:
            raise RuntimeError("key unavailable")
        return {"Signature-Agent": 'sig1="https://agent.test"',
                "Signature-Input": 'sig1=("@authority")', "Signature": "sig1=:AAAA:"}

    async def body():
        ws = FakeSocket()
        signer = mod._BotAuthSigner(ws, sign, logs.append)
        task = asyncio.ensure_future(signer.run(on_ready=ready.append))
        await ws.settle()
        first = list(ws.sent)
        ws.push({"method": "Target.attachedToTarget", "params": {
            "sessionId": "S1", "waitingForDebugger": True,
            "targetInfo": {"targetId": "T1", "type": "page", "url": "about:blank"}}})
        ws.push({"method": "Target.attachedToTarget", "params": {
            "sessionId": "S9", "waitingForDebugger": False,
            "targetInfo": {"targetId": "T9", "type": "other"}}})
        ws.push({"id": first[0]["id"], "result": {}})
        await ws.settle()
        attach = [m for m in ws.sent[len(first):]]
        ws.push(paused("R1", "https://example.com/p?q=1",
                       headers={"Accept": "text/html", "signature": "stale", "X-Keep": "1"}))
        ws.push(paused("R2", "data:text/plain,hi"))
        ws.push(paused("R3", "blob:https://example.com/0f0e"))
        ws.push(paused("R4", "chrome-extension://abc/x.js"))
        ws.push(paused("R5", "https://example.com/boom?token=SECRET123", session="S2"))
        await ws.settle()
        ws.push(None)  # browser closed
        await asyncio.wait_for(task, 2)
        conts = {m["params"]["requestId"]: m for m in ws.sent
                 if m.get("method") == "Fetch.continueRequest"}
        return first, attach, conts, task.done()

    first, attach, conts, finished = asyncio.run(body())
    r1 = conts.get("R1", {})
    names = [h["name"] for h in r1.get("params", {}).get("headers", [])]
    return {
        "first": [first[0].get("method"), first[0].get("params"), first[0].get("sessionId")],
        "ready": ready,
        "attach": [[m.get("method"), m.get("sessionId"), m.get("params")] for m in attach],
        "r1_session": r1.get("sessionId"),
        "r1_headers": names,
        "r1_values": {h["name"]: h["value"] for h in r1.get("params", {}).get("headers", [])},
        "unsigned": {rid: [conts[rid].get("sessionId"), sorted(conts[rid]["params"])]
                     for rid in ("R2", "R3", "R4", "R5") if rid in conts},
        "signed_urls": [u for _, u in signs],
        "logs": logs,
        "finished": finished,
    }


def sc_helper_real_signature(mod):
    """The helper with the real signing function: every continued request
    verifies (independent fixture verifier) and one signature takes < 1 ms."""
    if not have_crypto():
        return {"skipped": "cryptography not installed"}
    from cryptography.hazmat.primitives.asymmetric import ed25519
    key = ed25519.Ed25519PrivateKey.generate()
    jwk = mod._bot_auth_public_jwk(key)
    agent = "https://agent.example"

    def sign(method, url):
        return mod._bot_auth_sign_request(method, url, agent, key, jwk["kid"])

    urls = ["https://example.com/", "http://127.0.0.1:8080/api?x=1", "https://Shop.Example:8443/c",
            "https://example.com:443/default-port"]

    async def body():
        ws = FakeSocket()
        task = asyncio.ensure_future(mod._BotAuthSigner(ws, sign).run())
        for i, u in enumerate(urls):
            ws.push(paused(f"R{i}", u, method="POST" if i == 1 else "GET"))
        await ws.settle()
        ws.push(None)
        await asyncio.wait_for(task, 2)
        return [m for m in ws.sent if m.get("method") == "Fetch.continueRequest"]

    results = []
    for u, m in zip(urls, asyncio.run(body())):
        headers = {h["name"]: h["value"] for h in m["params"]["headers"]}
        headers["Host"] = mod._bot_auth_authority(u)  # what the browser sends as Host
        results.append(bot_auth_server.verify("GET", headers, {"keys": [jwk]}))
    # Tampering is caught: the same headers for another host fail.
    tampered = dict(headers, Host="evil.example")
    times = []
    for _ in range(300):
        t0 = time.perf_counter()
        sign("GET", "https://example.com/some/path?q=1")
        times.append((time.perf_counter() - t0) * 1000)
    return {"verified": results, "tampered": bot_auth_server.verify("GET", tampered, {"keys": [jwk]}),
            "median_ms": round(statistics.median(times), 4)}


def sc_navigate_skips_stealth(mod):
    """navigate_collect in stealth mode: stealth script + UA override are sent
    normally, and not at all while the Web Bot Auth signer runs."""

    class NavSocket:
        def __init__(self):
            self.sent, self.q = [], asyncio.Queue()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def send(self, raw):
            msg = json.loads(raw)
            self.sent.append(msg.get("method"))
            result = {}
            if msg.get("method") == "Browser.getVersion":
                result = {"userAgent": "Mozilla/5.0 HeadlessChrome/150.0.0.0 Safari/537.36",
                          "product": "HeadlessChrome/150.0.0.0"}
            elif msg.get("method") == "Runtime.evaluate":
                result = {"result": {"type": "string", "value": "page text"}}
            self.q.put_nowait({"id": msg.get("id"), "result": result})
            if msg.get("method") == "Page.navigate":
                self.q.put_nowait({"method": "Page.loadEventFired", "params": {}})

        async def recv(self):
            return json.dumps(await self.q.get())

    import types
    fake = types.ModuleType("websockets")
    sockets = []

    def connect(*a, **k):
        sockets.append(NavSocket())
        return sockets[-1]
    fake.connect = connect
    real = sys.modules.get("websockets")
    sys.modules["websockets"] = fake
    os.environ["CDPILOT_MODE"] = "stealth"
    out = {}
    try:
        for label, active in (("off", False), ("on", True)):
            mod._bot_auth_active = lambda port=None, _a=active: _a
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                asyncio.run(mod.navigate_collect("ws://fake/page", "https://example.com/", glow=False))
            sent = sockets[-1].sent
            out[label] = {"stealth_script": "Page.addScriptToEvaluateOnNewDocument" in sent,
                          "ua_override": "Emulation.setUserAgentOverride" in sent,
                          "navigated": "Page.navigate" in sent}
    finally:
        os.environ.pop("CDPILOT_MODE", None)
        if real is not None:
            sys.modules["websockets"] = real
        else:
            sys.modules.pop("websockets", None)
    return out


def sc_conflict_and_log(mod):
    """Stealth conflict = one warning line; the session log masks signatures."""
    out = {}
    for label, args, env in (("flag", ["--bot-auth", "--stealth"], None),
                             ("mode", ["--bot-auth"], "undetected"),
                             ("none", ["--bot-auth"], "regular")):
        if env:
            os.environ["CDPILOT_MODE"] = env
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            hit = mod._bot_auth_check_stealth_conflict(args)
        os.environ.pop("CDPILOT_MODE", None)
        out[label] = [hit, err.getvalue().count("\n"), "stealth injection skipped" in err.getvalue()]
    text = ('Signature: sig1=:QKN4fTdIYfh82fvoZCQiQA1weuozfCS/Led2zTMbewMMqH8PI2Wsy/5c4ao6B6D09nraNQdBNOADg8aM1MqfCg==:\n'
            '"Signature-Input": "sig1=(\\"@authority\\");created=1;keyid=\\"abc\\""\n'
            'Bot Auth: signing every request as https://agent.test')
    scrubbed = mod._slog_scrub_text(text)
    out["slog"] = {"signature_masked": "QKN4fTdIYfh8" not in scrubbed,
                   "input_masked": "created=1" not in scrubbed,
                   "status_kept": "Bot Auth: signing every request" in scrubbed}
    return out


def sc_state(mod):
    """Helper state: on/off label, liveness by pid, stop clears it."""
    port = 45123
    mod._bot_auth_clear_state(port)
    off = mod._bot_auth_status_label(port)
    mod._bot_auth_save_state(port, {"token": "t", "pid": os.getpid(), "ready": True,
                                    "keyid": "KID123", "port": port})
    on = mod._bot_auth_status_label(port)
    active = mod._bot_auth_active(port)
    mod._bot_auth_save_state(port, {"token": "t", "pid": 2 ** 22 + 12345, "ready": True,
                                    "keyid": "KID123", "port": port})
    dead = mod._bot_auth_status_label(port)
    stopped = mod._bot_auth_stop_helper(port, wait_s=0)
    return {"off": off, "on": on, "active": active, "dead_pid": dead, "stopped": stopped,
            "state_after_stop": mod._bot_auth_load_state(port)}


SCENARIOS = [sc_vectors, sc_thumbprint, sc_helper, sc_helper_real_signature,
             sc_navigate_skips_stealth, sc_conflict_and_log, sc_state]


def main():
    home = tempfile.mkdtemp(prefix="cdpilot-botauth-fake-")
    os.environ.update(CDPILOT_HOME=home, CDPILOT_PROFILE=os.path.join(home, "profile"),
                      CDP_PORT=os.environ.get("CDP_PORT", "19225"), CDPILOT_LOG="0")
    os.environ.pop("CDPILOT_MODE", None)
    mod = load(sys.argv[1])
    results = {}
    for sc in SCENARIOS:
        try:
            results[sc.__name__[3:]] = sc(mod)
        except Exception:
            results[sc.__name__[3:]] = {"error": traceback.format_exc()}
    print(json.dumps(results))


if __name__ == "__main__":
    main()

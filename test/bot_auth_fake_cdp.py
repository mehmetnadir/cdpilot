#!/usr/bin/env python3
"""Fake CDP harness for Web Bot Auth unit tests.

Tests signature base construction, JWK thumbprint (RFC 7638), key
management and the cryptography-missing fallback — all without a browser.
Outputs JSON: {"test_name": true/false, ...}.

Usage: python3 test/bot_auth_fake_cdp.py src/cdpilot.py
"""
import sys, os, json, importlib.util, tempfile, io, base64, hashlib
from contextlib import redirect_stdout, redirect_stderr


def _load_cdpilot(path):
    """Load cdpilot as a module without executing __main__ guard."""
    spec = importlib.util.spec_from_file_location("cdpilot_mod", path)
    mod = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = [path]
    # Ensure isolated env to avoid port conflicts
    os.environ.setdefault("CDP_PORT", "19222")
    os.environ.setdefault("CDPILOT_LOG", "0")
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old_argv
    return mod


def run_tests(module_path):
    results = {}
    cd = _load_cdpilot(module_path)

    # ── 1. JWK thumbprint (RFC 7638) with Cloudflare test key ──
    # The Cloudflare example directory has:
    #   x = "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"
    #   kid = "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"
    try:
        x_val = "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"
        kid = cd._bot_auth_jwk_thumbprint_raw(x_val)
        results["jwk_thumbprint_cloudflare"] = (
            kid == "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U")
    except Exception as e:
        results["jwk_thumbprint_cloudflare"] = False
        results["jwk_thumbprint_cloudflare_err"] = str(e)

    # ── 2. Signature base format (RFC 9421 §2.5) ──
    try:
        params = ('("@authority" "@method" "@path" "signature-agent")'
                  ';created=1735689600;expires=1735693200'
                  ';keyid="testkey";alg="ed25519"'
                  ';nonce="abc123";tag="web-bot-auth"')
        base = cd._bot_auth_signature_base(
            "GET", "example.com", "/foo", "https://bot.example.com", params)
        expected = (
            '"@authority": example.com\n'
            '"@method": GET\n'
            '"@path": /foo\n'
            '"signature-agent": "https://bot.example.com"\n'
            '"@signature-params": ' + params
        ).encode("utf-8")
        results["signature_base_format"] = (base == expected)
    except Exception as e:
        results["signature_base_format"] = False
        results["signature_base_format_err"] = str(e)

    # ── 3. Round-trip: generate key → sign → verify ──
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization

        priv = ed25519.Ed25519PrivateKey.generate()
        pub_raw = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        x_b64 = cd._b64url(pub_raw)
        keyid = cd._bot_auth_jwk_thumbprint_raw(x_b64)

        headers = cd._bot_auth_sign_request(
            "GET", "https://example.com/test?q=1",
            "https://bot.example.com", priv, keyid)

        # Verify: extract signature, reconstruct base, verify with pub key
        sig_input = headers["Signature-Input"]
        sig_raw = headers["Signature"]

        # Parse sig_raw: sig1=:base64:
        sig_b64 = sig_raw.split(":")[1]
        sig_bytes = base64.b64decode(sig_b64)

        # Parse sig_input: sig1=<params>
        params_str = sig_input[len("sig1="):]
        base = cd._bot_auth_signature_base(
            "GET", "example.com", "/test?q=1",
            "https://bot.example.com", params_str)

        priv.public_key().verify(sig_bytes, base)
        results["sign_verify_roundtrip"] = True
    except Exception as e:
        results["sign_verify_roundtrip"] = False
        results["sign_verify_roundtrip_err"] = str(e)

    # ── 4. bot-auth init / status / directory (isolated CDPILOT_HOME) ──
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Re-load cdpilot with isolated home
            os.environ["CDPILOT_HOME"] = tmpdir
            cd2 = _load_cdpilot(module_path)

            # init
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                cd2._bot_auth_generate_keypair("https://test.example.com")
            key_file = os.path.join(tmpdir, "bot-auth", "ed25519.key")
            cfg_file = os.path.join(tmpdir, "bot-auth", "config.json")
            results["init_creates_key"] = os.path.exists(key_file)
            results["init_creates_config"] = os.path.exists(cfg_file)

            # permissions
            if os.name != "nt":
                st = os.stat(key_file)
                results["key_permissions_0600"] = (st.st_mode & 0o777) == 0o600
            else:
                results["key_permissions_0600"] = True

            # config content
            with open(cfg_file) as f:
                cfg = json.load(f)
            results["config_has_agent_url"] = cfg.get("agent_url") == "https://test.example.com"
            results["config_has_keyid"] = bool(cfg.get("keyid"))

            # directory
            directory = cd2._bot_auth_build_directory()
            results["directory_has_keys"] = (
                "keys" in directory and len(directory["keys"]) == 1)
            results["directory_key_has_kid"] = (
                directory["keys"][0].get("kid") == cfg["keyid"])
            results["directory_key_has_x"] = bool(
                directory["keys"][0].get("x"))

            del os.environ["CDPILOT_HOME"]
    except Exception as e:
        results["init_creates_key"] = False
        results["init_err"] = str(e)
        os.environ.pop("CDPILOT_HOME", None)

    # ── 5. Missing cryptography → exit 2 ──
    try:
        saved = sys.modules.get("cryptography")
        saved_sub = {k: v for k, v in sys.modules.items()
                     if k.startswith("cryptography.")}
        # Block imports
        sys.modules["cryptography"] = None
        for k in list(sys.modules):
            if k.startswith("cryptography."):
                sys.modules[k] = None
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                cd._bot_auth_require_crypto()
            results["missing_crypto_exit2"] = False
        except SystemExit as e:
            results["missing_crypto_exit2"] = (e.code == 2)
            results["missing_crypto_message"] = "pip install" in buf.getvalue()
    except Exception as e:
        results["missing_crypto_exit2"] = False
        results["missing_crypto_err"] = str(e)
    finally:
        # Restore
        if saved is not None:
            sys.modules["cryptography"] = saved
        else:
            sys.modules.pop("cryptography", None)
        for k, v in saved_sub.items():
            sys.modules[k] = v

    print(json.dumps(results))
    all_pass = all(v for k, v in results.items() if not k.endswith("_err"))
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 bot_auth_fake_cdp.py <path_to_cdpilot.py>")
        sys.exit(1)
    run_tests(sys.argv[1])

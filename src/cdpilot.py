#!/usr/bin/env python3
"""
cdpilot — Zero-dependency browser automation from your terminal.

Controls any Chromium-based browser (Brave, Chrome, Chromium) via the
Chrome DevTools Protocol (CDP). No Puppeteer, no Playwright, no Selenium.

Usage:
  cdpilot <command> [arguments]

Environment:
  CDP_PORT             CDP debugging port (default: 9222)
  CHROME_BIN           Browser binary path (auto-detected if not set)
  CDPILOT_PROFILE      Isolated browser profile directory
"""

__version__ = "0.1.2"

import asyncio
import json
import sys
import base64
import os
import time
import urllib.request
import subprocess
import shutil
import platform
import socket
import difflib

# ─── Session Configuration ───
# cdpilot runs in its own Chrome instance on the configured CDP port.
# The user's existing Chrome/browser session is not affected.

CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
CHROME_BIN = os.environ.get("CHROME_BIN")
PROFILE_DIR = os.environ.get("CDPILOT_PROFILE", os.path.expanduser("~/.cdpilot/profile"))
if platform.system() == "Windows":
    SCREENSHOT_DIR = os.path.expandvars(r"%TEMP%")
else:
    SCREENSHOT_DIR = "/tmp"

DEV_EXTENSIONS_FILE = os.path.join(PROFILE_DIR, 'dev-extensions.json')
PROXY_CONFIG_FILE = os.path.join(PROFILE_DIR, 'proxy.json')
HEADLESS_CONFIG_FILE = os.path.join(PROFILE_DIR, 'headless.json')
DOWNLOAD_CONFIG_FILE = os.path.join(PROFILE_DIR, 'download-config.json')
SESSION_FILE = os.path.join(PROFILE_DIR, 'sessions.json')

# ─── Session Management ───
# Each session gets its own browser window.
# The BROWSER_SESSION env var sets the session identifier.

def _get_session_id():
    """Return the unique identifier for the current session."""
    sid = os.environ.get('BROWSER_SESSION', '')
    if sid:
        return sid
    # Default session — all commands share the same window
    return "cdpilot-default"

def _load_sessions():
    """Read the session registry."""
    try:
        with open(SESSION_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_sessions(sessions):
    """Write the session registry."""
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, 'w') as f:
        json.dump(sessions, f, indent=2)

def _cleanup_stale_sessions():
    """Remove sessions whose window/target no longer exists."""
    sessions = _load_sessions()
    if not sessions:
        return sessions
    tabs = cdp_get("/json") or []
    active_target_ids = {t.get("id") for t in tabs}
    cleaned = {}
    for sid, info in sessions.items():
        # Keep session if its target is still active
        if info.get("target_id") in active_target_ids:
            cleaned[sid] = info
    if len(cleaned) != len(sessions):
        _save_sessions(cleaned)
    return cleaned

# ─── Global State ───
INTERCEPT_RULES = []  # list of (pattern, action, data) tuples
DIALOG_MODE = None    # 'accept', 'dismiss', or None
_current_session_id = None  # lazy init

# ─── Visual Indicator Overlay CSS ───

GLOW_CSS = """
(function() {
  if (document.getElementById('cdpilot-glow')) return 'already active';
  const style = document.createElement('style');
  style.id = 'cdpilot-glow';
  style.textContent = `
    @keyframes cdpilot-pulse {
      0%, 100% { box-shadow: inset 0 0 20px 4px rgba(34, 197, 94, 0.25), inset 0 0 60px 8px rgba(34, 197, 94, 0.08); }
      50% { box-shadow: inset 0 0 30px 6px rgba(34, 197, 94, 0.35), inset 0 0 80px 12px rgba(34, 197, 94, 0.12); }
    }
    body::after {
      content: '';
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      pointer-events: none;
      z-index: 2147483647;
      animation: cdpilot-pulse 2s ease-in-out infinite;
      border: 2px solid rgba(34, 197, 94, 0.3);
      border-radius: 0;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
  `;
  document.head.appendChild(style);
  return 'glow active';
})()
"""

GLOW_OFF_CSS = """
(function() {
  const el = document.getElementById('cdpilot-glow');
  if (el) { el.remove(); return 'glow off'; }
  return 'already off';
})()
"""

# ─── Input Blocker (prevent user interference during automation) ───

INPUT_BLOCKER_ON = """
(function() {
  if (document.getElementById('cdpilot-input-blocker')) return 'blocker already active';
  const overlay = document.createElement('div');
  overlay.id = 'cdpilot-input-blocker';
  overlay.style.cssText = `
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    z-index: 2147483646; cursor: not-allowed;
    background: transparent;
  `;
  overlay.addEventListener('mousedown', e => { e.stopPropagation(); e.preventDefault(); }, true);
  overlay.addEventListener('mouseup', e => { e.stopPropagation(); e.preventDefault(); }, true);
  overlay.addEventListener('click', e => { e.stopPropagation(); e.preventDefault(); }, true);
  overlay.addEventListener('dblclick', e => { e.stopPropagation(); e.preventDefault(); }, true);
  overlay.addEventListener('contextmenu', e => { e.stopPropagation(); e.preventDefault(); }, true);
  overlay.addEventListener('wheel', e => { e.stopPropagation(); e.preventDefault(); }, {capture: true, passive: false});
  document.addEventListener('keydown', function _cb(e) {
    if (!document.getElementById('cdpilot-input-blocker')) {
      document.removeEventListener('keydown', _cb, true);
      return;
    }
    e.stopPropagation(); e.preventDefault();
  }, true);
  document.addEventListener('keyup', function _cb(e) {
    if (!document.getElementById('cdpilot-input-blocker')) {
      document.removeEventListener('keyup', _cb, true);
      return;
    }
    e.stopPropagation(); e.preventDefault();
  }, true);
  document.addEventListener('keypress', function _cb(e) {
    if (!document.getElementById('cdpilot-input-blocker')) {
      document.removeEventListener('keypress', _cb, true);
      return;
    }
    e.stopPropagation(); e.preventDefault();
  }, true);
  document.body.appendChild(overlay);
  return 'input blocker active';
})()
"""

INPUT_BLOCKER_OFF = """
(function() {
  const el = document.getElementById('cdpilot-input-blocker');
  if (el) { el.remove(); return 'input blocker off'; }
  return 'blocker already off';
})()
"""

# ─── Automation Indicator Wrapper ───

_glow_script_id = None  # addScriptToEvaluateOnNewDocument identifier

GLOW_ACTIVATE_JS = "document.documentElement.dataset.cdpilotActive = 'true';"
GLOW_DEACTIVATE_JS = """
document.documentElement.removeAttribute('data-cdpilot-active');
var _go = document.getElementById('cdpilot-glow-overlay');
var _gs = document.getElementById('cdpilot-glow-style');
if (_go) _go.remove();
if (_gs) _gs.remove();
"""

async def _control_start(ws_url):
    """Enable visual indicator and input blocker at command start."""
    global _glow_script_id
    try:
        # Inject activation marker on every new page load
        r = await cdp_send(ws_url, [
            (901, "Page.addScriptToEvaluateOnNewDocument", {"source": GLOW_ACTIVATE_JS}),
            (902, "Runtime.evaluate", {"expression": GLOW_ACTIVATE_JS, "returnByValue": True}),
            (903, "Runtime.evaluate", {"expression": INPUT_BLOCKER_ON, "returnByValue": True}),
        ])
        # Save script identifier for cleanup
        if 901 in r and "identifier" in r.get(901, {}):
            _glow_script_id = r[901]["identifier"]
    except Exception:
        pass  # Silent fail if no connection

async def _control_end(ws_url):
    """Disable visual indicator and input blocker at command end."""
    global _glow_script_id
    try:
        cmds = [
            (903, "Runtime.evaluate", {"expression": GLOW_DEACTIVATE_JS, "returnByValue": True}),
            (904, "Runtime.evaluate", {"expression": INPUT_BLOCKER_OFF, "returnByValue": True}),
        ]
        # Remove the persistent new-document script
        if _glow_script_id:
            cmds.append((905, "Page.removeScriptToEvaluateOnNewDocument", {"identifier": _glow_script_id}))
            _glow_script_id = None
        await cdp_send(ws_url, cmds)
    except Exception:
        pass  # Silent fail if no connection

# ─── Connection Helpers ───

def cdp_get(path):
    """GET request to a CDP HTTP endpoint."""
    try:
        with urllib.request.urlopen(f"{CDP_BASE}{path}", timeout=3) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return None


def get_tabs():
    """Retrieve all CDP targets."""
    result = cdp_get("/json")
    if result is None:
        print("CDP connection error. Is the browser running?", file=sys.stderr)
        sys.exit(1)
    return result


def _get_session_window_target_id():
    """Return the window target ID for the current session (None if not set)."""
    sid = _get_session_id()
    sessions = _load_sessions()
    info = sessions.get(sid)
    if not info:
        return None
    return info.get("target_id")

SESSION_IDLE_TIMEOUT = 300  # 5 minutes (seconds)


def _cleanup_idle_sessions():
    """Close session windows idle for more than 5 minutes."""
    sessions = _load_sessions()
    if not sessions:
        return
    now = time.time()
    to_remove = []
    for sid, info in sessions.items():
        last_used = info.get("last_used", 0)
        if last_used and (now - last_used) > SESSION_IDLE_TIMEOUT:
            to_remove.append(sid)
            target_id = info.get("target_id")
            if target_id:
                try:
                    urllib.request.urlopen(
                        f"{CDP_BASE}/json/close/{target_id}", timeout=2)
                except Exception:
                    pass
    if to_remove:
        for sid in to_remove:
            sessions.pop(sid, None)
        _save_sessions(sessions)


def _update_session_timestamp():
    """Update the last_used timestamp for the current session."""
    sid = _get_session_id()
    sessions = _load_sessions()
    if sid in sessions:
        sessions[sid]["last_used"] = time.time()
        _save_sessions(sessions)


def _create_session_window():
    """Create a new tab for the current session and register it.

    Uses CDP Target.createTarget to open a tab in the existing window
    (does not steal focus). newWindow: False — no new window is opened.
    """
    sid = _get_session_id()

    # Check existing tabs — reuse if already open
    tabs = cdp_get("/json")
    if tabs:
        pages = [t for t in tabs if t.get("type") == "page"]
        if pages:
            # A page is already open, no need to create a new tab
            target_id = pages[0].get("id")
            if target_id:
                sessions = _load_sessions()
                sessions[sid] = {
                    "target_id": target_id,
                    "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_used": time.time(),
                }
                _save_sessions(sessions)
                return target_id

    # No tabs open — create a new tab (not a window)
    try:
        req = urllib.request.Request(
            f"{CDP_BASE}/json/new?about:blank",
            method="PUT"
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        target_id = data.get("id")
    except Exception:
        target_id = None

    if target_id:
        sessions = _load_sessions()
        sessions[sid] = {
            "target_id": target_id,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_used": time.time(),
        }
        _save_sessions(sessions)

    return target_id

def _ensure_session_window():
    """Create a session window if none exists, or validate the existing one."""
    target_id = _get_session_window_target_id()
    if target_id:
        # Verify target still exists
        tabs = cdp_get("/json") or []
        if any(t.get("id") == target_id for t in tabs):
            return target_id
        # Target gone — clean up and recreate
        sessions = _load_sessions()
        sid = _get_session_id()
        sessions.pop(sid, None)
        _save_sessions(sessions)
    return _create_session_window()

def get_page_ws(prefer_url=None):
    """Find the WebSocket URL for the appropriate page target.

    If a session window exists, only looks at tabs in that window.
    Otherwise creates a new session window.
    """
    tabs = get_tabs()
    pages = [t for t in tabs if t.get("type") == "page"]

    # Get target ID for the current session window
    session_target_id = _get_session_window_target_id()

    if session_target_id and pages:
        session_page = None
        for p in pages:
            if p.get("id") == session_target_id:
                session_page = p
                break

        if session_page:
            return session_page["webSocketDebuggerUrl"], session_page
        else:
            # Session target gone — clean up
            sessions = _load_sessions()
            sid = _get_session_id()
            sessions.pop(sid, None)
            _save_sessions(sessions)

    # No session window or no tabs — create one
    if cdp_get("/json/version"):
        new_target_id = _create_session_window()
        if new_target_id:
            # Short wait for CDP to register the new target
            for _ in range(10):
                time.sleep(0.3)
                tabs = get_tabs()
                for t in tabs:
                    if t.get("id") == new_target_id:
                        return t["webSocketDebuggerUrl"], t

    # Fallback: use any available page
    if pages:
        if prefer_url:
            for p in pages:
                if prefer_url in p.get("url", ""):
                    return p["webSocketDebuggerUrl"], p
        for p in pages:
            url = p.get("url", "")
            if "chrome://" not in url and "omnibox" not in url:
                return p["webSocketDebuggerUrl"], p
        return pages[0]["webSocketDebuggerUrl"], pages[0]

    print("No active page found.", file=sys.stderr)
    sys.exit(1)


def activate_tab(page_id):
    """Bring a tab to the foreground."""
    try:
        urllib.request.urlopen(f"{CDP_BASE}/json/activate/{page_id}", timeout=2)
    except:
        pass


# ─── CDP WebSocket Operations ───

async def cdp_send(ws_url, commands, timeout=15):
    """Send multiple CDP commands and collect results."""
    import websockets
    results = {}
    try:
        async with websockets.connect(ws_url, max_size=100 * 1024 * 1024) as ws:
            for cmd_id, method, params in commands:
                await ws.send(json.dumps({"id": cmd_id, "method": method, "params": params or {}}))

            pending = {c[0] for c in commands}
            start = time.time()
            while pending and (time.time() - start) < timeout:
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(resp)
                    if "id" in data and data["id"] in pending:
                        pending.discard(data["id"])
                        results[data["id"]] = data.get("result", data.get("error", {}))
                except asyncio.TimeoutError:
                    continue
        return results
    except ConnectionRefusedError:
        print(f'Browser is not running. Run \'cdpilot launch\' first.', file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        err = str(e)
        if "websocket" in err.lower() or "connect" in err.lower() or "ws://" in err.lower():
            print(f'Browser is not running or CDP port {CDP_PORT} is unreachable. Run \'cdpilot launch\' first.', file=sys.stderr)
            sys.exit(1)
        raise


async def navigate_collect(ws_url, url, network=False, console=False, glow=True):
    """Navigate to a page and optionally collect network/console events."""
    import websockets
    events = {"network": [], "console": []}

    async with websockets.connect(ws_url, max_size=100 * 1024 * 1024) as ws:
        # Enable CDP domains
        sid = 1
        for domain in ["Page", "Network", "Runtime", "Log"]:
            await ws.send(json.dumps({"id": sid, "method": f"{domain}.enable", "params": {}}))
            sid += 1

        # Navigate
        await ws.send(json.dumps({"id": 100, "method": "Page.navigate", "params": {"url": url}}))

        # Collect events until page load
        loaded = False
        start = time.time()
        while time.time() - start < 20:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(resp)
                method = data.get("method", "")

                if network and method == "Network.responseReceived":
                    r = data["params"]["response"]
                    events["network"].append({
                        "url": r.get("url", "")[:150],
                        "status": r.get("status"),
                        "type": data["params"].get("type", ""),
                        "mime": r.get("mimeType", ""),
                    })

                if console and method == "Runtime.consoleAPICalled":
                    args = data["params"].get("args", [])
                    text = " ".join(str(a.get("value", a.get("description", ""))) for a in args)
                    events["console"].append({
                        "type": data["params"].get("type", "log"),
                        "text": text[:300],
                    })

                if console and method == "Log.entryAdded":
                    entry = data["params"]["entry"]
                    events["console"].append({
                        "type": entry.get("level", "log"),
                        "text": entry.get("text", "")[:300],
                    })

                if method == "Page.loadEventFired":
                    loaded = True
                    await asyncio.sleep(1.5)
                    break
            except asyncio.TimeoutError:
                if loaded:
                    break

        # Inject visual indicator (sets data-cdpilot-active attribute)
        if glow:
            await ws.send(json.dumps({
                "id": 200, "method": "Runtime.evaluate",
                "params": {"expression": GLOW_ACTIVATE_JS, "returnByValue": True}
            }))

        # Inject dev extension content scripts via the existing WS connection
        ext_scripts = _get_dev_extension_scripts(url)
        ext_injected = []
        for ext_name, filename, code, _ in ext_scripts:
            try:
                sid += 1
                await ws.send(json.dumps({
                    "id": sid, "method": "Runtime.evaluate",
                    "params": {"expression": code, "returnByValue": True}
                }))
                ext_injected.append(f"{ext_name}/{filename}")
            except Exception:
                pass
        if ext_injected:
            # Wait for injection responses
            for _ in ext_injected:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=3)
                except Exception:
                    pass
            print(f"  Dev extension injected: {', '.join(ext_injected)}")

        # Get DOM text content
        await ws.send(json.dumps({
            "id": 201, "method": "Runtime.evaluate",
            "params": {
                "expression": "document.body.innerText.substring(0, 10000)",
                "returnByValue": True,
            }
        }))

        content = ""
        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(resp)
                m = data.get("method", "")
                if network and m == "Network.responseReceived":
                    r = data["params"]["response"]
                    events["network"].append({
                        "url": r.get("url", "")[:150],
                        "status": r.get("status"),
                        "type": data["params"].get("type", ""),
                    })
                if data.get("id") == 201:
                    content = data.get("result", {}).get("result", {}).get("value", "")
                    break
            except asyncio.TimeoutError:
                break

    return content, events

# ─── Helper Functions ───

def _find_browser():
    """İşletim sistemine göre tarayıcı ikili dosyasını otomatik olarak bulur."""
    for b in ["brave-browser", "google-chrome", "chromium-browser", "chromium"]:
        found = shutil.which(b)
        if found:
            return found

    system = platform.system()
    if system == "Darwin":
        paths = [
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Linux":
        paths = [
            "/usr/bin/brave-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
    elif system == "Windows":
        paths = [
            os.path.expandvars(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.expandvars(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"C:\Program Files\Chromium\Application\chromium.exe"),
        ]
    else:
        return None

    for path in paths:
        if os.path.exists(path):
            return path
    return None


def _is_port_in_use(port):
    """Bir portun aktif olarak dinlenip dinlenmediğini kontrol eder."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def get_dev_extensions():
    """Read registered dev mode extension paths."""
    if os.path.exists(DEV_EXTENSIONS_FILE):
        try:
            with open(DEV_EXTENSIONS_FILE) as f:
                return json.load(f)
        except:
            pass
    return []

def save_dev_extensions(extensions):
    """Save dev mode extension paths."""
    os.makedirs(os.path.dirname(DEV_EXTENSIONS_FILE), exist_ok=True)
    with open(DEV_EXTENSIONS_FILE, 'w') as f:
        json.dump(extensions, f, indent=2)


def _match_url_pattern(pattern, url):
    """Test a Chrome extension match pattern against a URL.

    Supported pattern formats:
      *://*.google.com/*
      https://example.com/path/*
      <all_urls>
    """
    if pattern == '<all_urls>':
        return url.startswith('http://') or url.startswith('https://')

    import re
    # Pattern: scheme://host/path
    m = re.match(r'^(\*|https?|ftp)://((?:\*\.)?[^/]*)(/.*)$', pattern)
    if not m:
        return False
    p_scheme, p_host, p_path = m.groups()

    # Parse URL
    from urllib.parse import urlparse
    parsed = urlparse(url)
    u_scheme = parsed.scheme
    u_host = parsed.hostname or ''
    u_path = parsed.path or '/'
    if not u_path:
        u_path = '/'
    if parsed.query:
        u_path += '?' + parsed.query

    # Scheme check
    if p_scheme != '*' and p_scheme != u_scheme:
        return False

    # Host check
    if p_host == '*':
        pass  # any host
    elif p_host.startswith('*.'):
        suffix = p_host[2:]
        if u_host != suffix and not u_host.endswith('.' + suffix):
            return False
    else:
        if u_host != p_host:
            return False

    # Path check — convert glob to regex
    path_re = re.escape(p_path).replace(r'\*', '.*')
    if not re.fullmatch(path_re, u_path):
        return False

    return True


def _get_dev_extension_scripts(page_url):
    """Collect content_scripts from dev extensions matching the current page URL.

    Returns: list of (ext_name, filename, code, type) tuples
    type: 'js' or 'css'
    """
    dev_exts = get_dev_extensions()
    if not dev_exts:
        return []

    scripts = []
    for ext_path in dev_exts:
        manifest_path = os.path.join(ext_path, 'manifest.json')
        if not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except Exception:
            continue

        ext_name = manifest.get('name', os.path.basename(ext_path))

        for cs in manifest.get('content_scripts', []):
            matches = cs.get('matches', [])
            matched = any(_match_url_pattern(pat, page_url) for pat in matches)
            if not matched:
                continue

            for js_file in cs.get('js', []):
                js_path = os.path.join(ext_path, js_file)
                if not os.path.exists(js_path):
                    continue
                try:
                    with open(js_path) as f:
                        scripts.append((ext_name, js_file, f.read(), 'js'))
                except Exception:
                    pass

            for css_file in cs.get('css', []):
                css_path = os.path.join(ext_path, css_file)
                if not os.path.exists(css_path):
                    continue
                try:
                    with open(css_path) as f:
                        css_code = f.read()
                    css_escaped = json.dumps(css_code)
                    inject_css = f"""(function() {{
                        const style = document.createElement('style');
                        style.textContent = {css_escaped};
                        document.head.appendChild(style);
                    }})()"""
                    scripts.append((ext_name, css_file, inject_css, 'css'))
                except Exception:
                    pass

    return scripts


async def inject_dev_extension_scripts(ws_url, page_url):
    """Inject dev extension content_scripts via CDP (separate connection).

    For use outside navigate_collect (e.g. after cmd_eval).
    """
    scripts = _get_dev_extension_scripts(page_url)
    if not scripts:
        return

    injected = []
    for ext_name, filename, code, _ in scripts:
        try:
            await cdp_send(ws_url, [(
                500, "Runtime.evaluate", {
                    "expression": code,
                    "returnByValue": True,
                }
            )])
            injected.append(f"{ext_name}/{filename}")
        except Exception:
            pass

    if injected:
        print(f"  Dev extension scripts injected: {', '.join(injected)}")


def get_proxy_config():
    """Read proxy configuration."""
    proxy = os.environ.get('CHROME_PROXY', '')
    if proxy:
        return proxy
    if os.path.exists(PROXY_CONFIG_FILE):
        try:
            with open(PROXY_CONFIG_FILE) as f:
                data = json.load(f)
            return data.get('proxy', '')
        except:
            pass
    return ''

def get_headless_config():
    """Return whether headless mode is active."""
    env = os.environ.get('CHROME_HEADLESS', '')
    if env:
        return env.lower() in ('1', 'true', 'yes')
    if os.path.exists(HEADLESS_CONFIG_FILE):
        try:
            with open(HEADLESS_CONFIG_FILE) as f:
                return json.load(f).get('headless', False)
        except:
            pass
    return False

# ─── Commands ───

def cmd_launch():
    """Launch the browser with CDP enabled (isolated session — does not touch existing browser)."""
    global CHROME_BIN
    if cdp_get('/json/version'):
        print(f'Browser already running on port {CDP_PORT}.')
        return
    if _is_port_in_use(CDP_PORT):
        print(f'Error: Port {CDP_PORT} is in use by another process. Set CDP_PORT to a different port.', file=sys.stderr)
        sys.exit(1)

    if not CHROME_BIN:
        bin_path = _find_browser()
        if not bin_path:
            print('No supported browser found. Install Brave, Chrome, or Chromium and ensure it is in PATH or set CHROME_BIN.', file=sys.stderr)
            sys.exit(1)
        CHROME_BIN = bin_path
        print(f'Browser found: {bin_path}')

    os.makedirs(PROFILE_DIR, exist_ok=True)

    print(f'Launching browser (isolated session, port {CDP_PORT})...')

    chrome_args = [
        CHROME_BIN,
        f'--remote-debugging-port={CDP_PORT}',
        f'--user-data-dir={PROFILE_DIR}',
        '--remote-allow-origins=*',
        '--disable-fre', '--no-default-browser-check', '--no-first-run',
        # ─── Brave-specific features (harmless on other Chromium builds) ───
        '--disable-brave-rewards',
        '--disable-brave-wallet',
        '--disable-brave-shields',
        '--disable-brave-news',
        '--disable-brave-vpn',
        '--disable-brave-wayback-machine',
        '--disable-ai-chat',
        '--disable-speedreader',
        '--disable-tor',
        '--disable-ipfs',
        '--disable-brave-extension',
        # ─── Chromium performance flags ───
        '--disable-background-networking',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-breakpad',
        '--disable-client-side-phishing-detection',
        '--disable-component-update',
        '--disable-default-apps',
        '--disable-domain-reliability',
        '--disable-hang-monitor',
        '--disable-ipc-flooding-protection',
        '--disable-popup-blocking',
        '--disable-prompt-on-repost',
        '--disable-renderer-backgrounding',
        '--disable-sync',
        '--disable-translate',
        '--metrics-recording-only',
        '--no-pings',
        '--safebrowsing-disable-auto-update',
        '--password-store=basic',
        # ─── GPU / rendering ───
        '--disable-gpu-compositing',
        '--disable-smooth-scrolling',
        '--new-window', 'about:blank',
    ]

    # Dev extensions
    dev_exts = get_dev_extensions()
    valid_exts = [p for p in dev_exts if os.path.isdir(p)]
    if valid_exts:
        ext_list = ','.join(valid_exts)
        chrome_args.append(f"--load-extension={ext_list}")
        print(f'  Dev extensions: {len(valid_exts)}')

    # Proxy
    proxy = get_proxy_config()
    if proxy:
        chrome_args.append(f'--proxy-server={proxy}')
        print(f'  Proxy: {proxy}')

    # Headless
    if get_headless_config():
        chrome_args.append('--headless=new')
        print('  Mode: headless')

    subprocess.Popen(chrome_args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    for _ in range(20):
        time.sleep(0.5)
        if cdp_get('/json/version'):
            print(f'CDP ready! (port {CDP_PORT})')
            return
    print('Failed to start CDP (timeout).', file=sys.stderr)
    sys.exit(1)


def cmd_tabs():
    tabs = get_tabs()
    pages = [t for t in tabs if t.get("type") == "page"]
    for i, p in enumerate(pages):
        url = p.get("url", "")
        icon = "🔵" if url.startswith("chrome://") else "🟢"
        print(f"  {icon} [{i}] {p.get('title', '')[:70]}")
        print(f"       {url[:120]}")
    print(f"\n{len(pages)} pages, {len(tabs)} targets")


async def cmd_go(url):
    if not cdp_get("/json/version"):
        cmd_launch()

    ws, page = get_page_ws()
    content, _ = await navigate_collect(ws, url)
    print(content)


async def cmd_content():
    ws, _ = get_page_ws()
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {
        "expression": "document.body.innerText.substring(0, 1048576)",
        "returnByValue": True,
    })])
    content = r.get(1, {}).get("result", {}).get("value", "(empty)")
    print(content)
    if len(content) >= 1048576:
        print("[Output truncated at 1MB]")


async def cmd_html():
    ws, _ = get_page_ws()
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {
        "expression": "document.documentElement.outerHTML.substring(0, 1048576)",
        "returnByValue": True,
    })])
    html_content = r.get(1, {}).get("result", {}).get("value", "(empty)")
    print(html_content)
    if len(html_content) >= 1048576:
        print("[Output truncated at 1MB]")


async def cmd_shot(output=None):
    if not output:
        output = f"{SCREENSHOT_DIR}/screenshot.png"
    ws, _ = get_page_ws()
    r = await cdp_send(ws, [(1, "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})])
    b64 = r.get(1, {}).get("data", "")
    if b64:
        with open(output, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"{output}")
    else:
        print("Screenshot failed", file=sys.stderr)


async def cmd_eval(js_code):
    ws, _ = get_page_ws()
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {
        "expression": js_code,
        "returnByValue": True,
        "awaitPromise": True,
    })])
    result = r.get(1, {})
    if "exceptionDetails" in result:
        exc = result["exceptionDetails"]
        print(f"Error: {exc.get('text', '')} — {exc.get('exception', {}).get('description', '')}")
    else:
        val = result.get("result", {})
        if val.get("type") == "undefined":
            print("(undefined)")
        elif val.get("value") is not None:
            v = val["value"]
            print(json.dumps(v, indent=2, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v))
        else:
            print(json.dumps(val, indent=2, ensure_ascii=False))


async def cmd_click(selector):
    ws, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    js = f"""(function() {{
        const el = document.querySelector({safe_sel});
        if (!el) return 'Not found: ' + {safe_sel};
        el.scrollIntoView({{behavior:'smooth', block:'center'}});
        el.click();
        return 'Clicked: ' + el.tagName + ' ' + (el.textContent || '').substring(0, 60).trim();
    }})()"""
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    print(r.get(1, {}).get("result", {}).get("value", "?"))


async def cmd_fill(selector, value):
    """Fill an input field (React/Vue compatible)."""
    ws, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    safe_value = json.dumps(value)
    js = f"""(function() {{
        const el = document.querySelector({safe_sel});
        if (!el) return 'Not found: ' + {safe_sel};
        el.focus();
        const nativeSet = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
        ).set;
        nativeSet.call(el, {safe_value});
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return 'Filled: ' + el.tagName + ' = ' + el.value.substring(0, 50);
    }})()"""
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    print(r.get(1, {}).get("result", {}).get("value", "?"))


async def cmd_submit(selector="form"):
    ws, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    js = f"""(function() {{
        const form = document.querySelector({safe_sel});
        if (!form) return 'Form not found: ' + {safe_sel};
        const btn = form.querySelector('button[type=submit], input[type=submit], button:last-of-type');
        if (btn) {{ btn.click(); return 'Submit clicked: ' + btn.textContent.trim(); }}
        form.submit();
        return 'Form submitted';
    }})()"""
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    print(r.get(1, {}).get("result", {}).get("value", "?"))


async def cmd_wait(selector, timeout=5):
    ws, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    js = f"""new Promise((resolve) => {{
        const el = document.querySelector({safe_sel});
        if (el) return resolve('Found: ' + el.tagName + ' ' + (el.textContent||'').substring(0,60).trim());
        const obs = new MutationObserver(() => {{
            const el = document.querySelector({safe_sel});
            if (el) {{ obs.disconnect(); resolve('Found: ' + el.tagName + ' ' + (el.textContent||'').substring(0,60).trim()); }}
        }});
        obs.observe(document.body, {{childList:true, subtree:true}});
        setTimeout(() => {{ obs.disconnect(); resolve('Timeout: ' + {safe_sel} + ' not found ({timeout}s)'); }}, {int(timeout)*1000});
    }})"""
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})])
    print(r.get(1, {}).get("result", {}).get("value", "?"))


async def cmd_network(url=None):
    ws, page = get_page_ws()
    if url is None:
        url = page.get("url", "")
    content, events = await navigate_collect(ws, url, network=True)
    print("=== Network Requests ===")
    for req in events["network"]:
        s = req.get("status", "?")
        m = "✓" if str(s).startswith("2") else "✗" if str(s).startswith(("4", "5")) else "→"
        print(f"  {m} [{s}] {req.get('type',''):>10} {req['url']}")
    print(f"\nTotal: {len(events['network'])} requests")
    print(f"\n=== Content (first 3000 chars) ===\n{content[:3000]}")


async def cmd_console(url=None):
    ws, page = get_page_ws()
    if url is None:
        url = page.get("url", "")
    content, events = await navigate_collect(ws, url, console=True)
    print("=== Console ===")
    icons = {"log": "📝", "error": "❌", "warning": "⚠️", "info": "ℹ️"}
    for log in events["console"]:
        lvl = log.get("type", "log")
        print(f"  {icons.get(lvl, '📝')} [{lvl.upper()}] {log['text']}")
    if not events["console"]:
        print("  (empty)")
    print(f"\n=== Content (first 3000 chars) ===\n{content[:3000]}")


async def cmd_cookies(domain=None):
    ws, _ = get_page_ws()
    params = {}
    if domain:
        params["urls"] = [f"https://{domain}", f"http://{domain}"]
    r = await cdp_send(ws, [(1, "Network.getCookies", params)])
    cookies = r.get(1, {}).get("cookies", [])
    for c in cookies:
        sec = "🔒" if c.get("secure") else "  "
        print(f"  {sec} {c['name'][:35]:35} = {str(c.get('value',''))[:50]:50} ({c.get('domain','')})")
    print(f"\n{len(cookies)} cookies")


async def cmd_storage():
    ws, _ = get_page_ws()
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {
        "expression": "JSON.stringify(Object.fromEntries(Object.entries(localStorage).map(([k,v])=>[k,v.substring(0,200)])))",
        "returnByValue": True,
    })])
    val = r.get(1, {}).get("result", {}).get("value", "{}")
    try:
        data = json.loads(val)
        for k, v in data.items():
            print(f"  {k}: {v[:120]}")
        print(f"\n{len(data)} entries")
    except:
        print(val)


async def cmd_perf():
    ws, _ = get_page_ws()
    r = await cdp_send(ws, [
        (1, "Performance.enable", {}),
        (2, "Performance.getMetrics", {}),
    ])
    metrics = r.get(2, {}).get("metrics", [])
    important = {
        "Nodes": "DOM Nodes", "Documents": "Documents",
        "JSEventListeners": "Event Listeners", "LayoutCount": "Layout Count",
        "RecalcStyleCount": "Style Recalc", "JSHeapUsedSize": "JS Heap (Used)",
        "JSHeapTotalSize": "JS Heap (Total)", "FirstMeaningfulPaint": "First Meaningful Paint",
        "DomContentLoaded": "DomContentLoaded",
    }
    print("=== Performance ===")
    for m in metrics:
        if m["name"] in important:
            val = m["value"]
            if "Size" in m["name"]:
                val = f"{val / 1024 / 1024:.1f} MB"
            elif "Paint" in m["name"] or "Loaded" in m["name"]:
                val = f"{val:.3f}s"
            else:
                val = f"{int(val)}"
            print(f"  {important[m['name']]:25} {val}")


async def cmd_emulate(device):
    devices = {
        "iphone": (390, 844, 3, "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"),
        "ipad": (820, 1180, 2, "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)"),
        "android": (412, 915, 2.625, "Mozilla/5.0 (Linux; Android 14)"),
    }
    ws, _ = get_page_ws()
    if device == "reset" or device not in devices:
        await cdp_send(ws, [
            (1, "Emulation.clearDeviceMetricsOverride", {}),
            (2, "Network.setUserAgentOverride", {"userAgent": ""}),
        ])
        print("Emulation reset (desktop)")
        return

    w, h, s, ua = devices[device]
    await cdp_send(ws, [
        (1, "Emulation.setDeviceMetricsOverride", {
            "width": w, "height": h, "deviceScaleFactor": s, "mobile": True
        }),
        (2, "Network.setUserAgentOverride", {"userAgent": ua}),
    ])
    print(f"Emulating: {device} ({w}x{h})")


async def cmd_glow(state="on"):
    ws, page = get_page_ws()
    js = GLOW_ACTIVATE_JS if state == "on" else GLOW_DEACTIVATE_JS
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    print(f"Visual indicator {'on' if state == 'on' else 'off'}")


async def cmd_debug(url=None):
    """Full auto-debug: navigate + console + network + perf + screenshot."""
    if not cdp_get("/json/version"):
        cmd_launch()

    ws, page = get_page_ws()

    if url is None:
        url = page.get("url", "")

    print(f"🔍 Debug: {url}")
    print("=" * 60)

    content, events = await navigate_collect(ws, url, network=True, console=True, glow=True)

    print("\n📋 CONSOLE LOGS")
    print("-" * 40)
    errors = [l for l in events["console"] if l["type"] in ("error", "warning")]
    all_logs = events["console"]
    if errors:
        for log in errors:
            icon = "❌" if log["type"] == "error" else "⚠️"
            print(f"  {icon} {log['text']}")
    elif all_logs:
        for log in all_logs[:10]:
            print(f"  📝 {log['text']}")
    else:
        print("  ✅ Clean (no errors)")

    print(f"\n🌐 NETWORK ({len(events['network'])} requests)")
    print("-" * 40)
    failed = [r for r in events["network"] if str(r.get("status", "")).startswith(("4", "5"))]
    if failed:
        for req in failed:
            print(f"  ❌ [{req['status']}] {req['url']}")
    else:
        print("  ✅ All requests successful")
    slow = [r for r in events["network"] if r.get("type") in ("XHR", "Fetch", "Document")]
    if slow:
        print(f"  📊 API/Document requests: {len(slow)}")
        for r in slow[:5]:
            print(f"     [{r.get('status','?')}] {r.get('type','')} {r['url'][:100]}")

    print("\n⚡ PERFORMANCE")
    print("-" * 40)
    try:
        r = await cdp_send(ws, [
            (1, "Performance.enable", {}),
            (2, "Performance.getMetrics", {}),
        ])
        metrics = {m["name"]: m["value"] for m in r.get(2, {}).get("metrics", [])}
        heap = metrics.get("JSHeapUsedSize", 0) / 1024 / 1024
        nodes = int(metrics.get("Nodes", 0))
        listeners = int(metrics.get("JSEventListeners", 0))
        print(f"  JS Heap: {heap:.1f} MB")
        print(f"  DOM Nodes: {nodes}")
        print(f"  Event Listeners: {listeners}")
        if heap > 50:
            print(f"  ⚠️ High memory usage ({heap:.0f} MB)")
        if nodes > 3000:
            print(f"  ⚠️ High DOM node count ({nodes})")
    except:
        print("  (metrics unavailable)")

    print("\n📸 SCREENSHOT")
    print("-" * 40)
    shot_path = f"{SCREENSHOT_DIR}/debug-{int(time.time())}.png"
    try:
        r = await cdp_send(ws, [(10, "Page.captureScreenshot", {"format": "png"})])
        b64 = r.get(10, {}).get("data", "")
        if b64:
            with open(shot_path, "wb") as f:
                f.write(base64.b64decode(b64))
            print(f"  {shot_path}")
    except:
        print("  (unavailable)")

    print(f"\n📄 PAGE CONTENT (first 2000 chars)")
    print("-" * 40)
    print(content[:2000])

    print(f"\n{'=' * 60}")
    print(f"Debug complete: {url}")


async def cmd_close():
    ws, page = get_page_ws()
    r = await cdp_send(ws, [(1, "Page.close", {})])
    print("Tab closed")


def cmd_session():
    """Show current session info."""
    sid = _get_session_id()
    sessions = _load_sessions()
    info = sessions.get(sid)
    if info:
        print(f"Session: {sid}")
        print(f"  Target ID: {info.get('target_id', '?')}")
        print(f"  Created: {info.get('created', '?')}")
        # Check if target is still active
        tabs = cdp_get("/json") or []
        active = any(t.get("id") == info.get("target_id") for t in tabs)
        print(f"  Status: {'active' if active else 'gone (will be recreated)'}")
    else:
        print(f"Session: {sid}")
        print("  No window assigned yet (will be created on first command)")


def cmd_sessions():
    """List all active sessions."""
    sessions = _cleanup_stale_sessions()
    if not sessions:
        print("No active sessions.")
        return
    tabs = cdp_get("/json") or []
    active_ids = {t.get("id") for t in tabs}
    current_sid = _get_session_id()
    print(f"{'Session ID':<30} {'Target ID':<40} {'Status':<8} {'Created'}")
    print("─" * 100)
    for sid, info in sessions.items():
        tid = info.get("target_id", "?")
        created = info.get("created", "?")
        active = "active" if tid in active_ids else "gone"
        marker = " ← (current)" if sid == current_sid else ""
        print(f"{sid:<30} {tid:<40} {active:<8} {created}{marker}")
    print(f"\nTotal: {len(sessions)} sessions")


def cmd_session_close(session_id=None):
    """Close a specific session window and remove its registry entry."""
    sid = session_id or _get_session_id()
    sessions = _load_sessions()
    info = sessions.get(sid)
    if not info:
        print(f"Session not found: {sid}")
        return

    target_id = info.get("target_id")
    if target_id:
        # Close the tab
        tabs = cdp_get("/json") or []
        for t in tabs:
            if t.get("id") == target_id and "webSocketDebuggerUrl" in t:
                try:
                    import websockets
                    async def _close():
                        async with websockets.connect(
                            t["webSocketDebuggerUrl"],
                            max_size=10*1024*1024
                        ) as ws:
                            await ws.send(json.dumps({
                                "id": 1, "method": "Page.close", "params": {}
                            }))
                            try:
                                await asyncio.wait_for(ws.recv(), timeout=2)
                            except:
                                pass
                    asyncio.run(_close())
                except:
                    pass
                break

    sessions.pop(sid, None)
    _save_sessions(sessions)
    print(f"Session closed: {sid}")


def cmd_extensions():
    """List installed extensions."""
    ext_dir = os.path.join(PROFILE_DIR, "Default", "Extensions")
    if not os.path.isdir(ext_dir):
        print("No extensions installed.")
        return

    prefs_path = os.path.join(PROFILE_DIR, "Default", "Preferences")
    ext_names = {}
    if os.path.exists(prefs_path):
        try:
            with open(prefs_path) as f:
                prefs = json.load(f)
            settings = prefs.get("extensions", {}).get("settings", {})
            for ext_id, info in settings.items():
                manifest = info.get("manifest", {})
                ext_names[ext_id] = {
                    "name": manifest.get("name", ext_id),
                    "version": manifest.get("version", "?"),
                    "enabled": info.get("state", 1) == 1,
                    "path": info.get("path", ""),
                }
        except Exception:
            pass

    ext_ids = [d for d in os.listdir(ext_dir) if not d.startswith(".")]
    if not ext_ids:
        print("No extensions installed.")
        return

    for ext_id in sorted(ext_ids):
        info = ext_names.get(ext_id, {})
        name = info.get("name", ext_id)
        version = info.get("version", "?")
        enabled = info.get("enabled", True)
        status = "✅" if enabled else "⏸️"
        print(f"  {status} {name} (v{version})")
        print(f"     ID: {ext_id}")

    print(f"\n{len(ext_ids)} extensions")

    dev_exts = get_dev_extensions()
    if dev_exts:
        print(f'\nDev Mode Extensions ({len(dev_exts)}):')
        for i, path in enumerate(dev_exts):
            exists = '✅' if os.path.isdir(path) else '❌ (directory not found)'
            print(f'  {exists} [{i}] {path}')


def cmd_ext_install(source):
    """Install an extension from a CRX file or unpacked directory.

    Usage:
      ext-install /path/to/extension.crx
      ext-install /path/to/unpacked-extension-dir/
    """
    ext_dir = os.path.join(PROFILE_DIR, "Default", "Extensions")
    os.makedirs(ext_dir, exist_ok=True)

    source = os.path.expanduser(source)

    if os.path.isdir(source):
        manifest_path = os.path.join(source, 'manifest.json')
        if not os.path.exists(manifest_path):
            print(f'Error: {source}/manifest.json not found.', file=sys.stderr)
            sys.exit(1)

        with open(manifest_path) as f:
            manifest = json.load(f)

        name = manifest.get('name', os.path.basename(source))
        version = manifest.get('version', '1.0')
        abs_source = os.path.abspath(source)

        # Add to dev extensions list
        exts = get_dev_extensions()
        if abs_source not in exts:
            exts.append(abs_source)
            save_dev_extensions(exts)

        print(f'✅ Dev extension registered: {name} (v{version})')
        print(f'   Path: {abs_source}')
        print('   Restarting browser...')
        cmd_stop()
        import time as _time
        _time.sleep(1)
        cmd_launch()

    elif source.endswith(".crx"):
        if not os.path.exists(source):
            print(f"Error: {source} not found.", file=sys.stderr)
            sys.exit(1)

        import hashlib
        ext_id = hashlib.md5(os.path.basename(source).encode()).hexdigest()[:32]
        dest_dir = os.path.join(ext_dir, ext_id)
        os.makedirs(dest_dir, exist_ok=True)

        dest = os.path.join(dest_dir, os.path.basename(source))
        shutil.copy2(source, dest)

        print(f"✅ CRX copied: {os.path.basename(source)}")
        print(f"   ID: {ext_id}")
        print("   Note: Restart browser and load via chrome://extensions.")
        print("   Alternative: use an unpacked directory for direct loading.")

    else:
        print("Error: provide a .crx file or unpacked extension directory.", file=sys.stderr)
        print("Usage:")
        print("  ext-install /path/to/extension.crx")
        print("  ext-install /path/to/unpacked-extension-dir/")
        sys.exit(1)


def cmd_ext_remove(ext_id):
    """Remove an extension by ID."""
    # Check dev extensions list first
    dev_exts = get_dev_extensions()
    # ext_id may be a directory path or a list index
    try:
        idx = int(ext_id)
        if 0 <= idx < len(dev_exts):
            removed_path = dev_exts.pop(idx)
            save_dev_extensions(dev_exts)
            print(f'🗑️ Dev extension removed from list: {removed_path}')
            print('   Restart the browser (stop → launch).')
            return
    except ValueError:
        # Try matching by path
        if ext_id in dev_exts:
            dev_exts.remove(ext_id)
            save_dev_extensions(dev_exts)
            print(f'🗑️ Dev extension removed from list: {ext_id}')
            print('   Restart the browser (stop → launch).')
            return

    ext_dir = os.path.join(PROFILE_DIR, "Default", "Extensions", ext_id)
    if not os.path.isdir(ext_dir):
        print(f"Extension not found: {ext_id}", file=sys.stderr)
        sys.exit(1)

    name = ext_id
    prefs_path = os.path.join(PROFILE_DIR, "Default", "Preferences")
    if os.path.exists(prefs_path):
        try:
            with open(prefs_path) as f:
                prefs = json.load(f)
            info = prefs.get("extensions", {}).get("settings", {}).get(ext_id, {})
            name = info.get("manifest", {}).get("name", ext_id)
        except Exception:
            pass

    shutil.rmtree(ext_dir)
    print(f"🗑️ Extension removed: {name}")
    print("   Note: Restart the browser (stop → launch).")

async def cmd_new_tab(url='about:blank'):
    """Open a new tab."""
    import urllib.parse
    data = cdp_get(f'/json/new?{urllib.parse.quote(url, safe=":/?#[]@!$&\'()*+,;=")}')
    if data:
        print(f'New tab opened: {data.get("url", url)}')
        print(f'  ID: {data.get("id", "?")}')
    else:
        print('Failed to open tab', file=sys.stderr)

def cmd_switch_tab(index_or_id):
    """Switch to a tab by index number or tab ID."""
    tabs = get_tabs()
    pages = [t for t in tabs if t.get('type') == 'page']

    target = None
    try:
        idx = int(index_or_id)
        if 0 <= idx < len(pages):
            target = pages[idx]
    except ValueError:
        for p in pages:
            if p.get('id') == index_or_id:
                target = p
                break

    if target:
        activate_tab(target['id'])
        print(f'Switched to tab: {target.get("title", "")[:60]}')
        print(f'  URL: {target.get("url", "")[:120]}')
    else:
        print(f'Tab not found: {index_or_id}', file=sys.stderr)
        print('Available tabs:')
        cmd_tabs()

async def cmd_close_tab(index_or_id=None):
    """Close a specific tab by index or ID (active tab if omitted)."""
    if index_or_id is None:
        ws, page = get_page_ws()
        r = await cdp_send(ws, [(1, 'Page.close', {})])
        print('Active tab closed')
        return

    tabs = get_tabs()
    pages = [t for t in tabs if t.get('type') == 'page']

    target = None
    try:
        idx = int(index_or_id)
        if 0 <= idx < len(pages):
            target = pages[idx]
    except ValueError:
        for p in pages:
            if p.get('id') == index_or_id:
                target = p
                break

    if target:
        import websockets
        async with websockets.connect(target['webSocketDebuggerUrl'], max_size=100*1024*1024) as ws:
            await ws.send(json.dumps({'id': 1, 'method': 'Page.close', 'params': {}}))
            try:
                await asyncio.wait_for(ws.recv(), timeout=3)
            except:
                pass
        print(f'Tab closed: {target.get("title", "")[:60]}')
    else:
        print(f'Tab not found: {index_or_id}', file=sys.stderr)

async def cmd_pdf(output=None):
    """Save the current page as a PDF."""
    if not output:
        output = f'{SCREENSHOT_DIR}/page-{int(time.time())}.pdf'
    ws, _ = get_page_ws()
    r = await cdp_send(ws, [(1, 'Page.printToPDF', {
        'printBackground': True,
        'preferCSSPageSize': True,
    })], timeout=30)
    b64 = r.get(1, {}).get('data', '')
    if b64:
        with open(output, 'wb') as f:
            f.write(base64.b64decode(b64))
        print(f'PDF saved: {output}')
    else:
        print('PDF generation failed', file=sys.stderr)

async def cmd_upload(selector, file_path):
    """Upload a file to a file input element."""
    file_path = os.path.expanduser(file_path)
    if not os.path.exists(file_path):
        print(f'File not found: {file_path}', file=sys.stderr)
        sys.exit(1)

    abs_path = os.path.abspath(file_path)
    ws_url, _ = get_page_ws()

    import websockets
    async with websockets.connect(ws_url, max_size=100*1024*1024) as conn:
        # Enable DOM
        await conn.send(json.dumps({'id': 1, 'method': 'DOM.enable', 'params': {}}))
        await asyncio.wait_for(conn.recv(), timeout=5)

        # Get document root
        await conn.send(json.dumps({'id': 2, 'method': 'DOM.getDocument', 'params': {}}))
        while True:
            resp = await asyncio.wait_for(conn.recv(), timeout=5)
            data = json.loads(resp)
            if data.get('id') == 2:
                break
        root_id = data['result']['root']['nodeId']

        # querySelector
        await conn.send(json.dumps({'id': 3, 'method': 'DOM.querySelector', 'params': {
            'nodeId': root_id, 'selector': selector
        }}))
        while True:
            resp = await asyncio.wait_for(conn.recv(), timeout=5)
            data = json.loads(resp)
            if data.get('id') == 3:
                break

        node_id = data.get('result', {}).get('nodeId', 0)
        if not node_id:
            print(f'Element not found: {selector}', file=sys.stderr)
            return

        # setFileInputFiles
        await conn.send(json.dumps({'id': 4, 'method': 'DOM.setFileInputFiles', 'params': {
            'nodeId': node_id,
            'files': [abs_path]
        }}))
        while True:
            resp = await asyncio.wait_for(conn.recv(), timeout=5)
            data = json.loads(resp)
            if data.get('id') == 4:
                break

        if 'error' in data:
            print(f'Upload error: {data["error"].get("message", "")}', file=sys.stderr)
        else:
            print(f'File uploaded: {os.path.basename(file_path)} → {selector}')

async def cmd_multi_eval(js_code):
    """Execute JavaScript across all open tabs (parallel)."""
    tabs = get_tabs()
    pages = [t for t in tabs if t.get('type') == 'page' and 'chrome://' not in t.get('url', '')]

    if not pages:
        print('No open pages.', file=sys.stderr)
        return

    import websockets

    async def eval_on_tab(tab):
        try:
            async with websockets.connect(tab['webSocketDebuggerUrl'], max_size=100*1024*1024) as ws:
                await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {
                    'expression': js_code, 'returnByValue': True, 'awaitPromise': True
                }}))
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(resp)
                result = data.get('result', {}).get('result', {})
                return tab.get('title', '?')[:40], result.get('value', result.get('description', '?'))
        except Exception as e:
            return tab.get('title', '?')[:40], f'Error: {e}'

    results = await asyncio.gather(*[eval_on_tab(t) for t in pages])

    for title, value in results:
        print(f'  [{title}] → {value}')
    print(f'\nExecuted on {len(results)} tabs')

def cmd_proxy(proxy_url=None):
    """Set, show, or clear the proxy. Empty = clear."""
    if proxy_url is None:
        current = get_proxy_config()
        if current:
            print(f'Active proxy: {current}')
        else:
            print('No proxy configured.')
        return

    os.makedirs(os.path.dirname(PROXY_CONFIG_FILE), exist_ok=True)
    if proxy_url in ('off', ''):
        if os.path.exists(PROXY_CONFIG_FILE):
            os.remove(PROXY_CONFIG_FILE)
        print('Proxy removed. Restart browser (stop → launch).')
    else:
        with open(PROXY_CONFIG_FILE, 'w') as f:
            json.dump({'proxy': proxy_url}, f)
        print(f'Proxy set: {proxy_url}')
        print('Restart browser (stop → launch).')

def cmd_headless(state=None):
    """Enable or disable headless mode."""
    if state is None:
        current = get_headless_config()
        print(f'Headless mode: {"on" if current else "off"}')
        return

    os.makedirs(os.path.dirname(HEADLESS_CONFIG_FILE), exist_ok=True)
    enabled = state.lower() in ('on', '1', 'true', 'yes')
    with open(HEADLESS_CONFIG_FILE, 'w') as f:
        json.dump({'headless': enabled}, f)
    print(f'Headless mode: {"on" if enabled else "off"}')
    print('Restart browser (stop → launch).')


def cmd_stop():
    """Stop the browser instance managed by cdpilot."""
    if platform.system() == "Windows":
        browser_procs = ["brave.exe", "chrome.exe", "chromium.exe"]
        stopped_any = False
        for proc in browser_procs:
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", proc],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    print(f"  {proc} terminated")
                    stopped_any = True
            except Exception:
                pass
        if stopped_any:
            print(f"Browser stopped (port {CDP_PORT}).")
        else:
            print(f"No browser process found (port {CDP_PORT}).", file=sys.stderr)
        return

    import signal
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{CDP_PORT}"],
            capture_output=True, text=True
        )
        pids = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
        if pids:
            for pid in pids:
                os.kill(int(pid), signal.SIGTERM)
                print(f"  PID {pid} terminated")
            print(f"Browser stopped (port {CDP_PORT}).")
        else:
            # lsof bulamazsa pkill ile dene
            subprocess.run(
                ["pkill", "-f", f"remote-debugging-port={CDP_PORT}"],
                capture_output=True, text=True
            )
            print(f"Browser stopped (port {CDP_PORT}).")
    except Exception as e:
        print(f"Stop error: {e}", file=sys.stderr)


def cmd_version():
    """Show cdpilot version."""
    print(f"cdpilot v{__version__}")


# ─── New CDP Commands ───

async def _get_element_center(ws_url, selector):
    """Return the screen center (x, y) of the element matching selector."""
    js = f"""
    (function() {{
        var el = document.querySelector({json.dumps(selector)});
        if (!el) return null;
        var r = el.getBoundingClientRect();
        return {{x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)}};
    }})()
    """
    res = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    val = res.get(1, {}).get("result", {}).get("value")
    if not val:
        print(f"Error: element '{selector}' not found.", file=sys.stderr)
        sys.exit(1)
    return val["x"], val["y"]


async def _get_browser_ws():
    """Return the browser-level WebSocket URL (/json/version)."""
    info = cdp_get("/json/version")
    if not info:
        print("Error: browser not running (CDP /json/version unreachable).", file=sys.stderr)
        sys.exit(1)
    return info.get("webSocketDebuggerUrl")


# ─── 1. Request Interception ───

async def _run_intercept_session(ws_url, duration=30):
    """Intercept requests via Fetch.enable and apply rules."""
    import websockets
    import fnmatch
    global INTERCEPT_RULES

    if not INTERCEPT_RULES:
        print("No interception rules. Use 'intercept block/mock/headers' first.")
        return

    patterns = [{"urlPattern": "*", "requestStage": "Request"}]
    async with websockets.connect(ws_url, max_size=100 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Fetch.enable", "params": {"patterns": patterns}}))
        await asyncio.wait_for(ws.recv(), timeout=5)

        print(f"Intercepting requests ({duration} seconds)...")
        start = time.time()
        cmd_id = 100
        while time.time() - start < duration:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1)
                event = json.loads(raw)
                if event.get("method") != "Fetch.requestPaused":
                    continue
                params = event["params"]
                req_id = params["requestId"]
                req_url = params["request"]["url"]

                handled = False
                for rule_type, pattern, data in INTERCEPT_RULES:
                    if fnmatch.fnmatch(req_url, pattern):
                        cmd_id += 1
                        if rule_type == "block":
                            print(f"  Blocked: {req_url[:80]}")
                            await ws.send(json.dumps({"id": cmd_id, "method": "Fetch.failRequest",
                                "params": {"requestId": req_id, "errorReason": "BlockedByClient"}}))
                        elif rule_type == "mock":
                            try:
                                with open(data, "r", encoding="utf-8") as f:
                                    body = base64.b64encode(f.read().encode()).decode()
                                print(f"  Mocked: {req_url[:80]} → {data}")
                                await ws.send(json.dumps({"id": cmd_id, "method": "Fetch.fulfillRequest",
                                    "params": {"requestId": req_id, "responseCode": 200, "body": body,
                                               "responseHeaders": [{"name": "Content-Type", "value": "application/json"}]}}))
                            except FileNotFoundError:
                                print(f"  Warning: mock file not found: {data}", file=sys.stderr)
                                await ws.send(json.dumps({"id": cmd_id, "method": "Fetch.continueRequest",
                                    "params": {"requestId": req_id}}))
                        elif rule_type == "headers":
                            extra = []
                            for pair in data.split(";"):
                                if ":" in pair:
                                    n, v = pair.split(":", 1)
                                    extra.append({"name": n.strip(), "value": v.strip()})
                            print(f"  Headers added: {req_url[:80]}")
                            await ws.send(json.dumps({"id": cmd_id, "method": "Fetch.continueRequest",
                                "params": {"requestId": req_id, "headers": extra}}))
                        handled = True
                        break

                if not handled:
                    cmd_id += 1
                    await ws.send(json.dumps({"id": cmd_id, "method": "Fetch.continueRequest",
                        "params": {"requestId": req_id}}))

            except asyncio.TimeoutError:
                continue

        await ws.send(json.dumps({"id": 999, "method": "Fetch.disable", "params": {}}))
        print("Request interception complete.")


async def cmd_intercept(subcmd, *subcmd_args):
    """Request interception: block, mock, add headers, clear, list."""
    global INTERCEPT_RULES
    ws_url, _ = get_page_ws()

    if subcmd == "block":
        if not subcmd_args:
            print("Usage: intercept block <url-pattern>")
            sys.exit(1)
        pattern = subcmd_args[0]
        INTERCEPT_RULES.append(("block", pattern, None))
        print(f"Block rule added: {pattern}")
        await _run_intercept_session(ws_url, duration=30)

    elif subcmd == "mock":
        if len(subcmd_args) < 2:
            print("Usage: intercept mock <url-pattern> <json-file>")
            sys.exit(1)
        INTERCEPT_RULES.append(("mock", subcmd_args[0], subcmd_args[1]))
        print(f"Mock rule added: {subcmd_args[0]} → {subcmd_args[1]}")
        await _run_intercept_session(ws_url, duration=30)

    elif subcmd == "headers":
        if len(subcmd_args) < 2:
            print("Usage: intercept headers <url-pattern> <header:value>")
            sys.exit(1)
        INTERCEPT_RULES.append(("headers", subcmd_args[0], subcmd_args[1]))
        print(f"Header rule added: {subcmd_args[0]} → {subcmd_args[1]}")
        await _run_intercept_session(ws_url, duration=30)

    elif subcmd == "clear":
        INTERCEPT_RULES.clear()
        res = await cdp_send(ws_url, [(1, "Fetch.disable", {})])
        print("All interception rules cleared.")

    elif subcmd == "list":
        if not INTERCEPT_RULES:
            print("No active interception rules.")
        else:
            print(f"Active rules ({len(INTERCEPT_RULES)}):")
            for i, (rt, pat, dat) in enumerate(INTERCEPT_RULES, 1):
                extra = f" → {dat}" if dat else ""
                print(f"  {i}. [{rt}] {pat}{extra}")
    else:
        print("Usage: intercept [block|mock|headers|clear|list] ...")
        sys.exit(1)


# ─── 2. Accessibility Tree ───

async def cmd_a11y(subcmd=""):
    """Analyze the accessibility tree."""
    ws_url, _ = get_page_ws()
    res = await cdp_send(ws_url, [(1, "Accessibility.getFullAXTree", {})])
    nodes = res.get(1, {}).get("nodes", [])
    if not nodes:
        print("Could not get accessibility tree. Is the browser running?", file=sys.stderr)
        sys.exit(1)

    visible = [n for n in nodes if not n.get("ignored")]

    def get_prop(node, prop_name):
        for p in node.get("properties", []):
            if p.get("name") == prop_name:
                return p.get("value", {}).get("value", "")
        return ""

    parts = subcmd.strip().split(None, 1)
    sub = parts[0] if parts else ""
    arg = parts[1] if len(parts) > 1 else ""

    if sub == "" or sub == "full":
        print(f"Accessibility tree ({len(visible)} visible nodes):")
        for n in visible:
            role = n.get("role", {}).get("value", "?")
            name = get_prop(n, "name")
            val = get_prop(n, "value")
            desc = get_prop(n, "description")
            out = f"  [{role}]"
            if name:
                out += f" '{name}'"
            if val:
                out += f" value='{val}'"
            if desc:
                out += f" description='{desc}'"
            print(out)

    elif sub == "summary":
        counts = {}
        for n in visible:
            role = n.get("role", {}).get("value", "other")
            counts[role] = counts.get(role, 0) + 1
        interactive = ["button", "link", "textField", "comboBox", "checkbox", "radio", "menuItem"]
        print("Accessibility summary:")
        for role, count in sorted(counts.items(), key=lambda x: -x[1]):
            tag = " ← interactive" if role in interactive else ""
            print(f"  {role}: {count}{tag}")

    elif sub == "find":
        if not arg:
            print("Usage: a11y find <role>")
            sys.exit(1)
        found = [n for n in visible if n.get("role", {}).get("value", "") == arg]
        if not found:
            print(f"No elements with role '{arg}'.")
        else:
            print(f"{len(found)} elements with role '{arg}':")
            for n in found:
                name = get_prop(n, "name")
                print(f"  - '{name or '(unnamed)'}'")
    else:
        print("Usage: a11y [full|summary|find <role>]")
        sys.exit(1)


# ─── 3. Advanced Input Commands ───

async def cmd_hover(selector):
    """Move the mouse cursor to the specified element."""
    ws_url, _ = get_page_ws()
    x, y = await _get_element_center(ws_url, selector)
    await cdp_send(ws_url, [(1, "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": x, "y": y, "button": "none", "modifiers": 0})])
    print(f"Hover: {selector} ({x}, {y})")


async def cmd_dblclick(selector):
    """Double-click the specified element."""
    ws_url, _ = get_page_ws()
    x, y = await _get_element_center(ws_url, selector)
    cmds = [
        (1, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}),
        (2, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}),
        (3, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 2}),
        (4, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 2}),
    ]
    await cdp_send(ws_url, cmds)
    print(f"Double-clicked: {selector}")


async def cmd_rightclick(selector):
    """Right-click the specified element."""
    ws_url, _ = get_page_ws()
    x, y = await _get_element_center(ws_url, selector)
    cmds = [
        (1, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "right", "clickCount": 1}),
        (2, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "right", "clickCount": 1}),
    ]
    await cdp_send(ws_url, cmds)
    print(f"Right-clicked: {selector}")


async def cmd_drag(from_selector, to_selector):
    """Drag an element onto another element."""
    ws_url, _ = get_page_ws()
    fx, fy = await _get_element_center(ws_url, from_selector)
    tx, ty = await _get_element_center(ws_url, to_selector)

    import websockets
    async with websockets.connect(ws_url, max_size=100 * 1024 * 1024) as ws:
        async def send_mouse(cid, etype, x, y, button="left"):
            await ws.send(json.dumps({"id": cid, "method": "Input.dispatchMouseEvent",
                "params": {"type": etype, "x": x, "y": y, "button": button, "modifiers": 0}}))
            await asyncio.wait_for(ws.recv(), timeout=3)

        await send_mouse(1, "mousePressed", fx, fy)
        steps = 5
        for i in range(1, steps + 1):
            ix = int(fx + (tx - fx) * i / steps)
            iy = int(fy + (ty - fy) * i / steps)
            await send_mouse(10 + i, "mouseMoved", ix, iy)
            await asyncio.sleep(0.05)
        await send_mouse(20, "mouseReleased", tx, ty)

    print(f"Dragged: {from_selector} → {to_selector}")


async def cmd_keys(combo):
    """Send a keyboard shortcut (ctrl+a, shift+tab, enter, etc.)."""
    KEY_MAP = {
        "enter": ("Return", 13), "tab": ("Tab", 9), "escape": ("Escape", 27),
        "backspace": ("Backspace", 8), "delete": ("Delete", 46),
        "arrowup": ("ArrowUp", 38), "arrowdown": ("ArrowDown", 40),
        "arrowleft": ("ArrowLeft", 37), "arrowright": ("ArrowRight", 39),
        "home": ("Home", 36), "end": ("End", 35), "pageup": ("PageUp", 33), "pagedown": ("PageDown", 34),
        "f1": ("F1", 112), "f2": ("F2", 113), "f3": ("F3", 114), "f4": ("F4", 115),
        "f5": ("F5", 116), "f6": ("F6", 117), "f11": ("F11", 122), "f12": ("F12", 123),
        "a": ("a", 65), "b": ("b", 66), "c": ("c", 67), "d": ("d", 68), "e": ("e", 69),
        "f": ("f", 70), "g": ("g", 71), "h": ("h", 72), "i": ("i", 73), "j": ("j", 74),
        "k": ("k", 75), "l": ("l", 76), "m": ("m", 77), "n": ("n", 78), "o": ("o", 79),
        "p": ("p", 80), "q": ("q", 81), "r": ("r", 82), "s": ("s", 83), "t": ("t", 84),
        "u": ("u", 85), "v": ("v", 86), "w": ("w", 87), "x": ("x", 88), "y": ("y", 89), "z": ("z", 90),
    }
    MODIFIER_MAP = {"ctrl": 2, "control": 2, "shift": 8, "alt": 1, "meta": 4}

    ws_url, _ = get_page_ws()
    parts = combo.lower().split("+")
    modifiers = 0
    key_name = None
    key_code = 0

    for part in parts:
        if part in MODIFIER_MAP:
            modifiers |= MODIFIER_MAP[part]
        elif part in KEY_MAP:
            key_name, key_code = KEY_MAP[part]
        else:
            print(f"Error: unknown key '{part}'. Supported: {', '.join(list(KEY_MAP.keys())[:20])} ...", file=sys.stderr)
            sys.exit(1)

    if not key_name:
        print("Error: specify a valid key (e.g. ctrl+a, enter, tab).", file=sys.stderr)
        sys.exit(1)

    cmds = [
        (1, "Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": modifiers,
            "key": key_name, "windowsVirtualKeyCode": key_code, "nativeVirtualKeyCode": key_code}),
        (2, "Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": modifiers,
            "key": key_name, "windowsVirtualKeyCode": key_code, "nativeVirtualKeyCode": key_code}),
    ]
    await cdp_send(ws_url, cmds)
    print(f"Key sent: {combo}")


async def cmd_scroll_to(selector):
    """Scroll the specified element into view."""
    ws_url, _ = get_page_ws()
    js = f"(function(){{ var el=document.querySelector({json.dumps(selector)}); if(!el) return false; el.scrollIntoView({{behavior:'smooth',block:'center'}}); return true; }})()"
    res = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    ok = res.get(1, {}).get("result", {}).get("value", False)
    if ok:
        print(f"Scrolled to: {selector}")
    else:
        print(f"Error: element '{selector}' not found.", file=sys.stderr)
        sys.exit(1)


# ─── 4. iframe / Shadow DOM ───

async def cmd_frame(subcmd, *subcmd_args):
    """iframe and Shadow DOM access."""
    ws_url, _ = get_page_ws()

    if subcmd == "list":
        js = """(function(){
            var iframes = document.querySelectorAll('iframe');
            return Array.from(iframes).map(function(f, i){
                return {index: i, src: f.src || '(no source)', name: f.name || '', id: f.id || ''};
            });
        })()"""
        res = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
        frames = res.get(1, {}).get("result", {}).get("value", [])
        if not frames:
            print("No iframes found on page.")
        else:
            print(f"iframes ({len(frames)}):")
            for f in frames:
                print(f"  [{f['index']}] src={f['src'][:80]} name={f['name']} id={f['id']}")

    elif subcmd == "eval":
        if not subcmd_args:
            print("Usage: frame eval <js>")
            sys.exit(1)
        js_code = " ".join(subcmd_args)
        res = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js_code, "returnByValue": True})])
        val = res.get(1, {})
        if "error" in val or val.get("exceptionDetails"):
            print(f"Error: {val}", file=sys.stderr)
        else:
            print(f"Result: {val.get('result', {}).get('value', val)}")

    elif subcmd == "shadow":
        if not subcmd_args:
            print("Usage: frame shadow <selector>")
            sys.exit(1)
        selector = subcmd_args[0]
        js = f"(function(){{ var el=document.querySelector({json.dumps(selector)}); if(!el) return 'Element not found'; if(!el.shadowRoot) return 'No shadow root'; return el.shadowRoot.innerHTML.substring(0,3000); }})()"
        res = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
        val = res.get(1, {}).get("result", {}).get("value", "")
        print(val or "(empty)")

    else:
        print("Usage: frame [list|eval <js>|shadow <selector>]")
        sys.exit(1)


# ─── 5. Dialog Handling ───

async def cmd_dialog(subcmd, *subcmd_args):
    """JavaScript dialog management."""
    global DIALOG_MODE
    ws_url, _ = get_page_ws()

    if subcmd == "auto-accept":
        DIALOG_MODE = "accept"
        print("Dialogs will be automatically accepted.")

    elif subcmd == "auto-dismiss":
        DIALOG_MODE = "dismiss"
        print("Dialogs will be automatically dismissed.")

    elif subcmd == "prompt":
        text = " ".join(subcmd_args) if subcmd_args else ""
        res = await cdp_send(ws_url, [(1, "Page.handleJavaScriptDialog",
            {"accept": True, "promptText": text})])
        print(f"Dialog accepted with text: '{text}'")

    elif subcmd == "off":
        DIALOG_MODE = None
        print("Automatic dialog handling disabled.")

    else:
        print("Usage: dialog [auto-accept|auto-dismiss|prompt <text>|off]")
        sys.exit(1)


# ─── 6. Download ───

async def cmd_download(subcmd, *subcmd_args):
    """Manage download behavior."""
    browser_ws = await _get_browser_ws()

    if subcmd == "set":
        if not subcmd_args:
            print("Usage: download set <directory>")
            sys.exit(1)
        download_dir = os.path.abspath(subcmd_args[0])
        os.makedirs(download_dir, exist_ok=True)
        import websockets
        async with websockets.connect(browser_ws, max_size=100 * 1024 * 1024) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Browser.setDownloadBehavior",
                "params": {"behavior": "allow", "downloadPath": download_dir}}))
            await asyncio.wait_for(ws.recv(), timeout=5)
        cfg = {"downloadPath": download_dir}
        os.makedirs(PROFILE_DIR, exist_ok=True)
        with open(DOWNLOAD_CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
        print(f"Download directory: {download_dir}")

    elif subcmd == "status":
        if os.path.exists(DOWNLOAD_CONFIG_FILE):
            with open(DOWNLOAD_CONFIG_FILE) as f:
                cfg = json.load(f)
            print(f"Download directory: {cfg.get('downloadPath', '(not set)')}")
        else:
            print("Download directory not configured.")

    else:
        print("Usage: download [set <directory>|status]")
        sys.exit(1)


# ─── 7. Network Throttling ───

async def cmd_throttle(preset, *throttle_args):
    """Network throttling simulation."""
    PRESETS = {
        "slow3g":  {"offline": False, "downloadThroughput": 63750, "uploadThroughput": 63750, "latency": 2000},
        "fast3g":  {"offline": False, "downloadThroughput": 192000, "uploadThroughput": 96000, "latency": 563},
        "offline": {"offline": True,  "downloadThroughput": 0, "uploadThroughput": 0, "latency": 0},
        "off":     {"offline": False, "downloadThroughput": -1, "uploadThroughput": -1, "latency": 0},
    }

    ws_url, _ = get_page_ws()

    if preset in PRESETS:
        params = PRESETS[preset]
    elif preset == "custom":
        if len(throttle_args) < 3:
            print("Usage: throttle custom <down_kbps> <up_kbps> <latency_ms>")
            sys.exit(1)
        try:
            down = int(throttle_args[0]) * 1024 // 8
            up = int(throttle_args[1]) * 1024 // 8
            lat = int(throttle_args[2])
        except ValueError:
            print("Error: numeric values required.", file=sys.stderr)
            sys.exit(1)
        params = {"offline": False, "downloadThroughput": down, "uploadThroughput": up, "latency": lat}
    else:
        print(f"Error: unknown preset '{preset}'. Options: slow3g, fast3g, offline, off, custom")
        sys.exit(1)

    await cdp_send(ws_url, [(1, "Network.enable", {})])
    await cdp_send(ws_url, [(1, "Network.emulateNetworkConditions", params)])
    print(f"Network throttle: {preset}")


# ─── 8. Geolocation & Permissions ───

GEO_PRESETS = {
    "istanbul": (41.0082, 28.9784),
    "london":   (51.5074, -0.1278),
    "newyork":  (40.7128, -74.0060),
    "paris":    (48.8566, 2.3522),
    "tokyo":    (35.6762, 139.6503),
}


async def cmd_geo(lat_or_preset, lng=None, accuracy=None):
    """Set or clear geolocation override."""
    ws_url, _ = get_page_ws()

    if lat_or_preset == "off":
        await cdp_send(ws_url, [(1, "Emulation.clearGeolocationOverride", {})])
        print("Geolocation override cleared.")
        return

    if lat_or_preset in GEO_PRESETS:
        lat, lng_val = GEO_PRESETS[lat_or_preset]
        acc = 100.0
        label = lat_or_preset.capitalize()
    else:
        try:
            lat = float(lat_or_preset)
            lng_val = float(lng) if lng else 0.0
            acc = float(accuracy) if accuracy else 100.0
            label = f"({lat}, {lng_val})"
        except (TypeError, ValueError):
            print(f"Error: invalid coordinates or preset. Presets: {', '.join(GEO_PRESETS.keys())}", file=sys.stderr)
            sys.exit(1)

    await cdp_send(ws_url, [(1, "Emulation.setGeolocationOverride",
        {"latitude": lat, "longitude": lng_val, "accuracy": acc})])
    print(f"Location set: {label}")


async def cmd_permission(subcmd, perm=None):
    """Manage browser permissions."""
    browser_ws = await _get_browser_ws()
    ws_url, page_info = get_page_ws()

    import websockets
    async with websockets.connect(browser_ws, max_size=100 * 1024 * 1024) as ws:
        if subcmd == "grant":
            if not perm:
                print("Usage: permission grant <permission>  (geolocation, notifications, camera, microphone, etc.)")
                sys.exit(1)
            origin = page_info.get("url", "").split("?")[0].rstrip("/")
            if not origin.startswith("http"):
                print("Error: a web page must be open to grant permissions.", file=sys.stderr)
                sys.exit(1)
            await ws.send(json.dumps({"id": 1, "method": "Browser.grantPermissions",
                "params": {"permissions": [perm], "origin": origin}}))
            await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"Permission granted: {perm} ({origin})")

        elif subcmd == "deny":
            if not perm:
                print("Usage: permission deny <permission>")
                sys.exit(1)
            await ws.send(json.dumps({"id": 1, "method": "Browser.setPermission",
                "params": {"permission": {"name": perm}, "setting": "denied"}}))
            await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"Permission denied: {perm}")

        elif subcmd == "reset":
            await ws.send(json.dumps({"id": 1, "method": "Browser.resetPermissions", "params": {}}))
            await asyncio.wait_for(ws.recv(), timeout=5)
            print("All permissions reset.")

        else:
            print("Usage: permission [grant <permission>|deny <permission>|reset]")
            sys.exit(1)


# ─── MCP Server ───

class MCPServer:
    """Minimal MCP (Model Context Protocol) server over stdin/stdout.
    Implements JSON-RPC 2.0 for tool discovery and execution.
    Usage: cdpilot mcp
    """

    def __init__(self):
        self.tools = self._register_tools()

    def _register_tools(self):
        return [
            {"name": "browser_navigate", "description": "Navigate to a URL",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate to"}}, "required": ["url"]}},
            {"name": "browser_screenshot", "description": "Take a screenshot of the current page",
             "inputSchema": {"type": "object", "properties": {"filename": {"type": "string", "description": "Output filename", "default": "screenshot.png"}}}},
            {"name": "browser_click", "description": "Click an element by CSS selector",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector"}}, "required": ["selector"]}},
            {"name": "browser_type", "description": "Type text into an input element",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector"}, "text": {"type": "string", "description": "Text to type"}}, "required": ["selector", "text"]}},
            {"name": "browser_content", "description": "Get text content of the current page",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_html", "description": "Get HTML source of the current page",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_eval", "description": "Execute JavaScript in the browser",
             "inputSchema": {"type": "object", "properties": {"expression": {"type": "string", "description": "JavaScript expression"}}, "required": ["expression"]}},
            {"name": "browser_tabs", "description": "List all open browser tabs",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_console", "description": "Get console logs from the browser",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate and capture logs"}}}},
            {"name": "browser_network", "description": "Monitor network requests",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate and monitor"}}}},
            {"name": "browser_a11y", "description": "Get accessibility tree of the current page",
             "inputSchema": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["full", "summary"], "default": "full"}}}},
            {"name": "browser_fill", "description": "Set input value (React-compatible)",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector"}, "value": {"type": "string", "description": "Value to set"}}, "required": ["selector", "value"]}},
            {"name": "browser_launch", "description": "Launch browser with CDP enabled",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_close", "description": "Close the active tab",
             "inputSchema": {"type": "object", "properties": {}}},
        ]

    def _handle_request(self, request):
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cdpilot", "version": __version__}
            }}
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.tools}}
        elif method == "tools/call":
            return self._execute_tool(req_id, params.get("name", ""), params.get("arguments", {}))
        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    @staticmethod
    def _safe_filename(name):
        import re
        base = os.path.basename(name)
        base = re.sub(r'[^\w.\-]', '_', base)
        if not base.lower().endswith('.png'):
            base += '.png'
        return os.path.join(SCREENSHOT_DIR, base)

    def _execute_tool(self, req_id, tool_name, args):
        import io, subprocess
        tool_map = {
            "browser_navigate": lambda a: ["go", a.get("url", "")],
            "browser_screenshot": lambda a: ["shot"] + ([self._safe_filename(a["filename"])] if a.get("filename") else []),
            "browser_click": lambda a: ["click", a.get("selector", "")],
            "browser_type": lambda a: ["type", a.get("selector", ""), a.get("text", "")],
            "browser_content": lambda a: ["content"],
            "browser_html": lambda a: ["html"],
            "browser_eval": lambda a: ["eval", a.get("expression", "")],
            "browser_tabs": lambda a: ["tabs"],
            "browser_console": lambda a: ["console"] + ([a["url"]] if a.get("url") else []),
            "browser_network": lambda a: ["network"] + ([a["url"]] if a.get("url") else []),
            "browser_a11y": lambda a: ["a11y"] + ([a["mode"]] if a.get("mode") and a["mode"] != "full" else []),
            "browser_fill": lambda a: ["fill", a.get("selector", ""), a.get("value", "")],
            "browser_launch": lambda a: ["launch"],
            "browser_close": lambda a: ["close"],
        }
        if tool_name not in tool_map:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"}}

        cli_args = [a for a in tool_map[tool_name](args) if a]
        try:
            result = subprocess.run(
                [sys.executable, __file__] + cli_args,
                capture_output=True, text=True, timeout=30
            )
            output = result.stdout.strip()
            errors = result.stderr.strip()
            content = []
            if output:
                content.append({"type": "text", "text": output})
            if errors:
                content.append({"type": "text", "text": f"stderr: {errors}"})
            if not content:
                content.append({"type": "text", "text": "Command executed successfully"})
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": content, "isError": result.returncode != 0}}
        except subprocess.TimeoutExpired:
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "Error: Command timed out (30s)"}], "isError": True}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}}

    def run(self):
        import json as json_mod
        sys.stderr.write(f"cdpilot MCP server v{__version__} ready\n")
        sys.stderr.flush()
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                request = json_mod.loads(line)
                response = self._handle_request(request)
                if response is not None:
                    sys.stdout.write(json_mod.dumps(response) + "\n")
                    sys.stdout.flush()
            except json_mod.JSONDecodeError as e:
                sys.stdout.write(json_mod.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {str(e)}"}}) + "\n")
                sys.stdout.flush()
            except KeyboardInterrupt:
                break
            except Exception as e:
                sys.stderr.write(f"MCP error: {str(e)}\n")
                sys.stderr.flush()


# ─── CLI ───

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    sync_cmds = {
        'launch': cmd_launch,
        'tabs': cmd_tabs,
        'extensions': cmd_extensions,
        'stop': cmd_stop,
        'version': cmd_version,
        'proxy': lambda: cmd_proxy(args[0] if args else None),
        'headless': lambda: cmd_headless(args[0] if args else None),
        'session': cmd_session,
        'sessions': cmd_sessions,
        'session-close': lambda: cmd_session_close(args[0] if args else None),
    }

    if cmd == "mcp":
        server = MCPServer()
        server.run()
        sys.exit(0)

    if cmd == "ext-install":
        if not args:
            print("Usage: ext-install <crx-file-or-directory>")
            sys.exit(1)
        cmd_ext_install(args[0])
        sys.exit(0)

    if cmd == "ext-remove":
        if not args:
            print("Usage: ext-remove <extension-id>")
            sys.exit(1)
        cmd_ext_remove(args[0])
        sys.exit(0)

    if cmd == 'switch-tab':
        if not args:
            print('Usage: switch-tab <index-or-id>')
            sys.exit(1)
        cmd_switch_tab(args[0])
        sys.exit(0)

    if cmd in sync_cmds:
        sync_cmds[cmd]()
        sys.exit(0)

    def require_args(n, usage):
        if len(args) < n:
            print(f"Usage: {usage}")
            sys.exit(1)

    async_map = {
        "go": lambda: (require_args(1, "go <url>"), cmd_go(args[0]))[1] if not args else cmd_go(args[0]),
        "content": cmd_content,
        "html": cmd_html,
        "shot": lambda: cmd_shot(args[0] if args else None),
        "eval": lambda: (require_args(1, "eval <js>"), None)[1] if not args else cmd_eval(" ".join(args)),
        "click": lambda: (require_args(1, "click <selector>"), None)[1] if not args else cmd_click(args[0]),
        "fill": lambda: (require_args(2, "fill <selector> <value>"), None)[1] if len(args) < 2 else cmd_fill(args[0], " ".join(args[1:])),
        "submit": lambda: cmd_submit(args[0] if args else "form"),
        "type": lambda: (require_args(2, "type <selector> <value>"), None)[1] if len(args) < 2 else cmd_fill(args[0], " ".join(args[1:])),
        "wait": lambda: (require_args(1, "wait <selector>"), None)[1] if not args else cmd_wait(args[0], int(args[1]) if len(args) > 1 else 5),
        "tabs": cmd_tabs,
        "network": lambda: cmd_network(args[0] if args else None),
        "console": lambda: cmd_console(args[0] if args else None),
        "cookies": lambda: cmd_cookies(args[0] if args else None),
        "storage": cmd_storage,
        "perf": cmd_perf,
        "emulate": lambda: (require_args(1, "emulate <device>"), None)[1] if not args else cmd_emulate(args[0]),
        "glow": lambda: cmd_glow(args[0] if args else "on"),
        "debug": lambda: cmd_debug(args[0] if args else None),
        "close": cmd_close,
        'new-tab': lambda: cmd_new_tab(args[0] if args else 'about:blank'),
        'close-tab': lambda: cmd_close_tab(args[0] if args else None),
        'pdf': lambda: cmd_pdf(args[0] if args else None),
        'upload': lambda: (require_args(2, 'upload <selector> <file-path>'), None)[1] if len(args) < 2 else cmd_upload(args[0], ' '.join(args[1:])),
        'multi-eval': lambda: (require_args(1, 'multi-eval <js>'), None)[1] if not args else cmd_multi_eval(' '.join(args)),
        'intercept': lambda: (require_args(1, 'intercept [block|mock|headers|clear|list] ...'), None)[1] if not args else cmd_intercept(args[0], *args[1:]),
        'a11y': lambda: cmd_a11y(' '.join(args)),
        'hover': lambda: (require_args(1, 'hover <selector>'), None)[1] if not args else cmd_hover(args[0]),
        'dblclick': lambda: (require_args(1, 'dblclick <selector>'), None)[1] if not args else cmd_dblclick(args[0]),
        'rightclick': lambda: (require_args(1, 'rightclick <selector>'), None)[1] if not args else cmd_rightclick(args[0]),
        'drag': lambda: (require_args(2, 'drag <from-sel> <to-sel>'), None)[1] if len(args) < 2 else cmd_drag(args[0], args[1]),
        'keys': lambda: (require_args(1, 'keys <combo>'), None)[1] if not args else cmd_keys(args[0]),
        'scroll-to': lambda: (require_args(1, 'scroll-to <selector>'), None)[1] if not args else cmd_scroll_to(args[0]),
        'frame': lambda: (require_args(1, 'frame [list|eval <js>|shadow <selector>]'), None)[1] if not args else cmd_frame(args[0], *args[1:]),
        'dialog': lambda: (require_args(1, 'dialog [auto-accept|auto-dismiss|prompt <text>|off]'), None)[1] if not args else cmd_dialog(args[0], *args[1:]),
        'download': lambda: (require_args(1, 'download [set <directory>|status]'), None)[1] if not args else cmd_download(args[0], *args[1:]),
        'throttle': lambda: (require_args(1, 'throttle [slow3g|fast3g|offline|off|custom <down> <up> <lat>]'), None)[1] if not args else cmd_throttle(args[0], *args[1:]),
        'geo': lambda: (require_args(1, 'geo [<lat> <lng>|istanbul|london|newyork|off]'), None)[1] if not args else cmd_geo(args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None),
        'permission': lambda: (require_args(1, 'permission [grant|deny|reset] [<permission>]'), None)[1] if not args else cmd_permission(args[0], args[1] if len(args) > 1 else None),
    }

    # Commands that do not require the visual indicator / input blocker
    NO_CONTROL_CMDS = {'glow', 'stop', 'tabs', 'close', 'close-tab', 'new-tab',
                       'dialog', 'download', 'throttle', 'permission', 'intercept'}
    # Clean up idle sessions before running any command
    _cleanup_idle_sessions()

    if cmd in async_map:
        if cmd in NO_CONTROL_CMDS:
            asyncio.run(async_map[cmd]())
            _update_session_timestamp()
        else:
            async def _wrapped():
                ws_url = None
                try:
                    ws_url, _ = get_page_ws()
                    await _control_start(ws_url)
                except Exception:
                    pass
                try:
                    await async_map[cmd]()
                finally:
                    if ws_url:
                        try:
                            ws_new, _ = get_page_ws()
                            await _control_end(ws_new)
                        except Exception:
                            if ws_url:
                                await _control_end(ws_url)
            asyncio.run(_wrapped())
            _update_session_timestamp()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        all_cmds = sorted(set(list(sync_cmds.keys()) + list(async_map.keys())))
        matches = difflib.get_close_matches(cmd, all_cmds, n=1, cutoff=0.6)
        if matches:
            print(f"Did you mean: {matches[0]}?", file=sys.stderr)
        print(f"\nAvailable commands: {', '.join(all_cmds)}", file=sys.stderr)
        sys.exit(1)

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
import hashlib
import re as _re

# ─── Project-Based Multi-Instance Configuration ───
# Each project directory (cwd) gets its own browser instance with
# a unique CDP port and isolated profile directory. Zero-config.

CDPILOT_HOME = os.path.expanduser("~/.cdpilot")
REGISTRY_FILE = os.path.join(CDPILOT_HOME, "registry.json")
CDPILOT_PORT_RANGE_START = 9222
CDPILOT_PORT_RANGE_END = 9322
IS_MCP_SESSION = os.environ.get("CDPILOT_MCP_SESSION") == "1"


def _get_project_id():
    """Derive a deterministic project ID from the current working directory.

    Prefers CDPILOT_PROJECT_ID env (set by bin/cdpilot.js based on caller's cwd)
    over os.getcwd() which may differ when invoked via npx or absolute path.
    """
    env_id = os.environ.get("CDPILOT_PROJECT_ID")
    if env_id:
        return env_id
    cwd = os.getcwd()
    dir_name = os.path.basename(cwd)
    safe_name = _re.sub(r'[^a-zA-Z0-9-]', '', dir_name)[:20]
    hash_suffix = hashlib.md5(cwd.encode()).hexdigest()[:6]
    return f"{safe_name}-{hash_suffix}" if safe_name else hash_suffix


def _is_port_free(port):
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _load_registry():
    """Read the global project registry."""
    try:
        with open(REGISTRY_FILE) as f:
            data = json.load(f)
            return data.get("projects", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_registry(projects):
    """Write the global project registry."""
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    with open(REGISTRY_FILE, 'w') as f:
        json.dump({"version": 1, "projects": projects}, f, indent=2)


def _register_project(project_id, port, profile_dir, pid=None):
    """Register or update a project in the global registry."""
    registry = _load_registry()
    existing = registry.get(project_id, {})
    registry[project_id] = {
        "cwd": os.getcwd(),
        "port": port,
        "profile_dir": profile_dir,
        "pid": pid,
        "created": existing.get("created", time.strftime("%Y-%m-%dT%H:%M:%S")),
        "last_used": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "running" if pid else "stopped",
    }
    _save_registry(registry)


def _cleanup_registry():
    """Update status for dead processes and return cleaned registry."""
    registry = _load_registry()
    changed = False
    for pid_key, info in registry.items():
        if info.get("status") == "running":
            port = info.get("port")
            if port and _is_port_free(port):
                info["status"] = "stopped"
                info["pid"] = None
                changed = True
    if changed:
        _save_registry(registry)
    return registry


def _allocate_port(project_id):
    """Find a free port for the given project."""
    registry = _load_registry()

    # Reuse existing port if still free
    if project_id in registry:
        existing_port = registry[project_id].get("port")
        if existing_port and _is_port_free(existing_port):
            return existing_port

    # Collect ports used by other active projects
    used_ports = set()
    for pid, info in registry.items():
        if pid != project_id and info.get("port"):
            used_ports.add(info["port"])

    # Find first free port in range
    for port in range(CDPILOT_PORT_RANGE_START, CDPILOT_PORT_RANGE_END):
        if port not in used_ports and _is_port_free(port):
            return port

    raise RuntimeError(
        f"No free port in range {CDPILOT_PORT_RANGE_START}-{CDPILOT_PORT_RANGE_END}"
    )


def _resolve_project_config():
    """Determine port, profile dir, and project ID based on cwd + env vars."""
    env_port = os.environ.get("CDP_PORT")
    env_profile = os.environ.get("CDPILOT_PROFILE")

    # Treat CDP_PORT=0 as "auto-allocate"
    has_explicit_port = env_port and env_port != "0"

    # Full manual override (legacy behavior)
    if has_explicit_port and env_profile:
        return int(env_port), env_profile, None

    project_id = _get_project_id()
    registry = _load_registry()
    default_profile = os.path.join(CDPILOT_HOME, "projects", project_id, "profile")

    if project_id in registry:
        info = registry[project_id]
        port = int(env_port) if has_explicit_port else info.get("port", 9222)
        profile = env_profile or info.get("profile_dir", default_profile)
        return port, profile, project_id

    # New project: allocate port
    try:
        port = int(env_port) if has_explicit_port else _allocate_port(project_id)
    except RuntimeError:
        port = 9222  # fallback
    profile = env_profile or default_profile
    return port, profile, project_id


def _migrate_legacy_profile():
    """Migrate old single-profile layout to project-based layout."""
    legacy_profile = os.path.join(CDPILOT_HOME, "profile")
    if (os.path.isdir(legacy_profile) and not os.path.islink(legacy_profile)
            and not os.path.exists(REGISTRY_FILE)):
        project_id = _get_project_id()
        new_dir = os.path.join(CDPILOT_HOME, "projects", project_id)
        new_profile = os.path.join(new_dir, "profile")
        if not os.path.exists(new_profile):
            os.makedirs(new_dir, exist_ok=True)
            os.rename(legacy_profile, new_profile)
            os.symlink(new_profile, legacy_profile)


# Resolve project config at module load time
try:
    _migrate_legacy_profile()
except Exception:
    pass
CDP_PORT, PROFILE_DIR, PROJECT_ID = _resolve_project_config()
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
CHROME_BIN = os.environ.get("CHROME_BIN")

if platform.system() == "Windows":
    SCREENSHOT_DIR = os.path.expandvars(r"%TEMP%")
else:
    SCREENSHOT_DIR = "/tmp"

DEV_EXTENSIONS_FILE = os.path.join(PROFILE_DIR, 'dev-extensions.json')

# ─── Auto-Wait JS Helper ───────────────────────────────────────────────────────
# Tarayıcıya inject edilir; MutationObserver ile element görünene kadar bekler.
WAIT_AND_QUERY_JS = """
window.__cdpilot_waitFor = function(selector, timeout) {
  return new Promise(function(resolve) {
    var el = document.querySelector(selector);
    if (el) { resolve(el); return; }
    var obs = new MutationObserver(function() {
      var found = document.querySelector(selector);
      if (found) { obs.disconnect(); resolve(found); }
    });
    obs.observe(document.documentElement, {childList: true, subtree: true});
    setTimeout(function() { obs.disconnect(); resolve(null); }, timeout || 5000);
  });
};
"""
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
_A11Y_REF_MAP = {}  # ref_num -> backendNodeId mapping
_A11Y_REF_FILE = os.path.join(PROFILE_DIR, 'a11y-refs.json')


def _save_a11y_refs(ref_map):
    """Persist a11y ref map to disk for cross-process access."""
    os.makedirs(os.path.dirname(_A11Y_REF_FILE), exist_ok=True)
    with open(_A11Y_REF_FILE, 'w') as f:
        json.dump(ref_map, f)


def _load_a11y_refs():
    """Load a11y ref map from disk."""
    try:
        with open(_A11Y_REF_FILE) as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# ─── Visual Indicator Overlay CSS ───

GLOW_CSS = """
(function() {
  if (document.getElementById('cdpilot-glow-overlay')) {
    document.getElementById('cdpilot-glow-overlay').style.opacity = '1';
    clearTimeout(window.__cdpilot_glow_timeout);
    return 'glow refreshed';
  }
  var style = document.createElement('style');
  style.id = 'cdpilot-glow-style';
  style.textContent = `
    @keyframes cdpilot-pulse {
      0%, 100% { box-shadow: inset 0 0 20px 4px rgba(34,197,94,0.25), inset 0 0 60px 8px rgba(34,197,94,0.08); }
      50% { box-shadow: inset 0 0 30px 6px rgba(34,197,94,0.35), inset 0 0 80px 12px rgba(34,197,94,0.12); }
    }
    #cdpilot-glow-overlay {
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      pointer-events: none; z-index: 2147483646;
      animation: cdpilot-pulse 2s ease-in-out infinite;
      border: 2px solid rgba(34,197,94,0.3);
      transition: opacity 1s ease;
      opacity: 1;
    }
    #cdpilot-ai-toast {
      position: fixed; bottom: -80px; left: 50%; transform: translateX(-50%);
      z-index: 2147483647; background: rgba(15,0,0,0.92); color: #ef4444;
      padding: 14px 28px; border-radius: 12px;
      font: 600 14px/1.4 system-ui,-apple-system,sans-serif;
      transition: bottom 0.4s cubic-bezier(0.34,1.56,0.64,1);
      border: 1px solid rgba(239,68,68,0.4);
      box-shadow: 0 4px 24px rgba(0,0,0,0.5), 0 0 20px rgba(239,68,68,0.15);
      pointer-events: none; white-space: nowrap; backdrop-filter: blur(8px);
    }
  `;
  document.head.appendChild(style);
  var overlay = document.createElement('div');
  overlay.id = 'cdpilot-glow-overlay';
  document.body.appendChild(overlay);
  var toast = document.createElement('div');
  toast.id = 'cdpilot-ai-toast';
  toast.textContent = '\\u26A0\\uFE0F  Browser is controlled by AI — please wait';
  document.body.appendChild(toast);
  var _tt, _throttle = 0;
  function _showWarn() {
    if (!document.getElementById('cdpilot-glow-overlay')) return;
    var now = Date.now();
    if (now - _throttle < 2000) return;
    _throttle = now;
    toast.style.bottom = '24px';
    clearTimeout(_tt);
    _tt = setTimeout(function() { toast.style.bottom = '-80px'; }, 3000);
  }
  window.__cdpilot_warn = _showWarn;
  document.addEventListener('mousemove', _showWarn, true);
  clearTimeout(window.__cdpilot_glow_timeout);
  return 'glow active';
})()
"""

GLOW_OFF_CSS = """
(function() {
  var overlay = document.getElementById('cdpilot-glow-overlay');
  var style = document.getElementById('cdpilot-glow-style');
  var toast = document.getElementById('cdpilot-ai-toast');
  if (overlay) { overlay.style.opacity = '0'; setTimeout(function() { overlay.remove(); }, 1000); }
  if (style) setTimeout(function() { style.remove(); }, 1100);
  if (toast) toast.remove();
  if (window.__cdpilot_warn) {
    document.removeEventListener('mousemove', window.__cdpilot_warn, true);
    delete window.__cdpilot_warn;
  }
  clearTimeout(window.__cdpilot_glow_timeout);
  return overlay ? 'glow fading' : 'already off';
})()
"""

# ─── Input Blocker (prevent user interference during automation) ───

INPUT_BLOCKER_ON = """
(function() {
  if (document.getElementById('cdpilot-input-blocker')) return 'blocker already active';
  var overlay = document.createElement('div');
  overlay.id = 'cdpilot-input-blocker';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:2147483646;cursor:not-allowed;background:transparent;';
  var toast = document.createElement('div');
  toast.id = 'cdpilot-warning-toast';
  toast.textContent = '\\u26A0\\uFE0F  Browser is controlled by AI \\u2014 please wait';
  toast.style.cssText = 'position:fixed;bottom:-80px;left:50%;transform:translateX(-50%);z-index:2147483647;background:rgba(15,0,0,0.92);color:#ef4444;padding:14px 28px;border-radius:12px;font:600 14px/1.4 system-ui,-apple-system,sans-serif;transition:bottom 0.4s cubic-bezier(0.34,1.56,0.64,1);border:1px solid rgba(239,68,68,0.4);box-shadow:0 4px 24px rgba(0,0,0,0.5),0 0 20px rgba(239,68,68,0.15);pointer-events:none;white-space:nowrap;backdrop-filter:blur(8px);';
  document.body.appendChild(toast);
  var _tt;
  function _warn() {
    toast.style.bottom = '24px';
    clearTimeout(_tt);
    _tt = setTimeout(function() { toast.style.bottom = '-80px'; }, 3000);
  }
  overlay.addEventListener('mousedown', function(e) { e.stopPropagation(); e.preventDefault(); _warn(); }, true);
  overlay.addEventListener('mouseup', function(e) { e.stopPropagation(); e.preventDefault(); }, true);
  overlay.addEventListener('click', function(e) { e.stopPropagation(); e.preventDefault(); _warn(); }, true);
  overlay.addEventListener('dblclick', function(e) { e.stopPropagation(); e.preventDefault(); }, true);
  overlay.addEventListener('contextmenu', function(e) { e.stopPropagation(); e.preventDefault(); }, true);
  overlay.addEventListener('wheel', function(e) { e.stopPropagation(); e.preventDefault(); }, {capture:true, passive:false});
  document.addEventListener('keydown', function _cb(e) {
    if (!document.getElementById('cdpilot-input-blocker')) { document.removeEventListener('keydown', _cb, true); return; }
    e.stopPropagation(); e.preventDefault(); _warn();
  }, true);
  document.addEventListener('keyup', function _cb(e) {
    if (!document.getElementById('cdpilot-input-blocker')) { document.removeEventListener('keyup', _cb, true); return; }
    e.stopPropagation(); e.preventDefault();
  }, true);
  document.addEventListener('keypress', function _cb(e) {
    if (!document.getElementById('cdpilot-input-blocker')) { document.removeEventListener('keypress', _cb, true); return; }
    e.stopPropagation(); e.preventDefault();
  }, true);
  document.body.appendChild(overlay);
  return 'input blocker active';
})()
"""

INPUT_BLOCKER_OFF = """
(function() {
  var el = document.getElementById('cdpilot-input-blocker');
  if (el) el.remove();
  var toast = document.getElementById('cdpilot-warning-toast');
  if (toast) toast.remove();
  return el ? 'input blocker off' : 'blocker already off';
})()
"""

# ─── Visual Feedback System (cursor, ripple, keystroke) ───

VISUAL_FEEDBACK_JS = """
(function() {
  if (window.__cdpilot_vfx) return 'vfx already active';
  var style = document.createElement('style');
  style.id = 'cdpilot-vfx-style';
  style.textContent = `
    @keyframes cdpilot-ripple-anim {
      0% { transform: translate(-50%,-50%) scale(0); opacity: 1; }
      100% { transform: translate(-50%,-50%) scale(1); opacity: 0; }
    }
    .cdpilot-ripple {
      position: fixed; width: 50px; height: 50px;
      border: 2.5px solid #22c55e; border-radius: 50%;
      pointer-events: none; z-index: 2147483647;
      animation: cdpilot-ripple-anim 0.6s ease-out forwards;
      box-shadow: 0 0 12px rgba(34,197,94,0.4);
    }
    .cdpilot-ripple-inner {
      position: fixed; width: 8px; height: 8px;
      background: #22c55e; border-radius: 50%;
      pointer-events: none; z-index: 2147483647;
      transform: translate(-50%,-50%);
      opacity: 0.8;
      animation: cdpilot-ripple-anim 0.4s ease-out 0.1s forwards;
    }
    #cdpilot-cursor {
      position: fixed; pointer-events: none; z-index: 2147483647;
      transition: left 0.2s cubic-bezier(0.25,0.8,0.25,1), top 0.2s cubic-bezier(0.25,0.8,0.25,1);
      filter: drop-shadow(0 0 4px rgba(34,197,94,0.6));
    }
    #cdpilot-keystroke {
      position: fixed; bottom: 80px; left: 50%;
      transform: translateX(-50%);
      background: rgba(0,0,0,0.88); color: #22c55e;
      padding: 10px 20px; border-radius: 8px;
      font: 700 15px/1.4 'SF Mono',Monaco,Menlo,monospace;
      pointer-events: none; z-index: 2147483647;
      border: 1px solid rgba(34,197,94,0.4);
      box-shadow: 0 4px 20px rgba(0,0,0,0.4), 0 0 15px rgba(34,197,94,0.1);
      opacity: 0; transition: opacity 0.3s ease;
      backdrop-filter: blur(8px);
    }
  `;
  document.head.appendChild(style);
  var cursor = document.createElement('div');
  cursor.id = 'cdpilot-cursor';
  cursor.style.display = 'none';
  cursor.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M5.5 3.21V20.8l5.71-5.71h8.3L5.5 3.21z" fill="#22c55e" stroke="#15803d" stroke-width="1.2"/></svg>';
  document.body.appendChild(cursor);
  var ks = document.createElement('div');
  ks.id = 'cdpilot-keystroke';
  document.body.appendChild(ks);
  window.__cdpilot_vfx = {
    ripple: function(x, y) {
      var el = document.createElement('div');
      el.className = 'cdpilot-ripple';
      el.style.left = x + 'px'; el.style.top = y + 'px';
      document.body.appendChild(el);
      var inner = document.createElement('div');
      inner.className = 'cdpilot-ripple-inner';
      inner.style.left = x + 'px'; inner.style.top = y + 'px';
      document.body.appendChild(inner);
      setTimeout(function() { el.remove(); inner.remove(); }, 700);
    },
    moveCursor: function(x, y) {
      cursor.style.display = 'block';
      cursor.style.left = (x - 3) + 'px';
      cursor.style.top = (y - 2) + 'px';
    },
    hideCursor: function() { cursor.style.display = 'none'; },
    keystroke: function(text) {
      ks.textContent = text;
      ks.style.opacity = '1';
      clearTimeout(ks.__tid);
      ks.__tid = setTimeout(function() { ks.style.opacity = '0'; }, 2000);
    }
  };
  return 'vfx active';
})()
"""

VISUAL_FEEDBACK_OFF = """
(function() {
  delete window.__cdpilot_vfx;
  ['cdpilot-vfx-style','cdpilot-cursor','cdpilot-keystroke'].forEach(function(id) {
    var el = document.getElementById(id); if (el) el.remove();
  });
  document.querySelectorAll('.cdpilot-ripple,.cdpilot-ripple-inner').forEach(function(el) { el.remove(); });
  return 'vfx off';
})()
"""

# ─── Glow Auto-Timeout (fade out after 10s idle) ───

GLOW_TIMEOUT_JS = """
clearTimeout(window.__cdpilot_glow_timeout);
window.__cdpilot_glow_timeout = setTimeout(function() {
  var o = document.getElementById('cdpilot-glow-overlay');
  if (o) { o.style.opacity = '0'; setTimeout(function() { o.remove(); }, 1000); }
  var s = document.getElementById('cdpilot-glow-style');
  if (s) setTimeout(function() { s.remove(); }, 1100);
  var t = document.getElementById('cdpilot-ai-toast');
  if (t) t.remove();
  if (window.__cdpilot_warn) {
    document.removeEventListener('mousemove', window.__cdpilot_warn, true);
    delete window.__cdpilot_warn;
  }
  ['cdpilot-vfx-style','cdpilot-cursor','cdpilot-keystroke'].forEach(function(id) {
    var el = document.getElementById(id); if (el) el.remove();
  });
  delete window.__cdpilot_vfx;
}, 10000);
"""

# ─── Automation Indicator Wrapper ───

_glow_script_id = None  # addScriptToEvaluateOnNewDocument identifier

async def _control_start(ws_url):
    """Enable glow, input blocker, and visual feedback at command start."""
    global _glow_script_id
    try:
        # Remove previous persistent script if exists (prevent accumulation)
        cmds = []
        if _glow_script_id:
            cmds.append((900, "Page.removeScriptToEvaluateOnNewDocument", {"identifier": _glow_script_id}))
            _glow_script_id = None
        persistent_source = GLOW_CSS + "\n" + VISUAL_FEEDBACK_JS
        cmds.extend([
            (901, "Page.addScriptToEvaluateOnNewDocument", {"source": persistent_source}),
            (902, "Runtime.evaluate", {"expression": GLOW_CSS, "returnByValue": True}),
            (903, "Runtime.evaluate", {"expression": VISUAL_FEEDBACK_JS, "returnByValue": True}),
            (904, "Runtime.evaluate", {"expression": INPUT_BLOCKER_ON, "returnByValue": True}),
        ])
        r = await cdp_send(ws_url, cmds)
        resp_901 = r.get(901, {})
        result = resp_901.get("result", {})
        if isinstance(result, dict) and "identifier" in result:
            _glow_script_id = result["identifier"]
    except Exception:
        pass

async def _control_end(ws_url):
    """Remove input blocker, keep glow alive.

    In MCP session mode (CDPILOT_MCP_SESSION=1): glow stays permanently,
    no timeout — mimics Claude's persistent orange glow behavior.
    In CLI mode: glow fades after 10s idle (GLOW_TIMEOUT_JS).
    """
    global _glow_script_id
    try:
        cmds = [
            (903, "Runtime.evaluate", {"expression": INPUT_BLOCKER_OFF, "returnByValue": True}),
            # Re-inject glow+vfx on current page (may be new after navigation)
            (906, "Runtime.evaluate", {"expression": GLOW_CSS, "returnByValue": True}),
            (907, "Runtime.evaluate", {"expression": VISUAL_FEEDBACK_JS, "returnByValue": True}),
        ]
        if not IS_MCP_SESSION:
            # CLI mode: start 10s auto-cleanup timeout
            cmds.append((904, "Runtime.evaluate", {"expression": GLOW_TIMEOUT_JS, "returnByValue": True}))
        # Don't remove persistent script — it auto-cleans via GLOW_TIMEOUT_JS (CLI)
        # or stays forever (MCP session).
        _glow_script_id = None
        await cdp_send(ws_url, cmds)
    except Exception:
        pass

async def _vfx_ripple(ws_url, x, y):
    """Show click ripple + move cursor at (x, y)."""
    js = f"if(window.__cdpilot_vfx){{window.__cdpilot_vfx.moveCursor({x},{y});window.__cdpilot_vfx.ripple({x},{y});}}"
    try:
        await cdp_send(ws_url, [(999, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    except Exception:
        pass

async def _vfx_keystroke(ws_url, text):
    """Show keystroke display."""
    safe = json.dumps(text)
    js = f"if(window.__cdpilot_vfx){{window.__cdpilot_vfx.keystroke({safe});}}"
    try:
        await cdp_send(ws_url, [(999, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    except Exception:
        pass

async def _vfx_move_cursor(ws_url, x, y):
    """Move fake cursor to (x, y)."""
    js = f"if(window.__cdpilot_vfx){{window.__cdpilot_vfx.moveCursor({x},{y});}}"
    try:
        await cdp_send(ws_url, [(999, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    except Exception:
        pass

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
        print("Browser is not running. Run 'cdpilot launch' first.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        err = str(e)
        if "websocket" in err.lower() or "connect" in err.lower() or "ws://" in err.lower():
            print(f"Browser is not running or CDP port {CDP_PORT} is unreachable. Run 'cdpilot launch' first.", file=sys.stderr)
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

        # Inject visual indicator (glow overlay + visual feedback)
        if glow:
            await ws.send(json.dumps({
                "id": 200, "method": "Runtime.evaluate",
                "params": {"expression": GLOW_CSS, "returnByValue": True}
            }))
            sid += 1
            await ws.send(json.dumps({
                "id": sid, "method": "Runtime.evaluate",
                "params": {"expression": VISUAL_FEEDBACK_JS, "returnByValue": True}
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
    """Check if a port is actively in use."""
    return not _is_port_free(port)


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
    global CHROME_BIN, CDP_PORT, CDP_BASE
    if cdp_get('/json/version'):
        proj_label = f' [{PROJECT_ID}]' if PROJECT_ID else ''
        print(f'Browser already running on port {CDP_PORT}{proj_label}.')
        return
    if _is_port_in_use(CDP_PORT):
        if PROJECT_ID:
            # Auto-allocate a new port
            new_port = _allocate_port(PROJECT_ID)
            print(f'Port {CDP_PORT} busy, using {new_port}.')
            CDP_PORT = new_port
            CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
        else:
            print(f'Error: Port {CDP_PORT} is in use. Set CDP_PORT to a different port.', file=sys.stderr)
            sys.exit(1)

    if not CHROME_BIN:
        bin_path = _find_browser()
        if not bin_path:
            print('No supported browser found. Install Brave, Chrome, or Chromium and ensure it is in PATH or set CHROME_BIN.', file=sys.stderr)
            sys.exit(1)
        CHROME_BIN = bin_path
        print(f'Browser found: {bin_path}')

    os.makedirs(PROFILE_DIR, exist_ok=True)

    proj_label = f' [{PROJECT_ID}]' if PROJECT_ID else ''
    print(f'Launching browser (isolated session, port {CDP_PORT}){proj_label}...')

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

    proc = subprocess.Popen(chrome_args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    for _ in range(20):
        time.sleep(0.5)
        if cdp_get('/json/version'):
            if PROJECT_ID:
                _register_project(PROJECT_ID, CDP_PORT, PROFILE_DIR, pid=proc.pid)
            proj_label = f' [{PROJECT_ID}]' if PROJECT_ID else ''
            print(f'CDP ready! (port {CDP_PORT}){proj_label}')
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


async def cmd_shot(output=None, quality=None, element=None, fmt=None):
    """Take screenshot. Supports --quality, --element, --format for token savings.

    Args:
        output: File path (auto-detects format from extension)
        quality: JPEG quality 1-100 (only for jpeg format, saves ~5-7x tokens)
        element: CSS selector to capture only that element (crop)
        fmt: Force format: 'png', 'jpeg', or 'webp'
    """
    if not output:
        output = f"{SCREENSHOT_DIR}/screenshot.png"
    ws, _ = get_page_ws()

    # Auto-detect format from extension
    if fmt is None:
        ext = os.path.splitext(output)[1].lower()
        fmt = {"jpg": "jpeg", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}.get(ext, "png")

    params = {"format": fmt}
    if fmt == "jpeg" and quality:
        params["quality"] = max(1, min(100, int(quality)))
    elif fmt == "jpeg" and quality is None:
        params["quality"] = 80  # sensible default

    # Element-level crop: get bounding rect, use clip
    if element:
        safe_sel = json.dumps(element)
        js = f"""
        (function() {{
          var el = document.querySelector({safe_sel});
          if (!el) return null;
          el.scrollIntoView({{block: 'center'}});
          var r = el.getBoundingClientRect();
          return JSON.stringify({{x: r.x, y: r.y, width: r.width, height: r.height}});
        }})()
        """
        cr = await cdp_send(ws, [(2, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
        rect_str = cr.get(2, {}).get("result", {}).get("value")
        if rect_str:
            rect = json.loads(rect_str)
            params["clip"] = {
                "x": rect["x"], "y": rect["y"],
                "width": rect["width"], "height": rect["height"],
                "scale": 1
            }
        else:
            print(f"Element not found: {element}, taking full page", file=sys.stderr)

    r = await cdp_send(ws, [(1, "Page.captureScreenshot", params)])
    b64 = r.get(1, {}).get("result", {}).get("data", "") or r.get(1, {}).get("data", "")
    if b64:
        data = base64.b64decode(b64)
        with open(output, "wb") as f:
            f.write(data)
        size_kb = len(data) / 1024
        print(f"{output} ({size_kb:.1f}KB)")
    else:
        print("Screenshot failed", file=sys.stderr)


async def cmd_shot_annotated(output=None):
    """Etkileşimli elementler üzerine @N badge eklenmiş annotated screenshot al."""
    if not output:
        output = f"{SCREENSHOT_DIR}/screenshot-annotated.png"
    ws_url, _ = get_page_ws()

    # A11y tree'den etkileşimli node'ları topla
    await cdp_send(ws_url, [
        (0, "Accessibility.enable", {}),
        (9, "DOM.enable", {}),
    ])
    res = await cdp_send(ws_url, [(1, "Accessibility.getFullAXTree", {})])
    nodes = res.get(1, {}).get("nodes", [])

    interactive_roles = {
        "button", "link", "textbox", "textField", "combobox", "comboBox",
        "checkbox", "radio", "menuitem", "menuItem", "searchbox", "searchBox",
        "spinbutton", "spinButton", "switch", "tab", "slider",
    }
    targets = [
        n for n in nodes
        if not n.get("ignored")
        and n.get("role", {}).get("value", "") in interactive_roles
        and n.get("backendDOMNodeId")
    ]

    # Her node için ekran koordinatlarını al
    badge_count = 0
    inject_parts = []
    for idx, node in enumerate(targets, start=1):
        backend_id = node["backendDOMNodeId"]
        res_b = await cdp_send(ws_url, [(11, "DOM.getBoxModel", {"backendNodeId": backend_id})])
        model = res_b.get(11, {}).get("model")
        if not model:
            continue
        content = model.get("content", model.get("border", []))
        if len(content) < 8:
            continue
        left = int(content[0])
        top = int(content[1])
        width = int(content[2] - content[0])
        height = int(content[5] - content[1])
        if width == 0 or height == 0:
            continue
        label = json.dumps(f"@{idx}")
        inject_parts.append(
            f"(function(){{"
            f"var b=document.createElement('span');"
            f"b.textContent={label};"
            f"b.setAttribute('data-cdpilot-badge','1');"
            f"b.style.cssText='position:fixed;left:{left}px;top:{top}px;"
            f"background:#22c55e;color:#fff;font-size:11px;font-weight:bold;"
            f"padding:1px 4px;border-radius:3px;z-index:99999;"
            f"pointer-events:none;line-height:1.4;';"
            f"document.body.appendChild(b);"
            f"}})();"
        )
        badge_count += 1

    # Badge'leri inject et
    if inject_parts:
        inject_js = "\n".join(inject_parts)
        await cdp_send(ws_url, [(20, "Runtime.evaluate", {"expression": inject_js})])

    # Screenshot al
    r = await cdp_send(ws_url, [(21, "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})])
    b64 = r.get(21, {}).get("data", "")

    # Badge'leri temizle
    await cdp_send(ws_url, [(22, "Runtime.evaluate", {
        "expression": "document.querySelectorAll('[data-cdpilot-badge]').forEach(function(e){e.remove();})"
    })])

    if b64:
        with open(output, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"{output} ({badge_count} badge)")
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
    js = WAIT_AND_QUERY_JS + f"""
(function() {{
    return window.__cdpilot_waitFor({safe_sel}, 5000).then(function(el) {{
        if (!el) return 'Timeout waiting for: ' + {safe_sel};
        el.scrollIntoView({{behavior:'smooth', block:'center'}});
        if (window.__cdpilot_vfx) {{
            var r = el.getBoundingClientRect();
            var cx = Math.round(r.left + r.width/2), cy = Math.round(r.top + r.height/2);
            window.__cdpilot_vfx.moveCursor(cx, cy);
            window.__cdpilot_vfx.ripple(cx, cy);
        }}
        el.click();
        return 'Clicked: ' + el.tagName + ' ' + (el.textContent || '').substring(0, 60).trim();
    }});
}})()"""
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})])
    print(r.get(1, {}).get("result", {}).get("value", "?"))


async def cmd_fill(selector, value):
    """Fill an input field with auto-wait (React/Vue compatible)."""
    ws, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    safe_value = json.dumps(value)
    js = WAIT_AND_QUERY_JS + f"""
(function() {{
    return window.__cdpilot_waitFor({safe_sel}, 5000).then(function(el) {{
        if (!el) return 'Timeout waiting for: ' + {safe_sel};
        el.focus();
        if (window.__cdpilot_vfx) {{
            var r = el.getBoundingClientRect();
            window.__cdpilot_vfx.moveCursor(Math.round(r.left + r.width/2), Math.round(r.top + r.height/2));
            window.__cdpilot_vfx.keystroke('\\u2328 ' + {safe_value}.substring(0, 30));
        }}
        var nativeSet = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
        );
        if (nativeSet && nativeSet.set) {{
            nativeSet.set.call(el, {safe_value});
        }} else {{
            el.value = {safe_value};
        }}
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return 'Filled: ' + el.tagName + ' = ' + el.value.substring(0, 50);
    }});
}})()"""
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})])
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


async def cmd_batch():
    """stdin'den JSON komut dizisi oku, sırayla çalıştır, sonuçları JSON olarak yaz.

    Kullanım:
      echo '[{"cmd":"go","args":["https://example.com"]},{"cmd":"shot","args":["/tmp/out.png"]}]' | cdpilot batch
    """
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
        if not isinstance(data, list):
            print(json.dumps({"error": "Input must be a JSON array"}), file=sys.stderr)
            sys.exit(1)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"JSON parse error: {exc}"}), file=sys.stderr)
        sys.exit(1)

    results = []
    for item in data:
        cmd_name = item.get("cmd", "")
        cmd_args = item.get("args", [])
        try:
            if cmd_name == "go":
                await cmd_go(cmd_args[0] if cmd_args else "")
            elif cmd_name == "click":
                await cmd_click(cmd_args[0] if cmd_args else "")
            elif cmd_name in ("fill", "type"):
                await cmd_fill(cmd_args[0] if cmd_args else "", cmd_args[1] if len(cmd_args) > 1 else "")
            elif cmd_name == "shot":
                await cmd_shot(cmd_args[0] if cmd_args else None)
            elif cmd_name == "shot-annotated":
                await cmd_shot_annotated(cmd_args[0] if cmd_args else None)
            elif cmd_name == "wait":
                await cmd_wait(cmd_args[0] if cmd_args else "body", int(cmd_args[1]) if len(cmd_args) > 1 else 5)
            elif cmd_name == "eval":
                await cmd_eval(" ".join(cmd_args) if cmd_args else "")
            elif cmd_name == "submit":
                await cmd_submit(cmd_args[0] if cmd_args else "form")
            else:
                results.append({"cmd": cmd_name, "status": "error", "error": f"Unsupported command: {cmd_name}"})
                continue
            results.append({"cmd": cmd_name, "status": "ok"})
        except SystemExit:
            results.append({"cmd": cmd_name, "status": "error", "error": "Command exited with error"})
        except Exception as exc:
            results.append({"cmd": cmd_name, "status": "error", "error": str(exc)})

    print(json.dumps(results, indent=2, ensure_ascii=False))


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
    if state == "on":
        await cdp_send(ws, [
            (1, "Runtime.evaluate", {"expression": GLOW_CSS, "returnByValue": True}),
            (2, "Runtime.evaluate", {"expression": VISUAL_FEEDBACK_JS, "returnByValue": True}),
        ])
    else:
        await cdp_send(ws, [
            (1, "Runtime.evaluate", {"expression": GLOW_OFF_CSS, "returnByValue": True}),
            (2, "Runtime.evaluate", {"expression": VISUAL_FEEDBACK_OFF, "returnByValue": True}),
        ])
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
    safe_chars = ":/?#[]@!$&'()*+,;="
    data = cdp_get(f'/json/new?{urllib.parse.quote(url, safe=safe_chars)}')
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


def _stop_browser_on_port(port):
    """Stop the browser process listening on the given port."""
    import signal
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True
        )
        pids = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
        if pids:
            for pid in pids:
                os.kill(int(pid), signal.SIGTERM)
            return True
        else:
            subprocess.run(
                ["pkill", "-f", f"remote-debugging-port={port}"],
                capture_output=True, text=True
            )
            return True
    except Exception:
        return False


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

    # Update registry
    if PROJECT_ID:
        registry = _load_registry()
        if PROJECT_ID in registry:
            registry[PROJECT_ID]["status"] = "stopped"
            registry[PROJECT_ID]["pid"] = None
            _save_registry(registry)


def cmd_version():
    """Show cdpilot version."""
    print(f"cdpilot v{__version__}")


def cmd_projects():
    """List all registered cdpilot project instances."""
    registry = _cleanup_registry()
    if not registry:
        print("No registered projects.")
        return

    current = PROJECT_ID
    print(f"{'Project':<28} {'Port':<7} {'Status':<10} {'CWD'}")
    print("\u2500" * 90)

    for pid, info in sorted(registry.items(),
                            key=lambda x: x[1].get("last_used", ""), reverse=True):
        port = info.get("port", "?")
        status = info.get("status", "?")
        cwd = info.get("cwd", "?")
        # Live check
        if status == "running" and _is_port_free(port):
            status = "stopped"
        icon = "\U0001f7e2" if status == "running" else "\u26ab"
        marker = " \u2190 current" if pid == current else ""
        if len(cwd) > 45:
            cwd = "..." + cwd[-42:]
        print(f"  {pid:<26} {port:<7} {icon} {status:<8} {cwd}{marker}")

    print(f"\nTotal: {len(registry)} project(s)")


def cmd_project_stop(name):
    """Stop a specific project's browser instance."""
    registry = _load_registry()
    target_id = None
    for pid, info in registry.items():
        if name in pid or name in info.get("cwd", ""):
            target_id = pid
            break

    if not target_id:
        print(f"Project not found: {name}", file=sys.stderr)
        sys.exit(1)

    info = registry[target_id]
    port = info.get("port")
    if port and not _is_port_free(port):
        _stop_browser_on_port(port)
        print(f"Stopped: {target_id} (port {port})")
    else:
        print(f"Project already stopped: {target_id}")

    info["status"] = "stopped"
    info["pid"] = None
    _save_registry(registry)


def cmd_stop_all():
    """Stop all active cdpilot browser instances."""
    registry = _cleanup_registry()
    stopped = 0
    for pid, info in registry.items():
        port = info.get("port")
        if port and info.get("status") == "running" and not _is_port_free(port):
            _stop_browser_on_port(port)
            info["status"] = "stopped"
            info["pid"] = None
            stopped += 1
            print(f"  Stopped: {pid} (port {port})")
    _save_registry(registry)
    if stopped:
        print(f"\n{stopped} instance(s) stopped.")
    else:
        print("No active instances.")


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


async def cmd_describe():
    """Full page description for AI agents — structured data + screenshot fallback.

    Outputs URL/title, accessibility snapshot, screenshot path, and text content.
    AI agents can use the a11y snapshot for cheap navigation; fall back to the
    screenshot with a vision model when the snapshot is insufficient (canvas, WebGL).
    """
    global _A11Y_REF_MAP
    _A11Y_REF_MAP = {}
    ws_url, page = get_page_ws()

    print("=== Page Description ===")
    print(f"URL: {page.get('url', 'N/A')}")
    print(f"Title: {page.get('title', 'N/A')}")
    print()

    # ── Accessibility Snapshot ──────────────────────────────────────────────
    print("=== Accessibility Snapshot ===")

    ROLE_NORMALIZE = {
        "textField": "textbox",
        "comboBox": "combobox",
        "checkBox": "checkbox",
        "radioButton": "radio",
    }

    SKIP_ROLES = {
        "none", "presentation", "generic", "LineBreak", "InlineTextBox",
        "ignored", "unknown"
    }

    INTERACTIVE_ROLES = {
        "button", "link", "textbox", "checkbox", "radio", "combobox", "listbox",
        "menuitem", "menuitemcheckbox", "menuitemradio", "option", "spinbutton",
        "slider", "switch", "tab", "treeitem"
    }

    STRUCTURAL_ROLES = {
        "heading", "img", "navigation", "menu", "list", "listitem", "table",
        "grid", "row", "cell", "columnheader", "rowheader", "dialog", "alert",
        "main", "banner", "contentinfo", "region", "figure", "article", "section"
    }

    def _get_prop(node, prop_name):
        for p in node.get("properties", []):
            if p.get("name") == prop_name:
                return p.get("value", {}).get("value", "")
        return ""

    await cdp_send(ws_url, [(0, "Accessibility.enable", {})])
    res = await cdp_send(ws_url, [(1, "Accessibility.getFullAXTree", {})])
    nodes = res.get(1, {}).get("nodes", [])

    if not nodes:
        print("Could not get accessibility tree.", file=sys.stderr)

    ref_count = 0
    interactive_count = 0
    output_lines = []

    for node in nodes:
        backend_node_id = node.get("backendDOMNodeId") or node.get("backendNodeId")
        role = node.get("role", {}).get("value")
        name = node.get("name", {}).get("value")
        description = node.get("description", {}).get("value")
        ignored = node.get("ignored", False)

        if ignored:
            continue
        if not role or role in SKIP_ROLES:
            continue
        if not backend_node_id:
            continue
        if not name and not description and role in {"staticText", "text", "paragraph"}:
            continue

        normalized = ROLE_NORMALIZE.get(role, role)

        if normalized == "heading":
            level = _get_prop(node, "level")
            if level:
                normalized = f"heading/{level}"

        base_role = normalized.split("/")[0]
        is_interactive = base_role in INTERACTIVE_ROLES
        is_structural = base_role in STRUCTURAL_ROLES

        if not (is_interactive or (is_structural and (name or description))):
            continue

        ref_count += 1
        _A11Y_REF_MAP[ref_count] = backend_node_id

        if is_interactive:
            interactive_count += 1

        display_name = name or description or ""
        attrs = []

        if base_role == "link":
            href = _get_prop(node, "url")
            if href:
                attrs.append(f"href={href}")

        if _get_prop(node, "disabled") == "true":
            attrs.append("disabled")

        if _get_prop(node, "required") == "true":
            attrs.append("required")

        if base_role in {"textbox", "combobox"}:
            val = _get_prop(node, "value")
            if val:
                attrs.append(f"value={val!r}")
            ph = _get_prop(node, "placeholder")
            if ph:
                attrs.append(f"placeholder={ph!r}")

        if base_role in {"checkbox", "radio"}:
            if _get_prop(node, "checked") == "true":
                attrs.append("checked")

        if _get_prop(node, "expanded") == "true":
            attrs.append("expanded")

        attr_str = (" " + " ".join(attrs)) if attrs else ""
        output_lines.append(f"@{ref_count} [{normalized}] \"{display_name}\"{attr_str}")

    _save_a11y_refs(_A11Y_REF_MAP)

    for line in output_lines:
        print(line)
    print(f"\n[{interactive_count} interactive, {ref_count} total shown]")
    print()

    # ── Screenshot ─────────────────────────────────────────────────────────
    print("=== Screenshot ===")
    ts = int(time.time())
    shot_path = f"{SCREENSHOT_DIR}/cdpilot-describe-{ts}.png"
    shot_res = await cdp_send(ws_url, [(2, "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})])
    shot_data = shot_res.get(2, {}).get("data")
    if shot_data:
        with open(shot_path, "wb") as f:
            f.write(base64.b64decode(shot_data))
        print(f"Saved: {shot_path}")
    else:
        print("Could not capture screenshot.", file=sys.stderr)
    print()

    # ── Text Content ────────────────────────────────────────────────────────
    print("=== Page Content (first 2000 chars) ===")
    eval_res = await cdp_send(ws_url, [(3, "Runtime.evaluate", {
        "expression": "document.body ? document.body.innerText : ''",
        "returnByValue": True
    })])
    page_text = eval_res.get(3, {}).get("result", {}).get("value", "")
    print(page_text[:2000])


# ─── Data Extraction & Observation Commands ───

async def cmd_extract(selector, output_format="text"):
    """Extract structured data from elements matching selector.

    Returns text content, attributes, or full JSON structure.
    No LLM required — pure DOM extraction.

    Usage:
        cdpilot extract "table tr"              → text rows
        cdpilot extract ".product" --json        → full JSON (tag, text, attrs, children)
        cdpilot extract "a" --attrs=href,title   → specific attributes
        cdpilot extract "ul li" --list           → clean list output
    """
    ws_url, _ = get_page_ws()
    safe_sel = json.dumps(selector)

    if output_format == "json":
        js = f"""
        (function() {{
          var els = document.querySelectorAll({safe_sel});
          if (!els.length) return JSON.stringify([]);
          return JSON.stringify(Array.from(els).slice(0, 100).map(function(el) {{
            var attrs = {{}};
            for (var i = 0; i < el.attributes.length; i++) {{
              attrs[el.attributes[i].name] = el.attributes[i].value;
            }}
            return {{
              tag: el.tagName.toLowerCase(),
              text: (el.textContent || '').trim().substring(0, 500),
              attrs: attrs,
              value: el.value || null,
              href: el.href || null,
              src: el.src || null
            }};
          }}));
        }})()
        """
    elif output_format.startswith("attrs="):
        attr_names = output_format.split("=", 1)[1].split(",")
        attrs_js = ",".join(f'"{a}": el.getAttribute("{a}")' for a in attr_names)
        js = f"""
        (function() {{
          var els = document.querySelectorAll({safe_sel});
          if (!els.length) return JSON.stringify([]);
          return JSON.stringify(Array.from(els).slice(0, 100).map(function(el) {{
            return {{ {attrs_js} }};
          }}));
        }})()
        """
    elif output_format == "list":
        js = f"""
        (function() {{
          var els = document.querySelectorAll({safe_sel});
          if (!els.length) return '';
          return Array.from(els).slice(0, 200).map(function(el, i) {{
            return (i + 1) + '. ' + (el.textContent || '').trim().substring(0, 200);
          }}).join('\\n');
        }})()
        """
    else:
        # Default: text content, one per line
        js = f"""
        (function() {{
          var els = document.querySelectorAll({safe_sel});
          if (!els.length) return '';
          return Array.from(els).slice(0, 200).map(function(el) {{
            return (el.textContent || '').trim().substring(0, 300);
          }}).filter(function(t) {{ return t; }}).join('\\n');
        }})()
        """

    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "")
    if not result:
        print(f"No elements found: {selector}", file=sys.stderr)
        return
    if output_format in ("json",) or output_format.startswith("attrs="):
        # Pretty print JSON
        try:
            parsed = json.loads(result)
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        except (json.JSONDecodeError, TypeError):
            print(result)
    else:
        print(result)


async def cmd_observe():
    """List all interactive elements on the page with actions.

    Like Stagehand's observe() but deterministic — no LLM needed.
    Shows what you CAN DO on the current page.
    """
    ws_url, _ = get_page_ws()
    js = """
    (function() {
      var results = [];
      var els = document.querySelectorAll(
        'a, button, input, textarea, select, [role=button], [role=link], ' +
        '[role=tab], [role=menuitem], [role=checkbox], [role=radio], ' +
        '[onclick], [tabindex]:not([tabindex="-1"])'
      );
      var seen = new Set();
      Array.from(els).forEach(function(el, i) {
        if (i >= 50) return;
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        var style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return;

        var tag = el.tagName.toLowerCase();
        var type = el.type || '';
        var role = el.getAttribute('role') || '';
        var text = (el.textContent || el.value || el.placeholder || '').trim().substring(0, 60);
        var href = el.href || '';
        var name = el.name || el.id || '';

        // Determine action
        var action = 'click';
        if (tag === 'input' || tag === 'textarea') {
          if (type === 'checkbox' || type === 'radio') action = 'toggle';
          else if (type === 'submit') action = 'submit';
          else if (type === 'file') action = 'upload';
          else action = 'fill';
        } else if (tag === 'select') {
          action = 'select';
        } else if (tag === 'a') {
          action = 'navigate';
        }

        // Build selector
        var sel = '';
        if (el.id) sel = '#' + el.id;
        else if (name) sel = tag + '[name=' + JSON.stringify(name) + ']';
        else if (type) sel = tag + '[type=' + type + ']';
        else sel = tag;

        var key = action + ':' + sel + ':' + text;
        if (seen.has(key)) return;
        seen.add(key);

        var line = action.toUpperCase() + '  ' + sel;
        if (text) line += '  "' + text + '"';
        if (href && action === 'navigate') line += '  → ' + href.substring(0, 80);
        results.push(line);
      });
      return results.join('\\n') || 'No interactive elements found';
    })()
    """
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "No interactive elements found")
    print(f"=== What you can do on this page ===\n")
    print(result)


async def cmd_run_script(script_path):
    """Run a .cdp script file — sequential commands, one per line.

    Script format (plain text):
        go https://example.com
        wait-for h1
        assert h1 "Example Domain"
        click a
        shot /tmp/result.png

    Lines starting with # are comments. Empty lines are skipped.
    """
    if not os.path.exists(script_path):
        print(f"Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    with open(script_path) as f:
        lines = f.readlines()

    import shlex
    passed = 0
    failed = 0
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        cmd_name = parts[0]
        cmd_args = parts[1:]

        print(f"[{line_num}] {line}")
        try:
            result = subprocess.run(
                [sys.executable, __file__] + parts,
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "CDPILOT_MCP_SESSION": "1"}
            )
            output = result.stdout.strip()
            if output:
                for out_line in output.split("\n"):
                    print(f"     {out_line}")
            if result.returncode != 0:
                err = result.stderr.strip()
                if err:
                    print(f"     ERROR: {err}")
                failed += 1
            else:
                passed += 1
        except subprocess.TimeoutExpired:
            print(f"     TIMEOUT")
            failed += 1

    print(f"\n{'─' * 40}")
    print(f"Script: {script_path}")
    print(f"Result: {passed} passed, {failed} failed, {passed + failed} total")


# ─── Testing Commands ───

async def cmd_assert(selector, expected_text=None, check_visible=True):
    """Assert element exists, optionally check text content and visibility."""
    ws_url, _ = get_page_ws()
    visible_check = ""
    if check_visible:
        visible_check = """
        var rect = el.getBoundingClientRect();
        var style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' ||
            style.opacity === '0' || (rect.width === 0 && rect.height === 0)) {
          return 'FAIL: Element found but not visible: ' + sel;
        }"""
    text_check = ""
    if expected_text:
        safe_text = json.dumps(expected_text)
        text_check = f"""
        var actual = el.textContent || el.value || '';
        if (actual.indexOf({safe_text}) === -1) {{
          return 'FAIL: Expected text ' + {safe_text} + ' not found in: ' + actual.substring(0, 100);
        }}"""
    safe_sel = json.dumps(selector)
    js = f"""
    (function() {{
      var sel = {safe_sel};
      var el = document.querySelector(sel);
      if (!el) return 'FAIL: Element not found: ' + sel;
      {visible_check}
      {text_check}
      var tag = el.tagName.toLowerCase();
      var txt = (el.textContent || '').substring(0, 60).trim();
      return 'PASS: ' + tag + (txt ? ' "' + txt + '"' : '') + ' (' + sel + ')';
    }})()
    """
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "ERROR")
    print(result)


async def cmd_wait_for(selector, timeout_ms=5000):
    """Wait for element to appear in DOM, up to timeout."""
    ws_url, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    js = f"""
    (function() {{
      return new Promise(function(resolve) {{
        var sel = {safe_sel};
        var el = document.querySelector(sel);
        if (el) return resolve('FOUND: ' + el.tagName + ' "' + (el.textContent || '').substring(0, 60).trim() + '"');
        var obs = new MutationObserver(function() {{
          var el = document.querySelector(sel);
          if (el) {{ obs.disconnect(); resolve('FOUND: ' + el.tagName + ' "' + (el.textContent || '').substring(0, 60).trim() + '"'); }}
        }});
        obs.observe(document.body, {{childList: true, subtree: true}});
        setTimeout(function() {{ obs.disconnect(); resolve('TIMEOUT: ' + sel + ' not found after {timeout_ms}ms'); }}, {timeout_ms});
      }});
    }})()
    """
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})], timeout=max(15, timeout_ms // 1000 + 5))
    result = r.get(1, {}).get("result", {}).get("value", "ERROR")
    print(result)


async def cmd_check(checks_json=None):
    """Run batch assertions. Input: JSON array of {selector, text?} objects."""
    ws_url, _ = get_page_ws()
    if checks_json is None:
        raw = sys.stdin.read().strip()
    else:
        raw = checks_json
    try:
        checks = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        print("Error: Invalid JSON. Expected: [{\"selector\": \"...\", \"text\": \"...\"}]")
        sys.exit(1)

    passed = 0
    failed = 0
    results = []
    for i, check in enumerate(checks, 1):
        sel = check.get("selector", "")
        text = check.get("text")
        safe_sel = json.dumps(sel)
        text_check = ""
        if text:
            safe_text = json.dumps(text)
            text_check = f"""
            var actual = el.textContent || el.value || '';
            if (actual.indexOf({safe_text}) === -1) {{
              return 'FAIL: Expected ' + {safe_text} + ' in: ' + actual.substring(0, 80);
            }}"""
        js = f"""
        (function() {{
          var el = document.querySelector({safe_sel});
          if (!el) return 'FAIL: Not found: ' + {safe_sel};
          {text_check}
          return 'PASS: ' + el.tagName + ' (' + {safe_sel} + ')';
        }})()
        """
        r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
        result = r.get(1, {}).get("result", {}).get("value", "ERROR")
        if result.startswith("PASS"):
            passed += 1
        else:
            failed += 1
        results.append(f"  {i}. {result}")

    print(f"Test Report: {passed} passed, {failed} failed")
    print("─" * 40)
    for line in results:
        print(line)


async def cmd_assert_url(expected_url):
    """Assert current page URL contains the expected substring."""
    ws_url, _ = get_page_ws()
    safe_expected = json.dumps(expected_url)
    js = f"""(function() {{
      var href = window.location.href;
      var expected = {safe_expected};
      if (href.indexOf(expected) !== -1) return 'PASS: URL ' + href + ' contains \"' + expected + '\"';
      return 'FAIL: URL ' + href + ' does not contain \"' + expected + '\"';
    }})()"""
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "ERROR")
    print(result)


async def cmd_assert_title(expected_title):
    """Assert page title contains the expected substring."""
    ws_url, _ = get_page_ws()
    safe_expected = json.dumps(expected_title)
    js = f"""(function() {{
      var title = document.title;
      var expected = {safe_expected};
      if (title.indexOf(expected) !== -1) return 'PASS: Title \"' + title + '\" contains \"' + expected + '\"';
      return 'FAIL: Title \"' + title + '\" does not contain \"' + expected + '\"';
    }})()"""
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "ERROR")
    print(result)


async def cmd_assert_count(selector, expected_count):
    """Assert the number of elements matching a CSS selector equals expected_count."""
    ws_url, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    exp = int(expected_count)
    js = f"""(function() {{
      var count = document.querySelectorAll({safe_sel}).length;
      var exp = {exp};
      if (count === exp) return 'PASS: Found ' + count + ' element(s) matching {safe_sel} (expected ' + exp + ')';
      return 'FAIL: Expected ' + exp + ' \"{selector}\" but found ' + count;
    }})()"""
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "ERROR")
    print(result)


async def cmd_assert_value(selector, expected_value):
    """Assert an input/textarea/select element's value equals expected_value."""
    ws_url, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    safe_expected = json.dumps(expected_value)
    js = f"""(function() {{
      var el = document.querySelector({safe_sel});
      if (!el) return 'FAIL: Element not found: ' + {safe_sel};
      var val = el.value;
      var expected = {safe_expected};
      if (val === expected) return 'PASS: Value matches \"' + expected + '\"';
      return 'FAIL: Expected value \"' + expected + '\" but got \"' + val + '\"';
    }})()"""
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "ERROR")
    print(result)


async def cmd_assert_attr(selector, attr, expected):
    """Assert element attribute value contains expected substring."""
    ws_url, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    safe_attr = json.dumps(attr)
    safe_expected = json.dumps(expected)
    js = f"""(function() {{
      var el = document.querySelector({safe_sel});
      if (!el) return 'FAIL: Element not found: ' + {safe_sel};
      var val = el.getAttribute({safe_attr}) || '';
      var expected = {safe_expected};
      if (val.indexOf(expected) !== -1) return 'PASS: ' + {safe_sel} + '[' + {safe_attr} + '] = \"' + val + '\"';
      return 'FAIL: Expected ' + {safe_sel} + '[' + {safe_attr} + '] to contain \"' + expected + '\" but got \"' + val + '\"';
    }})()"""
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "ERROR")
    print(result)


async def cmd_assert_visible(selector, should_be_visible=True):
    """Assert element is visible (or hidden). should_be_visible=True checks for visible, False for hidden."""
    ws_url, _ = get_page_ws()
    safe_sel = json.dumps(selector)
    expect_label = "visible" if should_be_visible else "hidden"
    opposite_label = "hidden" if should_be_visible else "visible"
    js = f"""(function() {{
      var el = document.querySelector({safe_sel});
      if (!el) return 'FAIL: Element not found: ' + {safe_sel};
      var style = window.getComputedStyle(el);
      var rect = el.getBoundingClientRect();
      var isVisible = (
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        style.opacity !== '0' &&
        (rect.width > 0 || rect.height > 0)
      );
      var expectVisible = {str(should_be_visible).lower()};
      if (isVisible === expectVisible) return 'PASS: ' + {safe_sel} + ' is {expect_label}';
      return 'FAIL: ' + {safe_sel} + ' expected {expect_label} but is {opposite_label}';
    }})()"""
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    result = r.get(1, {}).get("result", {}).get("value", "ERROR")
    print(result)


async def cmd_screenshot_diff(path1, path2):
    """Compare two screenshot files byte-by-byte. No CDP required."""
    for path in (path1, path2):
        if not os.path.exists(path):
            print(f"ERROR: File not found: {path}")
            return
    size1 = os.path.getsize(path1)
    size2 = os.path.getsize(path2)
    with open(path1, "rb") as f1, open(path2, "rb") as f2:
        data1 = f1.read()
        data2 = f2.read()
    if data1 == data2:
        print("MATCH: Files are identical")
    else:
        kb1 = size1 / 1024
        kb2 = size2 / 1024
        print(f"DIFF: Files differ ({os.path.basename(path1)}: {kb1:.1f}KB, {os.path.basename(path2)}: {kb2:.1f}KB)")


async def cmd_a11y_snapshot():
    """Output a compact accessibility snapshot for AI agent navigation.

    Each line: @ref [role] "name" attributes...
    Use 'click-ref @N' to click an element by its reference number.
    """
    global _A11Y_REF_MAP
    _A11Y_REF_MAP = {}
    ws_url, _ = get_page_ws()
    await cdp_send(ws_url, [(0, "Accessibility.enable", {})])
    res = await cdp_send(ws_url, [(1, "Accessibility.getFullAXTree", {})])
    nodes = res.get(1, {}).get("nodes", [])
    if not nodes:
        print("Could not get accessibility tree.", file=sys.stderr)
        sys.exit(1)

    ROLE_NORMALIZE = {
        "textField": "textbox",
        "comboBox": "combobox",
        "checkBox": "checkbox",
        "radioButton": "radio",
    }

    SKIP_ROLES = {
        "none", "presentation", "generic", "LineBreak", "InlineTextBox",
        "ignored", "unknown"
    }

    INTERACTIVE_ROLES = {
        "button", "link", "textbox", "checkbox", "radio", "combobox", "listbox",
        "menuitem", "menuitemcheckbox", "menuitemradio", "option", "spinbutton",
        "slider", "switch", "tab", "treeitem"
    }

    STRUCTURAL_ROLES = {
        "heading", "img", "navigation", "menu", "list", "listitem", "table",
        "grid", "row", "cell", "columnheader", "rowheader", "dialog", "alert",
        "main", "banner", "contentinfo", "region", "figure", "article", "section"
    }

    def _get_prop(node, prop_name):
        for p in node.get("properties", []):
            if p.get("name") == prop_name:
                return p.get("value", {}).get("value", "")
        return ""

    ref_count = 0
    interactive_count = 0
    output_lines = []

    for node in nodes:
        backend_node_id = node.get("backendDOMNodeId") or node.get("backendNodeId")
        role = node.get("role", {}).get("value")
        name = node.get("name", {}).get("value")
        description = node.get("description", {}).get("value")
        ignored = node.get("ignored", False)

        if ignored:
            continue
        if not role or role in SKIP_ROLES:
            continue
        if not backend_node_id:
            continue
        if not name and not description and role in {"staticText", "text", "paragraph"}:
            continue

        normalized = ROLE_NORMALIZE.get(role, role)

        # heading/N format
        if normalized == "heading":
            level = _get_prop(node, "level")
            if level:
                normalized = f"heading/{level}"

        # Determine inclusion
        base_role = normalized.split("/")[0]
        is_interactive = base_role in INTERACTIVE_ROLES
        is_structural = base_role in STRUCTURAL_ROLES
        if not (is_interactive or (is_structural and (name or description))):
            continue

        display_name = name or description or ""

        attrs = []

        if base_role == "link":
            href = _get_prop(node, "url")
            if href:
                attrs.append(f"href={href}")

        if _get_prop(node, "disabled") == "true":
            attrs.append("disabled")

        if _get_prop(node, "required") == "true":
            attrs.append("required")

        if base_role in {"textbox", "combobox"}:
            val = _get_prop(node, "value")
            if val:
                attrs.append(f"value={val!r}")
            ph = _get_prop(node, "placeholder")
            if ph:
                attrs.append(f"placeholder={ph!r}")

        if base_role in {"checkbox", "radio"}:
            if _get_prop(node, "checked") == "true":
                attrs.append("checked")

        if _get_prop(node, "expanded") == "true":
            attrs.append("expanded")

        ref_count += 1
        _A11Y_REF_MAP[ref_count] = backend_node_id

        if is_interactive:
            interactive_count += 1

        attr_str = (" " + " ".join(attrs)) if attrs else ""
        line = f"@{ref_count} [{normalized}] \"{display_name}\"{attr_str}"
        output_lines.append(line)

    _save_a11y_refs(_A11Y_REF_MAP)

    for line in output_lines:
        print(line)
    print(f"\n[{interactive_count} interactive, {ref_count} total shown]")


async def cmd_click_ref(ref_str):
    """Click an element by its @N reference from the last a11y-snapshot."""
    ws_url, _ = get_page_ws()

    try:
        ref_num = int(ref_str.lstrip("@"))
    except ValueError:
        print(f"Error: Invalid reference '{ref_str}'. Expected @N (e.g. @3).", file=sys.stderr)
        sys.exit(1)

    ref_map = _A11Y_REF_MAP or _load_a11y_refs()
    backend_node_id = ref_map.get(ref_num)
    if not backend_node_id:
        print(f"Error: Reference '@{ref_num}' not found. Run 'a11y-snapshot' first.", file=sys.stderr)
        sys.exit(1)

    # Get element box model via backendNodeId directly
    await cdp_send(ws_url, [(0, "DOM.enable", {})])
    res1 = await cdp_send(ws_url, [(1, "DOM.getBoxModel", {"backendNodeId": backend_node_id})])
    model = res1.get(1, {}).get("model")
    if not model:
        # Fallback: resolve to objectId and use JS
        res_r = await cdp_send(ws_url, [(10, "DOM.resolveNode", {"backendNodeId": backend_node_id})])
        oid = res_r.get(10, {}).get("object", {}).get("objectId")
        if oid:
            res_js = await cdp_send(ws_url, [(11, "Runtime.callFunctionOn", {
                "functionDeclaration": "function(){var r=this.getBoundingClientRect();return{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};}",
                "objectId": oid, "returnByValue": True,
            })])
            val = res_js.get(11, {}).get("result", {}).get("value")
            if val and "x" in val:
                model = None  # skip box model path
                x, y = val["x"], val["y"]
    if model:
        # content quad: [x1,y1, x2,y2, x3,y3, x4,y4]
        content = model.get("content", model.get("border", []))
        if len(content) >= 8:
            x = int((content[0] + content[2] + content[4] + content[6]) / 4)
            y = int((content[1] + content[3] + content[5] + content[7]) / 4)
            val = {"x": x, "y": y}
        else:
            val = None
    elif not model and 'x' not in dir():
        val = None

    if not val or "x" not in val:
        print(f"Error: Could not get coordinates for @{ref_num}.", file=sys.stderr)
        sys.exit(1)

    x, y = val["x"], val["y"]
    await _vfx_ripple(ws_url, x, y)
    await cdp_send(ws_url, [
        (3, "Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1
        }),
        (4, "Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1
        }),
    ])
    print(f"Clicked @{ref_num} (backendNodeId={backend_node_id}): ({x}, {y})")


# ─── 3. Advanced Input Commands ───

async def cmd_hover(selector):
    """Move the mouse cursor to the specified element."""
    ws_url, _ = get_page_ws()
    x, y = await _get_element_center(ws_url, selector)
    await _vfx_move_cursor(ws_url, x, y)
    await cdp_send(ws_url, [(1, "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": x, "y": y, "button": "none", "modifiers": 0})])
    print(f"Hover: {selector} ({x}, {y})")


async def cmd_dblclick(selector):
    """Double-click the specified element."""
    ws_url, _ = get_page_ws()
    x, y = await _get_element_center(ws_url, selector)
    await _vfx_ripple(ws_url, x, y)
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
    await _vfx_ripple(ws_url, x, y)
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
    await _vfx_ripple(ws_url, fx, fy)

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
            await _vfx_move_cursor(ws_url, ix, iy)
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

    await _vfx_keystroke(ws_url, combo.upper())
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
            {"name": "browser_navigate", "description": "Navigate the browser to a URL and return the page text content. Use this to open websites, follow links, or load web applications. Waits for page load before returning. Returns first 10000 chars of visible text.",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "Full URL to navigate to (must include https://)"}}, "required": ["url"]}},
            {"name": "browser_screenshot", "description": "Capture a screenshot of the current browser viewport. Supports element-level cropping to save tokens (capture only a specific element instead of full page). Use JPEG format with quality parameter for smaller files (~5x smaller than PNG). Prefer element cropping + JPEG for token-efficient AI workflows.",
             "inputSchema": {"type": "object", "properties": {"filename": {"type": "string", "description": "Output file path (e.g. /tmp/screenshot.png). Extension determines format: .png, .jpg, .webp", "default": "screenshot.png"}, "element": {"type": "string", "description": "CSS selector to capture only that element (crops to bounding box). Saves ~3-7x tokens vs full page."}, "quality": {"type": "number", "description": "JPEG quality 1-100 (only for .jpg files). Lower = smaller file = fewer tokens. Default: 80"}}}},
            {"name": "browser_click", "description": "Click an element on the page identified by CSS selector. Auto-waits up to 5 seconds for the element to appear (MutationObserver). Scrolls the element into view before clicking. Returns the tag name and text of the clicked element.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector for the element to click (e.g. '#submit-btn', '.nav a', 'button[type=submit]')"}}, "required": ["selector"]}},
            {"name": "browser_type", "description": "Type text into an input or textarea element. Uses React-compatible value setting (native setter + input/change events). Auto-waits up to 5 seconds for the element. Use browser_fill as an alias.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector for the input element"}, "text": {"type": "string", "description": "Text value to type into the element"}}, "required": ["selector", "text"]}},
            {"name": "browser_content", "description": "Get the visible text content of the current page (document.body.innerText). Returns up to 10000 characters. Use this to read page content without HTML markup. Prefer browser_a11y for structured navigation data.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_html", "description": "Get the full HTML source of the current page (document.documentElement.outerHTML). Returns up to 50000 characters. Use sparingly — prefer browser_content or browser_a11y for most tasks as they return smaller, more useful data.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_eval", "description": "Execute arbitrary JavaScript code in the browser page context and return the result. Use for custom DOM queries, data extraction, or page manipulation that other tools don't cover. Expression is evaluated via Runtime.evaluate.",
             "inputSchema": {"type": "object", "properties": {"expression": {"type": "string", "description": "JavaScript expression to evaluate (e.g. 'document.title', 'document.querySelectorAll(\"a\").length')"}}, "required": ["expression"]}},
            {"name": "browser_tabs", "description": "List all open browser tabs with their IDs, URLs, and titles. Use this to see what pages are open and get tab IDs for switching between them with other navigation commands.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_console", "description": "Navigate to a URL and capture all browser console output (log, warn, error, info) and uncaught exceptions. Use for debugging JavaScript errors, monitoring API calls logged to console, or verifying application behavior.",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate to while capturing console output"}}}},
            {"name": "browser_network", "description": "Navigate to a URL and monitor all network requests/responses. Returns each request's URL, HTTP status code, and MIME type. Use for debugging API calls, checking resource loading, or verifying network behavior.",
             "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate to while monitoring network traffic"}}}},
            {"name": "browser_a11y", "description": "Get the accessibility tree of the current page as structured data. Returns interactive elements with @N references that can be used with browser_click. This is the PREFERRED way to understand page structure — uses ~500 tokens vs ~250K for screenshots. Use 'summary' mode for a compact view.",
             "inputSchema": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["full", "summary"], "description": "Output detail level: 'full' for complete tree, 'summary' for interactive elements only", "default": "full"}}}},
            {"name": "browser_fill", "description": "Set an input element's value using React-compatible method (native descriptor setter + input/change events). Auto-waits up to 5 seconds for the element. Works with regular inputs, textareas, and React controlled components.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector for the input element"}, "value": {"type": "string", "description": "Value to set in the input field"}}, "required": ["selector", "value"]}},
            {"name": "browser_launch", "description": "Launch an isolated browser instance with Chrome DevTools Protocol enabled. Uses existing Brave/Chrome/Chromium installation — no browser download needed. Creates an isolated profile directory so your personal browser data is never touched.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_close", "description": "Close the currently active browser tab. Use this to clean up after automation tasks or to close unwanted popups/tabs that were opened during navigation.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_extract", "description": "Extract structured data from elements matching a CSS selector. No LLM needed — pure DOM extraction. Returns text (default), JSON (with tag, text, attrs, href, src), specific attributes, or clean list. Use for scraping tables, lists, links, form values. Limit: 100 elements for JSON, 200 for text.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector to match elements (e.g. 'table tr', '.product', 'a')"}, "format": {"type": "string", "enum": ["text", "json", "list"], "description": "Output format: 'text' (one per line), 'json' (full structure with attrs), 'list' (numbered)", "default": "text"}}, "required": ["selector"]}},
            {"name": "browser_observe", "description": "List all interactive elements on the current page with their available actions (CLICK, FILL, NAVIGATE, TOGGLE, SELECT, SUBMIT, UPLOAD). Like Stagehand observe() but deterministic — no LLM needed. Shows what you CAN DO on the page. Use this to understand page structure before acting.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_describe", "description": "Get a comprehensive page description combining three data sources: (1) accessibility tree with @N references for interactive elements, (2) a PNG screenshot saved to disk, and (3) visible text content. Use this when browser_a11y alone is insufficient — for canvas/WebGL content, visual verification, or complex dynamic UIs. This is the vision fallback tool.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_assert", "description": "Assert that an element matching the CSS selector exists and optionally contains expected text. Returns PASS or FAIL with details. Use this for automated testing — verify page state after navigation or interaction. Checks visibility by default.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector to check for existence"}, "text": {"type": "string", "description": "Optional: expected text content (substring match)"}, "visible": {"type": "boolean", "description": "Check element is visible (not hidden/zero-size)", "default": True}}, "required": ["selector"]}},
            {"name": "browser_wait_for", "description": "Wait for an element matching the CSS selector to appear in the DOM, up to the specified timeout. Uses MutationObserver for efficient waiting. Returns the element's tag and text when found, or TIMEOUT if not found. Use before interactions with dynamically loaded content.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector to wait for"}, "timeout": {"type": "number", "description": "Maximum wait time in milliseconds", "default": 5000}}, "required": ["selector"]}},
            {"name": "browser_check", "description": "Run a batch of assertions on the current page and return a test report. Each check verifies element existence and optional text content. Returns a summary with PASS/FAIL count. Use this for comprehensive page validation after a series of actions.",
             "inputSchema": {"type": "object", "properties": {"checks": {"type": "array", "description": "Array of checks, each with 'selector' (required) and 'text' (optional)", "items": {"type": "object", "properties": {"selector": {"type": "string"}, "text": {"type": "string"}}, "required": ["selector"]}}}, "required": ["checks"]}},
            {"name": "browser_assert_url", "description": "Assert the current page URL contains the expected substring. Returns PASS with the full URL or FAIL. Use this after navigation to verify you landed on the correct page.",
             "inputSchema": {"type": "object", "properties": {"expected_url": {"type": "string", "description": "Expected substring to find in the current URL (e.g. 'example.com', '/dashboard', '?tab=settings')"}}, "required": ["expected_url"]}},
            {"name": "browser_assert_title", "description": "Assert the current page title contains the expected substring. Returns PASS with full title or FAIL. Useful for verifying page identity without relying on URL.",
             "inputSchema": {"type": "object", "properties": {"expected_title": {"type": "string", "description": "Expected substring to find in the page title (e.g. 'Dashboard', 'Login')"}}, "required": ["expected_title"]}},
            {"name": "browser_assert_count", "description": "Assert the number of elements matching a CSS selector equals an expected count. Returns PASS with count or FAIL with actual vs expected. Use this to verify list items, table rows, search results, or repeated components.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector to count matching elements"}, "expected_count": {"type": "integer", "description": "Expected number of matching elements"}}, "required": ["selector", "expected_count"]}},
            {"name": "browser_assert_value", "description": "Assert an input, textarea, or select element's current value equals the expected string. Returns PASS or FAIL with actual value. Use this to verify form field state after filling or after page load.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector for the input/textarea/select element"}, "expected_value": {"type": "string", "description": "Expected exact value of the element"}}, "required": ["selector", "expected_value"]}},
            {"name": "browser_assert_attr", "description": "Assert an element's HTML attribute contains the expected substring. Returns PASS with actual value or FAIL. Use this to verify href, src, data-*, aria-* and other attributes without reading full page HTML.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector for the element"}, "attr": {"type": "string", "description": "Attribute name (e.g. 'href', 'src', 'data-id', 'aria-label')"}, "expected": {"type": "string", "description": "Expected substring in the attribute value"}}, "required": ["selector", "attr", "expected"]}},
            {"name": "browser_assert_visible", "description": "Assert an element is visible on the page (not hidden by CSS). Checks display, visibility, opacity and bounding rect. Returns PASS or FAIL. Use this to verify modals opened, elements shown after interaction, or content loaded.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector for the element to check for visibility"}}, "required": ["selector"]}},
            {"name": "browser_assert_hidden", "description": "Assert an element exists but is hidden (display:none, visibility:hidden, opacity:0, or zero size). Returns PASS or FAIL. Use this to verify modals closed, tooltips dismissed, or conditional sections hidden.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector for the element expected to be hidden"}}, "required": ["selector"]}},
            {"name": "browser_screenshot_diff", "description": "Compare two screenshot PNG files byte-by-byte. Returns MATCH if files are identical or DIFF with file sizes if different. Use this for visual regression testing — take a baseline screenshot, perform actions, take another screenshot, then compare.",
             "inputSchema": {"type": "object", "properties": {"path1": {"type": "string", "description": "Absolute path to the first (baseline) screenshot PNG"}, "path2": {"type": "string", "description": "Absolute path to the second (current) screenshot PNG"}}, "required": ["path1", "path2"]}},
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
            "browser_screenshot": lambda a: ["shot"] + ([self._safe_filename(a["filename"])] if a.get("filename") else []) + ([f"--element={a['element']}"] if a.get("element") else []) + ([f"--quality={a['quality']}"] if a.get("quality") else []),
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
            "browser_extract": lambda a: ["extract", a.get("selector", "")] + ([f"--{a['format']}"] if a.get("format") and a["format"] != "text" else []),
            "browser_observe": lambda a: ["observe"],
            "browser_describe": lambda a: ["describe"],
            "browser_assert": lambda a: ["assert", a.get("selector", "")] + ([a["text"]] if a.get("text") else []),
            "browser_wait_for": lambda a: ["wait-for", a.get("selector", "")] + ([str(a["timeout"])] if a.get("timeout") else []),
            "browser_check": lambda a: ["check", json.dumps(a.get("checks", []))],
            "browser_assert_url": lambda a: ["assert-url", a.get("expected_url", "")],
            "browser_assert_title": lambda a: ["assert-title", a.get("expected_title", "")],
            "browser_assert_count": lambda a: ["assert-count", a.get("selector", ""), str(a.get("expected_count", 0))],
            "browser_assert_value": lambda a: ["assert-value", a.get("selector", ""), a.get("expected_value", "")],
            "browser_assert_attr": lambda a: ["assert-attr", a.get("selector", ""), a.get("attr", ""), a.get("expected", "")],
            "browser_assert_visible": lambda a: ["assert-visible", a.get("selector", "")],
            "browser_assert_hidden": lambda a: ["assert-hidden", a.get("selector", "")],
            "browser_screenshot_diff": lambda a: ["screenshot-diff", a.get("path1", ""), a.get("path2", "")],
        }
        if tool_name not in tool_map:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"}}

        cli_args = [a for a in tool_map[tool_name](args) if a]
        try:
            env = os.environ.copy()
            env["CDPILOT_MCP_SESSION"] = "1"
            result = subprocess.run(
                [sys.executable, __file__] + cli_args,
                capture_output=True, text=True, timeout=30, env=env
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
        'projects': cmd_projects,
        'project-stop': lambda: cmd_project_stop(args[0] if args else ''),
        'stop-all': cmd_stop_all,
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
        "shot": lambda: cmd_shot(
            output=next((a for a in args if not a.startswith("--")), None),
            quality=next((a.split("=")[1] for a in args if a.startswith("--quality=")), None),
            element=next((a.split("=")[1] for a in args if a.startswith("--element=")), None),
            fmt=next((a.split("=")[1] for a in args if a.startswith("--format=")), None),
        ),
        "shot-annotated": lambda: cmd_shot_annotated(args[0] if args else None),
        "batch": cmd_batch,
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
        'a11y-snapshot': cmd_a11y_snapshot,
        'describe': cmd_describe,
        'extract': lambda: (require_args(1, 'extract <selector> [--json|--list|--attrs=href,title]'), None)[1] if not args else cmd_extract(args[0], next((a.lstrip('-') for a in args[1:] if a.startswith('--')), "text")),
        'observe': cmd_observe,
        'run': lambda: (require_args(1, 'run <script.cdp>'), None)[1] if not args else cmd_run_script(args[0]),
        'assert': lambda: (require_args(1, 'assert <selector> [text]'), None)[1] if not args else cmd_assert(args[0], args[1] if len(args) > 1 else None),
        'wait-for': lambda: (require_args(1, 'wait-for <selector> [timeout_ms]'), None)[1] if not args else cmd_wait_for(args[0], int(args[1]) if len(args) > 1 else 5000),
        'check': lambda: cmd_check(args[0] if args else None),
        'assert-url': lambda: (require_args(1, 'assert-url <expected>'), None)[1] if not args else cmd_assert_url(args[0]),
        'assert-title': lambda: (require_args(1, 'assert-title <expected>'), None)[1] if not args else cmd_assert_title(args[0]),
        'assert-count': lambda: (require_args(2, 'assert-count <selector> <n>'), None)[1] if len(args) < 2 else cmd_assert_count(args[0], int(args[1])),
        'assert-value': lambda: (require_args(2, 'assert-value <selector> <value>'), None)[1] if len(args) < 2 else cmd_assert_value(args[0], args[1]),
        'assert-attr': lambda: (require_args(3, 'assert-attr <selector> <attr> <expected>'), None)[1] if len(args) < 3 else cmd_assert_attr(args[0], args[1], args[2]),
        'assert-visible': lambda: (require_args(1, 'assert-visible <selector>'), None)[1] if not args else cmd_assert_visible(args[0], True),
        'assert-hidden': lambda: (require_args(1, 'assert-hidden <selector>'), None)[1] if not args else cmd_assert_visible(args[0], False),
        'screenshot-diff': lambda: (require_args(2, 'screenshot-diff <path1> <path2>'), None)[1] if len(args) < 2 else cmd_screenshot_diff(args[0], args[1]),
        'click-ref': lambda: (require_args(1, 'click-ref <@N>'), None)[1] if not args else cmd_click_ref(args[0]),
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
                       'dialog', 'download', 'throttle', 'permission', 'intercept',
                       'batch', 'screenshot-diff', 'run'}
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

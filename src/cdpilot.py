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

__version__ = "0.8.0"

import asyncio
import atexit
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
import secrets
import glob
import datetime
import concurrent.futures
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
        return int(env_port), env_profile, _get_project_id()

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
# ─── Stealth & CAPTCHA Detection ──────────────────────────────────────────────
# Zero-dependency anti-fingerprinting layer. Patches common automation tells
# (navigator.webdriver, missing chrome.runtime, plugin list, WebGL vendor).
# Runs via Page.addScriptToEvaluateOnNewDocument BEFORE any page script.
# Notes:
#   - Does NOT weaken web security (CSP, CORS, SOP intact).
#   - Idempotent: guarded by window.__cdpilot_stealth flag.
#   - Fails silently per-patch; one failure cannot break the page.
#   - Opt-in via `cdpilot stealth on`. Default OFF for backward compatibility.
#
# THREE-TIER MODEL (crawl4ai-style regular -> stealth -> undetected):
#   - regular     : NO fingerprint patch injected at all. Cleanest, fastest,
#                   relies only on --disable-blink-features=AutomationControlled
#                   set at launch. Lowest entropy -> fewest leaks. Default tier.
#   - stealth     : STEALTH_JS_LIGHT - webdriver + chrome.runtime + permissions
#                   reconcile ONLY. Deliberately OMITS the plugin-array spoof,
#                   which Stealth Bench V1 proved is itself a leak source
#                   (bot.sannysoft.com surfaced garbage plugin filenames like
#                   "rCJMteXy" from the synthetic PluginArray). Light tier is a
#                   strict subset of FULL.
#   - undetected  : STEALTH_JS_FULL - the full body (light subset + plugins +
#                   Worker patch + WebGL vendor + hardwareConcurrency). Highest
#                   plausibility on naive checks but highest entropy; pair with
#                   behavioral entropy/humanize for the hardest targets.
#
# STEALTH_JS retains the FULL body for backward compatibility - every existing
# reference (`cdpilot stealth on`, adaptive escalation) maps to undetected.

# Light tier: the SAFE subset. webdriver + chrome.runtime + permissions only.
# No plugin spoofing (bench leak), no WebGL vendor override, no Worker wrap.
STEALTH_JS_LIGHT = r"""
(function() {
  'use strict';
  if (window.__cdpilot_stealth) return;
  try { Object.defineProperty(window, '__cdpilot_stealth', {value: true, writable: false, configurable: false}); } catch(e) {}

  // 1) navigator.webdriver - only patch if it's actually `true`.
  try {
    var wdValue;
    try { wdValue = navigator.webdriver; } catch (_) {}
    if (wdValue === true) {
      Object.defineProperty(Navigator.prototype, 'webdriver', {
        get: function() { return false; },
        configurable: true
      });
    }
  } catch (e) {}

  // 2) window.chrome - real Chrome exposes chrome.runtime even without extensions
  try {
    if (!window.chrome) {
      window.chrome = {};
    }
    if (!window.chrome.runtime) {
      window.chrome.runtime = {
        OnInstalledReason: {}, OnRestartRequiredReason: {}, PlatformArch: {},
        PlatformNackArch: {}, PlatformOs: {}, RequestUpdateCheckStatus: {}
      };
    }
    if (typeof window.chrome.app === 'undefined') {
      window.chrome.app = { isInstalled: false, InstallState: {}, RunningState: {} };
    }
  } catch (e) {}

  // 3) Permissions.query - reconcile with Notification.permission (classic tell)
  try {
    if (navigator.permissions && navigator.permissions.query) {
      var origQuery = navigator.permissions.query.bind(navigator.permissions);
      navigator.permissions.query = function(p) {
        if (p && p.name === 'notifications') {
          return Promise.resolve({ state: Notification.permission, onchange: null });
        }
        return origQuery(p);
      };
    }
  } catch (e) {}
})();
"""

# Full tier (a.k.a. "undetected"): the complete body. Light subset + plugin
# array + Worker patch + WebGL vendor + hardwareConcurrency. STEALTH_JS is kept
# as an alias of FULL so every legacy reference still resolves.
STEALTH_JS_FULL = r"""
(function() {
  'use strict';
  if (window.__cdpilot_stealth) return;
  try { Object.defineProperty(window, '__cdpilot_stealth', {value: true, writable: false, configurable: false}); } catch(e) {}

  // 1) navigator.webdriver — only patch if it's actually `true`.
  // Vanilla Chrome (no --enable-automation) already returns `false` and the
  // property exists on Navigator.prototype. Replacing the getter when it's
  // already safe creates a worse fingerprint (returning `undefined` instead
  // of `false` is itself a tell). Only mask when CDP/automation flagged it.
  try {
    var wdValue;
    try { wdValue = navigator.webdriver; } catch (_) {}
    if (wdValue === true) {
      Object.defineProperty(Navigator.prototype, 'webdriver', {
        get: function() { return false; },
        configurable: true
      });
    }
  } catch (e) {}

  // 2) window.chrome — real Chrome exposes chrome.runtime even without extensions
  try {
    if (!window.chrome) {
      window.chrome = {};
    }
    if (!window.chrome.runtime) {
      window.chrome.runtime = {
        OnInstalledReason: {}, OnRestartRequiredReason: {}, PlatformArch: {},
        PlatformNackArch: {}, PlatformOs: {}, RequestUpdateCheckStatus: {}
      };
    }
    if (typeof window.chrome.app === 'undefined') {
      window.chrome.app = { isInstalled: false, InstallState: {}, RunningState: {} };
    }
  } catch (e) {}

  // 3) Permissions.query — reconcile with Notification.permission (classic tell)
  try {
    if (navigator.permissions && navigator.permissions.query) {
      var origQuery = navigator.permissions.query.bind(navigator.permissions);
      navigator.permissions.query = function(p) {
        if (p && p.name === 'notifications') {
          return Promise.resolve({ state: Notification.permission, onchange: null });
        }
        return origQuery(p);
      };
    }
  } catch (e) {}

  // 4) navigator.plugins — empty array is a headless tell. Provide standard PDF set.
  // Critical: must be a real PluginArray instance, not vanilla Array, or
  // detection scripts catch it via `navigator.plugins instanceof PluginArray`.
  try {
    var PluginArrayProto = (window.PluginArray && window.PluginArray.prototype) || null;
    var PluginProto = (window.Plugin && window.Plugin.prototype) || null;
    var MimeTypeProto = (window.MimeType && window.MimeType.prototype) || null;

    var makeMime = function(type, suffixes, plugin) {
      var m = Object.create(MimeTypeProto || Object.prototype);
      Object.defineProperties(m, {
        type:        { value: type,        enumerable: true },
        suffixes:    { value: suffixes,    enumerable: true },
        description: { value: '',          enumerable: true },
        enabledPlugin: { value: plugin,    enumerable: true }
      });
      return m;
    };
    var makePlugin = function(name, filename) {
      var p = Object.create(PluginProto || Object.prototype);
      var mime = makeMime('application/pdf', 'pdf', p);
      Object.defineProperties(p, {
        name:        { value: name,        enumerable: true },
        filename:    { value: filename,    enumerable: true },
        description: { value: 'Portable Document Format', enumerable: true },
        length:      { value: 1,           enumerable: true },
        '0':         { value: mime,        enumerable: true }
      });
      p.item = function(i) { return i === 0 ? mime : null; };
      p.namedItem = function(n) { return n === mime.type ? mime : null; };
      return p;
    };
    var pluginNames = [
      ['PDF Viewer', 'internal-pdf-viewer'],
      ['Chrome PDF Viewer', 'internal-pdf-viewer'],
      ['Chromium PDF Viewer', 'internal-pdf-viewer'],
      ['Microsoft Edge PDF Viewer', 'internal-pdf-viewer'],
      ['WebKit built-in PDF', 'internal-pdf-viewer'],
    ];
    var plugins = Object.create(PluginArrayProto || Array.prototype);
    for (var i = 0; i < pluginNames.length; i++) {
      var p = makePlugin(pluginNames[i][0], pluginNames[i][1]);
      Object.defineProperty(plugins, i, { value: p, enumerable: true });
      Object.defineProperty(plugins, p.name, { value: p });
    }
    Object.defineProperty(plugins, 'length', { value: pluginNames.length });
    plugins.item = function(i) { return plugins[i] || null; };
    plugins.namedItem = function(n) {
      for (var k = 0; k < plugins.length; k++) if (plugins[k].name === n) return plugins[k];
      return null;
    };
    plugins.refresh = function() {};
    Object.defineProperty(Navigator.prototype, 'plugins', {
      get: function() { return plugins; },
      configurable: true
    });
  } catch (e) {}

  // 4b) Worker stealth — workers have their own global scope, so navigator.webdriver
  // patches above do NOT propagate. Fingerprint scripts that probe via Worker
  // (e.g. fpscanner.WEBDRIVER) catch this inconsistency. Fix: wrap the Worker
  // constructor to prepend a navigator.webdriver patch via blob URL. Limitations:
  // module workers and same-origin script URLs are best-effort (importScripts
  // doesn't support module workers; cross-origin URLs may bypass via direct fetch).
  try {
    var OrigWorker = window.Worker;
    if (OrigWorker && !window.__cdpilot_worker_patched) {
      var workerPatch = "(function(){try{Object.defineProperty(self.navigator||{},'webdriver',{get:function(){return undefined;},configurable:true});}catch(e){}})();";
      var WrappedWorker = function(scriptURL, options) {
        try {
          var isModule = options && options.type === 'module';
          if (typeof scriptURL === 'string' && !isModule) {
            // Wrap script in a blob that applies the patch then importScripts the original.
            var wrapped = workerPatch + "importScripts(" + JSON.stringify(String(scriptURL)) + ");";
            var blob = new Blob([wrapped], { type: 'application/javascript' });
            scriptURL = URL.createObjectURL(blob);
          }
        } catch (e) {}
        return new OrigWorker(scriptURL, options);
      };
      WrappedWorker.prototype = OrigWorker.prototype;
      Object.setPrototypeOf(WrappedWorker, OrigWorker);
      window.Worker = WrappedWorker;
      Object.defineProperty(window, '__cdpilot_worker_patched', { value: true });
    }
  } catch (e) {}

  // 5) WebGL vendor/renderer — UNMASKED_* params reveal "SwiftShader" in headless.
  // Override returns generic Intel values. Read-only spoof; does not affect rendering.
  try {
    var spoofParam = function(orig, parameter) {
      if (parameter === 37445) return 'Intel Inc.';                       // UNMASKED_VENDOR_WEBGL
      if (parameter === 37446) return 'Intel Iris OpenGL Engine';         // UNMASKED_RENDERER_WEBGL
      return orig.call(this, parameter);
    };
    if (window.WebGLRenderingContext) {
      var gp1 = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function(p) { return spoofParam.call(this, gp1, p); };
    }
    if (window.WebGL2RenderingContext) {
      var gp2 = WebGL2RenderingContext.prototype.getParameter;
      WebGL2RenderingContext.prototype.getParameter = function(p) { return spoofParam.call(this, gp2, p); };
    }
  } catch (e) {}

  // 6) navigator.hardwareConcurrency — 0 is a tell. Clamp to a sane default if missing.
  try {
    if (!navigator.hardwareConcurrency || navigator.hardwareConcurrency < 2) {
      Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', {
        get: function() { return 8; },
        configurable: true
      });
    }
  } catch (e) {}
})();
"""

# Backward-compat alias: STEALTH_JS == the FULL (undetected) body. Every legacy
# reference (`cdpilot stealth on`, adaptive escalation, navigate inject) keeps
# resolving to the full patch set, exactly as before the three-tier split.
STEALTH_JS = STEALTH_JS_FULL

# ─── CAPTCHA Detection ────────────────────────────────────────────────────────
# Read-only DOM probe. Detects common CAPTCHA/challenge providers post-navigation.
# Returns JSON string: {"detected": bool, "types": [...], "details": [...]}
# Pure detection — no DOM mutation, no network, no user data leak.
CAPTCHA_DETECT_JS = r"""
(function() {
  try {
    var result = { detected: false, types: [], details: [] };
    var add = function(type, provider, extra) {
      result.detected = true;
      if (result.types.indexOf(type) < 0) result.types.push(type);
      var d = { type: type, provider: provider };
      if (extra) for (var k in extra) d[k] = extra[k];
      result.details.push(d);
    };

    // Cloudflare Turnstile
    var ts = document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]');
    if (ts.length > 0) add('turnstile', 'Cloudflare', { count: ts.length });

    // Cloudflare interstitial / managed challenge
    var cfChallenge = document.querySelector('#challenge-form, #challenge-stage, #cf-challenge-running, #cf-please-wait');
    var titleLower = (document.title || '').toLowerCase();
    if (cfChallenge || titleLower.indexOf('just a moment') >= 0 || titleLower.indexOf('attention required') >= 0) {
      add('cloudflare-challenge', 'Cloudflare');
    }

    // hCaptcha
    var hc = document.querySelectorAll('iframe[src*="hcaptcha.com"]');
    var hcDiv = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
    if (hc.length > 0 || hcDiv) add('hcaptcha', 'hCaptcha');

    // reCAPTCHA (v2 visible, v2 invisible, v3, enterprise)
    var rc = document.querySelectorAll('iframe[src*="recaptcha/api2"], iframe[src*="recaptcha/enterprise"]');
    var rcDiv = document.querySelector('.g-recaptcha');
    if (rc.length > 0 || (rcDiv && !hcDiv)) add('recaptcha', 'Google');

    // DataDome
    if (document.querySelector('#datadome-captcha, iframe[src*="captcha-delivery.com"]')) {
      add('datadome', 'DataDome');
    }

    // PerimeterX / HUMAN
    if (document.querySelector('#px-captcha, [class*="px-captcha"]')) {
      add('perimeterx', 'HUMAN');
    }

    // Arkose Labs (FunCaptcha)
    if (document.querySelector('iframe[src*="arkoselabs.com"], iframe[src*="funcaptcha.com"], #FunCaptcha')) {
      add('arkose', 'Arkose Labs');
    }

    // GeeTest
    if (document.querySelector('.geetest_holder, .geetest_panel, [id^="geetest_"]')) {
      add('geetest', 'GeeTest');
    }

    // Amazon classic image CAPTCHA ("Type the characters you see in this image")
    // Solvable locally with the optional amazoncaptcha library (image OCR).
    var amzInput = document.querySelector('#captchacharacters');
    var amzImg = document.querySelector('img[src*="opfcaptcha"], img[src*="captcha"][src*="images-na.ssl-images-amazon.com"], form[action*="/errors/validateCaptcha"] img');
    if (amzInput && amzImg) {
      add('amazon-classic', 'Amazon', { img_src: amzImg.src, input_id: amzInput.id || 'captchacharacters' });
    }

    return JSON.stringify(result);
  } catch (e) {
    return JSON.stringify({ detected: false, error: String(e) });
  }
})()
"""

# ─── Progressive-Resilience Escalation Ladder ───
# Real sites stack defenses incrementally (sahibinden.com pattern: random
# captcha -> rate-limit -> login-wall -> SMS/OTP). CAPTCHA_DETECT_JS only sees
# the captcha rung. FRICTION_DETECT_JS detects the OTHER friction rungs purely
# from the DOM (read-only) and reports the HIGHEST one present. Bilingual
# (Turkish + English) keyword heuristics — TR sites are first-class.
#
# Ladder (low -> high):
#   none          normal page
#   rate_limited  HTTP 429 markers, "too many requests" / "çok fazla istek"
#   soft_captcha  (handled by CAPTCHA_DETECT_JS, merged in _detect_friction)
#   login_wall    login form gating the real content (sign in / giriş yap)
#   otp_sms       verification-code / OTP / SMS input
#   hard_block    access denied / banned / 403 forbidden, no content
FRICTION_DETECT_JS = r"""
(function() {
  try {
    var out = { level: 'none', signals: [], detail: '' };
    var bodyText = (document.body ? (document.body.innerText || '') : '').toLowerCase();
    var titleText = (document.title || '').toLowerCase();
    var hay = titleText + ' \n ' + bodyText;
    var sample = hay.slice(0, 6000);
    var hasAny = function(words) {
      for (var i = 0; i < words.length; i++) {
        if (sample.indexOf(words[i]) >= 0) return words[i];
      }
      return null;
    };

    // ── hard_block (highest) ──
    var blockWords = [
      'access denied', 'access to this page has been denied', 'you have been blocked',
      'permanently banned', 'ip has been banned', '403 forbidden', 'forbidden',
      'erişim engellendi', 'erişiminiz engellendi', 'engellendiniz', 'yasaklandı',
      'reddedildi', 'banlandı'
    ];
    var blockHit = hasAny(blockWords);
    // Only treat as a hard block when the page has almost no real content
    // (block pages are typically tiny). Avoids false positives on articles
    // that merely mention these words.
    var thinPage = bodyText.replace(/\s+/g, ' ').trim().length < 600;

    // ── otp_sms ──
    var otpWords = [
      'verification code', 'one-time code', 'one time password', 'otp',
      'sms code', 'code sent to your phone', 'enter the code',
      'doğrulama kodu', 'onay kodu', 'tek kullanımlık', 'telefonunuza gönderilen',
      'sms ile gönderilen', 'sms doğrulama', 'kodu girin'
    ];
    var otpInput = document.querySelector(
      'input[autocomplete="one-time-code"], input[name*="otp" i], input[id*="otp" i], ' +
      'input[name*="code" i][maxlength], input[name*="sms" i], input[name*="verification" i], ' +
      'input[id*="verification" i], input[name*="dogrulama" i], input[id*="dogrulama" i]'
    );
    var otpWordHit = hasAny(otpWords);

    // ── login_wall ──
    var pwInput = document.querySelector('input[type="password"]');
    var loginForm = document.querySelector(
      'form[action*="login" i], form[action*="signin" i], form[action*="giris" i], form[id*="login" i]'
    );
    var loginWords = [
      'sign in', 'log in', 'login to continue', 'please sign in', 'you must be logged in',
      'create an account to continue', 'sign in to continue',
      'giriş yap', 'oturum aç', 'giriş yapın', 'üye girişi', 'devam etmek için giriş',
      'giriş yapmalısınız', 'lütfen giriş yapın', 'hesabınıza giriş'
    ];
    var loginWordHit = hasAny(loginWords);

    // ── rate_limited ──
    var rateWords = [
      'too many requests', 'rate limit', 'rate limited', 'slow down',
      'you are being rate limited', 'request limit', 'try again later',
      'çok fazla istek', 'çok sık istek', 'lütfen yavaşlayın', 'yavaşlayın',
      'istek sınırı', 'çok hızlı', 'daha sonra tekrar deneyin', 'güvenlik doğrulaması'
    ];
    var rateWordHit = hasAny(rateWords);
    // 429 surfaced into DOM (some sites print the status), or retry-after hint
    var rate429 = /\b429\b/.test(sample) && (sample.indexOf('request') >= 0 || sample.indexOf('istek') >= 0 || rateWordHit);
    var retryAfter = /retry[\s-]?after/.test(sample);

    // Decide highest rung present.
    if (blockHit && thinPage) {
      out.level = 'hard_block';
      out.signals.push('keyword:' + blockHit);
      out.detail = 'Access denied / banned page with no real content.';
    } else if (otpWordHit || otpInput) {
      out.level = 'otp_sms';
      if (otpWordHit) out.signals.push('keyword:' + otpWordHit);
      if (otpInput) out.signals.push('input:otp');
      out.detail = 'SMS/OTP verification prompt detected.';
    } else if ((pwInput || loginForm) && loginWordHit) {
      out.level = 'login_wall';
      out.signals.push('keyword:' + loginWordHit);
      if (pwInput) out.signals.push('input:password');
      if (loginForm) out.signals.push('form:login');
      out.detail = 'Login wall gating the page content.';
    } else if (loginWordHit && loginForm) {
      out.level = 'login_wall';
      out.signals.push('keyword:' + loginWordHit);
      out.signals.push('form:login');
      out.detail = 'Login wall gating the page content.';
    } else if (rateWordHit || rate429 || retryAfter) {
      out.level = 'rate_limited';
      if (rateWordHit) out.signals.push('keyword:' + rateWordHit);
      if (rate429) out.signals.push('status:429');
      if (retryAfter) out.signals.push('hint:retry-after');
      out.detail = 'Rate-limit signal detected on page.';
    }

    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({ level: 'none', signals: [], detail: '', error: String(e) });
  }
})()
"""

PROXY_CONFIG_FILE = os.path.join(PROFILE_DIR, 'proxy.json')
HEADLESS_CONFIG_FILE = os.path.join(PROFILE_DIR, 'headless.json')
STEALTH_CONFIG_FILE = os.path.join(PROFILE_DIR, 'stealth.json')
MODE_CONFIG_FILE = os.path.join(PROFILE_DIR, 'mode.json')
BLOCK_CONFIG_FILE = os.path.join(PROFILE_DIR, 'block.json')
CAPTCHA_PROVIDERS_FILE = os.path.join(CDPILOT_HOME, 'captcha-providers.json')
CAPTCHA_AUTO_FILE = os.path.join(PROFILE_DIR, 'captcha-auto.json')
CAPTCHA_SOLVE_TIMEOUT = int(os.environ.get('CDPILOT_CAPTCHA_TIMEOUT', 120))
FAST_CONFIG_FILE = os.path.join(PROFILE_DIR, 'fast.json')
ADAPTIVE_CONFIG_FILE = os.path.join(PROFILE_DIR, 'adaptive.json')
ENTROPY_CONFIG_FILE = os.path.join(PROFILE_DIR, 'entropy.json')
DOWNLOAD_CONFIG_FILE = os.path.join(PROFILE_DIR, 'download-config.json')
SESSION_FILE = os.path.join(PROFILE_DIR, 'sessions.json')
# Tabs that cdpilot itself opened (via go / new-tab / smart-click). The smart
# `close` command only touches these — user tabs opened manually in the same
# isolated profile are left alone.
OWNED_TABS_FILE = os.path.join(PROFILE_DIR, 'owned-tabs.json')
COOKIES_DIR = os.path.join(CDPILOT_HOME, 'cookies')
COOKIES_AUTO_CONFIG_FILE = os.path.join(PROFILE_DIR, 'cookies-auto.json')
CF_CLEARANCE_COOKIES = frozenset({'cf_clearance', '__cf_bm', '_cfuvid'})

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
    """Enable glow, input blocker, visual feedback, and (if enabled) stealth.

    Stealth JS is registered via addScriptToEvaluateOnNewDocument so it runs
    BEFORE any page script on the next navigation. It cannot un-fingerprint
    the currently-loaded document — that's by design.
    """
    global _glow_script_id
    # Visual feedback default OFF since 0.4.4. _control_start is the per-command
    # entry point — gating here turns off glow/cursor/ripples globally without
    # touching every command's code path. Backward compat preserved by
    # get_visual_config() honoring CDPILOT_MCP_SESSION=1 and CDPILOT_SHOW=1.
    if not get_visual_config():
        return
    try:
        # NOTE: addScriptToEvaluateOnNewDocument registered here is session-bound
        # to the WS connection cdp_send opens — it dies when this call returns.
        # That's fine for GLOW (also injected via Runtime.evaluate below) but
        # NOT for stealth, which must run BEFORE page scripts. Stealth is
        # therefore registered inside navigate_collect on the same WS as
        # Page.navigate, so it survives long enough to apply.
        cmds = [(898, "Page.enable", {})]
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
    # Symmetric with _control_start: if visual feedback is off, skip the
    # re-inject + timeout dance entirely. Caller checked this already, but
    # belt-and-braces in case some other path invokes _control_end directly.
    if not get_visual_config():
        return
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

# Per-process micro-cache for hot CDP HTTP endpoints (`/json`, `/json/version`).
# A typical CLI invocation calls `cdp_get("/json")` 3-7 times (session lookup,
# tab discovery, target validation). Each call is a ~10-30ms blocking HTTP
# roundtrip via urllib. Caching for a short window collapses those into one
# fetch without changing semantics — CDP tab list rarely changes mid-command.
# TTL is intentionally tiny: long enough to dedupe within a single command's
# call graph, short enough that stale state is never a concern across commands.
_CDP_GET_CACHE = {}  # path -> (timestamp, value)
_CDP_GET_TTL_S = 0.5
_CDP_GET_CACHEABLE = ("/json", "/json/version")


def cdp_get(path, no_cache=False):
    """GET request to a CDP HTTP endpoint, with TTL cache for hot paths."""
    if not no_cache and path in _CDP_GET_CACHEABLE:
        hit = _CDP_GET_CACHE.get(path)
        if hit and (time.time() - hit[0]) < _CDP_GET_TTL_S:
            return hit[1]
    try:
        with urllib.request.urlopen(f"{CDP_BASE}{path}", timeout=3) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    if path in _CDP_GET_CACHEABLE:
        _CDP_GET_CACHE[path] = (time.time(), data)
    return data


def cdp_cache_invalidate():
    """Drop the cdp_get cache. Call after operations that mutate the tab set
    (create/close/switch tab) so the next read sees fresh state."""
    _CDP_GET_CACHE.clear()


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
        cdp_cache_invalidate()
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
        # Freshly created by cdpilot -> owned. (The reuse branch above does not
        # mark, since that tab may have been opened by the user.)
        _mark_owned_tab(target_id)

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

    Resolution order:
      1. CDPILOT_TARGET env — explicit target_id pin. Used by the browser
         context pool to address a specific tab inside a specific browser
         context from a parallel CLI invocation. Bypasses session lookup
         entirely.
      2. Session window target_id (CWD-keyed).
      3. Create a new session window.

    Why the env override matters: a parallel workflow like
        ID=$(cdpilot context create) ; CDPILOT_TARGET=$ID cdpilot go URL
    needs to address the just-created tab without polluting the CWD-keyed
    session state (which would be a race condition between concurrent calls).
    """
    tabs = get_tabs()
    pages = [t for t in tabs if t.get("type") == "page"]

    # Explicit target pin via env — used by context pool callers.
    pin = os.environ.get('CDPILOT_TARGET')
    if pin:
        for p in pages:
            if p.get("id") == pin:
                return p["webSocketDebuggerUrl"], p
        # Pin was specified but the tab is gone — fail loudly rather than
        # silently switching to a different tab (would be a heisenbug for
        # parallel workflows).
        print(f"CDPILOT_TARGET={pin} but no such tab. Did the context get destroyed?",
              file=sys.stderr)
        sys.exit(1)

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

# ─── WebSocket Connection Pool ───
#
# Goal: amortise the ~30-50 ms TCP+WebSocket handshake across repeated
# cdp_send calls within a single process (MCP server, batch mode).
# Tekil CLI invocations are unaffected — the process exits after one call
# so the pool never holds more than one entry anyway.
# Opt-out: CDPILOT_WS_POOL=0 reverts to the original open-use-close path.
# navigate_collect, cmd_new_tab, cmd_close_tab keep their own short-lived
# connections because they enable CDP domains that would pollute pooled WS
# with unrelated events.

_WS_POOL = {}          # ws_url -> open websockets.WebSocketClientProtocol
_WS_LOCKS = {}         # ws_url -> asyncio.Lock  (per-URL serialisation)
_WS_POOL_ENABLED = os.environ.get("CDPILOT_WS_POOL", "1") != "0"


def _ws_lock(ws_url):
    """Return the per-URL asyncio.Lock bound to the CURRENT running loop.

    On Python 3.9 and earlier, asyncio.Lock() snapshots the running loop at
    construction time and raises if reused on a different loop later. If a
    process invokes asyncio.run() twice (rare, but possible — e.g. a CLI
    command that schedules a follow-up async call after the main one), the
    cached Lock from the first run is bound to a closed loop. We guard by
    stamping each entry with the current loop and evicting on mismatch.
    Evicting the lock also drops any pooled WS for that URL — that WS is
    bound to the dead loop too and calling anything async on it would raise.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    entry = _WS_LOCKS.get(ws_url)
    if entry is None or entry[0] is not loop:
        # Stale or absent. Evict pooled WS too — same loop, same fate.
        if entry is not None:
            _WS_POOL.pop(ws_url, None)
        _WS_LOCKS[ws_url] = (loop, asyncio.Lock())
    return _WS_LOCKS[ws_url][1]


def _ws_is_open(ws):
    """Return True if `ws` looks usable, False if it is closed/half-closed.

    Prefers the typed State enum introduced in websockets 10+; falls back to
    the boolean `.closed` attribute on older versions so we don't hard-dep
    on a specific websockets release.
    """
    try:
        from websockets.protocol import State
        return ws.state is State.OPEN
    except (ImportError, AttributeError):
        return not getattr(ws, "closed", True)


async def _ws_drain(ws, max_drain=64):
    """Consume leftover event frames on a reused connection.

    CDP servers push unsolicited events (Page.loadEventFired, DOM mutations
    etc.) between our calls. Leaving them in the recv buffer would cause
    the next cdp_send's id-dispatch loop to waste iterations on stale data
    and could trigger false TimeoutErrors when the buffer fills.
    We read up to max_drain frames with a near-zero timeout; any timeout or
    error just means the buffer is empty — that's the happy path.
    """
    for _ in range(max_drain):
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.001)
        except Exception:
            break


def _ws_pool_close_all():
    """atexit handler: synchronously close pooled WebSocket transports.

    Earlier this used asyncio.new_event_loop() + run_until_complete(ws.close()),
    but `await ws.close()` raises if invoked from a different loop than the one
    that owns the protocol — and at process-exit time the original loop is
    already dead. The exception was swallowed, so the "graceful close" was
    effectively a no-op and FDs leaked until kernel reaped them.

    Going loop-agnostic: close the underlying asyncio.Transport synchronously.
    The TCP FIN goes out cleanly without needing a running event loop.
    """
    for ws in list(_WS_POOL.values()):
        transport = getattr(ws, 'transport', None)
        if transport is not None:
            try:
                if not transport.is_closing():
                    transport.close()
            except Exception:
                pass
    _WS_POOL.clear()
    _WS_LOCKS.clear()


atexit.register(_ws_pool_close_all)


async def cdp_send(ws_url, commands, timeout=15):
    """Send multiple CDP commands and collect results."""
    import websockets

    # ── Non-pooled path (CDPILOT_WS_POOL=0) — identical to original ──
    if not _WS_POOL_ENABLED:
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

    # ── Pooled path ──
    async with _ws_lock(ws_url):
        results = {}
        reused = False  # track whether we fetched from pool or opened fresh

        # Fetch or create the connection for this URL.
        # Note: we never drain on the happy path. A pooled connection is only
        # put back after `pending` was fully consumed (recv loop exited cleanly,
        # see post-loop check below), so by construction there are no stale
        # response frames waiting. Skipping the drain saves ~1ms per call —
        # this matters because cdp_send is called dozens of times per command.
        ws = _WS_POOL.get(ws_url)
        if ws is not None and _ws_is_open(ws):
            reused = True
        else:
            # Pool miss or dead entry — open a fresh connection
            if ws_url in _WS_POOL:
                _WS_POOL.pop(ws_url)
            try:
                ws = await websockets.connect(ws_url, max_size=100 * 1024 * 1024)
            except ConnectionRefusedError:
                print("Browser is not running. Run 'cdpilot launch' first.", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                err = str(e)
                if "websocket" in err.lower() or "connect" in err.lower() or "ws://" in err.lower():
                    print(f"Browser is not running or CDP port {CDP_PORT} is unreachable. Run 'cdpilot launch' first.", file=sys.stderr)
                    sys.exit(1)
                raise

        try:
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

            # Only re-pool if we drained `pending` to zero. If we timed out
            # with responses still in flight, late frames could arrive on this
            # connection and confuse the NEXT cdp_send call (which restarts
            # IDs from 1 and would mismatch IDs from the previous call).
            # Drop in that case — safer to pay a fresh handshake next time.
            if pending:
                _WS_POOL.pop(ws_url, None)
                try:
                    await ws.close()
                except Exception:
                    pass
            else:
                _WS_POOL[ws_url] = ws
            return results

        except Exception:
            # Drop the dead/errored connection from the pool
            _WS_POOL.pop(ws_url, None)
            try:
                await ws.close()
            except Exception:
                pass

            # Retry ONCE with a fresh connection, but only when no responses
            # have arrived yet — replaying after partial progress would
            # re-fire non-idempotent commands (mouse events, form submits).
            if not results and reused:
                try:
                    ws2 = await websockets.connect(ws_url, max_size=100 * 1024 * 1024)
                except ConnectionRefusedError:
                    print("Browser is not running. Run 'cdpilot launch' first.", file=sys.stderr)
                    sys.exit(1)
                except Exception as e2:
                    err = str(e2)
                    if "websocket" in err.lower() or "connect" in err.lower() or "ws://" in err.lower():
                        print(f"Browser is not running or CDP port {CDP_PORT} is unreachable. Run 'cdpilot launch' first.", file=sys.stderr)
                        sys.exit(1)
                    raise
                results2 = {}
                try:
                    for cmd_id, method, params in commands:
                        await ws2.send(json.dumps({"id": cmd_id, "method": method, "params": params or {}}))
                    pending2 = {c[0] for c in commands}
                    start2 = time.time()
                    while pending2 and (time.time() - start2) < timeout:
                        try:
                            resp2 = await asyncio.wait_for(ws2.recv(), timeout=2)
                            data2 = json.loads(resp2)
                            if "id" in data2 and data2["id"] in pending2:
                                pending2.discard(data2["id"])
                                results2[data2["id"]] = data2.get("result", data2.get("error", {}))
                        except asyncio.TimeoutError:
                            continue
                    # Same invariant as the main path: only re-pool on full drain.
                    if pending2:
                        try:
                            await ws2.close()
                        except Exception:
                            pass
                    else:
                        _WS_POOL[ws_url] = ws2
                    return results2
                except Exception:
                    _WS_POOL.pop(ws_url, None)
                    try:
                        await ws2.close()
                    except Exception:
                        pass
                    raise

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

        # Register stealth script BEFORE navigate, on this same WS session.
        # addScriptToEvaluateOnNewDocument is session-bound: it persists only
        # as long as this connection lives — which is exactly the window we
        # need (until Page.loadEventFired below). Stealth must run before
        # any page script inspects navigator; addScript guarantees that.
        #
        # Three-tier selection: regular -> inject nothing, stealth -> LIGHT,
        # undetected -> FULL. get_mode_config() folds in the legacy stealth
        # toggle and the CDPILOT_STEALTH env var (set during adaptive
        # escalation) so existing behavior is preserved.
        stealth_source = stealth_js_for_tier(get_mode_config())
        if stealth_source:
            await ws.send(json.dumps({
                "id": 50, "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {"source": stealth_source}
            }))

        # Apply request blocking BEFORE navigate, on this same WS session.
        # Network.setBlockedURLs is session-bound (just like the stealth
        # script): the patterns are honored until this connection closes.
        # Setting it before Page.navigate ensures the very first requests
        # for this page already get blocked.
        block_cfg = get_block_config()
        if block_cfg['enabled'] and block_cfg['patterns']:
            await ws.send(json.dumps({
                "id": 60, "method": "Network.setBlockedURLs",
                "params": {"urls": block_cfg['patterns']}
            }))

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
                    # Was 1.5s blind sleep. Most pages settle within 300ms
                    # of the load event. Pages with late JS still get up to
                    # the outer 20s deadline via the next iteration's recv —
                    # we just don't pay 1.2s of dead waiting on every nav.
                    await asyncio.sleep(0.3)
                    break
            except asyncio.TimeoutError:
                if loaded:
                    break

        # Inject visual indicator (glow overlay + visual feedback).
        # Default OFF since 0.4.4 — the glow/cursor animations made cdpilot
        # feel sluggish in real automation. Re-enable with `cdpilot show on`
        # or via CDPILOT_MCP_SESSION=1 / CDPILOT_SHOW=1.
        if glow and get_visual_config():
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

# ─── Browser preference & detection ───────────────────────────────────────────
# Map of canonical browser names to platform-specific binary candidates.
# Order matters within each list: first existing path wins.
BROWSER_BINARIES = {
    'brave':    {'Darwin':  ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
                 'Linux':   ["/usr/bin/brave-browser", "/usr/bin/brave"],
                 'Windows': [os.path.expandvars(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")]},
    'chrome':   {'Darwin':  ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
                 'Linux':   ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"],
                 'Windows': [os.path.expandvars(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                             os.path.expandvars(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")]},
    'vivaldi':  {'Darwin':  ["/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"],
                 'Linux':   ["/usr/bin/vivaldi", "/usr/bin/vivaldi-stable"],
                 'Windows': [os.path.expandvars(r"C:\Program Files\Vivaldi\Application\vivaldi.exe")]},
    'edge':     {'Darwin':  ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
                 'Linux':   ["/usr/bin/microsoft-edge"],
                 'Windows': [os.path.expandvars(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]},
    'chromium': {'Darwin':  ["/Applications/Chromium.app/Contents/MacOS/Chromium"],
                 'Linux':   ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium"],
                 'Windows': [os.path.expandvars(r"C:\Program Files\Chromium\Application\chromium.exe")]},
    # v0.8.0 NOTE: there is currently no Chromium-based TLS-corrected browser
    # that ships as a standalone binary with --remote-debugging-port. Camoufox
    # is Firefox+Juggler (no CDP). Patchright/undetected-chromedriver are
    # Playwright/Python wrappers, not standalone browsers. cdpilot's CDP-only
    # architecture is incompatible with all of them without an adapter.
    # TLS-correction roadmap is v0.9: either ship a thin TLS-MITM plugin
    # (curl-impersonate semantics) or build our own BoringSSL-patched Chromium.
}

BROWSER_CONFIG_FILE = os.path.join(CDPILOT_HOME, 'browser.json')


def _macos_major():
    """Return macOS major version (e.g. 26) or None on other platforms."""
    if platform.system() != 'Darwin':
        return None
    try:
        return int(platform.mac_ver()[0].split('.')[0])
    except (ValueError, IndexError):
        return None


def _resolve_browser_name(name):
    """Resolve a browser name to its binary path. Returns None if not installed."""
    name = (name or '').lower().strip()
    if name not in BROWSER_BINARIES:
        return None
    candidates = BROWSER_BINARIES[name].get(platform.system(), [])
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def get_browser_preference():
    """Read user's persisted browser preference. Returns name or 'auto'."""
    if os.path.exists(BROWSER_CONFIG_FILE):
        try:
            with open(BROWSER_CONFIG_FILE) as f:
                return (json.load(f).get('browser') or 'auto').lower()
        except (OSError, ValueError):
            pass
    return 'auto'


def _auto_browser_priority():
    """Workload-aware browser priority.

    Two axes:
      1. Extension workload — `cdpilot ext-install` populates dev-extensions.json.
         If non-empty, the user is doing extension work, so prioritise browsers
         that honor --load-extension for unpacked extensions:
           Vivaldi ✅, Brave ✅, Edge ✅, Chrome ❌ (silently drops, 147+),
           Chromium ✅ (but rarely installed).
         If the registry is empty, prefer Chrome — most stable, fastest startup,
         no idiosyncratic background workers.
      2. Platform stability — macOS 26 (Tahoe) demotes Brave because the
         current Brave 1.89 build crashes deterministically at ~7min uptime
         (SIGTRAP in ThreadPoolForegroundWorker, observed across 9+ dumps).

    Returns (priority_list, reason_string) — reason explains *why* this order
    was picked, surfaced by `cdpilot browser status`.
    """
    has_extensions = bool(get_dev_extensions())
    on_tahoe = _macos_major() and _macos_major() >= 26

    if has_extensions:
        if on_tahoe:
            order = ['vivaldi', 'brave', 'edge', 'chromium', 'chrome']
            reason = f"extension mode (registry has dev extensions) + macOS {_macos_major()} (Brave demoted)"
        else:
            order = ['brave', 'vivaldi', 'edge', 'chromium', 'chrome']
            reason = "extension mode (registry has dev extensions)"
    else:
        if on_tahoe:
            order = ['chrome', 'vivaldi', 'edge', 'chromium', 'brave']
            reason = f"stability mode (no dev extensions) + macOS {_macos_major()} (Brave demoted)"
        else:
            order = ['chrome', 'brave', 'vivaldi', 'edge', 'chromium']
            reason = "stability mode (no dev extensions)"
    return order, reason


def _find_browser():
    """Locate the browser binary. Priority:
    1. CHROME_BIN env var (full path, backward-compatible)
    2. ~/.cdpilot/browser.json preference (set via `cdpilot browser <name>`)
    3. Auto-detection per _auto_browser_priority()
    """
    # 1) PATH lookup for common command names (Linux/Brew installs)
    for b in ["brave-browser", "vivaldi", "google-chrome", "chromium-browser", "chromium"]:
        found = shutil.which(b)
        if found:
            # Only use PATH match as fallback — preference still wins below.
            path_match = found
            break
    else:
        path_match = None

    # 2) User preference from config (overrides auto)
    pref = get_browser_preference()
    if pref and pref != 'auto':
        resolved = _resolve_browser_name(pref)
        if resolved:
            return resolved
        # Configured browser not installed — fall through to auto with a warning.
        sys.stderr.write(f"⚠️  Configured browser '{pref}' not found, falling back to auto-detect.\n")

    # 3) Auto-detection in priority order
    order, _reason = _auto_browser_priority()
    for name in order:
        resolved = _resolve_browser_name(name)
        if resolved:
            return resolved

    return path_match  # Last resort


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


def _proxy_config_raw():
    """Return raw proxy config dict ({'active': str|None, 'pools': {...}, 'proxy': legacy_url})."""
    if os.path.exists(PROXY_CONFIG_FILE):
        try:
            with open(PROXY_CONFIG_FILE) as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            pass
    return {}


def get_proxy_config():
    """Read effective proxy URL.

    Resolution order (v0.7.0):
      1. CHROME_PROXY env var (highest priority — bench/CI override)
      2. Active named pool (`{"active": "<name>", "pools": {...}}`)
      3. Legacy `{"proxy": "<url>"}` (backward compat)
    """
    proxy = os.environ.get('CHROME_PROXY', '')
    if proxy:
        return proxy
    data = _proxy_config_raw()
    # New schema: active pool
    active = data.get('active')
    pools = data.get('pools') or {}
    if active and active in pools:
        return pools[active].get('url', '')
    # Legacy fallback
    return data.get('proxy', '')


def _proxy_pools():
    """Return the named pool dict."""
    return _proxy_config_raw().get('pools') or {}


def _proxy_active_name():
    """Return the active pool name, or None."""
    data = _proxy_config_raw()
    if data.get('active') and data['active'] in (data.get('pools') or {}):
        return data['active']
    return None


def _proxy_save(data):
    """Atomically persist proxy config."""
    os.makedirs(os.path.dirname(PROXY_CONFIG_FILE), exist_ok=True)
    _atomic_write_json(PROXY_CONFIG_FILE, data)


def _proxy_add_pool(name, url, geo=None, sticky=False):
    data = _proxy_config_raw()
    pools = data.get('pools') or {}
    entry = {'url': url}
    if geo:
        entry['geo'] = geo
    if sticky:
        entry['sticky'] = True
    pools[name] = entry
    data['pools'] = pools
    _proxy_save(data)


def _proxy_remove_pool(name):
    data = _proxy_config_raw()
    pools = data.get('pools') or {}
    if name not in pools:
        return False
    del pools[name]
    data['pools'] = pools
    if data.get('active') == name:
        data['active'] = None
    _proxy_save(data)
    return True


def _proxy_set_active(name_or_none):
    data = _proxy_config_raw()
    pools = data.get('pools') or {}
    if name_or_none is None:
        data['active'] = None
    elif name_or_none in pools:
        data['active'] = name_or_none
    else:
        return False
    _proxy_save(data)
    return True


def _proxy_redact(url):
    """Strip credentials from a proxy URL for safe display."""
    if not url:
        return ''
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(url)
        if p.username or p.password:
            host = p.hostname or ''
            if p.port:
                host = f"{host}:{p.port}"
            netloc = f"***:***@{host}"
            return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))
        return url
    except Exception:
        return url

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


# ─── Three-tier stealth mode (crawl4ai-style escalation) ──────────────────────
# Tiers, weakest fingerprint footprint -> strongest spoof:
#   regular    -> inject NOTHING (cleanest, default)
#   stealth    -> STEALTH_JS_LIGHT (webdriver/chrome.runtime/permissions only)
#   undetected -> STEALTH_JS_FULL  (light + plugins + WebGL + Worker)
MODE_TIERS = ('regular', 'stealth', 'undetected')
DEFAULT_MODE_TIER = 'regular'


def get_mode_config():
    """Return the active stealth tier as a string in MODE_TIERS.

    Resolution order: CDPILOT_MODE env -> mode.json -> legacy stealth on/off
    -> DEFAULT_MODE_TIER. Legacy `cdpilot stealth on` (no mode.json present)
    maps to 'undetected' so the old binary toggle still produces the full
    patch set; `stealth off` (or absent) keeps 'regular'.
    """
    env = os.environ.get('CDPILOT_MODE', '').strip().lower()
    if env in MODE_TIERS:
        return env
    if os.path.exists(MODE_CONFIG_FILE):
        try:
            with open(MODE_CONFIG_FILE) as f:
                tier = json.load(f).get('tier', DEFAULT_MODE_TIER)
            if tier in MODE_TIERS:
                return tier
        except (OSError, ValueError):
            pass
    # Backwards-compat: no explicit mode set — honor the legacy stealth toggle.
    # stealth on -> undetected (full), stealth off -> regular (clean).
    return 'undetected' if get_stealth_config() else DEFAULT_MODE_TIER


def set_mode_config(tier):
    """Persist the active tier to mode.json. Returns the normalized tier."""
    tier = (tier or '').strip().lower()
    if tier not in MODE_TIERS:
        raise ValueError(f"invalid tier: {tier!r}")
    _atomic_write_json(MODE_CONFIG_FILE, {'tier': tier})
    return tier


def stealth_js_for_tier(tier):
    """Return the fingerprint patch JS for a tier, or None for 'regular'.

    regular    -> None (inject nothing)
    stealth    -> STEALTH_JS_LIGHT
    undetected -> STEALTH_JS_FULL
    """
    if tier == 'stealth':
        return STEALTH_JS_LIGHT
    if tier == 'undetected':
        return STEALTH_JS_FULL
    return None


def cmd_mode(tier=None):
    """Get or set the three-tier stealth mode (regular | stealth | undetected).

    Usage:
      cdpilot mode                 # show current tier + what it injects
      cdpilot mode regular         # no fingerprint patch (cleanest, fastest)
      cdpilot mode stealth         # light patch: webdriver/chrome.runtime/perms
      cdpilot mode undetected      # full patch: + plugins + WebGL + Worker

    Default: regular. Stealth Bench V1 found that the full patch set ALONE
    lowered scores (-6.3p) because the synthetic plugin array leaks, while
    light host-learning gained (+6.3p). The 'stealth' tier omits plugin
    spoofing for this reason. Escalate to 'undetected' only for hard targets.
    Effect applies on the NEXT navigation. Env override: CDPILOT_MODE=<tier>.
    """
    if tier is None or tier.strip().lower() in ('', 'status'):
        current = get_mode_config()
        patch = {
            'regular': 'none (no fingerprint patch — cleanest)',
            'stealth': 'STEALTH_JS_LIGHT (webdriver, chrome.runtime, permissions)',
            'undetected': 'STEALTH_JS_FULL (light + plugins + WebGL + Worker)',
        }[current]
        print(f'Mode: {current}')
        print(f'  Injects: {patch}')
        return
    t = tier.strip().lower()
    if t not in MODE_TIERS:
        print(f"Invalid tier: {tier}. Use one of: {', '.join(MODE_TIERS)}.", file=sys.stderr)
        sys.exit(1)
    set_mode_config(t)
    # Keep the legacy stealth toggle coherent so `stealth status` and any code
    # still reading get_stealth_config() agree with the tier:
    #   regular   -> stealth off
    #   stealth   -> stealth on  (a patch IS injected, just the light one)
    #   undetected-> stealth on
    try:
        _atomic_write_json(STEALTH_CONFIG_FILE, {'stealth': t != 'regular'})
    except Exception:
        pass
    print(f'Mode: {t}')
    print('Effect applies on next navigation (`cdpilot go <url>`).')


def get_stealth_config():
    """Return whether stealth fingerprint patches are enabled.

    Default: False (opt-in) — preserves existing behavior, lets users enable
    only when needed. Some sites detect inconsistent fingerprints and
    block stealth-mode harder than they would block plain Chrome.
    """
    env = os.environ.get('CDPILOT_STEALTH', '')
    if env:
        return env.lower() in ('1', 'true', 'yes', 'on')
    if os.path.exists(STEALTH_CONFIG_FILE):
        try:
            with open(STEALTH_CONFIG_FILE) as f:
                return bool(json.load(f).get('stealth', False))
        except (OSError, ValueError):
            pass
    return False

def _sanitize_profile_state(profile_dir):
    """Patch Default/Preferences to suppress launch dialogs.

    Sets exit_type=Normal so Chrome doesn't show the crash-restore bubble after
    we kill the process, and disables the password-save infobar. Idempotent —
    safe to run every launch. Profile is isolated under ~/.cdpilot/, user's
    personal browser state is never touched.
    """
    prefs_path = os.path.join(profile_dir, 'Default', 'Preferences')
    try:
        if os.path.exists(prefs_path):
            with open(prefs_path) as f:
                prefs = json.load(f)
        else:
            os.makedirs(os.path.dirname(prefs_path), exist_ok=True)
            prefs = {}
        prof = prefs.setdefault('profile', {})
        prof['exit_type'] = 'Normal'
        prof['exited_cleanly'] = True
        prof['password_manager_enabled'] = False
        prof['password_manager_leak_detection'] = False
        prefs['credentials_enable_service'] = False
        prefs['credentials_enable_autosignin'] = False
        autofill = prefs.setdefault('autofill', {})
        autofill['enabled'] = False
        autofill['profile_enabled'] = False
        autofill['credit_card_enabled'] = False
        with open(prefs_path, 'w') as f:
            json.dump(prefs, f)
    except (OSError, ValueError):
        pass


# ─── Commands ───

def _minimize_browser_window():
    """Minimize the browser window via CDP (Browser.setWindowBounds).

    Reliable on macOS where negative --window-position is clamped back on
    screen. Uses cdpilot's own async cdp_send over the browser-level WS —
    no new dependency. Best-effort: any failure is swallowed by the caller.
    """
    ver = cdp_get('/json/version') or {}
    ws_url = ver.get('webSocketDebuggerUrl')
    if not ws_url:
        return

    async def _do():
        r = await cdp_send(ws_url, [(1, "Browser.getWindowForTarget", {})])
        win_id = ((r.get(1) or {}).get("result") or {}).get("windowId")
        if win_id is None:
            win_id = 1
        await cdp_send(ws_url, [(2, "Browser.setWindowBounds", {
            "windowId": win_id,
            "bounds": {"windowState": "minimized"},
        })])

    asyncio.run(_do())


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

    # ─── Stability fixes (2026-04-21) ───
    # Brave on Apple Silicon crashed with SIGTRAP/EXC_BREAKPOINT deterministically
    # at ~7 min uptime on ThreadPoolForegroundWorker. Two changes:
    #   1) `--disable-gpu-compositing` removed — conflicts with Metal accel on
    #      M-series. Browser falls back to GPU-accel rendering which is the
    #      Chromium default and matches what websites expect.
    #   2) `--disable-features=...` added — catches Brave-specific background
    #      tasks that individual `--disable-brave-*` flags don't fully kill
    #      (Rewards ad scanner, Sync heartbeat, News fetcher).
    # Per-browser profile isolation. Brave-written profiles include keys that
    # confuse Vivaldi/Chrome (search_engines.json missing, prefs schema diffs),
    # so each browser gets its own subdir. Brave keeps the original path for
    # backward compatibility — existing users don't lose state on upgrade.
    browser_basename = os.path.basename(CHROME_BIN).lower()
    if 'brave' in browser_basename:
        profile_dir = PROFILE_DIR
    elif 'vivaldi' in browser_basename:
        profile_dir = PROFILE_DIR + '-vivaldi'
    elif 'edge' in browser_basename or 'msedge' in browser_basename:
        profile_dir = PROFILE_DIR + '-edge'
    elif 'chromium' in browser_basename:
        profile_dir = PROFILE_DIR + '-chromium'
    else:
        # Default: chrome and unknown chromium-based browsers
        profile_dir = PROFILE_DIR + '-chrome'
    os.makedirs(profile_dir, exist_ok=True)
    _sanitize_profile_state(profile_dir)

    chrome_args = [
        CHROME_BIN,
        f'--remote-debugging-port={CDP_PORT}',
        f'--user-data-dir={profile_dir}',
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
        # Feature-level disables — catch background workers the
        # single-purpose flags above miss. Comma-joined string = one arg.
        '--disable-features=' + ','.join([
            'BraveRewards', 'BraveAds', 'BraveSync', 'BraveNewsToday',
            'BraveVPN', 'BraveWalletBubble', 'SpeedReader', 'Tor',
            'IPFSCompanion', 'Translate', 'OptimizationGuideModelDownloading',
            'InterestFeedContentSuggestions', 'CalculateNativeWinOcclusion',
            'PasswordManagerOnboarding', 'AutofillServerCommunication',
        ]),
        # Anti-bot leak fix (2026-05-31): Chrome's blink runtime exposes an
        # "automation controlled" flag when --remote-debugging-port is set;
        # Patchright/nodriver disable this. Even though navigator.webdriver
        # already reads false on vanilla Brave/Chrome, deeper detectors
        # (Cloudflare/Datadome behavioral) probe the blink flag directly.
        '--disable-blink-features=AutomationControlled',
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
        '--use-mock-keychain',
        '--disable-session-crashed-bubble',
        # ─── GPU / rendering ───
        # --disable-gpu-compositing REMOVED: caused EXC_BREAKPOINT on Apple
        # Silicon Brave 147+ after ~7min. Let the browser use its default
        # (Metal-accelerated) compositor.
        '--disable-smooth-scrolling',
        '--new-window', 'about:blank',
    ]

    # Off-screen window placement (opt-in). Keeps the browser HEADED (anti-bot
    # detection still sees a real window / GPU) but parks it far off the visible
    # desktop so it never steals focus or pops in front of the user — ideal for
    # long bench runs on a workstation. CDPILOT_OFFSCREEN=1 or a custom
    # CDPILOT_WINDOW_POSITION="x,y". No effect on headless.
    _win_pos = os.environ.get('CDPILOT_WINDOW_POSITION', '')
    if not _win_pos and os.environ.get('CDPILOT_OFFSCREEN') in ('1', 'true', 'yes', 'on'):
        _win_pos = '-3000,-3000'
    if _win_pos:
        chrome_args.append(f'--window-position={_win_pos}')

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
            # Off-screen / minimized placement (opt-in). Keeps the browser
            # HEADED (anti-bot still sees a real GPU-backed window) but parks it
            # out of the way so long bench runs never steal focus or pop in
            # front of the user. macOS clamps negative --window-position, so we
            # also minimize via CDP (Browser.setWindowBounds) which is reliable.
            if os.environ.get('CDPILOT_OFFSCREEN') in ('1', 'true', 'yes', 'on'):
                try:
                    _minimize_browser_window()
                except Exception:
                    pass
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
    # Mark this tab as cdpilot-owned so a later `close` knows it can shut it.
    if isinstance(page, dict):
        _mark_owned_tab(page.get("id"))

    try:
        from urllib.parse import urlparse
        expected_host = (urlparse(url).hostname or '').lower()
    except Exception:
        expected_host = ''

    cfg = get_adaptive_config()
    adaptive_stealth = False
    is_known_hostile = _adaptive_host_requires_stealth(url)

    # Adaptive mode (tier-aware): if we learned a tier for this host, start the
    # navigation at that tier via CDPILOT_MODE. Falls back to the legacy
    # stealth_hosts list (-> 'stealth' tier) for hosts learned before tiers
    # existed. CDPILOT_MODE takes precedence in get_mode_config().
    learned_tier = _adaptive_host_tier(url)
    if learned_tier and learned_tier != 'regular' and get_mode_config() == 'regular':
        os.environ['CDPILOT_MODE'] = learned_tier
        adaptive_stealth = True
        sys.stderr.write(f"🛡️  Adaptive: starting at learned tier '{learned_tier}' for known-hostile host\n")
    elif is_known_hostile and get_mode_config() == 'regular':
        # Legacy stealth_hosts entry with no tier learned yet — start at light.
        os.environ['CDPILOT_MODE'] = 'stealth'
        adaptive_stealth = True
        sys.stderr.write(f"🛡️  Adaptive: enabling stealth tier for known-hostile host\n")

    # Fix 1: Per-task context isolation (opt-in via CDPILOT_ADAPTIVE_FRESH_CONTEXT=1) — spawn a fresh BrowserContext when
    # adaptive is on and we know this host is hostile. Prevents cross-task
    # cookie/TLS bleed that caused wrong-site landings in the bench regression.
    ctx_id_to_dispose = None
    active_ws = ws
    if cfg['enabled'] and is_known_hostile and os.environ.get('CDPILOT_ADAPTIVE_FRESH_CONTEXT') == '1':
        try:
            ctx_id, _tgt_id, tab_ws = await _new_isolated_context(url)
            ctx_id_to_dispose = ctx_id
            active_ws = tab_ws
        except Exception as e:
            sys.stderr.write(f"⚠️  Adaptive: isolated context failed ({e}), using default tab\n")

    # --- COOKIES AUTO PRE-NAVIGATE (v0.6.1: safe-host scoped) ---
    if _cookies_auto_should_apply(expected_host):
        try:
            cached = _load_host_cookies(expected_host)
            if cached:
                await cdp_send(active_ws, [(910, 'Network.setCookies', {'cookies': cached})])
                sys.stderr.write(f"🍪 Cookie auto: injected {len(cached)} cached cookies for {expected_host}\n")
        except Exception:
            pass
    # --- END COOKIES AUTO PRE-NAVIGATE ---

    try:
        content, _ = await navigate_collect(active_ws, url)
        print(content)

        # Fix 4: Host assert — detect silent wrong-site landings immediately.
        try:
            await _assert_host(active_ws, expected_host)
        except NavigationDrift:
            raise
        except Exception:
            pass

        # Progressive-resilience friction probe (non-captcha rungs).
        # rate_limited -> exponential backoff + re-nav (bounded). login/otp/hard
        # -> stderr handoff warning only (NO autonomous bypass — ethics line).
        # The captcha rung is left to the dedicated probe below.
        try:
            fr = await _detect_friction(active_ws)
            fr_level = fr.get('level', 'none')
            if fr_level == 'rate_limited' and _friction_backoff_enabled():
                attempt = 0
                while fr_level == 'rate_limited' and attempt < _friction_max_retry():
                    wait_s = _friction_backoff_seconds(attempt)
                    sys.stderr.write(
                        f"⏳ Rate-limit tespit edildi ({','.join(fr.get('signals', [])) or '?'}); "
                        f"{wait_s}s backoff, retry {attempt + 1}/{_friction_max_retry()}...\n")
                    if expected_host:
                        _adaptive_remember_host(expected_host)
                    await asyncio.sleep(wait_s)
                    await navigate_collect(active_ws, url)
                    fr = await _detect_friction(active_ws)
                    fr_level = fr.get('level', 'none')
                    attempt += 1
                if fr_level == 'rate_limited':
                    sys.stderr.write("⚠️  Rate-limit backoff sonrası hâlâ sınırlı. Daha sonra deneyin.\n")
                else:
                    sys.stderr.write("✅ Rate-limit temizlendi.\n")
            elif fr_level in ('login_wall', 'otp_sms', 'hard_block'):
                act = _friction_action(fr_level)
                payload = {'action': act['action'], 'url': url, 'level': fr_level,
                           'signals': fr.get('signals', [])}
                if act.get('backoff_suggested'):
                    payload['backoff_suggested'] = True
                # Human handoff: warn + emit JSON line, but DO NOT block the
                # navigation (caller may still want the partial content).
                sys.stderr.write(f"{act['message']}\n")
                sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # Post-navigation CAPTCHA probe. Non-blocking: stderr warning only.
        try:
            info = await _detect_captcha(active_ws)
            if info.get("detected"):
                types = ",".join(info.get("types", [])) or "unknown"
                sys.stderr.write(f"⚠️  CAPTCHA tespit edildi ({types}). Çözüm için: cdpilot captcha-wait\n")

                # Adaptive escalation (tier-aware): bump the host one tier up
                # (regular -> stealth -> undetected), remember it, and re-nav
                # once at the new tier. Re-nav is gated to once-per-call.
                if cfg['enabled']:
                    current_tier = get_mode_config()
                    next_tier = _escalate_tier(current_tier)
                    if expected_host:
                        _adaptive_remember_host(expected_host)
                        _adaptive_remember_host_tier(expected_host, next_tier)
                        sys.stderr.write(f"🛡️  Adaptive: remembered {expected_host} at tier '{next_tier}'\n")
                        captcha_types = info.get('types', [])
                        _adaptive_remember_host_entropy(expected_host, captcha_types)
                        needs_entropy = any(CAPTCHA_ENTROPY_REQUIRED.get(t, True) for t in captcha_types)
                        if needs_entropy:
                            sys.stderr.write(f"🧬 Adaptive: per-host entropy enabled for {expected_host} ({','.join(captcha_types)})\n")
                    # Only retry if escalation actually changes the tier (not
                    # already at the undetected ceiling for this navigation).
                    if next_tier != current_tier:
                        sys.stderr.write(f"🛡️  Adaptive: retrying once at tier '{next_tier}'...\n")
                        os.environ['CDPILOT_MODE'] = next_tier
                        # Fix 3: Idempotent re-nav — skip if already on target.
                        current_host = await _adaptive_current_host(active_ws)
                        norm = lambda h: h[4:] if h.startswith("www.") else h
                        if expected_host and norm(current_host) == norm(expected_host):
                            sys.stderr.write("🛡️  Adaptive: already on target host, skip re-nav\n")
                        else:
                            await navigate_collect(active_ws, url)
                        # Re-probe after escalated re-nav
                        info2 = await _detect_captcha(active_ws)
                        if info2.get("detected"):
                            sys.stderr.write(f"⚠️  Adaptive: CAPTCHA still present after '{next_tier}' retry. Manual solve needed.\n")
                        else:
                            sys.stderr.write(f"✅ Adaptive: CAPTCHA cleared at tier '{next_tier}'.\n")
                # Captcha solver auto-mode: if provider configured + auto on, attempt solve
                try:
                    await _captcha_auto_solve_if_enabled(active_ws, info, url)
                except Exception:
                    pass
        except Exception:
            pass

        # --- COOKIES AUTO POST-NAVIGATE (v0.6.1: safe-host scoped) ---
        if _cookies_auto_should_apply(expected_host):
            try:
                r2 = await cdp_send(active_ws, [(912, 'Network.getCookies', {})])
                all_c = r2.get(912, {}).get('cookies', [])
                host_c = [c for c in all_c
                          if expected_host.endswith(c.get('domain', '').lstrip('.'))]
                if host_c:
                    _save_host_cookies(expected_host, host_c)
                    sys.stderr.write(f"🍪 Cookie auto: saved {len(host_c)} cookies for {expected_host}\n")
            except Exception:
                pass
        # --- END COOKIES AUTO POST-NAVIGATE ---

    finally:
        # Dispose the isolated context regardless of outcome.
        if ctx_id_to_dispose:
            await _dispose_context(ctx_id_to_dispose)


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


async def cmd_eval_batch(exprs_json):
    """Evaluate N JS expressions in a SINGLE Runtime.evaluate call.

    Input: JSON array of strings. Each string is one JS expression.
    Output: JSON array of results (one per expression). Per-expression errors
    are reported as {"error": "..."} without aborting the batch.

    Why this exists:
      Every CDP `Runtime.evaluate` is a WebSocket roundtrip (~10-40ms over
      localhost, more over network). For workflows that need many small
      observations (e.g. read 12 DOM values to fill a report), N sequential
      `eval` commands cost N × roundtrip. This packs them into one IIFE that
      runs all N expressions and returns the result array — one roundtrip
      total. Typical speedup: 5-30x for batches of 5+ expressions.
    """
    try:
        exprs = json.loads(exprs_json) if isinstance(exprs_json, str) else exprs_json
        if not isinstance(exprs, list) or not all(isinstance(e, str) for e in exprs):
            print(json.dumps({"error": "Input must be a JSON array of strings"}), file=sys.stderr)
            sys.exit(1)
    except (json.JSONDecodeError, TypeError) as exc:
        print(json.dumps({"error": f"JSON parse error: {exc}"}), file=sys.stderr)
        sys.exit(1)

    ws, _ = get_page_ws()
    # Wrap each expression in its own try/catch so one failure doesn't sink
    # the batch. The user's expression is dropped directly into a parenthesized
    # position, so any value-producing JS works as-is (`1+1`, `document.title`,
    # `await fetch(...).then(r=>r.json())`). Statement-style code that needs
    # `let`/`const` must be wrapped manually: `(function(){let x=1; return x})()`.
    wrapped = []
    for e in exprs:
        wrapped.append(
            "(async function(){try{return {ok:true, value: (" + e + ")};}"
            "catch(err){return {ok:false, error:String(err && err.message || err)};}})()"
        )
    js = "Promise.all([" + ",".join(wrapped) + "])"
    r = await cdp_send(ws, [(1, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": True,
    })], timeout=30)
    result = r.get(1, {})
    if "exceptionDetails" in result:
        exc = result["exceptionDetails"]
        print(json.dumps({"error": f"batch failed: {exc.get('text', '')}"}), file=sys.stderr)
        sys.exit(1)
    val = result.get("result", {}).get("value", [])
    print(json.dumps(val, indent=2, ensure_ascii=False))


# ─── Selector Ladder ──────────────────────────────────────────────────────────

def _levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = range(len(b) + 1)
    for i, c1 in enumerate(a):
        curr = [i + 1]
        for j, c2 in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


async def _resolve_selector_ladder(ws_url, inp, strategies=None):
    import re as _re2
    if strategies is None:
        strategies = ["css", "xpath", "role-name", "text-exact", "text-fuzzy", "stable-attr", "a11y-ref"]
    tried = []
    token = "p" + format(time.time_ns() % 0xFFFFFF, 'x')

    async def _inject(expr):
        js = f"(function(){{var el={expr};if(el){{el.setAttribute('data-cdpilot-tmp','{token}');return true;}}return false;}})()"""
        r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
        return r.get(1, {}).get("result", {}).get("value") is True

    for s in strategies:
        hit = False
        if s == "css":
            r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {
                "expression": f"!!document.querySelector({json.dumps(inp)})", "returnByValue": True})])
            if r.get(1, {}).get("result", {}).get("value"):
                tried.append({"strategy": "css", "hit": True, "selector": inp})
                return inp, tried
            tried.append({"strategy": "css", "hit": False})
            continue

        elif s == "xpath" and (inp.startswith("/") or inp.startswith(".//")):
            hit = await _inject(
                f"document.evaluate({json.dumps(inp)},document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue")

        elif s == "role-name":
            m = _re2.match(r'^(\w+)=(.+)$', inp)
            if m:
                role_part, name_part = m.groups()
                name_safe = json.dumps(name_part)
                if role_part == "button":
                    cond = f"(e.tagName==='BUTTON'||e.getAttribute('role')==='button')&&e.innerText.trim()==={name_safe}"
                elif role_part == "role":
                    cond = f"e.getAttribute('role')==={name_safe}"
                else:
                    cond = f"e.getAttribute({json.dumps(role_part)})==={name_safe}"
                hit = await _inject(
                    f"Array.from(document.querySelectorAll('*')).find(e=>e.offsetParent!==null&&({cond}))")

        elif s == "text-exact":
            hit = await _inject(
                f"Array.from(document.querySelectorAll('*')).find(e=>e.offsetParent!==null&&e.innerText.trim()==={json.dumps(inp)})")

        elif s == "text-fuzzy":
            js_lev = ("function _lev(a,b){if(a.length<b.length){var t=a;a=b;b=t;}"
                      "if(!b)return a.length;"
                      "var p=[];for(var i=0;i<=b.length;i++)p[i]=i;"
                      "for(var i=0;i<a.length;i++){var c=[i+1];"
                      "for(var j=0;j<b.length;j++)c.push(Math.min(p[j+1]+1,c[j]+1,p[j]+(a[i]===b[j]?0:1)));"
                      "p=c;}return p[b.length];}")
            hit = await _inject(
                f"(function(){{{js_lev} return Array.from(document.querySelectorAll('*'))"
                f".find(e=>e.offsetParent!==null&&e.children.length===0"
                f"&&_lev(e.innerText.trim().toLowerCase(),{json.dumps(inp.lower())})<3);}})()")

        elif s == "stable-attr":
            for attr in ["data-testid", "data-cy", "name", "id"]:
                inp_safe = inp.replace('"', '\\"')
                if await _inject(f'document.querySelector(\'[{attr}="{inp_safe}"]\')'):
                    hit = True
                    break

        elif s == "a11y-ref" and inp.startswith("@") and inp[1:].isdigit():
            ref_map = _A11Y_REF_MAP or _load_a11y_refs()
            node_id = ref_map.get(int(inp[1:]))
            if node_id:
                await cdp_send(ws_url, [(0, "DOM.enable", {})])
                res = await cdp_send(ws_url, [(1, "DOM.resolveNode", {"backendNodeId": node_id})])
                obj_id = res.get(1, {}).get("object", {}).get("objectId")
                if obj_id:
                    await cdp_send(ws_url, [(2, "Runtime.callFunctionOn", {
                        "functionDeclaration": f"function(){{this.setAttribute('data-cdpilot-tmp','{token}');}}",
                        "objectId": obj_id,
                    })])
                    hit = True

        if hit:
            sel = f'[data-cdpilot-tmp="{token}"]'
            tried.append({"strategy": s, "hit": True, "selector": sel})
            return sel, tried
        tried.append({"strategy": s, "hit": False})

    return None, tried


# ─── Behavioral Entropy ───
# Randomized human-like mouse/keyboard timing. Default OFF.
# Enable: cdpilot entropy on  |  Per-command: --entropy=on / --entropy=off

_ENTROPY_SEED = os.environ.get('CDPILOT_ENTROPY_SEED')


def get_entropy_config():
    """Return True if behavioral entropy is enabled."""
    env = os.environ.get('CDPILOT_ENTROPY', '')
    if env:
        return env.lower() in ('1', 'true', 'yes', 'on')
    if os.path.exists(ENTROPY_CONFIG_FILE):
        try:
            with open(ENTROPY_CONFIG_FILE) as f:
                return bool(json.load(f).get('entropy', False))
        except (OSError, ValueError):
            pass
    return False


# Tightened in v0.5.3 based on bench data — entropy adds latency/timeouts on
# non-behavioral detectors, only enable where mouse/keyboard pattern scoring
# is the primary defense.
CAPTCHA_ENTROPY_REQUIRED = {
    'turnstile': False,
    'cloudflare-challenge': False,
    'hcaptcha': True,
    'recaptcha': True,
    'datadome': False,         # OFF — bench: -2 tasks, latency hurts (not mouse-based)
    'perimeterx': True,        # KEEP — bench: +3 tasks, behavioral scoring
    'arkose': True,            # KEEP — heavy behavioral scoring
    'geetest': True,           # KEEP — slider gestures need entropy
    'custom_antibot': False,   # OFF — generic, inconsistent benefit
    'kasada': False,           # OFF — TLS-based detection
    'shape': False,            # OFF — TLS-based detection
    'temu_slider': True,       # KEEP — slider gesture, behavioral
}


def _adaptive_remember_host_entropy(hostname, captcha_types):
    """Set entropy_hosts[hostname]=True in adaptive.json if any captcha_type needs entropy."""
    needs_entropy = any(CAPTCHA_ENTROPY_REQUIRED.get(t, True) for t in captcha_types)
    if not needs_entropy:
        return
    cfg = get_adaptive_config()
    entropy_hosts = cfg.get('entropy_hosts', {})
    if entropy_hosts.get(hostname):
        return  # already set, skip write
    entropy_hosts[hostname] = True
    cfg['entropy_hosts'] = entropy_hosts
    _atomic_write_json(ADAPTIVE_CONFIG_FILE, cfg)


def _entropy_enabled(project_id=None, host=None):
    """Return True if behavioral entropy should be used.

    Priority:
      1. If host is given and adaptive memory marks it entropy_required → True.
      2. Global get_entropy_config() (env override or ENTROPY_CONFIG_FILE).
    """
    if host:
        try:
            cfg = get_adaptive_config()
            if cfg.get('entropy_hosts', {}).get(host):
                return True
        except Exception:
            pass
    return get_entropy_config()


def _gauss(mu, sigma, lo, hi):
    """Gaussian sample clamped to [lo, hi]."""
    import random as _r
    if _ENTROPY_SEED:
        r = _r.Random(int(_ENTROPY_SEED))
    else:
        r = _r
    return max(lo, min(hi, r.gauss(mu, sigma)))


def _quartic_easeout(t):
    """1 - (1-t)^4, maps [0,1] -> [0,1]."""
    return 1.0 - (1.0 - t) ** 4


def _bezier_path(start_xy, end_xy, points=15):
    """Quadratic Bezier from start to end via a random control point.
    Returns list of (x, y) tuples including start and end."""
    import random as _r
    if _ENTROPY_SEED:
        r = _r.Random(int(_ENTROPY_SEED))
    else:
        r = _r.Random()
    x0, y0 = start_xy
    x1, y1 = end_xy
    mx = (x0 + x1) / 2
    my = (y0 + y1) / 2
    cx = mx + r.uniform(-60, 60)
    cy = my + r.uniform(-60, 60)
    result = []
    for i in range(points):
        t = i / (points - 1) if points > 1 else 0.0
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
        result.append((int(round(x)), int(round(y))))
    return result


async def _humanize_mouse_move(ws_url, x, y):
    """Move mouse along a Bezier curve to (x, y) with random delays."""
    import random as _r
    r = _r.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else _r.Random()
    start = (r.randint(100, 800), r.randint(100, 600))
    path = _bezier_path(start, (x, y), points=r.randint(10, 20))
    for px, py in path[:-1]:
        await cdp_send(ws_url, [(998, "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": px, "y": py, "button": "none", "modifiers": 0})])
        await asyncio.sleep(r.uniform(0.008, 0.025))


async def _humanize_click(ws_url, x, y):
    """Pre-pause + Bezier move + jitter + mousePressed/Released + post-pause."""
    import random as _r
    r = _r.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else _r.Random()
    await asyncio.sleep(r.uniform(0.05, 0.15))
    jx = x + r.randint(-2, 2)
    jy = y + r.randint(-2, 2)
    await _humanize_mouse_move(ws_url, jx, jy)
    cmds = [
        (991, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": jx, "y": jy,
            "button": "left", "clickCount": 1}),
        (992, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": jx, "y": jy,
            "button": "left", "clickCount": 1}),
    ]
    await cdp_send(ws_url, cmds)
    await asyncio.sleep(r.uniform(0.08, 0.20))


# ─── PerimeterX / HUMAN "Press & Hold" solver ───────────────────────────────
# PerimeterX (HUMAN Security) gates content behind a button the user must press
# AND HOLD for several seconds. The detector measures the mouse-hold *behaviour*
# (press duration, micro-tremor during the hold, release timing) to tell a human
# hand from a bot — it is NOT a token challenge, so there is nothing to fetch or
# inject. The only way through is to emit a real, human-shaped press->hold->release
# gesture. We reuse the existing humanized mouse path + Input.dispatchMouseEvent
# (zero new deps, pure CDP) and add the natural hand-tremor PerimeterX looks for.

# JS that locates the press-and-hold target and returns its viewport centre.
# Tries the canonical #px-captcha / [class*="px-captcha"] hooks first, then any
# element whose visible text matches "press & hold" / "press and hold" / the
# Turkish "basili tut". Returns JSON: {found, cx, cy, w, h, how} or {found:false}.
PRESS_HOLD_FIND_JS = r"""
(function(userSel) {
  try {
    function centre(el, how) {
      if (!el) return null;
      try { el.scrollIntoView({behavior: 'instant', block: 'center'}); } catch (e) {}
      var r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return null;
      return JSON.stringify({
        found: true,
        cx: Math.round(r.left + r.width / 2),
        cy: Math.round(r.top + r.height / 2),
        w: Math.round(r.width), h: Math.round(r.height), how: how
      });
    }
    if (userSel) {
      var u = document.querySelector(userSel);
      var cu = centre(u, 'user-selector');
      if (cu) return cu;
    }
    // Canonical PerimeterX hooks.
    var px = document.querySelector('#px-captcha, [class*="px-captcha"]');
    if (px) {
      // The visible hold target is often an inner button/div; prefer a child
      // with real size, else the container itself.
      var inner = px.querySelector('div[role="button"], button, [tabindex], div');
      var ci = centre(inner, 'px-inner');
      if (ci) return ci;
      var cc = centre(px, 'px-container');
      if (cc) return cc;
    }
    // Text-based fallback: any small interactive element saying press & hold.
    var needles = ['press & hold', 'press and hold', 'press &amp; hold',
                   'basili tut', 'basılı tut', 'press hold'];
    var cands = document.querySelectorAll(
      'button, [role="button"], div, span, a, p');
    for (var i = 0; i < cands.length; i++) {
      var el = cands[i];
      var t = (el.textContent || '').toLowerCase().trim();
      if (!t || t.length > 60) continue;
      for (var j = 0; j < needles.length; j++) {
        if (t.indexOf(needles[j]) >= 0) {
          var ct = centre(el, 'text-match');
          if (ct) return ct;
        }
      }
    }
    return JSON.stringify({ found: false });
  } catch (e) {
    return JSON.stringify({ found: false, error: String(e) });
  }
})
"""


def _press_hold_duration_ms():
    """Gaussian-randomized hold duration in ms. mu~4000, clamped 3000..7000.

    PerimeterX rejects a fixed duration (machine-like). We draw from a Gaussian
    so each attempt looks individually human, then clamp to the band the widget
    actually accepts.
    """
    return int(_gauss(4000, 900, 3000, 7000))


async def _press_hold_gesture(ws_url, x, y, hold_ms):
    """Emit one real press->hold(jitter)->release gesture at (x, y) over CDP.

    1. Bezier-humanized mouse move to the target (reuses _humanize_mouse_move).
    2. Input.dispatchMouseEvent mousePressed (button:left) at the target.
    3. Hold loop: every 100-200ms emit a mouseMoved with +/-1-2px jitter WHILE the
       left button stays pressed -- this is the natural hand-tremor PerimeterX
       inspects. Total loop time == hold_ms.
    4. Input.dispatchMouseEvent mouseReleased.
    Returns the number of micro-jitter moves dispatched during the hold.
    """
    import random as _r
    r = _r.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else _r.Random()
    # Land the cursor on the target with a human path + small final offset.
    await _humanize_mouse_move(ws_url, x, y)
    await asyncio.sleep(r.uniform(0.05, 0.18))
    # Press and hold the left button at the target.
    await cdp_send(ws_url, [(981, "Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y,
        "button": "left", "buttons": 1, "clickCount": 1})])
    jitters = 0
    elapsed = 0.0
    cur_x, cur_y = x, y
    hold_s = hold_ms / 1000.0
    while elapsed < hold_s:
        step = r.uniform(0.10, 0.20)
        # Don't overshoot the requested hold window.
        if elapsed + step > hold_s:
            step = max(0.0, hold_s - elapsed)
        await asyncio.sleep(step)
        elapsed += step
        if elapsed >= hold_s:
            break
        # +/-1-2px tremor around the press point, button still held (buttons:1).
        cur_x = x + r.randint(-2, 2)
        cur_y = y + r.randint(-2, 2)
        await cdp_send(ws_url, [(982, "Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": cur_x, "y": cur_y,
            "button": "left", "buttons": 1, "modifiers": 0})])
        jitters += 1
    # Release at (near) the press point.
    await cdp_send(ws_url, [(983, "Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": cur_x, "y": cur_y,
        "button": "left", "buttons": 0, "clickCount": 1})])
    return jitters


async def _solve_press_and_hold(ws_url, target_sel=None):
    """Solve a PerimeterX/HUMAN "Press & Hold" challenge with a humanized gesture.

    Finds the hold target (#px-captcha / [class*="px-captcha"] / press-and-hold
    text, or an explicit target_sel), then performs press->hold(with micro-tremor)
    ->release. Verifies via _detect_captcha; retries once with a different hold
    duration if the challenge is still present.

    Returns: {"solved": bool, "method": "press_and_hold", "hold_ms": N,
              "attempts": N, ...}. Never raises.
    """
    last_hold = 0
    attempts = 0
    max_attempts = 2
    for attempts in range(1, max_attempts + 1):
        # (Re)locate the target each attempt -- the widget may re-render.
        try:
            find_expr = f"({PRESS_HOLD_FIND_JS})({json.dumps(target_sel) if target_sel else 'null'})"
            res = await cdp_send(ws_url, [(1, "Runtime.evaluate", {
                "expression": find_expr, "returnByValue": True})], timeout=8)
            raw = res.get(1, {}).get("result", {}).get("value")
            loc = json.loads(raw) if raw else {"found": False}
        except Exception as e:
            return {"solved": False, "method": "press_and_hold",
                    "hold_ms": last_hold, "attempts": attempts,
                    "error": f"locate_failed:{str(e)[:80]}"}
        if not loc.get("found"):
            return {"solved": False, "method": "press_and_hold",
                    "hold_ms": last_hold, "attempts": attempts,
                    "error": "target_not_found"}

        hold_ms = _press_hold_duration_ms()
        last_hold = hold_ms
        try:
            jitters = await _press_hold_gesture(
                ws_url, int(loc["cx"]), int(loc["cy"]), hold_ms)
        except Exception as e:
            return {"solved": False, "method": "press_and_hold",
                    "hold_ms": hold_ms, "attempts": attempts,
                    "error": f"gesture_failed:{str(e)[:80]}"}

        # Settle, then check whether the challenge cleared.
        import random as _r
        await asyncio.sleep((_r.Random().uniform(500, 1500)) / 1000.0)
        info = await _detect_captcha(ws_url)
        still_px = 'perimeterx' in (info.get('types') or [])
        if not still_px:
            return {"solved": True, "method": "press_and_hold",
                    "hold_ms": hold_ms, "attempts": attempts,
                    "jitter_moves": jitters}
        # else: loop and try once more with a fresh (re-drawn) hold duration.

    return {"solved": False, "method": "press_and_hold",
            "hold_ms": last_hold, "attempts": attempts,
            "error": "still_present_after_retry"}


async def _humanize_type(ws_url, text):
    """Type text with Gaussian inter-key and dwell delays via CDP key events."""
    import random as _r
    r = _r.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else _r.Random()
    for ch in text:
        key_code = ord(ch) if ord(ch) < 256 else 0
        await cdp_send(ws_url, [(993, "Input.dispatchKeyEvent", {
            "type": "keyDown", "key": ch, "text": ch,
            "windowsVirtualKeyCode": key_code, "nativeVirtualKeyCode": key_code,
        })])
        await asyncio.sleep(_gauss(55, 15, 30, 100) / 1000.0)
        await cdp_send(ws_url, [(994, "Input.dispatchKeyEvent", {
            "type": "keyUp", "key": ch, "text": ch,
            "windowsVirtualKeyCode": key_code, "nativeVirtualKeyCode": key_code,
        })])
        await asyncio.sleep(_gauss(85, 25, 40, 200) / 1000.0)


async def _humanize_scroll(ws_url, delta_y, x=400, y=400):
    """Scroll deltaY pixels with quartic ease-out chunking."""
    import random as _r
    r = _r.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else _r.Random()
    steps = r.randint(20, 30)
    prev = 0
    for i in range(1, steps + 1):
        t = i / steps
        eased = _quartic_easeout(t)
        chunk = int(round(delta_y * eased)) - prev
        prev = int(round(delta_y * eased))
        if chunk == 0:
            continue
        await cdp_send(ws_url, [(997, "Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": x, "y": y,
            "deltaX": 0, "deltaY": chunk, "modifiers": 0,
        })])
        await asyncio.sleep(r.uniform(0.012, 0.022))


def _log_heal(cmd, inp, tried, duration_ms, no_heal=False):
    if no_heal:
        return
    if not PROJECT_ID:
        return
    import datetime as _dt2
    path = os.path.join(CDPILOT_HOME, "projects", PROJECT_ID, "heal.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {
        "ts": _dt2.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cmd": cmd,
        "input": inp,
        "tried": tried,
        "duration_ms": round(duration_ms),
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


async def cmd_click(selector, ladder=None, no_heal=False, entropy=None):
    if selector.startswith("@") and selector[1:].isdigit():
        return await cmd_click_ref(selector)
    ws, _ = get_page_ws()
    if entropy is None:
        try:
            _h = await _adaptive_current_host(ws)
        except Exception:
            _h = None
        entropy = _entropy_enabled(_get_project_id(), host=_h)
    t0 = time.time()
    res_sel, tried = await _resolve_selector_ladder(ws, selector, ladder)
    dur = (time.time() - t0) * 1000
    if not res_sel:
        _log_heal("click", selector, tried, dur, no_heal)
        print(f"Error: selector '{selector}' not resolved.", file=sys.stderr)
        sys.exit(1)
    if len(tried) > 1 or (tried and not tried[0]["hit"]):
        _log_heal("click", selector, tried, dur, no_heal)
    safe_sel = json.dumps(res_sel)
    wait_ms = get_auto_wait_ms()
    js = WAIT_AND_QUERY_JS + f"""
(function() {{
    return window.__cdpilot_waitFor({safe_sel}, {wait_ms}).then(function(el) {{
        if (!el) return 'Timeout waiting for: ' + {safe_sel};
        el.scrollIntoView({{behavior:'instant', block:'center'}});
        if (window.__cdpilot_vfx) {{
            var r = el.getBoundingClientRect();
            var cx = Math.round(r.left + r.width/2), cy = Math.round(r.top + r.height/2);
            window.__cdpilot_vfx.moveCursor(cx, cy);
            window.__cdpilot_vfx.ripple(cx, cy);
        }}
        var rect = el.getBoundingClientRect();
        var cx = Math.round(rect.left + rect.width/2), cy = Math.round(rect.top + rect.height/2);
        el.click();
        var res = 'Clicked: ' + el.tagName + ' ' + (el.textContent || '').substring(0, 60).trim();
        if (el.hasAttribute('data-cdpilot-tmp')) el.removeAttribute('data-cdpilot-tmp');
        return JSON.stringify({{res: res, cx: cx, cy: cy}});
    }});
}})()"""
    if entropy:
        r2 = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})])
        raw = r2.get(1, {}).get("result", {}).get("value", "{}")
        try:
            data = json.loads(raw)
            cx, cy = data.get("cx", 0), data.get("cy", 0)
            print(data.get("res", "?"))
        except (ValueError, TypeError):
            print(raw)
            return
        await _humanize_click(ws, cx, cy)
    else:
        # Fast path: rewrite JS to return plain string
        js_fast = WAIT_AND_QUERY_JS + f"""
(function() {{
    return window.__cdpilot_waitFor({safe_sel}, {wait_ms}).then(function(el) {{
        if (!el) return 'Timeout waiting for: ' + {safe_sel};
        el.scrollIntoView({{behavior:'instant', block:'center'}});
        if (window.__cdpilot_vfx) {{
            var r = el.getBoundingClientRect();
            var cx = Math.round(r.left + r.width/2), cy = Math.round(r.top + r.height/2);
            window.__cdpilot_vfx.moveCursor(cx, cy);
            window.__cdpilot_vfx.ripple(cx, cy);
        }}
        el.click();
        var res = 'Clicked: ' + el.tagName + ' ' + (el.textContent || '').substring(0, 60).trim();
        if (el.hasAttribute('data-cdpilot-tmp')) el.removeAttribute('data-cdpilot-tmp');
        return res;
    }});
}})()"""
        r2 = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js_fast, "returnByValue": True, "awaitPromise": True})])
        print(r2.get(1, {}).get("result", {}).get("value", "?"))


async def cmd_fill(selector, value, ladder=None, no_heal=False, entropy=None):
    ws, _ = get_page_ws()
    if entropy is None:
        try:
            _h = await _adaptive_current_host(ws)
        except Exception:
            _h = None
        entropy = _entropy_enabled(_get_project_id(), host=_h)
    t0 = time.time()
    res_sel, tried = await _resolve_selector_ladder(ws, selector, ladder)
    dur = (time.time() - t0) * 1000
    if not res_sel:
        _log_heal("fill", selector, tried, dur, no_heal)
        print(f"Error: selector '{selector}' not resolved.", file=sys.stderr)
        sys.exit(1)
    if len(tried) > 1 or (tried and not tried[0]["hit"]):
        _log_heal("fill", selector, tried, dur, no_heal)
    safe_sel = json.dumps(res_sel)
    safe_value = json.dumps(value)
    wait_ms = get_auto_wait_ms()
    if entropy:
        # Focus element, field-focus pause, then humanize typing
        js_focus = WAIT_AND_QUERY_JS + f"""
(function() {{
    return window.__cdpilot_waitFor({safe_sel}, {wait_ms}).then(function(el) {{
        if (!el) return JSON.stringify({{err: 'Timeout waiting for: ' + {safe_sel}}});
        el.scrollIntoView({{behavior:'instant', block:'center'}});
        el.focus();
        el.click();
        var r = el.getBoundingClientRect();
        var cx = Math.round(r.left + r.width/2), cy = Math.round(r.top + r.height/2);
        if (window.__cdpilot_vfx) {{
            window.__cdpilot_vfx.moveCursor(cx, cy);
        }}
        if (el.hasAttribute('data-cdpilot-tmp')) el.removeAttribute('data-cdpilot-tmp');
        return JSON.stringify({{cx: cx, cy: cy, tag: el.tagName}});
    }});
}})()"""
        r2 = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js_focus, "returnByValue": True, "awaitPromise": True})])
        raw = r2.get(1, {}).get("result", {}).get("value", "{}")
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = {}
        if data.get("err"):
            print(data["err"])
            return
        # field-focus pause: human moves hand to keyboard
        import random as _r
        _fr = _r.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else _r.Random()
        await asyncio.sleep(_fr.uniform(0.2, 0.4))
        await _humanize_type(ws, value)
        print(f"Filled (entropy): {selector} = {value[:50]}")
    else:
        js = WAIT_AND_QUERY_JS + f"""
(function() {{
    return window.__cdpilot_waitFor({safe_sel}, {wait_ms}).then(function(el) {{
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
        var res = 'Filled: ' + el.tagName + ' = ' + el.value.substring(0, 50);
        if (el.hasAttribute('data-cdpilot-tmp')) el.removeAttribute('data-cdpilot-tmp');
        return res;
    }});
}})()"""
        r2 = await cdp_send(ws, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})])
        print(r2.get(1, {}).get("result", {}).get("value", "?"))


async def cmd_submit(selector="form", ladder=None, no_heal=False):
    ws, _ = get_page_ws()
    t0 = time.time()
    res_sel, tried = await _resolve_selector_ladder(ws, selector, ladder)
    dur = (time.time() - t0) * 1000
    if not res_sel:
        _log_heal("submit", selector, tried, dur, no_heal)
        print(f"Error: selector '{selector}' not resolved.", file=sys.stderr)
        sys.exit(1)
    if len(tried) > 1 or (tried and not tried[0]["hit"]):
        _log_heal("submit", selector, tried, dur, no_heal)
    safe_sel = json.dumps(res_sel)
    js = f"""(function() {{
        const form = document.querySelector({safe_sel});
        if (!form) return 'Form not found: ' + {safe_sel};
        const btn = form.querySelector('button[type=submit], input[type=submit], button:last-of-type');
        var res;
        if (btn) {{ btn.click(); res = 'Submit clicked: ' + btn.textContent.trim(); }}
        else {{ form.submit(); res = 'Form submitted'; }}
        if (form.hasAttribute('data-cdpilot-tmp')) form.removeAttribute('data-cdpilot-tmp');
        return res;
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


# ─── Per-host cookie persistence helpers ───

def _cookies_safe_host(host):
    """Make a hostname safe for use as a filesystem directory name."""
    return host.replace(':', '_').replace('/', '_')


def _cookies_host_dir(host):
    """Return the directory path for a host's cookie store."""
    return os.path.join(COOKIES_DIR, _cookies_safe_host(host))


def _save_host_cookies(host, cookies):
    """Save cookies to ~/.cdpilot/cookies/<safe_host>/cookies.json atomically.

    Returns the path of the written file.
    """
    d = _cookies_host_dir(host)
    os.makedirs(d, exist_ok=True)
    f_path = os.path.join(d, 'cookies.json')
    expires_vals = [c.get('expires', 0) for c in cookies if c.get('expires', 0) > 0]
    expires_soonest = min(expires_vals) if expires_vals else 0
    meta = {
        'cf_clearance_present': any(c.get('name') in CF_CLEARANCE_COOKIES for c in cookies),
        'expires_soonest_unix': expires_soonest,
        'saved_at': datetime.datetime.utcnow().isoformat() + 'Z',
    }
    _atomic_write_json(f_path, {'host': host, 'cookies': cookies, 'metadata': meta})
    try:
        os.chmod(f_path, 0o600)
    except OSError:
        pass
    return f_path


def _load_host_cookies(host):
    """Load cookies from per-host store.

    Returns list of cookies, or None if missing / all expired / corrupt.
    """
    f_path = os.path.join(_cookies_host_dir(host), 'cookies.json')
    if not os.path.exists(f_path):
        return None
    try:
        with open(f_path) as f:
            data = json.load(f)
        meta = data.get('metadata', {})
        exp = meta.get('expires_soonest_unix', 0)
        if exp and exp < time.time():
            return None
        return data.get('cookies') or None
    except (OSError, ValueError):
        return None


def _cookies_auto_config():
    """Return the cookies-auto config dict ({'enabled': bool, 'safe_hosts': [str]})."""
    if not os.path.exists(COOKIES_AUTO_CONFIG_FILE):
        return {'enabled': False, 'safe_hosts': []}
    try:
        with open(COOKIES_AUTO_CONFIG_FILE) as f:
            data = json.load(f) or {}
        return {
            'enabled': bool(data.get('enabled', False)),
            'safe_hosts': list(data.get('safe_hosts') or []),
        }
    except (OSError, ValueError):
        return {'enabled': False, 'safe_hosts': []}


def _cookies_auto_enabled():
    """Return True if cookie auto-persistence is enabled (global toggle)."""
    return _cookies_auto_config()['enabled']


def _cookies_auto_should_apply(host):
    """v0.6.1: Auto save/load only applies to opt-in safe hosts.

    A host matches if it equals a safe-list entry OR ends with `.<entry>`.
    Empty safe-list means auto is a no-op (safe default — prevents bench-style
    cross-task cookie pollution observed in v0.6.0).
    """
    if not host:
        return False
    cfg = _cookies_auto_config()
    if not cfg['enabled']:
        return False
    safe = cfg['safe_hosts']
    if not safe:
        return False
    h = host.lower()
    for entry in safe:
        e = (entry or '').lower().lstrip('.')
        if not e:
            continue
        if h == e or h.endswith('.' + e):
            return True
    return False


def _set_cookies_auto(enabled):
    """Enable or disable cookie auto-persistence (preserves safe_hosts)."""
    cfg = _cookies_auto_config()
    cfg['enabled'] = bool(enabled)
    _atomic_write_json(COOKIES_AUTO_CONFIG_FILE, cfg)


def _cookies_auto_add_host(host):
    cfg = _cookies_auto_config()
    h = (host or '').lower().lstrip('.')
    if not h:
        return False
    if h in (e.lower() for e in cfg['safe_hosts']):
        return False
    cfg['safe_hosts'].append(h)
    _atomic_write_json(COOKIES_AUTO_CONFIG_FILE, cfg)
    return True


def _cookies_auto_remove_host(host):
    cfg = _cookies_auto_config()
    h = (host or '').lower().lstrip('.')
    before = len(cfg['safe_hosts'])
    cfg['safe_hosts'] = [e for e in cfg['safe_hosts'] if e.lower() != h]
    _atomic_write_json(COOKIES_AUTO_CONFIG_FILE, cfg)
    return before != len(cfg['safe_hosts'])


async def cmd_cookies(*args):
    """List, export, or import cookies.

    Usage:
      cdpilot cookies                              # list all cookies (or for current page)
      cdpilot cookies <domain>                     # list cookies for a specific domain
      cdpilot cookies save <file> [<domain>]       # export to JSON (all or scoped)
      cdpilot cookies load <file>                  # import cookies from JSON
      cdpilot cookies save --host <hostname>       # save to per-host cache
      cdpilot cookies load --host <hostname>       # load from per-host cache
      cdpilot cookies list                         # list all cached hosts + age + CF flag
      cdpilot cookies clear --host <hostname>      # remove one host's cache
      cdpilot cookies clear --all                  # wipe entire cookie cache
      cdpilot cookies clear --older-than <Nd>      # remove stale entries (e.g. 7d)
      cdpilot cookies auto on|off|status           # toggle auto-save/replay on navigate
      cdpilot cookies auto add <host>              # add host to auto safe-list (v0.6.1)
      cdpilot cookies auto remove <host>           # remove host from safe-list
      cdpilot cookies auto list                    # show enable flag + safe-list
      cdpilot cookies cf-replay <url>              # inject cached CF clearance before nav

    v0.6.1: cookies auto is GATED by a per-host safe-list (default empty).
    Enabling `cookies auto on` alone is a no-op until you explicitly add hosts
    via `cookies auto add <host>`. This prevents cross-task cookie pollution
    in parallel/agent workloads (regression observed in v0.6.0).

    Why save/load: once you've beaten a Cloudflare/DataDome challenge in one
    cdpilot process, the `cf_clearance` (or equivalent) cookie sits in this
    browser instance's jar. Exporting it lets you skip the wall in a separate
    process or after a `cdpilot stop` cycle. Same applies to logged-in
    sessions — capture once, replay across runs.
    """
    sub = args[0].lower() if args else None

    if sub == 'save':
        # Per-host mode: cookies save --host <hostname>
        if len(args) >= 3 and args[1] == '--host':
            host = args[2]
            ws, _ = get_page_ws()
            r = await cdp_send(ws, [(1, "Network.getCookies", {})])
            all_c = r.get(1, {}).get("cookies", [])
            host_c = [c for c in all_c if host.endswith(c.get('domain', '').lstrip('.'))]
            if not host_c:
                print(f"No cookies found for host: {host}", file=sys.stderr)
                return
            path = _save_host_cookies(host, host_c)
            print(f"Saved {len(host_c)} cookies for {host} -> {path}")
            return
        # Global file mode (backward compat)
        if len(args) < 2:
            print('Usage: cdpilot cookies save <file> [<domain>]', file=sys.stderr)
            sys.exit(1)
        out_path = os.path.expanduser(args[1])
        domain_filter = args[2] if len(args) >= 3 else None
        ws, _ = get_page_ws()
        # Get all cookies (no urls filter → all). Domain filter is applied
        # client-side so we can match subdomains via endswith.
        r = await cdp_send(ws, [(1, "Network.getCookies", {})])
        cookies = r.get(1, {}).get("cookies", [])
        if domain_filter:
            d = domain_filter.lstrip('.')
            cookies = [c for c in cookies
                       if c.get('domain', '').lstrip('.').endswith(d)]
        with open(out_path, 'w') as f:
            json.dump(cookies, f, indent=2)
        print(f'Saved {len(cookies)} cookies -> {out_path}')
        return

    if sub == 'load':
        # Per-host mode: cookies load --host <hostname>
        if len(args) >= 3 and args[1] == '--host':
            host = args[2]
            cookies = _load_host_cookies(host)
            if not cookies:
                print(f"No valid cached cookies for {host}", file=sys.stderr)
                return
            ws, _ = get_page_ws()
            await cdp_send(ws, [(1, "Network.setCookies", {"cookies": cookies})])
            print(f"Injected {len(cookies)} cookies for {host}")
            return
        # Global file mode (backward compat)
        if len(args) < 2:
            print('Usage: cdpilot cookies load <file>', file=sys.stderr)
            sys.exit(1)
        in_path = os.path.expanduser(args[1])
        if not os.path.exists(in_path):
            print(f'File not found: {in_path}', file=sys.stderr)
            sys.exit(1)
        try:
            with open(in_path) as f:
                cookies = json.load(f)
        except (OSError, ValueError) as e:
            print(f'Cannot parse cookie file: {e}', file=sys.stderr)
            sys.exit(1)
        if not isinstance(cookies, list):
            print('Cookie file must contain a JSON array of cookie objects', file=sys.stderr)
            sys.exit(1)
        ws, _ = get_page_ws()
        # Network.setCookies takes the same shape Network.getCookies returns.
        # CDP will skip cookies it considers invalid; we log the count it
        # actually accepted by re-reading.
        await cdp_send(ws, [(1, "Network.setCookies", {"cookies": cookies})])
        # Verify count
        r = await cdp_send(ws, [(2, "Network.getCookies", {})])
        loaded = r.get(2, {}).get("cookies", [])
        # Map by (name, domain, path) for set inclusion check
        want = {(c.get('name'), c.get('domain'), c.get('path', '/')) for c in cookies}
        have = {(c.get('name'), c.get('domain'), c.get('path', '/')) for c in loaded}
        accepted = len(want & have)
        print(f'Loaded {accepted}/{len(cookies)} cookies from {in_path}')
        if accepted < len(cookies):
            print(f'  ({len(cookies) - accepted} rejected by CDP — usually because of expiry or domain mismatch)')
        return

    if sub == 'list':
        if not os.path.exists(COOKIES_DIR):
            print("No per-host cookies stored.")
            return
        entries = sorted(os.listdir(COOKIES_DIR))
        if not entries:
            print("No per-host cookies stored.")
            return
        print(f"  {'HOST':40} {'AGE':10} CF")
        print("  " + "-" * 56)
        for host_dir in entries:
            f_path = os.path.join(COOKIES_DIR, host_dir, 'cookies.json')
            if not os.path.exists(f_path):
                continue
            try:
                with open(f_path) as f:
                    data = json.load(f)
                meta = data.get('metadata', {})
                saved_at = datetime.datetime.fromisoformat(meta['saved_at'].rstrip('Z'))
                age = datetime.datetime.utcnow() - saved_at
                age_str = f"{age.days}d" if age.days > 0 else f"{age.seconds // 3600}h"
                cf = "cf_clearance" if meta.get('cf_clearance_present') else ""
                print(f"  {host_dir:40} {age_str:10} {cf}")
            except Exception:
                continue
        return

    if sub == 'clear':
        if len(args) >= 3 and args[1] == '--host':
            shutil.rmtree(_cookies_host_dir(args[2]), ignore_errors=True)
            print(f"Cleared cookies for {args[2]}")
        elif len(args) >= 2 and args[1] == '--all':
            shutil.rmtree(COOKIES_DIR, ignore_errors=True)
            print("Cleared all per-host cookies")
        elif len(args) >= 3 and args[1] == '--older-than':
            if not os.path.exists(COOKIES_DIR):
                print("No per-host cookies stored.")
                return
            days = int(args[2].rstrip('d'))
            now = datetime.datetime.utcnow()
            removed = 0
            for host_dir in os.listdir(COOKIES_DIR):
                d = os.path.join(COOKIES_DIR, host_dir)
                f = os.path.join(d, 'cookies.json')
                if not os.path.exists(f):
                    continue
                try:
                    with open(f) as j:
                        saved_at = datetime.datetime.fromisoformat(
                            json.load(j)['metadata']['saved_at'].rstrip('Z'))
                    if (now - saved_at).days >= days:
                        shutil.rmtree(d, ignore_errors=True)
                        removed += 1
                except Exception:
                    pass
            print(f"Removed {removed} host(s) older than {days}d")
        else:
            print("Usage: cdpilot cookies clear --host <h>|--all|--older-than <Nd>",
                  file=sys.stderr)
        return

    if sub == 'auto':
        state = args[1].lower() if len(args) >= 2 else 'status'
        if state == 'on':
            _set_cookies_auto(True)
        elif state == 'off':
            _set_cookies_auto(False)
        elif state == 'add':
            if len(args) < 3:
                print("Usage: cdpilot cookies auto add <host>", file=sys.stderr)
                return
            added = _cookies_auto_add_host(args[2])
            print(f"{'Added' if added else 'Already in safe-list:'} {args[2]}")
            return
        elif state in ('remove', 'rm'):
            if len(args) < 3:
                print("Usage: cdpilot cookies auto remove <host>", file=sys.stderr)
                return
            removed = _cookies_auto_remove_host(args[2])
            print(f"{'Removed' if removed else 'Not in safe-list:'} {args[2]}")
            return
        elif state in ('list', 'ls'):
            cfg = _cookies_auto_config()
            status = 'on' if cfg['enabled'] else 'off'
            hosts = cfg['safe_hosts']
            print(f"Cookie auto-persistence: {status}")
            print(f"Safe-list ({len(hosts)} host{'s' if len(hosts) != 1 else ''}):")
            for h in hosts:
                print(f"  {h}")
            if not hosts:
                print("  (empty — auto is a no-op until hosts are added)")
            return
        cfg = _cookies_auto_config()
        status = 'on' if cfg['enabled'] else 'off'
        hosts_n = len(cfg['safe_hosts'])
        print(f"Cookie auto-persistence: {status} (safe-list: {hosts_n} host{'s' if hosts_n != 1 else ''})")
        if cfg['enabled'] and hosts_n == 0:
            print("Note: safe-list is empty → auto is a no-op. Use: cdpilot cookies auto add <host>")
        return

    if sub == 'cf-replay':
        if len(args) < 2:
            print("Usage: cdpilot cookies cf-replay <url>", file=sys.stderr)
            return
        from urllib.parse import urlparse
        host = urlparse(args[1]).hostname or ''
        if not host:
            print(f"Cannot parse hostname from: {args[1]}", file=sys.stderr)
            return
        cookies = _load_host_cookies(host)
        if not cookies:
            print(f"No cached cookies for {host}")
            return
        ws, _ = get_page_ws()
        await cdp_send(ws, [(1, "Network.setCookies", {"cookies": cookies})])
        cf_count = sum(1 for c in cookies if c.get('name') in CF_CLEARANCE_COOKIES)
        print(f"Injected {len(cookies)} cookies for {host} ({cf_count} CF clearance)")
        return

    # List mode (default) — show browser's live cookie jar
    domain = args[0] if args else None
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


async def cmd_wipe(*args):
    """v0.6.2: Per-task state hygiene — clear cookies + storage for non-safe hosts.

    Solves cross-task contamination in parallel agent workloads without
    spawning new BrowserContexts (which break browser-use's target tracking).
    Designed to be called between tasks by the bench/agent adapter.

    Usage:
      cdpilot wipe                          # cookies + localStorage + sessionStorage,
                                              keeps cookies-auto safe-list hosts intact
      cdpilot wipe --all                    # also wipes safe-list hosts (full reset)
      cdpilot wipe --keep <host>[,host...]  # explicit keep-list (overrides safe-list)
      cdpilot wipe --cookies                # cookies only
      cdpilot wipe --storage                # localStorage + sessionStorage only
      cdpilot wipe --tabs                   # close all tabs except current

    Returns JSON: {cookies_removed, storage_cleared_origins, tabs_closed}
    """
    only_cookies = '--cookies' in args
    only_storage = '--storage' in args
    only_tabs = '--tabs' in args
    wipe_all = '--all' in args
    do_cookies = only_cookies or (not only_storage and not only_tabs)
    do_storage = only_storage or (not only_cookies and not only_tabs)
    do_tabs = only_tabs

    # Build keep-list (safe-list + explicit --keep)
    keep_hosts = set()
    if not wipe_all:
        keep_hosts.update(h.lower() for h in _cookies_auto_config()['safe_hosts'])
    for i, a in enumerate(args):
        if a == '--keep' and i + 1 < len(args):
            keep_hosts.update(h.strip().lower() for h in args[i + 1].split(',') if h.strip())

    def _host_kept(host):
        h = (host or '').lower().lstrip('.')
        if not h:
            return False
        for k in keep_hosts:
            if h == k or h.endswith('.' + k):
                return True
        return False

    ws, _ = get_page_ws()
    result = {'cookies_removed': 0, 'storage_cleared_origins': 0, 'tabs_closed': 0}

    if do_cookies:
        r = await cdp_send(ws, [(1, 'Network.getCookies', {})])
        cookies = r.get(1, {}).get('cookies', [])
        to_remove = [c for c in cookies if not _host_kept(c.get('domain', ''))]
        for c in to_remove:
            try:
                await cdp_send(ws, [(2, 'Network.deleteCookies', {
                    'name': c['name'],
                    'domain': c.get('domain'),
                    'path': c.get('path', '/'),
                })])
                result['cookies_removed'] += 1
            except Exception:
                pass

    if do_storage:
        # Collect origins from cookies (best-effort — CDP has no enumerate)
        origins = set()
        r = await cdp_send(ws, [(1, 'Network.getCookies', {})])
        for c in r.get(1, {}).get('cookies', []):
            d = c.get('domain', '').lstrip('.')
            if d and not _host_kept(d):
                origins.add(f"https://{d}")
                origins.add(f"http://{d}")
        # Also clear current origin storage if not kept
        try:
            r2 = await cdp_send(ws, [(2, 'Runtime.evaluate', {
                'expression': 'location.origin', 'returnByValue': True,
            })])
            cur_origin = r2.get(2, {}).get('result', {}).get('value')
            if cur_origin:
                from urllib.parse import urlparse
                h = urlparse(cur_origin).hostname or ''
                if not _host_kept(h):
                    origins.add(cur_origin)
        except Exception:
            pass
        for origin in origins:
            try:
                await cdp_send(ws, [(3, 'Storage.clearDataForOrigin', {
                    'origin': origin,
                    'storageTypes': 'local_storage,session_storage,indexeddb,websql,cache_storage,service_workers',
                })])
                result['storage_cleared_origins'] += 1
            except Exception:
                pass

    if do_tabs:
        tabs = get_tabs()
        page_tabs = [t for t in tabs if t.get('type') == 'page']
        cur_id = None
        try:
            cur_id = (await cdp_send(ws, [(1, 'Target.getTargets', {})])).get(1, {})
            # Fallback to URL match
        except Exception:
            pass
        for t in page_tabs[1:]:  # keep first tab
            try:
                await cdp_send(ws, [(4, 'Target.closeTarget', {'targetId': t['id']})])
                result['tabs_closed'] += 1
            except Exception:
                pass

    print(json.dumps(result))


# v0.8.0: known JA3/JA4 prefixes for recent Chrome stable. Updated periodically.
# Source: tls.peet.ws and browserleaks comparisons against Chrome 130–148 on macOS/Linux.
# Format: (label, ja3_md5_prefix_or_full, ja4_prefix). Empty values disable that check.
KNOWN_CHROME_TLS = [
    # Chrome 130-148, BoringSSL default. Hash varies slightly with GREASE — match prefix.
    ('chrome-stable-130-148', None, 't13d1516h2_'),
]


async def cmd_tls_check(*args):
    """v0.8.0: Probe the browser's TLS / HTTP-2 fingerprint via a public echo service.

    Why: anti-bot services (Akamai, Kasada, deeper CF checks) inspect JA3/JA4
    and HTTP-2 SETTINGS, not just JS-level signals. If the running browser's
    fingerprint doesn't look like Chrome stable, no amount of JS stealth will
    save it on TLS-gated sites.

    Usage:
      cdpilot tls-check                          # default: tls.peet.ws
      cdpilot tls-check --json                   # raw JSON only
      cdpilot tls-check --service browserleaks   # alternate echo service

    cdpilot itself does not modify TLS (BoringSSL is hardcoded inside Chromium).
    There is currently NO Chromium-based TLS-corrected browser that ships as a
    standalone binary with --remote-debugging-port:
      - Camoufox is Firefox+Juggler (no CDP)
      - Patchright / undetected-chromedriver / nodriver are Python/Playwright
        libraries, not standalone browsers
    cdpilot's CDP-only architecture is incompatible with all of them. The
    v0.9 roadmap addresses this via either (a) an optional TLS-MITM plugin
    using curl-impersonate semantics, or (b) a BoringSSL-patched Chromium fork.
    """
    json_only = '--json' in args
    service = 'tls.peet.ws'
    for i, a in enumerate(args):
        if a == '--service' and i + 1 < len(args):
            service = args[i + 1]

    url_map = {
        'tls.peet.ws': 'https://tls.peet.ws/api/all',
        'browserleaks': 'https://browserleaks.com/tls',
    }
    url = url_map.get(service, url_map['tls.peet.ws'])

    ws, _ = get_page_ws()
    try:
        await navigate_collect(ws, url)
    except Exception as e:
        print(json.dumps({'error': f'navigation failed: {e}', 'service': service}),
              file=sys.stderr)
        sys.exit(1)

    # Grab the response JSON from the page body
    r = await cdp_send(ws, [(1, 'Runtime.evaluate', {
        'expression': "(()=>{ const pre=document.querySelector('pre'); "
                      "return pre ? pre.textContent : document.body.innerText; })()",
        'returnByValue': True,
    })])
    raw = r.get(1, {}).get('result', {}).get('value', '')

    parsed = None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        pass

    if json_only:
        print(raw)
        return

    if not parsed:
        print(json.dumps({'error': 'could not parse TLS echo response',
                          'service': service, 'preview': raw[:200]}))
        return

    # Extract common fields (tls.peet.ws schema)
    tls = parsed.get('tls', {}) if isinstance(parsed, dict) else {}
    ja3 = tls.get('ja3', '') or parsed.get('ja3', '')
    ja3_hash = tls.get('ja3_hash', '') or parsed.get('ja3_hash', '')
    ja4 = tls.get('ja4', '') or parsed.get('ja4', '')
    h2 = parsed.get('http2', {}) if isinstance(parsed, dict) else {}
    h2_settings = h2.get('akamai_fingerprint', '') or h2.get('akamai_hash', '')

    # Chrome-likeness verdict
    verdict = 'unknown'
    notes = []
    if ja4 and any(ja4.startswith(prefix) for (_, _, prefix) in KNOWN_CHROME_TLS if prefix):
        verdict = 'chrome-like'
    elif ja4:
        verdict = 'non-chrome'
        notes.append(f'JA4 prefix "{ja4[:8]}" not in known Chrome stable set')
    if h2_settings and isinstance(h2_settings, str) and not h2_settings.startswith('1:65536'):
        notes.append(f'HTTP/2 SETTINGS differ from Chrome default (got "{h2_settings[:40]}...")')

    print(f"TLS fingerprint probe via {service}")
    print(f"  JA3:        {ja3 or '(missing)'}")
    print(f"  JA3 hash:   {ja3_hash or '(missing)'}")
    print(f"  JA4:        {ja4 or '(missing)'}")
    print(f"  H2 akamai:  {h2_settings or '(missing)'}")
    print(f"  Verdict:    {verdict}")
    if notes:
        print("  Notes:")
        for n in notes:
            print(f"    - {n}")
    if verdict == 'non-chrome':
        print("\n  → cdpilot has no in-tree TLS fix in v0.8.0 (no CDP-compatible TLS-corrected")
        print("    Chromium binary exists on the market). v0.9 will ship an optional")
        print("    TLS-MITM plugin (curl-impersonate semantics). Track:")
        print("    https://github.com/cdpilot/cdpilot/issues (v0.9 milestone)")


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


# ─── Owned-Tab Tracking ───
# cdpilot records every target_id it opens so that `close` can distinguish its
# own tabs from tabs the user opened manually in the same isolated profile.
# Stored as a JSON list in the project profile dir; survives across CLI
# invocations (each `go`/`new-tab` is a separate process).

def _load_owned_tabs():
    """Return the set of target_ids cdpilot opened in this project profile."""
    try:
        with open(OWNED_TABS_FILE) as f:
            data = json.load(f)
            return set(data.get("owned", []))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


def _save_owned_tabs(owned):
    """Persist the owned target_id set."""
    try:
        os.makedirs(os.path.dirname(OWNED_TABS_FILE), exist_ok=True)
        with open(OWNED_TABS_FILE, "w") as f:
            json.dump({"owned": sorted(owned)}, f)
    except OSError:
        pass


def _mark_owned_tab(target_id):
    """Record a target_id as cdpilot-owned. No-op on falsy input."""
    if not target_id:
        return
    owned = _load_owned_tabs()
    if target_id not in owned:
        owned.add(target_id)
        _save_owned_tabs(owned)


def _is_chrome_internal_url(url):
    """True for blank/new-tab/internal pages that don't count as 'real' tabs."""
    if not url:
        return True
    u = url.strip().lower()
    return (u in ("about:blank", "about:newtab", "")
            or u.startswith("chrome://")
            or u.startswith("edge://")
            or u.startswith("chrome-extension://")
            or u.startswith("devtools://")
            or u.startswith("brave://")
            or u.startswith("vivaldi://"))


async def _browser_close_graceful():
    """Ask the browser to shut down gracefully via the CDP Browser.close
    command (cleanest cross-platform path — flushes state, no orphaned procs).
    Returns True if the command was acknowledged. Falls back to a SIGTERM-based
    process stop (never kill -9) when the WebSocket path fails."""
    try:
        browser_ws = await _get_browser_ws()
        if browser_ws:
            await cdp_send(browser_ws, [(1, "Browser.close", {})], timeout=5)
            return True
    except SystemExit:
        raise
    except Exception:
        pass
    # Fallback: graceful OS-level termination (SIGTERM on POSIX, taskkill on
    # Windows). kill -9 is intentionally NOT used here — last resort only.
    return _stop_browser_on_port(CDP_PORT)


async def cmd_close(force_browser=False, keep_browser=False):
    """Smart close: shut down cdpilot's own tabs, then close the whole browser
    if no user tabs remain.

    Behavior:
      1. Close every cdpilot-owned tab (CDP Target.closeTarget).
      2. Inspect the remaining page targets:
         - 0 real tabs left (only about:blank / chrome:// / new-tab) ->
           close the browser application gracefully (Browser.close, SIGTERM
           fallback — never kill -9).
         - one or more user tabs remain -> leave the browser open; only the
           owned tabs were closed.

    Flags:
      keep_browser  — never close the browser, only the owned tabs.
      force_browser — close the browser even if user tabs remain.
    """
    if not cdp_get("/json/version"):
        print("No browser running.")
        return

    tabs = get_tabs()
    pages = [t for t in tabs if t.get("type") == "page"]
    owned = _load_owned_tabs()

    # Make sure the current session window counts as owned even if it predates
    # tracking (legacy session created before this feature shipped).
    session_target = _get_session_window_target_id()
    if session_target:
        owned.add(session_target)

    browser_ws = await _get_browser_ws()
    closed = 0
    for p in pages:
        tid = p.get("id")
        if tid and tid in owned:
            try:
                await cdp_send(browser_ws, [(1, "Target.closeTarget",
                                             {"targetId": tid})], timeout=5)
                closed += 1
            except Exception:
                pass

    # Owned set is consumed — clear tracking + the CWD session window pointer so
    # a later command starts clean.
    _save_owned_tabs(set())
    if session_target:
        sessions = _load_sessions()
        sid = _get_session_id()
        sessions.pop(sid, None)
        _save_sessions(sessions)
    cdp_cache_invalidate()

    print(f"Closed {closed} cdpilot tab(s).")

    # Re-read remaining targets after closing owned tabs.
    remaining = get_tabs()
    remaining_pages = [t for t in remaining if t.get("type") == "page"]
    user_pages = [p for p in remaining_pages
                  if not _is_chrome_internal_url(p.get("url"))]

    if keep_browser:
        if user_pages:
            print(f"Browser left open ({len(user_pages)} user tab(s)).")
        else:
            print("Browser left open (--keep).")
        return

    if user_pages and not force_browser:
        print(f"Browser left open — {len(user_pages)} user tab(s) still present.")
        return

    # No user tabs remain (or --force) -> close the browser gracefully.
    if await _browser_close_graceful():
        print(f"Browser closed gracefully (port {CDP_PORT}).")
        if PROJECT_ID:
            registry = _load_registry()
            if PROJECT_ID in registry:
                registry[PROJECT_ID]["status"] = "stopped"
                registry[PROJECT_ID]["pid"] = None
                _save_registry(registry)
    else:
        print("Browser close failed.", file=sys.stderr)


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
    """List installed extensions (packed via Chrome Web Store + dev mode unpacked).

    Two sources are checked independently — neither absence should hide the other.
    Previously an early-return on missing Default/Extensions/ silently swallowed
    dev-mode entries written by `ext-install`.
    """
    # 1) Packed (CRX) extensions live under Default/Extensions and are described
    #    in Default/Preferences. Only present after the user installs from the
    #    Chrome Web Store; ext-install does NOT write here.
    ext_dir = os.path.join(PROFILE_DIR, "Default", "Extensions")
    packed_ids = []
    ext_names = {}
    if os.path.isdir(ext_dir):
        prefs_path = os.path.join(PROFILE_DIR, "Default", "Preferences")
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
                    }
            except Exception:
                pass
        packed_ids = [d for d in os.listdir(ext_dir) if not d.startswith(".")]

    # 2) Dev-mode (unpacked) extensions registered by `ext-install` —
    #    loaded into the browser via --load-extension on each launch.
    dev_exts = get_dev_extensions()

    if not packed_ids and not dev_exts:
        print("No extensions installed.")
        return

    if packed_ids:
        for ext_id in sorted(packed_ids):
            info = ext_names.get(ext_id, {})
            name = info.get("name", ext_id)
            version = info.get("version", "?")
            enabled = info.get("enabled", True)
            status = "✅" if enabled else "⏸️"
            print(f"  {status} {name} (v{version})")
            print(f"     ID: {ext_id}")
        print(f"\n{len(packed_ids)} packed extension{'s' if len(packed_ids) != 1 else ''}")

    if dev_exts:
        if packed_ids:
            print()
        print(f"Dev Mode Extensions ({len(dev_exts)}):")
        for i, path in enumerate(dev_exts):
            exists = '✅' if os.path.isdir(path) else '❌ (directory not found)'
            # Try to read manifest for friendlier output
            label = os.path.basename(path.rstrip('/'))
            try:
                with open(os.path.join(path, 'manifest.json')) as f:
                    mf = json.load(f)
                label = f"{mf.get('name', label)} (v{mf.get('version', '?')})"
            except Exception:
                pass
            print(f"  {exists} [{i}] {label}")
            print(f"        {path}")


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

        # Warn if the active browser silently drops --load-extension.
        # Chrome 147+ does this without any console message, easily wasting
        # hours of "why isn't my extension loading?" debugging.
        active = os.environ.get('CHROME_BIN') or _find_browser() or ''
        active_lower = os.path.basename(active).lower()
        if 'google chrome' in active_lower or active_lower == 'chrome' or 'google-chrome' in active_lower:
            sys.stderr.write(
                "⚠️  Active browser is Chrome — Chrome 147+ silently ignores --load-extension\n"
                "   for unpacked extensions. Switch with: cdpilot browser vivaldi\n"
            )

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

# ─── Browser context pool (Target.createBrowserContext × N) ───
#
# Browser contexts are isolated cookie/storage namespaces inside the SAME
# browser process. Playwright's parallel-tabs model — true concurrency for
# automation workloads that would otherwise serialize on one shared cookie
# jar. Use cases:
#   - Run a citation tracker across 50 Perplexity queries in parallel
#     without each query stomping on the previous one's chat history.
#   - Test a flow against logged-in + logged-out + guest variants in
#     parallel without spinning up 3 browsers.
#   - Beat a Cloudflare wall in one context, keep the clearance there;
#     start a fresh anonymous context for the next sensitive operation.
#
# How parallelism works at the cdpilot CLI layer:
#   ID=$(cdpilot context create https://example.com)
#   ID2=$(cdpilot context create https://google.com)
#   CDPILOT_TARGET=$ID cdpilot eval 'document.title' &
#   CDPILOT_TARGET=$ID2 cdpilot eval 'document.title' &
#   wait
# Each invocation is a separate Python process with its own WS pool, talking
# to the SAME browser but a DIFFERENT tab inside a DIFFERENT context. They
# don't share cookies, storage, or auth state — but they DO share renderer
# CPU/memory (single browser process limit still applies).


async def cmd_context_create(url='about:blank'):
    """Create a fresh browser context + tab inside it. Print JSON to stdout.

    Output: {"context_id": "...", "target_id": "...", "url": "..."}
    The target_id is what CDPILOT_TARGET expects.
    """
    if not cdp_get('/json/version'):
        cmd_launch()
    # Resolve a base WS to talk to the browser itself (not a tab).
    ver = cdp_get('/json/version')
    browser_ws = ver.get('webSocketDebuggerUrl') if ver else None
    if not browser_ws:
        print('Cannot reach browser-level WS', file=sys.stderr)
        sys.exit(1)
    r = await cdp_send(browser_ws, [
        (1, "Target.createBrowserContext", {}),
    ])
    ctx_id = r.get(1, {}).get("browserContextId")
    if not ctx_id:
        print(f'createBrowserContext failed: {r.get(1)}', file=sys.stderr)
        sys.exit(1)
    r2 = await cdp_send(browser_ws, [
        (2, "Target.createTarget", {"url": url, "browserContextId": ctx_id}),
    ])
    tgt_id = r2.get(2, {}).get("targetId")
    if not tgt_id:
        # Roll back the empty context — orphaned contexts leak memory.
        await cdp_send(browser_ws, [
            (3, "Target.disposeBrowserContext", {"browserContextId": ctx_id})
        ])
        print(f'createTarget failed: {r2.get(2)}', file=sys.stderr)
        sys.exit(1)
    cdp_cache_invalidate()
    print(json.dumps({
        "context_id": ctx_id,
        "target_id": tgt_id,
        "url": url,
    }))


async def cmd_context_list():
    """List all browser contexts and their tabs as JSON."""
    ver = cdp_get('/json/version')
    browser_ws = ver.get('webSocketDebuggerUrl') if ver else None
    if not browser_ws:
        print('Cannot reach browser-level WS', file=sys.stderr)
        sys.exit(1)
    r = await cdp_send(browser_ws, [
        (1, "Target.getBrowserContexts", {}),
        (2, "Target.getTargets", {}),
    ])
    ctx_ids = r.get(1, {}).get("browserContextIds", [])
    targets = r.get(2, {}).get("targetInfos", [])
    # Group page targets by their browserContextId. Targets without a
    # browserContextId are in the default context.
    grouped = {}
    for t in targets:
        if t.get("type") != "page":
            continue
        cid = t.get("browserContextId", "default")
        grouped.setdefault(cid, []).append({
            "target_id": t.get("targetId"),
            "url": t.get("url", "")[:120],
            "title": (t.get("title") or '')[:80],
        })
    # Make sure every reported context shows up even if it has no tabs.
    for cid in ctx_ids:
        grouped.setdefault(cid, [])
    grouped.setdefault("default", grouped.get("default", []))
    print(json.dumps({
        "default_context": grouped.get("default", []),
        "browser_contexts": [
            {"context_id": cid, "tabs": grouped[cid]}
            for cid in ctx_ids
        ],
    }, indent=2))


async def cmd_context_close(context_id):
    """Destroy a browser context. All tabs inside it close automatically.

    Refuses to destroy the default context (which has no context_id anyway).
    """
    if not context_id or context_id == 'default':
        print('Cannot destroy the default context.', file=sys.stderr)
        sys.exit(1)
    ver = cdp_get('/json/version')
    browser_ws = ver.get('webSocketDebuggerUrl') if ver else None
    if not browser_ws:
        print('Cannot reach browser-level WS', file=sys.stderr)
        sys.exit(1)
    r = await cdp_send(browser_ws, [
        (1, "Target.disposeBrowserContext", {"browserContextId": context_id}),
    ])
    cdp_cache_invalidate()
    err = r.get(1, {}).get("error") if isinstance(r.get(1), dict) else None
    if err:
        print(f'disposeBrowserContext failed: {err}', file=sys.stderr)
        sys.exit(1)
    print(f'Closed context: {context_id}')


def cmd_context(*args):
    """Dispatcher for the context subcommand family.

    Usage:
      cdpilot context create [url]
      cdpilot context list
      cdpilot context close <context_id>
    """
    sub = args[0].lower() if args else None
    if sub == 'create':
        asyncio.run(cmd_context_create(args[1] if len(args) > 1 else 'about:blank'))
    elif sub == 'list':
        asyncio.run(cmd_context_list())
    elif sub == 'close':
        if len(args) < 2:
            print('Usage: cdpilot context close <context_id>', file=sys.stderr)
            sys.exit(1)
        asyncio.run(cmd_context_close(args[1]))
    else:
        print('Usage: cdpilot context [create|list|close]', file=sys.stderr)
        sys.exit(1)


async def cmd_new_tab(url='about:blank'):
    """Open a new tab."""
    import urllib.parse
    safe_chars = ":/?#[]@!$&'()*+,;="
    data = cdp_get(f'/json/new?{urllib.parse.quote(url, safe=safe_chars)}')
    cdp_cache_invalidate()
    if data:
        _mark_owned_tab(data.get("id"))
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
        cdp_cache_invalidate()
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
        cdp_cache_invalidate()
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

def cmd_proxy(*args):
    """Proxy chain management (v0.7.0 — provider-agnostic named pools).

    Usage:
      cdpilot proxy                              # show active proxy + pool list
      cdpilot proxy <url>                        # legacy: set single proxy URL
      cdpilot proxy off                          # clear all proxy state
      cdpilot proxy add <name> <url> [--geo X] [--sticky]
                                                 # register named pool
      cdpilot proxy remove <name>                # delete a pool
      cdpilot proxy use <name>|none              # activate one pool (or clear)
      cdpilot proxy list                         # show all pools + which is active
      cdpilot proxy show [<name>]                # raw URL of active or named pool (redacted)

    Examples:
      cdpilot proxy add brd  http://user-zone-resi:pass@brd.superproxy.io:22225 --geo us
      cdpilot proxy add ipr  http://user:pass@geo.iproyal.com:12321 --sticky
      cdpilot proxy use brd
      cdpilot proxy list

    Auth: include user:pass in the URL (e.g. http://USER:PASS@host:port). Chromium
    supports HTTP/SOCKS proxy auth via `--proxy-server` URL.

    Browser restart required after any change (stop → launch).
    """
    sub = args[0].lower() if args else None

    # Legacy single-URL forms (backward compat): `cdpilot proxy http://...` / `off`
    if sub and sub not in ('add', 'remove', 'rm', 'use', 'list', 'ls', 'show', 'status', 'off', ''):
        if sub.startswith('http://') or sub.startswith('https://') or sub.startswith('socks'):
            os.makedirs(os.path.dirname(PROXY_CONFIG_FILE), exist_ok=True)
            data = _proxy_config_raw()
            data['proxy'] = args[0]
            data.setdefault('pools', {})
            data.setdefault('active', None)
            _proxy_save(data)
            print(f'Proxy set: {_proxy_redact(args[0])}')
            print('Restart browser (stop → launch).')
            return

    if sub in (None, 'status'):
        active = _proxy_active_name()
        pools = _proxy_pools()
        effective = get_proxy_config()
        if active:
            print(f"Active pool: {active}")
        elif effective:
            print(f"Active proxy (legacy): {_proxy_redact(effective)}")
        else:
            print("No proxy configured.")
        print(f"Pools registered: {len(pools)}")
        for name, info in pools.items():
            marker = " *" if name == active else "  "
            geo = f" geo={info.get('geo')}" if info.get('geo') else ""
            sticky = " sticky" if info.get('sticky') else ""
            print(f"{marker} {name}: {_proxy_redact(info.get('url', ''))}{geo}{sticky}")
        return

    if sub == 'off':
        if os.path.exists(PROXY_CONFIG_FILE):
            os.remove(PROXY_CONFIG_FILE)
        print('Proxy cleared. Restart browser (stop → launch).')
        return

    if sub == 'add':
        if len(args) < 3:
            print('Usage: cdpilot proxy add <name> <url> [--geo X] [--sticky]', file=sys.stderr)
            return
        name = args[1]
        url = args[2]
        geo = None
        sticky = False
        for i, a in enumerate(args[3:], start=3):
            if a == '--geo' and i + 1 < len(args):
                geo = args[i + 1]
            elif a == '--sticky':
                sticky = True
        _proxy_add_pool(name, url, geo=geo, sticky=sticky)
        print(f'Pool added: {name} → {_proxy_redact(url)}'
              + (f' (geo={geo})' if geo else '')
              + (' (sticky)' if sticky else ''))
        active = _proxy_active_name()
        if not active:
            print(f"Note: pool registered but not active. Use: cdpilot proxy use {name}")
        return

    if sub in ('remove', 'rm'):
        if len(args) < 2:
            print('Usage: cdpilot proxy remove <name>', file=sys.stderr)
            return
        removed = _proxy_remove_pool(args[1])
        print(f"{'Removed' if removed else 'Not found:'} {args[1]}")
        if removed:
            print('Restart browser (stop → launch) if it was active.')
        return

    if sub == 'use':
        if len(args) < 2:
            print('Usage: cdpilot proxy use <name>|none', file=sys.stderr)
            return
        target = args[1].lower()
        if target in ('none', 'off', 'clear'):
            _proxy_set_active(None)
            print('Active pool cleared. Restart browser (stop → launch).')
            return
        ok = _proxy_set_active(args[1])
        if not ok:
            print(f"Pool not found: {args[1]}. Available: {', '.join(_proxy_pools().keys()) or '(none)'}",
                  file=sys.stderr)
            sys.exit(1)
        print(f'Active pool: {args[1]}. Restart browser (stop → launch).')
        return

    if sub in ('list', 'ls'):
        # Same as status but explicit
        return cmd_proxy()

    if sub == 'show':
        target = args[1] if len(args) > 1 else None
        if target:
            pools = _proxy_pools()
            if target in pools:
                print(_proxy_redact(pools[target].get('url', '')))
            else:
                print(f'Pool not found: {target}', file=sys.stderr)
                sys.exit(1)
        else:
            url = get_proxy_config()
            print(_proxy_redact(url) if url else '(none)')
        return

    print(f'Unknown subcommand: {sub}. See: cdpilot proxy', file=sys.stderr)
    sys.exit(1)

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


def cmd_browser(name=None):
    """Show or set the preferred browser (chrome|brave|chromium|edge|vivaldi|auto).

    The choice is persisted in ~/.cdpilot/browser.json and applies to all
    projects. `auto` (default) picks per-platform priority — on macOS 26
    Vivaldi is preferred over Brave due to a known Brave 1.89/macOS 26
    crash. `CHROME_BIN` env var still overrides if set.

    Usage:
      cdpilot browser                # show current + which is detected
      cdpilot browser vivaldi        # force Vivaldi
      cdpilot browser auto           # restore platform default
    """
    if name is None or name.lower() == 'status':
        pref = get_browser_preference()
        resolved = _resolve_browser_name(pref) if pref != 'auto' else None
        auto_resolved = _find_browser()
        installed = [n for n in BROWSER_BINARIES if _resolve_browser_name(n)]
        order, reason = _auto_browser_priority()
        ext_count = len(get_dev_extensions())
        print(f"Preference:  {pref}")
        if pref != 'auto':
            print(f"  resolved:  {resolved or '(not found — falling back to auto)'}")
        print(f"Auto-pick:   {auto_resolved or '(none)'}")
        print(f"  reason:    {reason}")
        print(f"  order:     {' > '.join(order)}")
        print(f"Installed:   {', '.join(installed) or '(none detected)'}")
        print(f"Dev exts:    {ext_count} registered (run `cdpilot extensions` to list)")
        return

    name = name.lower().strip()
    if name not in BROWSER_BINARIES and name != 'auto':
        valid = ', '.join(['auto'] + list(BROWSER_BINARIES.keys()))
        print(f"Invalid browser: {name}. Valid: {valid}", file=sys.stderr)
        sys.exit(1)

    if name != 'auto' and not _resolve_browser_name(name):
        print(f"⚠️  Browser '{name}' not installed on this system.", file=sys.stderr)
        candidates = BROWSER_BINARIES[name].get(platform.system(), [])
        if candidates:
            print(f"   Looked at: {candidates[0]}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(BROWSER_CONFIG_FILE), exist_ok=True)
    with open(BROWSER_CONFIG_FILE, 'w') as f:
        json.dump({'browser': name}, f)
    print(f"Browser preference: {name}")
    print('Restart the browser (`cdpilot stop` then any command) for the change to take effect.')


def cmd_health():
    """Print JSON health summary of the cdpilot browser session.

    Output keys:
      alive          — bool, CDP /json/version reachable
      port           — int, current CDP port
      project_id     — str|null, project identifier (multi-instance)
      tabs           — int, count of page targets (when alive)
      browser        — str|null, version string from /json/version
      crashes_today  — int, Brave crash dump count from macOS today
      stealth        — bool, current stealth config
      uptime_warning — str|null, hint when browser is alive but very old

    Exit codes: 0 = alive, 2 = down. Designed for shell watchdog loops:
      `until cdpilot health >/dev/null; do cdpilot launch; sleep 2; done`
    """
    import datetime as _dt
    import glob as _glob

    info = {
        'alive': False,
        'port': CDP_PORT,
        'project_id': PROJECT_ID,
        'tabs': 0,
        'browser': None,
        'crashes_today': 0,
        'stealth': get_stealth_config(),
        'uptime_warning': None,
    }
    ver = cdp_get('/json/version')
    if ver:
        info['alive'] = True
        info['browser'] = ver.get('Browser') or ver.get('browser') or ''
        targets = cdp_get('/json') or []
        info['tabs'] = sum(1 for t in targets if t.get('type') == 'page')

    # Today's crash count from macOS DiagnosticReports (Brave only).
    if platform.system() == 'Darwin':
        today = _dt.date.today().strftime('%Y-%m-%d')
        pattern = os.path.expanduser(f'~/Library/Logs/DiagnosticReports/Brave Browser-{today}-*.ips')
        info['crashes_today'] = len(_glob.glob(pattern))
        if info['crashes_today'] >= 3:
            info['uptime_warning'] = f"{info['crashes_today']} Brave crashes today — consider `cdpilot stop` then relaunch"

    print(json.dumps(info, ensure_ascii=False))
    sys.exit(0 if info['alive'] else 2)


# ─── Resource Block (perf opt-in) ───
#
# Why this exists:
#   Many automation workloads don't need images, fonts, or analytics pings.
#   Blocking them via CDP Network.setBlockedURLs cuts page load time
#   dramatically (often 3-10x) — bytes transferred drop, decoder pressure
#   drops, third-party connections drop.
#
# Stealth caveat:
#   Blocking changes the fingerprint surface — a real browser fetches images
#   and fonts. Cloudflare-class bot detectors notice missing requests. Keep
#   block-resources OFF when fighting bot challenges; turn it ON for known
#   internal/safe sites where speed matters more than blending in.
#
# Preset patterns are wildcards understood by Chromium's Network.setBlockedURLs.
BLOCK_PRESETS = {
    'images': ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.svg', '*.ico', '*.bmp'],
    'fonts':  ['*.woff', '*.woff2', '*.ttf', '*.otf', '*.eot'],
    'media':  ['*.mp4', '*.webm', '*.mp3', '*.wav', '*.ogg', '*.m4a', '*.m4v'],
    'ads': [
        '*googletagmanager.com*', '*google-analytics.com*', '*doubleclick.net*',
        '*facebook.com/tr*', '*facebook.net*', '*hotjar.com*', '*segment.io*',
        '*mixpanel.com*', '*amplitude.com*', '*googlesyndication.com*',
        '*adservice.google.*', '*ads.yahoo.com*', '*scorecardresearch.com*',
    ],
}


def get_block_config():
    """Return {'enabled': bool, 'patterns': [str, ...]} for the block system."""
    if not os.path.exists(BLOCK_CONFIG_FILE):
        return {'enabled': False, 'patterns': []}
    try:
        with open(BLOCK_CONFIG_FILE) as f:
            data = json.load(f)
        return {
            'enabled': bool(data.get('enabled', False)),
            'patterns': list(data.get('patterns', [])),
        }
    except (OSError, ValueError):
        return {'enabled': False, 'patterns': []}


def _save_block_config(enabled, patterns):
    os.makedirs(os.path.dirname(BLOCK_CONFIG_FILE), exist_ok=True)
    with open(BLOCK_CONFIG_FILE, 'w') as f:
        json.dump({'enabled': enabled, 'patterns': patterns}, f)


def cmd_block(*args):
    """Manage CDP request blocking (Network.setBlockedURLs).

    Usage:
      cdpilot block                                   # status
      cdpilot block on                                # enable with current patterns (default preset if none set)
      cdpilot block off                               # disable
      cdpilot block preset images,fonts,ads,media     # set patterns from named presets
      cdpilot block patterns '*.png' '*.woff2'        # set custom patterns directly
      cdpilot block clear                             # drop all patterns

    Effect applies on the next `cdpilot go <url>` (or any command that triggers
    navigate_collect). Existing pages keep their network policy. Opt-in only —
    breaks fingerprint plausibility, do NOT combine with stealth-mode targets.
    """
    cfg = get_block_config()

    if not args:
        print(f'Block: {"on" if cfg["enabled"] else "off"}')
        if cfg['patterns']:
            print(f'  Patterns ({len(cfg["patterns"])}):')
            for p in cfg['patterns'][:10]:
                print(f'    {p}')
            if len(cfg['patterns']) > 10:
                print(f'    ... and {len(cfg["patterns"]) - 10} more')
        else:
            print('  Patterns: (none)')
        return

    sub = args[0].lower()
    if sub in ('status',):
        cmd_block()
        return
    if sub in ('on', '1', 'true', 'yes'):
        patterns = cfg['patterns'] or (
            BLOCK_PRESETS['images'] + BLOCK_PRESETS['fonts'] + BLOCK_PRESETS['ads']
        )
        _save_block_config(True, patterns)
        print(f'Block: on ({len(patterns)} patterns)')
        print('Effect applies on next navigation.')
        return
    if sub in ('off', '0', 'false', 'no'):
        _save_block_config(False, cfg['patterns'])
        print('Block: off')
        return
    if sub == 'clear':
        _save_block_config(False, [])
        print('Block: cleared')
        return
    if sub == 'preset':
        if len(args) < 2:
            print('Usage: cdpilot block preset <names>  (e.g. images,fonts,ads,media)', file=sys.stderr)
            sys.exit(1)
        names = [n.strip().lower() for n in args[1].split(',') if n.strip()]
        unknown = [n for n in names if n not in BLOCK_PRESETS]
        if unknown:
            print(f'Unknown preset(s): {", ".join(unknown)}. Available: {", ".join(BLOCK_PRESETS)}', file=sys.stderr)
            sys.exit(1)
        patterns = []
        for n in names:
            patterns.extend(BLOCK_PRESETS[n])
        _save_block_config(True, patterns)
        print(f'Block: on — preset {",".join(names)} → {len(patterns)} patterns')
        return
    if sub == 'patterns':
        if len(args) < 2:
            print('Usage: cdpilot block patterns <pattern1> [pattern2 ...]', file=sys.stderr)
            sys.exit(1)
        patterns = list(args[1:])
        _save_block_config(True, patterns)
        print(f'Block: on — {len(patterns)} custom pattern(s)')
        return

    print(f'Unknown subcommand: {sub}. Use on|off|status|preset|patterns|clear.', file=sys.stderr)
    sys.exit(1)


def cmd_stealth(state=None):
    """Toggle stealth fingerprint patches.

    Usage:
      cdpilot stealth            # show status
      cdpilot stealth on|off     # toggle
      cdpilot stealth status     # show status (alias)

    Patches navigator.webdriver, chrome.runtime, plugins, WebGL vendor and
    permissions API to defeat the most common automation tells. Effect
    applies on the NEXT navigation (current pages keep their fingerprint).
    Zero new dependencies. Disabled by default.
    """
    if state is None or state.lower() == 'status':
        current = get_stealth_config()
        print(f'Stealth: {"on" if current else "off"}')
        if current:
            print('  Patches: navigator.webdriver, chrome.runtime, plugins, WebGL vendor, permissions, hardwareConcurrency')
        return

    s = state.lower()
    if s not in ('on', 'off', '1', '0', 'true', 'false', 'yes', 'no'):
        print(f"Invalid state: {state}. Use 'on', 'off', or 'status'.", file=sys.stderr)
        sys.exit(1)
    enabled = s in ('on', '1', 'true', 'yes')
    os.makedirs(os.path.dirname(STEALTH_CONFIG_FILE), exist_ok=True)
    with open(STEALTH_CONFIG_FILE, 'w') as f:
        json.dump({'stealth': enabled}, f)
    # Backward-compat bridge to the three-tier model: keep mode.json coherent
    # with the legacy toggle so `stealth on` -> 'undetected' (full patch) and
    # `stealth off` -> 'regular'. Without this, an existing mode.json would
    # silently override the toggle (get_mode_config reads mode.json first).
    try:
        set_mode_config('undetected' if enabled else 'regular')
    except Exception:
        pass
    print(f'Stealth: {"on" if enabled else "off"}')
    print('Effect applies on next navigation (`cdpilot go <url>`).')


# ─── Visual feedback config (default OFF) ───
#
# Why default OFF (BEHAVIOR CHANGE from 0.4.x):
#   The visual feedback layer (green glow border, fake cursor, click ripples,
#   keystroke display) was an early "is the AI working?" trust signal. In
#   real automation use it makes cdpilot feel slow and amateurish — animated
#   cursor moves take frames, the glow flashes between pages, every action
#   triggers a ripple. Defaulting OFF gives a quiet, professional experience.
#   Use `cdpilot show on` (or set `CDPILOT_MCP_SESSION=1`) to bring it back.
#
# Backwards-compat: CDPILOT_MCP_SESSION=1 still forces visual ON (used by
# the MCP server's persistent-glow flow). Existing scripts that rely on the
# visual layer can opt in via `cdpilot show on` once.

VISUAL_CONFIG_FILE = os.path.join(PROFILE_DIR, 'visual.json')


def _atomic_write_json(path, data):
    """Write JSON to `path` atomically — write to a temp file then os.replace.

    Without this, a concurrent reader (every command opens get_visual_config
    or get_fast_config) could observe a truncated file mid-write and fall
    through to the default. For the visual toggle this means glow flickering
    off for a single command. os.replace is POSIX-atomic on the same fs.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def get_visual_config():
    """Return True if the visual feedback layer should be injected on navigate."""
    # MCP persistent-glow flow takes precedence — it's how AI sessions signal
    # "I'm using this browser" to the human watching, and that promise was
    # made in 0.4.x docs. Don't break it silently.
    if os.environ.get('CDPILOT_MCP_SESSION') == '1':
        return True
    if os.environ.get('CDPILOT_SHOW') in ('1', 'true', 'yes', 'on'):
        return True
    if os.path.exists(VISUAL_CONFIG_FILE):
        try:
            with open(VISUAL_CONFIG_FILE) as f:
                return bool(json.load(f).get('enabled', False))
        except (OSError, ValueError):
            pass
    return False


def cmd_show(state=None):
    """Toggle the visual feedback layer (glow + cursor + ripples + keystrokes).

    Usage:
      cdpilot show              # status
      cdpilot show on|off       # toggle
      cdpilot show status       # status (alias)

    Default since 0.4.4: OFF. The MCP server's `CDPILOT_MCP_SESSION=1` flow
    still forces ON regardless of this setting — that's the persistent-glow
    promise to humans watching an AI session. The `cdpilot glow on/off`
    command is an explicit per-action override and is NOT gated by this
    config — call it directly to flash glow on demand without persisting.
    """
    if state is None or state.lower() == 'status':
        current = get_visual_config()
        print(f'Visual feedback: {"on" if current else "off"}')
        if os.environ.get('CDPILOT_MCP_SESSION') == '1':
            print('  (forced ON by CDPILOT_MCP_SESSION=1)')
        return
    s = state.lower()
    if s not in ('on', 'off', '1', '0', 'true', 'false', 'yes', 'no'):
        print(f"Invalid state: {state}. Use 'on', 'off', or 'status'.", file=sys.stderr)
        sys.exit(1)
    enabled = s in ('on', '1', 'true', 'yes')
    _atomic_write_json(VISUAL_CONFIG_FILE, {'enabled': enabled})
    print(f'Visual feedback: {"on" if enabled else "off"}')
    print('Effect applies on next navigation.')


# ─── Fast mode (auto-wait shrink, post-load shrink, opt-in bundle) ───
#
# A single switch that flips multiple timing knobs to "professional speed":
# - auto-wait timeout default 5000ms → 2000ms (configurable via CDPILOT_WAIT_MS)
# Visual feedback toggling has its own command (`show`) because it's a UX
# concern, not a timing one. `fast` is purely about how long we wait.

FAST_DEFAULT_WAIT_MS = 2000
NORMAL_DEFAULT_WAIT_MS = 5000


def get_fast_config():
    """Return True if fast mode is enabled."""
    if os.environ.get('CDPILOT_FAST') in ('1', 'true', 'yes', 'on'):
        return True
    if os.path.exists(FAST_CONFIG_FILE):
        try:
            with open(FAST_CONFIG_FILE) as f:
                return bool(json.load(f).get('enabled', False))
        except (OSError, ValueError):
            pass
    return False


def get_auto_wait_ms():
    """Return the effective auto-wait timeout in milliseconds.

    Resolution order: explicit CDPILOT_WAIT_MS env (user override) → fast
    mode default (2000) → normal default (5000). The env variable wins
    even over fast mode so power users can dial it independently.

    The env value is clamped to [100, 120_000]:
      - 0 would make __cdpilot_waitFor return null instantly, breaking every
        click on pages where the element renders even one paint frame late.
      - 100ms is a sane floor — single render tick + small buffer.
      - 120s (2 min) is a sane ceiling — beyond that the outer command timeout
        kicks in anyway; asyncio also handles very large floats poorly.
    """
    env = os.environ.get('CDPILOT_WAIT_MS')
    if env and env.isdigit():
        return max(100, min(int(env), 120_000))
    return FAST_DEFAULT_WAIT_MS if get_fast_config() else NORMAL_DEFAULT_WAIT_MS


def cmd_fast(state=None):
    """Toggle fast mode — shorter auto-wait, less idle padding.

    Usage:
      cdpilot fast              # status (shows effective auto-wait ms)
      cdpilot fast on|off       # toggle
      cdpilot fast status       # status (alias)

    Override the timeout independently via env CDPILOT_WAIT_MS=<ms>.
    """
    if state is None or state.lower() == 'status':
        current = get_fast_config()
        effective = get_auto_wait_ms()
        print(f'Fast mode: {"on" if current else "off"}')
        print(f'  Effective auto-wait: {effective}ms')
        return
    s = state.lower()
    if s not in ('on', 'off', '1', '0', 'true', 'false', 'yes', 'no'):
        print(f"Invalid state: {state}. Use 'on', 'off', or 'status'.", file=sys.stderr)
        sys.exit(1)
    enabled = s in ('on', '1', 'true', 'yes')
    _atomic_write_json(FAST_CONFIG_FILE, {'enabled': enabled})
    print(f'Fast mode: {"on" if enabled else "off"}')
    print(f'  Effective auto-wait: {get_auto_wait_ms()}ms')


# ─── Adaptive mode: "run fast, climb walls when seen" ───
#
# Default cdpilot mode is "fast lane" — no stealth, agile defaults. Some sites
# (Cloudflare Turnstile, hCaptcha, DataDome, PerimeterX) detect this and serve
# a challenge. Without adaptive mode the user has to manually `cdpilot stealth
# on` then re-navigate. Adaptive does it automatically:
#
#   1. cmd_go navigates as usual
#   2. _detect_captcha runs (it already runs today, just for warnings)
#   3. If CAPTCHA detected AND adaptive is ON:
#      - Persist this hostname so future visits start in stealth
#      - If stealth is currently OFF: flip it ON and re-navigate once
#      - Print what we did so the user sees the decision
#
# State persists in adaptive.json as {enabled, stealth_hosts: [hostname,...]}.
# We only AUTO-promote hostnames, never auto-demote — if you turn stealth on
# for example.com once, it stays on for example.com forever (until you
# manually clear the list). Conservative: prevents flapping when CAPTCHA
# detection has a false negative.


# ─── v0.5.1 Adaptive regression fixes ────────────────────────────────────────

class NavigationDrift(Exception):
    """Raised when post-navigation host differs from the requested host."""
    pass


async def _new_isolated_context(url='about:blank'):
    """Spawn a fresh BrowserContext + tab. Returns (ctx_id, tgt_id, tab_ws_url).

    Each call produces a fully isolated cookie/storage namespace inside the
    existing browser process. Used by adaptive escalation so known-hostile
    hosts cannot bleed cookies/TLS state from previous tasks.
    """
    browser_ws = await _get_browser_ws()
    r = await cdp_send(browser_ws, [(1, "Target.createBrowserContext", {})])
    ctx_id = r.get(1, {}).get("browserContextId")
    if not ctx_id:
        raise RuntimeError(f"Target.createBrowserContext failed: {r.get(1)}")
    r2 = await cdp_send(browser_ws, [
        (2, "Target.createTarget", {"url": url, "browserContextId": ctx_id}),
    ])
    tgt_id = r2.get(2, {}).get("targetId")
    if not tgt_id:
        try:
            await cdp_send(browser_ws, [
                (3, "Target.disposeBrowserContext", {"browserContextId": ctx_id})
            ])
        except Exception:
            pass
        raise RuntimeError(f"Target.createTarget failed: {r2.get(2)}")
    cdp_cache_invalidate()
    tab_ws = f"ws://127.0.0.1:{CDP_PORT}/devtools/page/{tgt_id}"
    return (ctx_id, tgt_id, tab_ws)


async def _dispose_context(ctx_id):
    """Dispose a browser context. Best-effort — silent on any error."""
    try:
        browser_ws = await _get_browser_ws()
        await cdp_send(browser_ws, [
            (1, "Target.disposeBrowserContext", {"browserContextId": ctx_id})
        ])
    except Exception:
        pass


async def _adaptive_current_host(ws_url):
    """Return location.host from the active tab, or '' on any failure."""
    try:
        r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {
            "expression": "location.host",
            "returnByValue": True,
        })])
        return r.get(1, {}).get("result", {}).get("value", "") or ""
    except Exception:
        return ""


async def _assert_host(ws_url, expected_host):
    """Verify that the active tab's host matches expected_host.

    Strips leading 'www.' from both sides before comparing.
    If CDPILOT_ADAPTIVE_STRICT=1: raises NavigationDrift on mismatch.
    Otherwise: writes a warning to stderr (silent log, never breaks callers).
    """
    if not expected_host:
        return
    try:
        actual = await _adaptive_current_host(ws_url)
        norm = lambda h: h[4:] if h.startswith("www.") else h
        if norm(actual) != norm(expected_host):
            msg = f"navigation drift: expected {expected_host}, got {actual}"
            if os.environ.get("CDPILOT_ADAPTIVE_STRICT") == "1":
                raise NavigationDrift(msg)
            sys.stderr.write(f"⚠️  {msg}\n")
    except NavigationDrift:
        raise
    except Exception:
        pass


def get_adaptive_config():
    """Return adaptive config with all learned-state keys carried through.

    Keys: enabled, stealth_hosts, entropy_hosts, host_tiers. The latter two
    MUST be preserved here because callers write the whole dict back via
    _atomic_write_json — dropping a key would silently erase learned state.
    """
    if not os.path.exists(ADAPTIVE_CONFIG_FILE):
        return {'enabled': False, 'stealth_hosts': [], 'entropy_hosts': {}, 'host_tiers': {}}
    try:
        with open(ADAPTIVE_CONFIG_FILE) as f:
            data = json.load(f)
        return {
            'enabled': bool(data.get('enabled', False)),
            'stealth_hosts': list(data.get('stealth_hosts', [])),
            'entropy_hosts': dict(data.get('entropy_hosts', {})),
            'host_tiers': dict(data.get('host_tiers', {})),
        }
    except (OSError, ValueError):
        return {'enabled': False, 'stealth_hosts': [], 'entropy_hosts': {}, 'host_tiers': {}}


def _adaptive_remember_host(hostname):
    """Add hostname to the stealth_hosts list. Idempotent."""
    cfg = get_adaptive_config()
    if hostname in cfg['stealth_hosts']:
        return
    cfg['stealth_hosts'].append(hostname)
    _atomic_write_json(ADAPTIVE_CONFIG_FILE, cfg)


def _escalate_tier(tier):
    """Return the next-stronger tier. undetected is the ceiling."""
    try:
        i = MODE_TIERS.index(tier)
    except ValueError:
        i = 0
    return MODE_TIERS[min(i + 1, len(MODE_TIERS) - 1)]


def _adaptive_remember_host_tier(hostname, tier):
    """Record the tier a host needs in adaptive.json under 'host_tiers'.

    Monotonic: only ever ratchets UP (regular -> stealth -> undetected),
    never down — mirrors the never-auto-demote policy of the stealth_hosts
    list so a single false-negative CAPTCHA detection can't downgrade a host.
    """
    if tier not in MODE_TIERS:
        return
    cfg = get_adaptive_config()
    host_tiers = cfg.get('host_tiers', {})
    prev = host_tiers.get(hostname)
    if prev in MODE_TIERS and MODE_TIERS.index(prev) >= MODE_TIERS.index(tier):
        return  # already at or above this tier, skip write
    host_tiers[hostname] = tier
    cfg['host_tiers'] = host_tiers
    _atomic_write_json(ADAPTIVE_CONFIG_FILE, cfg)


def _adaptive_host_tier(url):
    """Return the learned tier for a URL's host, or None if none/disabled."""
    cfg = get_adaptive_config()
    if not cfg.get('enabled'):
        return None
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return None
    tier = cfg.get('host_tiers', {}).get(host)
    return tier if tier in MODE_TIERS else None


def _adaptive_host_requires_stealth(url):
    """True if the URL's hostname is in the adaptive stealth list."""
    cfg = get_adaptive_config()
    if not cfg['enabled']:
        return False
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return False
    return host in cfg['stealth_hosts']


def cmd_adaptive(state=None):
    """Toggle adaptive mode — auto-escalate to stealth when a CAPTCHA is seen.

    Usage:
      cdpilot adaptive               # status — shows enabled + stealth host list
      cdpilot adaptive on|off        # toggle
      cdpilot adaptive clear         # drop the stealth host memory
      cdpilot adaptive forget <host> # remove one hostname from the list

    Default: OFF. When ON, cdpilot will:
      - Auto-enable stealth for known-hostile hostnames before navigating.
      - After every navigation, detect CAPTCHA and remember the hostname for
        future visits.
      - If a CAPTCHA appears AND stealth is currently off, flip stealth on and
        re-navigate once automatically.

    Never auto-demotes — once a hostname is in the list, it stays unless you
    run `cdpilot adaptive forget <host>` or `cdpilot adaptive clear`. This
    prevents flapping from a single false-negative CAPTCHA detection.
    """
    cfg = get_adaptive_config()

    if state is None or state.lower() == 'status':
        print(f'Adaptive: {"on" if cfg["enabled"] else "off"}')
        if cfg['stealth_hosts']:
            print(f'  Stealth hosts ({len(cfg["stealth_hosts"])}):')
            for h in cfg['stealth_hosts'][:10]:
                print(f'    {h}')
            if len(cfg['stealth_hosts']) > 10:
                print(f'    ... and {len(cfg["stealth_hosts"]) - 10} more')
        else:
            print('  Stealth hosts: (none)')
        return

    s = state.lower()
    if s in ('clear',):
        _atomic_write_json(ADAPTIVE_CONFIG_FILE, {'enabled': cfg['enabled'], 'stealth_hosts': []})
        print('Adaptive: stealth host list cleared')
        return
    if s in ('forget',):
        # Stub — actual hostname comes via sys.argv parsing in the dispatch
        print("Usage: cdpilot adaptive forget <hostname>", file=sys.stderr)
        sys.exit(1)
    if s not in ('on', 'off', '1', '0', 'true', 'false', 'yes', 'no'):
        print(f"Invalid state: {state}. Use 'on', 'off', 'clear', 'forget', or 'status'.", file=sys.stderr)
        sys.exit(1)
    enabled = s in ('on', '1', 'true', 'yes')
    _atomic_write_json(ADAPTIVE_CONFIG_FILE, {'enabled': enabled, 'stealth_hosts': cfg['stealth_hosts']})
    print(f'Adaptive: {"on" if enabled else "off"}')
    if enabled and not cfg['stealth_hosts']:
        print('  (no stealth hosts learned yet — visit a CAPTCHA-protected site to start the memory)')


def cmd_adaptive_forget(hostname):
    """Remove one hostname from the adaptive stealth list."""
    cfg = get_adaptive_config()
    if hostname not in cfg['stealth_hosts']:
        print(f'Adaptive: "{hostname}" was not in the stealth list')
        return
    cfg['stealth_hosts'].remove(hostname)
    _atomic_write_json(ADAPTIVE_CONFIG_FILE, cfg)
    print(f'Adaptive: forgot "{hostname}"')


def cmd_entropy(state=None):
    """Toggle behavioral entropy — humanized mouse paths, key timing, scroll easing.

    Usage:
      cdpilot entropy            # show status
      cdpilot entropy on|off     # toggle
      cdpilot entropy status     # alias

    When ON, click/fill/type/hover/drag/scroll commands use randomized
    Bezier mouse paths, Gaussian key dwell/inter-key delays, and quartic
    scroll easing. 2-5x slower per action — intentional anti-bot behavior.
    Default: OFF. Auto-enabled by adaptive escalation on CAPTCHA detect.
    Env override: CDPILOT_ENTROPY=on  |  Test seed: CDPILOT_ENTROPY_SEED=42
    """
    if state is None or state.lower() == 'status':
        current = get_entropy_config()
        print(f'Entropy: {"on" if current else "off"}')
        if current:
            print('  Behaviors: Bezier mouse, Gaussian key timing, quartic scroll, click jitter')
        return
    s = state.lower()
    if s not in ('on', 'off', '1', '0', 'true', 'false', 'yes', 'no'):
        print(f"Invalid state: {state}. Use 'on', 'off', or 'status'.", file=sys.stderr)
        sys.exit(1)
    enabled = s in ('on', '1', 'true', 'yes')
    _atomic_write_json(ENTROPY_CONFIG_FILE, {'entropy': enabled})
    print(f'Entropy: {"on" if enabled else "off"}')
    if enabled:
        print('  Effect: next click/fill/type/hover will use humanized timing (2-5x slower).')


async def _detect_captcha(ws_url):
    """Run CAPTCHA_DETECT_JS in the active page, return parsed dict.

    Returns: {"detected": bool, "types": [...], "details": [...], "error"?: str}
    Never raises — failures return {"detected": False, "error": "..."}.
    """
    try:
        r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {
            "expression": CAPTCHA_DETECT_JS,
            "returnByValue": True,
        })], timeout=5)
        raw = r.get(1, {}).get("result", {}).get("value")
        if not raw:
            return {"detected": False}
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {"detected": False, "error": "parse_failed"}
    except Exception as e:
        return {"detected": False, "error": str(e)[:120]}


# ─── Progressive-Resilience Escalation Ladder ───
# Friction levels ordered low -> high. soft_captcha is detected by the existing
# _detect_captcha (9 provider types); the other rungs come from
# FRICTION_DETECT_JS. _detect_friction merges both and reports the highest.
FRICTION_LEVELS = (
    'none', 'rate_limited', 'soft_captcha', 'login_wall', 'otp_sms', 'hard_block',
)


def _friction_backoff_enabled():
    """Whether cmd_go should auto-backoff on rate_limited. Default on."""
    return os.environ.get('CDPILOT_FRICTION_BACKOFF', 'on').lower() not in ('off', '0', 'false', 'no')


def _friction_max_retry():
    """Max rate-limit backoff retries in cmd_go. Default 2, clamped 0..5."""
    try:
        n = int(os.environ.get('CDPILOT_FRICTION_MAX_RETRY', '2'))
    except (ValueError, TypeError):
        n = 2
    return max(0, min(n, 5))


def _friction_backoff_seconds(attempt):
    """Exponential backoff with jitter: 2^attempt seconds, capped at 60s.

    attempt is 0-based (first retry -> 2s base). Adds up to 25% jitter so
    concurrent workers don't synchronize their retries.
    """
    import random as _r
    base = min(2 ** (attempt + 1), 60)
    jitter = _r.uniform(0, base * 0.25)
    return round(min(base + jitter, 60), 2)


def _friction_action(level):
    """Map a friction level to the response policy cmd_go should apply.

    ETHICS/SAFETY: login_wall, otp_sms and hard_block are NEVER bypassed
    autonomously — they hand off to the human. Only rate_limited is auto-handled
    (backoff + retry); soft_captcha defers to the existing captcha flow.

    Returns a dict: {action, level, autonomous: bool, message}.
    """
    if level == 'rate_limited':
        return {
            'action': 'backoff', 'level': level, 'autonomous': True,
            'message': 'Rate limited — exponential backoff then retry.',
        }
    if level == 'soft_captcha':
        return {
            'action': 'captcha', 'level': level, 'autonomous': True,
            'message': 'CAPTCHA — defer to detect/wait/solver flow.',
        }
    if level == 'login_wall':
        return {
            'action': 'human_login_required', 'level': level, 'autonomous': False,
            'message': '🔐 Login gerekli — kullanıcı girişi bekleniyor (otomatik giriş YOK).',
        }
    if level == 'otp_sms':
        return {
            'action': 'human_otp_required', 'level': level, 'autonomous': False,
            'message': '📱 SMS/OTP doğrulama gerekli — kullanıcı çözmeli (otomatik çözüm YOK).',
        }
    if level == 'hard_block':
        return {
            'action': 'hard_blocked', 'level': level, 'autonomous': False,
            'message': '🚫 Sert engelleme — geri çekil ve bekle.', 'backoff_suggested': True,
        }
    return {'action': 'proceed', 'level': 'none', 'autonomous': True, 'message': 'No friction.'}


async def _detect_friction(ws_url):
    """Detect the highest anti-bot friction rung on the active page.

    Runs FRICTION_DETECT_JS (rate-limit / login-wall / OTP / hard-block) and
    merges in the existing _detect_captcha result (soft_captcha). Returns the
    HIGHEST rung present per FRICTION_LEVELS ordering.

    Returns: {"level": str, "signals": [...], "detail": str, "captcha"?: {...}}
    Never raises — failures degrade to {"level": "none", ...}.
    """
    friction = {"level": "none", "signals": [], "detail": ""}
    try:
        r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {
            "expression": FRICTION_DETECT_JS,
            "returnByValue": True,
        })], timeout=5)
        raw = r.get(1, {}).get("result", {}).get("value")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("level") in FRICTION_LEVELS:
                    friction = parsed
            except (ValueError, TypeError):
                pass
    except Exception as e:
        friction = {"level": "none", "signals": [], "detail": "", "error": str(e)[:120]}

    # Merge soft_captcha from the dedicated captcha detector.
    try:
        cap = await _detect_captcha(ws_url)
    except Exception:
        cap = {"detected": False}
    if cap.get("detected"):
        cap_level = 'soft_captcha'
        # Keep whichever rung is higher in the ladder.
        cur_idx = FRICTION_LEVELS.index(friction.get('level', 'none')) if friction.get('level') in FRICTION_LEVELS else 0
        cap_idx = FRICTION_LEVELS.index(cap_level)
        if cap_idx > cur_idx:
            sigs = list(friction.get('signals', []))
            sigs.append('captcha:' + (",".join(cap.get('types', [])) or 'unknown'))
            friction = {
                'level': cap_level, 'signals': sigs,
                'detail': 'CAPTCHA challenge present (' + (",".join(cap.get('types', [])) or 'unknown') + ').',
            }
        friction['captcha'] = {'types': cap.get('types', []), 'detected': True}
    return friction


async def cmd_friction():
    """One-shot friction-level diagnostic on the active page. Prints JSON.

    Reports the highest escalation rung (none/rate_limited/soft_captcha/
    login_wall/otp_sms/hard_block) plus the recommended response policy.
    Read-only — never attempts to bypass anything.
    """
    ws, _ = get_page_ws()
    info = await _detect_friction(ws)
    action = _friction_action(info.get('level', 'none'))
    info['recommended'] = action
    print(json.dumps(info, ensure_ascii=False))


async def cmd_captcha_check():
    """One-shot CAPTCHA detection on the active page. Prints JSON.

    Exit codes: 0 = no CAPTCHA, 3 = CAPTCHA detected, 1 = error.
    Useful in scripts: `cdpilot captcha-check && do-stuff`.
    """
    ws, _ = get_page_ws()
    info = await _detect_captcha(ws)
    print(json.dumps(info, ensure_ascii=False))
    if info.get("error") and not info.get("detected"):
        sys.exit(1)
    sys.exit(3 if info.get("detected") else 0)


async def cmd_captcha_wait(timeout_arg=None):
    """Detect CAPTCHA and wait for the user to solve it.

    Behavior:
      - Interactive (stdin is a TTY): print warning, block on Enter.
      - Non-interactive (pipe / MCP): poll every 2s until the CAPTCHA
        disappears or timeout expires; emit one JSON line per poll on
        state change so callers can stream progress.

    Args:
      timeout_arg: int seconds (default 300, max 1800). Passed as string from CLI.

    Exit codes: 0 = solved (or none detected), 2 = timeout, 1 = error.
    """
    try:
        timeout = int(timeout_arg) if timeout_arg else 300
    except (ValueError, TypeError):
        print(f"Invalid timeout: {timeout_arg}", file=sys.stderr)
        sys.exit(1)
    timeout = max(5, min(timeout, 1800))

    ws, _ = get_page_ws()
    info = await _detect_captcha(ws)
    if not info.get("detected"):
        print(json.dumps({"detected": False, "status": "none"}, ensure_ascii=False))
        return

    types = ",".join(info.get("types", [])) or "unknown"
    interactive = sys.stdin.isatty() and not IS_MCP_SESSION

    if interactive:
        sys.stderr.write(f"\n⚠️  CAPTCHA tespit edildi: {types}\n")
        sys.stderr.write("    Tarayıcıda çözün, ardından Enter'a basın (Ctrl+C iptal)...\n")
        sys.stderr.flush()
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print(json.dumps({"detected": True, "status": "cancelled", "types": info.get("types", [])}, ensure_ascii=False))
            sys.exit(1)
        # Verify it's gone
        post = await _detect_captcha(ws)
        if post.get("detected"):
            print(json.dumps({"detected": True, "status": "still_present", "types": post.get("types", [])}, ensure_ascii=False))
            sys.exit(2)
        print(json.dumps({"detected": False, "status": "solved"}, ensure_ascii=False))
        return

    # Non-interactive: poll until solved or timeout
    print(json.dumps({"detected": True, "status": "waiting", "types": info.get("types", []), "timeout": timeout}, ensure_ascii=False), flush=True)
    deadline = time.time() + timeout
    poll_interval = 2.0
    while time.time() < deadline:
        await asyncio.sleep(poll_interval)
        post = await _detect_captcha(ws)
        if not post.get("detected"):
            print(json.dumps({"detected": False, "status": "solved", "elapsed": round(timeout - (deadline - time.time()), 1)}, ensure_ascii=False), flush=True)
            return
    print(json.dumps({"detected": True, "status": "timeout", "types": info.get("types", []), "waited": timeout}, ensure_ascii=False), flush=True)
    sys.exit(2)


# ─── Captcha Solver Plugin ──────────────────────────────────────────────────
# Opt-in 3rd-party captcha solver integration: 2captcha, anti-captcha, capmonster.
# API keys stored in ~/.cdpilot/captcha-providers.json (chmod 600, never in git).
# Supported types: recaptcha-v2, recaptcha-v3, hcaptcha, turnstile, funcaptcha.
# Per-solve cost ~$0.001–0.003 depending on provider and type.
# ────────────────────────────────────────────────────────────────────────────


class CaptchaSolverError(Exception):
    """Raised when a captcha solver API call fails or misconfiguration is detected."""
    pass


def _captcha_normalize_provider(name: str) -> str:
    """Normalize provider name variants to canonical form."""
    n = name.lower().strip()
    if '2captcha' in n or 'twocaptcha' in n:
        return '2captcha'
    if 'anti' in n:
        return 'anticaptcha'
    if 'monster' in n or 'capmon' in n:
        return 'capmonster'
    return n


def _captcha_load_config() -> dict:
    """Load captcha provider config from CAPTCHA_PROVIDERS_FILE.

    Returns default empty config if file is missing or corrupt.
    Format: {'providers': {'2captcha': {'api_key': '...', 'enabled': True}, ...}, 'preferred': '2captcha'}
    """
    try:
        with open(CAPTCHA_PROVIDERS_FILE) as f:
            data = json.load(f)
        return {
            'providers': {k: dict(v) for k, v in data.get('providers', {}).items()},
            'preferred': data.get('preferred', ''),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {'providers': {}, 'preferred': ''}


def _captcha_save_config(cfg: dict) -> None:
    """Write captcha config atomically with chmod 600 (API keys must not be world-readable)."""
    os.makedirs(CDPILOT_HOME, mode=0o700, exist_ok=True)
    _atomic_write_json(CAPTCHA_PROVIDERS_FILE, cfg)
    try:
        os.chmod(CAPTCHA_PROVIDERS_FILE, 0o600)
    except OSError:
        pass


def _captcha_get_preferred_provider(name: str = None):
    """Return (provider_name, api_key) for the requested or auto-selected enabled provider.

    Returns (None, None) if no enabled provider is configured.
    """
    cfg = _captcha_load_config()
    providers = cfg.get('providers', {})

    if name:
        name = _captcha_normalize_provider(name)
        p = providers.get(name, {})
        if p.get('enabled') and p.get('api_key'):
            return name, p['api_key']
        return None, None

    preferred = cfg.get('preferred', '')
    if preferred and preferred in providers:
        p = providers[preferred]
        if p.get('enabled') and p.get('api_key'):
            return preferred, p['api_key']

    for pname, p in providers.items():
        if p.get('enabled') and p.get('api_key'):
            return pname, p['api_key']

    return None, None


def _captcha_auto_enabled() -> bool:
    """Return True if captcha auto-solve mode is enabled."""
    try:
        with open(CAPTCHA_AUTO_FILE) as f:
            return bool(json.load(f).get('enabled', False))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False


def _captcha_set_auto(enabled: bool) -> None:
    """Write captcha auto-solve toggle state."""
    _atomic_write_json(CAPTCHA_AUTO_FILE, {'enabled': enabled})


async def _captcha_urlopen_async(url: str, data: bytes = None, headers: dict = None, timeout: int = 30) -> bytes:
    """urllib.request wrapper that runs in a thread executor to avoid blocking the event loop."""
    import urllib.request as _ureq
    _headers = headers or {}
    req = _ureq.Request(url, data=data, headers=_headers)

    def _sync():
        with _ureq.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


# ─── 2captcha provider ────────────────────────────────────────────────────

async def _solve_2captcha(api_key: str, captcha_type: str, site_key: str, url: str, **kwargs) -> dict:
    """Solve via 2captcha REST API (urlencoded form POST + poll).

    Returns {'token': '...', 'duration_ms': N, 'cost': 0.003, 'provider': '2captcha'}
    Raises CaptchaSolverError on API error or timeout.
    """
    import urllib.parse as _uparse

    _type_method = {
        'recaptcha-v2': 'userrecaptcha',
        'recaptcha-v3': 'userrecaptcha',
        'hcaptcha': 'hcaptcha',
        'turnstile': 'turnstile',
        'funcaptcha': 'funcaptcha',
    }
    method = _type_method.get(captcha_type, 'userrecaptcha')

    params: dict = {
        'key': api_key,
        'method': method,
        'pageurl': url,
        'json': '1',
    }
    if captcha_type in ('recaptcha-v2', 'recaptcha-v3'):
        params['googlekey'] = site_key
    elif captcha_type == 'hcaptcha':
        params['sitekey'] = site_key
    elif captcha_type == 'turnstile':
        params['sitekey'] = site_key
    elif captcha_type == 'funcaptcha':
        params['publickey'] = site_key
    else:
        params['googlekey'] = site_key

    if captcha_type == 'recaptcha-v3':
        params['version'] = 'v3'
        params['action'] = kwargs.get('action', 'verify')
        params['min_score'] = str(kwargs.get('min_score', '0.3'))

    t0 = time.time()

    body = _uparse.urlencode(params).encode()
    raw = await _captcha_urlopen_async('https://2captcha.com/in.php', data=body)
    try:
        resp = json.loads(raw)
    except (ValueError, TypeError):
        raise CaptchaSolverError(f"2captcha in.php non-JSON response: {raw[:200]!r}")

    if resp.get('status') != 1:
        raise CaptchaSolverError(f"2captcha submission failed: {resp.get('request', resp)}")

    task_id = resp['request']
    poll_url = f"https://2captcha.com/res.php?key={api_key}&action=get&id={task_id}&json=1"

    deadline = t0 + CAPTCHA_SOLVE_TIMEOUT
    while time.time() < deadline:
        await asyncio.sleep(5)
        raw2 = await _captcha_urlopen_async(poll_url)
        try:
            r2 = json.loads(raw2)
        except (ValueError, TypeError):
            continue
        if r2.get('status') == 1:
            return {
                'token': r2['request'],
                'duration_ms': int((time.time() - t0) * 1000),
                'cost': 0.003,
                'provider': '2captcha',
            }
        req_val = r2.get('request', '')
        if req_val != 'CAPCHA_NOT_READY':
            raise CaptchaSolverError(f"2captcha error: {req_val}")

    raise CaptchaSolverError(f"2captcha timeout after {CAPTCHA_SOLVE_TIMEOUT}s")


# ─── anti-captcha provider ────────────────────────────────────────────────

async def _solve_anticaptcha(api_key: str, captcha_type: str, site_key: str, url: str, **kwargs) -> dict:
    """Solve via anti-captcha.com v2 JSON API.

    Returns {'token': '...', 'duration_ms': N, 'cost': 0.003, 'provider': 'anticaptcha'}
    Raises CaptchaSolverError on API error or timeout.
    """
    _type_map = {
        'recaptcha-v2': 'NoCaptchaTaskProxyless',
        'recaptcha-v3': 'RecaptchaV3TaskProxyless',
        'hcaptcha': 'HCaptchaTaskProxyless',
        'turnstile': 'TurnstileTaskProxyless',
        'funcaptcha': 'FunCaptchaTaskProxyless',
    }
    task_type = _type_map.get(captcha_type, 'NoCaptchaTaskProxyless')

    task_body: dict = {'type': task_type, 'websiteURL': url, 'websiteKey': site_key}
    if captcha_type == 'funcaptcha':
        task_body['websitePublicKey'] = site_key
        del task_body['websiteKey']
    if captcha_type == 'recaptcha-v3':
        task_body['minScore'] = kwargs.get('min_score', 0.3)
        task_body['pageAction'] = kwargs.get('action', 'verify')

    payload = json.dumps({'clientKey': api_key, 'task': task_body}).encode()
    headers = {'Content-Type': 'application/json'}

    t0 = time.time()

    raw = await _captcha_urlopen_async('https://api.anti-captcha.com/createTask', data=payload, headers=headers)
    try:
        r = json.loads(raw)
    except (ValueError, TypeError):
        raise CaptchaSolverError(f"anticaptcha createTask non-JSON: {raw[:200]!r}")

    if r.get('errorId', 0) != 0:
        raise CaptchaSolverError(f"anticaptcha createTask error: {r.get('errorDescription', r)}")

    task_id = r['taskId']
    poll_payload = json.dumps({'clientKey': api_key, 'taskId': task_id}).encode()
    deadline = t0 + CAPTCHA_SOLVE_TIMEOUT

    while time.time() < deadline:
        await asyncio.sleep(5)
        raw2 = await _captcha_urlopen_async('https://api.anti-captcha.com/getTaskResult', data=poll_payload, headers=headers)
        try:
            r2 = json.loads(raw2)
        except (ValueError, TypeError):
            continue
        if r2.get('errorId', 0) != 0:
            raise CaptchaSolverError(f"anticaptcha poll error: {r2.get('errorDescription', r2)}")
        if r2.get('status') == 'ready':
            sol = r2.get('solution', {})
            token = sol.get('gRecaptchaResponse') or sol.get('token') or sol.get('text', '')
            return {
                'token': token,
                'duration_ms': int((time.time() - t0) * 1000),
                'cost': 0.003,
                'provider': 'anticaptcha',
            }

    raise CaptchaSolverError(f"anticaptcha timeout after {CAPTCHA_SOLVE_TIMEOUT}s")


# ─── capmonster provider ──────────────────────────────────────────────────

async def _solve_capmonster(api_key: str, captcha_type: str, site_key: str, url: str, **kwargs) -> dict:
    """Solve via capmonster.cloud (same API structure as anti-captcha).

    Returns {'token': '...', 'duration_ms': N, 'cost': 0.002, 'provider': 'capmonster'}
    Raises CaptchaSolverError on API error or timeout.
    """
    _type_map = {
        'recaptcha-v2': 'NoCaptchaTaskProxyless',
        'recaptcha-v3': 'RecaptchaV3TaskProxyless',
        'hcaptcha': 'HCaptchaTaskProxyless',
        'turnstile': 'TurnstileTaskProxyless',
        'funcaptcha': 'FunCaptchaTaskProxyless',
    }
    task_type = _type_map.get(captcha_type, 'NoCaptchaTaskProxyless')

    task_body: dict = {'type': task_type, 'websiteURL': url, 'websiteKey': site_key}
    if captcha_type == 'funcaptcha':
        task_body['websitePublicKey'] = site_key
        del task_body['websiteKey']

    payload = json.dumps({'clientKey': api_key, 'task': task_body}).encode()
    headers = {'Content-Type': 'application/json'}

    t0 = time.time()

    raw = await _captcha_urlopen_async('https://api.capmonster.cloud/createTask', data=payload, headers=headers)
    try:
        r = json.loads(raw)
    except (ValueError, TypeError):
        raise CaptchaSolverError(f"capmonster createTask non-JSON: {raw[:200]!r}")

    if r.get('errorId', 0) != 0:
        raise CaptchaSolverError(f"capmonster createTask error: {r.get('errorCode', r)}")

    task_id = r['taskId']
    poll_payload = json.dumps({'clientKey': api_key, 'taskId': task_id}).encode()
    deadline = t0 + CAPTCHA_SOLVE_TIMEOUT

    while time.time() < deadline:
        await asyncio.sleep(5)
        raw2 = await _captcha_urlopen_async('https://api.capmonster.cloud/getTaskResult', data=poll_payload, headers=headers)
        try:
            r2 = json.loads(raw2)
        except (ValueError, TypeError):
            continue
        if r2.get('errorId', 0) != 0:
            raise CaptchaSolverError(f"capmonster poll error: {r2.get('errorCode', r2)}")
        if r2.get('status') == 'ready':
            sol = r2.get('solution', {})
            token = sol.get('gRecaptchaResponse') or sol.get('token') or sol.get('text', '')
            return {
                'token': token,
                'duration_ms': int((time.time() - t0) * 1000),
                'cost': 0.002,
                'provider': 'capmonster',
            }

    raise CaptchaSolverError(f"capmonster timeout after {CAPTCHA_SOLVE_TIMEOUT}s")


_CAPTCHA_SOLVERS = {
    '2captcha': _solve_2captcha,
    'anticaptcha': _solve_anticaptcha,
    'capmonster': _solve_capmonster,
}


# ─── Site key extraction ──────────────────────────────────────────────────

_SITE_KEY_JS = r"""
(() => {
  const types = [
    { type: 'recaptcha-v2', sels: [
        '[data-sitekey]',
        '.g-recaptcha[data-sitekey]',
        'iframe[src*="recaptcha"]',
      ], attr: 'data-sitekey', srcParam: 'k' },
    { type: 'hcaptcha', sels: [
        '.h-captcha[data-sitekey]',
        '[data-hcaptcha-sitekey]',
        'iframe[src*="hcaptcha.com"]',
      ], attr: 'data-sitekey', srcParam: 'sitekey' },
    { type: 'turnstile', sels: [
        '.cf-turnstile[data-sitekey]',
        '[data-cf-turnstile-sitekey]',
        'div[data-sitekey]',
      ], attr: 'data-sitekey' },
    { type: 'funcaptcha', sels: [
        '[data-pkey]',
        'iframe[src*="arkoselabs.com"]',
        'iframe[src*="funcaptcha.com"]',
      ], attr: 'data-pkey', srcParam: 'pk' },
  ];
  for (const t of types) {
    for (const sel of t.sels) {
      const el = document.querySelector(sel);
      if (!el) continue;
      const key = el.getAttribute(t.attr);
      if (key) return JSON.stringify({type: t.type, site_key: key});
      if (t.srcParam && el.src) {
        try {
          const u = new URL(el.src);
          const k = u.searchParams.get(t.srcParam);
          if (k) return JSON.stringify({type: t.type, site_key: k});
        } catch(e) {}
      }
    }
  }
  return null;
})()
"""


async def _extract_site_key(ws_url: str, captcha_type: str = None):
    """Extract captcha site key from the current page DOM via CDP Runtime.evaluate.

    Returns dict {'type': 'recaptcha-v2', 'site_key': '...'} or None.
    captcha_type is used only as a hint; the JS probes all known types.
    """
    try:
        r = await cdp_send(ws_url, [(1, 'Runtime.evaluate', {
            'expression': _SITE_KEY_JS,
            'returnByValue': True,
        })], timeout=5)
        raw = r.get(1, {}).get('result', {}).get('value')
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


# ─── Token injection ──────────────────────────────────────────────────────

_TOKEN_INJECT_JS = r"""
(function(token, captchaType) {
  try {
    var injected = false;
    if (captchaType === 'recaptcha-v2' || captchaType === 'recaptcha-v3' || captchaType === 'recaptcha') {
      var el = document.getElementById('g-recaptcha-response');
      if (!el) el = document.querySelector('[name="g-recaptcha-response"]');
      if (el) { el.value = token; el.innerHTML = token; injected = true; }
      // Trigger grecaptcha callback
      try {
        var clients = window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients;
        if (clients) {
          for (var k in clients) {
            var c = clients[k];
            if (c && c.callback) { c.callback(token); break; }
          }
        }
      } catch(e) {}
    } else if (captchaType === 'hcaptcha') {
      var el = document.querySelector('[name="h-captcha-response"]');
      if (!el) el = document.querySelector('textarea[name="h-captcha-response"]');
      if (el) { el.value = token; injected = true; }
      try { if (window.hcaptcha) window.hcaptcha.setResponse(token); } catch(e) {}
    } else if (captchaType === 'turnstile') {
      var el = document.querySelector('[name="cf-turnstile-response"]');
      if (el) { el.value = token; injected = true; }
    } else if (captchaType === 'funcaptcha') {
      var el = document.querySelector('[name="fc-token"]');
      if (!el) el = document.querySelector('[id*="FunCaptcha"]');
      if (el) { el.value = token; injected = true; }
    }
    // Generic callback probe
    var cbAttr = document.querySelector('[data-callback]');
    if (cbAttr) {
      var cbName = cbAttr.getAttribute('data-callback');
      if (cbName && window[cbName]) { try { window[cbName](token); } catch(e) {} }
    }
    return injected;
  } catch(e) {
    return false;
  }
})(CDPILOT_TOKEN_PLACEHOLDER, CDPILOT_TYPE_PLACEHOLDER)
"""


async def _inject_captcha_token(ws_url: str, captcha_type: str, token: str) -> bool:
    """Inject solved captcha token into the active page via CDP Runtime.evaluate.

    Returns True if at least one response element was found and filled.
    Never raises — all errors return False.
    """
    # Safe string interpolation — token is base64-like, no JS injection risk
    # but we still json.dumps() to properly escape quotes/backslashes.
    js = _TOKEN_INJECT_JS.replace(
        'CDPILOT_TOKEN_PLACEHOLDER', json.dumps(token)
    ).replace(
        'CDPILOT_TYPE_PLACEHOLDER', json.dumps(captcha_type)
    )
    try:
        r = await cdp_send(ws_url, [(1, 'Runtime.evaluate', {
            'expression': js,
            'returnByValue': True,
        })], timeout=5)
        return bool(r.get(1, {}).get('result', {}).get('value', False))
    except Exception:
        return False


# ─── Internal solve entry point ──────────────────────────────────────────

async def _captcha_solve_internal(captcha_type: str, site_key: str, url: str,
                                   provider_name: str = None) -> dict | None:
    """Solve a captcha using the configured provider. Returns result dict or None.

    Used by both cmd_captcha_solve and _captcha_auto_solve_if_enabled.
    Never raises — errors returned as {'error': '...'}.
    """
    pname, api_key = _captcha_get_preferred_provider(provider_name)
    if not pname:
        return {'error': 'no_provider_configured'}

    solver_fn = _CAPTCHA_SOLVERS.get(pname)
    if not solver_fn:
        return {'error': f'unknown_provider:{pname}'}

    try:
        return await solver_fn(api_key, captcha_type, site_key, url)
    except CaptchaSolverError as e:
        return {'error': str(e)}
    except Exception as e:
        return {'error': f'unexpected:{e}'}


# ─── Adaptive auto-solve integration ─────────────────────────────────────

async def _captcha_auto_solve_if_enabled(ws_url: str, info: dict, current_url: str) -> None:
    """If auto-solve is enabled and a provider is configured, attempt to solve the captcha.

    Called from cmd_go after adaptive escalation block. Best-effort, non-blocking —
    all output goes to stderr so stdout (page content) is unaffected.
    """
    if not _captcha_auto_enabled():
        return
    pname, _ = _captcha_get_preferred_provider()
    if not pname:
        return

    types = info.get('types', [])
    # Priority order: recaptcha-v2 > hcaptcha > turnstile
    preferred_order = ['recaptcha-v2', 'hcaptcha', 'turnstile', 'recaptcha-v3', 'funcaptcha']
    captcha_type = None
    for t in preferred_order:
        if t in types:
            captcha_type = t
            break
    if not captcha_type and types:
        captcha_type = types[0]
    if not captcha_type:
        return

    try:
        meta = await _extract_site_key(ws_url, captcha_type)
        if not meta or not meta.get('site_key'):
            sys.stderr.write(f'⚙️  Captcha auto-solve: could not extract site key for {captcha_type}\n')
            return
        resolved_type = meta.get('type', captcha_type)
        site_key = meta['site_key']
        sys.stderr.write(f'⚙️  Captcha auto-solve: solving {resolved_type} via {pname}...\n')
        result = await _captcha_solve_internal(resolved_type, site_key, current_url)
        if not result or 'error' in result:
            sys.stderr.write(f'⚙️  Captcha auto-solve failed: {result}\n')
            return
        injected = await _inject_captcha_token(ws_url, resolved_type, result['token'])
        sys.stderr.write(
            f'⚙️  Captcha auto-solve: token injected={injected}, '
            f'duration={result.get("duration_ms", "?")}ms\n'
        )
    except Exception as e:
        sys.stderr.write(f'⚙️  Captcha auto-solve error: {e}\n')


# ─── CLI command functions ────────────────────────────────────────────────

def cmd_captcha_config(*args):
    """Configure a captcha solver provider.

    Usage:
      cdpilot captcha config --provider 2captcha --api-key YOUR_KEY
      cdpilot captcha config --provider anticaptcha --api-key YOUR_KEY
      cdpilot captcha config --provider 2captcha --disable
      cdpilot captcha config --provider 2captcha --enable

    Saves to ~/.cdpilot/captcha-providers.json (chmod 600).
    Sets saved provider as preferred unless --no-preferred is given.
    """
    arg_list = list(args)

    def _get_flag(flag):
        for i, a in enumerate(arg_list):
            if a == flag and i + 1 < len(arg_list):
                return arg_list[i + 1]
        return None

    provider = _get_flag('--provider') or _get_flag('-p')
    api_key = _get_flag('--api-key') or _get_flag('--key')
    disable = '--disable' in arg_list
    enable = '--enable' in arg_list
    no_preferred = '--no-preferred' in arg_list

    if not provider:
        print("Usage: cdpilot captcha config --provider <name> --api-key <key>", file=sys.stderr)
        sys.exit(1)

    provider = _captcha_normalize_provider(provider)
    cfg = _captcha_load_config()
    entry = cfg['providers'].get(provider, {'api_key': '', 'enabled': True})

    if api_key:
        entry['api_key'] = api_key
    if disable:
        entry['enabled'] = False
    if enable:
        entry['enabled'] = True
    if not disable and not enable:
        entry['enabled'] = True

    cfg['providers'][provider] = entry

    if not no_preferred and api_key:
        cfg['preferred'] = provider

    _captcha_save_config(cfg)
    pref_note = ' (preferred)' if cfg.get('preferred') == provider else ''
    action = 'disabled' if disable else ('enabled' if enable else 'configured')
    print(f'Provider {action}: {provider}{pref_note}')


async def cmd_captcha_solve_cli(*args):
    """Solve a captcha manually (debug / testing).

    Usage:
      cdpilot captcha solve --type recaptcha-v2 --site-key SK --url URL
      cdpilot captcha solve --provider 2captcha --type hcaptcha --site-key SK --url URL

    Returns JSON: {"token": "...", "duration_ms": N, "cost": 0.003, "provider": "..."}
    """
    arg_list = list(args)

    def _get_flag(flag):
        for i, a in enumerate(arg_list):
            if a == flag and i + 1 < len(arg_list):
                return arg_list[i + 1]
        return None

    captcha_type = _get_flag('--type') or _get_flag('-t')
    site_key = _get_flag('--site-key') or _get_flag('--sitekey')
    url = _get_flag('--url') or _get_flag('-u')
    provider = _get_flag('--provider') or _get_flag('-p')

    if not captcha_type or not site_key or not url:
        print("Usage: cdpilot captcha solve --type TYPE --site-key SK --url URL", file=sys.stderr)
        sys.exit(1)

    result = await _captcha_solve_internal(captcha_type, site_key, url, provider_name=provider)
    if result and 'error' in result:
        print(json.dumps({'error': result['error']}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))


def cmd_captcha_auto_toggle(*args):
    """Toggle captcha auto-solve mode (integrated with adaptive layer).

    Usage:
      cdpilot captcha auto on   # enable: adaptive layer will auto-solve on detect
      cdpilot captcha auto off  # disable
      cdpilot captcha auto      # show status
    """
    arg_list = list(args)
    if not arg_list or arg_list[0].lower() in ('status', ''):
        current = _captcha_auto_enabled()
        print(f'Captcha auto-solve: {"on" if current else "off"}')
        return
    s = arg_list[0].lower()
    if s not in ('on', 'off', '1', '0', 'true', 'false', 'yes', 'no'):
        print(f"Invalid state: {s}. Use 'on' or 'off'.", file=sys.stderr)
        sys.exit(1)
    enabled = s in ('on', '1', 'true', 'yes')
    _captcha_set_auto(enabled)
    print(f'Captcha auto-solve: {"on" if enabled else "off"}')
    if enabled:
        pname, _ = _captcha_get_preferred_provider()
        if not pname:
            print("  Warning: no provider configured. Run: cdpilot captcha config --provider 2captcha --api-key KEY")


async def cmd_captcha_status():
    """Show captcha solver configuration status.

    Prints JSON: {"configured": [...], "preferred": "...", "auto_enabled": bool}
    """
    cfg = _captcha_load_config()
    configured = [
        {'name': k, 'enabled': bool(v.get('enabled')), 'has_key': bool(v.get('api_key'))}
        for k, v in cfg.get('providers', {}).items()
    ]
    print(json.dumps({
        'configured': configured,
        'preferred': cfg.get('preferred', ''),
        'auto_enabled': _captcha_auto_enabled(),
    }, ensure_ascii=False))


async def cmd_captcha_balance():
    """Query account balance for each configured enabled provider.

    Prints JSON: {"2captcha": 1.23, "anticaptcha": 0.50, ...}
    """
    import urllib.parse as _uparse
    cfg = _captcha_load_config()
    results = {}

    for pname, pdata in cfg.get('providers', {}).items():
        if not pdata.get('enabled') or not pdata.get('api_key'):
            continue
        api_key = pdata['api_key']
        try:
            if pname == '2captcha':
                url = f'https://2captcha.com/res.php?key={_uparse.quote(api_key)}&action=getbalance&json=1'
                raw = await _captcha_urlopen_async(url)
                r = json.loads(raw)
                if r.get('status') == 1:
                    results[pname] = float(r.get('request', 0))
                else:
                    results[pname] = {'error': r.get('request', 'unknown')}
            elif pname in ('anticaptcha', 'capmonster'):
                base = 'https://api.anti-captcha.com' if pname == 'anticaptcha' else 'https://api.capmonster.cloud'
                payload = json.dumps({'clientKey': api_key}).encode()
                raw = await _captcha_urlopen_async(f'{base}/getBalance', data=payload,
                                                    headers={'Content-Type': 'application/json'})
                r = json.loads(raw)
                if r.get('errorId', 0) == 0:
                    results[pname] = float(r.get('balance', 0))
                else:
                    results[pname] = {'error': r.get('errorDescription', 'unknown')}
        except Exception as e:
            results[pname] = {'error': str(e)[:120]}

    print(json.dumps(results, ensure_ascii=False))


async def cmd_captcha_dispatch(args: list) -> None:
    """Top-level dispatcher for 'cdpilot captcha <subcommand> [args...]'.

    Subcommands: config, solve, auto, status, balance
    """
    if not args:
        print(
            "Usage: cdpilot captcha <subcommand> [options]\n"
            "  config  --provider NAME --api-key KEY\n"
            "  solve   --type TYPE --site-key SK --url URL [--provider NAME]\n"
            "  auto    on|off\n"
            "  status\n"
            "  balance",
            file=sys.stderr
        )
        sys.exit(1)

    sub = args[0].lower()
    rest = args[1:]

    if sub == 'config':
        cmd_captcha_config(*rest)
    elif sub == 'solve':
        await cmd_captcha_solve_cli(*rest)
    elif sub == 'auto':
        cmd_captcha_auto_toggle(*rest)
    elif sub == 'status':
        await cmd_captcha_status()
    elif sub == 'balance':
        await cmd_captcha_balance()
    else:
        print(f"Unknown captcha subcommand: {sub}", file=sys.stderr)
        sys.exit(1)


# ─── Amazon classic image CAPTCHA (local OCR + BYOK image solvers) ────────
# amazon.com rate-limit page: "Enter the characters you see below". The image
# is a 6-char distorted glyph string at a fixed URL pattern. The optional
# `amazoncaptcha` PyPI lib (pure-Python + Pillow, MIT) OCRs it offline with
# ~90% accuracy. It is NOT a mandatory dependency — imported lazily.
# BYOK fallback: CapSolver / 2Captcha image-to-text endpoints (HTTP only).


async def _detect_amazon_captcha(ws_url: str) -> dict:
    """Return {'detected': bool, 'img_src': str, 'input_id': str} for Amazon classic CAPTCHA.

    Probes the active page for the #captchacharacters input + captcha image.
    Never raises.
    """
    info = await _detect_captcha(ws_url)
    if not info.get('detected'):
        return {'detected': False}
    for d in info.get('details', []):
        if d.get('type') == 'amazon-classic':
            return {
                'detected': True,
                'img_src': d.get('img_src', ''),
                'input_id': d.get('input_id', 'captchacharacters'),
            }
    return {'detected': False}


async def _fetch_image_bytes(ws_url: str, img_src: str) -> bytes | None:
    """Download the captcha image bytes. Uses urllib (image URLs are public CDN)."""
    if not img_src:
        return None
    try:
        return await _captcha_urlopen_async(img_src, timeout=15)
    except Exception:
        return None


def _solve_amazon_local(img_bytes: bytes) -> str | None:
    """OCR Amazon classic CAPTCHA with the OPTIONAL amazoncaptcha library.

    Returns the solved string, or None if the library is unavailable or fails.
    Raises ImportError-as-signal via returning None; caller prints install hint.
    """
    try:
        from amazoncaptcha import AmazonCaptcha  # optional dependency
    except ImportError:
        return None
    try:
        import io as _io
        cap = AmazonCaptcha(_io.BytesIO(img_bytes))
        solution = cap.solve()
        if solution and solution.lower() != 'not solved':
            return solution
    except Exception:
        return None
    return None


async def _solve_image_byok(img_bytes: bytes) -> dict:
    """Solve an image CAPTCHA via a BYOK provider (CapSolver / 2Captcha).

    Reads CAPSOLVER_API_KEY then TWOCAPTCHA_API_KEY from the environment.
    Only stdlib HTTP — no new dependency. Returns {'token': text} or {'error': ...}.
    """
    import base64 as _b64
    b64 = _b64.b64encode(img_bytes).decode('ascii')

    capsolver_key = os.environ.get('CAPSOLVER_API_KEY')
    if capsolver_key:
        try:
            payload = json.dumps({
                'clientKey': capsolver_key,
                'task': {'type': 'ImageToTextTask', 'body': b64},
            }).encode()
            raw = await _captcha_urlopen_async(
                'https://api.capsolver.com/createTask', data=payload,
                headers={'Content-Type': 'application/json'}, timeout=60,
            )
            r = json.loads(raw)
            if r.get('errorId', 0) == 0:
                text = (r.get('solution') or {}).get('text', '')
                if text:
                    return {'token': text, 'provider': 'capsolver'}
            return {'error': f"capsolver: {r.get('errorDescription', r)}"}
        except Exception as e:
            return {'error': f'capsolver: {e}'}

    twocaptcha_key = os.environ.get('TWOCAPTCHA_API_KEY')
    if twocaptcha_key:
        import urllib.parse as _uparse
        try:
            body = _uparse.urlencode({
                'key': twocaptcha_key, 'method': 'base64',
                'body': b64, 'json': '1',
            }).encode()
            raw = await _captcha_urlopen_async('https://2captcha.com/in.php', data=body, timeout=30)
            resp = json.loads(raw)
            if resp.get('status') != 1:
                return {'error': f"2captcha submit: {resp.get('request', resp)}"}
            task_id = resp['request']
            poll = f"https://2captcha.com/res.php?key={twocaptcha_key}&action=get&id={task_id}&json=1"
            deadline = time.time() + CAPTCHA_SOLVE_TIMEOUT
            while time.time() < deadline:
                await asyncio.sleep(5)
                r2 = json.loads(await _captcha_urlopen_async(poll, timeout=15))
                if r2.get('status') == 1:
                    return {'token': r2['request'], 'provider': '2captcha'}
                if r2.get('request') != 'CAPCHA_NOT_READY':
                    return {'error': f"2captcha: {r2.get('request')}"}
            return {'error': '2captcha timeout'}
        except Exception as e:
            return {'error': f'2captcha: {e}'}

    return {'error': 'no_byok_key'}


async def _fill_amazon_solution(ws_url: str, input_id: str, solution: str) -> bool:
    """Type the solution into the Amazon CAPTCHA input and submit. Returns True on success."""
    safe_id = json.dumps(input_id)
    safe_val = json.dumps(solution)
    js = f"""
    (function() {{
      try {{
        var el = document.getElementById({safe_id}) || document.querySelector('#captchacharacters');
        if (!el) return false;
        var setter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, {safe_val});
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        var form = el.form || el.closest('form');
        if (form) {{ form.submit(); return true; }}
        var btn = document.querySelector('button[type=submit], input[type=submit]');
        if (btn) {{ btn.click(); return true; }}
        return true;
      }} catch(e) {{ return false; }}
    }})()
    """
    try:
        r = await cdp_send(ws_url, [(1, 'Runtime.evaluate', {
            'expression': js, 'returnByValue': True,
        })], timeout=5)
        return bool(r.get(1, {}).get('result', {}).get('value', False))
    except Exception:
        return False


async def cmd_press_hold(selector=None):
    """Solve a PerimeterX/HUMAN "Press & Hold" challenge (standalone, opt-in).

    Performs a humanized press->hold(with micro-tremor)->release gesture on the
    hold target. If no selector is given, auto-locates the px-captcha widget
    (#px-captcha / [class*="px-captcha"] / "press & hold" text). Prints JSON;
    exit 0 = solved, 1 = not solved / target not found.

    Usage:
      cdpilot press-hold              # auto-find the px-captcha target
      cdpilot press-hold "#px-captcha button"
    """
    if not cdp_get("/json/version"):
        print(json.dumps({'solved': False, 'error': 'no_browser',
                          'hint': 'Run: cdpilot launch'}, ensure_ascii=False))
        sys.exit(1)
    ws, _ = get_page_ws()
    res = await _solve_press_and_hold(ws, target_sel=selector)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get('solved') else 1)


async def cmd_captcha_solve(provider=None):
    """Solve the CAPTCHA on the current page (opt-in).

    Providers:
      amazon-local (default) — OCR Amazon classic image CAPTCHA with the optional
                               `amazoncaptcha` lib (pip install amazoncaptcha).
      capsolver / 2captcha   — BYOK image-to-text via CAPSOLVER_API_KEY /
                               TWOCAPTCHA_API_KEY env vars (stdlib HTTP only).

    Detects Amazon classic CAPTCHA (#captchacharacters + captcha image), solves,
    fills the input and submits. Prints JSON; exit 0 = solved, 3 = no captcha,
    1 = error / unsolvable.
    """
    provider = (provider or 'amazon-local').lower()
    ws, _ = get_page_ws()

    # PerimeterX / HUMAN "Press & Hold" is a behavioural (not token) challenge:
    # there is no provider to call, the only solution is a real humanized
    # press->hold->release gesture. Route it automatically whenever detected,
    # regardless of the requested provider, before the Amazon/BYOK path.
    pre = await _detect_captcha(ws)
    if 'perimeterx' in (pre.get('types') or []):
        res = await _solve_press_and_hold(ws)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get('solved') else 1)

    amz = await _detect_amazon_captcha(ws)
    if not amz.get('detected'):
        # Not an Amazon classic captcha — report what (if anything) was found.
        info = await _detect_captcha(ws)
        print(json.dumps({
            'solved': False, 'status': 'no_amazon_captcha',
            'detected_types': info.get('types', []),
        }, ensure_ascii=False))
        sys.exit(3 if not info.get('detected') else 1)

    img_src = amz.get('img_src', '')
    input_id = amz.get('input_id', 'captchacharacters')
    img_bytes = await _fetch_image_bytes(ws, img_src)
    if not img_bytes:
        print(json.dumps({'solved': False, 'error': 'image_fetch_failed', 'img_src': img_src}, ensure_ascii=False))
        sys.exit(1)

    solution = None
    used_provider = None

    if provider in ('amazon-local', 'amazon', 'local'):
        solution = _solve_amazon_local(img_bytes)
        used_provider = 'amazon-local'
        if solution is None:
            # Distinguish "lib missing" from "lib failed".
            try:
                import amazoncaptcha  # noqa: F401
                print(json.dumps({
                    'solved': False, 'status': 'ocr_failed',
                    'provider': 'amazon-local',
                    'hint': 'OCR returned no result; retry or use --provider capsolver',
                }, ensure_ascii=False))
            except ImportError:
                print(json.dumps({
                    'solved': False, 'status': 'amazoncaptcha_not_installed',
                    'hint': 'amazoncaptcha not installed. Run: pip install amazoncaptcha (optional)',
                }, ensure_ascii=False))
            sys.exit(1)
    elif provider in ('capsolver', '2captcha', 'twocaptcha'):
        res = await _solve_image_byok(img_bytes)
        if 'error' in res:
            if res['error'] == 'no_byok_key':
                print(json.dumps({
                    'solved': False, 'status': 'no_byok_key',
                    'hint': 'Set CAPSOLVER_API_KEY or TWOCAPTCHA_API_KEY in the environment',
                }, ensure_ascii=False))
            else:
                print(json.dumps({'solved': False, 'error': res['error']}, ensure_ascii=False))
            sys.exit(1)
        solution = res.get('token')
        used_provider = res.get('provider', provider)
    else:
        print(json.dumps({'solved': False, 'error': f'unknown_provider:{provider}'}, ensure_ascii=False))
        sys.exit(1)

    if not solution:
        print(json.dumps({'solved': False, 'error': 'empty_solution', 'provider': used_provider}, ensure_ascii=False))
        sys.exit(1)

    filled = await _fill_amazon_solution(ws, input_id, solution)
    print(json.dumps({
        'solved': True, 'solution': solution, 'provider': used_provider,
        'submitted': filled,
    }, ensure_ascii=False))
    sys.exit(0)


# ─── Profile warm-up (reCAPTCHA v3 score aging) ──────────────────────────
# New browser profiles get a -0.5 reCAPTCHA v3 trust penalty. Browsing a few
# popular, safe sites ages the cookie jar / history so the profile reads as
# "established", lifting the v3 score. Opt-in, uses the already-open session.

WARM_SAFE_SITES = [
    'https://en.wikipedia.org/wiki/Web_browser',
    'https://github.com/',
    'https://stackoverflow.com/',
    'https://news.ycombinator.com/',
    'https://www.bbc.com/news',
    'https://www.reddit.com/',
    'https://duckduckgo.com/',
    'https://www.wikipedia.org/',
]


async def cmd_profile_warm(minutes=None, sites=None):
    """Warm up the current profile by browsing safe popular sites (opt-in).

    Ages cookies/history to boost reCAPTCHA v3 score. Uses the already-open
    browser session (does not launch). Default ~2 minutes over a hardcoded
    safe site list with randomized dwell + light scrolling between visits.

    Args:
      minutes: budget in minutes (default 2, max 30). String from CLI.
      sites:   optional comma-separated override list of URLs.
    """
    import random as _r
    try:
        budget_min = float(minutes) if minutes else 2.0
    except (ValueError, TypeError):
        budget_min = 2.0
    budget_min = max(0.5, min(budget_min, 30.0))

    site_list = WARM_SAFE_SITES
    if sites:
        if isinstance(sites, str):
            site_list = [s.strip() for s in sites.split(',') if s.strip()]
        else:
            site_list = list(sites)
    if not site_list:
        site_list = WARM_SAFE_SITES

    if not cdp_get("/json/version"):
        print(json.dumps({'error': 'no_browser', 'hint': 'Run: cdpilot launch'}, ensure_ascii=False))
        sys.exit(1)

    ws, _ = get_page_ws()
    deadline = time.time() + budget_min * 60.0
    rnd = _r.Random()
    visited = 0
    total = len(site_list)

    for idx, url in enumerate(site_list, 1):
        if time.time() >= deadline:
            break
        try:
            await navigate_collect(ws, url)
            visited += 1
            sys.stderr.write(f"🔥 Warming profile: visited {visited}/{total} sites... ({url})\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"🔥 Warm: skip {url} ({str(e)[:60]})\n")
            continue

        # Light scroll to look engaged (reuses humanized scroll).
        try:
            await _humanize_scroll(ws, rnd.randint(400, 1200))
        except Exception:
            pass

        # Random aging delay 5-15s, but never overrun the budget.
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(rnd.uniform(5, 15), max(0.1, remaining)))

    print(json.dumps({
        'warmed': True, 'visited': visited, 'sites': total,
        'budget_minutes': budget_min,
    }, ensure_ascii=False))


async def cmd_profile_dispatch(args: list) -> None:
    """Top-level dispatcher for 'cdpilot profile <subcommand> [args...]'.

    Subcommands:
      warm [--minutes N] [--sites url1,url2]   Warm up profile (reCAPTCHA v3 aging).
    """
    if not args:
        print(
            "Usage: cdpilot profile <subcommand>\n"
            "  warm [--minutes N] [--sites url1,url2,...]   Age cookies/history to boost reCAPTCHA v3 score",
            file=sys.stderr,
        )
        sys.exit(1)

    sub = args[0].lower()
    rest = args[1:]

    def _get_flag(flag):
        for i, a in enumerate(rest):
            if a == flag and i + 1 < len(rest):
                return rest[i + 1]
            if a.startswith(flag + '='):
                return a.split('=', 1)[1]
        return None

    if sub == 'warm':
        await cmd_profile_warm(
            minutes=_get_flag('--minutes') or _get_flag('-m'),
            sites=_get_flag('--sites'),
        )
    else:
        print(f"Unknown profile subcommand: {sub}", file=sys.stderr)
        sys.exit(1)


# ─── End Captcha Solver Plugin ───────────────────────────────────────────


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


# ─── Browserbase-Compatible Local API ───

DEFAULT_MAX_SESSIONS = int(os.environ.get('CDPILOT_MAX_SESSIONS', '10'))
_api_session_store: dict = {}  # session_id -> session_dict


def _api_make_session_id() -> str:
    """Generate sess_<8 hex chars> unique ID."""
    return 'sess_' + secrets.token_hex(4)


def _api_create_session(opts: dict) -> dict:
    """Launch browser for a new API session. Returns session dict."""
    if len(_api_session_store) >= DEFAULT_MAX_SESSIONS:
        raise ValueError("Maximum session limit reached")

    session_id = _api_make_session_id()
    proj_id = f'api-{session_id}'
    port = _allocate_port(proj_id)
    created_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    sess = {
        'id': session_id,
        'createdAt': created_at,
        'projectId': proj_id,
        'status': 'RUNNING',
        'connectUrl': '',
        'seleniumRemoteUrl': None,
        'signingKey': None,
        'port': port,
    }

    if os.environ.get('CDPILOT_API_TEST_MODE') == '1':
        sess['connectUrl'] = 'ws://localhost:19999/devtools/browser/test-uuid'
    else:
        py_bin = sys.executable
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cdpilot.py')
        env = os.environ.copy()
        env['CDP_PORT'] = str(port)
        env['CDPILOT_PROJECT_ID'] = proj_id
        subprocess.Popen([py_bin, script, 'launch'], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        found = False
        for _ in range(20):  # 10 seconds timeout
            try:
                with urllib.request.urlopen(
                    f'http://127.0.0.1:{port}/json/version', timeout=1
                ) as r:
                    data = json.loads(r.read().decode())
                    sess['connectUrl'] = data.get('webSocketDebuggerUrl', '')
                    found = True
                    break
            except Exception:
                time.sleep(0.5)

        if not found:
            _stop_browser_on_port(port)
            raise RuntimeError("Browser failed to start or CDP endpoint unreachable")

    _api_session_store[session_id] = sess
    return sess


def _api_get_session(session_id: str) -> dict | None:
    return _api_session_store.get(session_id)


def _api_release_session(session_id: str) -> bool:
    """Stop browser for session, remove from store."""
    sess = _api_session_store.get(session_id)
    if not sess:
        return False
    port = sess.get('port')
    if port:
        _stop_browser_on_port(port)
    sess['status'] = 'STOPPED'
    del _api_session_store[session_id]
    return True


class BrowserbaseHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # quiet

    def _send_json(self, code: int, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parse_body(self) -> dict:
        try:
            clen = int(self.headers.get('Content-Length', 0))
            if clen == 0:
                return {}
            return json.loads(self.rfile.read(clen).decode())
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split('?')[0].rstrip('/')
        if not path:
            path = '/'
        parts = [p for p in path.split('/') if p]  # non-empty segments

        if path == '/healthz':
            return self._send_json(200, {'status': 'ok', 'version': __version__})

        if path == '/v1/sessions':
            return self._send_json(200, list(_api_session_store.values()))

        # /v1/sessions/{id}
        if len(parts) == 3 and parts[0] == 'v1' and parts[1] == 'sessions':
            sess = _api_get_session(parts[2])
            if sess:
                return self._send_json(200, sess)
            return self._send_json(404, {'error': {'message': 'Session not found', 'code': 'not_found'}})

        # /v1/sessions/{id}/debug
        if (len(parts) == 4 and parts[0] == 'v1' and parts[1] == 'sessions'
                and parts[3] == 'debug'):
            sess = _api_get_session(parts[2])
            if sess:
                port = sess.get('port', 9222)
                ws = sess.get('connectUrl', '')
                inspector = (f'http://localhost:{port}/devtools/inspector.html?ws='
                             + ws.replace('ws://', '').replace('wss://', ''))
                return self._send_json(200, {
                    'debuggerUrl': inspector,
                    'debuggerFullscreenUrl': inspector + '&fill',
                })
            return self._send_json(404, {'error': {'message': 'Session not found', 'code': 'not_found'}})

        self._send_json(404, {'error': {'message': 'Not found', 'code': 'not_found'}})

    def do_POST(self):
        path = self.path.split('?')[0].rstrip('/')
        parts = [p for p in path.split('/') if p]

        if path == '/v1/sessions':
            try:
                sess = _api_create_session(self._parse_body())
                return self._send_json(201, sess)
            except ValueError as e:
                return self._send_json(400, {'error': {'message': str(e), 'code': 'limit_exceeded'}})
            except Exception as e:
                return self._send_json(500, {'error': {'message': str(e), 'code': 'server_error'}})

        # /v1/sessions/{id}/release
        if (len(parts) == 4 and parts[0] == 'v1' and parts[1] == 'sessions'
                and parts[3] == 'release'):
            if _api_release_session(parts[2]):
                return self._send_json(200, {'status': 'ok'})
            return self._send_json(404, {'error': {'message': 'Session not found', 'code': 'not_found'}})

        self._send_json(404, {'error': {'message': 'Not found', 'code': 'not_found'}})

    def do_DELETE(self):
        path = self.path.split('?')[0].rstrip('/')
        parts = [p for p in path.split('/') if p]

        # DELETE /v1/sessions/{id}
        if len(parts) == 3 and parts[0] == 'v1' and parts[1] == 'sessions':
            if _api_release_session(parts[2]):
                return self._send_json(200, {'status': 'ok'})
            return self._send_json(404, {'error': {'message': 'Session not found', 'code': 'not_found'}})

        self._send_json(404, {'error': {'message': 'Not found', 'code': 'not_found'}})


def cmd_serve(api: bool = False, port: int = 9333):
    """Start Browserbase-compatible local API server (cdpilot serve --api [--port N])."""
    if not api:
        print('Usage: cdpilot serve --api [--port N]')
        sys.exit(1)

    server = ThreadingHTTPServer(('127.0.0.1', port), BrowserbaseHandler)
    print(f'cdpilot API server listening on http://127.0.0.1:{port}')
    print(f'Set BROWSERBASE_API_URL=http://localhost:{port}  BROWSERBASE_API_KEY=dummy')

    def _shutdown():
        for sess_id in list(_api_session_store.keys()):
            _api_release_session(sess_id)

    atexit.register(_shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down...')
        _shutdown()
        server.server_close()


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


# ─── Smart Commands (LLM-free intelligence) ───

async def cmd_smart_click(text):
    """Click element by visible text — fuzzy matching, no CSS selector needed.

    Like Stagehand's act("Click login") but without LLM.
    Searches: button text, link text, aria-label, placeholder, title, value.

    Usage:
        cdpilot smart-click "Login"
        cdpilot smart-click "Submit Order"
        cdpilot smart-click "Learn more"
    """
    ws_url, _ = get_page_ws()
    # Snapshot page targets before the click so a new tab opened by the click
    # (target=_blank, window.open) can be marked cdpilot-owned afterwards.
    _pre_click_targets = {t.get("id") for t in (cdp_get("/json") or [])
                          if t.get("type") == "page"}
    # Locale-aware lowercase so Turkish/German chars round-trip safely.
    # `toLocaleLowerCase()` (no arg) honors the browser's BCP-47 locale, which
    # matches what the user sees in the DOM. Python's str.lower() handles
    # ASCII fine for the *search* term that we marshal across; the in-page
    # comparison uses the same locale-aware function on both sides.
    safe_text = json.dumps(text.lower())
    js = f"""
    (function() {{
      // Walk into shadow roots so Salesforce Lightning / Polymer / any custom
      // element with attachShadow({{mode:'open'}}) becomes searchable.
      // Closed shadow roots are inaccessible by design — nothing we can do
      // about those without a DevTools-only API.
      function deepQuerySelectorAll(root, selector) {{
        var found = Array.from(root.querySelectorAll(selector));
        Array.from(root.querySelectorAll('*')).forEach(function(el) {{
          if (el.shadowRoot) {{
            found = found.concat(deepQuerySelectorAll(el.shadowRoot, selector));
          }}
        }});
        return found;
      }}

      function lc(s) {{
        // Locale-aware lowercase — `toLowerCase()` mishandles Turkish (İ → i̇
        // combining sequence in some engines) and stays case-sensitive on
        // ß in older runtimes. `toLocaleLowerCase()` matches the user's
        // expected mental model: "İletişim" → "iletişim".
        return (s == null ? '' : (s + '')).toLocaleLowerCase();
      }}

      var search = lc({safe_text}).trim();
      var candidates = [];
      var disabledCount = 0;

      // Score: exact > startsWith > includes > partial
      function score(str) {{
        if (!str) return 0;
        var s = lc(str).trim();
        if (s === search) return 100;
        if (s.startsWith(search)) return 80;
        if (s.includes(search)) return 60;
        // Partial word match
        var words = search.split(/\\s+/);
        var matched = words.filter(function(w) {{ return s.includes(w); }}).length;
        if (matched > 0) return 20 + (matched / words.length) * 30;
        return 0;
      }}

      var els = deepQuerySelectorAll(document,
        'a, button, input[type=submit], input[type=button], ' +
        '[role=button], [role=link], [role=tab], [role=menuitem], ' +
        'summary, label, [onclick], [tabindex]'
      );

      els.forEach(function(el) {{
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        var style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return;

        var texts = [
          el.textContent || '',
          el.getAttribute('aria-label') || '',
          el.getAttribute('title') || '',
          el.getAttribute('placeholder') || '',
          el.value || '',
          el.getAttribute('alt') || ''
        ];

        var bestScore = 0;
        var bestMatch = '';
        texts.forEach(function(t) {{
          var s = score(t);
          if (s > bestScore) {{ bestScore = s; bestMatch = (t + '').trim().substring(0, 60); }}
        }});

        if (bestScore > 0) {{
          // Reject elements that look clickable but won't fire — `<button
          // disabled>`, `[aria-disabled=true]`, or a disabled ancestor
          // (fieldset[disabled] propagates to children). Without this the
          // command reports "Clicked" but nothing happens — silent fail.
          var isDisabled = (
            el.disabled === true ||
            el.getAttribute('aria-disabled') === 'true' ||
            (typeof el.closest === 'function' && el.closest('fieldset[disabled], [aria-disabled="true"]') !== null)
          );
          if (isDisabled) {{
            disabledCount++;
            return;
          }}
          candidates.push({{
            el: el,
            score: bestScore,
            match: bestMatch,
            tag: el.tagName.toLowerCase(),
            cx: rect.x + rect.width / 2,
            cy: rect.y + rect.height / 2
          }});
        }}
      }});

      if (candidates.length === 0) {{
        return JSON.stringify({{
          found: false,
          allDisabled: disabledCount > 0,
          disabledCount: disabledCount
        }});
      }}

      candidates.sort(function(a, b) {{ return b.score - a.score; }});
      var best = candidates[0];
      best.el.scrollIntoView({{block: 'center'}});
      var rect = best.el.getBoundingClientRect();
      best.el.click();
      return JSON.stringify({{
        found: true,
        tag: best.tag,
        text: best.match,
        score: best.score,
        x: rect.x + rect.width / 2,
        y: rect.y + rect.height / 2,
        alternatives: candidates.slice(1, 4).map(function(c) {{
          return c.tag + ' "' + c.match + '" (score:' + c.score + ')';
        }})
      }});
    }})()
    """
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    raw = r.get(1, {}).get("result", {}).get("value", "")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        print(f"Error parsing result", file=sys.stderr)
        return

    if not data.get("found"):
        if data.get("allDisabled"):
            # Distinguish "no match" from "match exists but disabled" — the
            # latter is almost always a timing bug in the caller (form
            # validation hasn't unlocked the submit button yet).
            print(f'Error: no enabled element matches "{text}" '
                  f'({data.get("disabledCount", 0)} disabled match(es) skipped)', file=sys.stderr)
        else:
            print(f'No element found matching: "{text}"', file=sys.stderr)
        sys.exit(1)

    await _vfx_ripple(ws_url, data["x"], data["y"])
    # A click can spawn a new tab (target=_blank). Diff the target list and mark
    # any newcomer as cdpilot-owned so `close` will clean it up later.
    try:
        cdp_cache_invalidate()
        for t in (cdp_get("/json", no_cache=True) or []):
            if t.get("type") == "page" and t.get("id") not in _pre_click_targets:
                _mark_owned_tab(t.get("id"))
    except Exception:
        pass
    print(f'Clicked: {data["tag"].upper()} "{data["text"]}" (score:{data["score"]})')
    if data.get("alternatives"):
        print(f'  Also found: {", ".join(data["alternatives"])}')


# ─── Auto-dismiss: heuristic click for "leave me alone" modal buttons ───
#
# Many sites (especially LLM chat UIs — ChatGPT, Perplexity, Claude.ai, Gemini)
# gate access behind a sign-up modal but offer an escape hatch like "Stay
# signed out" or "Continue without". For unauthenticated query workflows
# (citation tracking, scraping public AI answers, etc.) we need to find and
# click that escape hatch reliably without firing on dangerous lookalikes.
#
# Two lists, evaluated against every visible clickable's text/aria/title:
#   POSITIVE → contribute a positive score (higher = more dismissive)
#   NEGATIVE → contribute a negative penalty (any hit = element is disqualified)
#
# Conservative on purpose: anti-patterns block obvious traps ("Delete account",
# "Sign out"), and the minimum score threshold (40) means weak partial matches
# don't trigger a click.

DISMISS_POSITIVE = [
    # English — direct anonymous-use intent
    ("stay signed out", 100), ("keep me signed out", 100),
    ("continue without signing in", 100), ("continue without an account", 100),
    ("use without an account", 95), ("continue as guest", 95),
    ("stay logged out", 95), ("no, thanks", 90),
    # English — generic dismiss
    ("no thanks", 85), ("not now", 80), ("maybe later", 75),
    ("skip for now", 75), ("skip", 65), ("dismiss", 70),
    ("later", 55), ("close", 50),
    # Cookie / GDPR — these unblock the page without consenting away rights
    ("reject all", 60), ("only necessary", 60), ("only essential", 60),
    ("decline", 55),
    # Turkish
    ("şimdi değil", 80), ("şimdilik geç", 80), ("üye olmadan", 95),
    ("hesapsız devam et", 95), ("girişsiz", 90), ("kapat", 50),
    ("atla", 65), ("vazgeç", 55), ("yok teşekkürler", 85),
    ("reddet", 55), ("tümünü reddet", 60),
]

DISMISS_NEGATIVE = [
    # Account destruction — never auto-click these
    "delete account", "remove account", "deactivate account",
    "hesabı sil", "hesabımı sil", "hesabı kapat",
    # Session destruction — opposite of what we want
    "sign out", "log out", "logout", "çıkış yap", "oturumu kapat",
    # Destructive confirmations
    "yes, delete", "confirm delete", "permanently delete",
    "evet, sil", "kalıcı olarak sil",
    # Subscription / payment
    "subscribe", "upgrade", "buy now", "satın al", "abone ol",
]


def _dismiss_js_template():
    """Build the JS expression for cmd_dismiss. Inlines pattern lists as JSON.

    Pulled out into a helper so tests can grep for the patterns without
    paying for a 200-line literal string in every function definition.
    """
    return f"""
    (function() {{
      var POS = {json.dumps(DISMISS_POSITIVE)};
      var NEG = {json.dumps(DISMISS_NEGATIVE)};
      var MIN_SCORE = 40;

      function checkText(t) {{
        if (!t) return {{ pos: 0, neg: false, hit: '' }};
        var s = (t + '').toLowerCase().trim();
        // Disqualifier first — one negative hit and the element is out,
        // regardless of how many positive patterns also match.
        for (var i = 0; i < NEG.length; i++) {{
          if (s.indexOf(NEG[i]) !== -1) return {{ pos: 0, neg: true, hit: NEG[i] }};
        }}
        var bestPos = 0, bestHit = '';
        for (var j = 0; j < POS.length; j++) {{
          var pat = POS[j][0], weight = POS[j][1];
          if (s.indexOf(pat) !== -1) {{
            // Exact match bonus; otherwise scaled by how much of the
            // element's text matches the pattern (longer match = more
            // confident).
            var score = (s === pat) ? weight + 10 : weight;
            if (score > bestPos) {{ bestPos = score; bestHit = pat; }}
          }}
        }}
        return {{ pos: bestPos, neg: false, hit: bestHit }};
      }}

      var els = document.querySelectorAll(
        'a, button, input[type=submit], input[type=button], ' +
        '[role=button], [role=link], [role=menuitem], [role=option], ' +
        'summary, [onclick], [tabindex]'
      );

      var best = null;
      Array.from(els).forEach(function(el) {{
        // Must be visible — invisible/0-size elements are not real buttons
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        var style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return;
        if (parseFloat(style.opacity) < 0.1) return;

        var texts = [
          el.textContent || '',
          el.getAttribute('aria-label') || '',
          el.getAttribute('title') || '',
          el.value || '',
          el.getAttribute('alt') || ''
        ];

        var disq = false, bestPos = 0, bestHit = '';
        for (var k = 0; k < texts.length; k++) {{
          var r = checkText(texts[k]);
          if (r.neg) {{ disq = true; break; }}
          if (r.pos > bestPos) {{ bestPos = r.pos; bestHit = r.hit; }}
        }}
        if (disq) return;
        if (bestPos < MIN_SCORE) return;

        if (best === null || bestPos > best.score) {{
          best = {{
            score: bestPos,
            hit: bestHit,
            text: (texts[0] || texts[1] || '').trim().substring(0, 80),
            tag: el.tagName.toLowerCase(),
            x: rect.x + rect.width / 2,
            y: rect.y + rect.height / 2,
            el: el
          }};
        }}
      }});

      if (best === null) return JSON.stringify({{ found: false }});

      best.el.scrollIntoView({{behavior:'instant', block:'center'}});
      best.el.click();
      return JSON.stringify({{
        found: true,
        tag: best.tag,
        text: best.text,
        pattern: best.hit,
        score: best.score
      }});
    }})()
    """


async def cmd_dismiss(repeat=None):
    """Find and click the strongest "dismiss / continue without account" button.

    Designed for LLM chat sites that gate queries behind a sign-up modal but
    offer an escape hatch ("Stay signed out", "No thanks", etc.). Built-in
    pattern library covers English + Turkish dismissive phrases and explicitly
    excludes destructive lookalikes ("Delete account", "Sign out", "Subscribe").

    Usage:
      cdpilot dismiss              # one shot — click best dismiss button if any
      cdpilot dismiss 3            # repeat up to 3 times (chained modals)
      cdpilot dismiss aggressive   # repeat until no candidates found (max 5)

    Exit code: 0 if something was clicked or nothing to dismiss, 1 on error.
    """
    # Parse repeat: int N, "aggressive" (=5), or default 1
    if repeat is None:
        max_iter = 1
    elif isinstance(repeat, str) and repeat.lower() == 'aggressive':
        max_iter = 5
    else:
        try:
            max_iter = max(1, min(int(repeat), 10))
        except (TypeError, ValueError):
            print(f"Invalid repeat: {repeat}. Use a number 1-10 or 'aggressive'.", file=sys.stderr)
            sys.exit(1)

    ws_url, _ = get_page_ws()
    js = _dismiss_js_template()
    total_clicked = 0
    for i in range(max_iter):
        r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
        raw = r.get(1, {}).get("result", {}).get("value", "")
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            print("Error parsing dismiss result", file=sys.stderr)
            sys.exit(1)
        if not data.get("found"):
            if total_clicked == 0:
                print("No dismiss candidates on page.")
            break
        total_clicked += 1
        print(f'Dismissed: {data["tag"].upper()} "{data["text"]}" '
              f'(pattern: "{data["pattern"]}", score: {data["score"]})')
        # Give the modal a moment to close before next scan
        if i + 1 < max_iter:
            await asyncio.sleep(0.4)

    if total_clicked:
        print(f'Total dismissed: {total_clicked}')


async def cmd_smart_fill(text, value):
    """Fill input by label/placeholder text — no CSS selector needed.

    Finds input by: associated label, placeholder, aria-label, name, id match,
    aria-labelledby, closest [aria-label], and nearby (4-prev) labels for
    floating-label designs (Material UI, Ant Design, Chakra).

    Usage:
        cdpilot smart-fill "Email" "test@example.com"
        cdpilot smart-fill "Password" "secret123"
        cdpilot smart-fill "Search" "cdpilot"
    """
    ws_url, _ = get_page_ws()
    safe_text = json.dumps(text.lower())
    safe_value = json.dumps(value)
    js = f"""
    (function() {{
      // Shadow DOM traversal — same helper as smart-click. Custom-element
      // form controls (e.g. <sf-input> in Salesforce Lightning) only
      // expose their <input> via shadow root.
      function deepQuerySelectorAll(root, selector) {{
        var found = Array.from(root.querySelectorAll(selector));
        Array.from(root.querySelectorAll('*')).forEach(function(el) {{
          if (el.shadowRoot) {{
            found = found.concat(deepQuerySelectorAll(el.shadowRoot, selector));
          }}
        }});
        return found;
      }}

      function lc(s) {{
        return (s == null ? '' : (s + '')).toLocaleLowerCase();
      }}

      var search = lc({safe_text}).trim();
      var value = {safe_value};
      var candidates = [];

      function score(str) {{
        if (!str) return 0;
        var s = lc(str).trim();
        if (s === search) return 100;
        if (s.startsWith(search)) return 80;
        if (s.includes(search)) return 60;
        return 0;
      }}

      var inputs = deepQuerySelectorAll(document,
        'input, textarea, select, [contenteditable=true]');
      inputs.forEach(function(el) {{
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;

        var scores = [];
        // 1. placeholder
        scores.push(score(el.getAttribute('placeholder') || ''));
        // 2. aria-label
        scores.push(score(el.getAttribute('aria-label') || ''));
        // 3. name / id
        scores.push(score(el.name || ''));
        scores.push(score(el.id || ''));
        // 4. label[for=id] (classic)
        if (el.id) {{
          var label = document.querySelector('label[for="' + el.id + '"]');
          if (label) scores.push(score(label.textContent || ''));
        }}
        // 5. parent <label>
        var parentLabel = el.closest('label');
        if (parentLabel) scores.push(score(parentLabel.textContent || ''));
        // 6. immediately-preceding sibling (legacy fallback)
        var prev = el.previousElementSibling;
        if (prev) scores.push(score(prev.textContent || ''));

        // 7. aria-labelledby — the input points at one or more IDs whose
        //    textContent forms the accessible name. ARIA spec says space-
        //    separated tokens, in order.
        var labelledby = el.getAttribute('aria-labelledby');
        if (labelledby) {{
          labelledby.split(/\\s+/).forEach(function(id) {{
            if (!id) return;
            var ref = document.getElementById(id);
            if (ref) scores.push(score(ref.textContent || ''));
          }});
        }}
        // 8. closest ancestor with [aria-label] — Material UI / Chakra wrap
        //    the input in a labelled container instead of using <label>.
        if (typeof el.closest === 'function') {{
          var aria = el.closest('[aria-label]');
          if (aria && aria !== el) scores.push(score(aria.getAttribute('aria-label') || ''));
        }}
        // 9. nearby label — walk up to 4 previous siblings looking for a
        //    <label> or label-like element. Floating-label designs render
        //    the label as a separate sibling at the parent level.
        var node = el;
        for (var depth = 0; depth < 2 && node && node.parentElement; depth++) {{
          var sib = node.previousElementSibling;
          for (var i = 0; i < 4 && sib; i++) {{
            if (sib.tagName === 'LABEL' ||
                sib.matches && (sib.matches('label, [class*="label" i], [class*="Label"]'))) {{
              var t = (sib.textContent || '').trim();
              if (t && t.length < 80) scores.push(score(t));
              break;
            }}
            sib = sib.previousElementSibling;
          }}
          node = node.parentElement;
        }}

        var bestScore = Math.max.apply(null, scores);
        if (bestScore > 0) {{
          candidates.push({{el: el, score: bestScore, tag: el.tagName.toLowerCase(), type: el.type || ''}});
        }}
      }});

      if (candidates.length === 0) return JSON.stringify({{found: false}});

      candidates.sort(function(a, b) {{ return b.score - a.score; }});
      var best = candidates[0];

      // React-compatible value setting
      var nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      ) || Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
      );
      if (nativeSetter && nativeSetter.set) {{
        nativeSetter.set.call(best.el, value);
      }} else {{
        best.el.value = value;
      }}
      best.el.dispatchEvent(new Event('input', {{bubbles: true}}));
      best.el.dispatchEvent(new Event('change', {{bubbles: true}}));

      return JSON.stringify({{
        found: true,
        tag: best.tag,
        type: best.type,
        score: best.score,
        placeholder: best.el.getAttribute('placeholder') || '',
        name: best.el.name || best.el.id || ''
      }});
    }})()
    """
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    raw = r.get(1, {}).get("result", {}).get("value", "")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        print(f"Error parsing result", file=sys.stderr)
        return

    if not data.get("found"):
        print(f'No input found matching: "{text}"', file=sys.stderr)
        sys.exit(1)

    ident = data.get("placeholder") or data.get("name") or data["tag"]
    print(f'Filled: {data["tag"].upper()}[{data["type"]}] "{ident}" = {value} (score:{data["score"]})')


async def cmd_smart_select(text, option_text):
    """Select dropdown option by label text — no CSS selector needed.

    Usage:
        cdpilot smart-select "Country" "Turkey"
        cdpilot smart-select "Size" "Large"
    """
    ws_url, _ = get_page_ws()
    safe_text = json.dumps(text.lower())
    safe_option = json.dumps(option_text.lower())
    js = f"""
    (function() {{
      // Shadow DOM + locale-aware comparison — same conventions as smart-click
      // / smart-fill so all three commands behave consistently on Lightning,
      // Polymer, and Turkish/German content.
      function deepQuerySelectorAll(root, selector) {{
        var found = Array.from(root.querySelectorAll(selector));
        Array.from(root.querySelectorAll('*')).forEach(function(el) {{
          if (el.shadowRoot) {{
            found = found.concat(deepQuerySelectorAll(el.shadowRoot, selector));
          }}
        }});
        return found;
      }}

      function lc(s) {{
        return (s == null ? '' : (s + '')).toLocaleLowerCase();
      }}

      var search = lc({safe_text}).trim();
      var optSearch = lc({safe_option}).trim();
      var selects = deepQuerySelectorAll(document, 'select');
      var best = null;
      var bestScore = 0;
      var disabledCount = 0;

      selects.forEach(function(sel) {{
        // Skip disabled selects — same rationale as smart-click: silently
        // setting .value on a disabled <select> is a no-op and confusing.
        var isDisabled = (
          sel.disabled === true ||
          sel.getAttribute('aria-disabled') === 'true' ||
          (typeof sel.closest === 'function' && sel.closest('fieldset[disabled], [aria-disabled="true"]') !== null)
        );
        var texts = [
          sel.getAttribute('aria-label') || '',
          sel.name || '', sel.id || ''
        ];
        if (sel.id) {{
          var label = document.querySelector('label[for="' + sel.id + '"]');
          if (label) texts.push(label.textContent || '');
        }}
        var parent = sel.closest('label');
        if (parent) texts.push(parent.textContent || '');

        var matched = false;
        texts.forEach(function(t) {{
          var s = lc(t).trim();
          var sc = s === search ? 100 : s.includes(search) ? 60 : 0;
          if (sc > 0) matched = true;
          if (sc > bestScore && !isDisabled) {{ bestScore = sc; best = sel; }}
        }});
        if (matched && isDisabled) disabledCount++;
      }});

      if (!best) {{
        return JSON.stringify({{
          found: false,
          allDisabled: disabledCount > 0,
          disabledCount: disabledCount
        }});
      }}

      // Find matching option
      var options = Array.from(best.options);
      var match = options.find(function(o) {{
        return lc(o.text).trim() === optSearch;
      }}) || options.find(function(o) {{
        return lc(o.text).includes(optSearch);
      }});

      if (!match) return JSON.stringify({{found: true, optionFound: false, available: options.map(function(o) {{ return o.text; }}).slice(0, 10)}});

      best.value = match.value;
      best.dispatchEvent(new Event('change', {{bubbles: true}}));
      return JSON.stringify({{found: true, optionFound: true, selected: match.text, value: match.value}});
    }})()
    """
    r = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js, "returnByValue": True})])
    raw = r.get(1, {}).get("result", {}).get("value", "")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        print("Error parsing result", file=sys.stderr)
        return

    if not data.get("found"):
        if data.get("allDisabled"):
            print(f'Error: no enabled select matches "{text}" '
                  f'({data.get("disabledCount", 0)} disabled match(es) skipped)', file=sys.stderr)
        else:
            print(f'No select found matching: "{text}"', file=sys.stderr)
        sys.exit(1)
    if not data.get("optionFound"):
        print(f'Option "{option_text}" not found. Available: {", ".join(data.get("available", []))}', file=sys.stderr)
        sys.exit(1)
    print(f'Selected: "{data["selected"]}" (value={data["value"]})')


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


async def cmd_wait_for_text(text, timeout_ms=5000):
    """Wait for text content to appear anywhere in document.body, up to timeout.

    Useful when you don't know the selector but know the text will appear (e.g.
    streaming AI responses, dynamic banners, late-loaded copy). Uses
    MutationObserver — returns as soon as the text is rendered, no fixed sleep.
    """
    ws_url, _ = get_page_ws()
    safe_text = json.dumps(text)
    js = f"""
    (function() {{
      return new Promise(function(resolve) {{
        var needle = {safe_text};
        function check() {{
          var bodyText = (document.body && document.body.innerText) || '';
          var idx = bodyText.indexOf(needle);
          if (idx === -1) return null;
          var ctx = bodyText.substring(Math.max(0, idx - 30), Math.min(bodyText.length, idx + needle.length + 30));
          return 'FOUND: "' + ctx.replace(/\\s+/g, ' ').trim() + '"';
        }}
        var hit = check();
        if (hit) return resolve(hit);
        var pending = false, done = false;
        function schedule() {{
          if (pending || done) return;
          pending = true;
          requestAnimationFrame(function() {{
            pending = false;
            if (done) return;
            var r = check();
            if (r) {{ done = true; obs.disconnect(); resolve(r); }}
          }});
        }}
        var obs = new MutationObserver(schedule);
        obs.observe(document.body, {{childList: true, subtree: true, characterData: true}});
        setTimeout(function() {{ if (done) return; done = true; obs.disconnect(); resolve('TIMEOUT: text "' + needle.substring(0, 40) + '" not found after {timeout_ms}ms'); }}, {timeout_ms});
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


# ─── Agent Token-Budget Mode ──────────────────────────────────────────────────

AGENT_INTERACTIVE_ROLES = {
    'button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'listbox',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'spinbutton',
    'slider', 'switch', 'tab', 'treeitem', 'searchbox', 'gridcell',
}

AGENT_ROLE_NORMALIZE = {
    'textField': 'textbox', 'comboBox': 'combobox',
    'checkBox': 'checkbox', 'radioButton': 'radio',
}

AGENT_SKIP_ROLES = {
    'none', 'presentation', 'generic', 'LineBreak', 'InlineTextBox',
    'ignored', 'unknown', 'RootWebArea',
}


def _agent_state_path():
    return os.path.join(CDPILOT_HOME, 'projects', PROJECT_ID, 'agent-state.json')


def _load_agent_state():
    path = _agent_state_path()
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            'last_url': None,
            'last_snapshot_hash': None,
            'actions_map': {},
            'ref_counter': 0,
            'total_tokens_full': 0,
            'total_tokens_diff': 0,
            'step': 0,
        }


def _save_agent_state(state):
    path = _agent_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Drop oldest entries if map exceeds 1000 to stay under ~50KB
    amap = state.get('actions_map', {})
    if len(amap) > 1000:
        sorted_refs = sorted(amap.keys(), key=lambda r: int(r.lstrip('@')))
        for ref in sorted_refs[:200]:
            del amap[ref]
        state['actions_map'] = amap
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, path)


def _estimate_tokens(obj):
    return max(1, len(json.dumps(obj)) // 4)


def _extract_text_summary(nodes, max_chars=2000):
    text_roles = {'staticText', 'text', 'paragraph', 'heading'}
    parts = []
    for node in nodes:
        if node.get('ignored'):
            continue
        role = node.get('role', {}).get('value', '')
        if role in text_roles:
            name = node.get('name', {}).get('value', '')
            if name:
                parts.append(name)
    summary = ' '.join(parts)
    return summary[:max_chars]


def _snapshot_to_actions(nodes, state):
    """Convert AXTree nodes to numbered action list. Updates state in place."""
    amap = state['actions_map']
    # Build reverse map: backend_node_id -> existing @ref
    bid_to_ref = {v['backend_node_id']: k for k, v in amap.items()}
    new_actions = []
    seen_names = {}

    for node in nodes:
        if node.get('ignored'):
            continue
        raw_role = node.get('role', {}).get('value', '')
        if not raw_role or raw_role in AGENT_SKIP_ROLES:
            continue
        role = AGENT_ROLE_NORMALIZE.get(raw_role, raw_role)
        name = node.get('name', {}).get('value', '') or ''
        bid = node.get('backendDOMNodeId') or node.get('backendNodeId')
        if not bid:
            continue

        is_interactive = role in AGENT_INTERACTIVE_ROLES
        # text-anchor fallback: unique non-empty name with any role
        is_text_anchor = (
            not is_interactive
            and len(name) > 2
            and seen_names.get(name, 0) == 0
        )
        if not is_interactive and not is_text_anchor:
            continue

        seen_names[name] = seen_names.get(name, 0) + 1

        # Assign ref — reuse if same backend node already tracked
        ref = bid_to_ref.get(bid)
        if ref is None:
            state['ref_counter'] += 1
            ref = f"@{state['ref_counter']}"
            bid_to_ref[bid] = ref

        # Build action descriptor
        action = {'ref': ref, 'role': role, 'name': name, 'backend_node_id': bid}
        if role in ('textbox', 'combobox', 'searchbox'):
            val = node.get('value', {}).get('value')
            if val is not None:
                action['value'] = val
        new_actions.append(action)

    return new_actions


def _diff_snapshots(old_map, new_actions):
    """Compute added/removed/value_changed between old state map and new actions."""
    new_map = {a['ref']: a for a in new_actions}
    old_refs = set(old_map.keys())
    new_refs = set(new_map.keys())

    added = list(new_refs - old_refs)
    removed = list(old_refs - new_refs)
    value_changed = []
    for ref in new_refs & old_refs:
        old_val = old_map[ref].get('value', '')
        new_val = new_map[ref].get('value', '')
        old_name = old_map[ref].get('name', '')
        new_name = new_map[ref].get('name', '')
        if old_val != new_val:
            value_changed.append(f"{ref}:{repr(new_val)}")
        elif old_name != new_name:
            value_changed.append(f"{ref}:name->{repr(new_name)}")

    return {'added': added, 'removed': removed, 'value_changed': value_changed}


async def _agent_full_snapshot():
    """Internal: take full AXTree snapshot, return (page, nodes, actions, state)."""
    ws_url, page = get_page_ws()
    await cdp_send(ws_url, [(0, 'Accessibility.enable', {})])
    res = await cdp_send(ws_url, [(1, 'Accessibility.getFullAXTree', {})])
    nodes = res.get(1, {}).get('nodes', [])
    state = _load_agent_state()
    actions = _snapshot_to_actions(nodes, state)
    # Rebuild actions_map from new actions
    state['actions_map'] = {a['ref']: a for a in actions}
    # Sync _A11Y_REF_MAP for compatibility with click-ref
    global _A11Y_REF_MAP
    _A11Y_REF_MAP = {int(a['ref'].lstrip('@')): a['backend_node_id'] for a in actions}
    _save_a11y_refs(_A11Y_REF_MAP)
    return page, nodes, actions, state


async def cmd_agent_observe():
    """Minimal-token page state for AI agents."""
    page, nodes, actions, state = await _agent_full_snapshot()
    text = _extract_text_summary(nodes)
    # Actions for output — exclude backend_node_id (internal only)
    out_actions = [
        {k: v for k, v in a.items() if k != 'backend_node_id'}
        for a in actions
    ]
    snap = {
        'url': page.get('url', ''),
        'title': page.get('title', ''),
        'actions': out_actions,
        'text': text,
        'token_estimate': _estimate_tokens(out_actions),
    }
    snap_str = json.dumps(snap)
    token_est = _estimate_tokens(snap_str)
    snap['token_estimate'] = token_est
    state['last_url'] = page.get('url', '')
    state['last_snapshot_hash'] = hashlib.md5(snap_str.encode()).hexdigest()[:8]
    state['step'] = state.get('step', 0) + 1
    state['total_tokens_full'] = state.get('total_tokens_full', 0) + token_est
    _save_agent_state(state)
    print(json.dumps(snap, indent=2))


async def cmd_agent_act(ref=None, url=None, action='click', text=None):
    """Perform action, return diff observation."""
    state = _load_agent_state()
    old_map = dict(state.get('actions_map', {}))

    if url:
        await cmd_go(url)
    elif ref:
        if ref not in old_map:
            print(json.dumps({'error': f'Unknown ref {ref}. Run: cdpilot agent observe'}), file=sys.stderr)
            sys.exit(1)
        bid = old_map[ref]['backend_node_id']
        ws_url, _ = get_page_ws()
        if action == 'click':
            await cmd_click_ref(ref)
        elif action in ('type', 'fill'):
            # Focus via backendNodeId then insert text
            await cdp_send(ws_url, [(1, 'DOM.enable', {})])
            res_r = await cdp_send(ws_url, [(2, 'DOM.resolveNode', {'backendNodeId': bid})])
            oid = res_r.get(2, {}).get('object', {}).get('objectId')
            if oid:
                await cdp_send(ws_url, [(3, 'Runtime.callFunctionOn', {
                    'objectId': oid,
                    'functionDeclaration': 'function(){this.focus();}',
                    'returnByValue': True,
                })])
            await cdp_send(ws_url, [(4, 'Input.insertText', {'text': text or ''})])
        elif action == 'hover':
            res_b = await cdp_send(ws_url, [(5, 'DOM.getBoxModel', {'backendNodeId': bid})])
            content = res_b.get(5, {}).get('model', {}).get('content', [])
            if len(content) >= 8:
                mx = int((content[0] + content[2] + content[4] + content[6]) / 4)
                my = int((content[1] + content[3] + content[5] + content[7]) / 4)
                await cdp_send(ws_url, [(6, 'Input.dispatchMouseEvent', {
                    'type': 'mouseMoved', 'x': mx, 'y': my,
                })])
        elif action == 'submit':
            await cdp_send(ws_url, [(7, 'DOM.enable', {})])
            res_r = await cdp_send(ws_url, [(8, 'DOM.resolveNode', {'backendNodeId': bid})])
            oid = res_r.get(8, {}).get('object', {}).get('objectId')
            if oid:
                await cdp_send(ws_url, [(9, 'Runtime.callFunctionOn', {
                    'objectId': oid,
                    'functionDeclaration': "function(){var f=this.closest('form');if(f)f.submit();else this.click();}",
                    'returnByValue': True,
                })])
    else:
        print(json.dumps({'error': 'Provide --ref @N or --url URL'}), file=sys.stderr)
        sys.exit(1)

    # Take new snapshot for diff
    page, nodes, new_actions, new_state = await _agent_full_snapshot()
    diff = _diff_snapshots(old_map, new_actions)
    new_text = _extract_text_summary(nodes)
    diff_tok = _estimate_tokens(diff)
    full_tok = _estimate_tokens(new_actions)
    saved = max(0.0, 1.0 - diff_tok / full_tok) if full_tok > 0 else 0.0

    new_state['total_tokens_diff'] = new_state.get('total_tokens_diff', 0) + diff_tok
    new_state['step'] = new_state.get('step', 0)  # already incremented in _agent_full_snapshot
    _save_agent_state(new_state)

    result = {
        'url': page.get('url', ''),
        'changed': diff,
        'new_text_blocks': [b for b in new_text.split('. ') if b.strip()],
        'token_estimate': diff_tok,
        'saved_vs_full': round(saved, 3),
    }
    print(json.dumps(result, indent=2))


async def cmd_agent_reset():
    path = _agent_state_path()
    if os.path.exists(path):
        os.remove(path)
    print(json.dumps({'status': 'reset', 'project_id': PROJECT_ID}))


async def cmd_agent_stats():
    state = _load_agent_state()
    full_tok = state.get('total_tokens_full', 0)
    diff_tok = state.get('total_tokens_diff', 0)
    saved = full_tok - diff_tok
    pct = f"{saved / full_tok * 100:.1f}%" if full_tok > 0 else "0%"
    print(json.dumps({
        'project_id': PROJECT_ID,
        'step': state.get('step', 0),
        'ref_counter': state.get('ref_counter', 0),
        'last_url': state.get('last_url'),
        'total_tokens_full': full_tok,
        'total_tokens_diff': diff_tok,
        'estimated_savings': saved,
        'savings_pct': pct,
    }, indent=2))


def _dispatch_agent_cmd(args):
    """Parse agent subcommand args, return coroutine for asyncio.run in main()."""
    sub = args[0] if args else ''
    rest = args[1:]

    if sub == 'observe':
        return cmd_agent_observe()
    if sub == 'reset':
        return cmd_agent_reset()
    if sub == 'stats':
        return cmd_agent_stats()
    if sub == 'act':
        ref = None
        url = None
        action = 'click'
        text = None
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok == '--ref' and i + 1 < len(rest):
                ref = rest[i + 1]; i += 2
            elif tok.startswith('--ref='):
                ref = tok.split('=', 1)[1]; i += 1
            elif tok == '--url' and i + 1 < len(rest):
                url = rest[i + 1]; i += 2
            elif tok.startswith('--url='):
                url = tok.split('=', 1)[1]; i += 1
            elif tok == '--action' and i + 1 < len(rest):
                action = rest[i + 1]; i += 2
            elif tok.startswith('--action='):
                action = tok.split('=', 1)[1]; i += 1
            elif tok == '--text' and i + 1 < len(rest):
                text = rest[i + 1]; i += 2
            elif tok.startswith('--text='):
                text = tok.split('=', 1)[1]; i += 1
            else:
                i += 1
        return cmd_agent_act(ref=ref, url=url, action=action, text=text)

    if sub == 'twitter':
        return _dispatch_agent_twitter_cmd(rest)

    print(f"Usage: agent [observe|act|reset|stats|twitter]", file=sys.stderr)
    print(f"  agent observe", file=sys.stderr)
    print(f"  agent act --ref @N [--action click|type|fill|hover|submit] [--text X]", file=sys.stderr)
    print(f"  agent act --url URL", file=sys.stderr)
    print(f"  agent reset", file=sys.stderr)
    print(f"  agent stats", file=sys.stderr)
    print(f"  agent twitter --help", file=sys.stderr)
    sys.exit(1)

# ─── End Agent Token-Budget Mode ──────────────────────────────────────────────


# ─── Agent Twitter Namespace ──────────────────────────────────────────────────

TWITTER_BASE = 'https://x.com'
_TW_SEL = {
    'textarea':       '[data-testid="tweetTextarea_0"]',
    'post_btn':       '[data-testid="tweetButtonInline"]',
    'post_btn2':      '[data-testid="tweetButton"]',
    'reply_btn':      '[data-testid="reply"]',
    'like_btn':       '[data-testid="like"]',
    'unlike_btn':     '[data-testid="unlike"]',
    'retweet_btn':    '[data-testid="retweet"]',
    'unretweet_btn':  '[data-testid="unretweet"]',
    'retweet_confirm':'[data-testid="retweetConfirm"]',
    'unretweet_confirm':'[data-testid="unretweetConfirm"]',
    'bookmark_btn':   '[data-testid="bookmark"]',
    'follow_btn':     '[data-testid="placementTracking"]',
    'unfollow_btn':   '[data-testid$="-unfollow"]',
    'unfollow_confirm':'[data-testid="confirmationSheetConfirm"]',
    'user_name':      '[data-testid="UserName"]',
    'tweet_text':     '[data-testid="tweetText"]',
    'caret_btn':      '[data-testid="caret"]',
    'pin_menu_item':  '[data-testid="pin"]',
    'unpin_menu_item':'[data-testid="unpin"]',
    'pin_confirm':    '[data-testid="confirmationSheetConfirm"]',
    'add_tweet_btn':  '[data-testid="addButton"]',
    'file_input':     'input[type="file"][data-testid="fileInput"]',
    'media_alt_btn':  '[data-testid="ALT_overlay"]',
    'media_alt_text': '[data-testid="alt_text"]',
    'media_alt_save': '[data-testid="alt-text-save"]',
    'poll_btn':       '[data-testid="pollButton"]',
    'poll_opt_input': '[data-testid^="pollChoice"]',
    'quote_btn':      '[data-testid="quote"]',  # tweet'in retweet menüsünde "Quote"
    'long_form_btn':  '[data-testid="longFormButton"]',  # Premium long-form mode
}

_TW_HUMANIZE = lambda: os.environ.get('CDPILOT_TWITTER_HUMANIZE') != 'off'


async def _tw_pause(mu=1.0, sigma=0.3):
    if _TW_HUMANIZE():
        await asyncio.sleep(_gauss(mu * 1000, sigma * 1000, mu * 500, mu * 2000) / 1000.0)


async def _tw_navigate(ws, path):
    url = f"{TWITTER_BASE}{path}" if path.startswith('/') else path
    await navigate_collect(ws, url)
    await asyncio.sleep(2.0 if _TW_HUMANIZE() else 0.5)


async def _tw_type(ws, text):
    humanize = _TW_HUMANIZE()
    if humanize:
        await _tw_pause(1.2, 0.3)
    expr = f"""(() => {{
        const ta = document.querySelector('[data-testid="tweetTextarea_0"]');
        if (!ta) return {{ok: false, error: 'textarea not found'}};
        ta.focus();
        const ok = document.execCommand('insertText', false, {json.dumps(text)});
        return {{ok: ok, content: ta.innerText}};
    }})()"""
    result = await _tw_eval(ws, expr)
    if not isinstance(result, dict) or not result.get('ok'):
        print(json.dumps({'error': 'type_failed', 'details': result}), file=sys.stderr)
        sys.exit(1)
    if humanize:
        await _tw_pause(0.8, 0.2)


async def _tw_click_sel(ws, selector):
    res = await cdp_send(ws, [(802, 'Runtime.evaluate', {
        'expression': f'(function(){{var e=document.querySelector({json.dumps(selector)});if(!e)return null;var r=e.getBoundingClientRect();return {{x:r.x,y:r.y,w:r.width,h:r.height}};}})();',
        'returnByValue': True,
    })])
    box = res.get(802, {}).get('value')
    if not box:
        return False
    x = box['x'] + box['w'] / 2
    y = box['y'] + box['h'] / 2
    if _TW_HUMANIZE():
        await _humanize_click(ws, int(x), int(y))
    else:
        await cdp_send(ws, [
            (803, 'Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': int(x), 'y': int(y), 'button': 'left', 'clickCount': 1}),
            (804, 'Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': int(x), 'y': int(y), 'button': 'left', 'clickCount': 1}),
        ])
    return True


def _tw_parse_tweet_url(s):
    import re as _re
    m = _re.search(r'status/(\d+)', str(s))
    return m.group(0) if m else None


async def _tw_eval(ws, expr):
    res = await cdp_send(ws, [(810, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})])
    return res.get(810, {}).get('value')


async def cmd_twitter_login():
    ws, _ = get_page_ws()
    await _tw_navigate(ws, '/i/flow/login')
    print('>>> Open the browser and complete login, then press Enter here...', file=sys.stderr)
    await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
    await _tw_navigate(ws, '/home')
    logged = await _tw_eval(ws, f'!!document.querySelector({json.dumps(_TW_SEL["user_name"])})')
    print(json.dumps({'status': 'logged_in' if logged else 'not_logged_in'}))


async def cmd_twitter_status():
    ws, _ = get_page_ws()
    await _tw_navigate(ws, '/home')
    url = await _tw_eval(ws, 'location.href')
    logged_in = bool(url) and '/login' not in url and '/i/flow' not in url
    handle = None
    if logged_in:
        raw = await _tw_eval(ws, f'(document.querySelector({json.dumps(_TW_SEL["user_name"])})?.innerText||"").split("\\n").pop().trim()')
        handle = raw if raw else None
    rate_limited = await _tw_eval(ws, '"Rate limit" in document.body.innerText') or False
    print(json.dumps({'logged_in': logged_in, 'handle': handle, 'rate_limited': bool(rate_limited), 'suspended': False}))


async def _tw_attach_media(ws, paths_and_alts):
    """
    Compose dialog'una media yükle. paths_and_alts = [(path, alt_text|None), ...].
    Page.setFileInputFiles ile dosyalar input[type=file]'a aktarılır.
    Premium hesap alt-text 1000 char'a kadar destekler.
    """
    if not paths_and_alts:
        return
    paths = [p for p, _ in paths_and_alts]
    # File input'u bul
    res = await cdp_send(ws, [(820, 'Runtime.evaluate', {
        'expression': f'document.querySelector({json.dumps(_TW_SEL["file_input"])})?.getAttribute("name") || ""',
        'returnByValue': True,
    })])
    # CDP DOM.setFileInputFiles: backendNodeId üzerinden file inject
    node_res = await cdp_send(ws, [(821, 'DOM.getDocument', {})])
    root_id = node_res.get(821, {}).get('root', {}).get('nodeId')
    if root_id:
        q_res = await cdp_send(ws, [(822, 'DOM.querySelector', {
            'nodeId': root_id, 'selector': _TW_SEL['file_input'],
        })])
        node_id = q_res.get(822, {}).get('nodeId')
        if node_id:
            await cdp_send(ws, [(823, 'DOM.setFileInputFiles', {
                'files': paths, 'nodeId': node_id,
            })])
            await _tw_pause(2.5, 0.5)  # upload bekle

    # Alt-text ekle (her media için)
    for idx, (_, alt) in enumerate(paths_and_alts):
        if not alt:
            continue
        # Media item'ı için ALT button'a tıkla
        await _tw_pause(0.5, 0.1)
        await _tw_eval(ws, f"""
        (() => {{
            const btns = document.querySelectorAll('{_TW_SEL["media_alt_btn"]}');
            if (btns[{idx}]) btns[{idx}].click();
        }})()
        """)
        await _tw_pause(1.0, 0.2)
        # Alt-text textarea'ya yaz
        await _tw_eval(ws, f"""
        (() => {{
            const ta = document.querySelector('{_TW_SEL["media_alt_text"]}');
            if (ta) {{ ta.focus(); document.execCommand('insertText', false, {json.dumps(alt)}); }}
        }})()
        """)
        await _tw_pause(0.5, 0.1)
        await _tw_click_sel(ws, _TW_SEL['media_alt_save'])
        await _tw_pause(0.5, 0.1)


async def _tw_set_poll(ws, options, duration_hours=24):
    """Compose'da poll butonuna tıkla, option'ları doldur, süreyi set et."""
    await _tw_click_sel(ws, _TW_SEL['poll_btn'])
    await _tw_pause(0.8, 0.2)
    # Option input'ları sırayla doldur
    for i, opt in enumerate(options[:4]):
        await _tw_eval(ws, f"""
        (() => {{
            const inputs = document.querySelectorAll('{_TW_SEL["poll_opt_input"]}');
            if (inputs[{i}]) {{ inputs[{i}].focus(); document.execCommand('insertText', false, {json.dumps(opt)}); }}
        }})()
        """)
        await _tw_pause(0.3, 0.1)
    # Duration: X UI 1 day / 7 days dropdown'ları sunar. duration_hours'a göre yakın eşleştir.
    # Default 1 day; özel duration için ileride detaylandır.


async def cmd_twitter_post(text, long_form=False, quote_url=None, poll_options=None,
                            poll_duration=24, media=None):
    """
    Tweet at. Modifier'lar:
      long_form: 280+ karakter (Premium)
      quote_url: set ise quote tweet
      poll_options: list of str, set ise poll ekle (duration_hours opsiyonel)
      media: list of (path, alt_text|None), set ise media yükle
    """
    ws, _ = get_page_ws()

    # Quote tweet ayrı bir flow — önce hedef tweet'e git, retweet menüsünden Quote seç
    if quote_url:
        tid = _tw_parse_tweet_url(quote_url)
        if not tid:
            print(json.dumps({'error': f'invalid quote_url: {quote_url}'}), file=sys.stderr)
            sys.exit(1)
        await _tw_navigate(ws, f'/i/status/{tid.split("/")[-1]}')
        await _tw_pause(1.2, 0.3)
        await _tw_click_sel(ws, _TW_SEL['retweet_btn'])
        await _tw_pause(0.6, 0.1)
        await _tw_click_sel(ws, _TW_SEL['quote_btn'])
        await _tw_pause(1.2, 0.3)
    else:
        await _tw_navigate(ws, '/compose/tweet')
        await _tw_pause(1.5, 0.4)

    ok = await _tw_click_sel(ws, _TW_SEL['textarea'])
    if not ok:
        print(json.dumps({'error': 'textarea not found, are you logged in?'}), file=sys.stderr)
        sys.exit(1)

    # Long-form mode (Premium) — text 280'i aşıyorsa otomatik veya butonla aç
    if long_form or (text and len(text) > 280):
        # Premium UI long-form için ayrı button gösterebilir; selector dene
        await _tw_click_sel(ws, _TW_SEL['long_form_btn'])
        await _tw_pause(0.5, 0.1)

    await _tw_pause(0.5, 0.1)
    await _tw_type(ws, text)
    await _tw_pause(1.0, 0.2)

    # Media yükle
    if media:
        await _tw_attach_media(ws, media)

    # Poll ekle
    if poll_options:
        await _tw_set_poll(ws, poll_options, poll_duration)

    await _tw_pause(1.2, 0.3)
    await _tw_click_sel(ws, _TW_SEL['post_btn2']) or await _tw_click_sel(ws, _TW_SEL['post_btn'])
    await asyncio.sleep(4.0 if _TW_HUMANIZE() else 1.5)
    url = await _tw_eval(ws, 'window.location.href')
    print(json.dumps({'url': url, 'tweet_id': _tw_parse_tweet_url(url or '')}))


async def cmd_twitter_thread(texts):
    """
    Native thread — compose dialog'unda + butonuyla multi-tweet draft oluştur,
    tek seferde "Post all" ile gönder. Reply-chain DEĞİL.
    """
    if not texts or len(texts) < 2:
        print(json.dumps({'error': 'thread requires min 2 tweets'}), file=sys.stderr)
        sys.exit(1)

    ws, _ = get_page_ws()
    await _tw_navigate(ws, '/compose/tweet')
    await _tw_pause(1.5, 0.4)

    # İlk tweet'i textarea'ya yaz
    await _tw_click_sel(ws, _TW_SEL['textarea'])
    await _tw_pause(0.4, 0.1)
    await _tw_type(ws, texts[0])

    # Sonraki tweet'leri "+" ile ekle
    for i, t in enumerate(texts[1:], start=1):
        if not t.strip():
            continue
        await _tw_pause(0.6, 0.15)
        # "+" butonuna tıkla
        clicked = await _tw_click_sel(ws, _TW_SEL['add_tweet_btn'])
        if not clicked:
            print(json.dumps({'error': f'add-tweet button not found for tweet {i}'}), file=sys.stderr)
            sys.exit(1)
        await _tw_pause(0.6, 0.15)
        # i'inci textarea'ya yaz — selector tweetTextarea_i şeklinde
        expr = f"""(() => {{
            const ta = document.querySelector('[data-testid="tweetTextarea_{i}"]');
            if (!ta) return {{ok: false}};
            ta.focus();
            const ok = document.execCommand('insertText', false, {json.dumps(t)});
            return {{ok: ok, content: ta.innerText}};
        }})()"""
        await _tw_eval(ws, expr)
        await _tw_pause(0.5, 0.1)

    # Tüm thread'i tek seferde gönder
    await _tw_pause(1.2, 0.3)
    await _tw_click_sel(ws, _TW_SEL['post_btn2']) or await _tw_click_sel(ws, _TW_SEL['post_btn'])
    await asyncio.sleep(5.0 if _TW_HUMANIZE() else 2.0)
    url = await _tw_eval(ws, 'window.location.href')
    first_tid = _tw_parse_tweet_url(url or '')
    print(json.dumps({
        'url': url,
        'first_tweet_id': first_tid,
        'tweet_count': len(texts),
        'mode': 'native_thread',
    }, indent=2))


async def cmd_twitter_reply(tweet_id, text):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    await _tw_pause(1.0, 0.3)
    await _tw_click_sel(ws, _TW_SEL['reply_btn'])
    await _tw_pause(0.8, 0.2)
    await _tw_type(ws, text)
    await _tw_pause(1.0, 0.2)
    await _tw_click_sel(ws, _TW_SEL['post_btn']) or await _tw_click_sel(ws, _TW_SEL['post_btn2'])
    await asyncio.sleep(3.0 if _TW_HUMANIZE() else 0.8)
    url = await _tw_eval(ws, 'window.location.href')
    print(json.dumps({'url': url, 'tweet_id': _tw_parse_tweet_url(url or '')}))


async def cmd_twitter_replies(tweet_id, limit=20):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    slice_end = limit + 1
    expr = (
        'Array.from(document.querySelectorAll("article")).slice(1,' + str(slice_end) + ')'
        '.map(function(a){var tt=a.querySelector("[data-testid=\'tweetText\']");var un=a.querySelector("[data-testid=\'UserName\']");var tm=a.querySelector("time");'
        'return {text:tt?tt.innerText:"",user:un?un.innerText:"",id:tm&&tm.parentElement?tm.parentElement.href.split("/").pop():""}})'
    )
    data = await _tw_eval(ws, expr) or []
    print(json.dumps(data, indent=2))


async def cmd_twitter_mentions(since=None):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, '/notifications/mentions')
    expr = (
        'Array.from(document.querySelectorAll("article"))'
        '.map(function(a){var tt=a.querySelector("[data-testid=\'tweetText\']");var un=a.querySelector("[data-testid=\'UserName\']");var tm=a.querySelector("time");'
        'return {text:tt?tt.innerText:"",user:un?un.innerText:"",id:tm&&tm.parentElement?tm.parentElement.href.split("/").pop():""}})'
    )
    data = await _tw_eval(ws, expr) or []
    print(json.dumps(data, indent=2))


async def cmd_twitter_profile(handle):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/{handle}')
    bio = await _tw_eval(ws, '(document.querySelector("[data-testid=\'UserDescription\']")||{}).innerText||""')
    followers = await _tw_eval(ws, '(document.querySelector("a[href$=\'/followers\'] span")||{}).innerText||""')
    following = await _tw_eval(ws, '(document.querySelector("a[href$=\'/following\'] span")||{}).innerText||""')
    print(json.dumps({'handle': handle, 'bio': bio, 'followers': followers, 'following': following}, indent=2))


async def cmd_twitter_like(tweet_id):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    await _tw_pause(0.8, 0.2)
    # Eğer zaten like'lıysa unlike_btn görünür, like noop
    already = await _tw_eval(ws, f'!!document.querySelector({json.dumps(_TW_SEL["unlike_btn"])})')
    if already:
        print(json.dumps({'status': 'noop', 'reason': 'already_liked', 'tweet_id': tweet_id}))
        return
    ok = await _tw_click_sel(ws, _TW_SEL['like_btn'])
    print(json.dumps({'status': 'ok' if ok else 'failed', 'tweet_id': tweet_id}))


async def cmd_twitter_unlike(tweet_id):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    await _tw_pause(0.8, 0.2)
    ok = await _tw_click_sel(ws, _TW_SEL['unlike_btn'])
    if not ok:
        # Zaten unlike durumda
        print(json.dumps({'status': 'noop', 'reason': 'not_liked', 'tweet_id': tweet_id}))
        return
    print(json.dumps({'status': 'ok', 'tweet_id': tweet_id}))


async def cmd_twitter_retweet(tweet_id):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    await _tw_pause(1.0, 0.3)
    # Eğer zaten retweet'liyse unretweet_btn görünür
    already = await _tw_eval(ws, f'!!document.querySelector({json.dumps(_TW_SEL["unretweet_btn"])})')
    if already:
        print(json.dumps({'status': 'noop', 'reason': 'already_retweeted', 'tweet_id': tweet_id}))
        return
    await _tw_click_sel(ws, _TW_SEL['retweet_btn'])
    await _tw_pause(0.6, 0.15)
    # Açılan menüden "Repost" (retweetConfirm) seç
    ok = await _tw_click_sel(ws, _TW_SEL['retweet_confirm'])
    print(json.dumps({'status': 'ok' if ok else 'failed', 'tweet_id': tweet_id}))


async def cmd_twitter_unretweet(tweet_id):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    await _tw_pause(1.0, 0.3)
    clicked = await _tw_click_sel(ws, _TW_SEL['unretweet_btn'])
    if not clicked:
        print(json.dumps({'status': 'noop', 'reason': 'not_retweeted', 'tweet_id': tweet_id}))
        return
    await _tw_pause(0.6, 0.15)
    ok = await _tw_click_sel(ws, _TW_SEL['unretweet_confirm'])
    print(json.dumps({'status': 'ok' if ok else 'failed', 'tweet_id': tweet_id}))


async def cmd_twitter_bookmark(tweet_id):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    await _tw_pause(0.8, 0.2)
    ok = await _tw_click_sel(ws, _TW_SEL['bookmark_btn'])
    print(json.dumps({'status': 'ok' if ok else 'failed', 'tweet_id': tweet_id}))


async def cmd_twitter_pin(tweet_id):
    """Kendi tweet'ini profile'a pin'le. ... menüsünden 'Pin to profile' seç."""
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    await _tw_pause(1.0, 0.3)
    # ... butonuna tıkla (tweet'in üst sağ köşesi)
    await _tw_click_sel(ws, _TW_SEL['caret_btn'])
    await _tw_pause(0.6, 0.15)
    # Menüden "Pin to profile" tıkla
    clicked = await _tw_click_sel(ws, _TW_SEL['pin_menu_item'])
    if not clicked:
        print(json.dumps({'error': 'pin menu item not found — tweet not yours or already pinned?'}), file=sys.stderr)
        sys.exit(1)
    await _tw_pause(0.6, 0.15)
    # Confirmation dialog
    ok = await _tw_click_sel(ws, _TW_SEL['pin_confirm'])
    print(json.dumps({'status': 'ok' if ok else 'failed', 'tweet_id': tweet_id, 'action': 'pin'}))


async def cmd_twitter_unpin(tweet_id):
    """Pinli tweet'i unpin'le."""
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/i/status/{tweet_id}')
    await _tw_pause(1.0, 0.3)
    await _tw_click_sel(ws, _TW_SEL['caret_btn'])
    await _tw_pause(0.6, 0.15)
    clicked = await _tw_click_sel(ws, _TW_SEL['unpin_menu_item'])
    if not clicked:
        print(json.dumps({'error': 'unpin menu item not found — tweet not pinned?'}), file=sys.stderr)
        sys.exit(1)
    await _tw_pause(0.6, 0.15)
    ok = await _tw_click_sel(ws, _TW_SEL['pin_confirm'])
    print(json.dumps({'status': 'ok' if ok else 'failed', 'tweet_id': tweet_id, 'action': 'unpin'}))


async def cmd_twitter_follow(handle):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/{handle}')
    await _tw_pause(0.8, 0.2)
    # Zaten following ise unfollow_btn görünür
    already = await _tw_eval(ws, f'!!document.querySelector({json.dumps(_TW_SEL["unfollow_btn"])})')
    if already:
        print(json.dumps({'status': 'noop', 'reason': 'already_following', 'handle': handle}))
        return
    ok = await _tw_click_sel(ws, _TW_SEL['follow_btn'])
    print(json.dumps({'status': 'ok' if ok else 'failed', 'handle': handle}))


async def cmd_twitter_unfollow(handle):
    ws, _ = get_page_ws()
    await _tw_navigate(ws, f'/{handle}')
    await _tw_pause(0.8, 0.2)
    clicked = await _tw_click_sel(ws, _TW_SEL['unfollow_btn'])
    if not clicked:
        print(json.dumps({'status': 'noop', 'reason': 'not_following', 'handle': handle}))
        return
    await _tw_pause(0.6, 0.15)
    # Confirmation dialog
    ok = await _tw_click_sel(ws, _TW_SEL['unfollow_confirm'])
    print(json.dumps({'status': 'ok' if ok else 'failed', 'handle': handle, 'action': 'unfollow'}))


async def cmd_twitter_analytics(days=7):
    """
    Gerçek analytics scrape. X'in /i/account/analytics sayfasından son N gün:
      - Impressions, profile visits, mentions, follower change
    Tweet-level metrics için /username/tweet/ID/analytics sayfası gerekir.

    Çıktı schema'sı:
      {
        "date": "YYYY-MM-DD",  # bugün
        "window_days": N,
        "follower_count": int,
        "following_count": int,
        "impressions": int,
        "profile_visits": int,
        "posts": [
          {"id": "...", "content": "...", "impressions": int, "likes": int, "retweets": int, "replies": int, "hour": int},
          ...
        ]
      }
    """
    ws, _ = get_page_ws()
    await _tw_navigate(ws, '/i/account/analytics')
    await _tw_pause(3.0, 0.5)

    # Sayfadan metrics scrape — exact selector'lar X tarafından sık değişir
    metrics = await _tw_eval(ws, """
    (() => {
      const out = {};
      // Top-level metric kartları
      document.querySelectorAll('[data-testid="analytics-metric-card"]').forEach(card => {
        const label = card.querySelector('span')?.innerText?.toLowerCase() || '';
        const value = card.querySelector('span:last-child')?.innerText || '';
        if (label.includes('impression')) out.impressions = value;
        else if (label.includes('profile')) out.profile_visits = value;
        else if (label.includes('mention')) out.mentions = value;
        else if (label.includes('follower')) out.follower_delta = value;
      });
      // Fallback: tüm metric değerlerini grab et
      out._raw_metrics = Array.from(document.querySelectorAll('article, [role="article"]'))
        .slice(0, 20)
        .map(a => a.innerText?.slice(0, 200));
      return out;
    })()
    """) or {}

    # Profil sayfasından follower/following say
    handle_data = await _tw_eval(ws, """
    (() => {
      const link = document.querySelector('a[href$="/followers"] span');
      const fl = link?.innerText || '';
      const link2 = document.querySelector('a[href$="/following"] span');
      const fg = link2?.innerText || '';
      return {followers: fl, following: fg};
    })()
    """) or {}

    today = datetime_now_iso_date()
    out = {
        'date': today,
        'window_days': days,
        'follower_count': handle_data.get('followers', ''),
        'following_count': handle_data.get('following', ''),
        'impressions': metrics.get('impressions', ''),
        'profile_visits': metrics.get('profile_visits', ''),
        'mentions': metrics.get('mentions', ''),
        'follower_delta': metrics.get('follower_delta', ''),
        'posts': [],  # tweet-level scraping ayrı flow gerektirir; ileride genişlet
        '_raw': metrics.get('_raw_metrics', [])[:5],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


def datetime_now_iso_date():
    """Today's date in YYYY-MM-DD."""
    from datetime import date
    return date.today().isoformat()


def _parse_post_flags(rest):
    """
    post komutu için flag parser.
    Returns (text, long_form, quote_url, poll_options, poll_duration, media_list)
    media_list = [(path, alt_text|None), ...]
    """
    long_form = False
    quote_url = None
    poll_options = []
    poll_duration = 24
    media_list = []
    pending_alt = None  # son --media için alt-text bekliyor

    positional = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == '--long':
            long_form = True; i += 1
        elif a == '--quote' and i + 1 < len(rest):
            quote_url = rest[i + 1]; i += 2
        elif a == '--poll' and i + 1 < len(rest):
            poll_options.append(rest[i + 1]); i += 2
        elif a == '--poll-duration' and i + 1 < len(rest):
            poll_duration = int(rest[i + 1]); i += 2
        elif a == '--media' and i + 1 < len(rest):
            media_list.append((rest[i + 1], None)); i += 2
        elif a == '--alt' and i + 1 < len(rest):
            # Son --media'ya bağla
            if media_list:
                media_list[-1] = (media_list[-1][0], rest[i + 1])
            i += 2
        else:
            positional.append(a); i += 1

    text = positional[0] if positional else sys.stdin.read().strip()
    return text, long_form, quote_url, (poll_options or None), poll_duration, (media_list or None)


def _dispatch_agent_twitter_cmd(args):
    if not args:
        print('Usage: agent twitter SUBCMD ...', file=sys.stderr)
        print('Content actions:', file=sys.stderr)
        print('  login | status', file=sys.stderr)
        print('  post "text" [--long] [--quote URL] [--poll opt1 --poll opt2 ...] [--poll-duration N]', file=sys.stderr)
        print('       [--media PATH [--alt "alt text"]] (repeatable)', file=sys.stderr)
        print('  thread "t1" "t2" "t3"... (native multi-tweet draft)', file=sys.stderr)
        print('  reply TWEET_ID "text"', file=sys.stderr)
        print('  pin TWEET_ID | unpin TWEET_ID', file=sys.stderr)
        print('Engagement actions:', file=sys.stderr)
        print('  like TWEET_ID | unlike TWEET_ID', file=sys.stderr)
        print('  retweet TWEET_ID | unretweet TWEET_ID', file=sys.stderr)
        print('  bookmark TWEET_ID', file=sys.stderr)
        print('  follow HANDLE | unfollow HANDLE', file=sys.stderr)
        print('Read actions:', file=sys.stderr)
        print('  replies TWEET_ID [--limit N]', file=sys.stderr)
        print('  mentions [--since ISO]', file=sys.stderr)
        print('  profile HANDLE', file=sys.stderr)
        print('  analytics [--days N]', file=sys.stderr)
        sys.exit(1)
    sub = args[0]
    rest = args[1:]

    # Content actions
    if sub == 'login':
        return cmd_twitter_login()
    if sub == 'status':
        return cmd_twitter_status()
    if sub == 'post':
        text, long_form, quote_url, poll_opts, poll_dur, media = _parse_post_flags(rest)
        return cmd_twitter_post(text, long_form=long_form, quote_url=quote_url,
                                 poll_options=poll_opts, poll_duration=poll_dur, media=media)
    if sub == 'thread':
        if rest:
            texts = list(rest)
        else:
            texts = [l.rstrip('\n') for l in sys.stdin.readlines()]
        return cmd_twitter_thread(texts)
    if sub == 'reply':
        # --to flag desteği (executor öyle çağırıyor)
        to = None; pos = []
        i = 0
        while i < len(rest):
            if rest[i] == '--to' and i + 1 < len(rest):
                to = rest[i + 1]; i += 2
            else:
                pos.append(rest[i]); i += 1
        if to and pos:
            return cmd_twitter_reply(to, pos[0])
        if len(rest) >= 2:
            return cmd_twitter_reply(rest[0], rest[1])
        print('Usage: agent twitter reply TWEET_ID "text"  OR  reply --to TWEET_ID "text"', file=sys.stderr)
        sys.exit(1)
    if sub == 'pin':
        if not rest: print('Usage: agent twitter pin TWEET_ID', file=sys.stderr); sys.exit(1)
        return cmd_twitter_pin(rest[0])
    if sub == 'unpin':
        if not rest: print('Usage: agent twitter unpin TWEET_ID', file=sys.stderr); sys.exit(1)
        return cmd_twitter_unpin(rest[0])

    # Engagement actions
    if sub == 'like':
        if not rest: print('Usage: agent twitter like TWEET_ID', file=sys.stderr); sys.exit(1)
        return cmd_twitter_like(rest[0])
    if sub == 'unlike':
        if not rest: print('Usage: agent twitter unlike TWEET_ID', file=sys.stderr); sys.exit(1)
        return cmd_twitter_unlike(rest[0])
    if sub == 'retweet':
        if not rest: print('Usage: agent twitter retweet TWEET_ID', file=sys.stderr); sys.exit(1)
        return cmd_twitter_retweet(rest[0])
    if sub == 'unretweet':
        if not rest: print('Usage: agent twitter unretweet TWEET_ID', file=sys.stderr); sys.exit(1)
        return cmd_twitter_unretweet(rest[0])
    if sub == 'bookmark':
        if not rest: print('Usage: agent twitter bookmark TWEET_ID', file=sys.stderr); sys.exit(1)
        return cmd_twitter_bookmark(rest[0])
    if sub == 'follow':
        if not rest: print('Usage: agent twitter follow HANDLE', file=sys.stderr); sys.exit(1)
        return cmd_twitter_follow(rest[0])
    if sub == 'unfollow':
        if not rest: print('Usage: agent twitter unfollow HANDLE', file=sys.stderr); sys.exit(1)
        return cmd_twitter_unfollow(rest[0])

    # Read actions
    if sub == 'replies':
        lim = 20
        tweet_id = rest[0] if rest else None
        i = 1
        while i < len(rest):
            if rest[i] == '--limit' and i + 1 < len(rest):
                lim = int(rest[i + 1]); i += 2
            else:
                i += 1
        if not tweet_id:
            print('Usage: agent twitter replies TWEET_ID [--limit N]', file=sys.stderr); sys.exit(1)
        return cmd_twitter_replies(tweet_id, lim)
    if sub == 'mentions':
        sinc = None
        i = 0
        while i < len(rest):
            if rest[i] == '--since' and i + 1 < len(rest):
                sinc = rest[i + 1]; i += 2
            else:
                i += 1
        return cmd_twitter_mentions(sinc)
    if sub == 'profile':
        if not rest: print('Usage: agent twitter profile HANDLE', file=sys.stderr); sys.exit(1)
        return cmd_twitter_profile(rest[0])
    if sub == 'analytics':
        ds = 7
        i = 0
        while i < len(rest):
            if rest[i] == '--days' and i + 1 < len(rest):
                ds = int(rest[i + 1]); i += 2
            else:
                i += 1
        return cmd_twitter_analytics(ds)

    print(f'Unknown twitter subcommand: {sub}', file=sys.stderr)
    sys.exit(1)

# ─── End Agent Twitter Namespace ──────────────────────────────────────────────


# ─── Heal Log Commands ────────────────────────────────────────────────────────

def cmd_heal_log(last_n=20):
    path = os.path.join(CDPILOT_HOME, "projects", PROJECT_ID, "heal.jsonl")
    if not os.path.exists(path):
        print("No heal log found.")
        return
    with open(path) as f:
        lines = f.readlines()
    for line in lines[-last_n:]:
        try:
            d = json.loads(line)
            win = next((t["strategy"] for t in reversed(d["tried"]) if t.get("hit")), "MISS")
            print(f"[{d['ts']}] {d['cmd']}: {d['input']!r} -> {win} ({d['duration_ms']}ms)")
        except Exception:
            pass


def cmd_heal_stats():
    path = os.path.join(CDPILOT_HOME, "projects", PROJECT_ID, "heal.jsonl")
    if not os.path.exists(path):
        print("No heal log found.")
        return
    stats = {}
    cmd_wins = {}
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
                c = d["cmd"]
                if c not in cmd_wins:
                    cmd_wins[c] = {}
                for t in d["tried"]:
                    s = t["strategy"]
                    if s not in stats:
                        stats[s] = {"hits": 0, "misses": 0}
                    if t.get("hit"):
                        stats[s]["hits"] += 1
                        cmd_wins[c][s] = cmd_wins[c].get(s, 0) + 1
                    else:
                        stats[s]["misses"] += 1
            except Exception:
                pass
    print(f"{'Strategy':<15} | {'Hits':<5} | {'Misses':<6} | Win%")
    print("-" * 40)
    for s, v in stats.items():
        total = v["hits"] + v["misses"]
        pct = v["hits"] / total * 100 if total else 0
        print(f"{s:<15} | {v['hits']:<5} | {v['misses']:<6} | {pct:.1f}%")
    if cmd_wins:
        print("\nTop fallback by command:")
        for c, s_map in cmd_wins.items():
            if s_map:
                top = max(s_map.items(), key=lambda x: x[1])[0]
                print(f"  {c}: {top}")


# ─── 3. Advanced Input Commands ───

async def cmd_hover(selector, ladder=None, no_heal=False, entropy=None):
    ws_url, _ = get_page_ws()
    if entropy is None:
        try:
            _h = await _adaptive_current_host(ws_url)
        except Exception:
            _h = None
        entropy = _entropy_enabled(_get_project_id(), host=_h)
    t0 = time.time()
    res_sel, tried = await _resolve_selector_ladder(ws_url, selector, ladder)
    dur = (time.time() - t0) * 1000
    if not res_sel:
        _log_heal("hover", selector, tried, dur, no_heal)
        print(f"Error: selector '{selector}' not resolved.", file=sys.stderr)
        sys.exit(1)
    if len(tried) > 1 or (tried and not tried[0]["hit"]):
        _log_heal("hover", selector, tried, dur, no_heal)
    x, y = await _get_element_center(ws_url, res_sel)
    if entropy:
        await _humanize_mouse_move(ws_url, x, y)
    else:
        await _vfx_move_cursor(ws_url, x, y)
        await cdp_send(ws_url, [(1, "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y, "button": "none", "modifiers": 0})])
    # cleanup tmp attr if used
    await cdp_send(ws_url, [(2, "Runtime.evaluate", {
        "expression": f"(function(){{var e=document.querySelector({json.dumps(res_sel)});if(e)e.removeAttribute('data-cdpilot-tmp')}})()"})])
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


async def cmd_drag(from_selector, to_selector, entropy=None):
    """Drag an element onto another element."""
    ws_url, _ = get_page_ws()
    if entropy is None:
        try:
            _h = await _adaptive_current_host(ws_url)
        except Exception:
            _h = None
        entropy = _entropy_enabled(_get_project_id(), host=_h)
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
        if entropy:
            path = _bezier_path((fx, fy), (tx, ty), points=15)
            for i, (ix, iy) in enumerate(path[1:], start=10):
                await send_mouse(i, "mouseMoved", ix, iy)
                import random as _r
                _dr = _r.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else _r.Random()
                await asyncio.sleep(_dr.uniform(0.02, 0.06))
        else:
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


async def cmd_scroll_to(selector, entropy=None):
    """Scroll the specified element into view."""
    ws_url, _ = get_page_ws()
    if entropy is None:
        try:
            _h = await _adaptive_current_host(ws_url)
        except Exception:
            _h = None
        entropy = _entropy_enabled(_get_project_id(), host=_h)
    if entropy:
        # Get element position then humanize scroll
        js_pos = f"""(function(){{
            var el=document.querySelector({json.dumps(selector)});
            if(!el) return null;
            var r=el.getBoundingClientRect();
            return {{top: r.top, height: r.height}};
        }})()"""
        res_pos = await cdp_send(ws_url, [(1, "Runtime.evaluate", {"expression": js_pos, "returnByValue": True})])
        val = res_pos.get(1, {}).get("result", {}).get("value")
        if not val:
            print(f"Error: element '{selector}' not found.", file=sys.stderr)
            sys.exit(1)
        delta = int(val.get("top", 0))
        if delta != 0:
            await _humanize_scroll(ws_url, delta)
        print(f"Scrolled to (entropy): {selector}")
    else:
        js = f"(function(){{ var el=document.querySelector({json.dumps(selector)}); if(!el) return false; el.scrollIntoView({{behavior:'instant',block:'center'}}); return true; }})()"
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
            {"name": "browser_eval_batch", "description": "Evaluate N JavaScript expressions in a SINGLE round-trip. Returns an array of {ok, value} or {ok:false, error} objects, one per expression — a failure in one does not abort the batch. Use this when you need many small observations (read 10 DOM values, query multiple selectors, build a report) — collapses N×roundtrip into 1×roundtrip, typically 5-30x faster than calling browser_eval repeatedly.",
             "inputSchema": {"type": "object", "properties": {"expressions": {"type": "array", "items": {"type": "string"}, "description": "Array of JavaScript expression strings. Each runs in its own try/catch."}}, "required": ["expressions"]}},
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
            {"name": "browser_close", "description": "Smart close: shut down every tab cdpilot opened during this automation, then close the whole browser application gracefully ONLY if no user-opened tabs remain. If the user has their own tabs open in the same browser, those are left untouched and the browser stays open. Use this to clean up after automation. Set force=true to close the browser even when user tabs remain; set keep_browser=true to only close cdpilot's tabs and never quit the browser.",
             "inputSchema": {"type": "object", "properties": {"force": {"type": "boolean", "description": "Close the browser application even if user-opened tabs remain.", "default": False}, "keep_browser": {"type": "boolean", "description": "Only close cdpilot's own tabs; never quit the browser.", "default": False}}}},
            {"name": "browser_extract", "description": "Extract structured data from elements matching a CSS selector. No LLM needed — pure DOM extraction. Returns text (default), JSON (with tag, text, attrs, href, src), specific attributes, or clean list. Use for scraping tables, lists, links, form values. Limit: 100 elements for JSON, 200 for text.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector to match elements (e.g. 'table tr', '.product', 'a')"}, "format": {"type": "string", "enum": ["text", "json", "list"], "description": "Output format: 'text' (one per line), 'json' (full structure with attrs), 'list' (numbered)", "default": "text"}}, "required": ["selector"]}},
            {"name": "browser_observe", "description": "List all interactive elements on the current page with their available actions (CLICK, FILL, NAVIGATE, TOGGLE, SELECT, SUBMIT, UPLOAD). Like Stagehand observe() but deterministic — no LLM needed. Shows what you CAN DO on the page. Use this to understand page structure before acting.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_smart_click", "description": "Click an element by its visible text — no CSS selector needed. Uses fuzzy matching across text content, aria-label, title, placeholder, and value. Returns match score and alternatives. Like Stagehand act('Click login') but without LLM cost. Use when you know WHAT to click but not the exact selector.",
             "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "description": "Visible text of the element to click (e.g. 'Login', 'Submit Order', 'Learn more')"}}, "required": ["text"]}},
            {"name": "browser_dismiss", "description": "Find and click the strongest 'dismiss / continue without account' button on the page. Built-in pattern library covers English + Turkish dismissive phrases ('Stay signed out', 'No thanks', 'Skip', 'Continue without', etc.) and explicitly excludes destructive lookalikes (Delete account, Sign out, Subscribe). Designed for LLM chat sites that gate queries behind a sign-up modal. Pass 'aggressive' or an integer N (max 10) to handle chained modals.",
             "inputSchema": {"type": "object", "properties": {"repeat": {"type": "string", "description": "Optional. Number of dismiss attempts (1-10) or 'aggressive' (up to 5 chained). Default: 1.", "default": "1"}}}},
            {"name": "browser_captcha_solve", "description": "Solve the CAPTCHA on the current page (opt-in). Detects and solves Amazon classic image CAPTCHA (the \"Type the characters you see\" rate-limit page) by OCRing the image, filling the input, and submitting. Default provider 'amazon-local' uses the optional amazoncaptcha library (pip install amazoncaptcha) for offline OCR. BYOK providers 'capsolver' / '2captcha' use image-to-text APIs via CAPSOLVER_API_KEY / TWOCAPTCHA_API_KEY env vars. Returns JSON with solved status. For token-based CAPTCHAs (reCAPTCHA, hCaptcha, Turnstile) use the captcha config/auto CLI instead.",
             "inputSchema": {"type": "object", "properties": {"provider": {"type": "string", "enum": ["amazon-local", "capsolver", "2captcha"], "description": "Solver provider. Default: amazon-local (offline OCR via optional amazoncaptcha lib).", "default": "amazon-local"}}}},
            {"name": "browser_press_hold", "description": "Solve a PerimeterX/HUMAN \"Press & Hold\" challenge on the current page (opt-in). PerimeterX is a BEHAVIOURAL challenge -- the user must press AND HOLD a button for several seconds while the detector measures hold duration, natural hand-tremor, and release timing. It is NOT token-based, so there is no provider to call: the only solution is a real humanized press->hold->release gesture, which this tool emits via CDP Input events (Gaussian-randomized ~3-7s hold with +/-1-2px micro-jitter while the button is held). Auto-locates the #px-captcha widget (or pass an explicit selector). Returns JSON with solved status, hold_ms, and attempts. Use this when browser_friction/captcha-check reports a 'perimeterx' type.", "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "Optional CSS selector for the hold target. If omitted, auto-finds the px-captcha button."}}}},
            {"name": "browser_friction", "description": "Detect the highest anti-bot 'friction' rung on the current page and return the recommended response policy as JSON. Real sites stack defenses incrementally (rate-limit -> CAPTCHA -> login-wall -> SMS/OTP -> hard-block); this reports which rung is currently active. Levels (low->high): none, rate_limited, soft_captcha, login_wall, otp_sms, hard_block. Bilingual (English + Turkish) DOM heuristics. Read-only — never bypasses anything. login_wall/otp_sms/hard_block are flagged for HUMAN handoff (not autonomously solved) for safety/ethics; rate_limited recommends exponential backoff; soft_captcha defers to the captcha tools. Use this for diagnosis before deciding how to proceed on a gated site.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_smart_fill", "description": "Fill an input by its label or placeholder text — no CSS selector needed. Finds input by associated label, placeholder, aria-label, name, or id. React-compatible value setting. Use when you know WHAT field to fill but not the exact selector.",
             "inputSchema": {"type": "object", "properties": {"label": {"type": "string", "description": "Label or placeholder text of the input (e.g. 'Email', 'Password', 'Search')"}, "value": {"type": "string", "description": "Value to fill in the input"}}, "required": ["label", "value"]}},
            {"name": "browser_smart_select", "description": "Select a dropdown option by label and option text — no CSS selector needed. Finds the select element by label/name, then selects the matching option. Use for dropdown interactions without knowing selectors.",
             "inputSchema": {"type": "object", "properties": {"label": {"type": "string", "description": "Label text of the select dropdown"}, "option": {"type": "string", "description": "Text of the option to select"}}, "required": ["label", "option"]}},
            {"name": "browser_describe", "description": "Get a comprehensive page description combining three data sources: (1) accessibility tree with @N references for interactive elements, (2) a PNG screenshot saved to disk, and (3) visible text content. Use this when browser_a11y alone is insufficient — for canvas/WebGL content, visual verification, or complex dynamic UIs. This is the vision fallback tool.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_assert", "description": "Assert that an element matching the CSS selector exists and optionally contains expected text. Returns PASS or FAIL with details. Use this for automated testing — verify page state after navigation or interaction. Checks visibility by default.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector to check for existence"}, "text": {"type": "string", "description": "Optional: expected text content (substring match)"}, "visible": {"type": "boolean", "description": "Check element is visible (not hidden/zero-size)", "default": True}}, "required": ["selector"]}},
            {"name": "browser_wait_for", "description": "Wait for an element matching the CSS selector to appear in the DOM, up to the specified timeout. Uses MutationObserver for efficient waiting. Returns the element's tag and text when found, or TIMEOUT if not found. Use before interactions with dynamically loaded content.",
             "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "CSS selector to wait for"}, "timeout": {"type": "number", "description": "Maximum wait time in milliseconds", "default": 5000}}, "required": ["selector"]}},
            {"name": "browser_wait_for_text", "description": "Wait for a specific text string to appear anywhere in document.body, up to the specified timeout. Uses MutationObserver (subtree + characterData) for efficient adaptive waiting — returns the moment the text renders, no fixed sleeps. Ideal for streaming AI responses, async toasts, late-loaded banners, and citation tracking where you know the text but not the selector. Returns surrounding context on hit.",
             "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "description": "Text fragment to wait for (substring match on document.body.innerText)"}, "timeout": {"type": "number", "description": "Maximum wait time in milliseconds", "default": 5000}}, "required": ["text"]}},
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
            {"name": "browser_watch_start", "description": "Begin a continuous JPEG screencast of the active page to disk. CDP's Page.startScreencast streams frames at 10-30fps so the model can actually SEE animation, mouse cursors, and short visual events that single screenshots miss. Spawns a background daemon that writes JPEGs into a per-project ring buffer (default 5 min retention, 100MB cap). Use this to capture video playback, animated demos, or any time-based UI for later multimodal analysis.",
             "inputSchema": {"type": "object", "properties": {
                 "url": {"type": "string", "description": "URL or file:// path to load before recording. Pass '-' or omit to attach to the currently-loaded page."},
                 "fps": {"type": "integer", "description": "Frames per second (1-30). Higher = more detail but bigger ring buffer.", "default": 10},
                 "quality": {"type": "integer", "description": "JPEG quality 1-100.", "default": 70},
                 "max_width": {"type": "integer", "description": "Maximum frame width in pixels (shrinks proportionally).", "default": 1280},
                 "retention_s": {"type": "integer", "description": "Seconds to keep frames before eviction.", "default": 300},
                 "disk_cap_mb": {"type": "integer", "description": "Maximum total frame size in MB before oldest-first eviction.", "default": 100},
                 "seek": {"type": "string", "description": "Optional MM:SS or seconds to seek the page's first <video> element to."}
             }}},
            {"name": "browser_watch_stop", "description": "Stop the background screencast daemon and (by default) delete the captured frames. Use after you've finished querying so you don't leak disk. Pass keep_frames=true to keep the ring buffer for later inspection.",
             "inputSchema": {"type": "object", "properties": {
                 "keep_frames": {"type": "boolean", "description": "Keep the captured frames on disk instead of deleting them.", "default": False}
             }}},
            {"name": "browser_watch_query", "description": "Return the file paths of JPEG frames captured around a target time window. Frames live on local disk so you can read them and feed them to a multimodal API (vision call) to actually understand what happened. Choose ONE of: at_window (centered on a video time), last (relative to the newest frame), since_last (everything new since the previous query). Returns at most `max` frames (default 16) — when more frames fall in the window we downsample, preferring high-motion moments when Pillow is available.",
             "inputSchema": {"type": "object", "properties": {
                 "at": {"type": "string", "description": "Video time to center on, MM:SS or seconds (e.g. '1:23'). Measured from screencast start."},
                 "window": {"type": "string", "description": "Width of the window around `at`, e.g. '5s', '500ms'.", "default": "5s"},
                 "last": {"type": "string", "description": "Return frames from the last N seconds (e.g. '5s'). Relative to the newest frame on disk."},
                 "since_last": {"type": "boolean", "description": "Return only frames newer than the previous watch_query call."},
                 "max": {"type": "integer", "description": "Maximum number of frame paths to return (downsampled if window has more).", "default": 16}
             }}},
            {"name": "browser_watch_status", "description": "Report the current screencast daemon state: running flag, frame count, total disk usage, oldest/newest timestamps. Use before browser_watch_query to confirm frames are actually being captured.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "browser_mode", "description": "Get or set the three-tier stealth mode (crawl4ai-style escalation). Tiers from lightest to heaviest fingerprint footprint: 'regular' injects NO anti-fingerprint patch (cleanest, fastest, fewest leaks — the default and best for most sites); 'stealth' injects a light patch (navigator.webdriver, chrome.runtime, permissions only — deliberately omits plugin spoofing which leaks); 'undetected' injects the full patch (light + plugin array + WebGL vendor + Worker patch — highest plausibility on naive checks but highest entropy). Omit 'tier' to read the current mode. Effect applies on the next navigation. Escalate to 'undetected' only for hard anti-bot targets.",
             "inputSchema": {"type": "object", "properties": {"tier": {"type": "string", "enum": ["regular", "stealth", "undetected"], "description": "Tier to set. Omit to get the current tier."}}}},
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
            "browser_eval_batch": lambda a: ["eval-batch", json.dumps(a.get("expressions", []))],
            "browser_tabs": lambda a: ["tabs"],
            "browser_console": lambda a: ["console"] + ([a["url"]] if a.get("url") else []),
            "browser_network": lambda a: ["network"] + ([a["url"]] if a.get("url") else []),
            "browser_a11y": lambda a: ["a11y"] + ([a["mode"]] if a.get("mode") and a["mode"] != "full" else []),
            "browser_fill": lambda a: ["fill", a.get("selector", ""), a.get("value", "")],
            "browser_launch": lambda a: ["launch"],
            "browser_close": lambda a: ["close"] + (["--force"] if a.get("force") else []) + (["--keep"] if a.get("keep_browser") else []),
            "browser_extract": lambda a: ["extract", a.get("selector", "")] + ([f"--{a['format']}"] if a.get("format") and a["format"] != "text" else []),
            "browser_observe": lambda a: ["observe"],
            "browser_smart_click": lambda a: ["smart-click", a.get("text", "")],
            "browser_dismiss": lambda a: ["dismiss"] + ([str(a["repeat"])] if a.get("repeat") else []),
            "browser_smart_fill": lambda a: ["smart-fill", a.get("label", ""), a.get("value", "")],
            "browser_captcha_solve": lambda a: ["captcha-solve"] + ([f"--provider={a['provider']}"] if a.get("provider") else []),
            "browser_press_hold": lambda a: ["press-hold"] + ([a["selector"]] if a.get("selector") else []),
            "browser_friction": lambda a: ["friction"],
            "browser_smart_select": lambda a: ["smart-select", a.get("label", ""), a.get("option", "")],
            "browser_describe": lambda a: ["describe"],
            "browser_assert": lambda a: ["assert", a.get("selector", "")] + ([a["text"]] if a.get("text") else []),
            "browser_wait_for": lambda a: ["wait-for", a.get("selector", "")] + ([str(a["timeout"])] if a.get("timeout") else []),
            "browser_wait_for_text": lambda a: ["wait-for-text", a.get("text", "")] + ([str(a["timeout"])] if a.get("timeout") else []),
            "browser_check": lambda a: ["check", json.dumps(a.get("checks", []))],
            "browser_assert_url": lambda a: ["assert-url", a.get("expected_url", "")],
            "browser_assert_title": lambda a: ["assert-title", a.get("expected_title", "")],
            "browser_assert_count": lambda a: ["assert-count", a.get("selector", ""), str(a.get("expected_count", 0))],
            "browser_assert_value": lambda a: ["assert-value", a.get("selector", ""), a.get("expected_value", "")],
            "browser_assert_attr": lambda a: ["assert-attr", a.get("selector", ""), a.get("attr", ""), a.get("expected", "")],
            "browser_assert_visible": lambda a: ["assert-visible", a.get("selector", "")],
            "browser_assert_hidden": lambda a: ["assert-hidden", a.get("selector", "")],
            "browser_screenshot_diff": lambda a: ["screenshot-diff", a.get("path1", ""), a.get("path2", "")],
            "browser_watch_start": lambda a: ["watch", "start"] + ([a["url"]] if a.get("url") else []) + ([f"--fps={a['fps']}"] if a.get("fps") else []) + ([f"--quality={a['quality']}"] if a.get("quality") else []) + ([f"--max-width={a['max_width']}"] if a.get("max_width") else []) + ([f"--retention={a['retention_s']}"] if a.get("retention_s") else []) + ([f"--disk-cap={a['disk_cap_mb']}"] if a.get("disk_cap_mb") else []) + ([f"--seek={a['seek']}"] if a.get("seek") else []),
            "browser_watch_stop": lambda a: ["watch", "stop"] + (["--keep-frames"] if a.get("keep_frames") else []),
            "browser_watch_query": lambda a: ["watch", "query"] + ([f"--at={a['at']}"] if a.get("at") else []) + ([f"--window={a['window']}"] if a.get("window") else []) + ([f"--last={a['last']}"] if a.get("last") else []) + (["--since-last"] if a.get("since_last") else []) + ([f"--max={a['max']}"] if a.get("max") else []),
            "browser_watch_status": lambda a: ["watch", "status"],
            "browser_mode": lambda a: ["mode"] + ([a["tier"]] if a.get("tier") else []),
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


# ─── Test Runner ───

TRACES_DIR = os.path.join(CDPILOT_HOME, 'traces')

TRACE_VIEWER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>cdpilot Trace Viewer</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; display: flex; height: 100vh; margin: 0; background: #f8f9fa; color: #1a1a1a; }
        #list { width: 320px; border-right: 1px solid #dee2e6; overflow-y: auto; background: white; }
        #main { flex: 1; display: flex; flex-direction: column; padding: 24px; overflow-y: auto; }
        .step { padding: 14px 18px; cursor: pointer; border-bottom: 1px solid #f1f3f5; transition: all 0.1s; }
        .step:hover { background: #f8f9fa; }
        .step.active { background: #e7f5ff; border-left: 4px solid #228be6; font-weight: 600; }
        .badge { padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
        .pass { background: #ebfbee; color: #2b8a3e; border: 1px solid #d3f9d8; }
        .fail { background: #fff5f5; color: #c92a2a; border: 1px solid #ffe3e3; }
        img { max-width: 100%; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.08); margin: 20px 0; background: #fff; border: 1px solid #dee2e6; }
        pre { background: #1a1b1e; color: #ced4da; padding: 16px; border-radius: 8px; font-size: 13px; line-height: 1.5; overflow-x: auto; font-family: 'JetBrains Mono', 'Fira Code', monospace; }
        h3 { margin-top: 32px; font-size: 16px; border-bottom: 1px solid #dee2e6; padding-bottom: 8px; color: #495057; }
        .meta { color: #868e96; font-size: 13px; }
        #header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
        .nav-hint { font-size: 12px; color: #adb5bd; margin-top: 8px; }
    </style>
</head>
<body>
    <div id="list"></div>
    <div id="main">
        <div id="header">
            <div>
                <span id="status-badge" class="badge"></span>
                <h2 id="step-name" style="display:inline; margin-left:12px; font-size: 20px;">Select a step</h2>
            </div>
            <div id="step-info" class="meta"></div>
        </div>
        <div class="nav-hint">Use &uarr;/&darr; or &larr;/&rarr; arrows to navigate steps</div>
        <img id="screenshot" style="display:none">
        <div id="details">
            <h3>A11y Tree</h3><pre id="a11y">No data</pre>
            <h3>Console</h3><pre id="console-log">No data</pre>
            <h3>Network</h3><pre id="network">No data</pre>
        </div>
    </div>
    <script>
        let steps = []; let currentIdx = -1;
        async function load() {
            try {
                const [sRes, mRes] = await Promise.all([fetch('/steps.jsonl'), fetch('/meta.json').then(r=>r.json()).catch(()=>({}))]);
                steps = (await sRes.text()).trim().split('\\n').filter(Boolean).map(JSON.parse);
                const badge = document.getElementById('status-badge');
                badge.textContent = mRes.failed > 0 ? 'FAILED' : 'PASSED';
                badge.className = 'badge ' + (mRes.failed > 0 ? 'fail' : 'pass');
                const list = document.getElementById('list');
                steps.forEach((s, i) => {
                    const div = document.createElement('div');
                    div.className = 'step';
                    div.innerHTML = '<div style="font-size:11px;color:#adb5bd;margin-bottom:2px">STEP ' + (i+1) + '</div><div style="font-size:14px">' + (s.action || 'Navigation') + '</div>';
                    div.onclick = () => selectStep(i);
                    list.appendChild(div);
                });
                if (steps.length > 0) selectStep(0);
            } catch (e) { document.getElementById('main').innerHTML = '<h1>Error loading trace data</h1>'; }
        }
        async function selectStep(i) {
            if (i < 0 || i >= steps.length) return;
            currentIdx = i;
            document.querySelectorAll('.step').forEach((el, idx) => el.classList.toggle('active', idx === i));
            const s = steps[i];
            document.getElementById('step-name').textContent = s.action || 'Navigation';
            document.getElementById('step-info').textContent = 'Duration: ' + (s.duration_ms || 0) + 'ms';
            const img = document.getElementById('screenshot');
            const pad = String(i).padStart(3, '0');
            img.src = '/screenshots/step-' + pad + '.png';
            img.style.display = 'block';
            img.onerror = () => { img.style.display = 'none'; };
            const fetchText = path => fetch(path).then(r => r.ok ? r.text() : 'No data').catch(() => 'No data');
            const [a11y, conLog, network] = await Promise.all([
                fetch('/a11y/step-' + pad + '.json').then(r => r.json()).catch(() => 'No data'),
                fetchText('/console.jsonl'),
                fetchText('/network.jsonl')
            ]);
            document.getElementById('a11y').textContent = typeof a11y === 'string' ? a11y : JSON.stringify(a11y, null, 2);
            document.getElementById('console-log').textContent = conLog;
            document.getElementById('network').textContent = network;
            document.getElementById('list').children[i].scrollIntoView({ block: 'nearest' });
        }
        window.onkeydown = e => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); selectStep(currentIdx + 1); }
            if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); selectStep(currentIdx - 1); }
        };
        load();
    </script>
</body>
</html>
"""


def cmd_test(files=None, watch=False, parallel=1, reporter='default', trace='default', grep=None):
    """Run *.cdpt.js test files via Node internal test runner."""
    bin_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bin', 'cdpilot.js')

    def find_tests():
        if files:
            found = []
            for f in files:
                if os.path.isdir(f):
                    found.extend(glob.glob(os.path.join(f, '**', '*.cdpt.js'), recursive=True))
                elif f.endswith('.cdpt.js') and os.path.exists(f):
                    found.append(f)
            return found
        return sorted(glob.glob('**/*.cdpt.js', recursive=True))

    def run_one(file):
        run_id = datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + os.path.basename(file).replace('.cdpt.js', '')
        trace_dir = os.path.join(TRACES_DIR, run_id)
        cmd = ['node', bin_path, '--internal-test-runner', file, '--trace-dir', trace_dir, '--parallel', str(parallel)]
        if trace == 'off':
            cmd.append('--trace=off')
        if grep:
            cmd.extend(['--grep', grep])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            try:
                data = json.loads(res.stdout)
            except Exception:
                data = {
                    "passed": 0, "failed": 1,
                    "tests": [{"name": file, "status": "failed", "duration_ms": 0,
                               "error": (res.stdout + res.stderr).strip()[:500]}],
                }
            if trace == 'retain-on-failure' and data.get('failed', 0) == 0:
                if os.path.exists(trace_dir):
                    shutil.rmtree(trace_dir)
            return data
        except subprocess.TimeoutExpired:
            return {"passed": 0, "failed": 1, "tests": [{"name": file, "status": "failed", "duration_ms": 120000, "error": "Timeout"}]}
        except Exception as e:
            return {"passed": 0, "failed": 1, "tests": [{"name": file, "status": "failed", "duration_ms": 0, "error": str(e)}]}

    def print_results(all_results, rep):
        if rep == 'json':
            print(json.dumps({"results": all_results}))
            return
        if rep == 'tap':
            total = sum(len(r.get('tests', [])) for r in all_results)
            print(f"TAP version 13\n1..{total}")
            n = 1
            for r in all_results:
                for t in r.get('tests', []):
                    ok = 'ok' if t.get('status') == 'passed' else 'not ok'
                    print(f"{ok} {n} - {t.get('name', 'test')}")
                    n += 1
            return
        if rep == 'junit':
            lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<testsuites>']
            for r in all_results:
                for t in r.get('tests', []):
                    lines.append(f'  <testcase name="{t.get("name", "")}" time="{t.get("duration_ms", 0)/1000:.3f}">')
                    if t.get('status') != 'passed':
                        err = (t.get('error') or '').replace('&', '&amp;').replace('<', '&lt;')
                        lines.append(f'    <failure>{err}</failure>')
                    lines.append('  </testcase>')
            lines.append('</testsuites>')
            print('\n'.join(lines))
            return
        # default
        tp = tf = 0
        for r in all_results:
            tp += r.get('passed', 0)
            tf += r.get('failed', 0)
            for t in r.get('tests', []):
                sym = "\033[32m  ✓\033[0m" if t.get('status') == 'passed' else "\033[31m  ✗\033[0m"
                print(f"{sym} {t.get('name', '?')} ({t.get('duration_ms', 0)}ms)")
                if t.get('status') != 'passed' and t.get('error'):
                    print(f"    \033[31m{t.get('error')}\033[0m")
        print(f"\n  {tp} passed, {tf} failed")

    def run_suite():
        test_files = find_tests()
        if not test_files:
            print("No tests found.")
            return False
        workers = max(1, min(parallel, len(test_files)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            all_results = list(executor.map(run_one, test_files))
        print_results(all_results, reporter)
        return any(r.get('failed', 0) > 0 for r in all_results)

    if not watch:
        if run_suite():
            sys.exit(1)
    else:
        print("Watching for changes... (Ctrl+C to stop)")
        last_m = 0
        while True:
            try:
                cur_files = find_tests()
                curr_m = max((os.path.getmtime(f) for f in cur_files), default=0) if cur_files else 0
                if curr_m > last_m:
                    run_suite()
                    last_m = curr_m
                time.sleep(1)
            except KeyboardInterrupt:
                break


def cmd_trace_list():
    """List all trace runs in ~/.cdpilot/traces/."""
    if not os.path.exists(TRACES_DIR):
        print("No traces found.")
        return
    dirs = sorted(
        (d for d in os.listdir(TRACES_DIR) if os.path.isdir(os.path.join(TRACES_DIR, d))),
        key=lambda x: os.path.getmtime(os.path.join(TRACES_DIR, x)),
        reverse=True,
    )
    if not dirs:
        print("No traces found.")
        return
    print(f"{'RUN ID':<50} | {'STATUS':<6} | {'TESTS':<5} | DATE")
    print("-" * 80)
    for d in dirs:
        meta = os.path.join(TRACES_DIR, d, 'meta.json')
        if os.path.exists(meta):
            try:
                with open(meta) as f:
                    m = json.load(f)
                status = "PASS" if m.get('failed', 0) == 0 else "FAIL"
                total = m.get('passed', 0) + m.get('failed', 0)
                date = datetime.datetime.fromtimestamp(os.path.getmtime(meta)).strftime('%Y-%m-%d %H:%M')
                print(f"{d:<50} | {status:<6} | {total:<5} | {date}")
            except Exception:
                print(f"{d:<50} | {'?':<6} | {'?':<5} | ?")


def cmd_trace_open(run_id=None, port=9444):
    """Start trace viewer HTTP server for a run. Default: most recent."""
    from http.server import SimpleHTTPRequestHandler
    if not run_id:
        if not os.path.exists(TRACES_DIR):
            print("No traces found.")
            return
        dirs = sorted(
            (d for d in os.listdir(TRACES_DIR) if os.path.isdir(os.path.join(TRACES_DIR, d))),
            key=lambda x: os.path.getmtime(os.path.join(TRACES_DIR, x)),
            reverse=True,
        )
        if not dirs:
            print("No traces found.")
            return
        run_id = dirs[0]
    trace_path = os.path.join(TRACES_DIR, run_id)
    if not os.path.exists(trace_path):
        print(f"Trace not found: {run_id}", file=sys.stderr)
        sys.exit(1)

    class TraceHandler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *a):
            pass  # suppress request logs

        def do_GET(self):
            if self.path == '/':
                body = TRACE_VIEWER_HTML.encode()
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                rel = self.path.lstrip('/')
                target = os.path.join(trace_path, rel)
                target = os.path.realpath(target)
                # Security: only serve files within trace_path
                if not target.startswith(os.path.realpath(trace_path)):
                    self.send_error(403)
                    return
                if os.path.exists(target) and os.path.isfile(target):
                    with open(target, 'rb') as f:
                        data = f.read()
                    self.send_response(200)
                    if target.endswith('.jsonl') or target.endswith('.json'):
                        self.send_header('Content-type', 'application/json')
                    elif target.endswith('.png'):
                        self.send_header('Content-type', 'image/png')
                    else:
                        self.send_header('Content-type', 'application/octet-stream')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)

    sys.stderr.write(f"Trace viewer: http://localhost:{port}  (run: {run_id})\nCtrl+C to stop.\n")
    try:
        ThreadingHTTPServer(('127.0.0.1', port), TraceHandler).serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_trace_clean(older_than='7d'):
    """Remove trace directories older than a given age."""
    import re as _re_local
    m = _re_local.match(r'^(\d+)([dhm])$', older_than)
    if not m:
        print("Invalid format. Use e.g. 7d, 24h, 30m.")
        return
    multiplier = {'d': 86400, 'h': 3600, 'm': 60}[m.group(2)]
    cutoff = time.time() - int(m.group(1)) * multiplier
    count = 0
    if os.path.exists(TRACES_DIR):
        for d in os.listdir(TRACES_DIR):
            p = os.path.join(TRACES_DIR, d)
            if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                shutil.rmtree(p)
                count += 1
    print(f"Removed {count} trace(s).")


def cmd_test_dispatch(args):
    opts = {'watch': False, 'parallel': 1, 'reporter': 'default', 'trace': 'default', 'grep': None, 'files': []}
    for arg in args:
        if arg == '--watch':
            opts['watch'] = True
        elif arg.startswith('--parallel='):
            opts['parallel'] = int(arg.split('=', 1)[1])
        elif arg.startswith('--reporter='):
            opts['reporter'] = arg.split('=', 1)[1]
        elif arg.startswith('--trace='):
            opts['trace'] = arg.split('=', 1)[1]
        elif arg.startswith('--grep='):
            opts['grep'] = arg.split('=', 1)[1]
        elif not arg.startswith('--'):
            opts['files'].append(arg)
    cmd_test(
        files=opts['files'] if opts['files'] else None,
        watch=opts['watch'],
        parallel=opts['parallel'],
        reporter=opts['reporter'],
        trace=opts['trace'],
        grep=opts['grep'],
    )


def cmd_trace_dispatch(args):
    sub = args[0] if args else 'list'
    rest = args[1:] if len(args) > 1 else []
    if sub == 'list':
        cmd_trace_list()
    elif sub == 'open':
        port = 9444
        run_id = None
        for a in rest:
            if a.startswith('--port='):
                port = int(a.split('=', 1)[1])
            elif not a.startswith('--'):
                run_id = a
        cmd_trace_open(run_id, port)
    elif sub == 'clean':
        cmd_trace_clean(rest[0] if rest else '7d')
    else:
        print(f"Unknown trace subcommand: {sub}. Use: list | open [run-id] | clean [--older-than 7d]")


# ─── Blog Publish Namespace ───────────────────────────────────────────────────

BLOG_DIR = '/Users/nadir/01dev/cdpilot-site/content/blog'

# day-NNN.md master plan file lookup (relative to cdpilot project root)
_BLOG_DAY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              '.claude', 'docs', 'twitter-master-plan', 'days')


def _blog_slugify(text):
    """Generate valid kebab-case slug, max 50 chars."""
    text = text.lower()
    text = _re.sub(r'[^a-z0-9\s-]', '', text)
    text = _re.sub(r'[\s-]+', '-', text).strip('-')
    return text[:50]


def _blog_estimate_words(text):
    """Rough word count for gate checking."""
    return len(text.split())


def _blog_parse_day_file(content):
    """Parse day-NNN.md format. Returns dict: topic, tweets[], metadata{}."""
    data = {'topic': 'Untitled', 'tweets': [], 'metadata': {}}

    # Topic: text on the line(s) after '## Topic'
    topic_m = _re.search(r'^## Topic\s*\n+([^\n#]+)', content, _re.MULTILINE)
    if topic_m:
        data['topic'] = topic_m.group(1).strip()

    # Tweets: ## Tweet N/M — optional label, then text until next ##
    tweet_blocks = _re.findall(
        r'^## Tweet \d+/\d+(?:[^\n]*)?\n+(.*?)(?=\n## |\Z)',
        content, _re.DOTALL | _re.MULTILINE
    )
    data['tweets'] = [t.strip() for t in tweet_blocks if t.strip()]

    # Metadata block: lines like "- hashtags: #devtools"
    meta_block_m = _re.search(r'^## Metadata\s*\n(.*?)(?=\n## |\Z)', content,
                               _re.DOTALL | _re.MULTILINE)
    if meta_block_m:
        for line in meta_block_m.group(1).splitlines():
            kv = _re.match(r'^\s*-\s*(\w+):\s*(.+)', line)
            if kv:
                data['metadata'][kv.group(1).strip()] = kv.group(2).strip()

    return data


def _blog_generate_frontmatter(meta):
    """Render YAML frontmatter block."""
    lines = ['---']
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f'{k}:')
            for item in v:
                lines.append(f'  - {item}')
        else:
            val = str(v).replace('"', '\\"')
            lines.append(f'{k}: "{val}"')
    lines.append('---')
    return '\n'.join(lines)


def _blog_section_title(tweet_text):
    """Derive a short H2 title from tweet text (first 6 words, title-cased)."""
    words = tweet_text.split()[:6]
    title = ' '.join(words).rstrip('.,!?:')
    return title if title else 'Key Insight'


def _blog_generate_faq(tweets, topic):
    """Generate 3-5 FAQ Q&A pairs from tweet content."""
    faq_templates = [
        ("What problem does {topic} solve?",
         "It addresses the overhead and abstraction layers in traditional browser automation. "
         "By working directly at the CDP level, {topic} eliminates middleman processes and reduces latency."),
        ("How does this compare to existing tools like Selenium or Playwright?",
         "Those tools add driver layers between your code and the browser. This approach connects directly "
         "via WebSocket, giving lower latency, direct event access, and zero binary version mismatches."),
        ("Do I need to install anything to get started?",
         "No external dependencies are required. cdpilot uses only stdlib — no driver binaries, "
         "no package managers beyond npm for the CLI entry point."),
        ("Is this suitable for production automation?",
         "Yes. The direct CDP connection is the same mechanism DevTools itself uses. "
         "It is stable, well-documented, and used in large-scale scraping and testing pipelines."),
        ("Can I use this for parallel automation tasks?",
         "Yes. cdpilot supports browser context pools (Target.createBrowserContext) for true "
         "parallelism across isolated sessions without spawning multiple browser processes."),
    ]
    # Inject topic into templates
    items = []
    for q_tmpl, a_tmpl in faq_templates[:max(3, min(5, len(tweets) + 1))]:
        q = q_tmpl.format(topic=topic)
        a = a_tmpl.format(topic=topic)
        items.append((q, a))
    return items


def cmd_blog_publish(source):
    """Transform a tweet thread or day-NNN.md file into a blog post."""
    source_tweet = source
    parsed = {'topic': 'Browser Automation', 'tweets': [], 'metadata': {}}

    is_url = source.startswith(('https://x.com', 'https://twitter.com'))

    if is_url:
        print(f"Note: live URL fetch for {source} requires cdpilot browser running. "
              f"Storing URL as reference — content will need manual expansion.", file=sys.stderr)
        parsed['topic'] = 'Browser Automation Insight'
        parsed['tweets'] = [f'Read the full thread at {source}']
    else:
        # Resolve file path
        file_path = None
        if _re.match(r'^day-\d{3}$', source):
            file_path = os.path.join(_BLOG_DAY_DIR, f'{source}.md')
        elif source.endswith('.md') or os.sep in source:
            file_path = source
        else:
            # Try day-NNN format without .md
            candidate = os.path.join(_BLOG_DAY_DIR, f'{source}.md')
            file_path = candidate if os.path.exists(candidate) else source

        if not os.path.exists(file_path):
            print(f"Error: source file not found: {file_path}", file=sys.stderr)
            sys.exit(1)

        with open(file_path, encoding='utf-8') as f:
            raw = f.read()
        parsed = _blog_parse_day_file(raw)

    tweets = parsed['tweets']
    topic = parsed['topic']

    if len(tweets) < 1:
        print("Error: needs more depth — add more tweets or richer content", file=sys.stderr)
        sys.exit(1)

    hook = tweets[0]
    # Title: topic + hook first 6 words, capped at 60 chars
    hook_preview = ' '.join(hook.split()[:6]).rstrip('.,!?')
    raw_title = f"{topic}: {hook_preview}"
    title = raw_title[:60].strip()

    description = hook[:160].strip()
    slug = _blog_slugify(topic)

    if not slug or not _re.match(r'^[a-z0-9]+(-[a-z0-9]+)*$', slug):
        print(f"Error: could not generate valid slug from \"{topic}\".", file=sys.stderr)
        sys.exit(1)

    # Tags: from metadata hashtags + defaults
    tags = ['cdpilot', 'browser-automation']
    raw_hashtags = parsed['metadata'].get('hashtags', '')
    for ht in raw_hashtags.split():
        cleaned = ht.strip('# ')
        if cleaned and cleaned not in tags:
            tags.append(cleaned)

    meta = {
        'title': title,
        'description': description,
        'date': datetime.date.today().isoformat(),
        'tags': tags,
        'slug': slug,
        'author': 'cdpilot',
        'source_tweet': source_tweet,
    }

    parts = [_blog_generate_frontmatter(meta), f'\n# {title}\n']

    # Introduction (tweet 1 expanded)
    parts.append(
        f'\n## Introduction\n\n'
        f'[EXPAND: Expand into ~300 words. Hook: {hook}]\n\n'
        f'{hook}\n'
    )

    # Body sections: each middle tweet → H2
    for tweet in tweets[1:]:
        section_title = _blog_section_title(tweet)
        parts.append(
            f'\n## {section_title}\n\n'
            f'[EXPAND: 200-400 words expanding this point.]\n\n'
            f'{tweet}\n'
        )

    # Why It Matters
    parts.append(
        f'\n## Why This Matters\n\n'
        f'[EXPAND: 1-2 paragraphs on developer impact. '
        f'What changes in practice when you adopt this approach?]\n'
    )

    # FAQ (GEO-optimized)
    faq_items = _blog_generate_faq(tweets, topic)
    faq_lines = ['\n## FAQ\n']
    for q, a in faq_items:
        faq_lines.append(f'### Q: {q}\n{a}\n')
    parts.append('\n'.join(faq_lines))

    # Related
    parts.append(f'\n## Related\n\nOriginal thread: [{source_tweet}]({source_tweet})\n')

    final_md = '\n'.join(parts)

    # Check for slug collision
    out_dir = BLOG_DIR
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f'{slug}.md')
    if os.path.exists(out_path):
        print(f"Warning: {slug}.md already exists. Use: cdpilot blog regenerate {slug} to overwrite.",
              file=sys.stderr)
        sys.exit(1)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(final_md)

    word_count = _blog_estimate_words(final_md)
    print(f"Published: {out_path}")
    print(f"Estimated word count: {word_count}")
    if word_count < 800:
        print(f"Warning: needs expansion (estimated {word_count} words, target 800+)")


def cmd_blog_list():
    """List all published blog posts with slug, date, and title."""
    if not os.path.isdir(BLOG_DIR):
        print("No blog posts found")
        return

    files = sorted(
        [f for f in os.listdir(BLOG_DIR) if f.endswith('.md')],
        reverse=True
    )
    if not files:
        print("No blog posts found")
        return

    print(f"{'SLUG':<35} | {'DATE':<12} | TITLE")
    print('-' * 80)
    for fname in files:
        fpath = os.path.join(BLOG_DIR, fname)
        with open(fpath, encoding='utf-8') as f:
            content = f.read()
        t_m = _re.search(r'^title:\s*"(.*?)"', content, _re.MULTILINE)
        d_m = _re.search(r'^date:\s*"(.*?)"', content, _re.MULTILINE)
        title = t_m.group(1) if t_m else 'Untitled'
        date = d_m.group(1) if d_m else 'Unknown'
        slug = fname[:-3]
        print(f"{slug[:35]:<35} | {date:<12} | {title}")


def cmd_blog_regenerate(slug):
    """Re-generate a blog post from its original source_tweet frontmatter field."""
    out_path = os.path.join(BLOG_DIR, f'{slug}.md')
    if not os.path.exists(out_path):
        print(f"Error: blog post not found: {out_path}", file=sys.stderr)
        sys.exit(1)

    with open(out_path, encoding='utf-8') as f:
        content = f.read()

    s_m = _re.search(r'^source_tweet:\s*"(.*?)"', content, _re.MULTILINE)
    if not s_m:
        print("Error: could not find source_tweet in frontmatter", file=sys.stderr)
        sys.exit(1)

    # Remove existing file so publish doesn't hit collision guard
    os.remove(out_path)
    cmd_blog_publish(s_m.group(1))


def _dispatch_blog_cmd(args):
    """Parse blog subcommand args. Sync — called directly from sync_cmds."""
    sub = args[0] if args else ''

    if not sub or sub in ('--help', 'help', '-h'):
        print("Usage: cdpilot blog <subcommand> [options]", file=sys.stderr)
        print("", file=sys.stderr)
        print("Subcommands:", file=sys.stderr)
        print("  publish <source>      Source: tweet URL, day-NNN, or .md file path", file=sys.stderr)
        print("  list                  List all published blog posts", file=sys.stderr)
        print("  regenerate <slug>     Re-generate post from its original source", file=sys.stderr)
        print("", file=sys.stderr)
        print("Examples:", file=sys.stderr)
        print("  cdpilot blog publish day-001", file=sys.stderr)
        print("  cdpilot blog publish https://x.com/user/status/123", file=sys.stderr)
        print("  cdpilot blog list", file=sys.stderr)
        print("  cdpilot blog regenerate cdp-websocket-session-init", file=sys.stderr)
        sys.exit(0)

    if sub == 'publish':
        if len(args) < 2:
            print("Error: publish requires a source argument.", file=sys.stderr)
            print("Usage: cdpilot blog publish <tweet-url|day-NNN|file.md>", file=sys.stderr)
            sys.exit(1)
        cmd_blog_publish(args[1])
    elif sub == 'list':
        cmd_blog_list()
    elif sub == 'regenerate':
        if len(args) < 2:
            print("Error: regenerate requires a slug argument.", file=sys.stderr)
            sys.exit(1)
        cmd_blog_regenerate(args[1])
    else:
        print(f"Unknown blog subcommand: {sub}. Run: cdpilot blog --help", file=sys.stderr)
        sys.exit(1)

# ─── End Blog Publish Namespace ───────────────────────────────────────────────


# ─── cdpilot watch — continuous screencast for AI video understanding ─────────
#
# Why this exists: still screenshots taken at command-rate intervals (~1s)
# cannot capture animation, mouse cursors, scroll dynamics, or short visual
# events ("kedi sola mı sağa mı koştu?"). CDP's built-in Page.startScreencast
# streams JPEG frames at 10-30fps directly from the renderer. We tee the
# stream onto a disk ring buffer so AI orchestrators (Claude, etc.) can query
# any time window after the fact and get real frames to feed into a
# multimodal API. Two-process design: a long-lived daemon owns the WS and
# writes frames; foreground `query/status/stop` commands only read disk.

WATCH_DEFAULT_FPS = 10
WATCH_DEFAULT_QUALITY = 70
WATCH_DEFAULT_MAX_WIDTH = 1280
WATCH_DEFAULT_RETENTION_S = 300     # 5 minutes
WATCH_DEFAULT_DISK_CAP_MB = 100
WATCH_DAEMON_FLAG = '--_watch-daemon'  # hidden — used only for re-entrant fork


def _watch_dir():
    """Return per-project watch directory (state + frames + index)."""
    pid = PROJECT_ID or _get_project_id()
    return os.path.join(CDPILOT_HOME, 'projects', pid, 'watch')


def _watch_frames_dir():
    return os.path.join(_watch_dir(), 'frames')


def _watch_state_path():
    return os.path.join(_watch_dir(), 'state.json')


def _watch_index_path():
    return os.path.join(_watch_dir(), 'index.jsonl')


def _watch_log_path():
    return os.path.join(_watch_dir(), 'daemon.log')


def _watch_load_state():
    try:
        with open(_watch_state_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _watch_save_state(state):
    os.makedirs(_watch_dir(), exist_ok=True)
    tmp = _watch_state_path() + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, _watch_state_path())


def _watch_clear_state():
    for p in (_watch_state_path(), _watch_index_path()):
        try:
            os.remove(p)
        except OSError:
            pass


def _watch_pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _watch_parse_timecode(spec):
    """Parse '1:23', '83', '1:23.5' into seconds (float). Returns None on failure."""
    if spec is None:
        return None
    s = str(spec).strip()
    if not s:
        return None
    try:
        if ':' in s:
            mm, ss = s.split(':', 1)
            return float(mm) * 60 + float(ss)
        return float(s)
    except ValueError:
        return None


def _watch_parse_window(spec):
    """Parse '5s', '2.5', '500ms' into seconds (float). Returns 5.0 on failure."""
    if spec is None:
        return 5.0
    s = str(spec).strip().lower()
    if not s:
        return 5.0
    try:
        if s.endswith('ms'):
            return float(s[:-2]) / 1000.0
        if s.endswith('s'):
            return float(s[:-1])
        return float(s)
    except ValueError:
        return 5.0


def _watch_evict(retention_s, disk_cap_bytes):
    """Drop frames older than retention OR over disk cap (oldest-first).

    Returns (removed_count, bytes_freed).
    """
    fdir = _watch_frames_dir()
    if not os.path.isdir(fdir):
        return 0, 0
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - int(retention_s * 1000)

    files = []
    for name in os.listdir(fdir):
        if not name.endswith('.jpg'):
            continue
        try:
            ts_ms = int(name[:-4])
        except ValueError:
            continue
        path = os.path.join(fdir, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        files.append((ts_ms, path, size))
    files.sort()  # oldest first

    removed = 0
    freed = 0
    # Age-based eviction
    keep = []
    for ts_ms, path, size in files:
        if ts_ms < cutoff_ms:
            try:
                os.remove(path)
                removed += 1
                freed += size
            except OSError:
                pass
        else:
            keep.append((ts_ms, path, size))

    # Disk-cap eviction (drop oldest until under cap)
    total = sum(s for _, _, s in keep)
    while keep and total > disk_cap_bytes:
        ts_ms, path, size = keep.pop(0)
        try:
            os.remove(path)
            removed += 1
            freed += size
            total -= size
        except OSError:
            pass

    return removed, freed


def _watch_list_frames():
    """Scan the ring buffer dir, return sorted list of (ts_ms, path)."""
    fdir = _watch_frames_dir()
    out = []
    if not os.path.isdir(fdir):
        return out
    for name in os.listdir(fdir):
        if not name.endswith('.jpg'):
            continue
        try:
            ts_ms = int(name[:-4])
        except ValueError:
            continue
        out.append((ts_ms, os.path.join(fdir, name)))
    out.sort()
    return out


def _watch_frame_diff(a_path, b_path):
    """Mean absolute pixel difference (0.0..1.0). Returns None if PIL missing.

    Graceful degradation: if PIL/Pillow is not installed we return None and
    callers fall back to uniform frame picking.
    """
    try:
        from PIL import Image, ImageChops, ImageStat  # type: ignore
    except ImportError:
        return None
    try:
        with Image.open(a_path) as a_img, Image.open(b_path) as b_img:
            a_g = a_img.convert('L').resize((160, 90))
            b_g = b_img.convert('L').resize((160, 90))
            diff = ImageChops.difference(a_g, b_g)
            stat = ImageStat.Stat(diff)
            return float(stat.mean[0]) / 255.0
    except Exception:
        return None


# ─── watch daemon (the actual screencast consumer) ───

async def _watch_daemon_run(url, fps, quality, max_width, retention_s,
                            disk_cap_bytes, seek_s):
    """Long-lived process: open WS, subscribe to screencastFrame, write JPEGs.

    Runs until SIGTERM / parent kill. Each frame:
      1. base64-decode payload
      2. write to frames/<unix_ms>.jpg
      3. ACK with Page.screencastFrameAck (required, else stream stalls)
      4. periodically evict (every ~2s)
    """
    import websockets

    fdir = _watch_frames_dir()
    os.makedirs(fdir, exist_ok=True)

    # Launch browser if needed
    if not cdp_get("/json/version"):
        cmd_launch()

    ws_url, _ = get_page_ws()

    # Navigate first (so the page exists before we start screencasting).
    # If url is empty we just attach to whatever is currently loaded.
    if url:
        try:
            await navigate_collect(ws_url, url, glow=False)
        except Exception as e:
            sys.stderr.write(f"watch: navigate failed: {e}\n")

    # Try to coax a <video> element into autoplay + (optional) seek.
    # Best-effort — silent if the page has no video.
    autoplay_js = (
        "(()=>{const v=document.querySelector('video');"
        "if(!v) return {ok:false,reason:'no-video'};"
        "try{v.muted=true;v.playsInline=true;"
        + (f"v.currentTime={float(seek_s)};" if seek_s is not None else "")
        + "const p=v.play();if(p&&p.catch)p.catch(()=>{});"
        "return {ok:true,duration:v.duration||0,currentTime:v.currentTime};}"
        "catch(e){return {ok:false,reason:String(e)};}})()"
    )
    try:
        await cdp_send(ws_url, [(81, "Runtime.evaluate", {
            "expression": autoplay_js, "returnByValue": True,
        })])
    except Exception:
        pass

    # everyNthFrame: CDP samples at ~60fps native; nth=6 → ~10fps.
    every_nth = max(1, int(round(60 / max(1, fps))))

    # We bypass the pooled cdp_send for the screencast loop because we need
    # to consume *unsolicited* event frames (Page.screencastFrame) for the
    # entire daemon lifetime. The pool model assumes request/response.
    async with websockets.connect(ws_url, max_size=100 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Page.enable", "params": {}}))
        await ws.send(json.dumps({
            "id": 2, "method": "Page.startScreencast",
            "params": {
                "format": "jpeg",
                "quality": int(quality),
                "maxWidth": int(max_width),
                "everyNthFrame": every_nth,
            },
        }))

        last_evict = time.time()
        frame_count = 0
        # Update state file with confirmed start so `status` shows "running"
        st = _watch_load_state() or {}
        st['screencast_started_at_ms'] = int(time.time() * 1000)
        _watch_save_state(st)

        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                # Periodic eviction even if no frames arrive (e.g. page paused)
                if time.time() - last_evict > 2.0:
                    _watch_evict(retention_s, disk_cap_bytes)
                    last_evict = time.time()
                continue
            try:
                data = json.loads(resp)
            except ValueError:
                continue
            if data.get("method") != "Page.screencastFrame":
                continue
            params = data.get("params", {})
            session_id = params.get("sessionId")
            b64 = params.get("data", "")
            ts_ms = int(time.time() * 1000)

            try:
                raw = base64.b64decode(b64)
            except Exception:
                raw = b""
            if raw:
                fpath = os.path.join(fdir, f"{ts_ms}.jpg")
                try:
                    with open(fpath, 'wb') as f:
                        f.write(raw)
                    # Append to index (best-effort; missing entries are fine,
                    # query falls back to scanning the dir directly)
                    try:
                        with open(_watch_index_path(), 'a') as idx:
                            idx.write(json.dumps({
                                "ts_ms": ts_ms,
                                "filename": f"{ts_ms}.jpg",
                                "size": len(raw),
                            }) + "\n")
                    except OSError:
                        pass
                    frame_count += 1
                except OSError as e:
                    sys.stderr.write(f"watch: write failed: {e}\n")

            # ACK is REQUIRED — CDP stops sending frames until acknowledged.
            try:
                await ws.send(json.dumps({
                    "id": 1000 + (frame_count % 10000),
                    "method": "Page.screencastFrameAck",
                    "params": {"sessionId": session_id},
                }))
            except Exception:
                break

            # Periodic eviction (every ~2s)
            if time.time() - last_evict > 2.0:
                _watch_evict(retention_s, disk_cap_bytes)
                last_evict = time.time()


def _cmd_watch_daemon_entry():
    """Internal: re-entrant entry point when called with --_watch-daemon flag.

    Reads parameters from state file, runs the async screencast loop forever.
    Logs go to daemon.log so the foreground process can stay clean.
    """
    state = _watch_load_state() or {}
    url = state.get('url') or ''
    fps = int(state.get('fps') or WATCH_DEFAULT_FPS)
    quality = int(state.get('quality') or WATCH_DEFAULT_QUALITY)
    max_width = int(state.get('max_width') or WATCH_DEFAULT_MAX_WIDTH)
    retention_s = float(state.get('retention_s') or WATCH_DEFAULT_RETENTION_S)
    disk_cap_bytes = int(state.get('disk_cap_bytes') or WATCH_DEFAULT_DISK_CAP_MB * 1024 * 1024)
    seek_s = state.get('seek_s')

    state['pid'] = os.getpid()
    state['daemon_started_at_ms'] = int(time.time() * 1000)
    _watch_save_state(state)

    try:
        asyncio.run(_watch_daemon_run(
            url, fps, quality, max_width, retention_s, disk_cap_bytes, seek_s
        ))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        try:
            with open(_watch_log_path(), 'a') as f:
                f.write(f"[{datetime.datetime.utcnow().isoformat()}] daemon crash: {e}\n")
        except OSError:
            pass


def cmd_watch_start(*args):
    """Start screencast capture in a background daemon.

    cdpilot watch start <url|file://path|->  [--fps=10] [--quality=70]
                                              [--max-width=1280]
                                              [--retention=300]
                                              [--disk-cap=100]
                                              [--seek=1:23]

    - URL may be omitted to attach to the currently-loaded page.
    - `-` as URL also means "attach, don't navigate".
    - Idempotent: if a daemon for this project is already running it is
      stopped first (we never want two screencasts on the same target).
    """
    # Stop any prior daemon — two screencasts on one target would race.
    prev = _watch_load_state()
    if prev and _watch_pid_alive(prev.get('pid')):
        try:
            os.kill(int(prev['pid']), 15)
        except OSError:
            pass
        # brief wait so the WS releases
        for _ in range(20):
            if not _watch_pid_alive(prev.get('pid')):
                break
            time.sleep(0.05)

    # Wipe ring buffer + index from any prior run (same project, different video)
    fdir = _watch_frames_dir()
    if os.path.isdir(fdir):
        for name in os.listdir(fdir):
            if name.endswith('.jpg'):
                try:
                    os.remove(os.path.join(fdir, name))
                except OSError:
                    pass
    try:
        os.remove(_watch_index_path())
    except OSError:
        pass

    # Parse args
    url = ''
    fps = WATCH_DEFAULT_FPS
    quality = WATCH_DEFAULT_QUALITY
    max_width = WATCH_DEFAULT_MAX_WIDTH
    retention_s = WATCH_DEFAULT_RETENTION_S
    disk_cap_mb = WATCH_DEFAULT_DISK_CAP_MB
    seek_s = None

    positional = []
    for a in args:
        if a.startswith('--fps='):
            try:
                fps = max(1, min(30, int(a.split('=', 1)[1])))
            except ValueError:
                pass
        elif a.startswith('--quality='):
            try:
                quality = max(1, min(100, int(a.split('=', 1)[1])))
            except ValueError:
                pass
        elif a.startswith('--max-width='):
            try:
                max_width = max(160, min(3840, int(a.split('=', 1)[1])))
            except ValueError:
                pass
        elif a.startswith('--retention='):
            try:
                retention_s = max(5, int(a.split('=', 1)[1]))
            except ValueError:
                pass
        elif a.startswith('--disk-cap='):
            try:
                disk_cap_mb = max(1, int(a.split('=', 1)[1]))
            except ValueError:
                pass
        elif a.startswith('--seek='):
            seek_s = _watch_parse_timecode(a.split('=', 1)[1])
        elif not a.startswith('--'):
            positional.append(a)

    if positional:
        url = positional[0]
        if url == '-':
            url = ''

    os.makedirs(_watch_frames_dir(), exist_ok=True)
    state = {
        'url': url,
        'fps': fps,
        'quality': quality,
        'max_width': max_width,
        'retention_s': retention_s,
        'disk_cap_bytes': disk_cap_mb * 1024 * 1024,
        'seek_s': seek_s,
        'started_at_ms': int(time.time() * 1000),
        'project_id': PROJECT_ID,
        'pid': None,
    }
    _watch_save_state(state)

    # Fork the daemon. Use the same python + this script + the hidden flag.
    script = os.path.abspath(__file__)
    log_f = None
    try:
        log_f = open(_watch_log_path(), 'a')
    except OSError:
        log_f = subprocess.DEVNULL

    env = os.environ.copy()
    env['CDPILOT_PROJECT_ID'] = PROJECT_ID or _get_project_id()
    # The daemon must use the same CDP port (same project's browser)
    env['CDP_PORT'] = str(CDP_PORT)

    proc = subprocess.Popen(
        [sys.executable, script, WATCH_DAEMON_FLAG],
        stdout=log_f, stderr=log_f,
        env=env,
        start_new_session=True,  # detach from this terminal's process group
    )
    state['pid'] = proc.pid
    _watch_save_state(state)

    # Wait briefly for the daemon to confirm screencast start
    confirmed = False
    for _ in range(40):  # up to ~2s
        time.sleep(0.05)
        st = _watch_load_state() or {}
        if st.get('screencast_started_at_ms'):
            confirmed = True
            break
        if not _watch_pid_alive(proc.pid):
            break

    out = {
        'ok': confirmed or _watch_pid_alive(proc.pid),
        'pid': proc.pid,
        'url': url or '(attach)',
        'fps': fps,
        'quality': quality,
        'max_width': max_width,
        'retention_s': retention_s,
        'disk_cap_mb': disk_cap_mb,
        'frames_dir': _watch_frames_dir(),
        'state_path': _watch_state_path(),
    }
    print(json.dumps(out, indent=2))
    if not out['ok']:
        sys.exit(1)


def cmd_watch_stop(*args):
    """Stop the watch daemon and optionally cleanup frames."""
    keep_frames = '--keep-frames' in args
    state = _watch_load_state()
    if not state:
        print(json.dumps({'ok': True, 'message': 'no active watch session'}))
        return

    pid = state.get('pid')
    killed = False
    if pid and _watch_pid_alive(pid):
        try:
            os.kill(int(pid), 15)
            killed = True
        except OSError:
            pass
        for _ in range(40):
            if not _watch_pid_alive(pid):
                break
            time.sleep(0.05)
        if _watch_pid_alive(pid):
            try:
                os.kill(int(pid), 9)
            except OSError:
                pass

    removed = 0
    if not keep_frames:
        fdir = _watch_frames_dir()
        if os.path.isdir(fdir):
            for name in os.listdir(fdir):
                if name.endswith('.jpg'):
                    try:
                        os.remove(os.path.join(fdir, name))
                        removed += 1
                    except OSError:
                        pass
        try:
            os.remove(_watch_index_path())
        except OSError:
            pass

    _watch_clear_state()
    print(json.dumps({
        'ok': True,
        'killed': killed,
        'pid': pid,
        'frames_removed': removed,
        'kept_frames': keep_frames,
    }, indent=2))


def cmd_watch_status(*args):
    """Report daemon state, frame count, disk usage."""
    state = _watch_load_state()
    frames = _watch_list_frames()
    total_size = sum(os.path.getsize(p) for _, p in frames if os.path.exists(p)) if frames else 0

    out = {
        'running': bool(state and _watch_pid_alive(state.get('pid'))),
        'frames': len(frames),
        'disk_bytes': total_size,
        'disk_mb': round(total_size / (1024 * 1024), 2),
        'oldest_ts_ms': frames[0][0] if frames else None,
        'newest_ts_ms': frames[-1][0] if frames else None,
    }
    if state:
        out['pid'] = state.get('pid')
        out['url'] = state.get('url') or '(attach)'
        out['fps'] = state.get('fps')
        out['started_at_ms'] = state.get('started_at_ms')
        out['screencast_started_at_ms'] = state.get('screencast_started_at_ms')
        out['retention_s'] = state.get('retention_s')
        out['disk_cap_mb'] = (state.get('disk_cap_bytes') or 0) // (1024 * 1024)
    print(json.dumps(out, indent=2))


def _watch_last_query_path():
    return os.path.join(_watch_dir(), 'last-query.json')


def cmd_watch_query(*args):
    """Return frame paths inside a time window as JSON.

    cdpilot watch query --at <mm:ss|sec> --window <Ns>  [--max=16]
    cdpilot watch query --since-last [--max=16]
    cdpilot watch query --last <Ns> [--max=16]    (relative to newest frame)

    Time mapping: --at is interpreted as VIDEO time, measured from the moment
    the screencast started (state['screencast_started_at_ms']). This matches
    user intuition for "what happened at 0:35" because we begin capturing
    right after autoplay.
    """
    state = _watch_load_state()
    if not state:
        print(json.dumps({'frames': [], 'count': 0, 'error': 'no watch session'}))
        return

    max_frames = 16
    at_s = None
    window_s = 5.0
    since_last = False
    last_window = None

    args_list = list(args)
    i = 0
    while i < len(args_list):
        a = args_list[i]
        if a == '--at' and i + 1 < len(args_list):
            at_s = _watch_parse_timecode(args_list[i + 1])
            i += 2
        elif a.startswith('--at='):
            at_s = _watch_parse_timecode(a.split('=', 1)[1])
            i += 1
        elif a == '--window' and i + 1 < len(args_list):
            window_s = _watch_parse_window(args_list[i + 1])
            i += 2
        elif a.startswith('--window='):
            window_s = _watch_parse_window(a.split('=', 1)[1])
            i += 1
        elif a == '--max' and i + 1 < len(args_list):
            try:
                max_frames = max(1, min(64, int(args_list[i + 1])))
            except ValueError:
                pass
            i += 2
        elif a.startswith('--max='):
            try:
                max_frames = max(1, min(64, int(a.split('=', 1)[1])))
            except ValueError:
                pass
            i += 1
        elif a == '--since-last':
            since_last = True
            i += 1
        elif a == '--last' and i + 1 < len(args_list):
            last_window = _watch_parse_window(args_list[i + 1])
            i += 2
        elif a.startswith('--last='):
            last_window = _watch_parse_window(a.split('=', 1)[1])
            i += 1
        else:
            i += 1

    frames = _watch_list_frames()
    if not frames:
        print(json.dumps({'frames': [], 'count': 0, 'duration_s': 0}))
        return

    sc_start_ms = state.get('screencast_started_at_ms') or state.get('started_at_ms') or frames[0][0]
    selected = []

    if since_last:
        last_q = 0
        try:
            with open(_watch_last_query_path()) as f:
                last_q = int(json.load(f).get('ts_ms') or 0)
        except (OSError, ValueError):
            last_q = 0
        selected = [(ts, p) for ts, p in frames if ts > last_q]
    elif last_window is not None:
        newest_ts = frames[-1][0]
        lo_ms = newest_ts - int(last_window * 1000)
        selected = [(ts, p) for ts, p in frames if ts >= lo_ms]
    elif at_s is not None:
        # Map video time to wall-clock ms
        center_ms = sc_start_ms + int(at_s * 1000)
        half_ms = int((window_s / 2.0) * 1000)
        lo_ms = center_ms - half_ms
        hi_ms = center_ms + half_ms
        selected = [(ts, p) for ts, p in frames if lo_ms <= ts <= hi_ms]
    else:
        # Default: the latest <window_s> seconds
        newest_ts = frames[-1][0]
        lo_ms = newest_ts - int(window_s * 1000)
        selected = [(ts, p) for ts, p in frames if ts >= lo_ms]

    # Downsample to max_frames (uniform pick, keep first + last)
    if len(selected) > max_frames:
        # Try motion-aware picking when PIL is available
        motion_scores = []
        for j in range(1, len(selected)):
            d = _watch_frame_diff(selected[j - 1][1], selected[j][1])
            motion_scores.append(d if d is not None else 0.0)
        if motion_scores and any(s is not None for s in motion_scores):
            # Pick frames around the highest-motion peaks
            indices = sorted(range(len(motion_scores)),
                             key=lambda k: motion_scores[k], reverse=True)
            pick_idx = sorted(set([0, len(selected) - 1] + indices[:max_frames - 2]))
            pick_idx = pick_idx[:max_frames]
            selected = [selected[k] for k in pick_idx]
        else:
            # Uniform downsample
            step = len(selected) / max_frames
            picks = [int(j * step) for j in range(max_frames)]
            picks[-1] = len(selected) - 1
            selected = [selected[k] for k in picks]

    if selected:
        try:
            with open(_watch_last_query_path(), 'w') as f:
                json.dump({'ts_ms': selected[-1][0]}, f)
        except OSError:
            pass

    duration_s = (selected[-1][0] - selected[0][0]) / 1000.0 if len(selected) >= 2 else 0.0
    out = {
        'frames': [p for _, p in selected],
        'timestamps_ms': [t for t, _ in selected],
        'count': len(selected),
        'duration_s': round(duration_s, 3),
        'window_s': window_s,
        'at_s': at_s,
        'screencast_started_at_ms': sc_start_ms,
    }
    print(json.dumps(out, indent=2))


def cmd_watch_ask(*args):
    """Tiny natural-language wrapper around `watch query`.

    cdpilot watch ask "0:35'te kedi sola mı sağa mı koştu?"
    cdpilot watch ask "son 5 saniyede ne oldu"

    We don't actually do LLM inference here — this command just parses a
    time window out of the question and emits the same JSON shape as
    `watch query` so the orchestrator (Claude) can pick up the frames and
    feed them to a multimodal API itself.
    """
    if not args:
        print(json.dumps({'error': 'question required'}))
        sys.exit(1)
    question = ' '.join(args)
    q_lower = question.lower()

    # Find mm:ss or m:ss anywhere in the string
    m = _re.search(r'(\d+):(\d{1,2})(?:\.\d+)?', question)
    at_s = None
    if m:
        at_s = float(m.group(1)) * 60 + float(m.group(2))

    # "son N saniye(de)" / "last N seconds"
    last_match = _re.search(r'(?:son|last)\s+(\d+(?:\.\d+)?)\s*(?:saniye|sec|seconds?|s\b)', q_lower)
    last_window = float(last_match.group(1)) if last_match else None

    forward = []
    if at_s is not None:
        forward = ['--at', f'{int(at_s // 60)}:{at_s % 60:.2f}'.rstrip('0').rstrip('.'),
                   '--window', '5s']
    elif last_window is not None:
        forward = ['--last', f'{last_window}s']
    else:
        forward = ['--last', '5s']

    forward += ['--max', '8']
    cmd_watch_query(*forward)


def _dispatch_watch_cmd(args):
    """Parse `cdpilot watch <sub> ...` and dispatch. Sync wrapper."""
    sub = args[0] if args else ''
    rest = args[1:]
    if not sub or sub in ('--help', '-h', 'help'):
        print("Usage: cdpilot watch <subcommand> [options]", file=sys.stderr)
        print("", file=sys.stderr)
        print("Subcommands:", file=sys.stderr)
        print("  start [url|-] [--fps=N] [--quality=N] [--max-width=N]", file=sys.stderr)
        print("                 [--retention=SEC] [--disk-cap=MB] [--seek=MM:SS]", file=sys.stderr)
        print("  stop [--keep-frames]", file=sys.stderr)
        print("  query --at MM:SS --window 5s [--max=16]", file=sys.stderr)
        print("  query --since-last [--max=16]", file=sys.stderr)
        print("  query --last 5s [--max=16]", file=sys.stderr)
        print("  status", file=sys.stderr)
        print("  ask \"<natural-language question>\"", file=sys.stderr)
        sys.exit(0)
    if sub == 'start':
        cmd_watch_start(*rest)
    elif sub == 'stop':
        cmd_watch_stop(*rest)
    elif sub == 'query':
        cmd_watch_query(*rest)
    elif sub == 'status':
        cmd_watch_status(*rest)
    elif sub == 'ask':
        cmd_watch_ask(*rest)
    else:
        print(f"Unknown watch subcommand: {sub}. Run: cdpilot watch --help", file=sys.stderr)
        sys.exit(1)


# ─── End cdpilot watch namespace ──────────────────────────────────────────────


# ─── CLI ───

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    # POSIX-style flag aliases — accepted at the Python entry point too,
    # not just at the Node wrapper. Lets `python src/cdpilot.py --version`
    # work in CI and for users who skip the Node wrapper entirely.
    if cmd in ('--version', '-v'):
        cmd = 'version'
    elif cmd in ('--help', '-h'):
        print(__doc__)
        sys.exit(0)

    # Hidden re-entrant entry for the watch daemon. `cdpilot watch start`
    # forks this process with the flag so the screencast consumer runs in
    # the background while the foreground process returns immediately.
    if cmd == WATCH_DAEMON_FLAG:
        _cmd_watch_daemon_entry()
        sys.exit(0)

    sync_cmds = {
        'launch': cmd_launch,
        'tabs': cmd_tabs,
        'extensions': cmd_extensions,
        'stop': cmd_stop,
        'version': cmd_version,
        'proxy': lambda: cmd_proxy(*args),
        'headless': lambda: cmd_headless(args[0] if args else None),
        'stealth': lambda: cmd_stealth(args[0] if args else None),
        'mode': lambda: cmd_mode(args[0] if args else None),
        'block': lambda: cmd_block(*args),
        'context': lambda: cmd_context(*args),
        'show': lambda: cmd_show(args[0] if args else None),
        'fast': lambda: cmd_fast(args[0] if args else None),
        'adaptive': (lambda: cmd_adaptive_forget(args[1])) if (len(args) >= 2 and args[0].lower() == 'forget') else (lambda: cmd_adaptive(args[0] if args else None)),
        'entropy': lambda: cmd_entropy(args[0] if args else None),
        'browser': lambda: cmd_browser(args[0] if args else None),
        'health': cmd_health,
        'session': cmd_session,
        'sessions': cmd_sessions,
        'session-close': lambda: cmd_session_close(args[0] if args else None),
        'projects': cmd_projects,
        'project-stop': lambda: cmd_project_stop(args[0] if args else ''),
        'stop-all': cmd_stop_all,
        'heal': lambda: (
            cmd_heal_stats() if args and args[0] == 'stats'
            else cmd_heal_log(int(args[1]) if len(args) >= 2 and args[1].isdigit() else 20)
        ),
        'test': lambda: cmd_test_dispatch(args),
        'trace': lambda: cmd_trace_dispatch(args),
        'blog': lambda: _dispatch_blog_cmd(args),
        'watch': lambda: _dispatch_watch_cmd(args),
    }

    if cmd == "serve":
        _api_flag = '--api' in args
        _port_val = 9333
        for _a in args:
            if _a.startswith('--port='):
                _port_val = int(_a.split('=', 1)[1])
            elif _a == '--port' and args.index(_a) + 1 < len(args):
                _port_val = int(args[args.index(_a) + 1])
        cmd_serve(api=_api_flag, port=_port_val)
        sys.exit(0)

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

    # `stop --smart` aliases the smart close (owned tabs + browser-if-empty).
    # Bare `stop` keeps its legacy full-kill behavior for backward compatibility.
    if cmd == "stop" and "--smart" in args:
        asyncio.run(cmd_close(
            force_browser="--force" in args,
            keep_browser=("--keep" in args or "--keep-browser" in args),
        ))
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
        "eval-batch": lambda: (require_args(1, "eval-batch <json_array_of_expressions>"), None)[1] if not args else cmd_eval_batch(args[0]),
        "click": lambda: (require_args(1, "click <selector> [--ladder s1,s2] [--no-heal] [--entropy=on|off]"), None)[1] if not args else cmd_click(
            next(a for a in args if not a.startswith("--")),
            ladder=next((a.split("=")[1].split(",") for a in args if a.startswith("--ladder=")), None),
            no_heal="--no-heal" in args,
            entropy=True if "--entropy=on" in args else (False if "--entropy=off" in args else None),
        ),
        "fill": lambda: (require_args(2, "fill <selector> <value> [--ladder s1,s2] [--no-heal] [--entropy=on|off]"), None)[1] if len([a for a in args if not a.startswith("--")]) < 2 else cmd_fill(
            [a for a in args if not a.startswith("--")][0],
            " ".join([a for a in args if not a.startswith("--")][1:]),
            ladder=next((a.split("=")[1].split(",") for a in args if a.startswith("--ladder=")), None),
            no_heal="--no-heal" in args,
            entropy=True if "--entropy=on" in args else (False if "--entropy=off" in args else None),
        ),
        "submit": lambda: cmd_submit(
            next((a for a in args if not a.startswith("--")), "form"),
            ladder=next((a.split("=")[1].split(",") for a in args if a.startswith("--ladder=")), None),
            no_heal="--no-heal" in args,
        ),
        "type": lambda: (require_args(2, "type <selector> <value> [--ladder s1,s2] [--no-heal] [--entropy=on|off]"), None)[1] if len([a for a in args if not a.startswith("--")]) < 2 else cmd_fill(
            [a for a in args if not a.startswith("--")][0],
            " ".join([a for a in args if not a.startswith("--")][1:]),
            ladder=next((a.split("=")[1].split(",") for a in args if a.startswith("--ladder=")), None),
            no_heal="--no-heal" in args,
            entropy=True if "--entropy=on" in args else (False if "--entropy=off" in args else None),
        ),
        "wait": lambda: (require_args(1, "wait <selector>"), None)[1] if not args else cmd_wait(args[0], int(args[1]) if len(args) > 1 else 5),
        "tabs": cmd_tabs,
        "network": lambda: cmd_network(args[0] if args else None),
        "console": lambda: cmd_console(args[0] if args else None),
        "cookies": lambda: cmd_cookies(*args),
        "storage": cmd_storage,
        "wipe": lambda: cmd_wipe(*args),
        "tls-check": lambda: cmd_tls_check(*args),
        "perf": cmd_perf,
        "emulate": lambda: (require_args(1, "emulate <device>"), None)[1] if not args else cmd_emulate(args[0]),
        "glow": lambda: cmd_glow(args[0] if args else "on"),
        "debug": lambda: cmd_debug(args[0] if args else None),
        "close": lambda: cmd_close(
            force_browser="--force" in args,
            keep_browser=("--keep" in args or "--keep-browser" in args),
        ),
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
        'smart-click': lambda: (require_args(1, 'smart-click <text>'), None)[1] if not args else cmd_smart_click(" ".join(args)),
        'dismiss': lambda: cmd_dismiss(args[0] if args else None),
        'smart-fill': lambda: (require_args(2, 'smart-fill <label> <value>'), None)[1] if len(args) < 2 else cmd_smart_fill(args[0], " ".join(args[1:])),
        'smart-select': lambda: (require_args(2, 'smart-select <label> <option>'), None)[1] if len(args) < 2 else cmd_smart_select(args[0], " ".join(args[1:])),
        'assert': lambda: (require_args(1, 'assert <selector> [text]'), None)[1] if not args else cmd_assert(args[0], args[1] if len(args) > 1 else None),
        'wait-for': lambda: (require_args(1, 'wait-for <selector> [timeout_ms]'), None)[1] if not args else cmd_wait_for(args[0], int(args[1]) if len(args) > 1 else 5000),
        'wait-for-text': lambda: (require_args(1, 'wait-for-text <text> [timeout_ms]'), None)[1] if not args else cmd_wait_for_text(args[0], int(args[1]) if len(args) > 1 else 5000),
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
        'hover': lambda: (require_args(1, 'hover <selector> [--ladder s1,s2] [--no-heal] [--entropy=on|off]'), None)[1] if not args else cmd_hover(
            next(a for a in args if not a.startswith("--")),
            ladder=next((a.split("=")[1].split(",") for a in args if a.startswith("--ladder=")), None),
            no_heal="--no-heal" in args,
            entropy=True if "--entropy=on" in args else (False if "--entropy=off" in args else None),
        ),
        'dblclick': lambda: (require_args(1, 'dblclick <selector>'), None)[1] if not args else cmd_dblclick(args[0]),
        'rightclick': lambda: (require_args(1, 'rightclick <selector>'), None)[1] if not args else cmd_rightclick(args[0]),
        'drag': lambda: (require_args(2, 'drag <from-sel> <to-sel> [--entropy=on|off]'), None)[1] if len([a for a in args if not a.startswith("--")]) < 2 else cmd_drag(
            [a for a in args if not a.startswith("--")][0],
            [a for a in args if not a.startswith("--")][1],
            entropy=True if "--entropy=on" in args else (False if "--entropy=off" in args else None),
        ),
        'keys': lambda: (require_args(1, 'keys <combo>'), None)[1] if not args else cmd_keys(args[0]),
        'scroll-to': lambda: (require_args(1, 'scroll-to <selector> [--entropy=on|off]'), None)[1] if not args else cmd_scroll_to(
            next(a for a in args if not a.startswith("--")),
            entropy=True if "--entropy=on" in args else (False if "--entropy=off" in args else None),
        ),
        'frame': lambda: (require_args(1, 'frame [list|eval <js>|shadow <selector>]'), None)[1] if not args else cmd_frame(args[0], *args[1:]),
        'dialog': lambda: (require_args(1, 'dialog [auto-accept|auto-dismiss|prompt <text>|off]'), None)[1] if not args else cmd_dialog(args[0], *args[1:]),
        'download': lambda: (require_args(1, 'download [set <directory>|status]'), None)[1] if not args else cmd_download(args[0], *args[1:]),
        'throttle': lambda: (require_args(1, 'throttle [slow3g|fast3g|offline|off|custom <down> <up> <lat>]'), None)[1] if not args else cmd_throttle(args[0], *args[1:]),
        'geo': lambda: (require_args(1, 'geo [<lat> <lng>|istanbul|london|newyork|off]'), None)[1] if not args else cmd_geo(args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None),
        'permission': lambda: (require_args(1, 'permission [grant|deny|reset] [<permission>]'), None)[1] if not args else cmd_permission(args[0], args[1] if len(args) > 1 else None),
        'captcha-check': cmd_captcha_check,
        'captcha-wait': lambda: cmd_captcha_wait(args[0] if args else None),
        'captcha': lambda: cmd_captcha_dispatch(args),
        'friction': cmd_friction,
        'captcha-solve': lambda: cmd_captcha_solve(
            next((a.split('=')[1] for a in args if a.startswith('--provider=')),
                 args[args.index('--provider') + 1] if '--provider' in args and args.index('--provider') + 1 < len(args)
                 else (next((a for a in args if not a.startswith('--')), None))),
        ),
        'profile': lambda: cmd_profile_dispatch(args),
        'press-hold': lambda: cmd_press_hold(
            next((a for a in args if not a.startswith('--')), None)),
        'agent': lambda: _dispatch_agent_cmd(args),
    }

    # Commands that do not require the visual indicator / input blocker
    NO_CONTROL_CMDS = {'glow', 'stop', 'tabs', 'close', 'close-tab', 'new-tab',
                       'dialog', 'download', 'throttle', 'permission', 'intercept',
                       'batch', 'screenshot-diff', 'run',
                       'captcha-check', 'captcha-wait', 'captcha', 'friction',
                       'profile',
                       'cookies'}  # v0.6.1: cookies auto-config doesn't need browser
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

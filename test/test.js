#!/usr/bin/env node

/**
 * cdpilot — basic test suite
 * Tests CLI entry point, browser detection, and command routing
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const assert = require('assert');

const CLI = path.join(__dirname, '..', 'bin', 'cdpilot.js');
let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  ✓ ${name}`);
  } catch (err) {
    failed++;
    console.log(`  ✗ ${name}`);
    console.log(`    ${err.message}`);
  }
}

function run(args = '') {
  return execSync(`node ${CLI} ${args} 2>&1`, {
    timeout: 10000,
    encoding: 'utf-8',
    // CDP_PORT avoids a conflict with a real browser; this helper does not
    // isolate CDPILOT_HOME, so keep its commands out of the real session log.
    env: { ...process.env, CDP_PORT: '19222', CDPILOT_LOG: '0' },
  });
}

console.log('\n  cdpilot tests\n');

// ── CLI basics ──

test('--version prints version', () => {
  const out = run('--version');
  assert(out.includes(require('../package.json').version), 'Should print version');
});

test('-v prints version', () => {
  const out = run('-v');
  assert(out.includes(require('../package.json').version), 'Should print version');
});

test('help shows usage', () => {
  const out = run('help');
  assert(out.includes('cdpilot'), 'Should show cdpilot name');
  assert(out.includes('USAGE'), 'Should show USAGE section');
});

test('--help shows usage', () => {
  const out = run('--help');
  assert(out.includes('NAVIGATION'), 'Should show NAVIGATION section');
});

test('no args shows help', () => {
  const out = run('');
  assert(out.includes('SETUP'), 'Should show SETUP section');
});

// ── Setup ──

test('setup detects browser', () => {
  const out = run('setup');
  assert(out.includes('Browser:'), 'Should show browser detection');
  assert(out.includes('Profile:'), 'Should show profile path');
});

test('setup detects python', () => {
  const out = run('setup');
  assert(out.includes('Python:'), 'Should show Python detection');
});

test('setup detects python websockets', () => {
  const out = run('setup');
  assert(out.includes('websockets:'), 'Should show Python\'s websockets detection');
});

// ── File structure ──

test('cdpilot.py exists', () => {
  const pyPath = path.join(__dirname, '..', 'src', 'cdpilot.py');
  assert(fs.existsSync(pyPath), 'src/cdpilot.py should exist');
});

test('package.json has bin field', () => {
  const pkg = require('../package.json');
  assert(pkg.bin && pkg.bin.cdpilot, 'Should have bin.cdpilot');
});

test('package.json has correct name', () => {
  const pkg = require('../package.json');
  assert.strictEqual(pkg.name, 'cdpilot');
});

// ── Python script basics ──

test('python script has version', () => {
  const pyPath = path.join(__dirname, '..', 'src', 'cdpilot.py');
  if (fs.existsSync(pyPath)) {
    const content = fs.readFileSync(pyPath, 'utf-8');
    assert(content.includes('__version__'), 'Should have __version__');
  }
});

test('python script has shebang', () => {
  const pyPath = path.join(__dirname, '..', 'src', 'cdpilot.py');
  if (fs.existsSync(pyPath)) {
    const content = fs.readFileSync(pyPath, 'utf-8');
    assert(content.startsWith('#!/usr/bin/env python3'), 'Should have python3 shebang');
  }
});

// ── Stealth & CAPTCHA layer ──

const PY_PATH = path.join(__dirname, '..', 'src', 'cdpilot.py');
const PY_CONTENT = fs.existsSync(PY_PATH) ? fs.readFileSync(PY_PATH, 'utf-8') : '';

function extractRawTripleString(src, varName) {
  // Extract the content between  VARNAME = r"""  ...  """
  const re = new RegExp(varName + '\\s*=\\s*r"""([\\s\\S]*?)"""', 'm');
  const m = src.match(re);
  return m ? m[1] : null;
}

test('STEALTH_JS constant is defined', () => {
  // Three-tier split: the full body lives in STEALTH_JS_FULL; STEALTH_JS is a
  // backward-compat alias. Both must be present.
  assert(PY_CONTENT.includes('STEALTH_JS_FULL = r"""'), 'Should define STEALTH_JS_FULL');
  assert(/STEALTH_JS = STEALTH_JS_FULL/.test(PY_CONTENT), 'STEALTH_JS must alias STEALTH_JS_FULL');
});

test('STEALTH_JS is syntactically valid JavaScript', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(js, 'STEALTH_JS body should be extractable');
  const vm = require('vm');
  // new Script validates syntax without executing
  assert.doesNotThrow(() => new vm.Script(js), 'STEALTH_JS should parse as valid JS');
});

test('STEALTH_JS is idempotent (guards with __cdpilot_stealth flag)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(js.includes('__cdpilot_stealth'), 'Should guard against double-injection');
  assert(js.includes('if (window.__cdpilot_stealth) return'), 'Should early-return on repeat');
});

test('STEALTH_JS patches the documented fingerprint surfaces', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(js.includes("'webdriver'") || js.includes('"webdriver"'), 'Should patch navigator.webdriver');
  assert(js.includes('chrome.runtime') || js.includes("chrome.runtime"), 'Should patch chrome.runtime');
  assert(js.includes("'plugins'") || js.includes('"plugins"'), 'Should patch navigator.plugins');
  assert(js.includes('37445'), 'Should spoof WebGL UNMASKED_VENDOR (37445)');
  assert(js.includes('37446'), 'Should spoof WebGL UNMASKED_RENDERER (37446)');
  assert(js.includes('permissions.query') || js.includes('permissions'), 'Should patch permissions.query');
});

test('STEALTH_JS only patches webdriver when value is actually true (smart no-op)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(/wdValue\s*===\s*true/.test(js),
    'webdriver patch must be conditional on actual value being true — patching a benign Chrome creates a worse fingerprint');
});

test('STEALTH_JS plugins inherit from PluginArray.prototype (instanceof check)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(js.includes('PluginArray.prototype') || js.includes('PluginArrayProto'),
    'plugins must inherit from PluginArray.prototype, not vanilla Array');
  assert(js.includes('Plugin.prototype') || js.includes('PluginProto'),
    'individual plugins must inherit from Plugin.prototype');
});

test('STEALTH_JS patches Worker constructor for worker-context webdriver', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(/window\.Worker/.test(js), 'Should wrap window.Worker');
  assert(/createObjectURL/.test(js), 'Should use blob URL to inject patch');
  assert(/__cdpilot_worker_patched/.test(js), 'Should guard against double-patching Worker');
  assert(/options\s*&&\s*options\.type\s*===\s*'module'/.test(js),
    'Must skip module workers (importScripts incompatible)');
});

test('STEALTH_JS does NOT weaken web security primitives', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  // Fail-fast on common anti-patterns that would be a security regression.
  assert(!js.includes('eval('), 'Must not use eval()');
  assert(!js.includes('document.domain'), 'Must not relax same-origin via document.domain');
  assert(!js.includes('Content-Security-Policy'), 'Must not touch CSP');
  assert(!/fetch\(|XMLHttpRequest/.test(js), 'Must not make network calls');
});

test('CAPTCHA_DETECT_JS constant is defined', () => {
  assert(PY_CONTENT.includes('CAPTCHA_DETECT_JS = r"""'), 'Should define CAPTCHA_DETECT_JS');
});

test('CAPTCHA_DETECT_JS is syntactically valid JavaScript', () => {
  const js = extractRawTripleString(PY_CONTENT, 'CAPTCHA_DETECT_JS');
  assert(js, 'CAPTCHA_DETECT_JS body should be extractable');
  const vm = require('vm');
  assert.doesNotThrow(() => new vm.Script(js), 'CAPTCHA_DETECT_JS should parse as valid JS');
});

test('CAPTCHA_DETECT_JS covers major providers', () => {
  const js = extractRawTripleString(PY_CONTENT, 'CAPTCHA_DETECT_JS');
  assert(js.includes('challenges.cloudflare.com'), 'Should detect Turnstile');
  assert(js.includes('hcaptcha.com'), 'Should detect hCaptcha');
  assert(js.includes('recaptcha'), 'Should detect reCAPTCHA');
  assert(js.includes('datadome'), 'Should detect DataDome');
  assert(js.includes('arkoselabs.com') || js.includes('funcaptcha'), 'Should detect Arkose');
});

test('CAPTCHA_DETECT_JS is read-only (no DOM mutation or network)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'CAPTCHA_DETECT_JS');
  assert(!/\.innerHTML\s*=/.test(js), 'Must not write innerHTML');
  assert(!/\.appendChild\(/.test(js), 'Must not append DOM nodes');
  assert(!/fetch\(|XMLHttpRequest|navigator\.sendBeacon/.test(js), 'Must not make network calls');
  assert(!/localStorage|sessionStorage|document\.cookie/.test(js), 'Must not read storage/cookies');
});

test('get_stealth_config default is OFF (opt-in)', () => {
  // Look at the function body for the default return path.
  // \r?\n tolerates Windows CRLF checkouts (defense-in-depth alongside .gitattributes).
  const m = PY_CONTENT.match(/def get_stealth_config\(\):[\s\S]*?\r?\n    return (False|True)\r?\n/);
  assert(m, 'get_stealth_config should have a clear default return');
  assert.strictEqual(m[1], 'False', 'Default must be False (opt-in) for backward compat');
});

test('cmd_stealth is registered in sync dispatch', () => {
  assert(/'stealth':\s*lambda:\s*cmd_stealth/.test(PY_CONTENT),
    "Should register 'stealth' in sync_cmds dispatch");
});

test('captcha-check and captcha-wait are registered in async dispatch', () => {
  assert(/'captcha-check':\s*cmd_captcha_check/.test(PY_CONTENT),
    "Should register 'captcha-check' in async_map");
  assert(/'captcha-wait':\s*lambda:\s*cmd_captcha_wait/.test(PY_CONTENT),
    "Should register 'captcha-wait' in async_map");
});

test('captcha commands are in NO_CONTROL_CMDS (no glow interference)', () => {
  const m = PY_CONTENT.match(/NO_CONTROL_CMDS\s*=\s*\{([\s\S]*?)\}/);
  assert(m, 'NO_CONTROL_CMDS should exist');
  assert(m[1].includes("'captcha-check'"), 'captcha-check should bypass control wrapper');
  assert(m[1].includes("'captcha-wait'"), 'captcha-wait should bypass control wrapper');
});

// ── captcha-solve (Amazon classic + provider abstraction) ──

test('captcha-solve: cmd_captcha_solve defined + dispatched', () => {
  assert(/async def cmd_captcha_solve\(provider=None\)/.test(PY_CONTENT),
    'Should define async cmd_captcha_solve(provider=None)');
  assert(/'captcha-solve':\s*lambda:\s*cmd_captcha_solve/.test(PY_CONTENT),
    "Should register 'captcha-solve' in async_map dispatch");
});

test('captcha-solve: amazon detection via #captchacharacters', () => {
  const js = extractRawTripleString(PY_CONTENT, 'CAPTCHA_DETECT_JS');
  assert(js, 'CAPTCHA_DETECT_JS should be extractable');
  assert(js.includes('#captchacharacters'), 'Detection JS should look for #captchacharacters input');
  assert(js.includes('amazon-classic'), "Detection JS should tag 'amazon-classic'");
  assert(/opfcaptcha|images-na\.ssl-images-amazon\.com/.test(js),
    'Detection JS should match Amazon captcha image src patterns');
  assert(/async def _detect_amazon_captcha/.test(PY_CONTENT),
    'Should define _detect_amazon_captcha helper');
});

test('captcha-solve: graceful when amazoncaptcha not installed', () => {
  assert(/from amazoncaptcha import AmazonCaptcha/.test(PY_CONTENT),
    'Should lazily import amazoncaptcha (optional dependency)');
  const solver = PY_CONTENT.match(/def _solve_amazon_local[\s\S]*?return None\n/);
  assert(solver, '_solve_amazon_local should exist');
  assert(/except ImportError:\s*\n\s*return None/.test(solver[0]),
    '_solve_amazon_local must return None on ImportError (no hard dependency)');
  assert(/amazoncaptcha not installed\. Run: pip install amazoncaptcha/.test(PY_CONTENT),
    'cmd_captcha_solve should print an install hint when the lib is missing');
});

test('captcha-solve: capsolver BYOK reads CAPSOLVER_API_KEY env', () => {
  assert(/os\.environ\.get\('CAPSOLVER_API_KEY'\)/.test(PY_CONTENT),
    'BYOK solver should read CAPSOLVER_API_KEY from environment');
  assert(/os\.environ\.get\('TWOCAPTCHA_API_KEY'\)/.test(PY_CONTENT),
    'BYOK solver should read TWOCAPTCHA_API_KEY from environment');
  const byok = PY_CONTENT.match(/async def _solve_image_byok[\s\S]*?return \{'error': 'no_byok_key'\}/);
  assert(byok, '_solve_image_byok should exist');
  assert(/_captcha_urlopen_async/.test(byok[0]),
    'BYOK solver must use the stdlib urllib wrapper (no new HTTP dependency)');
  assert(!/\bimport requests\b/.test(byok[0]), 'BYOK solver must not import requests');
});

// ── PerimeterX / HUMAN "Press & Hold" solver ──

test('press-hold: _solve_press_and_hold defined + cmd_press_hold dispatched', () => {
  assert(/async def _solve_press_and_hold\(ws_url, target_sel=None\)/.test(PY_CONTENT),
    'Should define async _solve_press_and_hold(ws_url, target_sel=None)');
  assert(/async def cmd_press_hold\(selector=None\)/.test(PY_CONTENT),
    'Should define async cmd_press_hold(selector=None)');
  assert(/'press-hold':\s*lambda:\s*cmd_press_hold/.test(PY_CONTENT),
    "Should register 'press-hold' in async_map dispatch");
});

test('press-hold: uses Input.dispatchMouseEvent mousePressed->mouseMoved(jitter)->mouseReleased sequence', () => {
  const m = PY_CONTENT.match(/async def _press_hold_gesture\(ws_url, x, y, hold_ms\)[\s\S]*?return jitters/);
  assert(m, '_press_hold_gesture should exist');
  const body = m[0];
  const iPress = body.indexOf('"type": "mousePressed"');
  const iMove = body.indexOf('"type": "mouseMoved"');
  const iRelease = body.indexOf('"type": "mouseReleased"');
  assert(iPress >= 0, 'gesture must dispatch mousePressed');
  assert(iMove >= 0, 'gesture must dispatch mouseMoved (the hold tremor)');
  assert(iRelease >= 0, 'gesture must dispatch mouseReleased');
  assert(iPress < iMove && iMove < iRelease,
    'order must be mousePressed -> mouseMoved -> mouseReleased');
  assert(/Input\.dispatchMouseEvent/.test(body),
    'must use CDP Input.dispatchMouseEvent (zero new deps)');
});

test('press-hold: hold duration is gaussian-randomized (not fixed)', () => {
  const m = PY_CONTENT.match(/def _press_hold_duration_ms\(\)[\s\S]*?return [^\n]+/);
  assert(m, '_press_hold_duration_ms should exist');
  assert(/_gauss\(4000,\s*\d+,\s*3000,\s*7000\)/.test(m[0]),
    'hold duration must be _gauss(mu=4000, sigma, lo=3000, hi=7000) — randomized + clamped');
  assert(/hold_ms = _press_hold_duration_ms\(\)/.test(PY_CONTENT),
    '_solve_press_and_hold must draw a fresh randomized hold per attempt');
});

test('press-hold: micro-jitter during hold (1-2px mouseMoved with button held)', () => {
  const m = PY_CONTENT.match(/async def _press_hold_gesture\(ws_url, x, y, hold_ms\)[\s\S]*?return jitters/);
  assert(m, '_press_hold_gesture should exist');
  const body = m[0];
  assert(/r\.randint\(-2, 2\)/.test(body),
    'jitter must be +/-2px (randint(-2, 2)) around the press point');
  const moveBlock = body.slice(body.indexOf('"type": "mouseMoved"'));
  assert(/"button":\s*"left"/.test(moveBlock) && /"buttons":\s*1/.test(moveBlock),
    'hold-phase mouseMoved must keep the left button held (button:left, buttons:1)');
  const pressBlock = body.slice(body.indexOf('"type": "mousePressed"'),
                               body.indexOf('"type": "mouseMoved"'));
  assert(/"buttons":\s*1/.test(pressBlock), 'mousePressed must set buttons:1 (held)');
  const relBlock = body.slice(body.indexOf('"type": "mouseReleased"'));
  assert(/"buttons":\s*0/.test(relBlock), 'mouseReleased must clear buttons (buttons:0)');
});

test('press-hold: reuses existing humanizer (no reimplemented mouse path) + jitter cadence', () => {
  const m = PY_CONTENT.match(/async def _press_hold_gesture\(ws_url, x, y, hold_ms\)[\s\S]*?return jitters/);
  assert(m, '_press_hold_gesture should exist');
  const body = m[0];
  assert(/await _humanize_mouse_move\(ws_url, x, y\)/.test(body),
    'must reuse the existing _humanize_mouse_move Bezier path (not reimplement)');
  assert(/r\.uniform\(0\.10, 0\.20\)/.test(body),
    'micro-jitter cadence must be ~100-200ms (uniform(0.10, 0.20))');
});

test('press-hold: cmd_captcha_solve routes perimeterx -> press_and_hold', () => {
  const m = PY_CONTENT.match(/async def cmd_captcha_solve\(provider=None\)[\s\S]*?amz = await _detect_amazon_captcha/);
  assert(m, 'cmd_captcha_solve prologue should exist');
  const head = m[0];
  assert(/'perimeterx' in \(pre\.get\('types'\) or \[\]\)/.test(head),
    'cmd_captcha_solve must check for a perimeterx type');
  assert(/await _solve_press_and_hold\(ws\)/.test(head),
    'cmd_captcha_solve must route perimeterx to _solve_press_and_hold');
  const iRoute = head.indexOf('_solve_press_and_hold');
  const iAmz = head.indexOf('_detect_amazon_captcha');
  assert(iRoute >= 0 && iRoute < iAmz,
    'perimeterx routing must run before the Amazon/BYOK provider path');
});

test('press-hold: target finder (px hooks + TR/EN text) + retry + result schema', () => {
  const js = extractRawTripleString(PY_CONTENT, 'PRESS_HOLD_FIND_JS');
  assert(js, 'PRESS_HOLD_FIND_JS should be extractable');
  assert(js.includes('#px-captcha') && js.includes('px-captcha'),
    'finder must look for #px-captcha / [class*="px-captcha"]');
  assert(/press and hold|press & hold/.test(js) && /bas[ıi]l[ıi] tut/.test(js),
    'finder must match press-and-hold text in English + Turkish');
  const solver = PY_CONTENT.match(/async def _solve_press_and_hold[\s\S]*?"error": "still_present_after_retry"\}/);
  assert(solver, '_solve_press_and_hold should exist with retry');
  assert(/max_attempts = 2/.test(solver[0]), 'solver must allow a 2nd attempt on failure');
  assert(/"method": "press_and_hold"/.test(solver[0]), 'result must report method press_and_hold');
  assert(/"hold_ms"/.test(solver[0]) && /"attempts"/.test(solver[0]),
    'result must include hold_ms and attempts');
  assert(/info = await _detect_captcha\(ws_url\)/.test(solver[0]),
    'solver must verify with _detect_captcha after the gesture');
});

test('MCP: browser_press_hold tool + handler registered', () => {
  assert(/\{"name":\s*"browser_press_hold"/.test(PY_CONTENT),
    'browser_press_hold MCP tool should be declared');
  assert(/"browser_press_hold":\s*lambda a:\s*\["press-hold"\]/.test(PY_CONTENT),
    'browser_press_hold MCP handler should map to the press-hold CLI command');
});

// ── profile warm (reCAPTCHA v3 score aging) ──

test('profile warm: cmd_profile_warm defined', () => {
  assert(/async def cmd_profile_warm\(minutes=None, sites=None\)/.test(PY_CONTENT),
    'Should define async cmd_profile_warm(minutes=None, sites=None)');
  assert(/'profile':\s*lambda:\s*cmd_profile_dispatch\(args\)/.test(PY_CONTENT),
    "Should register top-level 'profile' command routing to cmd_profile_dispatch");
  assert(/if sub == 'warm':/.test(PY_CONTENT),
    "cmd_profile_dispatch should handle the 'warm' subcommand");
});

test('profile warm: visits safe site list + aging delays', () => {
  const m = PY_CONTENT.match(/WARM_SAFE_SITES\s*=\s*\[([\s\S]*?)\]/);
  assert(m, 'WARM_SAFE_SITES list should be defined');
  assert(/wikipedia/.test(m[1]), 'Safe list should include wikipedia');
  assert(/github\.com/.test(m[1]), 'Safe list should include github');
  assert(/stackoverflow\.com/.test(m[1]), 'Safe list should include stackoverflow');
  const fn = PY_CONTENT.match(/async def cmd_profile_warm[\s\S]*?budget_minutes/);
  assert(fn, 'cmd_profile_warm body should be extractable');
  assert(/_humanize_scroll/.test(fn[0]), 'Should reuse _humanize_scroll for engagement');
  assert(/navigate_collect/.test(fn[0]), 'Should visit sites via navigate_collect (open session)');
  assert(/asyncio\.sleep\(/.test(fn[0]), 'Should apply randomized aging delays between visits');
  assert(/Warming profile: visited/.test(fn[0]), 'Should report progress to stderr');
});

test('MCP: browser_captcha_solve tool registered', () => {
  assert(/"name":\s*"browser_captcha_solve"/.test(PY_CONTENT),
    'browser_captcha_solve should be registered in _register_tools()');
  assert(/"browser_captcha_solve":\s*lambda a:\s*\["captcha-solve"\]/.test(PY_CONTENT),
    'browser_captcha_solve should map to the captcha-solve CLI command in tool_map');
});

// ── Progressive-resilience escalation ladder (friction) ──

test('friction: FRICTION_DETECT_JS constant defined + valid JS', () => {
  assert(PY_CONTENT.includes('FRICTION_DETECT_JS = r"""'), 'Should define FRICTION_DETECT_JS');
  const js = extractRawTripleString(PY_CONTENT, 'FRICTION_DETECT_JS');
  assert(js, 'FRICTION_DETECT_JS body should be extractable');
  const vm = require('vm');
  assert.doesNotThrow(() => new vm.Script(js), 'FRICTION_DETECT_JS should parse as valid JS');
});

test('friction: FRICTION_DETECT_JS is read-only (no mutation/network/storage)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'FRICTION_DETECT_JS');
  assert(!/\.innerHTML\s*=/.test(js), 'Must not write innerHTML');
  assert(!/\.appendChild\(/.test(js), 'Must not append DOM nodes');
  assert(!/fetch\(|XMLHttpRequest|navigator\.sendBeacon/.test(js), 'Must not make network calls');
  assert(!/localStorage|sessionStorage|document\.cookie/.test(js), 'Must not touch storage/cookies');
});

test('friction: _detect_friction defined + cmd_friction dispatched', () => {
  assert(/async def _detect_friction\(ws_url\)/.test(PY_CONTENT),
    'Should define async _detect_friction(ws_url)');
  assert(/async def cmd_friction\(\)/.test(PY_CONTENT),
    'Should define async cmd_friction()');
  assert(/'friction':\s*cmd_friction/.test(PY_CONTENT),
    "Should register 'friction' in async_map dispatch");
});

test('friction: 6-level ladder ordered low->high', () => {
  const m = PY_CONTENT.match(/FRICTION_LEVELS\s*=\s*\(([\s\S]*?)\)/);
  assert(m, 'FRICTION_LEVELS tuple should exist');
  const body = m[1];
  ['none', 'rate_limited', 'soft_captcha', 'login_wall', 'otp_sms', 'hard_block'].forEach((lvl) => {
    assert(body.includes(`'${lvl}'`), `FRICTION_LEVELS should include ${lvl}`);
  });
  // Ordering: none before hard_block in the source tuple.
  assert(body.indexOf("'none'") < body.indexOf("'rate_limited'"), 'none before rate_limited');
  assert(body.indexOf("'rate_limited'") < body.indexOf("'hard_block'"), 'rate_limited before hard_block');
});

test('friction: rate_limited keyword detection (TR + EN)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'FRICTION_DETECT_JS');
  assert(js.includes('too many requests'), 'Should detect EN rate-limit phrase');
  assert(js.includes('çok fazla istek'), 'Should detect TR rate-limit phrase');
  assert(/rate_limited/.test(js), "Should classify as 'rate_limited'");
  assert(/\\b429\\b/.test(js) || js.includes('429'), 'Should consider HTTP 429 marker');
});

test('friction: login_wall detection (login form + gate keyword)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'FRICTION_DETECT_JS');
  assert(js.includes('giriş yap'), 'Should detect TR login phrase');
  assert(js.includes('sign in') || js.includes('log in'), 'Should detect EN login phrase');
  assert(/input\[type="password"\]/.test(js), 'Should look for a password input');
  assert(/login_wall/.test(js), "Should classify as 'login_wall'");
});

test('friction: otp_sms detection (verification code input/keyword)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'FRICTION_DETECT_JS');
  assert(js.includes('doğrulama kodu'), 'Should detect TR OTP phrase');
  assert(js.includes('verification code'), 'Should detect EN OTP phrase');
  assert(/one-time-code/.test(js), 'Should look for one-time-code autocomplete input');
  assert(/otp_sms/.test(js), "Should classify as 'otp_sms'");
});

test('friction: hard_block detection (403/access denied)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'FRICTION_DETECT_JS');
  assert(js.includes('access denied'), 'Should detect EN block phrase');
  assert(js.includes('erişim engellendi'), 'Should detect TR block phrase');
  assert(js.includes('403') || js.includes('forbidden'), 'Should detect 403/forbidden');
  assert(/hard_block/.test(js), "Should classify as 'hard_block'");
});

test('friction: _friction_action returns backoff for rate_limited', () => {
  const m = PY_CONTENT.match(/def _friction_action\(level\):[\s\S]*?return \{'action': 'proceed'/);
  assert(m, '_friction_action body should be extractable');
  const body = m[0];
  assert(/level == 'rate_limited'[\s\S]*?'action': 'backoff'/.test(body),
    'rate_limited should map to backoff action');
  assert(/'autonomous': True/.test(body), 'backoff should be autonomous');
});

test('friction: login/otp/hard map to human handoff (NO autonomous bypass)', () => {
  const m = PY_CONTENT.match(/def _friction_action\(level\):[\s\S]*?return \{'action': 'proceed'/);
  assert(m, '_friction_action body should be extractable');
  const body = m[0];
  assert(/'action': 'human_login_required'[\s\S]*?'autonomous': False/.test(body),
    'login_wall must be human_login_required + autonomous False');
  assert(/'action': 'human_otp_required'[\s\S]*?'autonomous': False/.test(body),
    'otp_sms must be human_otp_required + autonomous False');
  assert(/'action': 'hard_blocked'[\s\S]*?'autonomous': False/.test(body),
    'hard_block must be hard_blocked + autonomous False');
  // Ethics guard: no auto-fill of password/OTP anywhere in friction handling.
  assert(!/human_login_required[\s\S]{0,200}smart-fill/.test(PY_CONTENT),
    'login handoff must not auto-fill credentials');
});

test('friction: cmd_go integrates friction probe with bounded backoff', () => {
  const m = PY_CONTENT.match(/async def cmd_go\(url\):[\s\S]*?Post-navigation CAPTCHA probe/);
  assert(m, 'cmd_go body up to captcha probe should be extractable');
  const body = m[0];
  assert(/_detect_friction\(active_ws\)/.test(body), 'cmd_go should call _detect_friction');
  assert(/_friction_max_retry\(\)/.test(body), 'cmd_go backoff loop should be bounded by _friction_max_retry');
  assert(/asyncio\.sleep\(wait_s\)/.test(body), 'cmd_go should sleep for the backoff window');
  assert(/_friction_action\(fr_level\)/.test(body), 'cmd_go should resolve a friction action for handoff rungs');
});

test('friction: env knobs honored (CDPILOT_FRICTION_BACKOFF / MAX_RETRY)', () => {
  assert(/CDPILOT_FRICTION_BACKOFF/.test(PY_CONTENT), 'Should read CDPILOT_FRICTION_BACKOFF');
  assert(/CDPILOT_FRICTION_MAX_RETRY/.test(PY_CONTENT), 'Should read CDPILOT_FRICTION_MAX_RETRY');
  // Backoff is capped at 60s.
  assert(/min\(2 \*\* \(attempt \+ 1\), 60\)/.test(PY_CONTENT), 'Backoff should cap at 60s');
});

test('friction: in NO_CONTROL_CMDS (no glow interference)', () => {
  const m = PY_CONTENT.match(/NO_CONTROL_CMDS\s*=\s*\{([\s\S]*?)\}/);
  assert(m, 'NO_CONTROL_CMDS should exist');
  assert(m[1].includes("'friction'"), 'friction should bypass control wrapper');
});

test('MCP: browser_friction tool registered + mapped', () => {
  assert(/"name":\s*"browser_friction"/.test(PY_CONTENT),
    'browser_friction should be registered in _register_tools()');
  assert(/"browser_friction":\s*lambda a:\s*\["friction"\]/.test(PY_CONTENT),
    'browser_friction should map to the friction CLI command in tool_map');
});

test('navigate_collect gates stealth injection behind the active tier', () => {
  // The fingerprint script must be registered on the SAME WS as Page.navigate
  // so the session-bound script survives until loadEventFired. With the
  // three-tier model the gate selects via stealth_js_for_tier(get_mode_config())
  // and only injects when a (non-regular) source is returned.
  const m = PY_CONTENT.match(/async def navigate_collect[\s\S]*?stealth_source = stealth_js_for_tier\(get_mode_config\(\)\)[\s\S]*?if stealth_source:[\s\S]*?addScriptToEvaluateOnNewDocument[\s\S]*?stealth_source/);
  assert(m, 'navigate_collect should select the tier source via stealth_js_for_tier(get_mode_config()) and conditionally register it via addScriptToEvaluateOnNewDocument');
});

test('navigate_collect registers stealth BEFORE Page.navigate', () => {
  // Order matters: stealth must be registered before the navigate command,
  // otherwise the page may execute its detection script before our patch.
  const body = PY_CONTENT.match(/async def navigate_collect[\s\S]*?return content, events/)[0];
  const stealthIdx = body.search(/Page\.addScriptToEvaluateOnNewDocument/);
  const navigateIdx = body.search(/"Page\.navigate"/);
  assert(stealthIdx > 0, 'addScriptToEvaluateOnNewDocument should appear in navigate_collect');
  assert(navigateIdx > 0, 'Page.navigate should appear in navigate_collect');
  assert(stealthIdx < navigateIdx, 'Stealth script must be registered before Page.navigate');
});

test('cmd_go runs CAPTCHA detection after navigate (non-blocking)', () => {
  const m = PY_CONTENT.match(/async def cmd_go[\s\S]*?_detect_captcha[\s\S]*?CAPTCHA tespit edildi/);
  assert(m, 'cmd_go should probe CAPTCHA after navigate_collect and warn on stderr');
});

test('help output includes STEALTH & CAPTCHA section', () => {
  const out = run('--help');
  assert(out.includes('STEALTH'), 'Help should advertise stealth');
  assert(out.includes('captcha-check'), 'Help should advertise captcha-check');
  assert(out.includes('captcha-wait'), 'Help should advertise captcha-wait');
});

test('wait-for-text command is defined as async function', () => {
  assert(/async def cmd_wait_for_text\(text,\s*timeout_ms=5000\):/.test(PY_CONTENT),
    "Should define async def cmd_wait_for_text(text, timeout_ms=5000)");
});

test('wait-for-text uses MutationObserver with characterData=true', () => {
  // characterData mutations are essential for streaming text (AI responses,
  // typewriter effects) — without it the observer misses text node updates.
  const m = PY_CONTENT.match(/async def cmd_wait_for_text[\s\S]*?characterData:\s*true/);
  assert(m, "cmd_wait_for_text should observe characterData mutations");
});

test('wait-for-text is registered in async dispatch', () => {
  assert(/'wait-for-text':\s*lambda:\s*\(require_args\(1,\s*'wait-for-text\s+<text>/.test(PY_CONTENT),
    "Should register 'wait-for-text' in async_map");
});

test('browser_wait_for_text MCP tool exposed in tools/list and tool_map', () => {
  assert(PY_CONTENT.includes('"browser_wait_for_text"'),
    "browser_wait_for_text should appear as MCP tool name");
  assert(/"browser_wait_for_text":\s*lambda\s+a:\s*\["wait-for-text"/.test(PY_CONTENT),
    "browser_wait_for_text should map to wait-for-text CLI command");
});

// ── Perf: cdp_get cache, eval-batch, block-resources ──

test('cdp_get has TTL cache for /json and /json/version', () => {
  assert(/_CDP_GET_CACHE\b/.test(PY_CONTENT),
    "Should declare _CDP_GET_CACHE structure");
  assert(/_CDP_GET_CACHEABLE\s*=\s*\(\s*"\/json"\s*,\s*"\/json\/version"\s*\)/.test(PY_CONTENT),
    "Should declare which paths are cacheable");
  // Honor an explicit bypass so callers that need fresh state can opt out.
  assert(/def cdp_get\(path,\s*no_cache=False\)/.test(PY_CONTENT),
    "cdp_get should accept no_cache bypass parameter");
});

test('cdp_cache_invalidate is called after tab-mutating ops', () => {
  // /json reflects tab set + URLs; mutations must drop the cache so the next
  // read isn't stale. We invalidate on new-tab, close-tab, and session window
  // creation — the three places we know the tab set changed.
  assert(/def cdp_cache_invalidate\(\)/.test(PY_CONTENT),
    "Should define cdp_cache_invalidate()");
  const newTab = PY_CONTENT.match(/async def cmd_new_tab[\s\S]*?cdp_cache_invalidate\(\)/);
  assert(newTab, "cmd_new_tab should invalidate cache after creating a tab");
  const closeTab = PY_CONTENT.match(/async def cmd_close_tab[\s\S]*?cdp_cache_invalidate\(\)/);
  assert(closeTab, "cmd_close_tab should invalidate cache after closing a tab");
});

test('eval-batch command is defined and runs all expressions in one Promise.all', () => {
  assert(/async def cmd_eval_batch\(exprs_json\):/.test(PY_CONTENT),
    "Should define async def cmd_eval_batch(exprs_json)");
  // The whole point: one Runtime.evaluate, N expressions inside. Promise.all
  // is the cheap way to keep return order stable + parallel-friendly.
  const m = PY_CONTENT.match(/async def cmd_eval_batch[\s\S]*?Promise\.all\(\[/);
  assert(m, "cmd_eval_batch should wrap all expressions in Promise.all([...])");
  // Each expression must be wrapped in its own try/catch so one failure
  // doesn't sink the entire batch.
  const m2 = PY_CONTENT.match(/async def cmd_eval_batch[\s\S]*?try\{[\s\S]*?catch\(err\)/);
  assert(m2, "cmd_eval_batch should wrap each expression in try/catch");
});

test('eval-batch is registered in dispatch', () => {
  assert(/"eval-batch":\s*lambda:[\s\S]*?cmd_eval_batch\(args\[0\]\)/.test(PY_CONTENT),
    "Should register 'eval-batch' in dispatch");
});

test('browser_eval_batch MCP tool exposed in tools/list and tool_map', () => {
  assert(PY_CONTENT.includes('"browser_eval_batch"'),
    "browser_eval_batch should appear as MCP tool name");
  assert(/"browser_eval_batch":\s*lambda\s+a:\s*\["eval-batch"/.test(PY_CONTENT),
    "browser_eval_batch should map to eval-batch CLI command");
});

test('block-resources: config + presets + cmd_block defined', () => {
  assert(/BLOCK_CONFIG_FILE\s*=/.test(PY_CONTENT),
    "Should declare BLOCK_CONFIG_FILE path");
  assert(/BLOCK_PRESETS\s*=\s*\{[\s\S]*?'images'[\s\S]*?'fonts'[\s\S]*?'ads'/.test(PY_CONTENT),
    "BLOCK_PRESETS should expose images/fonts/ads preset groups");
  assert(/def get_block_config\(\)/.test(PY_CONTENT),
    "Should define get_block_config()");
  assert(/def cmd_block\(\*args\):/.test(PY_CONTENT),
    "Should define cmd_block accepting variadic args");
});

test('navigate_collect applies Network.setBlockedURLs when block is enabled', () => {
  // Block must be wired into the SAME WS that runs Page.navigate, otherwise
  // the patterns don't apply to the very first request. We also need it
  // gated behind get_block_config() so disabled-by-default is honored.
  const m = PY_CONTENT.match(/async def navigate_collect[\s\S]*?get_block_config\(\)[\s\S]*?Network\.setBlockedURLs/);
  assert(m, "navigate_collect should send Network.setBlockedURLs when get_block_config().enabled");
});

test('block command is registered in dispatch', () => {
  assert(/'block':\s*lambda:\s*cmd_block\(\*args\)/.test(PY_CONTENT),
    "Should register 'block' in dispatch with variadic args");
});

test('help output advertises eval-batch and block', () => {
  const out = run('--help');
  assert(out.includes('eval-batch'), "Help should advertise eval-batch");
  assert(out.includes('block'), "Help should advertise block");
  assert(out.includes('PERFORMANCE'), "Help should have a PERFORMANCE section");
});

// ── WebSocket connection pool ──

test('cdp_send signature is unchanged (callers depend on it)', () => {
  // Every existing caller passes (ws_url, commands) with optional timeout=15.
  // If this signature changes the entire codebase needs touching — fail loud.
  assert(/async def cdp_send\(ws_url,\s*commands,\s*timeout=15\):/.test(PY_CONTENT),
    "cdp_send must keep exact signature: async def cdp_send(ws_url, commands, timeout=15)");
});

test('WS pool: structures and atexit cleanup are declared', () => {
  assert(/^_WS_POOL\s*=\s*\{\}/m.test(PY_CONTENT),
    "Should declare _WS_POOL dict at module scope");
  assert(/^_WS_LOCKS\s*=\s*\{\}/m.test(PY_CONTENT),
    "Should declare _WS_LOCKS dict at module scope");
  assert(/_WS_POOL_ENABLED\s*=\s*os\.environ\.get\("CDPILOT_WS_POOL",\s*"1"\)\s*!=\s*"0"/.test(PY_CONTENT),
    "Pool must be env-gated via CDPILOT_WS_POOL (default ON)");
  assert(/atexit\.register\(_ws_pool_close_all\)/.test(PY_CONTENT),
    "Pool must register an atexit cleanup so exiting processes close connections");
});

test('WS pool: helpers exist with correct contracts', () => {
  assert(/def _ws_lock\(ws_url\):/.test(PY_CONTENT),
    "Should define _ws_lock(ws_url) factory");
  assert(/def _ws_is_open\(ws\):/.test(PY_CONTENT),
    "Should define _ws_is_open(ws) liveness check");
  assert(/async def _ws_drain\(ws,\s*max_drain=64\):/.test(PY_CONTENT),
    "Should define async _ws_drain(ws, max_drain=64)");
  // Drain must use a near-zero timeout, otherwise it slows every reused call.
  // Match _ws_drain body through to the first wait_for — docstring may exceed
  // the previous 400-char window, allow up to 1500.
  assert(/async def _ws_drain[\s\S]{0,1500}?asyncio\.wait_for\(ws\.recv\(\),\s*timeout=0\.001\)/.test(PY_CONTENT),
    "_ws_drain must use ~1ms timeout, never block on empty buffer");
});

test('WS pool: non-pooled path stays identical when CDPILOT_WS_POOL=0', () => {
  // Regression guard: turning the pool off must restore exact prior behavior
  // for users who hit edge cases. The opt-out branch must use the original
  // `async with websockets.connect(...)` open-use-close pattern.
  const m = PY_CONTENT.match(/if not _WS_POOL_ENABLED:[\s\S]*?async with websockets\.connect/);
  assert(m, "Non-pooled path must use `async with websockets.connect(...)` (the original pattern)");
});

test('WS pool: stale-conn retry only fires on reused conn with zero results', () => {
  // Invariant: retrying after partial progress would re-fire non-idempotent
  // commands (mouse events, form submits). Retry must be gated on both
  // `not results` AND `reused`.
  const m = PY_CONTENT.match(/async def cdp_send[\s\S]*?if not results and reused:/);
  assert(m, "Retry guard must be `if not results and reused:` — never retry after partial success");
});

test('WS pool: per-URL lock prevents command interleaving', () => {
  // Two cdp_send calls to the same target tab must serialise so their command
  // frames don't interleave on the wire (CDP responses are id-routed, but the
  // browser still expects frames to belong to coherent transactions).
  assert(/async with _ws_lock\(ws_url\):/.test(PY_CONTENT),
    "Pooled path must acquire _ws_lock(ws_url) before touching the connection");
});

// ── Efficient mode: scroll, post-load, visual, fast ──

test('scrollIntoView uses instant (not smooth) everywhere', () => {
  // Smooth scroll animates ~300-500ms before the click can fire. In automation
  // it never adds value and adds time. The previous behavior was a regression
  // we inherited from earlier "make it feel alive" code.
  assert(!/behavior:\s*'smooth'/.test(PY_CONTENT),
    "No JS in cdpilot.py should use scrollIntoView with behavior:'smooth'");
  // And we DO want instant on at least one of the action sites:
  assert(/behavior:\s*'instant'/.test(PY_CONTENT),
    "At least one action should use scrollIntoView({behavior:'instant'}) — verifies the replacement actually landed");
});

test('navigate_collect post-load sleep cut from 1.5s to 0.3s', () => {
  // The 1.5s blind wait after Page.loadEventFired was the single biggest
  // contributor to the "amateur typing" feel. 0.3s is enough buffer for late
  // JS without blocking on every navigation.
  const m = PY_CONTENT.match(/async def navigate_collect[\s\S]*?Page\.loadEventFired[\s\S]*?asyncio\.sleep\(0\.3\)/);
  assert(m, "navigate_collect should sleep 0.3s after loadEventFired (was 1.5s)");
  // Negative assert: the old 1.5s must NOT come back here.
  const neg = PY_CONTENT.match(/async def navigate_collect[\s\S]*?asyncio\.sleep\(1\.5\)/);
  assert(!neg, "navigate_collect must not regress to the 1.5s sleep");
});

test('visual feedback config: default OFF', () => {
  // The whole "professional feel" change. Default OFF means new users don't
  // see the glow/cursor unless they opt in via `cdpilot show on` or env.
  assert(/def get_visual_config\(\)/.test(PY_CONTENT),
    "Should define get_visual_config()");
  // Default-false branch is explicit at the bottom of get_visual_config.
  const m = PY_CONTENT.match(/def get_visual_config[\s\S]*?return False\s*$/m);
  assert(m, "get_visual_config() must end with `return False` — default OFF");
  // Backward compat: CDPILOT_MCP_SESSION=1 still forces ON (MCP persistent glow).
  assert(/CDPILOT_MCP_SESSION[\s\S]{0,200}?return True/.test(PY_CONTENT),
    "CDPILOT_MCP_SESSION=1 must short-circuit to True (backward compat)");
});

test('_control_start and _control_end gate on visual config', () => {
  // _control_start/_control_end re-inject glow on every command boundary —
  // they bypass navigate_collect's gate. Both must respect the visual config
  // or `cdpilot show off` silently fails to remove the glow.
  const start = PY_CONTENT.match(/async def _control_start[\s\S]{0,800}?if not get_visual_config\(\):\s*\n\s*return/);
  assert(start, "_control_start must early-return when get_visual_config() is False");
  const end = PY_CONTENT.match(/async def _control_end[\s\S]{0,800}?if not get_visual_config\(\):\s*\n\s*return/);
  assert(end, "_control_end must early-return when get_visual_config() is False");
});

test('fast mode config: get_auto_wait_ms honors env override and clamps', () => {
  // get_auto_wait_ms is the single source of truth for auto-wait timing.
  // CDPILOT_WAIT_MS must win over fast mode so power users can dial it
  // independently of the bundle switch. The returned value must be clamped
  // to a sane range so an env of "0" (instant timeout, breaks every click)
  // or "9999999999" (>10 days, breaks asyncio) can't propagate.
  assert(/def get_auto_wait_ms\(\)/.test(PY_CONTENT),
    "Should define get_auto_wait_ms()");
  const envCheck = PY_CONTENT.match(/def get_auto_wait_ms[\s\S]*?CDPILOT_WAIT_MS[\s\S]*?int\(env\)/);
  assert(envCheck, "get_auto_wait_ms must check CDPILOT_WAIT_MS env first and use int(env)");
  const clamp = PY_CONTENT.match(/def get_auto_wait_ms[\s\S]*?max\(\s*\d+\s*,\s*min\(int\(env\)\s*,\s*\d/);
  assert(clamp, "get_auto_wait_ms must clamp env value via max(floor, min(int(env), ceiling))");
});

test('cmd_click and cmd_fill use get_auto_wait_ms (no hardcoded 5000)', () => {
  // Originally cmd_click hardcoded `5000` as the wait timeout. Switching to
  // get_auto_wait_ms() means `cdpilot fast on` actually shortens the wait
  // (instead of just toggling a flag with no effect).
  const click = PY_CONTENT.match(/async def cmd_click[\s\S]*?wait_ms\s*=\s*get_auto_wait_ms\(\)[\s\S]*?__cdpilot_waitFor\([^)]*,\s*\{wait_ms\}/);
  assert(click, "cmd_click must compute wait_ms = get_auto_wait_ms() and use it in the JS template");
  const fill = PY_CONTENT.match(/async def cmd_fill[\s\S]*?wait_ms\s*=\s*get_auto_wait_ms\(\)[\s\S]*?__cdpilot_waitFor\([^)]*,\s*\{wait_ms\}/);
  assert(fill, "cmd_fill must compute wait_ms = get_auto_wait_ms() and use it in the JS template");
});

test('show and fast registered in dispatch', () => {
  assert(/'show':\s*lambda:\s*cmd_show\(/.test(PY_CONTENT),
    "Should register 'show' in dispatch");
  assert(/'fast':\s*lambda:\s*cmd_fast\(/.test(PY_CONTENT),
    "Should register 'fast' in dispatch");
});

test('help output advertises show and fast', () => {
  const out = run('--help');
  assert(out.includes('show'), "Help should advertise show");
  assert(out.includes('fast'), "Help should advertise fast");
});

// ── Auto-dismiss: pattern lib + safety guards ──

test('dismiss pattern lib: positives cover LLM chat escape hatches', () => {
  // Direct anonymous-use intent — these are the killer use cases.
  // Score asymmetry matters: "stay signed out" must beat generic "later".
  assert(PY_CONTENT.includes('"stay signed out", 100'),
    "DISMISS_POSITIVE should include 'stay signed out' at weight 100");
  assert(PY_CONTENT.includes('"continue without signing in", 100'),
    "DISMISS_POSITIVE should include 'continue without signing in' at weight 100");
  assert(PY_CONTENT.includes('"continue as guest", 95'),
    "DISMISS_POSITIVE should include 'continue as guest'");
  // Turkish coverage — cdpilot's primary audience.
  assert(PY_CONTENT.includes('"şimdi değil", 80'),
    "DISMISS_POSITIVE should include Turkish 'şimdi değil'");
  assert(PY_CONTENT.includes('"üye olmadan", 95'),
    "DISMISS_POSITIVE should include Turkish 'üye olmadan'");
});

test('dismiss pattern lib: negatives prevent destructive misfires', () => {
  // Anti-patterns are load-bearing — they're what makes auto-dismiss safe to
  // ship as a default-on style helper. If these regress, users lose accounts.
  assert(/DISMISS_NEGATIVE\s*=/.test(PY_CONTENT),
    "DISMISS_NEGATIVE list must be declared");
  assert(PY_CONTENT.includes('"delete account"'),
    "DISMISS_NEGATIVE must disqualify 'delete account'");
  assert(PY_CONTENT.includes('"sign out"'),
    "DISMISS_NEGATIVE must disqualify 'sign out'");
  assert(PY_CONTENT.includes('"subscribe"'),
    "DISMISS_NEGATIVE must disqualify 'subscribe'");
  // Turkish account-destruction patterns
  assert(PY_CONTENT.includes('"hesabı sil"') || PY_CONTENT.includes('"hesabımı sil"'),
    "DISMISS_NEGATIVE must disqualify Turkish account-deletion phrasing");
});

test('cmd_dismiss: one negative hit disqualifies regardless of positives', () => {
  // Critical invariant: an element matching ANY anti-pattern is out, period.
  // Without this an element labelled "no thanks, delete account" would still
  // get a positive score from "no thanks" and be clicked.
  // Note: the JS lives inside a Python f-string so `{{` in source → `{` after format.
  const m = PY_CONTENT.match(/checkText[\s\S]{0,800}?NEG\[i\][\s\S]{0,200}?return\s*\{+\s*pos:\s*0,\s*neg:\s*true/);
  assert(m, "checkText must early-return {pos:0, neg:true} as soon as any NEG pattern hits");
});

test('cmd_dismiss: visibility gate + min score threshold', () => {
  // No clicks on invisible elements (0×0 box, display:none, opacity:0). And
  // weak partial matches must NOT cross the dismiss threshold — that's the
  // line between "found the escape hatch" and "guessing".
  assert(/rect\.width === 0 && rect\.height === 0/.test(PY_CONTENT),
    "Dismiss must skip 0-size elements");
  assert(/style\.display === 'none' \|\| style\.visibility === 'hidden'/.test(PY_CONTENT),
    "Dismiss must skip display:none / visibility:hidden");
  assert(/MIN_SCORE\s*=\s*40/.test(PY_CONTENT),
    "Dismiss must enforce MIN_SCORE = 40 to avoid weak-match misfires");
});

test('dismiss registered in dispatch + MCP', () => {
  assert(/'dismiss':\s*lambda:\s*cmd_dismiss\(/.test(PY_CONTENT),
    "Should register 'dismiss' in dispatch");
  assert(PY_CONTENT.includes('"browser_dismiss"'),
    "Should expose browser_dismiss MCP tool");
  assert(/"browser_dismiss":\s*lambda\s+a:\s*\["dismiss"\]/.test(PY_CONTENT),
    "MCP tool_map must route browser_dismiss to the dismiss CLI command");
});

test('help advertises dismiss command', () => {
  const out = run('--help');
  assert(out.includes('dismiss'), "Help should advertise dismiss");
});

// ── Adaptive escalation (CAPTCHA → stealth memory) ──

test('adaptive config + hostname memory defined', () => {
  assert(/ADAPTIVE_CONFIG_FILE\s*=/.test(PY_CONTENT),
    "ADAPTIVE_CONFIG_FILE path must be declared alongside the other config files");
  assert(/def get_adaptive_config\(\)/.test(PY_CONTENT),
    "Should define get_adaptive_config()");
  assert(/stealth_hosts/.test(PY_CONTENT),
    "Adaptive must persist a stealth_hosts list");
});

test('cmd_go: adaptive auto-enables tier for known host before navigate', () => {
  // Invariant: when adaptive is ON and the URL's host has a learned tier (or is
  // in the legacy stealth_hosts list), cmd_go must set CDPILOT_MODE BEFORE
  // navigate_collect runs so the right fingerprint script is registered in time.
  // The Fix 1 isolation block sits between the CDPILOT_MODE set and
  // navigate_collect, so we verify the invariants separately.
  const hasTierStart = /async def cmd_go[\s\S]*?_adaptive_host_tier\(url\)[\s\S]{0,600}?CDPILOT_MODE/.test(PY_CONTENT);
  const hasLegacyStart = /async def cmd_go[\s\S]*?_adaptive_host_requires_stealth\(url\)[\s\S]{0,900}?CDPILOT_MODE/.test(PY_CONTENT);
  const hasNavCollect = /async def cmd_go[\s\S]*?navigate_collect\(active_ws,\s*url\)/.test(PY_CONTENT);
  assert(hasTierStart && hasLegacyStart && hasNavCollect,
    "cmd_go must check the learned tier (and legacy stealth_hosts) and set CDPILOT_MODE BEFORE navigate_collect");
});

test('cmd_go: CAPTCHA detection → remember host + retry once with stealth', () => {
  // The escalation loop: after navigate, if CAPTCHA is detected AND adaptive
  // mode is enabled, the host is added to the persistent list. If stealth
  // was OFF during this navigation, retry exactly once with stealth enabled.
  const m = PY_CONTENT.match(/info\.get\("detected"\)[\s\S]*?_adaptive_remember_host\(expected_host\)[\s\S]*?navigate_collect\(active_ws,\s*url\)/);
  assert(m, "cmd_go must call _adaptive_remember_host(expected_host) and re-navigate when CAPTCHA is detected with adaptive on");
});

test('adaptive never auto-demotes — once added, hostname stays until manual forget', () => {
  // Conservative design: a single false-negative CAPTCHA detection shouldn't
  // drop a host out of the list. Removal is manual via `adaptive forget`
  // or `adaptive clear`. The forget helper must be defined.
  assert(/def cmd_adaptive_forget\(hostname\):/.test(PY_CONTENT),
    "Should define cmd_adaptive_forget(hostname)");
  // No automatic removal path in cmd_go or _detect_captcha.
  const autoRemove = PY_CONTENT.match(/cfg\['stealth_hosts'\]\.remove/g) || [];
  assert(autoRemove.length === 1,
    "Only cmd_adaptive_forget should call stealth_hosts.remove — auto-demote is forbidden");
});

test('adaptive registered in dispatch with forget subcommand routing', () => {
  // The dispatch handles two shapes: `adaptive forget <host>` routes to
  // cmd_adaptive_forget(host); everything else routes to cmd_adaptive.
  assert(/'adaptive':[\s\S]{0,200}?cmd_adaptive_forget\(args\[1\]\)/.test(PY_CONTENT),
    "Dispatch must route 'adaptive forget <host>' to cmd_adaptive_forget(args[1])");
  assert(/'adaptive':[\s\S]{0,200}?cmd_adaptive\(args\[0\]/.test(PY_CONTENT),
    "Dispatch must route 'adaptive' / 'adaptive on/off' to cmd_adaptive");
});

test('help advertises adaptive command', () => {
  const out = run('--help');
  assert(out.includes('adaptive'), "Help should advertise adaptive");
});

// ── Cookies save/load (clearance pool foundation) ──

test('cmd_cookies accepts variadic args for save/load', () => {
  // The old signature was cmd_cookies(domain=None) — just listing. With
  // save/load subcommands the function must accept *args.
  assert(/async def cmd_cookies\(\*args\):/.test(PY_CONTENT),
    "cmd_cookies should accept *args to handle save/load subcommands");
});

test('cmd_cookies save: writes JSON array via Network.getCookies', () => {
  // The 'save' subcommand must fetch via Network.getCookies (NOT a hand-rolled
  // scan), apply optional domain filter, and write as a JSON array.
  const m = PY_CONTENT.match(/sub == 'save'[\s\S]{0,1200}?Network\.getCookies[\s\S]{0,800}?json\.dump\(cookies/);
  assert(m, "cookies save must use Network.getCookies and json.dump the result");
});

test('cmd_cookies load: round-trips via Network.setCookies and verifies count', () => {
  const m = PY_CONTENT.match(/sub == 'load'[\s\S]{0,1500}?Network\.setCookies[\s\S]{0,500}?Network\.getCookies/);
  assert(m, "cookies load must call Network.setCookies and verify via Network.getCookies");
});

test('cookies dispatch passes variadic args', () => {
  // Old dispatch was `cmd_cookies(args[0] if args else None)` — would only
  // forward one positional. Save/load need ≥2 args.
  assert(/"cookies":\s*lambda:\s*cmd_cookies\(\*args\)/.test(PY_CONTENT),
    "Dispatch must call cmd_cookies(*args) to forward subcommand + path");
});

test('help advertises cookies save/load', () => {
  const out = run('--help');
  assert(out.includes('cookies save'), "Help should advertise 'cookies save'");
  assert(out.includes('cookies load'), "Help should advertise 'cookies load'");
});

// ── Browser context pool ──

test('cmd_context_create uses CDP Target.createBrowserContext + createTarget', () => {
  // True isolation: a fresh BrowserContext gives you a clean cookie/storage
  // jar. Without createBrowserContext first, createTarget would land in the
  // default context (shared cookies) — that's a soft tab, not a real
  // isolated session.
  const m = PY_CONTENT.match(/async def cmd_context_create[\s\S]*?Target\.createBrowserContext[\s\S]*?Target\.createTarget/);
  assert(m, "cmd_context_create must call Target.createBrowserContext THEN Target.createTarget(browserContextId=...)");
});

test('cmd_context_create rolls back on createTarget failure', () => {
  // If createBrowserContext succeeded but createTarget failed, we'd leak an
  // empty context. The rollback path must call disposeBrowserContext BEFORE
  // sys.exit so we don't leave the orphan dangling.
  const m = PY_CONTENT.match(/async def cmd_context_create[\s\S]*?if not tgt_id:[\s\S]{0,600}?Target\.disposeBrowserContext[\s\S]{0,400}?sys\.exit\(1\)/);
  assert(m, "cmd_context_create must dispose the orphan context BEFORE sys.exit(1) when createTarget fails");
});

test('CDPILOT_TARGET env pin bypasses session lookup', () => {
  // For parallel workflows, each CLI invocation must be able to address a
  // specific tab without polluting CWD-keyed session state. The env pin must
  // be checked BEFORE _get_session_window_target_id.
  const m = PY_CONTENT.match(/def get_page_ws[\s\S]{0,1200}?CDPILOT_TARGET[\s\S]{0,500}?return\s+p\[.webSocketDebuggerUrl.\],\s*p/);
  assert(m, "get_page_ws must check CDPILOT_TARGET env first and short-circuit on match");
});

test('CDPILOT_TARGET pin fails loud when tab is gone', () => {
  // Silent fallback to a different tab on a missing pin would be a heisenbug
  // for parallel callers — they'd think they hit context A but actually
  // ran on context B.
  const m = PY_CONTENT.match(/CDPILOT_TARGET[\s\S]{0,500}?no such tab[\s\S]{0,200}?sys\.exit\(1\)/);
  assert(m, "Missing pinned target must print an error and sys.exit(1), not silently fall through");
});

test('cmd_context_close refuses to destroy the default context', () => {
  // disposeBrowserContext on the default context's "id" (which is empty/None
  // depending on how it's passed) would either no-op or break things. Refuse
  // to even try.
  const m = PY_CONTENT.match(/async def cmd_context_close[\s\S]{0,500}?context_id == 'default'[\s\S]{0,200}?sys\.exit\(1\)/);
  assert(m, "cmd_context_close must refuse 'default' context_id");
});

test('context registered in dispatch as variadic dispatcher', () => {
  // The dispatch entry must forward *args because the subcommand structure
  // is `context create|list|close [extra]` — single-arg lambda would lose
  // the URL / context_id parameter.
  assert(/'context':\s*lambda:\s*cmd_context\(\*args\)/.test(PY_CONTENT),
    "Dispatch must call cmd_context(*args) to forward subcommand + extra args");
});

test('help advertises context commands', () => {
  const out = run('--help');
  assert(out.includes('context'), "Help should advertise context");
  assert(out.includes('CDPILOT_TARGET'), "Help should explain how to target a context's tab");
});

// ── Selector Ladder + Heal Log Tests ──

test('_resolve_selector_ladder exists with correct default strategy order', () => {
  // The ladder must be defined in the source with all 7 strategies in order.
  const m = PY_CONTENT.match(/async def _resolve_selector_ladder\([\s\S]{0,300}?"css"[\s\S]{0,100}?"xpath"[\s\S]{0,100}?"role-name"[\s\S]{0,100}?"text-exact"[\s\S]{0,100}?"text-fuzzy"[\s\S]{0,100}?"stable-attr"[\s\S]{0,100}?"a11y-ref"/);
  assert(m, "_resolve_selector_ladder must define default strategies: css, xpath, role-name, text-exact, text-fuzzy, stable-attr, a11y-ref in that order");
});

test('text-exact strategy queries visible elements by innerText', () => {
  // text-exact must search offsetParent-visible elements comparing innerText.trim().
  const m = PY_CONTENT.match(/text-exact[\s\S]{0,300}?offsetParent[\s\S]{0,200}?innerText\.trim\(\)/);
  assert(m, "text-exact strategy must filter by offsetParent and match innerText.trim()");
});

test('css fast-path returns inp directly without token injection', () => {
  // CSS hit must return inp as selector immediately — no data-cdpilot-tmp needed.
  // Verify: after css hit, return inp, tried (no token used).
  const m = PY_CONTENT.match(/"css"[\s\S]{0,500}?return inp, tried/);
  assert(m, "css strategy must return inp directly (no tmp-attr injection) on hit");
});

test('_log_heal writes JSONL with required fields', () => {
  // heal.jsonl entry must contain ts, cmd, input, tried, duration_ms.
  const m = PY_CONTENT.match(/def _log_heal[\s\S]{0,400}?"ts"[\s\S]{0,100}?"cmd"[\s\S]{0,100}?"input"[\s\S]{0,100}?"tried"[\s\S]{0,100}?"duration_ms"/);
  assert(m, "_log_heal must write JSON with fields: ts, cmd, input, tried, duration_ms");
});

test('_log_heal writes to project-specific heal.jsonl path', () => {
  // Path must be under CDPILOT_HOME/projects/PROJECT_ID/heal.jsonl.
  const m = PY_CONTENT.match(/def _log_heal[\s\S]{0,300}?CDPILOT_HOME[\s\S]{0,100}?projects[\s\S]{0,100}?PROJECT_ID[\s\S]{0,100}?heal\.jsonl/);
  assert(m, "_log_heal must write to ~/.cdpilot/projects/<PROJECT_ID>/heal.jsonl");
});

test('_log_heal respects no_heal flag (skips write)', () => {
  // When no_heal=True, _log_heal must return immediately without writing.
  const m = PY_CONTENT.match(/def _log_heal[\s\S]{0,100}?no_heal[\s\S]{0,100}?if no_heal:\s*\n\s*return/);
  assert(m, "_log_heal must early-return when no_heal is True");
});

test('cmd_click skips heal log on immediate CSS hit', () => {
  // If CSS matches first (tried has 1 entry, hit=True), _log_heal must NOT be called.
  // Verified by: log condition checks len(tried) > 1 or tried[0] not hit.
  // v0.5.2: ws + host-aware entropy block added before tried check → wider scan window.
  const m = PY_CONTENT.match(/async def cmd_click[\s\S]{0,900}?len\(tried\) > 1 or \(tried and not tried\[0\]\["hit"\]\)/);
  assert(m, "cmd_click must only call _log_heal when fallback was used or CSS missed");
});

test('cmd_click delegates @N refs to cmd_click_ref unchanged', () => {
  // a11y-ref shortcut: @digit input must delegate to cmd_click_ref, bypassing ladder.
  const m = PY_CONTENT.match(/async def cmd_click[\s\S]{0,200}?selector\.startswith\("@"\) and selector\[1:\]\.isdigit\(\)[\s\S]{0,100}?cmd_click_ref/);
  assert(m, "cmd_click must bypass ladder and delegate to cmd_click_ref for @N inputs");
});

test('cmd_heal_log and cmd_heal_stats are registered in sync_cmds under heal', () => {
  // The heal command must dispatch to cmd_heal_log (default) or cmd_heal_stats.
  const m = PY_CONTENT.match(/'heal':\s*lambda[\s\S]{0,300}?cmd_heal_stats[\s\S]{0,100}?cmd_heal_log/);
  assert(m, "'heal' must be in sync_cmds dispatching to cmd_heal_log/cmd_heal_stats");
});

test('stable-attr strategy tries data-testid, data-cy, name, id', () => {
  // All four stable attributes must be in the strategy implementation.
  const m = PY_CONTENT.match(/stable-attr[\s\S]{0,400}?data-testid[\s\S]{0,200}?data-cy[\s\S]{0,200}?(?:name|id)[\s\S]{0,200}?(?:id|name)/);
  assert(m, "stable-attr must try data-testid, data-cy, name, id attributes");
});

test('--no-heal flag plumbed through click dispatch', () => {
  // The click dispatch lambda must pass no_heal kwarg.
  const m = PY_CONTENT.match(/"click":\s*lambda[\s\S]{0,400}?no_heal=/);
  assert(m, "click dispatch must pass no_heal= kwarg from --no-heal flag");
});

test('--ladder flag plumbed through click dispatch', () => {
  // The click dispatch lambda must extract --ladder= and pass to cmd_click.
  const m = PY_CONTENT.match(/"click":\s*lambda[\s\S]{0,400}?--ladder=/);
  assert(m, "click dispatch must extract --ladder= flag and pass to cmd_click");
});

// ── Behavioral Entropy ──

test('ENTROPY_CONFIG_FILE is declared alongside other config files', () => {
  assert(/ENTROPY_CONFIG_FILE\s*=\s*os\.path\.join\(PROFILE_DIR/.test(PY_CONTENT),
    "ENTROPY_CONFIG_FILE must be declared near ADAPTIVE_CONFIG_FILE");
});

test('_ENTROPY_SEED is read from CDPILOT_ENTROPY_SEED env at module scope', () => {
  assert(/_ENTROPY_SEED\s*=\s*os\.environ\.get\('CDPILOT_ENTROPY_SEED'\)/.test(PY_CONTENT),
    "Must declare _ENTROPY_SEED = os.environ.get('CDPILOT_ENTROPY_SEED') for test seeding");
});

test('get_entropy_config default is OFF', () => {
  const m = PY_CONTENT.match(/def get_entropy_config\(\):[\s\S]*?\n    return (False|True)\n/);
  assert(m, "get_entropy_config must have a clear default return");
  assert.strictEqual(m[1], 'False', "Default must be False (opt-in)");
});

test('get_entropy_config honors CDPILOT_ENTROPY env override', () => {
  const m = PY_CONTENT.match(/def get_entropy_config[\s\S]{0,500}?CDPILOT_ENTROPY[\s\S]{0,200}?return/);
  assert(m, "get_entropy_config must check CDPILOT_ENTROPY env first");
});

test('_gauss clamp logic is present', () => {
  assert(/def _gauss\(mu,\s*sigma,\s*lo,\s*hi\):/.test(PY_CONTENT),
    "Must define _gauss(mu, sigma, lo, hi)");
  assert(/max\(lo,\s*min\(hi,/.test(PY_CONTENT),
    "_gauss must use max(lo, min(hi, ...)) clamping");
});

test('_quartic_easeout is defined with correct formula', () => {
  assert(/def _quartic_easeout\(t\):/.test(PY_CONTENT),
    "Must define _quartic_easeout(t)");
  assert(/1\.0\s*-\s*\(1\.0\s*-\s*t\)\s*\*\*\s*4/.test(PY_CONTENT),
    "_quartic_easeout must use formula 1-(1-t)^4");
  // Verify boundary values via Python (inline pure function extract).
  // execFileSync (no shell): cmd.exe mangles multiline -c strings, and
  // Windows has `python`, not `python3`.
  const { execFileSync } = require('child_process');
  const PY_BIN = process.platform === 'win32' ? 'python' : 'python3';
  const out = execFileSync(PY_BIN, ['-c', `
def _quartic_easeout(t): return 1.0 - (1.0 - t) ** 4
print(_quartic_easeout(0), _quartic_easeout(1))
`], { encoding: 'utf-8', timeout: 5000 });
  const [v0, v1] = out.trim().split(' ').map(Number);
  assert(Math.abs(v0 - 0.0) < 0.001, "_quartic_easeout(0) must be 0.0");
  assert(Math.abs(v1 - 1.0) < 0.001, "_quartic_easeout(1) must be 1.0");
});

test('_bezier_path returns correct point count', () => {
  // Verify formula via inline Python (stdlib only, no cdpilot.py load needed)
  const { execFileSync } = require('child_process');
  const PY_BIN = process.platform === 'win32' ? 'python' : 'python3';
  const out = execFileSync(PY_BIN, ['-c', `
import random, os
os.environ['CDPILOT_ENTROPY_SEED'] = '42'
_ENTROPY_SEED = '42'
def _bezier_path(start_xy, end_xy, points=15):
    r = random.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else random.Random()
    x0, y0 = start_xy; x1, y1 = end_xy
    mx, my = (x0+x1)/2, (y0+y1)/2
    cx = mx + r.uniform(-60, 60); cy = my + r.uniform(-60, 60)
    result = []
    for i in range(points):
        t = i/(points-1) if points>1 else 0.0
        x = (1-t)**2*x0 + 2*(1-t)*t*cx + t**2*x1
        y = (1-t)**2*y0 + 2*(1-t)*t*cy + t**2*y1
        result.append((int(round(x)), int(round(y))))
    return result
pts = _bezier_path((0, 0), (100, 100), 10)
print(len(pts))
`], { encoding: 'utf-8', timeout: 5000 });
  assert.strictEqual(parseInt(out.trim()), 10, "_bezier_path must return exactly N points");
});

test('_gauss stays within [lo, hi] bounds (1000 samples)', () => {
  const { execFileSync } = require('child_process');
  const PY_BIN = process.platform === 'win32' ? 'python' : 'python3';
  const out = execFileSync(PY_BIN, ['-c', `
import random
_ENTROPY_SEED = '42'
def _gauss(mu, sigma, lo, hi):
    r = random.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else random
    return max(lo, min(hi, r.gauss(mu, sigma)))
failures = [v for i in range(1000) for v in [_gauss(85, 25, 40, 200)] if v < 40 or v > 200]
print(len(failures))
`], { encoding: 'utf-8', timeout: 5000 });
  assert.strictEqual(parseInt(out.trim()), 0, "_gauss must produce 0 out-of-range samples in 1000 trials");
});

test('cmd_entropy is defined as sync function', () => {
  assert(/^def cmd_entropy\(state=None\):/m.test(PY_CONTENT),
    "Must define def cmd_entropy(state=None) as sync (not async)");
});

test('cmd_entropy registered in sync dispatch', () => {
  assert(/'entropy':\s*lambda:\s*cmd_entropy\(/.test(PY_CONTENT),
    "Must register 'entropy' in sync_cmds dispatch");
});

test('cmd_entropy writes to ENTROPY_CONFIG_FILE via _atomic_write_json', () => {
  const m = PY_CONTENT.match(/def cmd_entropy[\s\S]{0,1500}?_atomic_write_json\(ENTROPY_CONFIG_FILE/);
  assert(m, "cmd_entropy must persist state via _atomic_write_json(ENTROPY_CONFIG_FILE, ...)");
});

test('--entropy flag plumbed through click dispatch', () => {
  const m = PY_CONTENT.match(/"click":\s*lambda[\s\S]{0,600}?--entropy=on/);
  assert(m, "click dispatch must accept --entropy=on flag");
});

test('--entropy flag plumbed through fill dispatch', () => {
  const m = PY_CONTENT.match(/"fill":\s*lambda[\s\S]{0,600}?--entropy=on/);
  assert(m, "fill dispatch must accept --entropy=on flag");
});

test('--entropy flag plumbed through hover dispatch', () => {
  const m = PY_CONTENT.match(/'hover':\s*lambda[\s\S]{0,600}?--entropy=on/);
  assert(m, "hover dispatch must accept --entropy=on flag");
});

test('cmd_click accepts entropy param', () => {
  assert(/async def cmd_click\(selector,\s*ladder=None,\s*no_heal=False,\s*entropy=None\):/.test(PY_CONTENT),
    "cmd_click must have entropy=None parameter");
});

test('cmd_fill accepts entropy param', () => {
  assert(/async def cmd_fill\(selector,\s*value,\s*ladder=None,\s*no_heal=False,\s*entropy=None\):/.test(PY_CONTENT),
    "cmd_fill must have entropy=None parameter");
});

test('cmd_hover accepts entropy param', () => {
  assert(/async def cmd_hover\(selector,\s*ladder=None,\s*no_heal=False,\s*entropy=None\):/.test(PY_CONTENT),
    "cmd_hover must have entropy=None parameter");
});

test('adaptive escalation auto-enables entropy on CAPTCHA detect (v0.5.2: per-host)', () => {
  // v0.5.2: global entropy.json write replaced by per-host _adaptive_remember_host_entropy.
  // The adaptive block must call _adaptive_remember_host_entropy after remembering the host.
  const m = PY_CONTENT.match(/_adaptive_remember_host\(expected_host\)[\s\S]{0,400}?_adaptive_remember_host_entropy\(expected_host/);
  assert(m, "cmd_go adaptive block must call _adaptive_remember_host_entropy(expected_host, ...) after _adaptive_remember_host");
});

test('_humanize_mouse_move dispatches mouseMoved events via CDP', () => {
  assert(/async def _humanize_mouse_move\(ws_url,\s*x,\s*y\):/.test(PY_CONTENT),
    "Must define _humanize_mouse_move");
  assert(/"mouseMoved"/.test(PY_CONTENT), "Must dispatch mouseMoved events");
});

test('_humanize_type dispatches keyDown/keyUp with dwell delay', () => {
  assert(/async def _humanize_type\(ws_url,\s*text\):/.test(PY_CONTENT),
    "Must define _humanize_type");
  const m = PY_CONTENT.match(/async def _humanize_type[\s\S]{0,600}?keyDown[\s\S]{0,500}?keyUp/);
  assert(m, "_humanize_type must send keyDown before keyUp for each character");
});

test('_humanize_scroll uses quartic easeout chunking', () => {
  assert(/async def _humanize_scroll\(ws_url,\s*delta_y/.test(PY_CONTENT),
    "Must define _humanize_scroll");
  const m = PY_CONTENT.match(/async def _humanize_scroll[\s\S]{0,800}?_quartic_easeout/);
  assert(m, "_humanize_scroll must use _quartic_easeout for easing");
});

// ── Agent Token-Budget Mode ──

test('AGENT_INTERACTIVE_ROLES defined with core interactive roles', () => {
  assert(/AGENT_INTERACTIVE_ROLES\s*=\s*\{/.test(PY_CONTENT),
    "AGENT_INTERACTIVE_ROLES must be defined");
  assert(/'button'/.test(PY_CONTENT) && /'link'/.test(PY_CONTENT),
    "AGENT_INTERACTIVE_ROLES must include button and link");
});

test('_agent_state_path returns project-scoped path', () => {
  assert(/def _agent_state_path\(\):/.test(PY_CONTENT),
    "_agent_state_path must be a zero-arg function");
  assert(/agent-state\.json/.test(PY_CONTENT),
    "_agent_state_path must return path to agent-state.json");
  assert(/CDPILOT_HOME[\s\S]{0,80}projects[\s\S]{0,80}PROJECT_ID[\s\S]{0,80}agent-state/.test(PY_CONTENT),
    "_agent_state_path must use CDPILOT_HOME/projects/PROJECT_ID");
});

test('_load_agent_state returns fresh state dict on missing file', () => {
  assert(/def _load_agent_state\(\):/.test(PY_CONTENT),
    "_load_agent_state must be defined");
  const m = PY_CONTENT.match(/def _load_agent_state[\s\S]{0,400}?ref_counter/);
  assert(m, "_load_agent_state fresh state must include ref_counter");
  const m2 = PY_CONTENT.match(/def _load_agent_state[\s\S]{0,400}?total_tokens_full/);
  assert(m2, "_load_agent_state fresh state must include total_tokens_full");
});

test('_save_agent_state drops oldest entries when actions_map exceeds 1000', () => {
  assert(/len\(amap\)\s*>\s*1000/.test(PY_CONTENT),
    "_save_agent_state must enforce 1000-entry cap on actions_map");
  assert(/sorted_refs\[:200\]/.test(PY_CONTENT) || /\[:200\]/.test(PY_CONTENT),
    "_save_agent_state must drop 200 oldest entries when cap exceeded");
});

test('_estimate_tokens uses chars//4 heuristic', () => {
  assert(/def _estimate_tokens\(/.test(PY_CONTENT),
    "_estimate_tokens must be defined");
  assert(/\/\/\s*4/.test(PY_CONTENT),
    "_estimate_tokens must divide by 4");
});

test('_diff_snapshots computes added/removed/value_changed', () => {
  assert(/def _diff_snapshots\(old_map,\s*new_actions\)/.test(PY_CONTENT),
    "_diff_snapshots must accept old_map and new_actions");
  assert(/'added'/.test(PY_CONTENT) && /'removed'/.test(PY_CONTENT) && /'value_changed'/.test(PY_CONTENT),
    "_diff_snapshots output dict must have added, removed, value_changed keys");
});

test('_diff_snapshots uses set operations for efficiency (no O(n) .remove)', () => {
  // The old_refs/new_refs approach with set difference
  const m = PY_CONTENT.match(/_diff_snapshots[\s\S]{0,600}?set\(/);
  assert(m, "_diff_snapshots must use set operations for O(1) lookups");
});

test('_snapshot_to_actions assigns monotonically increasing ref IDs', () => {
  assert(/def _snapshot_to_actions\(nodes,\s*state\)/.test(PY_CONTENT),
    "_snapshot_to_actions must be defined");
  assert(/ref_counter.*\+= 1/.test(PY_CONTENT),
    "_snapshot_to_actions must increment ref_counter for new elements");
});

test('_snapshot_to_actions reuses existing ref for same backend_node_id', () => {
  // bid_to_ref reverse map is built and then .get(bid) is used to look up existing ref
  assert(/bid_to_ref\s*=\s*\{/.test(PY_CONTENT),
    "_snapshot_to_actions must build bid_to_ref reverse map");
  assert(/bid_to_ref\.get\(bid\)/.test(PY_CONTENT),
    "_snapshot_to_actions must use bid_to_ref.get(bid) to reuse existing ref");
});

test('cmd_agent_observe is async and outputs JSON with required fields', () => {
  assert(/async def cmd_agent_observe\(\)/.test(PY_CONTENT),
    "cmd_agent_observe must be async def");
  const m = PY_CONTENT.match(/cmd_agent_observe[\s\S]{0,1000}?token_estimate/);
  assert(m, "cmd_agent_observe output must include token_estimate");
  const m2 = PY_CONTENT.match(/cmd_agent_observe[\s\S]{0,1000}?'actions'/);
  assert(m2, "cmd_agent_observe output must include actions key");
});

test('cmd_agent_act is async and handles click/type/hover/submit/url', () => {
  assert(/async def cmd_agent_act\(/.test(PY_CONTENT),
    "cmd_agent_act must be async def");
  assert(/action\s*==\s*'click'/.test(PY_CONTENT),
    "cmd_agent_act must handle click action");
  assert(/action\s*in\s*\('type',\s*'fill'\)/.test(PY_CONTENT),
    "cmd_agent_act must handle type/fill actions");
  assert(/action\s*==\s*'hover'/.test(PY_CONTENT),
    "cmd_agent_act must handle hover action");
  assert(/action\s*==\s*'submit'/.test(PY_CONTENT),
    "cmd_agent_act must handle submit action");
  assert(/if url:/.test(PY_CONTENT),
    "cmd_agent_act must handle --url navigation");
});

test('cmd_agent_act type/fill uses Input.insertText CDP (not cmd_fill selector)', () => {
  const m = PY_CONTENT.match(/Input\.insertText/);
  assert(m, "cmd_agent_act type/fill must use Input.insertText CDP method");
});

test('cmd_agent_act outputs diff JSON with saved_vs_full', () => {
  const m = PY_CONTENT.match(/saved_vs_full/);
  assert(m, "cmd_agent_act output must include saved_vs_full ratio");
});

test('cmd_agent_reset deletes state file and outputs JSON', () => {
  assert(/async def cmd_agent_reset\(\)/.test(PY_CONTENT),
    "cmd_agent_reset must be async def");
  assert(/os\.remove\(.*agent/.test(PY_CONTENT) || /os\.remove\(path\)/.test(PY_CONTENT),
    "cmd_agent_reset must call os.remove on state file");
  const m = PY_CONTENT.match(/cmd_agent_reset[\s\S]{0,200}?'status'.*'reset'|'status'.*'reset'[\s\S]{0,200}?cmd_agent_reset/);
  assert(m, "cmd_agent_reset must output {status: reset}");
});

test('cmd_agent_stats outputs token savings JSON', () => {
  assert(/async def cmd_agent_stats\(\)/.test(PY_CONTENT),
    "cmd_agent_stats must be async def");
  const m = PY_CONTENT.match(/cmd_agent_stats[\s\S]{0,400}?savings_pct|savings_pct[\s\S]{0,400}?cmd_agent_stats/);
  assert(m, "cmd_agent_stats must output savings_pct");
});

test('_dispatch_agent_cmd is synchronous and returns coroutine', () => {
  assert(/def _dispatch_agent_cmd\(args\):/.test(PY_CONTENT),
    "_dispatch_agent_cmd must be a sync function");
  // It returns coroutines from async fns, not calls asyncio.run
  const m = PY_CONTENT.match(/_dispatch_agent_cmd[\s\S]{0,800}?return cmd_agent_observe\(\)/);
  assert(m, "_dispatch_agent_cmd must return coroutine for observe");
});

test('_dispatch_agent_cmd parses --ref, --action, --text, --url flags', () => {
  assert(/--ref/.test(PY_CONTENT), "_dispatch_agent_cmd must parse --ref flag");
  assert(/--action/.test(PY_CONTENT), "_dispatch_agent_cmd must parse --action flag");
  assert(/--text/.test(PY_CONTENT), "_dispatch_agent_cmd must parse --text flag");
  assert(/--url/.test(PY_CONTENT), "_dispatch_agent_cmd must parse --url flag");
});

test("'agent' command registered in main() async_map dispatch", () => {
  const m = PY_CONTENT.match(/'agent'\s*:\s*lambda[\s\S]{0,100}?_dispatch_agent_cmd/);
  assert(m, "'agent' must be in async_map pointing to _dispatch_agent_cmd");
});

test('_agent_full_snapshot syncs _A11Y_REF_MAP for click-ref compatibility', () => {
  const m = PY_CONTENT.match(/_agent_full_snapshot[\s\S]{0,600}?_A11Y_REF_MAP/);
  assert(m, "_agent_full_snapshot must update global _A11Y_REF_MAP");
  const m2 = PY_CONTENT.match(/_agent_full_snapshot[\s\S]{0,700}?_save_a11y_refs/);
  assert(m2, "_agent_full_snapshot must call _save_a11y_refs for click-ref compat");
});

// ── Browserbase-compatible API (serve command) ──

console.log('\n  Browserbase-compatible API (serve command)\n');

test('cmd_serve function defined', () => {
  assert(/def cmd_serve/.test(PY_CONTENT), 'cmd_serve must be defined');
});

test('BrowserbaseHandler class defined', () => {
  assert(/class BrowserbaseHandler/.test(PY_CONTENT), 'BrowserbaseHandler must be defined');
});

test('DEFAULT_MAX_SESSIONS defined', () => {
  assert(/DEFAULT_MAX_SESSIONS/.test(PY_CONTENT), 'DEFAULT_MAX_SESSIONS must be defined');
});

test('_api_create_session defined', () => {
  assert(/def _api_create_session/.test(PY_CONTENT), '_api_create_session must be defined');
});

test('_api_get_session defined', () => {
  assert(/def _api_get_session/.test(PY_CONTENT), '_api_get_session must be defined');
});

test('_api_release_session defined', () => {
  assert(/def _api_release_session/.test(PY_CONTENT), '_api_release_session must be defined');
});

test("serve command registered in main() dispatch", () => {
  assert(/cmd == .serve./.test(PY_CONTENT), "'serve' must be handled in main()");
});

test('TEST_MODE env var supported in _api_create_session', () => {
  assert(/CDPILOT_API_TEST_MODE/.test(PY_CONTENT), 'CDPILOT_API_TEST_MODE must be checked');
});

test('ThreadingHTTPServer used in cmd_serve', () => {
  assert(/ThreadingHTTPServer/.test(PY_CONTENT), 'ThreadingHTTPServer must be used');
});

test('CDPILOT_MAX_SESSIONS env configures session limit', () => {
  assert(/CDPILOT_MAX_SESSIONS/.test(PY_CONTENT), 'CDPILOT_MAX_SESSIONS env var must be read');
});

test('atexit shutdown registered in cmd_serve', () => {
  const m = PY_CONTENT.match(/def cmd_serve[\s\S]{0,600}?atexit\.register/);
  assert(m, 'cmd_serve must register atexit shutdown handler');
});

test('/healthz route handled in do_GET', () => {
  assert(/healthz/.test(PY_CONTENT), '/healthz route must be handled');
});

test('/v1/sessions POST route handled in do_POST', () => {
  const m = PY_CONTENT.match(/def do_POST[\s\S]{0,400}?\/v1\/sessions/);
  assert(m, 'do_POST must handle /v1/sessions');
});

test('/v1/sessions/{id}/debug route handled', () => {
  assert(/debug/.test(PY_CONTENT) && /debuggerUrl/.test(PY_CONTENT),
    '/debug route must return debuggerUrl');
});

test('do_DELETE handles /v1/sessions/{id}', () => {
  assert(/def do_DELETE/.test(PY_CONTENT), 'do_DELETE must be defined');
  const m = PY_CONTENT.match(/def do_DELETE[\s\S]{0,400}?_api_release_session/);
  assert(m, 'do_DELETE must call _api_release_session');
});

test('404 returned for unknown routes', () => {
  assert(/not_found/.test(PY_CONTENT), 'unknown routes must return not_found error');
});

test('Browserbase session dict shape contains required fields', () => {
  assert(/'id'/.test(PY_CONTENT), "session dict must have 'id'");
  assert(/'createdAt'/.test(PY_CONTENT), "session dict must have 'createdAt'");
  assert(/'connectUrl'/.test(PY_CONTENT), "session dict must have 'connectUrl'");
  assert(/'status'/.test(PY_CONTENT), "session dict must have 'status'");
  assert(/'seleniumRemoteUrl'/.test(PY_CONTENT), "session dict must have 'seleniumRemoteUrl'");
});

// ── Live API server tests (spawn Python with TEST_MODE) ──

(function() {
  const http = require('http');
  const os = require('os');
  const { spawn, spawnSync } = require('child_process');

  const API_PORT = 19333;
  const PY_SCRIPT = path.join(__dirname, '..', 'src', 'cdpilot.py');

  // Check curl availability
  const curlCheck = spawnSync('curl', ['--version'], { encoding: 'utf-8' });
  if (curlCheck.error) {
    console.log('  ⚠ curl not available — skipping live API server tests');
    return;
  }

  // Isolated registry home: _api_create_session() allocates a real port via
  // _allocate_port()/registry.json on every POST /v1/sessions. Without this
  // override these tests read and mutate the operator's real
  // ~/.cdpilot/registry.json on every run.
  const apiTestHome = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-api-test-'));

  // Start server
  const serverProc = spawn(
    'python3', [PY_SCRIPT, 'serve', '--api', `--port=${API_PORT}`],
    {
      env: { ...process.env, CDPILOT_API_TEST_MODE: '1', CDP_PORT: '19222', CDPILOT_HOME: apiTestHome },
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );

  // Poll until ready (max 6s)
  const deadline = Date.now() + 6000;
  let ready = false;
  while (Date.now() < deadline) {
    const r = spawnSync('curl', ['-s', '-o', '/dev/null', '-w', '%{http_code}',
      `http://127.0.0.1:${API_PORT}/healthz`], { encoding: 'utf-8', timeout: 1000 });
    if (r.stdout && r.stdout.trim() === '200') { ready = true; break; }
    spawnSync('sleep', ['0.2']);
  }

  if (!ready) {
    serverProc.kill();
    console.log('  ⚠ API server did not start in time — skipping live tests');
    return;
  }

  function curl(method, urlPath, body) {
    const curlArgs = ['-s', '-w', '\n%{http_code}', '-X', method,
      `http://127.0.0.1:${API_PORT}${urlPath}`,
      '-H', 'Content-Type: application/json'];
    if (body) curlArgs.push('-d', JSON.stringify(body));
    const r = spawnSync('curl', curlArgs, { encoding: 'utf-8', timeout: 5000 });
    const lines = (r.stdout || '').split('\n');
    const status = parseInt(lines[lines.length - 1], 10);
    let json = null;
    try { json = JSON.parse(lines.slice(0, -1).join('\n')); } catch (_) {}
    return { status, json };
  }

  test('live: GET /healthz returns 200 with status ok', () => {
    const { status, json } = curl('GET', '/healthz');
    assert.strictEqual(status, 200, 'healthz must return 200');
    assert(json && json.status === 'ok', 'healthz must return {status: "ok"}');
  });

  let createdId = null;

  test('live: POST /v1/sessions returns 201 with id and connectUrl', () => {
    const { status, json } = curl('POST', '/v1/sessions', {});
    assert.strictEqual(status, 201, 'POST /v1/sessions must return 201');
    assert(json && json.id && json.id.startsWith('sess_'), 'id must start with sess_');
    assert(json && json.connectUrl, 'connectUrl must be present');
    createdId = json.id;
  });

  test('live: GET /v1/sessions returns array', () => {
    const { status, json } = curl('GET', '/v1/sessions');
    assert.strictEqual(status, 200, 'GET /v1/sessions must return 200');
    assert(Array.isArray(json), 'response must be an array');
  });

  test('live: GET /v1/sessions/{id} returns session', () => {
    if (!createdId) { assert.fail('No session created, skipping'); }
    const { status, json } = curl('GET', `/v1/sessions/${createdId}`);
    assert.strictEqual(status, 200, 'GET session by id must return 200');
    assert(json && json.id === createdId, 'returned session id must match');
  });

  test('live: GET /v1/sessions/{id}/debug returns debuggerUrl', () => {
    if (!createdId) { assert.fail('No session created, skipping'); }
    const { status, json } = curl('GET', `/v1/sessions/${createdId}/debug`);
    assert.strictEqual(status, 200, '/debug must return 200');
    assert(json && json.debuggerUrl, 'debuggerUrl must be present');
  });

  test('live: DELETE /v1/sessions/{id} returns 200', () => {
    if (!createdId) { assert.fail('No session created, skipping'); }
    const { status, json } = curl('DELETE', `/v1/sessions/${createdId}`);
    assert.strictEqual(status, 200, 'DELETE must return 200');
    assert(json && json.status === 'ok', 'response must be {status: "ok"}');
  });

  test('live: GET /v1/sessions/{id} after delete returns 404', () => {
    if (!createdId) { assert.fail('No session created, skipping'); }
    const { status } = curl('GET', `/v1/sessions/${createdId}`);
    assert.strictEqual(status, 404, 'deleted session must return 404');
  });

  test('live: unknown route returns 404', () => {
    const { status } = curl('GET', '/v1/unknown-route');
    assert.strictEqual(status, 404, 'unknown route must return 404');
  });

  serverProc.kill();
  fs.rmSync(apiTestHome, { recursive: true, force: true });
})();

// ── Port registry cleanup regression (vaat-denetimi-2026-09-27) ──
// _allocate_port() used to trust every registry entry forever, even ones
// whose port was long dead (browser closed, process exited, machine
// rebooted). On a long-lived dev machine the registry accumulated 127
// such entries and, once enough of them piled up inside the 100-slot
// 9222-9322 range, _allocate_port() raised "No free port" even though
// nothing was actually listening anywhere — which is exactly what broke
// the `serve --api` tests above on this machine before the fix.
// All of this runs against a throwaway CDPILOT_HOME; the user's real
// ~/.cdpilot/registry.json is never read or written by these tests.
(function() {
  const { spawnSync } = require('child_process');
  const os = require('os');

  const tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-registry-test-'));

  function writeFakeRegistry(ports) {
    const projects = {};
    for (const port of ports) {
      projects[`fake-project-${port}`] = {
        cwd: `/tmp/fake-${port}`,
        port,
        profile_dir: `/tmp/fake-${port}/profile`,
        // Absurdly large, guaranteed-nonexistent pid (real pids top out
        // around 10^5-10^7 on every platform) — never collides with a
        // real running process.
        pid: 900000000 + port,
        created: '2020-01-01T00:00:00',
        last_used: '2020-01-01T00:00:00',
        status: 'running',
      };
    }
    fs.writeFileSync(
      path.join(tmpHome, 'registry.json'),
      JSON.stringify({ version: 1, projects }, null, 2)
    );
  }

  function runPy(script) {
    return spawnSync('python3', ['-c', script], {
      encoding: 'utf-8',
      timeout: 15000,
      env: { ...process.env, CDPILOT_HOME: tmpHome },
    });
  }

  // This machine may already have something genuinely bound to a handful
  // of ports inside 9222-9322 (another tool, a leftover dev browser, ...).
  // Probing for ports that are ACTUALLY free right now — instead of
  // assuming the whole range is free — keeps the fake-registry tests
  // deterministic regardless of what else is running on the host.
  function findFreePorts(count) {
    const script = `
import socket, json

def is_free(p):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", p))
        return True
    except OSError:
        return False
    finally:
        s.close()

found = []
for p in range(9222, 9322):
    if is_free(p):
        found.append(p)
    if len(found) >= ${count}:
        break
print(json.dumps(found))
`;
    const r = spawnSync('python3', ['-c', script], { encoding: 'utf-8', timeout: 10000 });
    if (r.status !== 0) {
      throw new Error(`findFreePorts(${count}) failed: ${r.stderr}`);
    }
    const ports = JSON.parse((r.stdout || '[]').trim());
    assert.strictEqual(ports.length, count,
      `expected ${count} free ports in 9222-9322, only found ${ports.length}`);
    return ports;
  }

  // Every port in 9222-9322 that is free RIGHT NOW, whatever that count is
  // (a couple of slots may legitimately be held by something else on this
  // host). Filling exactly these with dead registry entries still saturates
  // the range for the pre-fix _allocate_port: the handful of genuinely-bound
  // ports were already unavailable via its own _is_port_free() check, and
  // every other slot is now claimed by a fake dead entry.
  function findAllCurrentlyFreePorts() {
    const script = `
import socket, json

def is_free(p):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", p))
        return True
    except OSError:
        return False
    finally:
        s.close()

print(json.dumps([p for p in range(9222, 9322) if is_free(p)]))
`;
    const r = spawnSync('python3', ['-c', script], { encoding: 'utf-8', timeout: 10000 });
    if (r.status !== 0) {
      throw new Error(`findAllCurrentlyFreePorts failed: ${r.stderr}`);
    }
    return JSON.parse((r.stdout || '[]').trim());
  }

  const IMPORT_SNIPPET = `
import importlib.util
spec = importlib.util.spec_from_file_location("cdpilot_under_test", ${JSON.stringify(PY_PATH)})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
`;

  test('registry: pid liveness never signals the process (Windows os.kill(pid, 0) terminates it)', () => {
    // On Windows, Python turns os.kill(pid, 0) into TerminateProcess. The
    // registry cleanup runs on every command's startup against pids that may
    // have been reused by unrelated programs, so a "probe" there could kill
    // them. All liveness checks must go through _pid_alive, which asks the
    // kernel on Windows. Comments are stripped so a mention can't pass.
    const code = PY_CONTENT.split('\n').map((l) => l.replace(/#.*$/, '')).join('\n');
    const probes = code.match(/os\.kill\([^,]+,\s*0\s*\)/g) || [];
    assert.strictEqual(probes.length, 1,
      `exactly one os.kill(pid, 0) allowed (inside _pid_alive), found ${probes.length}`);
    const fn = (code.match(/def _pid_alive\(pid\):([\s\S]*?)\n\ndef /) || [])[1] || '';
    assert(/os\.name == "nt"/.test(fn) && /OpenProcess/.test(fn),
      '_pid_alive must take the OpenProcess path on Windows');
    assert(fn.indexOf('os.name == "nt"') < fn.indexOf('os.kill('),
      'the Windows branch must return before os.kill is reached');
  });

  test('registry: port probe cannot bind over a live listener on Windows', () => {
    // Windows SO_REUSEADDR lets a socket bind on top of a port another socket
    // is listening on, so a probe using it called every port free: CI on
    // windows-latest pruned a live entry (2026-09-27). The Windows branch must
    // ask for exclusive use instead.
    const code = PY_CONTENT.split('\n').map((l) => l.replace(/#.*$/, '')).join('\n');
    const fn = (code.match(/def _is_port_free\(port\):([\s\S]*?)\n\ndef /) || [])[1] || '';
    assert(/os\.name == "nt"/.test(fn) && /SO_EXCLUSIVEADDRUSE/.test(fn),
      '_is_port_free must use SO_EXCLUSIVEADDRUSE on Windows');
    assert(fn.indexOf('SO_EXCLUSIVEADDRUSE, 1') < fn.indexOf('SO_REUSEADDR, 1'),
      'SO_REUSEADDR must only be reached on the non-Windows branch');
  });

  test('registry: _is_port_free reports a listening port as taken', () => {
    const [p] = findFreePorts(1);
    const r = runPy(`
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", ${p}))
s.listen(1)
${IMPORT_SNIPPET}
print("FREE_WHILE_LISTENING=" + str(mod._is_port_free(${p})))
s.close()
`);
    assert.strictEqual(r.status, 0, `probe must not error (stderr: ${r.stderr})`);
    assert(/FREE_WHILE_LISTENING=False/.test(r.stdout),
      `a listening port must not look free, got stdout=${r.stdout}`);
  });

  test('registry: _pid_alive tells a live pid from a dead one', () => {
    const r = runPy(IMPORT_SNIPPET +
      'import os\nprint("SELF=" + str(mod._pid_alive(os.getpid())))\n' +
      'print("DEAD=" + str(mod._pid_alive(900000000)))\nprint("BAD=" + str(mod._pid_alive("x")))\n');
    assert.strictEqual(r.status, 0, `_pid_alive must not error (stderr: ${r.stderr})`);
    assert(/SELF=True/.test(r.stdout) && /DEAD=False/.test(r.stdout) && /BAD=False/.test(r.stdout),
      `unexpected liveness results: ${r.stdout}`);
  });

  test('registry: CDPILOT_HOME is overridable via env var (test isolation)', () => {
    assert(PY_CONTENT.includes('os.environ.get("CDPILOT_HOME")'),
      'CDPILOT_HOME must honor an env override so tests never touch the real ~/.cdpilot registry');
  });

  test('registry: 100 dead entries filling the whole port range no longer exhaust _allocate_port (regression)', () => {
    // Fill every currently-free port in the 9222-9322 range with fake,
    // dead entries: nothing is listening on any of them and none of the
    // pids exist. A correct _allocate_port() must prune them first and
    // hand back a free port; the pre-fix implementation trusted the
    // registry file unconditionally and raised "No free port in range
    // 9222-9322" once dead entries alone covered every free slot.
    const freePorts = findAllCurrentlyFreePorts();
    assert(freePorts.length > 0, 'need at least one free port in range to run this test');
    writeFakeRegistry(freePorts);
    const r = runPy(IMPORT_SNIPPET + 'print("PORT=" + str(mod._allocate_port("brand-new-project-id")))\n');
    assert.strictEqual(r.status, 0,
      `_allocate_port must succeed once dead entries are pruned (stderr: ${r.stderr})`);
    assert(/PORT=\d+/.test(r.stdout || ''),
      `expected an allocated port, got stdout=${r.stdout} stderr=${r.stderr}`);
  });

  test('registry: dead entries are actually removed from disk, not just marked stopped', () => {
    const ports = findFreePorts(5);
    writeFakeRegistry(ports);
    const r = runPy(IMPORT_SNIPPET + 'reg = mod._cleanup_registry()\nprint("COUNT=" + str(len(reg)))\n');
    assert.strictEqual(r.status, 0, `_cleanup_registry must not error (stderr: ${r.stderr})`);
    assert(/COUNT=0/.test(r.stdout || ''),
      `all 5 dead entries should be pruned, got stdout=${r.stdout}`);
    const onDisk = JSON.parse(fs.readFileSync(path.join(tmpHome, 'registry.json'), 'utf-8'));
    assert.strictEqual(Object.keys(onDisk.projects).length, 0,
      'pruned entries must be persisted to registry.json, not just returned in memory');
  });

  test('registry: a genuinely live (listening) port is never pruned', () => {
    // Bind a real socket on the fake entry's port *before* cleanup runs, in
    // the same Python process, so there is no cross-process timing race:
    // a dead-looking registry entry whose port is actually bound (e.g.
    // another project's live browser) must survive cleanup.
    const [livePort] = findFreePorts(1);
    writeFakeRegistry([livePort]);
    const script = `
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", ${livePort}))
s.listen(1)
${IMPORT_SNIPPET}
reg = mod._cleanup_registry()
print("KEPT=" + str("fake-project-${livePort}" in reg))
s.close()
`;
    const r = runPy(script);
    assert.strictEqual(r.status, 0, `cleanup must not error (stderr: ${r.stderr})`);
    assert(/KEPT=True/.test(r.stdout || ''),
      `a live (listening) port's registry entry must never be pruned, got stdout=${r.stdout} stderr=${r.stderr}`);
  });

  test('registry: pruning never touches the real ~/.cdpilot/registry.json', () => {
    const realRegistry = path.join(os.homedir(), '.cdpilot', 'registry.json');
    const before = fs.existsSync(realRegistry) ? fs.readFileSync(realRegistry, 'utf-8') : null;
    writeFakeRegistry(findFreePorts(3));
    runPy(IMPORT_SNIPPET + 'mod._cleanup_registry()\n');
    const after = fs.existsSync(realRegistry) ? fs.readFileSync(realRegistry, 'utf-8') : null;
    assert.strictEqual(before, after, "the user's real registry.json must be untouched by these tests");
  });

  // ── stop: bounded, and only ever cdpilot's own browser (2026-09-27) ──
  // `cdpilot stop` ran `lsof` with no timeout (hung forever on a Mac with a
  // stale network mount) and, on Windows, `taskkill /IM chrome.exe` etc.,
  // which also killed the user's personal browser.
  const PYBIN = process.env.CDPILOT_PYTHON || 'python3';
  const CODE_NO_COMMENTS = PY_CONTENT.split('\n').map((l) => l.replace(/#.*$/, '')).join('\n');

  // Argument text of a call whose '(' sits at openIdx (string-aware).
  function callArgs(src, openIdx) {
    let depth = 0;
    let quote = null;
    for (let i = openIdx; i < src.length; i++) {
      const c = src[i];
      if (quote) {
        if (c === '\\') i++;
        else if (c === quote) quote = null;
        continue;
      }
      if (c === '"' || c === "'") quote = c;
      else if ('([{'.includes(c)) depth++;
      else if (')]}'.includes(c) && --depth === 0) return src.slice(openIdx + 1, i);
    }
    return src.slice(openIdx + 1);
  }

  test('stop: no taskkill call targets an image name (/IM kills the user\'s own browser)', () => {
    assert(!/taskkill[^\n]*\/IM\b/i.test(CODE_NO_COMMENTS),
      'a taskkill command line must never use /IM');
    assert(!/\[\s*["']taskkill["'][^\]]*["']\/IM["']/i.test(CODE_NO_COMMENTS),
      'a taskkill argv must never contain "/IM"; kill by /PID of the matched process instead');
    const fn = (CODE_NO_COMMENTS.match(/def cmd_stop\(\):([\s\S]*?)\n\ndef /) || [])[1] || '';
    assert(/_stop_browser_on_port\(CDP_PORT/.test(fn),
      'cmd_stop must go through the shared _stop_browser_on_port helper');
  });

  test('stop: every lsof/pkill/pgrep/taskkill/powershell subprocess.run passes timeout=', () => {
    const re = /subprocess\.(?:run|call|check_output|check_call)\(/g;
    let m;
    let checked = 0;
    const missing = [];
    while ((m = re.exec(CODE_NO_COMMENTS)) !== null) {
      const args = callArgs(CODE_NO_COMMENTS, m.index + m[0].length - 1);
      const argv0 = (args.match(/^\s*\[\s*f?["']([^"']+)["']/) || [])[1] || '';
      if (!/^(lsof|pkill|pgrep|taskkill|powershell)(\.exe)?$/i.test(argv0)) continue;
      checked++;
      if (!/\btimeout\s*=/.test(args)) missing.push(`${argv0}: ${args.slice(0, 80)}`);
    }
    assert(checked >= 3, `expected the pgrep/powershell/taskkill calls to be found, saw ${checked}`);
    assert.deepStrictEqual(missing, [], `process-tool calls without timeout=:\n${missing.join('\n')}`);
  });

  test('stop: nothing listening -> returns fast and reports no browser found', () => {
    const [p] = findFreePorts(1);
    const started = Date.now();
    const r = spawnSync(PYBIN, [PY_PATH, 'stop'], {
      encoding: 'utf-8',
      timeout: 30000,
      env: {
        ...process.env,
        CDPILOT_HOME: tmpHome,
        CDP_PORT: String(p),
        CDPILOT_PROFILE: path.join(tmpHome, 'stop-profile'),
      },
    });
    const elapsed = Date.now() - started;
    assert(!r.error, `stop must not hang or fail to spawn: ${r.error}`);
    assert(elapsed < 10000, `stop took ${elapsed} ms with nothing to stop (limit 10000)`);
    assert(new RegExp(`No browser process found \\(port ${p}\\)`).test(r.stderr + r.stdout),
      `expected "No browser process found (port ${p})", got stdout=${r.stdout} stderr=${r.stderr}`);
  });

  test('stop: kills the process with --remote-debugging-port=<p>, never the one with <p>0', () => {
    // Two dummy processes, no real browser. The first listens on p like a
    // browser would (and never answers HTTP, so the graceful Browser.close
    // step has to give up on its own); the second only carries the look-alike
    // flag p0. The flag text is built from pieces so this script's own command
    // line never contains an exact match.
    const [p] = findFreePorts(1);
    const script = `
import json, os, subprocess, sys, threading, time
P = ${p}
${IMPORT_SNIPPET}
flag = "--remote-debugging-" + "port="
listener = "import socket, sys, time\\ns = socket.socket()\\ns.bind(('127.0.0.1', int(sys.argv[1])))\\ns.listen(5)\\ntime.sleep(60)"
d1 = subprocess.Popen([sys.executable, "-c", listener, str(P), flag + str(P)])
d2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", flag + str(P) + "0"])
reaper = threading.Thread(target=d1.wait, daemon=True)  # no zombie for pid checks
reaper.start()
out = {"d1": d1.pid, "d2": d2.pid}
try:
    deadline = time.time() + 10
    while time.time() < deadline and mod._is_port_free(P):
        time.sleep(0.1)
    out["bound"] = not mod._is_port_free(P)
    out["matched"] = sorted(mod._debug_port_pids(P))
    env = dict(os.environ, CDP_PORT=str(P),
               CDPILOT_PROFILE=os.path.join(os.environ["CDPILOT_HOME"], "stop-profile"))
    t0 = time.time()
    r = subprocess.run([sys.executable, ${JSON.stringify(PY_PATH)}, "stop"], env=env,
                       capture_output=True, text=True, timeout=40)
    out["elapsed"] = round(time.time() - t0, 2)
    out["stdout"], out["stderr"] = r.stdout, r.stderr
    reaper.join(10)
    out["d1_dead"] = d1.returncode is not None
    out["d2_alive"] = d2.poll() is None
finally:
    for d in (d1, d2):
        try:
            d.kill()
        except OSError:
            pass
print("RESULT=" + json.dumps(out))
`;
    const r = spawnSync(PYBIN, ['-c', script], {
      encoding: 'utf-8',
      timeout: 60000,
      env: { ...process.env, CDPILOT_HOME: tmpHome },
    });
    assert(!r.error, `harness failed to run: ${r.error}`);
    const line = (r.stdout || '').split('\n').find((l) => l.startsWith('RESULT='));
    assert(line, `no result (status ${r.status}) stdout=${r.stdout} stderr=${r.stderr}`);
    const res = JSON.parse(line.slice('RESULT='.length));
    assert(res.bound, `dummy browser never bound port ${p}: ${line}`);
    assert(res.matched.includes(res.d1) && !res.matched.includes(res.d2),
      `pid match must be exact (want ${res.d1}, not ${res.d2}): ${line}`);
    assert(res.elapsed < 20, `stop took ${res.elapsed}s: ${line}`);
    assert(new RegExp(`Browser stopped \\(port ${p}\\)`).test(res.stdout),
      `expected "Browser stopped (port ${p})": ${line}`);
    assert(res.d1_dead, `the --remote-debugging-port=${p} process must be stopped: ${line}`);
    assert(res.d2_alive, `the --remote-debugging-port=${p}0 process must survive: ${line}`);
  });

  fs.rmSync(tmpHome, { recursive: true, force: true });
})();

// ── Test Runner ──

const FIXTURE = path.join(__dirname, 'fixtures', 'example.cdpt.js');

test('test runner: fixture file exists', () => {
  assert(fs.existsSync(FIXTURE), 'example.cdpt.js should exist');
});

test('test runner: cmd_test defined in cdpilot.py', () => {
  assert(PY_CONTENT.includes('def cmd_test('), 'Should define cmd_test');
});

test('test runner: cmd_trace_list defined in cdpilot.py', () => {
  assert(PY_CONTENT.includes('def cmd_trace_list()'), 'Should define cmd_trace_list');
});

test('test runner: cmd_trace_open defined in cdpilot.py', () => {
  assert(PY_CONTENT.includes('def cmd_trace_open('), 'Should define cmd_trace_open');
});

test('test runner: cmd_trace_clean defined in cdpilot.py', () => {
  assert(PY_CONTENT.includes('def cmd_trace_clean('), 'Should define cmd_trace_clean');
});

test('test runner: TRACES_DIR constant defined', () => {
  assert(PY_CONTENT.includes("TRACES_DIR = os.path.join(CDPILOT_HOME, 'traces')"), 'Should define TRACES_DIR');
});

test('test runner: TRACE_VIEWER_HTML constant defined', () => {
  assert(PY_CONTENT.includes('TRACE_VIEWER_HTML = """'), 'Should define TRACE_VIEWER_HTML');
});

test('test runner: test and trace registered in sync_cmds', () => {
  assert(/'test':\s*lambda:\s*cmd_test_dispatch/.test(PY_CONTENT), "Should register 'test' in sync_cmds");
  assert(/'trace':\s*lambda:\s*cmd_trace_dispatch/.test(PY_CONTENT), "Should register 'trace' in sync_cmds");
});

test('test runner: --internal-test-runner flag handled in bin/cdpilot.js', () => {
  const binContent = fs.readFileSync(path.join(__dirname, '..', 'bin', 'cdpilot.js'), 'utf-8');
  assert(binContent.includes('--internal-test-runner'), 'bin/cdpilot.js should handle --internal-test-runner');
  assert(binContent.includes('runInternalTestRunner'), 'Should define runInternalTestRunner function');
});

test('test runner: --grep flag parsed in cmd_test_dispatch', () => {
  assert(PY_CONTENT.includes("'--grep='"), 'Should handle --grep= flag');
});

test('test runner: reporters handled (json, junit, tap)', () => {
  assert(PY_CONTENT.includes("rep == 'json'"), 'Should handle json reporter');
  assert(PY_CONTENT.includes("rep == 'junit'"), 'Should handle junit reporter');
  assert(PY_CONTENT.includes("rep == 'tap'"), 'Should handle tap reporter');
});

test('test runner: parallel execution via ThreadPoolExecutor', () => {
  assert(PY_CONTENT.includes('ThreadPoolExecutor'), 'Should use ThreadPoolExecutor for parallel tests');
});

test('test runner: watch mode uses getmtime polling', () => {
  assert(PY_CONTENT.includes('getmtime') && PY_CONTENT.includes('watch'), 'Should poll mtime for watch mode');
});

test('test runner: trace bundle format — meta.json + steps.jsonl referenced', () => {
  const binContent = fs.readFileSync(path.join(__dirname, '..', 'bin', 'cdpilot.js'), 'utf-8');
  assert(binContent.includes('meta.json'), 'Should write meta.json');
  assert(binContent.includes('steps.jsonl'), 'Should write steps.jsonl');
});

test('test runner: trace clean handles d/h/m suffixes', () => {
  assert(PY_CONTENT.includes("'d': 86400"), 'Should handle day suffix');
  assert(PY_CONTENT.includes("'h': 3600"), 'Should handle hour suffix');
  assert(PY_CONTENT.includes("'m': 60"), 'Should handle minute suffix');
});

test('test runner: fixture runs via --internal-test-runner (no browser)', () => {
  const { execSync: es } = require('child_process');
  const os = require('os');
  const tmpDir = path.join(os.tmpdir(), 'cdpilot-test-' + Date.now());
  try {
    const out = es(
      `node ${CLI} --internal-test-runner ${FIXTURE} --trace-dir ${tmpDir} --trace=off`,
      { encoding: 'utf-8', timeout: 15000, env: { ...process.env, CDP_PORT: '19222' } }
    );
    const result = JSON.parse(out.trim().split('\n').pop());
    assert(result.passed >= 3, `Expected 3+ passed, got ${result.passed}`);
    assert.strictEqual(result.failed, 0, `Expected 0 failed, got ${result.failed}`);
  } finally {
    try { require('fs').rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
  }
});

test('test runner: --grep filters tests', () => {
  const { execSync: es } = require('child_process');
  const os = require('os');
  const tmpDir = path.join(os.tmpdir(), 'cdpilot-test-grep-' + Date.now());
  try {
    const out = es(
      `node ${CLI} --internal-test-runner ${FIXTURE} --trace-dir ${tmpDir} --trace=off --grep=noop`,
      { encoding: 'utf-8', timeout: 15000, env: { ...process.env, CDP_PORT: '19222' } }
    );
    const result = JSON.parse(out.trim().split('\n').pop());
    // Only 'noop test passes' and 'async noop' match 'noop'
    assert(result.tests.every(t => /noop/i.test(t.name)), 'grep should filter to noop tests only');
    assert.strictEqual(result.failed, 0, 'Filtered tests should pass');
  } finally {
    try { require('fs').rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
  }
});

// ── Agent Twitter Namespace ──

test('twitter: TWITTER_BASE constant defined', () => {
  assert(PY_CONTENT.includes("TWITTER_BASE = 'https://x.com'"), 'Should define TWITTER_BASE');
});

test('twitter: _TW_SEL dict contains required testid selectors', () => {
  assert(PY_CONTENT.includes('tweetTextarea_0'), 'Should have textarea selector');
  assert(PY_CONTENT.includes('tweetButtonInline'), 'Should have post_btn selector');
  assert(PY_CONTENT.includes('tweetButton'), 'Should have post_btn2 selector');
  assert(PY_CONTENT.includes("'reply_btn'"), 'Should have reply_btn key');
  assert(PY_CONTENT.includes("'like_btn'"), 'Should have like_btn key');
  assert(PY_CONTENT.includes("'follow_btn'"), 'Should have follow_btn key');
});

test('twitter: _TW_HUMANIZE checks CDPILOT_TWITTER_HUMANIZE env', () => {
  assert(PY_CONTENT.includes('CDPILOT_TWITTER_HUMANIZE'), 'Should check CDPILOT_TWITTER_HUMANIZE env var');
});

test('twitter: cmd_twitter_status checks logged_in, handle, rate_limited, suspended', () => {
  assert(PY_CONTENT.includes('cmd_twitter_status'), 'Should define cmd_twitter_status');
  assert(PY_CONTENT.includes("'logged_in'"), 'Status output should have logged_in field');
  assert(PY_CONTENT.includes("'handle'"), 'Status output should have handle field');
  assert(PY_CONTENT.includes("'rate_limited'"), 'Status output should have rate_limited field');
  assert(PY_CONTENT.includes("'suspended'"), 'Status output should have suspended field');
});

test('twitter: cmd_twitter_post navigates to compose/tweet', () => {
  assert(PY_CONTENT.includes('cmd_twitter_post'), 'Should define cmd_twitter_post');
  assert(PY_CONTENT.includes('/compose/tweet'), 'Should navigate to compose/tweet');
});

test('twitter: cmd_twitter_post prints tweet_id in output', () => {
  assert(PY_CONTENT.includes("'tweet_id'"), 'Post output should have tweet_id field');
});

test('twitter: cmd_twitter_thread uses humanized pacing via _tw_pause', () => {
  assert(PY_CONTENT.includes('cmd_twitter_thread'), 'Should define cmd_twitter_thread');
  const fn = PY_CONTENT.match(/async def cmd_twitter_thread[\s\S]{0,4000}?(?=\nasync def |\ndef [a-z])/);
  assert(fn, 'cmd_twitter_thread body must be present');
  assert(/_tw_pause/.test(fn[0]), 'Thread must use _tw_pause between actions for humanized timing');
});

test('twitter: cmd_twitter_reply navigates to /i/status/TWEET_ID', () => {
  assert(PY_CONTENT.includes('cmd_twitter_reply'), 'Should define cmd_twitter_reply');
  assert(PY_CONTENT.includes('/i/status/'), 'Should navigate to /i/status/');
});

test('twitter: cmd_twitter_replies slices articles from DOM', () => {
  assert(PY_CONTENT.includes('cmd_twitter_replies'), 'Should define cmd_twitter_replies');
  assert(PY_CONTENT.includes('querySelectorAll("article")'), 'Should use article selector');
});

test('twitter: cmd_twitter_like navigates and clicks like_btn', () => {
  assert(PY_CONTENT.includes('cmd_twitter_like'), 'Should define cmd_twitter_like');
  assert(PY_CONTENT.includes("_TW_SEL['like_btn']"), 'Should use like_btn selector');
});

test('twitter: cmd_twitter_follow navigates to profile and clicks follow_btn', () => {
  assert(PY_CONTENT.includes('cmd_twitter_follow'), 'Should define cmd_twitter_follow');
  assert(PY_CONTENT.includes("_TW_SEL['follow_btn']"), 'Should use follow_btn selector');
});

test('twitter: _dispatch_agent_twitter_cmd dispatches all subcommands', () => {
  assert(PY_CONTENT.includes('_dispatch_agent_twitter_cmd'), 'Should define _dispatch_agent_twitter_cmd');
  const subCmds = ['login', 'status', 'post', 'thread', 'reply', 'replies', 'mentions', 'profile', 'like', 'follow', 'analytics'];
  for (const s of subCmds) {
    assert(PY_CONTENT.includes(`sub == '${s}'`), `Dispatcher should handle '${s}'`);
  }
});

test('twitter: _dispatch_agent_cmd routes twitter to _dispatch_agent_twitter_cmd', () => {
  assert(PY_CONTENT.includes("sub == 'twitter'"), 'Agent dispatcher should route twitter subcommand');
  assert(PY_CONTENT.includes('return _dispatch_agent_twitter_cmd(rest)'), 'Should return twitter cmd coroutine');
});

// ── Blog tests ───────────────────────────────────────────────────────────────

test('blog: _dispatch_blog_cmd handles publish/list/regenerate subcommands', () => {
  assert(PY_CONTENT.includes('_dispatch_blog_cmd'), 'Should define _dispatch_blog_cmd');
  assert(PY_CONTENT.includes("sub == 'publish'"), "Dispatcher should handle 'publish'");
  assert(PY_CONTENT.includes("sub == 'list'"), "Dispatcher should handle 'list'");
  assert(PY_CONTENT.includes("sub == 'regenerate'"), "Dispatcher should handle 'regenerate'");
});

test('blog: cmd_blog_publish writes to BLOG_DIR with valid slug', () => {
  assert(PY_CONTENT.includes('def cmd_blog_publish'), 'Should define cmd_blog_publish');
  assert(PY_CONTENT.includes('BLOG_DIR'), 'Should declare BLOG_DIR constant');
  assert(PY_CONTENT.includes('_blog_slugify'), 'Should use _blog_slugify for slug generation');
  assert(/slug\s*=\s*_blog_slugify/.test(PY_CONTENT), 'Should assign slug via _blog_slugify');
});

test('blog: slug validation enforces kebab-case pattern', () => {
  assert(PY_CONTENT.includes('def _blog_slugify'), 'Should define _blog_slugify helper');
  assert(PY_CONTENT.includes('[a-z0-9]'), 'Should use [a-z0-9] character class in slug regex');
  assert(PY_CONTENT.includes("_re.match(r'^[a-z0-9]+(-[a-z0-9]+)*$', slug)"),
    'Should validate slug with kebab-case pattern');
});

test('blog: FAQ section minimum 3 items enforced', () => {
  assert(PY_CONTENT.includes('def _blog_generate_faq'), 'Should define _blog_generate_faq helper');
  assert(PY_CONTENT.includes('## FAQ'), 'Should emit ## FAQ section header');
  assert(PY_CONTENT.includes('### Q:'), 'Should emit ### Q: formatted FAQ questions');
  assert(/faq_items\s*=\s*_blog_generate_faq/.test(PY_CONTENT), 'Should call _blog_generate_faq');
});

test('blog: word count gate warns below 800 words', () => {
  assert(PY_CONTENT.includes('def _blog_estimate_words'), 'Should define _blog_estimate_words');
  assert(PY_CONTENT.includes('word_count < 800'), 'Should check for min 800 word threshold');
  assert(PY_CONTENT.includes('Warning: needs expansion'), 'Should print warning on low word count');
});

test('blog: sync_cmds dispatcher includes blog entry routing to _dispatch_blog_cmd', () => {
  assert(/'blog':\s*lambda/.test(PY_CONTENT), "sync_cmds should have 'blog' lambda entry");
  assert(PY_CONTENT.includes('_dispatch_blog_cmd(args)'), 'blog entry should call _dispatch_blog_cmd');
});

// ── Bug regression: PROJECT_ID=None path in _log_heal / _resolve_project_config ──

test('_resolve_project_config returns non-None project_id even in manual-override mode', () => {
  // When both CDP_PORT and CDPILOT_PROFILE are set (legacy/manual override),
  // _resolve_project_config used to return None as project_id, causing
  // os.path.join(CDPILOT_HOME, "projects", None, "heal.jsonl") → TypeError.
  // Fixed: use _get_project_id() fallback instead of hard-coded None.
  const m = PY_CONTENT.match(/if has_explicit_port and env_profile:\s*\n\s*return int\(env_port\), env_profile, (None|_get_project_id\(\))/);
  assert(m, '_resolve_project_config manual-override branch must be present');
  assert.notStrictEqual(m[1], 'None',
    '_resolve_project_config must NOT return None as project_id — use _get_project_id() instead to prevent posixpath.join TypeError');
});

test('_log_heal guards against None PROJECT_ID before os.path.join', () => {
  // Secondary safety net: even if PROJECT_ID ever becomes None, _log_heal must
  // silently skip writing rather than raising TypeError.
  const m = PY_CONTENT.match(/def _log_heal[\s\S]{0,400}?if not PROJECT_ID:\s*\n\s*return/);
  assert(m, '_log_heal must guard with `if not PROJECT_ID: return` before os.path.join call');
});

// ── v0.5.1 adaptive regression fixes ──

test('NavigationDrift exception class is defined', () => {
  assert(PY_CONTENT.includes('class NavigationDrift(Exception):'),
    'NavigationDrift exception class must be defined');
});

test('_assert_host raises NavigationDrift when CDPILOT_ADAPTIVE_STRICT=1', () => {
  // Verify that _assert_host checks os.environ for CDPILOT_ADAPTIVE_STRICT
  // and raises NavigationDrift (not a generic exception) on mismatch.
  assert(PY_CONTENT.includes("os.environ.get(\"CDPILOT_ADAPTIVE_STRICT\") == \"1\""),
    '_assert_host must check CDPILOT_ADAPTIVE_STRICT env var');
  assert(PY_CONTENT.includes('raise NavigationDrift('),
    '_assert_host must raise NavigationDrift on mismatch when STRICT=1');
});

test('_assert_host no-ops when expected_host is empty', () => {
  // Guard: if expected_host is falsy the function must return immediately.
  const m = PY_CONTENT.match(/async def _assert_host[\s\S]{0,600}?if not expected_host:\s*\n\s*return/);
  assert(m, '_assert_host must return early when expected_host is falsy');
});

test('idempotent adaptive: cmd_go checks current host before re-nav', () => {
  // Fix 3: the retry block must call _adaptive_current_host and skip
  // navigate_collect if the page is already on the expected host.
  assert(PY_CONTENT.includes('_adaptive_current_host(active_ws)'),
    'cmd_go retry must call _adaptive_current_host to check current host');
  assert(PY_CONTENT.includes('skip re-nav'),
    'cmd_go must log "skip re-nav" message when already on target host');
});

test('_new_isolated_context calls Target.createBrowserContext and Target.createTarget', () => {
  assert(PY_CONTENT.includes('"Target.createBrowserContext"'),
    '_new_isolated_context must issue Target.createBrowserContext');
  assert(PY_CONTENT.includes('"Target.createTarget"'),
    '_new_isolated_context must issue Target.createTarget');
  assert(PY_CONTENT.includes('async def _new_isolated_context'),
    '_new_isolated_context helper must be defined');
});

test('cmd_go uses isolated context when adaptive on and host is known-hostile', () => {
  // Fix 1: cmd_go must call _new_isolated_context when the conditions are met,
  // and dispose the context in a finally block.
  assert(PY_CONTENT.includes('_new_isolated_context(url)'),
    'cmd_go must call _new_isolated_context when adaptive + known-hostile');
  assert(PY_CONTENT.includes('ctx_id_to_dispose'),
    'cmd_go must track ctx_id_to_dispose for cleanup');
  const m = PY_CONTENT.match(/finally:[\s\S]{0,200}?_dispose_context\(ctx_id_to_dispose\)/);
  assert(m, 'cmd_go must dispose isolated context in finally block');
  assert(PY_CONTENT.includes('CDPILOT_ADAPTIVE_FRESH_CONTEXT'),
    'cmd_go must check CDPILOT_ADAPTIVE_FRESH_CONTEXT for isolation gate');
});

test('Fix 1 context spawn gated by CDPILOT_ADAPTIVE_FRESH_CONTEXT env var (default OFF)', () => {
  const re = /if cfg\['enabled'\] and is_known_hostile and os\.environ\.get\('CDPILOT_ADAPTIVE_FRESH_CONTEXT'\) == '1'/;
  assert(re.test(PY_CONTENT), 'cmd_go must gate isolation spawn with CDPILOT_ADAPTIVE_FRESH_CONTEXT == "1"');
});

test('_new_isolated_context and _dispose_context helpers exist for env-gated use', () => {
  assert(PY_CONTENT.includes('async def _new_isolated_context'),
    '_new_isolated_context helper must be defined');
  assert(PY_CONTENT.includes('async def _dispose_context'),
    '_dispose_context helper must be defined');
});

// ── v0.5.2 — Adaptive entropy auto-hook ──

test('CAPTCHA_ENTROPY_REQUIRED defined with correct CF=False, behavior-sensitive=True mapping', () => {
  assert(/CAPTCHA_ENTROPY_REQUIRED\s*=\s*\{/.test(PY_CONTENT),
    'CAPTCHA_ENTROPY_REQUIRED dict must be defined');
  // Cloudflare entries must be False
  assert(/['"]turnstile['"]\s*:\s*False/.test(PY_CONTENT),
    'turnstile must map to False (CF fingerprint-based, not mouse-sensitive)');
  assert(/['"]cloudflare-challenge['"]\s*:\s*False/.test(PY_CONTENT),
    'cloudflare-challenge must map to False');
  // Behavior-sensitive providers must be True
  assert(/['"]perimeterx['"]\s*:\s*True/.test(PY_CONTENT),
    'perimeterx must map to True (mouse-behavior-sensitive)');
  // v0.5.3: datadome OFF — bench data showed entropy adds latency, not mouse-behavior-based
  assert(/['"]datadome['"]\s*:\s*False/.test(PY_CONTENT),
    'datadome must map to False (v0.5.3: bench -2 tasks, TLS+JS challenge, not mouse-sensitive)');
  assert(/['"]hcaptcha['"]\s*:\s*True/.test(PY_CONTENT),
    'hcaptcha must map to True');
  assert(/['"]arkose['"]\s*:\s*True/.test(PY_CONTENT),
    'arkose must map to True');
  assert(/['"]geetest['"]\s*:\s*True/.test(PY_CONTENT),
    'geetest must map to True');
  assert(/['"]recaptcha['"]\s*:\s*True/.test(PY_CONTENT),
    'recaptcha must map to True');
  // TLS-based detectors — entropy irrelevant
  assert(/['"]kasada['"]\s*:\s*False/.test(PY_CONTENT),
    'kasada must map to False (TLS-based)');
  assert(/['"]shape['"]\s*:\s*False/.test(PY_CONTENT),
    'shape must map to False (TLS-based)');
});

test('_adaptive_remember_host_entropy defined and writes entropy_hosts to adaptive.json', () => {
  assert(/def _adaptive_remember_host_entropy\(hostname,\s*captcha_types\)/.test(PY_CONTENT),
    '_adaptive_remember_host_entropy must be defined');
  assert(/entropy_hosts/.test(PY_CONTENT),
    'adaptive.json must use entropy_hosts key');
  const m = PY_CONTENT.match(/def _adaptive_remember_host_entropy[\s\S]{0,600}?_atomic_write_json\(ADAPTIVE_CONFIG_FILE/);
  assert(m, '_adaptive_remember_host_entropy must persist via _atomic_write_json(ADAPTIVE_CONFIG_FILE)');
});

test('_entropy_enabled accepts host param and checks adaptive entropy_hosts', () => {
  assert(/def _entropy_enabled\(project_id=None,\s*host=None\)/.test(PY_CONTENT),
    '_entropy_enabled must accept host=None parameter');
  const m = PY_CONTENT.match(/def _entropy_enabled[\s\S]{0,400}?entropy_hosts[\s\S]{0,200}?get_entropy_config\(\)/);
  assert(m, '_entropy_enabled must check entropy_hosts and fall back to get_entropy_config()');
});

test('adaptive detect: calls _adaptive_remember_host_entropy with detected captcha_types', () => {
  const m = PY_CONTENT.match(/_adaptive_remember_host\(expected_host\)[\s\S]{0,400}?_adaptive_remember_host_entropy\(expected_host,\s*captcha_types\)/);
  assert(m, 'cmd_go must call _adaptive_remember_host_entropy after _adaptive_remember_host');
});

test('adaptive detect: no longer global-writes entropy.json (per-host instead)', () => {
  // Old behavior: _atomic_write_json(ENTROPY_CONFIG_FILE, ...) inside cmd_go adaptive block
  // New behavior: per-host via _adaptive_remember_host_entropy → adaptive.json
  // Extract cmd_go body up to the next top-level async def
  const cmdGoMatch = PY_CONTENT.match(/async def cmd_go\b[\s\S]*?(?=\nasync def |\ndef (?!_))/);
  const cmdGoBody = cmdGoMatch ? cmdGoMatch[0] : '';
  assert(cmdGoBody.length > 0, 'cmd_go must be findable in source');
  assert(!cmdGoBody.includes('_atomic_write_json(ENTROPY_CONFIG_FILE'),
    'cmd_go must not write global ENTROPY_CONFIG_FILE — per-host entropy_hosts replaces it');
});

test('cmd_click: ws obtained before entropy check (host-aware ordering)', () => {
  // ws must be assigned before _entropy_enabled is called so we can pass host
  const m = PY_CONTENT.match(/async def cmd_click[\s\S]{0,200}?ws,\s*_\s*=\s*get_page_ws\(\)[\s\S]{0,400}?_entropy_enabled\(_get_project_id\(\)/);
  assert(m, 'cmd_click must get_page_ws() before calling _entropy_enabled with host');
});

test('cmd_fill: ws obtained before entropy check (host-aware ordering)', () => {
  const m = PY_CONTENT.match(/async def cmd_fill[\s\S]{0,200}?ws,\s*_\s*=\s*get_page_ws\(\)[\s\S]{0,400}?_entropy_enabled\(_get_project_id\(\)/);
  assert(m, 'cmd_fill must get_page_ws() before calling _entropy_enabled with host');
});

test('cmd_hover and cmd_drag use host-aware _entropy_enabled', () => {
  const hoverM = PY_CONTENT.match(/async def cmd_hover[\s\S]{0,400}?_entropy_enabled\(_get_project_id\(\),\s*host=/);
  assert(hoverM, 'cmd_hover must call _entropy_enabled with host parameter');
  const dragM = PY_CONTENT.match(/async def cmd_drag[\s\S]{0,400}?_entropy_enabled\(_get_project_id\(\),\s*host=/);
  assert(dragM, 'cmd_drag must call _entropy_enabled with host parameter');
});

test('cmd_scroll_to uses host-aware _entropy_enabled', () => {
  const m = PY_CONTENT.match(/async def cmd_scroll_to[\s\S]{0,400}?_entropy_enabled\(_get_project_id\(\),\s*host=/);
  assert(m, 'cmd_scroll_to must call _entropy_enabled with host parameter');
});

// ── Captcha Solver Plugin (v0.6) ──

test('captcha: CAPTCHA_PROVIDERS_FILE points to CDPILOT_HOME', () => {
  assert(PY_CONTENT.includes("CAPTCHA_PROVIDERS_FILE = os.path.join(CDPILOT_HOME, 'captcha-providers.json')"),
    'CAPTCHA_PROVIDERS_FILE must be in CDPILOT_HOME (shared across projects)');
});

test('captcha: CAPTCHA_AUTO_FILE in PROFILE_DIR (per-project)', () => {
  assert(PY_CONTENT.includes("CAPTCHA_AUTO_FILE = os.path.join(PROFILE_DIR, 'captcha-auto.json')"),
    'CAPTCHA_AUTO_FILE must be per-project in PROFILE_DIR');
});

test('captcha: CaptchaSolverError defined', () => {
  assert(/class CaptchaSolverError\(Exception\)/.test(PY_CONTENT),
    'CaptchaSolverError must be a proper Exception subclass');
});

test('captcha: _captcha_load_config returns default dict on missing file', () => {
  assert(/def _captcha_load_config/.test(PY_CONTENT), '_captcha_load_config must exist');
  // Must handle FileNotFoundError gracefully
  assert(PY_CONTENT.includes('FileNotFoundError'), '_captcha_load_config must handle missing file');
});

test('captcha: _captcha_save_config uses atomic write and chmod 600', () => {
  assert(/def _captcha_save_config/.test(PY_CONTENT), '_captcha_save_config must exist');
  assert(PY_CONTENT.includes('_atomic_write_json(CAPTCHA_PROVIDERS_FILE'), '_captcha_save_config must use _atomic_write_json');
  assert(PY_CONTENT.includes('os.chmod(CAPTCHA_PROVIDERS_FILE, 0o600)'), '_captcha_save_config must chmod 600');
});

test('captcha: _solve_2captcha polls res.php every 5s', () => {
  const m = PY_CONTENT.match(/async def _solve_2captcha[\s\S]{0,2000}?2captcha\.com\/res\.php/);
  assert(m, '_solve_2captcha must poll 2captcha.com/res.php');
  const body = PY_CONTENT.match(/async def _solve_2captcha[\s\S]+?(?=\nasync def |\ndef (?!_))/);
  assert(body && body[0].includes('asyncio.sleep(5)'), '_solve_2captcha must use asyncio.sleep(5) for polling');
  assert(body && body[0].includes('CAPCHA_NOT_READY'), '_solve_2captcha must handle CAPCHA_NOT_READY response');
});

test('captcha: _solve_anticaptcha uses JSON API with createTask/getTaskResult', () => {
  const m = PY_CONTENT.match(/async def _solve_anticaptcha[\s\S]{0,2000}?anti-captcha\.com\/createTask/);
  assert(m, '_solve_anticaptcha must POST to api.anti-captcha.com/createTask');
  const body = PY_CONTENT.match(/async def _solve_anticaptcha[\s\S]+?(?=\nasync def |\ndef (?!_))/);
  assert(body && body[0].includes('getTaskResult'), '_solve_anticaptcha must poll getTaskResult');
  assert(body && body[0].includes("'status') == 'ready'"), "_solve_anticaptcha must check status == 'ready'");
});

test('captcha: _solve_capmonster uses capmonster.cloud base URL', () => {
  const m = PY_CONTENT.match(/async def _solve_capmonster[\s\S]{0,2000}?capmonster\.cloud/);
  assert(m, '_solve_capmonster must use api.capmonster.cloud');
});

test('captcha: provider preferred fallback (first enabled if preferred unavailable)', () => {
  const m = PY_CONTENT.match(/def _captcha_get_preferred_provider[\s\S]+?(?=\ndef |\nasync def )/);
  assert(m, '_captcha_get_preferred_provider must exist');
  assert(m[0].includes("preferred"), '_captcha_get_preferred_provider must check preferred provider');
  // Must have a fallback loop
  assert(m[0].includes('for pname'), '_captcha_get_preferred_provider must iterate providers as fallback');
});

test('captcha: _extract_site_key probes recaptcha, hcaptcha, turnstile selectors', () => {
  assert(/async def _extract_site_key/.test(PY_CONTENT), '_extract_site_key must exist');
  assert(PY_CONTENT.includes('g-recaptcha'), '_extract_site_key must probe recaptcha selector');
  assert(PY_CONTENT.includes('h-captcha'), '_extract_site_key must probe hcaptcha selector');
  assert(PY_CONTENT.includes('cf-turnstile'), '_extract_site_key must probe turnstile selector');
});

test('captcha: _inject_captcha_token handles recaptcha, hcaptcha, turnstile', () => {
  assert(/async def _inject_captcha_token/.test(PY_CONTENT), '_inject_captcha_token must exist');
  assert(PY_CONTENT.includes('g-recaptcha-response'), '_inject_captcha_token must handle recaptcha-v2 response field');
  assert(PY_CONTENT.includes('h-captcha-response'), '_inject_captcha_token must handle hcaptcha response field');
  assert(PY_CONTENT.includes('cf-turnstile-response'), '_inject_captcha_token must handle turnstile response field');
});

test('captcha: adaptive auto-solve hook fires in cmd_go after captcha detect', () => {
  const cmdGoBlock = PY_CONTENT.match(/async def cmd_go\b[\s\S]+?(?=\nasync def cmd_content)/);
  assert(cmdGoBlock, 'cmd_go must be findable');
  assert(cmdGoBlock[0].includes('_captcha_auto_solve_if_enabled'),
    'cmd_go must call _captcha_auto_solve_if_enabled when captcha is detected');
});

test('captcha: cmd_captcha_dispatch subcommand routing', () => {
  assert(/async def cmd_captcha_dispatch/.test(PY_CONTENT), 'cmd_captcha_dispatch must exist');
  const m = PY_CONTENT.match(/async def cmd_captcha_dispatch[\s\S]+?(?=\n# ─── End Captcha)/);
  assert(m, 'cmd_captcha_dispatch must be followed by End Captcha comment');
  assert(m[0].includes("'config'"), "cmd_captcha_dispatch must route 'config'");
  assert(m[0].includes("'solve'"), "cmd_captcha_dispatch must route 'solve'");
  assert(m[0].includes("'auto'"), "cmd_captcha_dispatch must route 'auto'");
  assert(m[0].includes("'status'"), "cmd_captcha_dispatch must route 'status'");
  assert(m[0].includes("'balance'"), "cmd_captcha_dispatch must route 'balance'");
});

test('captcha: captcha command in async_map dispatch table', () => {
  assert(PY_CONTENT.includes("'captcha': lambda: cmd_captcha_dispatch(args)"),
    "main() async_map must include 'captcha' -> cmd_captcha_dispatch");
});

// ── Per-host cookie persistence (v0.6) ──

test('COOKIES_DIR constant defined under CDPILOT_HOME', () => {
  assert(/COOKIES_DIR\s*=\s*os\.path\.join\(CDPILOT_HOME/.test(PY_CONTENT),
    "COOKIES_DIR must be os.path.join(CDPILOT_HOME, 'cookies')");
});

test('CF_CLEARANCE_COOKIES frozenset contains cf_clearance and __cf_bm', () => {
  const m = PY_CONTENT.match(/CF_CLEARANCE_COOKIES\s*=\s*frozenset\(\{[^}]+\}\)/);
  assert(m, "CF_CLEARANCE_COOKIES frozenset must be defined");
  assert(m[0].includes('cf_clearance'), "must include cf_clearance");
  assert(m[0].includes('__cf_bm'), "must include __cf_bm");
});

test('_cookies_safe_host replaces : and / with _', () => {
  const m = PY_CONTENT.match(/def _cookies_safe_host[\s\S]{0,200}?replace\(':',\s*'_'\)/);
  assert(m, "_cookies_safe_host must replace ':' with '_'");
});

test('_cookies_host_dir returns path under COOKIES_DIR', () => {
  const m = PY_CONTENT.match(/def _cookies_host_dir[\s\S]{0,200}?os\.path\.join\(COOKIES_DIR/);
  assert(m, "_cookies_host_dir must use os.path.join(COOKIES_DIR, ...)");
});

test('_save_host_cookies: atomic write + chmod 600 + returns path', () => {
  const body = PY_CONTENT.match(/def _save_host_cookies[\s\S]{0,1200}?def _/);
  assert(body, "_save_host_cookies must be present");
  assert(body[0].includes('_atomic_write_json'), "must use _atomic_write_json");
  assert(body[0].includes('0o600'), "must chmod 0o600");
  assert(body[0].includes('return f_path'), "must return file path");
});

test('_save_host_cookies: metadata contains cf_clearance_present and expires_soonest_unix', () => {
  const m = PY_CONTENT.match(/def _save_host_cookies[\s\S]{0,600}?cf_clearance_present[\s\S]{0,200}?expires_soonest_unix/);
  assert(m, "metadata must include cf_clearance_present and expires_soonest_unix");
});

test('_load_host_cookies: returns None on expiry', () => {
  const m = PY_CONTENT.match(/def _load_host_cookies[\s\S]{0,600}?expires_soonest_unix[\s\S]{0,200}?time\.time\(\)/);
  assert(m, "_load_host_cookies must check expires_soonest_unix < time.time()");
});

test('_load_host_cookies: returns None on OSError/ValueError', () => {
  const m = PY_CONTENT.match(/def _load_host_cookies[\s\S]{0,600}?except \(OSError, ValueError\)[\s\S]{0,100}?return None/);
  assert(m, "_load_host_cookies must catch OSError/ValueError and return None");
});

test('_cookies_auto_config reads COOKIES_AUTO_CONFIG_FILE (v0.6.1)', () => {
  const m = PY_CONTENT.match(/def _cookies_auto_config[\s\S]{0,500}?COOKIES_AUTO_CONFIG_FILE/);
  assert(m, "_cookies_auto_config must reference COOKIES_AUTO_CONFIG_FILE");
});

test('v0.6.1: _cookies_auto_should_apply gates by safe-host list', () => {
  const m = PY_CONTENT.match(/def _cookies_auto_should_apply[\s\S]{0,1000}?safe_hosts/);
  assert(m, "_cookies_auto_should_apply must check safe_hosts");
});

test('v0.6.1: cookies auto add/remove/list CLI subcommands', () => {
  const fnBody = PY_CONTENT.match(/async def cmd_cookies[\s\S]{0,15000}?(?=\nasync def |\ndef [a-z])/);
  assert(fnBody, "cmd_cookies function must be present");
  assert(fnBody[0].includes("'add'") && fnBody[0].includes('_cookies_auto_add_host'),
    "cookies auto add must call _cookies_auto_add_host");
  assert(fnBody[0].includes("'remove'") && fnBody[0].includes('_cookies_auto_remove_host'),
    "cookies auto remove must call _cookies_auto_remove_host");
  assert(fnBody[0].includes("'list'"), "cookies auto list subcommand required");
});

test('cmd_cookies: save --host mode writes per-host via _save_host_cookies', () => {
  // Check that per-host branch and _save_host_cookies both appear in cmd_cookies body
  const fnBody = PY_CONTENT.match(/async def cmd_cookies[\s\S]{0,12000}?(?=\nasync def |\ndef [a-z])/);
  assert(fnBody, "cmd_cookies function must be present");
  assert(fnBody[0].includes("'--host'") && fnBody[0].includes('_save_host_cookies'),
    "cookies save --host must call _save_host_cookies");
});

test('cmd_cookies: load --host mode calls _load_host_cookies', () => {
  const m = PY_CONTENT.match(/sub == 'load'[\s\S]{0,300}?--host[\s\S]{0,300}?_load_host_cookies/);
  assert(m, "cookies load --host must call _load_host_cookies");
});

test('cmd_cookies: list subcommand lists COOKIES_DIR', () => {
  const m = PY_CONTENT.match(/sub == 'list'[\s\S]{0,600}?COOKIES_DIR/);
  assert(m, "cookies list must read COOKIES_DIR");
});

test('cmd_cookies: clear --all removes entire COOKIES_DIR', () => {
  const m = PY_CONTENT.match(/--all[\s\S]{0,200}?shutil\.rmtree\(COOKIES_DIR/);
  assert(m, "cookies clear --all must shutil.rmtree(COOKIES_DIR)");
});

test('cmd_cookies: auto on|off toggles _set_cookies_auto', () => {
  const m = PY_CONTENT.match(/sub == 'auto'[\s\S]{0,400}?_set_cookies_auto/);
  assert(m, "cookies auto must call _set_cookies_auto");
});

test('cmd_cookies: cf-replay injects cookies via Network.setCookies', () => {
  const m = PY_CONTENT.match(/sub == 'cf-replay'[\s\S]{0,800}?Network\.setCookies/);
  assert(m, "cookies cf-replay must inject via Network.setCookies");
});

test('cmd_go: auto pre-navigate hook injects cached cookies (v0.6.1 safe-host gated)', () => {
  const m = PY_CONTENT.match(/COOKIES AUTO PRE-NAVIGATE[\s\S]{0,500}?_cookies_auto_should_apply[\s\S]{0,300}?_load_host_cookies/);
  assert(m, "cmd_go must have COOKIES AUTO PRE-NAVIGATE hook gated by _cookies_auto_should_apply");
});

test('cmd_go: auto post-navigate hook saves cookies after navigation (v0.6.1 safe-host gated)', () => {
  const m = PY_CONTENT.match(/COOKIES AUTO POST-NAVIGATE[\s\S]{0,800}?_cookies_auto_should_apply[\s\S]{0,400}?_save_host_cookies/);
  assert(m, "cmd_go must have COOKIES AUTO POST-NAVIGATE hook gated by _cookies_auto_should_apply");
});

test('cmd_cookies: clear --older-than guards against missing COOKIES_DIR', () => {
  const m = PY_CONTENT.match(/--older-than[\s\S]{0,200}?os\.path\.exists\(COOKIES_DIR\)/);
  assert(m, "clear --older-than must guard with os.path.exists(COOKIES_DIR)");
});

// ── v0.8.0: TLS fingerprint awareness ──

test('v0.8.0: BROWSER_BINARIES does NOT include camoufox/undetected-chrome (CDP incompatible)', () => {
  const m = PY_CONTENT.match(/BROWSER_BINARIES\s*=\s*\{[\s\S]{0,4000}?\n\}/);
  assert(m, 'BROWSER_BINARIES dict must be present');
  assert(!m[0].includes("'camoufox'"), 'camoufox is Firefox+Juggler — incompatible with cdpilot CDP');
  assert(!m[0].includes("'undetected-chrome'"), 'undetected-chrome is a Python lib, not a binary');
});

test('v0.8.0: cmd_tls_check defined and probes via navigate_collect', () => {
  assert(PY_CONTENT.includes('async def cmd_tls_check'), 'cmd_tls_check must be defined');
  const m = PY_CONTENT.match(/async def cmd_tls_check[\s\S]{0,5000}?(?=\nasync def |\ndef [a-z])/);
  assert(m, 'cmd_tls_check body required');
  assert(/navigate_collect/.test(m[0]), 'cmd_tls_check must use navigate_collect');
  assert(/tls\.peet\.ws|browserleaks/.test(m[0]), 'cmd_tls_check must reference a known echo service');
  assert(/ja3|JA3/.test(m[0]), 'cmd_tls_check must extract JA3');
  assert(/ja4|JA4/.test(m[0]), 'cmd_tls_check must extract JA4');
});

test('v0.8.0: KNOWN_CHROME_TLS comparison set defined', () => {
  assert(/KNOWN_CHROME_TLS\s*=/.test(PY_CONTENT), 'KNOWN_CHROME_TLS must exist for verdict logic');
});

test('v0.8.0: tls-check registered in async dispatch table', () => {
  assert(/"tls-check":\s*lambda/.test(PY_CONTENT), 'tls-check must be in async_map');
});

// ── v0.7.0: residential proxy framework ──

test('v0.7.0: _proxy_config_raw + named pool helpers exist', () => {
  assert(PY_CONTENT.includes('def _proxy_config_raw'), '_proxy_config_raw must be defined');
  assert(PY_CONTENT.includes('def _proxy_pools'), '_proxy_pools must be defined');
  assert(PY_CONTENT.includes('def _proxy_active_name'), '_proxy_active_name must be defined');
  assert(PY_CONTENT.includes('def _proxy_add_pool'), '_proxy_add_pool must be defined');
  assert(PY_CONTENT.includes('def _proxy_remove_pool'), '_proxy_remove_pool must be defined');
  assert(PY_CONTENT.includes('def _proxy_set_active'), '_proxy_set_active must be defined');
});

test('v0.7.0: get_proxy_config returns active pool URL over legacy', () => {
  const m = PY_CONTENT.match(/def get_proxy_config[\s\S]{0,1500}?(?=\ndef )/);
  assert(m, 'get_proxy_config body must be present');
  assert(/active[\s\S]{0,400}?pools/.test(m[0]), 'must consult active pool from pools dict');
  assert(/CHROME_PROXY/.test(m[0]), 'env override must still work');
});

test('v0.7.0: _proxy_redact masks credentials in URL', () => {
  assert(PY_CONTENT.includes('def _proxy_redact'), '_proxy_redact must be defined');
  const m = PY_CONTENT.match(/def _proxy_redact[\s\S]{0,1000}?(?=\ndef )/);
  assert(m, '_proxy_redact body required');
  assert(/\*\*\*/.test(m[0]), 'must replace credentials with ***');
});

test('v0.7.0: cmd_proxy supports add/remove/use/list/show subcommands', () => {
  const m = PY_CONTENT.match(/def cmd_proxy[\s\S]{0,8000}?(?=\ndef )/);
  assert(m, 'cmd_proxy body required');
  for (const sub of ["'add'", "'remove'", "'use'", "'list'", "'show'", "'off'"]) {
    assert(m[0].includes(sub), `cmd_proxy must handle ${sub}`);
  }
  assert(/--geo/.test(m[0]), 'cmd_proxy must accept --geo flag');
  assert(/--sticky/.test(m[0]), 'cmd_proxy must accept --sticky flag');
});

test('v0.7.0: proxy command dispatched with *args', () => {
  assert(/'proxy':\s*lambda:\s*cmd_proxy\(\*args\)/.test(PY_CONTENT),
    "'proxy' must dispatch with *args (legacy single-url form still works)");
});

// ── v0.6.2: cmd_wipe (per-task state hygiene) ──

test('v0.6.2: cmd_wipe defined with --all/--keep/--cookies/--storage/--tabs flags', () => {
  assert(PY_CONTENT.includes('async def cmd_wipe'), 'cmd_wipe must be defined');
  const m = PY_CONTENT.match(/async def cmd_wipe[\s\S]{0,5000}?(?=\nasync def |\ndef [a-z])/);
  assert(m, 'cmd_wipe body must be present');
  assert(m[0].includes("'--all'"), 'wipe must support --all');
  assert(m[0].includes("'--keep'"), 'wipe must support --keep');
  assert(m[0].includes("'--cookies'"), 'wipe must support --cookies');
  assert(m[0].includes("'--storage'"), 'wipe must support --storage');
  assert(m[0].includes("'--tabs'"), 'wipe must support --tabs');
});

test('v0.6.2: cmd_wipe preserves cookies-auto safe-list by default', () => {
  const m = PY_CONTENT.match(/async def cmd_wipe[\s\S]{0,5000}?_cookies_auto_config/);
  assert(m, 'cmd_wipe must consult _cookies_auto_config for safe-list');
});

test('v0.6.2: cmd_wipe uses Network.deleteCookies + Storage.clearDataForOrigin', () => {
  const m = PY_CONTENT.match(/async def cmd_wipe[\s\S]{0,5000}?Network\.deleteCookies[\s\S]{0,2000}?Storage\.clearDataForOrigin/);
  assert(m, 'cmd_wipe must use Network.deleteCookies and Storage.clearDataForOrigin');
});

test('v0.6.2: wipe command registered in async dispatch table', () => {
  assert(/"wipe":\s*lambda/.test(PY_CONTENT), 'wipe must be in async_map');
});

// ── smart-click / smart-fill / smart-select: disabled, shadow DOM, locale, label heuristics ──
//
// These tests are static-analysis only (same style as the STEALTH_JS tests
// above). They verify that the rendered JS template contains the right
// guards — the *behavior* of those guards is exercised by the e2e smoke
// suite and live bench runs, not here.

function extractCmdBody(src, funcName) {
  // Capture from `async def cmd_X` up to the next top-level `async def ` /
  // `def ` definition. The next-def regex accepts underscore-prefixed
  // helpers (`_dismiss_js_template`) and any-case identifier so we don't
  // accidentally swallow neighbouring functions into the body.
  const re = new RegExp('async def ' + funcName + '[\\s\\S]*?(?=\\nasync def |\\ndef [A-Za-z_])', 'm');
  const m = src.match(re);
  return m ? m[0] : null;
}

const SMART_CLICK_BODY = extractCmdBody(PY_CONTENT, 'cmd_smart_click');
const SMART_FILL_BODY = extractCmdBody(PY_CONTENT, 'cmd_smart_fill');
const SMART_SELECT_BODY = extractCmdBody(PY_CONTENT, 'cmd_smart_select');

test('smart_click: skips disabled buttons', () => {
  // The disabled check must run inside the candidate-scoring loop, otherwise
  // a disabled <button>Login</button> still ends up as the top match and we
  // silently click nothing.
  assert(SMART_CLICK_BODY, 'cmd_smart_click body must be extractable');
  assert(/el\.disabled\s*===\s*true/.test(SMART_CLICK_BODY),
    'smart_click must check el.disabled === true');
  assert(/aria-disabled['"]\s*\)\s*===\s*['"]true/.test(SMART_CLICK_BODY),
    'smart_click must check aria-disabled === "true"');
  assert(/fieldset\[disabled\]/.test(SMART_CLICK_BODY),
    'smart_click must check fieldset[disabled] ancestor');
  assert(/disabledCount/.test(SMART_CLICK_BODY),
    'smart_click must track disabledCount to distinguish "no match" from "all disabled"');
});

test('smart_click: errors when all matches disabled', () => {
  // When candidates are empty but disabledCount > 0, the Python side must
  // emit a specific error so callers can tell a timing bug from a missing
  // element.
  assert(/allDisabled/.test(SMART_CLICK_BODY),
    'smart_click JS must return allDisabled in not-found payload');
  assert(/no enabled element matches/.test(SMART_CLICK_BODY),
    'smart_click Python must print "no enabled element matches" error');
});

test('smart_click: deepQuerySelectorAll traverses shadow root', () => {
  // Without shadow DOM traversal, Salesforce Lightning / Polymer custom
  // widgets are invisible to smart-click. The helper must recurse into
  // every open shadowRoot.
  assert(/function deepQuerySelectorAll/.test(SMART_CLICK_BODY),
    'smart_click must define deepQuerySelectorAll');
  assert(/el\.shadowRoot/.test(SMART_CLICK_BODY),
    'smart_click traversal must inspect el.shadowRoot');
  assert(/deepQuerySelectorAll\(document,/.test(SMART_CLICK_BODY),
    'smart_click must call deepQuerySelectorAll(document, ...) instead of document.querySelectorAll');
});

test('smart_fill: deepQuerySelectorAll for shadow inputs', () => {
  // Lightning / Polymer / lit-element form controls expose <input> only
  // through their shadow root — smart-fill must walk in.
  assert(SMART_FILL_BODY, 'cmd_smart_fill body must be extractable');
  assert(/function deepQuerySelectorAll/.test(SMART_FILL_BODY),
    'smart_fill must define deepQuerySelectorAll');
  assert(/deepQuerySelectorAll\(document,\s*\n?\s*'input,/.test(SMART_FILL_BODY),
    'smart_fill must call deepQuerySelectorAll for input/textarea/select');
});

test('smart_click: Turkish İ matches lowercase i (locale-aware lowercase)', () => {
  // `'İ'.toLowerCase()` yields `'i̇'` (i + combining dot) in some
  // engines, which breaks `===` against `'i'`. `toLocaleLowerCase()` is the
  // ICU-backed path that produces `'i'`.
  //
  // The check ignores `tagName.toLowerCase()` (HTML tag names are pure
  // ASCII — "BUTTON" → "button" is safe under any folding) and string
  // contents inside `//` line comments.
  assert(/toLocaleLowerCase\(\)/.test(SMART_CLICK_BODY),
    'smart_click must use toLocaleLowerCase() (not toLowerCase) for Turkish/German safety');
  const lines = SMART_CLICK_BODY.split('\n');
  const offenders = lines.filter(l => {
    if (/^\s*\/\//.test(l)) return false;             // strip JS line comments
    if (!/\.toLowerCase\(\)/.test(l)) return false;
    if (/tagName\.toLowerCase\(\)/.test(l)) return false; // tag names are ASCII
    return true;
  });
  assert.strictEqual(offenders.length, 0,
    'smart_click must NOT use plain .toLowerCase() on user-visible text — offenders: ' +
      JSON.stringify(offenders));
});

test('smart_click: German ß matches (locale-aware lowercase used everywhere)', () => {
  // The fix is the same as Turkish — locale-aware folding. We assert the
  // helper exists and is used in both score() and the candidate text walk.
  assert(/function lc\(s\)/.test(SMART_CLICK_BODY),
    'smart_click must define lc() locale-aware helper');
  // lc() must be the one wrapping the search term going in
  assert(/lc\(\{safe_text\}|search\s*=\s*lc\(/.test(SMART_CLICK_BODY) ||
    /var search = lc/.test(SMART_CLICK_BODY),
    'smart_click must apply lc() to the search term');
});

test('smart_fill: aria-labelledby lookup', () => {
  // Material UI / Ant Design / Chakra often wire the label via
  // aria-labelledby instead of <label for>. Without this fallback their
  // inputs are unreachable.
  assert(/aria-labelledby/.test(SMART_FILL_BODY),
    'smart_fill must read aria-labelledby attribute');
  assert(/getElementById\(id\)/.test(SMART_FILL_BODY),
    'smart_fill must dereference aria-labelledby IDs via getElementById');
});

test('smart_fill: nested aria-label closest()', () => {
  // Floating-label designs wrap the input in a container that carries the
  // aria-label. `closest('[aria-label]')` finds that container.
  assert(/closest\(['"]\[aria-label\]['"]\)/.test(SMART_FILL_BODY),
    'smart_fill must use closest("[aria-label]") for ancestor lookup');
  // Also: nearby label scan (4 prev siblings) for floating-label widgets
  assert(/previousElementSibling/.test(SMART_FILL_BODY),
    'smart_fill must walk previousElementSibling for nearby labels');
});

// ── Cross-cutting hardening for smart-select ──

test('smart_select: also gets disabled + shadow + locale hardening', () => {
  // smart-select is the third "smart" command and silently inherits the
  // same bug surface — calling .value on a disabled <select> is a no-op,
  // <select>s can live in shadow roots, and option text uses non-Latin
  // characters all the time (country pickers).
  assert(SMART_SELECT_BODY, 'cmd_smart_select body must be extractable');
  assert(/function deepQuerySelectorAll/.test(SMART_SELECT_BODY),
    'smart_select must define deepQuerySelectorAll');
  assert(/toLocaleLowerCase\(\)/.test(SMART_SELECT_BODY),
    'smart_select must use toLocaleLowerCase()');
  assert(/sel\.disabled\s*===\s*true/.test(SMART_SELECT_BODY),
    'smart_select must check sel.disabled === true');
});

// ── v0.9: cdpilot watch (continuous screencast for AI video understanding) ──

test('v0.9 watch: cmd_watch_start defined and registered in sync dispatch', () => {
  assert(PY_CONTENT.includes('def cmd_watch_start('), 'cmd_watch_start must be defined');
  assert(/'watch':\s*lambda:\s*_dispatch_watch_cmd\(args\)/.test(PY_CONTENT),
    "'watch' must dispatch via _dispatch_watch_cmd in sync_cmds");
});

test('v0.9 watch: daemon entry sends Page.startScreencast with correct params', () => {
  const m = PY_CONTENT.match(/async def _watch_daemon_run[\s\S]{0,8000}?(?=\ndef |\nasync def )/);
  assert(m, '_watch_daemon_run body must be present');
  assert(/Page\.startScreencast/.test(m[0]), 'must invoke Page.startScreencast');
  assert(/"format":\s*"jpeg"/.test(m[0]), 'must request JPEG format');
  assert(/everyNthFrame/.test(m[0]), 'must set everyNthFrame for fps control');
  assert(/Page\.screencastFrameAck/.test(m[0]), 'must ACK frames (else CDP stalls)');
  assert(/maxWidth/.test(m[0]), 'must constrain max frame width');
  assert(/quality/i.test(m[0]), 'must pass JPEG quality');
});

test('v0.9 watch: frames written to per-project ring buffer dir as <ts_ms>.jpg', () => {
  const m = PY_CONTENT.match(/async def _watch_daemon_run[\s\S]{0,8000}?(?=\ndef |\nasync def )/);
  assert(m, '_watch_daemon_run body required');
  // <unix_ms>.jpg naming + write to frames dir
  assert(/\{ts_ms\}\.jpg/.test(m[0]), 'frame filename must be <ts_ms>.jpg');
  assert(/_watch_frames_dir|frames_dir|fdir/.test(m[0]), 'must write under frames dir');
  assert(/base64\.b64decode/.test(m[0]), 'must decode the screencast payload');
  // Ring buffer dir helper points under ~/.cdpilot/projects/<pid>/watch/frames
  const fdMatch = PY_CONTENT.match(/def _watch_frames_dir[\s\S]{0,300}?(?=\ndef )/);
  assert(fdMatch, '_watch_frames_dir helper required');
  assert(/['"]frames['"]/.test(fdMatch[0]), 'ring buffer subdir must be "frames"');
});

test('v0.9 watch: cmd_watch_query filters by --at/--window and --last/--since-last', () => {
  const m = PY_CONTENT.match(/def cmd_watch_query[\s\S]{0,8000}?(?=\ndef |\nasync def )/);
  assert(m, 'cmd_watch_query body required');
  for (const flag of ["'--at'", "'--at='", "'--window'", "'--last'", "'--since-last'", "'--max'"]) {
    assert(m[0].includes(flag), `cmd_watch_query must parse ${flag}`);
  }
  // Time-window arithmetic: center_ms = sc_start + at*1000, plus/minus half window
  assert(/center_ms/.test(m[0]) && /half_ms/.test(m[0]),
    'must compute center+half-window for --at queries');
});

test('v0.9 watch: ring buffer evicts frames older than retention OR over disk cap', () => {
  const m = PY_CONTENT.match(/def _watch_evict[\s\S]{0,3000}?(?=\ndef )/);
  assert(m, '_watch_evict body required');
  assert(/cutoff_ms/.test(m[0]), 'must compute time-based cutoff');
  assert(/disk_cap_bytes/.test(m[0]), 'must enforce disk cap');
  assert(/total\s*>\s*disk_cap_bytes/.test(m[0]),
    'must evict oldest-first until under disk cap');
  assert(/os\.remove/.test(m[0]), 'must actually delete evicted files');
});

test('v0.9 watch: cmd_watch_status returns frame count + disk usage as JSON', () => {
  const m = PY_CONTENT.match(/def cmd_watch_status[\s\S]{0,2000}?(?=\ndef )/);
  assert(m, 'cmd_watch_status body required');
  assert(/['"]running['"]/.test(m[0]), 'status JSON must include "running" flag');
  assert(/['"]frames['"]/.test(m[0]), 'status JSON must include "frames" count');
  assert(/disk_bytes|disk_mb/.test(m[0]), 'status JSON must include disk usage');
  assert(/_watch_pid_alive/.test(m[0]), 'must probe daemon pid for liveness');
});

test('v0.9 watch: cmd_watch_query emits JSON with frame paths + timestamps + count', () => {
  const m = PY_CONTENT.match(/def cmd_watch_query[\s\S]{0,8000}?(?=\ndef |\nasync def )/);
  assert(m, 'cmd_watch_query body required');
  assert(/['"]frames['"]/.test(m[0]), 'query output must include frames key');
  assert(/['"]count['"]/.test(m[0]), 'query output must include count key');
  assert(/['"]timestamps_ms['"]/.test(m[0]), 'query output must include timestamps_ms');
  assert(/json\.dumps/.test(m[0]), 'query must print JSON');
});

test('v0.9 watch: daemon is forked via subprocess.Popen with hidden flag (no blocking)', () => {
  const m = PY_CONTENT.match(/def cmd_watch_start[\s\S]{0,6000}?(?=\ndef )/);
  assert(m, 'cmd_watch_start body required');
  assert(/subprocess\.Popen/.test(m[0]),
    'cmd_watch_start must Popen a daemon (foreground returns immediately)');
  assert(/WATCH_DAEMON_FLAG/.test(m[0]), 'must use the hidden --_watch-daemon flag');
  assert(/start_new_session=True/.test(m[0]),
    'daemon must detach from controlling terminal');
  // And the re-entrant flag must be handled at __main__ before sync_cmds
  assert(PY_CONTENT.includes("WATCH_DAEMON_FLAG = '--_watch-daemon'"),
    'WATCH_DAEMON_FLAG constant must exist');
  assert(/if cmd == WATCH_DAEMON_FLAG/.test(PY_CONTENT),
    '__main__ must short-circuit into daemon mode on the hidden flag');
});

test('v0.9 watch: MCP server exposes browser_watch_* tools', () => {
  for (const tool of [
    '"browser_watch_start"',
    '"browser_watch_stop"',
    '"browser_watch_query"',
    '"browser_watch_status"',
  ]) {
    assert(PY_CONTENT.includes(tool), `MCP tools list must contain ${tool}`);
  }
  // Tool router maps must be present
  assert(/"browser_watch_start":\s*lambda a:/.test(PY_CONTENT),
    'tool_map must route browser_watch_start to the CLI');
  assert(/"browser_watch_query":\s*lambda a:/.test(PY_CONTENT),
    'tool_map must route browser_watch_query to the CLI');
});

test('v0.9 watch: CLI smoke — `watch status` works with no active session', () => {
  const out = run('watch status');
  // Should emit valid JSON with running:false (no daemon = no error)
  assert(/"running":\s*false/.test(out), `status must report not-running, got: ${out}`);
  assert(/"frames":\s*0/.test(out), 'status frames count must be 0 when empty');
});

test('v0.9 watch: CLI smoke — `watch query` without a session returns empty + error key', () => {
  const out = run('watch query --at 0:01 --window 1s');
  assert(/"frames":\s*\[\]/.test(out), 'query must emit empty frames list');
  assert(/no watch session/.test(out), 'query must surface "no watch session" hint');
});

// ── Three-tier stealth mode (regular | stealth | undetected) ──

test('mode: cmd_mode defined + dispatched', () => {
  assert(/def cmd_mode\(/.test(PY_CONTENT), 'cmd_mode must be defined');
  assert(/'mode':\s*lambda:\s*cmd_mode\(/.test(PY_CONTENT),
    'mode must be wired into the sync_cmds dispatch table');
});

test('mode: regular tier injects no fingerprint patch', () => {
  // stealth_js_for_tier('regular') must return None so navigate injects nothing.
  assert(/def stealth_js_for_tier\(tier\):/.test(PY_CONTENT),
    'stealth_js_for_tier resolver must exist');
  const re = /def stealth_js_for_tier\(tier\):[\s\S]*?\n\n\ndef /;
  const m = PY_CONTENT.match(re);
  assert(m, 'should extract stealth_js_for_tier body');
  assert(/return None/.test(m[0]), "regular tier must fall through to return None");
  // navigate_collect must only inject when a source is returned (truthy).
  assert(/stealth_source = stealth_js_for_tier\(get_mode_config\(\)\)/.test(PY_CONTENT),
    'navigate_collect must select the stealth source via tier');
  assert(/if stealth_source:/.test(PY_CONTENT),
    'navigate_collect must guard injection on a truthy source (regular = no inject)');
});

test('mode: stealth tier uses STEALTH_JS_LIGHT (no plugin array)', () => {
  assert(/STEALTH_JS_LIGHT = r"""/.test(PY_CONTENT), 'STEALTH_JS_LIGHT must be defined');
  const re = /def stealth_js_for_tier\(tier\):[\s\S]*?\n\n\ndef /;
  const body = PY_CONTENT.match(re)[0];
  assert(/if tier == 'stealth':\s*\n\s*return STEALTH_JS_LIGHT/.test(body),
    "stealth tier must resolve to STEALTH_JS_LIGHT");
});

test('mode: undetected tier uses STEALTH_JS_FULL', () => {
  assert(/STEALTH_JS_FULL = r"""/.test(PY_CONTENT), 'STEALTH_JS_FULL must be defined');
  const re = /def stealth_js_for_tier\(tier\):[\s\S]*?\n\n\ndef /;
  const body = PY_CONTENT.match(re)[0];
  assert(/if tier == 'undetected':\s*\n\s*return STEALTH_JS_FULL/.test(body),
    "undetected tier must resolve to STEALTH_JS_FULL");
  // STEALTH_JS legacy alias must point at the FULL body.
  assert(/STEALTH_JS = STEALTH_JS_FULL/.test(PY_CONTENT),
    'STEALTH_JS must alias STEALTH_JS_FULL for backward compatibility');
});

test('mode: STEALTH_JS_LIGHT excludes plugin spoofing', () => {
  const light = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_LIGHT');
  assert(light, 'STEALTH_JS_LIGHT body should be extractable');
  // Light tier is the SAFE subset — bench proved the synthetic plugin array
  // is itself a leak (bot.sannysoft.com garbage filenames).
  assert(!/PluginArray/.test(light), 'LIGHT must NOT spoof navigator.plugins (bench leak)');
  assert(!/makePlugin/.test(light), 'LIGHT must NOT build fake Plugin objects');
  assert(!/internal-pdf-viewer/.test(light), 'LIGHT must NOT inject fake PDF plugin filenames');
  assert(!/37445/.test(light), 'LIGHT must NOT override WebGL vendor');
  // But it MUST keep the safe subset.
  assert(/'webdriver'/.test(light), 'LIGHT must still patch navigator.webdriver');
  assert(/chrome\.runtime/.test(light), 'LIGHT must still patch chrome.runtime');
  assert(/permissions\.query/.test(light), 'LIGHT must still reconcile permissions.query');
  // Light must be syntactically valid JS.
  const vm = require('vm');
  assert.doesNotThrow(() => new vm.Script(light), 'STEALTH_JS_LIGHT should parse as valid JS');
  // The FULL body, by contrast, MUST still spoof plugins.
  const full = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(/PluginArray/.test(full), 'FULL tier must keep the plugin spoof');
});

test('mode: backwards-compat — stealth on maps to undetected', () => {
  // get_mode_config must treat the legacy stealth toggle as undetected when
  // no explicit mode is set, and cmd_stealth must bridge to set_mode_config.
  assert(/return 'undetected' if get_stealth_config\(\) else DEFAULT_MODE_TIER/.test(PY_CONTENT),
    'get_mode_config must map legacy stealth-on to undetected');
  assert(/set_mode_config\('undetected' if enabled else 'regular'\)/.test(PY_CONTENT),
    'cmd_stealth must keep mode.json coherent (on->undetected, off->regular)');
});

// ── Headless UA override (stealth + undetected only) ──
// Measured 2026-09-27: every tier leaked "HeadlessChrome" (header + navigator),
// failing sannysoft User Agent / HEADCHR_UA / CHR_MEMORY and incolumitas intoli
// userAgent. The stealth tiers now override it on the navigate session; the
// regular tier ("no patches") must never send it.

function extractPyFunc(src, name) {
  const re = new RegExp(`\\n((?:async )?def ${name}\\([\\s\\S]*?)(?=\\n\\n\\n)`);
  const m = src.match(re);
  return m ? m[1] : null;
}

const NAV_COLLECT_BODY = (PY_CONTENT.match(/async def navigate_collect\([\s\S]*?\n(?=async def |def )/) || [''])[0];

test('stealth UA: stealth/undetected navigate path calls the headless UA override', () => {
  // The override lives INSIDE the `if stealth_source:` block (stealth -> LIGHT,
  // undetected -> FULL), on the same WS as the stealth script.
  const m = NAV_COLLECT_BODY.match(/\n(\s+)if stealth_source:\n([\s\S]*?)\n\n/);
  assert(m, 'navigate_collect must keep an `if stealth_source:` block');
  assert(/await apply_headless_ua_override\(ws\)/.test(m[2]),
    'the stealth_source block must call apply_headless_ua_override(ws)');
  assert(/addScriptToEvaluateOnNewDocument/.test(m[2]),
    'the UA override must sit next to the stealth script registration (same session)');
});

test('stealth UA: regular tier never reaches the UA override', () => {
  // regular -> stealth_js_for_tier() returns None -> the guarded block is skipped.
  // So the ONLY call site in the whole file must be the guarded one.
  const code = PY_CONTENT.split('\n').map((l) => l.replace(/#.*$/, '')).join('\n');
  const calls = code.match(/await apply_headless_ua_override\(/g) || [];
  assert.strictEqual(calls.length, 1, `exactly one call site expected, found ${calls.length}`);
  const guard = NAV_COLLECT_BODY.indexOf('if stealth_source:');
  const call = NAV_COLLECT_BODY.indexOf('await apply_headless_ua_override(');
  assert(guard > 0 && call > guard, 'the call must come after (inside) the stealth_source guard');
  const tierFn = extractPyFunc(PY_CONTENT, 'stealth_js_for_tier');
  assert(tierFn && /return None/.test(tierFn), 'regular must still resolve to None (no patch, no override)');
});

test('stealth UA: override is headless-gated, reads Browser.getVersion, sends metadata', () => {
  const fn = extractPyFunc(PY_CONTENT, 'apply_headless_ua_override');
  assert(fn, 'apply_headless_ua_override must exist');
  assert(/"Browser\.getVersion"/.test(fn), 'real UA must come from Browser.getVersion (no hard-coded version)');
  assert(/headless_ua_rewrite\(real_ua\)/.test(fn), 'UA must go through headless_ua_rewrite');
  assert(/if not new_ua or new_ua == real_ua:\s*\n\s*return None/.test(fn),
    'headed browser (no HeadlessChrome token) must send no override at all');
  assert(/"Emulation\.setUserAgentOverride"/.test(fn), 'must use Emulation.setUserAgentOverride');
  assert(/"userAgentMetadata"/.test(fn),
    'must pass userAgentMetadata (without it navigator.userAgentData.brands is emptied)');
  assert(/except Exception:\s*\n\s*return None\s*$/.test(fn), 'must never raise into navigation');
});

test('stealth UA: headless_ua_rewrite / brand rewrite / GREASE list (pure)', () => {
  const { execFileSync } = require('child_process');
  const PY_BIN = process.platform === 'win32' ? 'python' : 'python3';
  const fns = ['headless_ua_rewrite', 'headless_brand_rewrite', 'grease_brand_list']
    .map((n) => extractPyFunc(PY_CONTENT, n));
  fns.forEach((f, i) => assert(f, `function #${i} must be extractable`));
  const out = execFileSync(PY_BIN, ['-c', fns.join('\n\n') + `
import json
H = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/154.0.0.0 Safari/537.36'
C = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36'
F = 'Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0'
def names(l): return [b['brand'] + '/' + b['version'] for b in l]
print(json.dumps({
  'headless': headless_ua_rewrite(H), 'chrome': headless_ua_rewrite(C),
  'firefox': headless_ua_rewrite(F), 'none': headless_ua_rewrite(None),
  'brands': names(headless_brand_rewrite([{'brand': 'HeadlessChrome', 'version': '138'},
                                          {'brand': 'Chromium', 'version': '138'}])),
  'g120': names(grease_brand_list(120, 'Google Chrome')),
  'g124': names(grease_brand_list(124, 'Google Chrome')),
  'g131': names(grease_brand_list(131, 'Google Chrome')),
  'g154': names(grease_brand_list(154, 'Brave', '154.0.0.0')),
}))
`], { encoding: 'utf-8', timeout: 5000 });
  const r = JSON.parse(out.trim());
  const C = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36';
  assert.strictEqual(r.headless, C, 'HeadlessChrome/154 must become Chrome/154, rest untouched');
  assert.strictEqual(r.chrome, C, 'a UA with no Headless token must come back unchanged');
  assert.strictEqual(r.firefox, 'Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0',
    'non-Chrome UA must come back unchanged');
  assert.strictEqual(r.none, null, 'None passes through');
  assert.deepStrictEqual(r.brands, ['Google Chrome/138', 'Chromium/138'],
    'HeadlessChrome brand -> Google Chrome, others kept');
  // Real Sec-CH-UA values (Chrome 120/124/131 headers; 154 = this Brave, measured).
  assert.deepStrictEqual(r.g120, ['Not_A Brand/8', 'Chromium/120', 'Google Chrome/120']);
  assert.deepStrictEqual(r.g124, ['Chromium/124', 'Google Chrome/124', 'Not-A.Brand/99']);
  assert.deepStrictEqual(r.g131, ['Google Chrome/131', 'Chromium/131', 'Not_A Brand/24']);
  assert.deepStrictEqual(r.g154, ['Chromium/154.0.0.0', 'Brave/154.0.0.0', 'Not A(Brand/99.0.0.0']);
});

test('stealth UA: FULL plugin item() coerces like WebIDL unsigned long (overflowTest)', () => {
  const full = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(/plugins\.item = function\(i\) \{ return plugins\[i >>> 0\] \|\| null; \};/.test(full),
    'PluginArray.item must use i >>> 0 (native item(4294967296) === item(0))');
  assert(/p\.item = function\(i\) \{ return \(i >>> 0\) === 0 \? mime : null; \};/.test(full),
    'Plugin.item must use i >>> 0 as well');
});

test('stealth UA: FULL Worker wrapper resolves relative URLs and only patches webdriver===true', () => {
  const full = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(/new URL\(String\(scriptURL\), document\.baseURI\)\.href/.test(full),
    'relative worker URLs must be resolved against the page (blob: base broke them)');
  assert(/self\.navigator\.webdriver===true/.test(full),
    'worker webdriver patch must only act when the value is true (no own-property tell)');
  assert(!/return undefined;/.test(full.match(/var workerPatch = [^\n]*/)[0]),
    'worker patch must not force webdriver to undefined');
  const vm = require('vm');
  assert.doesNotThrow(() => new vm.Script(full), 'STEALTH_JS_FULL should parse as valid JS');
});

test('MCP: browser_mode tool registered', () => {
  assert(/"name":\s*"browser_mode"/.test(PY_CONTENT),
    'browser_mode must be registered in _register_tools');
  assert(/"browser_mode":\s*lambda a:\s*\["mode"\]/.test(PY_CONTENT),
    'browser_mode must be routed in the MCP tool_map');
  // Enum must list all three tiers.
  const re = /"name":\s*"browser_mode"[\s\S]*?"enum":\s*\[([^\]]*)\]/;
  const m = PY_CONTENT.match(re);
  assert(m, 'browser_mode must declare a tier enum');
  assert(/regular/.test(m[1]) && /stealth/.test(m[1]) && /undetected/.test(m[1]),
    'browser_mode enum must list regular, stealth, undetected');
});

// ── LIGHT tier self-containment regression guard ──
// Context: STEALTH_JS_FULL was split into a LIGHT subset (06a32f2). A split can
// silently leave a symbol behind — LIGHT calling a helper (makePlugin,
// spoofParam, PluginArrayProto, OrigWorker, …) that is ONLY declared inside
// FULL. Such a dangling reference throws ReferenceError on every page load when
// LIGHT is injected via Page.addScriptToEvaluateOnNewDocument, killing the JS
// context (the "stealth tier = 0 steps" failure mode). These tests prove LIGHT
// is a hermetic IIFE: it parses, runs, and references no FULL-only symbol.

test('mode: STEALTH_JS_LIGHT is a self-contained IIFE (no FULL-only refs)', () => {
  const light = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_LIGHT');
  const full = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  assert(light && full, 'both LIGHT and FULL bodies must be extractable');

  // Wrapped in a single IIFE — the whole body is one (function(){...})() form.
  assert(/^\s*\(function\s*\(\)\s*\{/.test(light), 'LIGHT must open with an IIFE');
  assert(/\}\)\(\);\s*$/.test(light.trim() + '\n'.repeat(0)) || /\}\)\(\);\s*$/.test(light.trimEnd()),
    'LIGHT must close the IIFE with })();');

  // Helpers/vars that exist ONLY in FULL — LIGHT must reference NONE of them.
  // (If the split leaked one of these into LIGHT, it would throw at runtime.)
  const fullOnlySymbols = [
    'makeMime', 'makePlugin', 'spoofParam', 'PluginArrayProto', 'PluginProto',
    'MimeTypeProto', 'pluginNames', 'workerPatch', 'WrappedWorker', 'OrigWorker',
    'gp1', 'gp2', '__cdpilot_worker_patched',
  ];
  for (const sym of fullOnlySymbols) {
    // Sanity: the symbol really is a FULL concept.
    assert(full.includes(sym), `precondition: ${sym} should exist in FULL`);
    assert(!light.includes(sym),
      `LIGHT must NOT reference FULL-only symbol "${sym}" — dangling ref = ReferenceError on every page (0-step bench failure)`);
  }
});

test('mode: stealth tier injection doesn\'t reference undefined symbols', () => {
  const light = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_LIGHT');
  const vm = require('vm');

  // Collect every locally-declared identifier (var/function/catch params) so we
  // can assert LIGHT never calls a helper it didn't define itself.
  const declaredVars = [...light.matchAll(/\bvar\s+([A-Za-z_$][\w$]*)/g)].map(m => m[1]);
  const declaredFns = [...light.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)/g)].map(m => m[1]);
  const declared = new Set([...declaredVars, ...declaredFns]);
  // LIGHT defines wdValue + origQuery as locals today; assert that holds.
  assert(declared.has('wdValue'), 'LIGHT should declare wdValue locally');
  assert(declared.has('origQuery'), 'LIGHT should declare origQuery locally');

  // Execute LIGHT in a minimal sandbox that emulates the bits of `window`/global
  // a real page exposes BEFORE any stealth runs. If LIGHT touched an
  // undefined FULL-only helper, this run would throw — the test would fail.
  const sandbox = {};
  const win = {
    chrome: undefined,
    PluginArray: function () {}, Plugin: function () {}, MimeType: function () {},
    WebGLRenderingContext: function () {}, WebGL2RenderingContext: function () {},
    Worker: function () {},
  };
  win.WebGLRenderingContext.prototype = { getParameter() { return null; } };
  win.WebGL2RenderingContext.prototype = { getParameter() { return null; } };
  sandbox.window = win;
  sandbox.Navigator = function () {};
  // Real Chrome exposes navigator.webdriver on Navigator.prototype (not as an
  // own prop). LIGHT redefines the prototype getter, so mirror that shape here.
  sandbox.Navigator.prototype = {};
  Object.defineProperty(sandbox.Navigator.prototype, 'webdriver', { get() { return true; }, configurable: true });
  sandbox.navigator = Object.create(sandbox.Navigator.prototype);
  sandbox.navigator.permissions = { query: () => Promise.resolve({ state: 'granted' }) };
  sandbox.Notification = { permission: 'default' };
  sandbox.Promise = Promise;
  sandbox.Object = Object;
  vm.createContext(sandbox);
  assert.doesNotThrow(
    () => new vm.Script(light).runInContext(sandbox, { timeout: 1000 }),
    'STEALTH_JS_LIGHT must execute without ReferenceError/throw — a dangling FULL-only ref would surface here',
  );
  // Post-condition: the webdriver mask actually applied (proves the IIFE ran to
  // completion, not just parsed). Vanilla `true` -> patched to `false`.
  assert.strictEqual(sandbox.navigator.webdriver, false,
    'LIGHT should have masked navigator.webdriver to false after running');
});

test('mode: LIGHT is a strict subset of FULL (regression guard for the split)', () => {
  const light = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_LIGHT');
  const full = extractRawTripleString(PY_CONTENT, 'STEALTH_JS_FULL');
  // The three LIGHT patches (webdriver / chrome.runtime / permissions) are the
  // SAFE subset and must each also appear in FULL — LIGHT can never gain a
  // surface FULL lacks, or "subset" is a lie and tier escalation is incoherent.
  assert(light.includes("'webdriver'") && full.includes("'webdriver'"),
    'webdriver patch must exist in both tiers');
  assert(light.includes('window.chrome.runtime') && full.includes('window.chrome.runtime'),
    'chrome.runtime patch must exist in both tiers');
  assert(light.includes('navigator.permissions.query') && full.includes('navigator.permissions.query'),
    'permissions.query patch must exist in both tiers');
  // FULL must be strictly larger (it carries the extra surfaces).
  assert(full.length > light.length, 'FULL must be a superset of LIGHT (larger body)');
  // Shared idempotency guard — both gate on the same flag so a page that ran
  // one tier won\'t double-run the other.
  assert(light.includes('__cdpilot_stealth') && full.includes('__cdpilot_stealth'),
    'both tiers must share the __cdpilot_stealth idempotency guard');
});

// ── Smart browser close (owned-tab tracking + Browser.close) ──

test('close: cmd_close defined and dispatched with --force/--keep flags', () => {
  assert(/async def cmd_close\(force_browser=False, keep_browser=False\)/.test(PY_CONTENT),
    'cmd_close must accept force_browser/keep_browser params');
  // Dispatcher wires `close` -> cmd_close with flag parsing.
  const m = PY_CONTENT.match(/"close":\s*lambda:\s*cmd_close\(([\s\S]*?)\),/);
  assert(m, 'close must be registered in async_map as a cmd_close call');
  assert(/force_browser="--force" in args/.test(m[1]),
    'close dispatch must parse --force into force_browser');
  assert(/keep_browser=\("--keep" in args/.test(m[1]),
    'close dispatch must parse --keep into keep_browser');
});

test('close: tracks owned tab on go / new-tab / session-window / smart-click', () => {
  // go marks the resolved page target as owned.
  assert(/ws, page = get_page_ws\(\)\s*\n\s*#[\s\S]*?_mark_owned_tab\(page\.get\("id"\)\)/.test(PY_CONTENT),
    'cmd_go must mark its page target as owned');
  // new-tab marks the freshly opened target.
  const newTab = PY_CONTENT.match(/data = cdp_get\(f'\/json\/new\?[\s\S]*?_mark_owned_tab\(data\.get\("id"\)\)/);
  assert(newTab, 'cmd_new_tab must mark the new target as owned');
  // The session window cdpilot creates is owned.
  assert(/_save_sessions\(sessions\)\s*\n\s*#[\s\S]*?_mark_owned_tab\(target_id\)/.test(PY_CONTENT),
    'a freshly created session window must be marked owned');
  // smart-click marks any tab the click spawned.
  assert(/_pre_click_targets/.test(PY_CONTENT) &&
    /if t\.get\("type"\) == "page" and t\.get\("id"\) not in _pre_click_targets:\s*\n\s*_mark_owned_tab/.test(PY_CONTENT),
    'cmd_smart_click must mark click-spawned tabs as owned');
});

test('close: closes ONLY owned tabs, leaves user tabs', () => {
  const body = PY_CONTENT.match(/async def cmd_close\([\s\S]*?\n\nasync def _browser_close_graceful/);
  // _browser_close_graceful is defined BEFORE cmd_close, so grab cmd_close body explicitly.
  const m = PY_CONTENT.match(/async def cmd_close\(force_browser=False, keep_browser=False\):([\s\S]*?)\n\n# ─/);
  const fn = (m && m[1]) || '';
  assert(fn.includes('owned = _load_owned_tabs()'),
    'cmd_close must load the owned-tab set');
  assert(/if tid and tid in owned:/.test(fn),
    'cmd_close must only close targets present in the owned set');
  assert(/Target\.closeTarget/.test(fn),
    'cmd_close must use CDP Target.closeTarget to close owned tabs');
  // User-tab detection skips internal/blank pages.
  assert(/user_pages = \[p for p in remaining_pages\s*\n\s*if not _is_chrome_internal_url/.test(fn),
    'cmd_close must filter user pages excluding chrome-internal/blank tabs');
});

test('close: when no user tabs remain -> Browser.close (graceful, never kill -9)', () => {
  const m = PY_CONTENT.match(/async def _browser_close_graceful\(\):([\s\S]*?)\n\nasync def cmd_close/);
  const fn = (m && m[1]) || '';
  assert(fn.includes('"Browser.close"') || fn.includes("'Browser.close'"),
    '_browser_close_graceful must send the CDP Browser.close command first');
  assert(/_stop_browser_on_port\(CDP_PORT\)/.test(fn),
    'graceful close must fall back to SIGTERM-based _stop_browser_on_port');
  // No actual SIGKILL/kill -9 invocation in the graceful path. (A comment may
  // mention "kill -9" to explain why it's avoided — only flag real calls.)
  assert(!/signal\.SIGKILL|os\.kill\([^)]*9\)|"-9"|'-9'/.test(fn),
    'graceful close must NOT invoke kill -9 / SIGKILL');
  // cmd_close calls graceful close only when user tabs absent or --force.
  const cm = PY_CONTENT.match(/async def cmd_close\(force_browser=False, keep_browser=False\):([\s\S]*?)\n\n# ─/);
  const cfn = (cm && cm[1]) || '';
  assert(/if user_pages and not force_browser:[\s\S]*?Browser left open/.test(cfn),
    'cmd_close must leave the browser open when user tabs remain (unless --force)');
  assert(/await _browser_close_graceful\(\)/.test(cfn),
    'cmd_close must invoke graceful browser close when empty/forced');
});

test('close: --keep never quits the browser; legacy cmd_stop preserved', () => {
  const cm = PY_CONTENT.match(/async def cmd_close\(force_browser=False, keep_browser=False\):([\s\S]*?)\n\n# ─/);
  const cfn = (cm && cm[1]) || '';
  assert(/if keep_browser:[\s\S]*?return/.test(cfn),
    'cmd_close must short-circuit and never quit when keep_browser is set');
  // Legacy full-kill stop is untouched and still registered.
  assert(/'stop':\s*cmd_stop,/.test(PY_CONTENT),
    'legacy `stop` must still map to the full-kill cmd_stop');
  assert(/def cmd_stop\(\):/.test(PY_CONTENT),
    'cmd_stop (legacy kill-all behavior) must still exist');
  // `stop --smart` aliases the smart close without removing legacy stop.
  assert(/if cmd == "stop" and "--smart" in args:[\s\S]*?cmd_close\(/.test(PY_CONTENT),
    '`stop --smart` must alias the smart close');
});

test('close: MCP browser_close exposes force/keep_browser + maps to flags', () => {
  const m = PY_CONTENT.match(/"name": "browser_close"[\s\S]*?inputSchema[\s\S]*?\}\}/);
  assert(m, 'browser_close tool must be registered');
  assert(/"force"/.test(m[0]) && /"keep_browser"/.test(m[0]),
    'browser_close schema must expose force + keep_browser');
  assert(/"browser_close": lambda a: \["close"\][\s\S]*?--force[\s\S]*?--keep/.test(PY_CONTENT),
    'browser_close must map force/keep_browser to CLI --force/--keep');
});

test('close: owned-tab tracking persists to a per-profile JSON file', () => {
  assert(/OWNED_TABS_FILE = os\.path\.join\(PROFILE_DIR, 'owned-tabs\.json'\)/.test(PY_CONTENT),
    'owned tabs must be stored in a per-project profile file');
  assert(/def _load_owned_tabs\(\):/.test(PY_CONTENT) && /def _save_owned_tabs\(/.test(PY_CONTENT)
    && /def _mark_owned_tab\(/.test(PY_CONTENT),
    'owned-tab load/save/mark helpers must exist');
  // After consuming the set, cmd_close clears tracking.
  const cm = PY_CONTENT.match(/async def cmd_close\(force_browser=False, keep_browser=False\):([\s\S]*?)\n\n# ─/);
  const cfn = (cm && cm[1]) || '';
  assert(/_save_owned_tabs\(set\(\)\)/.test(cfn),
    'cmd_close must clear the owned-tab set after closing');
});

test('close: CLI smoke — `close` with no browser is a graceful no-op', () => {
  const out = run('close');
  assert(/No browser running\./.test(out),
    '`close` must report no browser running instead of crashing');
});

test('close: CLI smoke — `stop --smart` with no browser is a graceful no-op', () => {
  const out = run('stop --smart');
  assert(/No browser running\./.test(out),
    '`stop --smart` must report no browser running instead of crashing');
});

// ── Metadata consistency (2026-09-27) ──
// The same fact lived in several files and drifted apart: glama.json and
// bin/cdpilot.js said Python 3.8+ while the code needs 3.10+, and the MCP
// Registry rejects a server.json whose version differs from the npm package.

test('metadata: version is identical in package.json, cdpilot.py and server.json', () => {
  const root = path.join(__dirname, '..');
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  const py = fs.readFileSync(path.join(root, 'src', 'cdpilot.py'), 'utf8');
  const server = JSON.parse(fs.readFileSync(path.join(root, 'server.json'), 'utf8'));
  const pyVersion = (py.match(/^__version__ = "([^"]+)"/m) || [])[1];
  assert.strictEqual(pyVersion, pkg.version, 'src/cdpilot.py __version__ must match package.json');
  assert.strictEqual(server.version, pkg.version, 'server.json version must match package.json');
  assert.strictEqual(server.packages[0].version, pkg.version,
    'server.json packages[0].version must match package.json');
});

test('claims: README panel numbers are tied to a measurement file that backs them', () => {
  // April's "sannysoft 24/24, intoli 6/6" stayed in the README for months
  // without re-measurement and were false by 2026-09-27. The panel table must
  // link its evidence file, and the headline numbers must appear there.
  const root = path.join(__dirname, '..');
  const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
  const m = readme.match(/\]\((\.claude\/docs\/stealth-panel-olcumu-(\d{4}-\d{2}-\d{2})\.md)\)/);
  assert(m, 'the README panel section must link a dated stealth-panel measurement file');
  const evidencePath = path.join(root, m[1]);
  assert(fs.existsSync(evidencePath), `${m[1]} must exist in the repo`);
  const evidence = fs.readFileSync(evidencePath, 'utf8');
  assert(/31\/0\/0/.test(evidence) && /\*\*6\/6\*\*/.test(evidence),
    'the evidence file must contain the sannysoft 31/0/0 and intoli 6/6 the README claims');
  assert(!/24\/24 PASS/.test(readme), 'the withdrawn April figure must not come back');
});

test('launcher: a python killed by a signal is not reported as success', () => {
  // `process.exit(code || 0)` exited 0 when the child died from a signal
  // (code === null), so an OOM kill looked like a clean run.
  const js = fs.readFileSync(path.join(__dirname, '..', 'bin', 'cdpilot.js'), 'utf8');
  assert(!/process\.exit\(code \|\| 0\)/.test(js), 'signal deaths must not map to exit 0');
  assert(/on\('close', \(code, signal\)/.test(js) && /128 \+ \(os\.constants\.signals\[signal\]/.test(js),
    'the close handler must turn a signal into 128 + signal number');
});

test('metadata: publish workflow can be re-run after npm succeeded', () => {
  // 0.9.1: npm accepted the package but it stayed invisible past the wait, so
  // the release failed before the MCP Registry steps. A re-run must skip the
  // npm publish instead of dying on "version already exists".
  const wf = fs.readFileSync(path.join(__dirname, '..', '.github', 'workflows', 'publish.yml'), 'utf8');
  assert(/workflow_dispatch:/.test(wf), 'publish.yml must be dispatchable to resume the registry half');
  const step = (wf.match(/- name: Publish to npm[\s\S]*?(?=\n\s*- name:)/) || [])[0] || '';
  assert(/npm view cdpilot@"\$V" version/.test(step) && /already on npm/.test(step),
    'the npm publish step must skip a version that is already published');
});

test('metadata: MCP Registry name matches between package.json and server.json', () => {
  const root = path.join(__dirname, '..');
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  const server = JSON.parse(fs.readFileSync(path.join(root, 'server.json'), 'utf8'));
  assert.strictEqual(pkg.mcpName, server.name,
    'the registry verifies npm ownership by package.json mcpName == server.json name');
  assert(server.description.length <= 100, 'registry schema caps description at 100 chars');
});

test('metadata: no file advertises a Python older than the 3.10 the code needs', () => {
  const root = path.join(__dirname, '..');
  const files = ['README.md', 'glama.json', path.join('bin', 'cdpilot.js')];
  for (const f of files) {
    const txt = fs.readFileSync(path.join(root, f), 'utf8');
    assert(!/[Pp]ython\s*(?:>=|&gt;=)?\s*3\.[0-9](?![0-9])\s*\+?/.test(
      txt.replace(/[Pp]ython\s*(?:>=|&gt;=)?\s*3\.1[0-9]/g, '')),
      `${f} advertises a Python version below 3.10`);
  }
});

test('metadata: launch drafts do not repeat the corrected 0.9.1 numbers', () => {
  const root = path.join(__dirname, '..');
  // CHANGELOG [0.9.1] "Corrected": src/cdpilot.py is 13,129 lines / ~542KB, not
  // "50KB"; the tool has one Python dependency (websockets) and 70+ commands,
  // not "zero dependencies" / "40+ commands"; the "500x fewer tokens than
  // screenshots" a11y-snapshot claim had no measurement behind it. These drafts
  // are pre-launch (unlike twitter-launch-thread.md, which is historical and
  // excluded) so any recurrence of the old numbers must be caught before posting.
  const files = [
    'hackernews-post.md',
    'reddit-posts.md',
    'blog-launch-post.md',
    'platform-submission-guide.md',
  ];
  const banned = /50 ?KB|500x|40\+ commands/;
  for (const f of files) {
    const txt = fs.readFileSync(path.join(root, 'docs', f), 'utf8');
    assert(!banned.test(txt), `docs/${f} repeats a corrected 0.9.1 number (50KB/50 KB/500x/40+ commands)`);
  }
});

// ── iframe targeting (#1) ──
// `click "iframe#card >>> input"` / `--frame <f>` for element commands, over
// CDP (flat sessions for out-of-process frames), never contentDocument.
// Parsers run as pure Python; the resolver, pool, frame search and `frame`
// command run against a fake CDP page (test/frames_fake_cdp.py: the real
// cdpilot.py with only the websocket replaced); the browser path is the
// opt-in e2e test at the end (CDPILOT_E2E=1) plus test/fixtures/frames/.
(function() {
  const { execFileSync, spawn, spawnSync } = require('child_process');
  const os = require('os');
  const PYB = process.env.CDPILOT_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const FRAME_SEP_LINE = (PY_CONTENT.match(/^FRAME_SEP = ".*"$/m) || [])[0];

  function pyFuncs(names) {
    const fns = names.map((n) => extractPyFunc(PY_CONTENT, n));
    fns.forEach((f, i) => assert(f, `${names[i]} must be extractable`));
    assert(FRAME_SEP_LINE, 'FRAME_SEP constant must exist');
    return FRAME_SEP_LINE + '\n\n' + fns.join('\n\n');
  }

  function pyCases(src, cases) {
    return JSON.parse(execFileSync(PYB, ['-c', src], {
      input: JSON.stringify(cases.map((c) => c[0])), encoding: 'utf-8', timeout: 10000,
    }).trim());
  }

  let fakeResults = null;
  let fakeTrace = null;  // CDPILOT_CDP_TRACE file of the fake-CDP run
  function fake(name) {
    if (!fakeResults) {
      const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-frames-fake-'));
      fakeTrace = path.join(home, 'cdp-trace.txt');
      const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
        CDP_PORT: '19224', CDPILOT_LOG: '0', CDPILOT_CDP_TRACE: fakeTrace };
      for (const k of ['CDPILOT_WS_POOL', 'CDPILOT_TARGET', 'CDPILOT_TIMEOUT']) delete env[k];
      const out = execFileSync(PYB, [path.join(__dirname, 'frames_fake_cdp.py'), PY_PATH], {
        encoding: 'utf-8', timeout: 60000, env,
      });
      fakeResults = JSON.parse(out.trim().split('\n').pop());
    }
    const r = fakeResults[name];
    assert(r, `fake-CDP scenario ${name} missing`);
    assert(!r.error, `fake-CDP scenario ${name} crashed:\n${r.error}`);
    return r;
  }

  test('frames: >>> chain parser (nesting, quotes, brackets, escapes, empty segments = no chain)', () => {
    const src = pyFuncs(['_split_frame_chain', '_frame_selector_hops']) + `
import json, sys
print(json.dumps([_frame_selector_hops(t) for t in json.load(sys.stdin)]))
`;
    const cases = [
      ['iframe#card >>> input[name=cardnumber]', [['iframe#card'], 'input[name=cardnumber]']],
      ['iframe.a >>> iframe.b >>> button', [['iframe.a', 'iframe.b'], 'button']],
      ['iframe[title="a >>> b"] >>> button', [['iframe[title="a >>> b"]'], 'button']],
      ["iframe[title='x>>>y'] >>> #b", [["iframe[title='x>>>y']"], '#b']],
      ['iframe[title=a>>>b] >>> #b', [['iframe[title=a>>>b]'], '#b']],
      ['  iframe  >>>  button  ', [['iframe'], 'button']],
      ['Home >>> Products', [['Home'], 'Products']],
      ['div:not(.a >>> .b)', null],
      ['#a\\>>> b', null],
      ['button.primary', null],
      ['Next >>>', null],
      [' >>> button', null],
      ['a >>> >>> b', null],
    ];
    const got = pyCases(src, cases);
    cases.forEach((c, i) => assert.deepStrictEqual(got[i], c[1], `hops ${JSON.stringify(c[0])}`));
  });

  test('frames: literal-fallback decision — a >>> whose first hop is no iframe stays the old selector', () => {
    const src = 'import re as _re\n' + pyFuncs(['_split_frame_chain', '_frame_selector_hops', '_parse_frame_hop',
      '_frame_hop_is_selector', '_frame_chain_candidate', '_frame_selector_plan']) + `
import json, sys
print(json.dumps([_frame_selector_plan(*c) for c in json.load(sys.stdin)]))
`;
    const note = (hop) => `note: '${hop}' matched no iframe; used the selector as written`;
    const cases = [
      [['Next >>>', false], [[], 'Next >>>', null]],
      [['Next >>>', true], [[], 'Next >>>', null]],
      [['button.primary', false], [[], 'button.primary', null]],
      [['Home >>> Products', false], [[], 'Home >>> Products', note('Home')]],
      [['#nope >>> #x', false], [[], '#nope >>> #x', note('#nope')]],
      [['Page 1 of 3 >>> Next page', false], [[], 'Page 1 of 3 >>> Next page', note('Page 1 of 3')]],
      [['iframe#card >>> input', true], [[{ kind: 'sel', value: 'iframe#card' }], 'input', null]],
      [['#card >>> 1 >>> url=stripe >>> #b', true],
        [[{ kind: 'sel', value: '#card' }, { kind: 'index', value: 1 }, { kind: 'url', value: 'stripe' }], '#b', null]],
      // smart-* text: a first hop of plain words is never a frame (querySelector("Main")
      // would find <main> and step into an iframe inside it), even if it wraps one.
      [['Main >>> Settings', true, 'text'], [[], 'Main >>> Settings', null]],
      [['main >>> Settings', true, 'text'], [[], 'main >>> Settings', null]],
      [['Page 1 of 3 >>> Next page', true, 'text'], [[], 'Page 1 of 3 >>> Next page', null]],
      [['Frameworks >>> React', true, 'text'], [[], 'Frameworks >>> React', null]],
      [['Main >>> Settings', true, 'css'], [[{ kind: 'sel', value: 'Main' }], 'Settings', null]],
      [['iframe >>> Pay now', true, 'text'], [[{ kind: 'sel', value: 'iframe' }], 'Pay now', null]],
      [['frame[name=f] >>> Pay now', true, 'text'], [[{ kind: 'sel', value: 'frame[name=f]' }], 'Pay now', null]],
      [['#card-element >>> Pay now', true, 'text'], [[{ kind: 'sel', value: '#card-element' }], 'Pay now', null]],
      [['.widget >>> Pay now', false, 'text'], [[], '.widget >>> Pay now', note('.widget')]],
      [['url=stripe >>> Pay now', true, 'text'], [[{ kind: 'url', value: 'stripe' }], 'Pay now', null]],
    ];
    const got = pyCases(src, cases);
    cases.forEach((c, i) => assert.deepStrictEqual(got[i], c[1], `plan ${JSON.stringify(c[0])}`));
  });

  test('frames: --frame flag extraction and hop kinds (index / url= / auto for --frame, sel for >>>)', () => {
    const src = pyFuncs(['_split_frame_chain', '_parse_frame_hop', '_parse_frame_spec', '_extract_frame_flag']) + `
import json, sys
def run(kind, arg):
    try:
        if kind == 'hop':
            return _parse_frame_hop(arg)
        if kind == 'implicit':
            return _parse_frame_hop(arg, implicit=True)
        if kind == 'spec':
            return _parse_frame_spec(arg)
        rest, value = _extract_frame_flag(arg)
        return [rest, value]
    except ValueError:
        return 'ERR'
print(json.dumps([run(k, a) for k, a in json.load(sys.stdin)]))
`;
    const cases = [
      [['hop', '2'], { kind: 'index', value: 2 }],
      [['hop', ' 0 '], { kind: 'index', value: 0 }],
      [['hop', 'url=js.stripe.com'], { kind: 'url', value: 'js.stripe.com' }],
      [['hop', 'URL:localhost:8762'], { kind: 'url', value: 'localhost:8762' }],
      [['hop', '#card'], { kind: 'auto', value: '#card' }],
      [['hop', 'card-frame'], { kind: 'auto', value: 'card-frame' }],
      [['implicit', 'card-frame'], { kind: 'sel', value: 'card-frame' }],
      [['implicit', '3'], { kind: 'index', value: 3 }],
      [['spec', '0 >>> iframe[name="x >>> y"]'],
        [{ kind: 'index', value: 0 }, { kind: 'auto', value: 'iframe[name="x >>> y"]' }]],
      [['spec', 'a >>> '], 'ERR'],
      [['spec', ''], 'ERR'],
      [['flag', ['--frame', '#card', 'button']], [['button'], '#card']],
      [['flag', ['button', '--frame=2', '--no-heal']], [['button', '--no-heal'], '2']],
      [['flag', ['a', 'b']], [['a', 'b'], null]],
      [['flag', ['--framex', 'a']], [['--framex', 'a'], null]],
      [['flag', ['a', '--frame']], 'ERR'],
      [['flag', ['--frame=', 'a']], 'ERR'],
      [['flag', ['--frame', ' ', 'a']], 'ERR'],
    ];
    const got = pyCases(src, cases);
    cases.forEach((c, i) => assert.deepStrictEqual(got[i], c[1], `${JSON.stringify(c[0])}`));
  });

  test('frames: rewrite sends Runtime/DOM into the frame and shifts mouse x/y by the frame offset', () => {
    const src = extractPyFunc(PY_CONTENT, '_frame_route_rewrite');
    assert(src, '_frame_route_rewrite must be extractable');
    const out = execFileSync(PYB, ['-c', src + `

import asyncio, json
class Route:
    context_id, session_id, chain, dirty, offset = 42, 'S1', [('p', 'o')], True, (0.0, 0.0)
calls = []
async def _frame_route_refresh_offset(route):
    calls.append(1)
    route.offset, route.dirty = (100.0, 1000.0), False
    return route.offset
cmds = [
    (1, 'Runtime.evaluate', {'expression': '1'}),
    (2, 'DOM.describeNode', {'objectId': 'o'}),
    (3, 'Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': 10, 'y': 20}),
    (4, 'Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': 10, 'y': 20}),
    (5, 'Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'a'}),
    (6, 'Page.navigate', {'url': 'about:blank'}),
    (7, 'Runtime.evaluate', {'expression': '2', 'contextId': 99}),
    (8, 'Runtime.evaluate', {'expression': '3'}, 'EXPLICIT'),
    (9, 'Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 5, 'y': 5}),
]
res = asyncio.run(_frame_route_rewrite(Route(), cmds))
print(json.dumps({'out': res, 'refreshes': len(calls), 'orig': cmds[2][2]}))
`], { encoding: 'utf-8', timeout: 10000 });
    const r = JSON.parse(out.trim());
    assert.deepStrictEqual(r.out, [
      [1, 'Runtime.evaluate', { expression: '1', contextId: 42 }, 'S1'],
      [2, 'DOM.describeNode', { objectId: 'o' }, 'S1'],
      [3, 'Input.dispatchMouseEvent', { type: 'mousePressed', x: 110, y: 1020 }],
      [4, 'Input.dispatchMouseEvent', { type: 'mouseReleased', x: 110, y: 1020 }],
      [5, 'Input.dispatchKeyEvent', { type: 'keyDown', key: 'a' }],
      [6, 'Page.navigate', { url: 'about:blank' }],
      [7, 'Runtime.evaluate', { expression: '2', contextId: 99 }, 'S1'],
      [8, 'Runtime.evaluate', { expression: '3' }, 'EXPLICIT'],
      [9, 'Input.dispatchMouseEvent', { type: 'mouseMoved', x: 105, y: 1005 }],
    ]);
    assert.strictEqual(r.refreshes, 2, 'offset re-measured once per page-JS run before mouse input, not per event');
    assert.deepStrictEqual(r.orig, { type: 'mousePressed', x: 10, y: 20 }, "caller's params must not be mutated");
  });

  test('frames (fake CDP): element and smart-* commands are frame-aware; search limits 20 frames / 2 s', () => {
    const r = fake('commands');
    for (const fn of ['cmd_click', 'cmd_fill', 'cmd_submit', 'cmd_hover', 'cmd_dblclick', 'cmd_rightclick']) {
      assert.strictEqual(r.kinds[fn], 'css', `${fn} must resolve >>> / --frame as a selector`);
    }
    for (const fn of ['cmd_smart_click', 'cmd_smart_fill', 'cmd_smart_select']) {
      assert.strictEqual(r.kinds[fn], 'text', `${fn} must resolve >>> / --frame before its text`);
    }
    assert.deepStrictEqual(r.cli, ['click', 'dblclick', 'fill', 'frame', 'hover', 'rightclick', 'smart-click',
      'smart-fill', 'smart-select', 'submit', 'type']);
    assert.deepStrictEqual(r.limits, [20, 2.0, 60]);
  });

  test('frames (fake CDP): >>> and --frame reach same-process, nested and out-of-process frames', () => {
    const r = fake('routing');
    assert.deepStrictEqual(r.css.res, ['ok', 'card|#btn']);
    assert.strictEqual(r.css.context, r.contexts.card, 'Runtime.evaluate must carry the frame context id');
    assert.deepStrictEqual(r.css.mouse, ['mousePressed', 101, 1002], 'mouse x/y shifted by the frame offset');
    assert.deepStrictEqual(r.nested.res, ['ok', 'nested|#deep']);
    assert.strictEqual(r.nested.context, r.contexts.nested);
    assert.deepStrictEqual(r.nested.mouse, ['mousePressed', 111, 1022], 'nested offsets add up');
    assert.deepStrictEqual(r.oopif.res, ['ok', 'pay|#cc']);
    assert.strictEqual(r.oopif.session, 'S-pay', 'out-of-process frame: flat session id on the message');
    assert.deepStrictEqual(r.oopif.mouse, ['mousePressed', 6, 9]);
    assert.deepStrictEqual(r.flag_index.res, ['ok', 'pay|#cc'], '--frame 1');
    assert.deepStrictEqual(r.flag_src.res, ['ok', 'pay|#cc'], '--frame takes a bare src substring');
    assert.deepStrictEqual(r.arrow_src_word.res, ['ok', 'top|pay.html >>> #cc'],
      'a >>> hop never matches by src substring (url= does): the string stays literal');
    assert.deepStrictEqual(r.attached, ['pay', 'pay', 'pay']);
    assert.deepStrictEqual(r.detached, ['S-pay', 'S-pay', 'S-pay'], 'every flat session is detached');
    assert.deepStrictEqual(r.open_sessions, []);
    assert.strictEqual(r.stderr, '');
  });

  test('frames (fake CDP): "Next >>>", "Home >>> Products" run as written; failure adds the note line', () => {
    const r = fake('literal');
    assert.deepStrictEqual(r.next.res, ['ok', 'top|Next >>>']);
    assert.deepStrictEqual(r.next.messages, ['Runtime.evaluate', 'Input.dispatchMouseEvent'],
      'an empty segment: no frame lookup at all, only the command itself');
    assert.deepStrictEqual(r.home.res, ['ok', 'top|Home >>> Products']);
    assert.deepStrictEqual(r.page_of.res, ['ok', 'top|Page 1 of 3 >>> Next page']);
    assert.strictEqual(r.home.stderr + r.page_of.stderr, '', 'no note when the literal selector works');
    assert.deepStrictEqual(r.fail_nope.res, ['exit', 1], 'exit code of the command itself');
    assert.strictEqual(r.fail_nope.stderr, "Error: selector '#nope >>> #x' not resolved.\n"
      + "note: '#nope' matched no iframe; used the selector as written\n");
    assert.deepStrictEqual(r.fail_plain.res, ['exit', 1]);
    assert(!/note:/.test(r.fail_plain.stderr), 'no note when no frame was looked for');
    assert(r.seen.every((s) => !s.routed), 'literal strings never run inside a frame');
    assert.deepStrictEqual(r.flag_strict.res, ['exit', 1], '--frame stays strict');
    assert.strictEqual(r.flag_strict.stderr, "Error: no iframe matches '#nope' in top document (frames: [0] card; [1] pay)\n");
    assert.deepStrictEqual(r.later_hop_strict.res, ['exit', 1], 'after a real first hop the chain is strict');
    assert(/no iframe matches '#missing' in iframe#card/.test(r.later_hop_strict.stderr), r.later_hop_strict.stderr);
  });

  test('frames (fake CDP): smart-click "Main >>> Settings" stays literal text (no frame lookup)', () => {
    const r = fake('text_hops');
    for (const key of ['text_main', 'text_main_lower', 'text_page_of']) {
      assert.deepStrictEqual(r[key].messages, ['Runtime.evaluate', 'Input.dispatchMouseEvent'],
        `${key}: the command alone, no frame lookup`);
      assert.strictEqual(r[key].stderr, '', key);
    }
    assert.deepStrictEqual(r.text_main.res, ['ok', 'top|Main >>> Settings'], 'the page, with the whole text');
    assert.deepStrictEqual(r.text_selector.res, ['ok', 'card|Pay now'], 'iframe#card >>> text still routes');
    assert.deepStrictEqual(r.text_url.res, ['ok', 'card|Pay now'], 'url= >>> text still routes');
    assert.deepStrictEqual(r.css_wrapper.res, ['ok', 'card|#btn'], 'css kind: "main" is a selector');
  });

  test('frames (fake CDP): a hop that wraps an iframe works, with one stderr note', () => {
    const r = fake('text_hops');
    const note = (hop) => `note: '${hop}' is not an iframe; using the iframe inside it\n`;
    assert.deepStrictEqual(r.text_wrapper.res, ['ok', 'card|Pay now']);
    assert.strictEqual(r.text_wrapper.stderr, note('#card-element'));
    assert.strictEqual(r.css_wrapper.stderr, note('main'));
    assert.deepStrictEqual(r.flag_wrapper.res, ['ok', 'card|#btn']);
    assert.strictEqual(r.flag_wrapper.stderr, note('#card-element'), '--frame too');
    assert.strictEqual(r.css_frame.stderr, '', 'no note when the hop is the iframe itself');
    assert.strictEqual(r.text_selector.stderr, '');
  });

  test('frames (fake CDP): CDPILOT_WS_POOL=0 is restored after an exception, SystemExit and cancellation', () => {
    const r = fake('pool_restore');
    assert.deepStrictEqual(r.pool_inside, [true, true, true, false],
      'pool pinned on inside a route (flat sessions share one socket), already restored for a literal command');
    for (const [key, res] of [['exception', ['raise', 'RuntimeError']], ['system_exit', ['exit', 3]],
      ['frame_error', ['exit', 1]], ['cancel_in_close', ['raise', 'CancelledError']],
      ['literal', ['ok', 'top|Home >>> Products']]]) {
      const c = r[key];
      assert.deepStrictEqual(c.res, res, `${key}: outcome passes through unchanged`);
      assert.strictEqual(c.pool_after, false, `${key}: pool flag must be restored to off`);
      assert.strictEqual(c.pooled_after, false, `${key}: the socket opened for the route must leave the pool`);
      assert(c.sockets >= 1 && c.all_closed, `${key}: every socket must be closed (${c.sockets})`);
    }
  });

  test('frames (fake CDP): smart-* order — page real match, disabled-only, frames, then page weak match', () => {
    const r = fake('smart_order');
    const c = r.c_page_real;
    assert.deepStrictEqual(c.finder, [['top', 'strict']], 'page: one find-and-act script');
    assert.deepStrictEqual(c.acts, [['top', 'strict']]);
    assert.strictEqual(c.frame_lists, 0, 'enabled real page match: no frame search');
    assert.deepStrictEqual(c.res, { found: true, x: 9, y: 9 });
    const d = r.d_disabled_only;
    assert.deepStrictEqual(d.finder, [['top', 'strict'], ['top', 'loose']],
      'only disabled real matches: the old page rules (their error), no frame search');
    assert.strictEqual(d.frame_lists, 0);
    assert.deepStrictEqual(d.res, { found: false, disabled: 1 });
    assert.deepStrictEqual(d.acts, []);
    const e = r.e_frame_real;
    assert.deepStrictEqual(e.finder, [['top', 'strict'], ['card', 'probe'], ['card', 'strict']],
      'weak page match: frames probed (find only), then the finder acts in the chosen frame');
    assert.deepStrictEqual(e.acts, [['card', 'strict']], 'exactly one action');
    assert.deepStrictEqual(e.res, { found: true, x: 105, y: 1006 }, 'frame x/y returned in page coordinates');
    assert.strictEqual(e.stderr, 'smart-x: matched inside frame iframe#card (http://a.test/inner.html)\n');
    const n = r.e_nothing;
    assert.deepStrictEqual(n.finder, [['top', 'strict'], ['card', 'probe'], ['xo', 'probe'], ['pay', 'probe'],
      ['top', 'loose']], 'no frame match: back to the page weak match');
    assert.deepStrictEqual(n.acts, [['top', 'loose']], 'frames were only probed');
    assert.deepStrictEqual(n.res, { found: true, x: 1, y: 1, weak: true });
    assert.deepStrictEqual(n.open_sessions, [], 'search sessions detached');
    const all = r.e_oopif_all;
    assert.deepStrictEqual(all.attached, ['pay'], 'smart-click searches out-of-process frames too');
    assert.deepStrictEqual(all.res, { found: true, x: 10, y: 13 });
    assert.deepStrictEqual(all.acts, [['pay', 'strict']]);
  });

  test('frames (fake CDP): the chosen frame no longer matching at act time gives its not-found result', () => {
    const r = fake('smart_order').act_changed;
    assert.deepStrictEqual(r.finder, [['top', 'strict'], ['card', 'probe'], ['card', 'strict']],
      'no page fallback after a frame was chosen');
    assert.deepStrictEqual(r.acts, []);
    assert.deepStrictEqual(r.res, { found: false, weakScore: 20 }, 'the command prints its normal not-found error');
  });

  test('frames (fake CDP): smart-fill/select auto search enters same-origin frames only', () => {
    const r = fake('smart_order');
    const same = r.fill_same_origin;
    assert.deepStrictEqual(same.finder, [['top', 'strict'], ['card', 'probe'], ['card', 'strict']]);
    assert.deepStrictEqual(same.acts, [['card', 'strict']]);
    assert.deepStrictEqual(same.res, { found: true, x: 105, y: 1006 });
    const cross = r.fill_cross_origin;
    assert.deepStrictEqual(cross.attached, [], 'never attaches to an out-of-process (cross-site) frame');
    assert.deepStrictEqual(cross.finder, [['top', 'strict'], ['card', 'probe'], ['xo', 'guarded'], ['top', 'loose']],
      'a same-process cross-origin frame is skipped by the origin guard before the finder runs');
    assert.deepStrictEqual(cross.res, { found: false }, 'the old not-found result from the page');
    assert.strictEqual(cross.stderr, '');
  });

  test('frames (fake CDP): a slow frame call gets the remaining budget as its timeout', () => {
    const r = fake('budget');
    const d = r.direct;
    assert.strictEqual(d.hit, null);
    assert.strictEqual(d.stderr, 'smart-x: frame search stopped after 0.5s (1 of 3 frames)\n');
    assert(d.elapsed >= 0.45 && d.elapsed < 1.5, `budget 0.5 s, took ${d.elapsed}`);
    assert(d.calls.every((c) => c.timeout <= 0.5), `every call capped at the budget: ${JSON.stringify(d.calls)}`);
    const slow = d.calls.filter((c) => c.finder);
    assert.strictEqual(slow.length, 1);
    // <= not <: Windows' monotonic clock ticks every ~16 ms, so no time may have
    // passed yet and the time left is the whole budget.
    assert(slow[0].timeout >= 0.1 && slow[0].timeout <= 0.5, `slow call timeout = time left: ${slow[0].timeout}`);
    assert.strictEqual(d.socket_kept, true, 'a timed-out search call keeps the shared socket');
    assert.deepStrictEqual(d.finder, [['slow', 'probe']], 'the slow frame only ever gets the side-effect-free probe');
    assert.deepStrictEqual(d.acts, []);
    const g = r.default_budget;
    assert.strictEqual(g.stderr, 'smart-x: frame search stopped after 2s (1 of 3 frames)\n');
    assert(g.elapsed >= 1.9 && g.elapsed < 3.5, `default budget 2 s, took ${g.elapsed}`);
    assert(g.max_search_timeout <= 2.0, `search calls capped at 2 s: ${g.max_search_timeout}`);
    assert.deepStrictEqual(g.finder, [['top', 'strict'], ['slow', 'probe'], ['top', 'loose']]);
    assert.deepStrictEqual(g.acts, [['top', 'loose']], 'exactly one action overall');
    assert.deepStrictEqual(g.res, { found: true, x: 1, y: 1, weak: true }, 'falls back to the page');
  });

  test('frames (fake CDP): a probe cut off by the budget acts nowhere; the page fallback is the one action', () => {
    const r = fake('probe_timeout');
    // The slow frame holds a real match: were its script the act-mode finder,
    // it would click/type after the call gave up, and the page would act too.
    for (const key of ['click', 'fill_same_origin']) {
      const c = r[key];
      assert.deepStrictEqual(c.finder, [['top', 'strict'], ['slow', 'probe'], ['top', 'loose']], key);
      assert.strictEqual(c.stderr, 'smart-x: frame search stopped after 0.5s (1 of 2 frames)\n', key);
      assert(c.elapsed < 1.5, `${key}: ${c.elapsed}`);
    }
    assert.deepStrictEqual(r.click.acts, [['top', 'loose']], 'smart-click: only the page weak match is clicked');
    assert.deepStrictEqual(r.fill_same_origin.acts, [], 'smart-fill: nothing typed; the old not-found result');
    assert.deepStrictEqual(r.fill_same_origin.res, { found: false });
  });

  test('frames (fake CDP): a frame-call timeout keeps the pooled socket; a plain cdp_send timeout drops it', () => {
    const r = fake('keep_socket');
    assert.strictEqual(r.kept, true, 'flat sessions live on the socket: keep it');
    assert.strictEqual(r.again, 'top|again', 'and it still answers');
    assert.strictEqual(r.sockets, 1);
    assert(r.frame_elapsed < 1.5, `timeout=0.3 must not wait a 2 s recv slice: ${r.frame_elapsed}`);
    assert(r.dropped && r.closed, 'ordinary calls keep the old rule: drop and close after a timeout');
    assert(r.plain_elapsed >= 0.3 && r.plain_elapsed < 3, `plain call: old flat 2 s recv wait: ${r.plain_elapsed}`);
  });

  test('frames (fake CDP): plain cdp_send still reads a reply that lands just after its timeout', () => {
    // `wait "#nope" 15` answers from a 15 s page timer, at 15.0x s: the old
    // flat 2 s recv wait read it; a wait trimmed to the timeout dropped it.
    const r = fake('late_reply');
    assert.strictEqual(r.plain.value, 'top|late', `reply 0.1 s after timeout=0.3 must be read (${r.plain.elapsed}s)`);
    assert.strictEqual(r.frame.value, null, 'frame-search calls stop at their timeout');
    assert(r.frame.elapsed < 0.39, `frame call: ${r.frame.elapsed}`);
  });

  test('frames (fake CDP): no frame command sends Runtime.enable (main world via DOM.resolveNode)', () => {
    // Runtime.enable is the best-known CDP detection signal (Turnstile,
    // DataDome), and Turnstile runs inside an iframe. Every scenario above
    // (routes, nested and out-of-process frames, smart-* search, frame
    // list/eval, pool restore) ran against the fake page.
    fake('routing');
    const sent = fakeResults._methods;
    assert(!sent['Runtime.enable'] && !sent['Runtime.disable'], `sent: ${JSON.stringify(sent)}`);
    assert(sent['DOM.resolveNode'] > 0, 'same-process frames: main world from the frame document');
    assert.strictEqual(sent['Runtime.releaseObjectGroup'], sent['DOM.resolveNode'],
      'every resolved frame document is released');
    assert(sent['Target.attachToTarget'] > 0, 'out-of-process frames: flat session');
    const r = fake('routing');
    assert.strictEqual(r.css.context, r.contexts.card, 'the main-world context id');
    assert.strictEqual(r.nested.context, r.contexts.nested);
  });

  test('frames (fake CDP): no usable main-world id: isolated world, and frame eval says so', () => {
    const r = fake('isolated_fallback');
    assert.deepStrictEqual(r.eval.contexts, r.eval.isolated, 'eval ran in the isolated world');
    assert.strictEqual(r.eval.stdout, 'Result: card|z\n');
    assert(/eval runs in an isolated world/.test(r.eval.stderr), r.eval.stderr);
    assert.strictEqual(r.list.stderr, '', 'only frame eval (page globals) needs the note');
  });

  test('frames (fake CDP): CDPILOT_CDP_TRACE lists each CDP method sent, names only', () => {
    fake('routing');
    const lines = fs.readFileSync(fakeTrace, 'utf8').trim().split('\n');
    assert(lines.length > 100, `${lines.length} lines`);
    assert(lines.every((l) => /^[A-Z][A-Za-z]*\.[A-Za-z]+$/.test(l)), 'method names only, no params');
    assert.deepStrictEqual([...new Set(lines)].sort(), Object.keys(fakeResults._methods).sort());
  });

  test('frames (fake CDP): plain cdp_send sends the same wire messages and skips interleaved events', () => {
    // Guards removing the frame-only event collection from cdp_send: pooled
    // and CDPILOT_WS_POOL=0 paths, events arriving before the replies.
    const r = fake('plain_wire');
    for (const key of ['pooled', 'unpooled']) {
      assert.deepStrictEqual(r[key].wire, [
        { id: 1, method: 'Runtime.evaluate', params: { expression: 'NOISY', returnByValue: true } },
        { id: 2, method: 'Runtime.evaluate', params: { expression: 'WHERE:x' } },
      ], key);
      assert.deepStrictEqual(r[key].result, { 1: { result: { type: 'string', value: 'top|noisy' } },
        2: { result: { type: 'string', value: 'top|x' } } }, key);
    }
  });

  test('frames (fake CDP): frame list keeps its old output; --frame lists and evals inside the frame', () => {
    const r = fake('frame_list');
    assert.strictEqual(r.top.stdout, 'iframes (2):\n  [0] src=about:blank name= id=hidden-frame\n'
      + '  [1] src=http://a.test/inner.html name=card-frame id=card\n');
    assert.strictEqual(r.inside.stdout, 'iframes in iframe#card (2):\n  [0] src=http://a.test/nested.html name= id=nested\n'
      + '  [1] src=(no source) name= id=ghost (hidden)\n');
    assert.strictEqual(r.eval_inside.stdout, 'Result: card|z\n');
    assert.strictEqual(r.eval_top.stdout, 'Result: top|z\n');
  });

  test('frames: CLI rejects --frame without a value (exit 2, before any browser work)', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-frames-test-'));
    const r = spawnSync(process.execPath, [CLI, 'click', 'button', '--frame'], {
      encoding: 'utf-8', timeout: 30000,
      env: { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
        CDP_PORT: '19223', CHROME_BIN: path.join(home, 'no-such-browser'), CDPILOT_NO_AUTOLAUNCH: '1' },
    });
    assert.strictEqual(r.status, 2, `exit ${r.status}, stderr: ${r.stderr}`);
    assert(/--frame needs a value/.test(r.stderr), `stderr: ${r.stderr}`);
  });

  test('frames: docs — README section, CHANGELOG [Unreleased], help text in src and bin', () => {
    const root = path.join(__dirname, '..');
    const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
    const section = (readme.split('### Element targeting inside iframes')[1] || '').split('\n### ')[0];
    assert(section, 'README needs the element-targeting section');
    for (const s of ['iframe#card >>> input[name=cardnumber]', '--frame', 'matched no iframe; used the selector as written',
      "page's own origin", 'frame search stopped after 2s', 'is not an iframe; using the iframe inside it']) {
      assert(section.includes(s), `README iframe section must mention ${s}`);
    }
    const changelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8');
    // The newest release, plus the [Unreleased] section above it if there is one.
    const secs = changelog.split(/^## \[/m);
    const unreleased = (secs[1] || '').startsWith('Unreleased]') ? secs[1] + (secs[2] || '') : (secs[1] || '');
    for (const s of ['--frame', 'matched no iframe', "page's own origin", 'frame search stopped after 2s',
      'is not an iframe; using the iframe inside it']) {
      assert(unreleased.includes(s), `CHANGELOG [Unreleased] must describe ${s}`);
    }
    const doc = (PY_CONTENT.match(/^"""([\s\S]*?)"""/m) || [])[1] || '';
    assert(doc.includes('>>>') && doc.includes('--frame'), 'python --help docstring must document frames');
    const bin = fs.readFileSync(CLI, 'utf8');
    assert(bin.includes('iframe#card >>> input[name=cardnumber]') && bin.includes('--frame'),
      'bin help must document frames');
  });

  // Real browser, headless, isolated CDPILOT_HOME + free ports. Opt-in
  // locally; the CI `e2e` job runs it against the runner's Chrome.
  if (process.env.CDPILOT_E2E !== '1') {
    console.log('  - skipped: frames e2e (set CDPILOT_E2E=1 to run it against a headless browser)');
    return;
  }
  const fixtures = path.join(__dirname, 'fixtures', 'frames');
  let e2e = null;
  test('frames e2e: headless browser and two fixture origins start', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-frames-e2e-'));
    const [cdpPort, p1, p2] = JSON.parse(execFileSync(PYB, ['-c', [
      'import json, socket', 'ss = [socket.socket() for _ in range(3)]',
      '[s.bind(("127.0.0.1", 0)) for s in ss]',
      'print(json.dumps([s.getsockname()[1] for s in ss]))', '[s.close() for s in ss]',
    ].join('\n')], { encoding: 'utf-8', timeout: 10000 }).trim());
    const servers = [p1, p2].map((p) => spawn(PYB, ['-m', 'http.server', String(p), '--bind', '127.0.0.1'],
      { cwd: fixtures, stdio: 'ignore' }));
    const trace = path.join(home, 'cdp-trace.txt');
    const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: String(cdpPort), CHROME_HEADLESS: '1', CDPILOT_CDP_TRACE: trace };
    delete env.CDPILOT_TARGET;
    const c = (...args) => spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf-8', timeout: 60000, env });
    const stop = () => {
      c('stop');
      servers.forEach((s) => { try { s.kill(); } catch (err) { /* already gone */ } });
    };
    try {
      execFileSync(PYB, ['-c', [
        'import time, urllib.request',
        `urls = ["http://127.0.0.1:${p1}/top.html", "http://127.0.0.1:${p2}/widget.html"]`,
        'for u in urls:',
        '    for _ in range(50):',
        '        try: urllib.request.urlopen(u, timeout=1); break',
        '        except Exception: time.sleep(0.1)',
      ].join('\n')], { timeout: 20000 });
      const r = c('launch');
      assert(/CDP ready/.test(r.stdout + r.stderr), `launch: ${r.stdout}${r.stderr}`);
    } catch (err) {
      stop();
      throw err;
    }
    e2e = { c, p1, p2, stop, trace };
  });
  const ok = (r, re, what) => assert(re.test(r.stdout + r.stderr),
    `${what}: exit ${r.status}\nstdout: ${r.stdout}\nstderr: ${r.stderr}`);
  const needE2E = () => { assert(e2e, 'browser setup failed'); return e2e; };
  try {
    test('frames e2e: click/fill/type/smart-click in same-origin and cross-origin (OOPIF) iframes', () => {
      const { c, p1, p2 } = needE2E();
      const child = `http://localhost:${p2}/inner.html?nested=http://127.0.0.1:${p1}/nested.html`;
      for (const url of [`http://127.0.0.1:${p1}/top.html`,
        `http://127.0.0.1:${p1}/top.html?child=${encodeURIComponent(child)}`]) {
        c('go', url);
        ok(c('click', '#card >>> #pay-btn'), /Clicked: BUTTON Pay now/, `click ${url}`);
        ok(c('fill', 'iframe#card >>> input[name=cardnumber]', '4242'), /Filled: INPUT = 4242/, 'fill');
        ok(c('type', '--frame', 'card-frame', '#cvc', '123'), /Filled: INPUT = 123/, 'type --frame');
        ok(c('click', '#card >>> #nested >>> #deep-btn', '--entropy=on'), /Clicked: BUTTON Deep button/, 'nested');
        ok(c('smart-click', 'Deep button'), /matched inside frame iframe#card >>> iframe#nested/, 'smart-click');
        ok(c('frame', 'eval', '--frame', '#card', "[window.FRAME_NAME, document.querySelector('#status').textContent,"
          + " document.querySelector('#cc').value, document.querySelector('#cvc').value].join('|')"),
        /Result: inner\|paid\|4242\|123/, 'frame eval');
        ok(c('frame', 'eval', '--frame', '#card >>> #nested', 'document.body.dataset.log'),
          /deep-click:trusted/, 'page-coordinate click landed in the nested frame');
      }
    });

    // smart.html: page "Sign&nbsp;up" link, DISABLED Submit, "Next >>>" button;
    // widget.html (cross-origin here): newsletter button, enabled Submit, Email.
    const crossPage = (p1, p2) => `http://127.0.0.1:${p1}/smart.html?child=`
      + encodeURIComponent(`http://localhost:${p2}/widget.html`);
    const frameLog = (c) => c('frame', 'eval', '--frame', '#child', 'document.body.dataset.log').stdout;

    test('frames e2e: smart-click takes the page match (&nbsp;, disabled-only) over a cross-origin frame', () => {
      const { c, p1, p2 } = needE2E();
      c('go', crossPage(p1, p2));
      const r = c('smart-click', 'Sign up');
      // The label is printed as the page has it (NBSP); scoring collapsed it.
      ok(r, /Clicked: A "Sign\sup" \(score:100\)/, 'page link "Sign&nbsp;up" is an exact match');
      assert(!/matched inside frame/.test(r.stderr), `no frame search: ${r.stderr}`);
      ok(c('eval', 'document.body.dataset.log'), /signup;/, 'page link clicked');
      const s = c('smart-click', 'Submit');
      assert.strictEqual(s.status, 1, `disabled-only page match must exit 1: ${s.stdout}${s.stderr}`);
      ok(s, /no enabled element matches "Submit" \(1 disabled match\(es\) skipped\)/, 'old disabled message');
      const log = frameLog(c);
      assert(!/newsletter|submit/.test(log), `nothing in the frame was clicked: ${log}`);
    });

    test('frames e2e: text containing >>> stays literal; a missing first hop adds the note line', () => {
      const { c, p1, p2 } = needE2E();
      c('go', crossPage(p1, p2));
      ok(c('click', 'Next >>>'), /Clicked: BUTTON Next >>>/, 'click "Next >>>"');
      ok(c('eval', 'document.body.dataset.log'), /next;/, 'the page button was clicked');
      const r = c('click', '#nope >>> #x');
      assert.strictEqual(r.status, 1, `exit ${r.status}`);
      assert(r.stderr.includes("note: '#nope' matched no iframe; used the selector as written"), r.stderr);
    });

    test('frames e2e: smart-click "Main >>> Settings" is page text; a wrapper hop works with a note', () => {
      const { c, p1, p2 } = needE2E();
      c('go', crossPage(p1, p2));
      // iframe#child sits inside <main id="widget-box">, and the widget has a
      // "Settings" button: querySelector("Main") must not route there.
      const t = c('smart-click', 'Main >>> Settings');
      ok(t, /Clicked: A "Main >>> Settings" \(score:100\)/, 'page link');
      assert(!/note:|matched inside frame/.test(t.stderr), t.stderr);
      ok(c('eval', 'document.body.dataset.log'), /crumb;/, 'the page link was clicked');
      assert(!/settings/.test(frameLog(c)), 'nothing clicked in the frame');
      const w = c('click', '#widget-box >>> #settings');
      ok(w, /Clicked: BUTTON Settings/, 'wrapper hop');
      assert(w.stderr.includes("note: '#widget-box' is not an iframe; using the iframe inside it"), w.stderr);
      assert(/settings;/.test(frameLog(c)), 'clicked inside the frame');
    });

    test('frames e2e: smart-fill auto search stays same-origin; >>> / --frame reach a cross-origin frame', () => {
      const { c, p1, p2 } = needE2E();
      c('go', crossPage(p1, p2));
      const value = () => c('frame', 'eval', '--frame', '#child', "document.getElementById('email').value").stdout;
      const miss = c('smart-fill', 'Email', 'auto@x.test');
      assert.strictEqual(miss.status, 1, `cross-origin frame must not be auto-filled: ${miss.stdout}${miss.stderr}`);
      ok(miss, /No input found matching: "Email"/, 'old not-found path');
      assert(/Result: \s*$/.test(value()), `frame field untouched: ${value()}`);
      ok(c('smart-fill', '--frame', '#child', 'Email', 'flag@x.test'), /Filled: .* = flag@x\.test/, '--frame');
      assert(/Result: flag@x\.test/.test(value()), value());
      ok(c('smart-fill', 'iframe#child >>> Email', 'arrow@x.test'), /Filled: .* = arrow@x\.test/, '>>>');
      assert(/Result: arrow@x\.test/.test(value()), value());
      c('go', `http://127.0.0.1:${p1}/smart.html`);  // widget.html on the page's own origin
      const same = c('smart-fill', 'Email', 'same@x.test');
      ok(same, /Filled: .* = same@x\.test/, 'same-origin frame is searched');
      assert(/smart-fill: matched inside frame iframe#child/.test(same.stderr), same.stderr);
      assert(/Result: same@x\.test/.test(value()), value());
    });

    test('frames e2e: frame list without --frame prints the old output', () => {
      const { c, p1, p2 } = needE2E();
      c('go', crossPage(p1, p2));
      const r = c('frame', 'list');
      assert.strictEqual(r.stdout.trimEnd(), ['iframes (2):', '  [0] src=about:blank name= id=hidden-frame',
        `  [1] src=http://localhost:${p2}/widget.html name= id=child`].join('\n'));
    });

    test('frames e2e: no command above sent Runtime.enable (CDPILOT_CDP_TRACE)', () => {
      const { trace } = needE2E();
      const lines = fs.readFileSync(trace, 'utf8').trim().split('\n');
      assert(lines.every((l) => /^[A-Z][A-Za-z]*\.[A-Za-z]+$/.test(l)), 'method names only');
      const sent = new Set(lines);
      assert(!sent.has('Runtime.enable'), 'Runtime.enable was sent');
      assert(sent.has('DOM.resolveNode') && sent.has('Target.attachToTarget'),
        'same-process and out-of-process frames were both entered');
    });
  } finally {
    if (e2e) e2e.stop();
  }
})();

// ── Connection resilience: auto-launch, global --timeout, `open` alias ──
// Measured on ~1,225 real agent sessions: "CDP connection error. Is the
// browser running?" 292x, a hung command with no way to bound it 171x
// (issue #2), `open <url>` typed instead of `go <url>` 14x.
// None of these tests needs a browser: CDP_PORT points at a free port (or at a
// socket that accepts TCP and never answers), and CHROME_BIN points at a path
// that does not exist, so a gating bug can never start a real browser.
// Everything runs against a throwaway CDPILOT_HOME.
(function() {
  const { spawnSync } = require('child_process');
  const os = require('os');
  const PY_BIN = process.platform === 'win32' ? 'python' : 'python3';
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-autolaunch-test-'));
  const FAKE_BROWSER = path.join(home, 'no-such-browser', 'chrome');
  const LEGACY_ERR = 'CDP connection error. Is the browser running?';

  function freePort() {
    const r = spawnSync(PY_BIN, ['-c',
      'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); '
      + 'print(s.getsockname()[1]); s.close()'], { encoding: 'utf-8', timeout: 10000 });
    assert.strictEqual(r.status, 0, `freePort failed: ${r.stderr}`);
    return r.stdout.trim();
  }

  function cliEnv(extra) {
    const env = {
      ...process.env,
      CDPILOT_HOME: home,
      CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: freePort(),
      CHROME_BIN: FAKE_BROWSER,
    };
    for (const k of ['CDPILOT_TIMEOUT', 'CDPILOT_NO_AUTOLAUNCH', 'CDPILOT_TARGET']) delete env[k];
    return { ...env, ...extra };
  }

  function cli(args, extra = {}) {
    return spawnSync(process.execPath, [CLI, ...args], {
      encoding: 'utf-8', timeout: 30000, env: cliEnv(extra),
    });
  }

  const lines = (s) => (s || '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean);

  // Runs `node bin/cdpilot.js <args>` with CDP_PORT on a socket that completes
  // the TCP handshake (kernel backlog) but never sends a byte, so cdpilot's
  // CDP discovery blocks. A Python wrapper holds the socket because this
  // harness is synchronous (spawnSync blocks Node's own event loop).
  function cliAgainstSilentPort(args, extra = {}) {
    const wrapper = [
      'import json, os, socket, subprocess, sys, time',
      'srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)',
      'srv.bind(("127.0.0.1", 0))',
      'srv.listen(16)',
      'env = dict(os.environ, CDP_PORT=str(srv.getsockname()[1]))',
      't0 = time.time()',
      'r = subprocess.run(sys.argv[1:], env=env, capture_output=True, text=True, timeout=60)',
      'print(json.dumps({"code": r.returncode, "stderr": r.stderr, "elapsed": time.time() - t0}))',
    ].join('\n');
    const r = spawnSync(PY_BIN, ['-c', wrapper, process.execPath, CLI, ...args], {
      encoding: 'utf-8', timeout: 90000, env: cliEnv(extra),
    });
    assert.strictEqual(r.status, 0, `silent-port wrapper failed: ${r.stderr}`);
    return JSON.parse(r.stdout.trim());
  }

  function mainBlock() {
    const i = PY_CONTENT.indexOf('if __name__ == "__main__":');
    assert(i > 0, '__main__ block required');
    return PY_CONTENT.slice(i);
  }

  function dispatchNames() {
    const main = mainBlock();
    const names = new Set();
    for (const m of main.matchAll(/^\s*['"]([\w-]+)['"]:\s/gm)) names.add(m[1]);
    for (const m of main.matchAll(/cmd == ['"]([\w-]+)['"]/g)) names.add(m[1]);
    return names;
  }

  function skipList() {
    const m = PY_CONTENT.match(/AUTOLAUNCH_SKIP_CMDS = frozenset\(\{([\s\S]*?)\}\)/);
    assert(m, 'AUTOLAUNCH_SKIP_CMDS must be a frozenset literal');
    return new Set([...m[1].matchAll(/'([^']+)'/g)].map((x) => x[1]));
  }

  test('autolaunch: CDPILOT_NO_AUTOLAUNCH=1 keeps the exact old error and exit code', () => {
    const r = cli(['content'], { CDPILOT_NO_AUTOLAUNCH: '1' });
    assert.strictEqual(r.status, 1, `exit ${r.status}, stderr: ${r.stderr}`);
    assert.deepStrictEqual(lines(r.stderr), [LEGACY_ERR]);
  });

  test('autolaunch: a failed launch prints the old error plus the reason, exits non-zero', () => {
    const r = cli(['content']);
    assert.notStrictEqual(r.status, 0, 'must exit non-zero');
    const l = lines(r.stderr);
    assert.strictEqual(l[0], LEGACY_ERR, `stderr: ${r.stderr}`);
    assert(l[1] && l[1].startsWith('cdpilot: auto-launch failed:') && l[1].includes('no-such-browser'),
      `second stderr line must carry the launch failure reason, got: ${r.stderr}`);
    assert.strictEqual(l.length, 2, `no retry loop — exactly one attempt, got: ${r.stderr}`);
    assert(!r.stdout.includes('Launching browser'), 'launch progress must not leak into stdout');
  });

  test('launch: a browser binary that cannot start is named, with no traceback', () => {
    // Windows' FileNotFoundError text does not carry the path, so the failure
    // must be reported by cdpilot itself (caught on windows-latest CI).
    const r = cli(['launch']);
    assert.strictEqual(r.status, 1, `stderr: ${r.stderr}`);
    assert(/Cannot start browser '.*no-such-browser/.test(r.stderr), `stderr: ${r.stderr}`);
    assert(!/Traceback/.test(r.stderr), `must not print a traceback: ${r.stderr}`);
  });

  test('autolaunch: never-launch commands are real dispatch names and cover lifecycle/status/servers', () => {
    const skip = skipList();
    const nodeHandled = new Set(['status', 'setup', 'help', '--help', '-h', '--version', '-v']);
    const known = dispatchNames();
    for (const name of skip) {
      assert(known.has(name) || nodeHandled.has(name),
        `AUTOLAUNCH_SKIP_CMDS has '${name}', which is not a command in the dispatch table`);
    }
    for (const name of ['launch', 'stop', 'close', 'close-tab', 'session-close', 'project-stop',
      'stop-all', 'status', 'health', 'setup', 'help', '--help', '--version', 'version',
      'mcp', 'serve']) {
      assert(skip.has(name), `'${name}' must never auto-launch the browser`);
    }
    for (const name of ['go', 'content', 'html', 'click', 'fill', 'type', 'shot', 'eval', 'new-tab']) {
      assert(known.has(name), `'${name}' should be a dispatch name`);
      assert(!skip.has(name), `page command '${name}' must be allowed to auto-launch`);
    }
  });

  test('autolaunch: a never-launch command does not attempt a launch', () => {
    // `tabs` reaches get_tabs(); with the gate broken it would try the fake
    // browser and print an "auto-launch failed" line.
    const r = cli(['tabs']);
    assert.strictEqual(r.status, 1, `exit ${r.status}, stderr: ${r.stderr}`);
    assert.deepStrictEqual(lines(r.stderr), [LEGACY_ERR]);
  });

  test('autolaunch: go/debug/context no longer call cmd_launch directly (one gated path)', () => {
    for (const fn of ['cmd_go', 'cmd_debug', 'cmd_context_create']) {
      const m = PY_CONTENT.match(new RegExp(`async def ${fn}\\([\\s\\S]*?(?=\\n(?:async )?def )`));
      assert(m, `${fn} body required`);
      const code = m[0].split('\n').map((l) => l.replace(/#.*$/, '')).join('\n');
      assert(!/\bcmd_launch\(\)/.test(code),`${fn} must not bypass CDPILOT_NO_AUTOLAUNCH via cmd_launch()`);
    }
    assert(/def get_tabs\(\):[\s\S]{0,400}_autolaunch_if_down\(\)/.test(PY_CONTENT),
      'get_tabs must try the gated auto-launch before failing');
  });

  test('--timeout: parsed before/after the command, env fallback, flag wins, lookalikes kept', () => {
    const script = [
      'import importlib.util, json',
      `spec = importlib.util.spec_from_file_location("cdpilot_under_test", ${JSON.stringify(PY_PATH)})`,
      'mod = importlib.util.module_from_spec(spec)',
      'spec.loader.exec_module(mod)',
      'out = {}',
      'def case(name, argv, env):',
      '    try:',
      '        out[name] = list(mod._extract_timeout(argv, env))',
      '    except ValueError:',
      '        out[name] = "ValueError"',
      'case("before", ["--timeout", "10", "click", "#x"], {})',
      'case("after", ["click", "#x", "--timeout", "10"], {})',
      'case("equals", ["click", "--timeout=2.5", "#x"], {})',
      'case("env", ["click", "#x"], {"CDPILOT_TIMEOUT": "7"})',
      'case("flag_over_env", ["click", "#x", "--timeout", "3"], {"CDPILOT_TIMEOUT": "7"})',
      'case("zero_disables", ["--timeout", "0", "click"], {"CDPILOT_TIMEOUT": "7"})',
      'case("unset", ["click", "#x"], {})',
      'case("bad", ["--timeout", "abc", "click"], {})',
      'case("negative", ["click", "--timeout=-1"], {})',
      'case("bad_env", ["click"], {"CDPILOT_TIMEOUT": "soon"})',
      'case("missing", ["click", "--timeout"], {})',
      'case("lookalikes", ["eval", "f(\'--timeout 5\')", "--timeout-ms=5", "--timeouts"], {})',
      'mod.COMMANDS_WITH_OWN_TIMEOUT = frozenset({"fake-wait"})',
      'case("own", ["--timeout", "9", "fake-wait", "#x", "--timeout", "3"], {})',
      'print(json.dumps(out))',
    ].join('\n');
    const r = spawnSync(PY_BIN, ['-c', script], { encoding: 'utf-8', timeout: 20000, env: cliEnv({}) });
    assert.strictEqual(r.status, 0, `import failed: ${r.stderr}`);
    const c = JSON.parse(r.stdout.trim());
    assert.deepStrictEqual(c.before, [10, ['click', '#x']]);
    assert.deepStrictEqual(c.after, [10, ['click', '#x']]);
    assert.deepStrictEqual(c.equals, [2.5, ['click', '#x']]);
    assert.deepStrictEqual(c.env, [7, ['click', '#x']]);
    assert.deepStrictEqual(c.flag_over_env, [3, ['click', '#x']]);
    assert.deepStrictEqual(c.zero_disables, [0, ['click']]);
    assert.deepStrictEqual(c.unset, [null, ['click', '#x']]);
    for (const k of ['bad', 'negative', 'bad_env', 'missing']) {
      assert.strictEqual(c[k], 'ValueError', `${k} must be rejected`);
    }
    assert.deepStrictEqual(c.lookalikes,
      [null, ['eval', "f('--timeout 5')", '--timeout-ms=5', '--timeouts']]);
    // A command that parses its own --timeout keeps it (its own value wins);
    // the global one before the command is still read.
    assert.deepStrictEqual(c.own, [9, ['fake-wait', '#x', '--timeout', '3']]);
  });

  test('--timeout: the launcher skips a leading --timeout to find its own commands', () => {
    const v = cli(['--timeout', '5', '--version']);
    assert.strictEqual(v.status, 0, v.stderr);
    assert(v.stdout.includes(require('../package.json').version), 'should print the version');
    const h = cli(['--timeout=5', 'help']);
    assert.strictEqual(h.status, 0, h.stderr);
    assert(h.stdout.includes('USAGE') && h.stdout.includes('--timeout'), 'help must document --timeout');
  });

  test('--timeout: a malformed value exits 2 with a message', () => {
    const r = cli(['--timeout', 'abc', 'content'], { CDPILOT_NO_AUTOLAUNCH: '1' });
    assert.strictEqual(r.status, 2, `exit ${r.status}, stderr: ${r.stderr}`);
    assert(r.stderr.includes('--timeout expects a number of seconds'), r.stderr);
  });

  test('--timeout: a hung command exits 124 with the message (flag before the command)', () => {
    // Without the flag this command blocks ~3s on the silent port, then fails with exit 1.
    const r = cliAgainstSilentPort(['--timeout', '1', 'content'], { CDPILOT_NO_AUTOLAUNCH: '1' });
    assert.strictEqual(r.code, 124, `exit ${r.code}, stderr: ${r.stderr}`);
    assert(lines(r.stderr).includes('cdpilot: timed out after 1s (content)'), r.stderr);
  });

  test('--timeout: CDPILOT_TIMEOUT applies, and a flag after the command beats it', () => {
    const viaEnv = cliAgainstSilentPort(['content'],
      { CDPILOT_NO_AUTOLAUNCH: '1', CDPILOT_TIMEOUT: '1' });
    assert.strictEqual(viaEnv.code, 124, `env: exit ${viaEnv.code}, stderr: ${viaEnv.stderr}`);
    assert(lines(viaEnv.stderr).includes('cdpilot: timed out after 1s (content)'), viaEnv.stderr);
    const flagWins = cliAgainstSilentPort(['content', '--timeout', '1'],
      { CDPILOT_NO_AUTOLAUNCH: '1', CDPILOT_TIMEOUT: '60' });
    assert.strictEqual(flagWins.code, 124, `flag: exit ${flagWins.code}, stderr: ${flagWins.stderr}`);
    assert(flagWins.elapsed < 30, `flag must win over CDPILOT_TIMEOUT=60 (took ${flagWins.elapsed}s)`);
  });

  test('--timeout: expiry kills child processes, but not a released one (the launched browser)', () => {
    const killed = path.join(home, 'tracked-child-alive');
    const kept = path.join(home, 'released-child-alive');
    const child = 'import sys, time; time.sleep(2.5); open(sys.argv[1], "w").write("alive")';
    const script = [
      'import importlib.util, subprocess, sys, time',
      `spec = importlib.util.spec_from_file_location("cdpilot_under_test", ${JSON.stringify(PY_PATH)})`,
      'mod = importlib.util.module_from_spec(spec)',
      'spec.loader.exec_module(mod)',
      'mod._arm_timeout_watchdog(1.0, "orphan-check")',
      'quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)',
      `tracked = subprocess.Popen([sys.executable, "-c", ${JSON.stringify(child)}, ${JSON.stringify(killed)}], **quiet)`,
      `released = subprocess.Popen([sys.executable, "-c", ${JSON.stringify(child)}, ${JSON.stringify(kept)}], **quiet)`,
      'mod._timeout_release_child(released)',
      'time.sleep(30)',
    ].join('\n');
    const r = spawnSync(PY_BIN, ['-c', script], { encoding: 'utf-8', timeout: 20000, env: cliEnv({}) });
    assert.strictEqual(r.status, 124, `exit ${r.status}, stderr: ${r.stderr}`);
    assert(lines(r.stderr).includes('cdpilot: timed out after 1s (orphan-check)'), r.stderr);
    // Give both children time to have written their marker if still alive.
    const deadline = Date.now() + 8000;
    while (!fs.existsSync(kept) && Date.now() < deadline) {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200);
    }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500);
    assert(fs.existsSync(kept), 'a released child (the up-and-registered browser) must survive');
    assert(!fs.existsSync(killed), 'a tracked child must be killed on timeout, not orphaned');
  });

  test('open: routes to go (alias in __main__, not a separate command)', () => {
    assert(/if cmd == 'open':\s*\n\s*cmd = 'go'/.test(mainBlock()), "__main__ must alias 'open' to 'go'");
    assert(!/^\s*['"]open['"]:\s/m.test(mainBlock()), "'open' must not have its own dispatch entry");
    const r = cli(['open', 'https://example.com'], { CDPILOT_NO_AUTOLAUNCH: '1' });
    assert.strictEqual(r.status, 1, `exit ${r.status}, stderr: ${r.stderr}`);
    assert.deepStrictEqual(lines(r.stderr), [LEGACY_ERR], 'open must behave exactly like go');
  });

  test('docs: README and CHANGELOG cover --timeout, CDPILOT_TIMEOUT, CDPILOT_NO_AUTOLAUNCH', () => {
    const root = path.join(__dirname, '..');
    const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
    for (const s of ['--timeout', '`CDPILOT_TIMEOUT`', '`CDPILOT_NO_AUTOLAUNCH`']) {
      assert(readme.includes(s), `README must document ${s}`);
    }
    const changelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8');
    // Newest section is [Unreleased] between releases and the package version
    // once released; either way it must be the one describing these flags.
    const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
    const first = (changelog.match(/^## \[([^\]]+)\]/m) || [])[1];
    assert(first === 'Unreleased' || first === pkg.version,
      `newest CHANGELOG section must be [Unreleased] or [${pkg.version}], got [${first}]`);
    assert(changelog.includes('CDPILOT_NO_AUTOLAUNCH'), 'CHANGELOG must describe CDPILOT_NO_AUTOLAUNCH');
  });
})();

// ── Idle auto-close ──
// A browser cdpilot launched (explicitly or by auto-launch) closes itself after
// CDPILOT_IDLE_CLOSE minutes (default 15, 0 = off) without a cdpilot command.
// No real browser here: the watcher's decisions are exercised in-process with
// stubbed CDP answers, against a throwaway CDPILOT_HOME.
(function() {
  const { spawnSync } = require('child_process');
  const os = require('os');
  const PY_BIN = process.platform === 'win32' ? 'python' : 'python3';
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-idle-test-'));
  const IMPORT = [
    'import importlib.util, json, os, sys, time',
    `spec = importlib.util.spec_from_file_location("cdpilot_idle", ${JSON.stringify(PY_PATH)})`,
    'mod = importlib.util.module_from_spec(spec)',
    'spec.loader.exec_module(mod)',
  ].join('\n');

  function freePort() {
    const r = spawnSync(PY_BIN, ['-c',
      'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); '
      + 'print(s.getsockname()[1]); s.close()'], { encoding: 'utf-8', timeout: 10000 });
    assert.strictEqual(r.status, 0, `freePort failed: ${r.stderr}`);
    return r.stdout.trim();
  }

  function pyEnv(extra = {}) {
    const env = {
      ...process.env,
      CDPILOT_HOME: home,
      CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: freePort(),
      CDPILOT_PROJECT_ID: 'idle-proj',
      CDPILOT_NO_AUTOLAUNCH: '1',
    };
    for (const k of ['CDPILOT_TIMEOUT', 'CDPILOT_IDLE_CLOSE']) delete env[k];
    return { ...env, ...extra };
  }

  function py(script, extra = {}) {
    const r = spawnSync(PY_BIN, ['-c', IMPORT + '\n' + script], {
      encoding: 'utf-8', timeout: 30000, env: pyEnv(extra),
    });
    assert(!r.error, `python failed to run: ${r.error}`);
    const line = (r.stdout || '').split('\n').find((l) => l.startsWith('RESULT='));
    assert(line, `no result (status ${r.status}) stdout=${r.stdout} stderr=${r.stderr}`);
    return { res: JSON.parse(line.slice('RESULT='.length)), stderr: r.stderr };
  }

  const activityFile = path.join(home, 'projects', 'idle-proj', 'last-activity');

  test('idle close: CDPILOT_IDLE_CLOSE parsing (auto default 15, explicit default off, 0/off, fractions, bad value warns)', () => {
    const { res, stderr } = py(`
f = mod._idle_close_minutes
E = lambda v: {"CDPILOT_IDLE_CLOSE": v}
out = {
  "unset": f({}), "empty": f(E(" ")), "zero": f(E("0")), "off": f(E("off")), "frac": f(E("0.2")),
  "thirty": f(E("30")), "bad": f(E("abc")), "neg": f(E("-3")), "nan": f(E("nan")),
  "inf": f(E("inf")), "env": f(),
  "x_unset": f({}, auto=False), "x_env": f(E("0.2"), auto=False), "x_zero": f(E("0"), auto=False),
  "x_bad": f(E("abc"), auto=False), "x_flag": f({}, auto=False, flag="5"),
  "x_flag_wins": f(E("30"), auto=False, flag="0"), "a_flag": f(E("30"), flag="2.5"),
  "flags": [mod._idle_close_flag(a) for a in (["--idle-close", "3"], ["--idle-close=0.2"],
            ["--idle-close"], [], ["--x"])],
}
try:
    f({}, auto=False, flag="soon")
    out["bad_flag"] = "accepted"
except ValueError as e:
    out["bad_flag"] = str(e)
print("RESULT=" + json.dumps(out))
`, { CDPILOT_IDLE_CLOSE: '7' });
    const badFlag = res.bad_flag;
    delete res.bad_flag;
    assert.deepStrictEqual(res, {
      unset: 15, empty: 15, zero: 0, off: 0, frac: 0.2, thirty: 30,
      bad: 15, neg: 15, nan: 15, inf: 15, env: 7,
      x_unset: 0, x_env: 0.2, x_zero: 0, x_bad: 0, x_flag: 5, x_flag_wins: 0, a_flag: 2.5,
      flags: ['3', '0.2', '', null, null],
    });
    assert(badFlag.includes('--idle-close') && badFlag.includes("'soon'"), `bad flag must raise: ${badFlag}`);
    const warnings = stderr.split('\n').filter((l) => l.includes('ignoring CDPILOT_IDLE_CLOSE'));
    assert.strictEqual(warnings.length, 1, `one warning per process, got: ${stderr}`);
    assert(warnings[0].includes("'abc'") && warnings[0].includes('using 15'), warnings[0]);
  });

  test('idle close: auto-launch gets a watcher; explicit launch only with env or --idle-close', () => {
    // cmd_launch in-process with the browser and the watcher Popen faked.
    const { res } = py(`
spawned = []
class FakePopen:
    def __init__(self, argv, **kw):
        self.pid = 4000 + len(spawned)
        spawned.append("watcher" if mod.IDLE_WATCHER_FLAG in argv else "browser")
    def poll(self):
        return None
mod.subprocess.Popen = FakePopen
up = [False]
def fake_cdp_get(path, no_cache=False):
    if path == "/json/version" and up[0]:
        return {"webSocketDebuggerUrl": "ws://x/browser/g%d" % len(spawned)}
    return None
mod.cdp_get = fake_cdp_get
mod.CHROME_BIN = "/nonexistent/chrome"
def fast_sleep(s):  # the launch wait loop: the fake browser answers from its first round
    up[0] = True
mod.time.sleep = fast_sleep
out = {}
def run(name, env=None, **kw):
    spawned.clear(); up[0] = False
    os.environ.pop("CDPILOT_IDLE_CLOSE", None)
    if env is not None:
        os.environ["CDPILOT_IDLE_CLOSE"] = env
    code = 0
    try:
        mod.cmd_launch(**kw)
    except SystemExit as e:
        code = e.code
    out[name] = [list(spawned), code]
run("explicit")
run("explicit_env", env="0.2")
run("explicit_env0", env="0")
run("explicit_flag", idle_close="5")
run("explicit_bad_flag", idle_close="soon")
run("auto", auto=True)
run("auto_env0", env="0", auto=True)
mod.IS_MCP_SESSION = True  # a launch from the MCP server (browser_launch -> "launch")
run("mcp")
run("mcp_env0", env="0")
print("RESULT=" + json.dumps(out))
`);
    assert.deepStrictEqual(res.explicit, [['browser'], 0], 'explicit launch without env: no watcher');
    assert.deepStrictEqual(res.explicit_env, [['browser', 'watcher'], 0], 'explicit launch + env > 0: watcher');
    assert.deepStrictEqual(res.explicit_env0, [['browser'], 0]);
    assert.deepStrictEqual(res.explicit_flag, [['browser', 'watcher'], 0], 'launch --idle-close <min>: watcher');
    assert.deepStrictEqual(res.explicit_bad_flag, [[], 2], 'an invalid --idle-close exits 2 before starting a browser');
    assert.deepStrictEqual(res.auto, [['browser', 'watcher'], 0], 'auto-launch: watcher by default');
    assert.deepStrictEqual(res.auto_env0, [['browser'], 0]);
    assert.deepStrictEqual(res.mcp, [['browser', 'watcher'], 0], 'an MCP launch counts as auto: watcher by default');
    assert.deepStrictEqual(res.mcp_env0, [['browser'], 0], 'CDPILOT_IDLE_CLOSE=0 still turns it off for MCP');
    assert(/"CDPILOT_MCP_SESSION"\] = "1"/.test(PY_CONTENT) && /auto = auto or IS_MCP_SESSION/.test(PY_CONTENT),
      'MCP tool calls run with CDPILOT_MCP_SESSION=1, which cmd_launch treats as auto');
  });

  test('idle close: page fingerprint (ids + urls, no titles) and change detection are pure', () => {
    const { res } = py(`
fp, ch = mod._idle_page_fingerprint, mod._idle_pages_changed
a = [{"type": "page", "id": "1", "url": "https://a/", "title": "A"},
     {"type": "service_worker", "id": "sw", "url": "https://a/sw.js", "title": ""},
     {"type": "page", "id": "2", "url": "about:blank", "title": ""}]
b = list(reversed(a))
nav = [dict(a[0], url="https://a/next")] + a[1:]
title = [dict(a[0], title="A (1)")] + a[1:]
opened = a + [{"type": "page", "id": "3", "url": "about:blank", "title": ""}]
closed = a[:2]
worker_only = a + [{"type": "iframe", "id": "f", "url": "https://ad/", "title": ""}]
out = {
  "order_free": fp(a) == fp(b), "pages_only": len(fp(a)),
  "same": ch(fp(a), fp(b)), "nav": ch(fp(a), fp(nav)), "title": ch(fp(a), fp(title)),
  "opened": ch(fp(a), fp(opened)), "closed": ch(fp(a), fp(closed)),
  "non_page": ch(fp(a), fp(worker_only)),
  "unknown_now": ch(fp(a), fp(None)), "first_round": ch(None, fp(a)), "none": fp(None),
}
print("RESULT=" + json.dumps(out))
`);
    assert.deepStrictEqual(res, {
      order_free: true, pages_only: 2, same: false, nav: true, title: false,
      opened: true, closed: true, non_page: false, unknown_now: false, first_round: false, none: null,
    });
  });

  test('idle close: a normal command touches the activity stamp, read-only checks do not', () => {
    fs.rmSync(activityFile, { force: true });
    const t0 = Date.now() / 1000;
    const r = spawnSync(PY_BIN, [PY_PATH, 'mode'], { encoding: 'utf-8', timeout: 30000, env: pyEnv() });
    assert.strictEqual(r.status, 0, `mode failed: ${r.stderr}`);
    assert(fs.existsSync(activityFile), 'a normal command must write projects/<id>/last-activity');
    const stamp = parseFloat(fs.readFileSync(activityFile, 'utf-8'));
    assert(stamp >= t0 - 1 && stamp <= Date.now() / 1000 + 1, `stamp ${stamp} is not "now" (${t0})`);
    fs.rmSync(activityFile, { force: true });
    for (const cmd of ['health', 'version', 'projects']) {
      const q = spawnSync(PY_BIN, [PY_PATH, cmd], { encoding: 'utf-8', timeout: 30000, env: pyEnv() });
      assert(!q.error, `${cmd} failed to run: ${q.error}`);
      assert(!fs.existsSync(activityFile), `read-only \`${cmd}\` must not count as activity`);
    }
  });

  test('idle close: decision function (now, last activity, minutes) -> close?', () => {
    const { res } = py(`
f = mod._idle_should_close
print("RESULT=" + json.dumps([
  f(1000, 100, 15), f(1000, 101, 15), f(1000, 100, 0), f(1000, None, 15),
  f(1000, 2000, 15), f(1000, 988, 0.2), f(1000, 989, 0.2), f(1000, 0, None),
]))
`);
    assert.deepStrictEqual(res, [true, false, false, false, false, true, false, false]);
  });

  test('idle close: the watcher only ever closes the browser cdpilot launched', () => {
    const { res } = py(`
P = 45678
OURS = "ws://127.0.0.1:%d/devtools/browser/aaaa" % P
calls, attached = [], [False]
mod._stop_browser_on_port = lambda port, verbose=False: calls.append(port) or True
mod._idle_client_attached = lambda version: attached[0]
PAGE = {"type": "page", "id": "1", "url": "https://a/", "title": "A"}
pages = [[PAGE]]
mod._idle_page_targets = lambda port: pages[0]

def setup(registry_pid=4242, ws=OURS, token="T", activity_age=3600):
    now = time.time()
    mod._save_registry({"p1": {"port": P, "pid": registry_pid, "status": "running"}})
    mod._idle_save_state(P, {"token": token, "pid": os.getpid(), "port": P, "project_id": "p1",
                             "browser_pid": 4242, "browser_ws": OURS, "minutes": 0.2,
                             "started": now - 7200})
    mod._idle_write_activity("p1", now - activity_age)
    mod._idle_version = lambda port: {"webSocketDebuggerUrl": ws}

out = {}
setup(ws="ws://127.0.0.1:%d/devtools/browser/bbbb" % P)       # another browser took the port
out["foreign"] = [mod._idle_watcher_step(P, "T"), list(calls), mod._idle_load_state(P)]
setup(registry_pid=None)                                        # not (or no longer) launched by cdpilot
out["unowned"] = [mod._idle_watcher_step(P, "T"), list(calls), mod._idle_load_state(P)]
setup(); mod._idle_version = lambda port: None; mod._pid_alive = lambda pid: False
out["gone"] = [mod._idle_watcher_step(P, "T"), list(calls)]
setup(token="NEWER")                                            # a newer launch owns the port
out["replaced"] = [mod._idle_watcher_step(P, "T"), list(calls), (mod._idle_load_state(P) or {}).get("token")]
setup(activity_age=2)                                           # used 2 s ago
out["recent"] = [mod._idle_watcher_step(P, "T"), list(calls)]
setup(); attached[0] = True                                     # a CDP client holds a page
out["attached"] = [mod._idle_watcher_step(P, "T"), list(calls),
                   round(time.time() - mod._idle_read_activity("p1"))]
attached[0] = False
setup(); memo = {"pages": mod._idle_page_fingerprint([PAGE])}
pages[0] = [dict(PAGE, url="https://a/next")]                   # navigated outside cdpilot
out["navigated"] = [mod._idle_watcher_step(P, "T", memo=memo), list(calls),
                    round(time.time() - mod._idle_read_activity("p1")), memo["pages"][0][1]]
setup(); pages[0] = [dict(PAGE, url="https://a/next", title="(3) A")]   # only the title ticked
out["unchanged"] = [mod._idle_watcher_step(P, "T", memo=memo), list(calls)]   # -> still idle
calls.clear()
setup()
out["ours"] = [mod._idle_watcher_step(P, "T"), list(calls), mod._idle_load_state(P),
               mod._load_registry()["p1"]["status"], mod._load_registry()["p1"]["pid"]]
own = {"browser_pid": 1, "browser_ws": "ws://x/browser/a", "project_id": "p", "port": 9}
reg = {"p": {"pid": 1, "port": 9}}
v = {"webSocketDebuggerUrl": "ws://x/browser/a"}
out["pure"] = [mod._idle_owns_browser(own, reg, v), mod._idle_owns_browser(own, reg, None),
               mod._idle_owns_browser(None, reg, v), mod._idle_owns_browser(own, {}, v),
               mod._idle_owns_browser(own, {"p": {"pid": 2, "port": 9}}, v),
               mod._idle_owns_browser(own, {"p": {"pid": 1, "port": 10}}, v),
               mod._idle_owns_browser(dict(own, browser_pid=None), {"p": {"pid": None, "port": 9}}, v),
               mod._idle_owns_browser(own, reg, {"webSocketDebuggerUrl": "ws://x/browser/b"})]
print("RESULT=" + json.dumps(out))
`);
    assert.deepStrictEqual(res.foreign, ['exit', [], null], 'a different browser on the port must be left alone');
    assert.deepStrictEqual(res.unowned, ['exit', [], null], 'a browser without the launch mark must be left alone');
    assert.deepStrictEqual(res.gone, ['exit', []], 'the watcher exits once the browser is gone');
    assert.deepStrictEqual(res.replaced, ['exit', [], 'NEWER'], 'a replaced watcher exits and keeps the new record');
    assert.deepStrictEqual(res.recent, ['wait', []]);
    assert.deepStrictEqual(res.attached.slice(0, 2), ['wait', []], 'an attached CDP client counts as use');
    assert(res.attached[2] <= 2, 'an attached client refreshes the activity stamp');
    assert.deepStrictEqual(res.navigated.slice(0, 2), ['wait', []], 'a page change outside cdpilot counts as use');
    assert(res.navigated[2] <= 2, 'a page change refreshes the activity stamp');
    assert.strictEqual(res.navigated[3], 'https://a/next', 'the watcher remembers the new fingerprint');
    assert.deepStrictEqual(res.unchanged, ['closed', [45678]],
      'unchanged pages are not activity, and neither is a title the page rewrote itself');
    assert.deepStrictEqual(res.ours, ['closed', [45678], null, 'stopped', null]);
    assert.deepStrictEqual(res.pure, [true, false, false, false, false, false, false, false]);
  });

  test('idle close: watcher is spawned detached on POSIX and Windows, std streams not inherited', () => {
    const fn = (PY_CONTENT.match(/def _idle_spawn_watcher\([\s\S]*?\n\n\ndef /) || [''])[0];
    assert(/"start_new_session"\]\s*=\s*True/.test(fn), 'POSIX: own session (start_new_session=True)');
    assert(/DETACHED_PROCESS/.test(fn) && /CREATE_NEW_PROCESS_GROUP/.test(fn),
      'Windows: DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP');
    for (const s of ['stdin', 'stdout', 'stderr']) {
      assert(new RegExp(`"${s}": subprocess\\.DEVNULL`).test(fn), `${s} must be DEVNULL`);
    }
    const { res } = py(`
seen = []
class FakePopen:
    def __init__(self, argv, **kw):
        self.pid = 31337
        seen.append({"argv": argv[2:], "kw": {k: v for k, v in kw.items() if k != "env"},
                     "timeout_env": "CDPILOT_TIMEOUT" in kw["env"]})
mod.subprocess.Popen = FakePopen
mod.cdp_get = lambda path, no_cache=False: {"webSocketDebuggerUrl": "ws://x/browser/g"}
os.environ["CDPILOT_TIMEOUT"] = "5"
real, out = os.name, {}
try:  # both branches on every CI OS
    os.name = "posix"
    out["posix"] = mod._idle_spawn_watcher(99, port=45679, project_id="p1", minutes=15)
    os.name = "nt"
    out["nt"] = mod._idle_spawn_watcher(99, port=45680, project_id="p1", minutes=15)
finally:
    os.name = real
out["posix_state"] = mod._idle_load_state(45679)
out["off"] = mod._idle_spawn_watcher(99, port=45679, project_id="p1", minutes=0)
out["off_state"] = mod._idle_load_state(45679)
out["seen"] = [{"argv": s["argv"], "timeout_env": s["timeout_env"],
                "sns": s["kw"].get("start_new_session"), "flags": s["kw"].get("creationflags", 0),
                "streams": [s["kw"].get(k) == mod.subprocess.DEVNULL for k in ("stdin", "stdout", "stderr")]}
               for s in seen]
out["flag"] = mod.IDLE_WATCHER_FLAG
print("RESULT=" + json.dumps(out))
`);
    assert.strictEqual(res.posix, 31337);
    assert.strictEqual(res.nt, 31337);
    assert.strictEqual(res.off, null, 'CDPILOT_IDLE_CLOSE=0: no watcher');
    assert.strictEqual(res.off_state, null, 'turning it off retires the previous record on the port');
    assert.strictEqual(res.seen.length, 2, 'Popen must not run when idle close is off');
    const [posix, nt] = res.seen;
    const st = res.posix_state;
    assert.deepStrictEqual(posix.argv, [res.flag, '45679', st.token], 'watcher argv: flag, port, token');
    assert(st.pid === 31337 && st.browser_pid === 99 && st.browser_ws === 'ws://x/browser/g',
      `state must carry the launch mark: ${JSON.stringify(st)}`);
    assert.strictEqual(posix.sns, true);
    assert.strictEqual(posix.flags, 0, 'POSIX: no Windows creation flags');
    assert.strictEqual(nt.sns, null, 'Windows: start_new_session is POSIX-only');
    assert.strictEqual(nt.flags & 0x8, 0x8, 'DETACHED_PROCESS');
    assert.strictEqual(nt.flags & 0x200, 0x200, 'CREATE_NEW_PROCESS_GROUP');
    for (const s of res.seen) {
      assert.deepStrictEqual(s.streams, [true, true, true], 'stdin/stdout/stderr must be DEVNULL');
      assert.strictEqual(s.timeout_env, false, 'the watcher must not inherit CDPILOT_TIMEOUT');
    }
  });

  test('idle close: wired into launch, dispatcher, mcp and serve', () => {
    const launch = (PY_CONTENT.match(/def cmd_launch\(auto=False, idle_close=None\):([\s\S]*?)\n\ndef /) || [])[1] || '';
    const reg = launch.indexOf('_register_project(PROJECT_ID');
    const spawn = launch.indexOf('_idle_spawn_watcher(proc.pid');
    assert(reg > 0 && spawn > reg, 'launch spawns the watcher after registering the browser it started');
    assert(launch.indexOf('already running') < launch.indexOf('subprocess.Popen(chrome_args'),
      'an already-running browser returns before any spawn (attach never gets a watcher)');
    assert(/def _autolaunch_if_down\(\):[\s\S]*?cmd_launch\(auto=True\)/.test(PY_CONTENT),
      'auto-launch must launch with auto=True (idle close on by default)');
    const main = PY_CONTENT.slice(PY_CONTENT.indexOf('if __name__ == "__main__":'));
    assert(/'launch': lambda: cmd_launch\(idle_close=_idle_close_flag\(args\)\)/.test(main),
      'explicit launch passes --idle-close and defaults to auto=False');
    const flag = main.indexOf('if cmd == IDLE_WATCHER_FLAG:');
    assert(flag > 0 && flag < main.indexOf('_AUTOLAUNCH["cmd"] = cmd'),
      'the hidden watcher entry must run before auto-launch / timeout setup');
    assert(main.indexOf('_idle_touch_activity(cmd)') > flag, 'every dispatched command touches activity');
    const entry = (PY_CONTENT.match(/def _idle_watcher_entry\([\s\S]*?\n\n\ndef /) || [''])[0];
    assert(/memo = \{"pages": _idle_page_fingerprint\(_idle_page_targets\(port\)\)\}/.test(entry)
      && /_idle_watcher_step\(port, token, memo=memo\)/.test(entry),
      'the watcher loop must baseline and carry the page fingerprint between rounds');
    assert(/def _idle_page_targets\(port\):[\s\S]{0,200}urlopen\(.*\/json", timeout=3\)/.test(PY_CONTENT),
      'the /json read must be bounded');
    const mcp = (PY_CONTENT.match(/def _execute_tool\([\s\S]*?\n    def run\(self\)/) || [''])[0];
    assert(/_idle_write_activity\(\)/.test(mcp), 'each MCP tool call counts as activity');
    assert(/def parse_request\(self\):\s*\n\s*_idle_write_activity\(\)/.test(PY_CONTENT),
      'each serve API request counts as activity');
    const api = (PY_CONTENT.match(/def _api_create_session\([\s\S]*?\n\n\ndef /) || [''])[0];
    assert(/env\['CDPILOT_IDLE_CLOSE'\] = '0'/.test(api), 'serve owns its sessions: no idle watcher');
  });

  test('idle close: status (node) and health (python) show "idle close in Xm" / "idle close off"', () => {
    const port = 45681;
    const now = Date.now() / 1000;
    fs.mkdirSync(path.join(home, 'idle'), { recursive: true });
    const statePath = path.join(home, 'idle', `${port}.json`);
    fs.writeFileSync(statePath, JSON.stringify({
      token: 't', pid: process.pid, port, project_id: 'idle-proj', minutes: 15, started: now - 600,
    }));
    fs.mkdirSync(path.dirname(activityFile), { recursive: true });
    fs.writeFileSync(activityFile, `${now - 90}\n`);
    const js = fs.readFileSync(CLI, 'utf-8');
    const src = (js.match(/function idleCloseLabel\(port\) \{[\s\S]*?\n\}\n/) || [])[0];
    assert(src, 'bin/cdpilot.js must define idleCloseLabel');
    assert(/console\.log\(`\s*\$\{idleCloseLabel\(port\)\}/.test(js), 'runStatus must print the label');
    const label = new Function('fs', 'path', 'os', 'process', `${src}\nreturn idleCloseLabel;`)(
      fs, path, os, { env: { CDPILOT_HOME: home }, kill: process.kill.bind(process) });
    assert.strictEqual(label(port), 'idle close in 14m');
    assert.strictEqual(label(port + 1), 'idle close off', 'no watcher record -> off');
    const { res } = py(`
print("RESULT=" + json.dumps([mod._idle_status(${port}), mod._idle_status(${port + 1})]))
`);
    assert.deepStrictEqual(res[0][0], 'idle close in 14m');
    assert(res[0][1] > 780 && res[0][1] <= 810, `seconds left: ${res[0][1]}`);
    assert.deepStrictEqual(res[1], ['idle close off', null]);
    fs.writeFileSync(statePath, JSON.stringify({ pid: 900000000, minutes: 15, started: now, project_id: 'x' }));
    assert.strictEqual(label(port), 'idle close off', 'a dead watcher means off');
    assert(/info\['idle_close'\], info\['idle_close_in_s'\]/.test(PY_CONTENT), 'health reports idle_close');
  });

  test('idle close: README and CHANGELOG document CDPILOT_IDLE_CLOSE', () => {
    const root = path.join(__dirname, '..');
    const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
    assert(/\| `CDPILOT_IDLE_CLOSE` \| `15` \|/.test(readme), 'README env table needs CDPILOT_IDLE_CLOSE');
    assert(/Idle auto-close/.test(readme), 'README Reliability section needs the idle auto-close note');
    const changelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8');
    // The newest release, plus the [Unreleased] section above it if there is one.
    const secs = changelog.split(/^## \[/m);
    const unreleased = (secs[1] || '').startsWith('Unreleased]') ? secs[1] + (secs[2] || '') : (secs[1] || '');
    assert(unreleased.includes('CDPILOT_IDLE_CLOSE'), 'CHANGELOG [Unreleased] must describe CDPILOT_IDLE_CLOSE');
  });

  fs.rmSync(home, { recursive: true, force: true });
})();

// ── Session log (`cdpilot log`) ──
// No browser anywhere: CDP_PORT is a free port, CHROME_BIN does not exist and
// CDPILOT_NO_AUTOLAUNCH=1. Every scenario gets its own throwaway CDPILOT_HOME
// and a fixed CDPILOT_PROJECT_ID, so the log dir is known in advance.
(function() {
  const { spawnSync } = require('child_process');
  const os = require('os');
  const PY_BIN = process.platform === 'win32' ? 'python' : 'python3';
  const PROJECT = 'logtest-0001';
  const LEGACY_ERR = 'CDP connection error. Is the browser running?';
  const SECRET = 'hunter2-SECRET-value';
  const LOG_KEYS = ['ts', 'cmd', 'args', 'exit', 'duration_ms', 'url', 'title', 'summary',
    'error', 'files'];

  const r0 = spawnSync(PY_BIN, ['-c',
    'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); '
    + 'print(s.getsockname()[1]); s.close()'], { encoding: 'utf-8', timeout: 10000 });
  const PORT = (r0.stdout || '').trim() || '19299';

  const newHome = () => fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-log-test-'));
  const logDir = (home) => path.join(home, 'projects', PROJECT, 'log');
  const lines = (s) => (s || '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean);

  function localDay(daysAgo = 0) {
    const d = new Date();
    d.setDate(d.getDate() - daysAgo);
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  function baseEnv(home, extra) {
    const env = {
      ...process.env,
      CDPILOT_HOME: home,
      CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: PORT,
      CDPILOT_PROJECT_ID: PROJECT,
      CHROME_BIN: path.join(home, 'no-such-browser', 'chrome'),
      CDPILOT_NO_AUTOLAUNCH: '1',
    };
    for (const k of ['CDPILOT_LOG', 'CDPILOT_LOG_DAYS', 'CDPILOT_LOG_VIA', 'CDPILOT_TIMEOUT',
      'CDPILOT_TARGET', 'CDPILOT_MCP_SESSION']) delete env[k];
    return { ...env, ...extra };
  }

  function cli(home, args, extra = {}) {
    return spawnSync(process.execPath, [CLI, ...args], {
      encoding: 'utf-8', timeout: 30000, env: baseEnv(home, extra),
    });
  }

  function logFileLines(home) {
    const dir = logDir(home);
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir).filter((f) => f.endsWith('.jsonl')).sort()
      .flatMap((f) => fs.readFileSync(path.join(dir, f), 'utf-8').split('\n').filter(Boolean));
  }

  // The redaction functions are pure; run them all in one interpreter.
  let redactCache = null;
  function redacted() {
    if (redactCache) return redactCache;
    const script = `
import importlib.util, json
spec = importlib.util.spec_from_file_location("cdpilot_under_test", ${JSON.stringify(PY_PATH)})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
LONG = "x" * 60
cases = {
  "fill": ("fill", ["#pw", "hunter2"]),
  "fill_multi": ("fill", ["#pw", "my", "long", "pass", "--no-heal"]),
  "type": ("type", ["--entropy=on", "#q", "hello world"]),
  "fill_dashes": ("fill", ["#pw", "--ladder=#a,#b", "--hunter2"]),
  "smart_fill": ("smart-fill", ["Password", "S3cr3t!"]),
  "smart_select": ("smart-select", ["Country", "Turkey"]),
  "assert_value": ("assert-value", ["#pw", "hunter2"]),
  "dialog": ("dialog", ["prompt", "my answer"]),
  "assert_attr": ("assert-attr", ["#pw", "value", "hunter2"]),
  "assert_attr_href": ("assert-attr", ["a", "href", "/login"]),
  "api_key_flag": ("captcha", ["config", "--provider", "2captcha", "--api-key", "fake-value-x"]),
  "password_flag": ("x", ["--password=hunter2", "--token", "t0k3n", "--keep"]),
  "header": ("intercept", ["headers", "*", "Authorization: Bearer abc.def"]),
  "header_word": ("intercept", ["headers", "*", "Authorization", "Bearer xyz"]),
  "cookie_value": ("cookies", ["set", "sid=abc123"]),
  "cookie_save": ("cookies", ["save", "/tmp/c.json", "example.com"]),
  "eval": ("eval", ["var s = '" + LONG + "'; document.querySelector('#pw').value = 'hunter2'; 'ok'"]),
  "eval_storage": ("eval", ["localStorage.setItem('k', 'v1'); fetch('https://a.example/?token=t0k3n')"]),
  "eval_batch": ("eval-batch", [json.dumps(["document.title", "x.value === 'hunter2'"])]),
  "url": ("go", ["https://u:pw@ex.com/cb?code=XYZ123&state=ok&access_token=abc#id_token=zzz"]),
  "plain": ("go", ["https://example.com"]),
  "plain_click": ("click", ["#login"]),
  "tab_id": ("close-tab", ["E3B0C44298FC1C149AFBF4C8996FB924"]),
  "data_url": ("go", ["data:text/html,<input value=secret123>"]),
  "api_token": ("x", ["sk-ant-api03-abcdefghijklmnopqrstuvwxyz"]),
  "proxy": ("proxy", ["http://user:p4ss@proxy.local:8080"]),
}
out = {k: m._slog_redact_args(c, a) for k, (c, a) in cases.items()}
out["scrub_filled"] = m._slog_scrub_text("Filled: INPUT = hunter2-very-secret-value-th", ["hunter2-very-secret-value-that-is-long"])
out["scrub_echo"] = m._slog_scrub_text("[1] go https://x.example\\n[2] fill #pw hunter2")
out["scrub_bearer"] = m._slog_scrub_text("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijk")
out["scrub_kv"] = m._slog_scrub_text('{"password": "pw1", "api_key": "k2", "page": 3}')
out["summary_cookies"] = m._slog_summary("cookies", [], "sid=abc; theme=dark", [])
out["summary_cookie_save"] = m._slog_summary("cookies", ["save", "/tmp/c.json"], "Saved 3 cookies -> /tmp/c.json", [])
out["summary_storage"] = m._slog_summary("storage", [], '{"token": "abc"}', [])
out["summary_eval_secret"] = m._slog_summary("eval", ["document.cookie"], "sid=abc", [])
out["summary_fill"] = m._slog_summary("fill", ["#pw", "hunter2"], "Filled: INPUT = hunter2", ["hunter2"])
out["mask_same"] = m._slog_mask_url("https://example.com/path?q=cats&page=2")
print(json.dumps(out))  # ASCII: Windows stdout is cp1252 and mangles « »
`;
    const home = newHome();
    const r = spawnSync(PY_BIN, ['-c', script], {
      encoding: 'utf-8', timeout: 20000, env: baseEnv(home, {}),
    });
    assert.strictEqual(r.status, 0, `redaction script failed: ${r.stderr}`);
    redactCache = JSON.parse(r.stdout.trim());
    return redactCache;
  }
  const args = (k) => redacted()[k][0];
  const secrets = (k) => redacted()[k][1];

  test('log redaction: fill/type/smart-fill/smart-select/assert-value/dialog values', () => {
    assert.deepStrictEqual(args('fill'), ['#pw', '«redacted:7 chars»']);
    assert(secrets('fill').includes('hunter2'), 'raw value must be returned for output scrubbing');
    assert.deepStrictEqual(args('fill_multi'), ['#pw', '«redacted:12 chars»', '--no-heal']);
    assert.deepStrictEqual(args('type'), ['--entropy=on', '#q', '«redacted:11 chars»']);
    assert.deepStrictEqual(args('fill_dashes'), ['#pw', '--ladder=#a,#b', '«redacted:9 chars»'],
      'an unknown --flag on fill may be a mistyped value');
    assert.deepStrictEqual(args('smart_fill'), ['Password', '«redacted:7 chars»']);
    assert.deepStrictEqual(args('smart_select'), ['Country', '«redacted:6 chars»']);
    assert.deepStrictEqual(args('assert_value'), ['#pw', '«redacted:7 chars»']);
    assert.deepStrictEqual(args('dialog'), ['prompt', '«redacted:9 chars»']);
    assert.deepStrictEqual(args('assert_attr'), ['#pw', 'value', '«redacted:7 chars»']);
    assert.deepStrictEqual(args('assert_attr_href'), ['a', 'href', '/login']);
  });

  test('log redaction: password/token/key flags, header values, cookie values', () => {
    assert.deepStrictEqual(args('api_key_flag'),
      ['config', '--provider', '2captcha', '--api-key', '«redacted:12 chars»']);
    assert.deepStrictEqual(args('password_flag'),
      ['--password=«redacted:7 chars»', '--token', '«redacted:5 chars»', '--keep']);
    assert.deepStrictEqual(args('header'), ['headers', '*', 'Authorization: «redacted:14 chars»']);
    assert.deepStrictEqual(args('header_word'), ['headers', '*', 'Authorization', '«redacted:10 chars»']);
    assert.deepStrictEqual(args('cookie_value'), ['set', 'sid=«redacted:6 chars»']);
    assert.deepStrictEqual(args('cookie_save'), ['save', '/tmp/c.json', 'example.com']);
    const r = redacted();
    assert(r.summary_cookies.startsWith('«output not logged'), `cookie listing leaked: ${r.summary_cookies}`);
    assert.strictEqual(r.summary_cookie_save, 'Saved 3 cookies -> /tmp/c.json');
    assert(r.summary_storage.startsWith('«output not logged'), `storage leaked: ${r.summary_storage}`);
    assert(r.summary_eval_secret.startsWith('«output not logged'), 'eval reading document.cookie must not log its result');
  });

  test('log redaction: eval source kept, long string literals cut, secret literals replaced', () => {
    const src = args('eval')[0];
    assert(src.startsWith(`var s = '${'x'.repeat(40)}…«+20 chars»'`), src);
    assert(src.includes(".value = '«redacted:7 chars»'"), src);
    assert(src.includes("document.querySelector('#pw')"), 'short literals stay readable');
    assert(src.endsWith("'ok'"), src);
    const st = args('eval_storage')[0];
    assert(st.includes("setItem('k', '«redacted:2 chars»')"), st);
    assert(st.includes('?token=«redacted:5 chars»'), st);
    const batch = JSON.parse(args('eval_batch')[0]);
    assert.deepStrictEqual(batch, ['document.title', "x.value === '«redacted:7 chars»'"]);
  });

  test('log redaction: URL query/fragment/userinfo masking; plain commands untouched', () => {
    assert.deepStrictEqual(args('url'), ['https://u:«redacted:2 chars»@ex.com/cb?code=«redacted:6 chars»'
      + '&state=ok&access_token=«redacted:3 chars»#id_token=«redacted:3 chars»']);
    assert.deepStrictEqual(redacted().plain, [['https://example.com'], []]);
    assert.deepStrictEqual(redacted().plain_click, [['#login'], []]);
    assert.deepStrictEqual(args('tab_id'), ['E3B0C44298FC1C149AFBF4C8996FB924'], 'CDP ids are not secrets');
    assert.strictEqual(redacted().mask_same, 'https://example.com/path?q=cats&page=2');
    assert.deepStrictEqual(args('data_url'), ['data:text/html,«redacted:23 chars»']);
    assert.deepStrictEqual(args('api_token'), ['«redacted:39 chars»']);
    assert.deepStrictEqual(args('proxy'), ['http://user:«redacted:4 chars»@proxy.local:8080']);
  });

  test('log redaction: output text — echoed values (even cut off), run echo lines, bearer/JWT, key=value', () => {
    const r = redacted();
    assert.strictEqual(r.scrub_filled, 'Filled: INPUT = «redacted:38 chars»');
    assert.strictEqual(r.scrub_echo, '[1] go https://x.example\n[2] fill #pw «redacted:7 chars»');
    assert(!/eyJ|abcdefghijk/.test(r.scrub_bearer), r.scrub_bearer);
    assert(!r.scrub_kv.includes('pw1') && !r.scrub_kv.includes('"k2"'), r.scrub_kv);
    assert(r.scrub_kv.includes('"page": 3'), r.scrub_kv);
    assert.strictEqual(r.summary_fill, 'Filled: INPUT = «redacted:7 chars»');
  });

  test('log: one command writes exactly one JSON line with the expected fields; output unchanged', () => {
    const home = newHome();
    const r = cli(home, ['fill', '#pw', SECRET]);
    assert.strictEqual(r.status, 1, `exit ${r.status}, stderr: ${r.stderr}`);
    assert.deepStrictEqual(lines(r.stderr), [LEGACY_ERR], 'logging must not add output');
    const file = path.join(logDir(home), `${localDay()}.jsonl`);
    assert(fs.existsSync(file), `expected ${file}`);
    const raw = fs.readFileSync(file, 'utf-8');
    assert(!raw.includes('hunter2'), 'the typed value must never reach the disk');
    const got = lines(raw);
    assert.strictEqual(got.length, 1, `expected exactly one line, got ${got.length}`);
    const e = JSON.parse(got[0]);
    for (const k of LOG_KEYS) assert(k in e, `missing field ${k}`);
    assert.strictEqual(e.cmd, 'fill');
    assert.deepStrictEqual(e.args, ['#pw', `«redacted:${SECRET.length} chars»`]);
    assert.strictEqual(e.exit, 1);
    assert.strictEqual(e.error, LEGACY_ERR);
    assert(Number.isInteger(e.duration_ms) && e.duration_ms >= 0, `duration_ms: ${e.duration_ms}`);
    assert(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}([+-]\d{2}:\d{2}|Z)$/.test(e.ts), `ts: ${e.ts}`);
    assert.strictEqual(e.ts.slice(0, 10), localDay(), 'ts is local time, file is the local day');
    assert.deepStrictEqual(e.files, []);

    const v = cli(home, ['version']);
    assert.strictEqual(v.status, 0, v.stderr);
    const e2 = JSON.parse(logFileLines(home)[1]);
    assert.strictEqual(e2.cmd, 'version');
    assert.strictEqual(e2.exit, 0);
    assert(e2.summary.includes(require('../package.json').version), `summary: ${e2.summary}`);
    assert.strictEqual(e2.error, null);
  });

  // Python 3.10/3.11 drop the __main__ frame from a SystemExit's traceback
  // before atexit runs, so an exit code read from the traceback logged 0 for
  // every failed command there (CI ubuntu 3.11, 2026-09-28). Run the same
  // failing command under every interpreter this machine has.
  test('log: the logged exit code is the process exit code on every local Python', () => {
    const start = PY_CONTENT.indexOf('def _slog_exit_code');
    const body = PY_CONTENT.slice(start, PY_CONTENT.indexOf('\ndef ', start + 1));
    assert(start > 0 && !body.includes('__traceback__'), '_slog_exit_code must not read the traceback');
    assert(/\n    _SLOG\["main_done"\] = True\s*$/.test(PY_CONTENT), '__main__ must end with the main_done marker');
    const pys = ['python3.10', 'python3.11', 'python3.12', 'python3.13', PY_BIN].filter((py, i, all) =>
      all.indexOf(py) === i && spawnSync(py, ['-c', 'pass'], { timeout: 10000 }).status === 0);
    for (const py of pys) {
      const home = newHome();
      const r = spawnSync(py, [PY_PATH, 'fill', '#pw', SECRET], {
        encoding: 'utf-8', timeout: 30000, env: baseEnv(home, {}),
      });
      assert.strictEqual(r.status, 1, `${py}: exit ${r.status}, stderr: ${r.stderr}`);
      const got = logFileLines(home).map((l) => JSON.parse(l).exit);
      assert.deepStrictEqual(got, [1], `${py}: logged exit ${JSON.stringify(got)}`);
    }
  });

  // Windows pipes default to the ANSI code page (cp1252): a Turkish title or
  // an emoji crashed any command an agent ran through a pipe, and an MCP child
  // writing one code page while the server read another made the server log
  // the call twice. Both ends are UTF-8 now.
  test('output: UTF-8 on Windows pipes; MCP child and server agree on UTF-8', () => {
    const main = PY_CONTENT.slice(PY_CONTENT.indexOf('if __name__ == "__main__":'));
    const fix = main.indexOf('_stream.reconfigure(encoding="utf-8", errors="replace")');
    assert(fix > 0 && fix < main.indexOf('_slog_begin(_argv)'),
      '__main__ must switch stdout/stderr to UTF-8 on Windows before the session log wraps them');
    assert(/os\.name == "nt" and not os\.environ\.get\("PYTHONIOENCODING"\)/.test(main),
      'the switch is Windows-only and yields to a PYTHONIOENCODING the user set');
    const call = PY_CONTENT.slice(PY_CONTENT.indexOf('env[SLOG_VIA_ENV] = via'));
    const run = call.slice(0, call.indexOf('output = result.stdout'));
    assert(run.includes('env["PYTHONIOENCODING"] = "utf-8"'), 'MCP child must write UTF-8');
    assert(run.includes('encoding="utf-8", errors="replace"') && !run.includes('text=True'),
      'MCP server must read the child as UTF-8');
  });

  test('log: exit codes and output are identical with logging on and off', () => {
    for (const argv of [['version'], ['nosuchcommand'], ['fill', '#pw', SECRET], ['log', '--bogus']]) {
      const on = cli(newHome(), argv);
      const off = cli(newHome(), argv, { CDPILOT_LOG: '0' });
      assert.strictEqual(on.status, off.status, `${argv[0]}: exit ${on.status} vs ${off.status}`);
      assert.strictEqual(on.stdout, off.stdout, `${argv[0]}: stdout differs`);
      assert.strictEqual(on.stderr, off.stderr, `${argv[0]}: stderr differs`);
    }
  });

  test('log: CDPILOT_LOG=0 writes nothing', () => {
    const home = newHome();
    cli(home, ['version'], { CDPILOT_LOG: '0' });
    cli(home, ['fill', '#pw', SECRET], { CDPILOT_LOG: '0' });
    assert(!fs.existsSync(logDir(home)), 'no log dir may be created');
  });

  test('log: an unwritable log dir never changes the exit code (one stderr warning)', () => {
    const home = newHome();
    // `log` is a file where the directory should be: fails on every OS.
    fs.mkdirSync(path.dirname(logDir(home)), { recursive: true });
    fs.writeFileSync(logDir(home), 'not a directory');
    const v = cli(home, ['version']);
    assert.strictEqual(v.status, 0, v.stderr);
    assert(v.stdout.includes(require('../package.json').version), v.stdout);
    const warn = lines(v.stderr).filter((l) => l.includes('session log not written'));
    assert.strictEqual(warn.length, 1, `expected one warning, stderr: ${v.stderr}`);
    const f = cli(home, ['fill', '#pw', SECRET]);
    assert.strictEqual(f.status, 1, f.stderr);
    assert.strictEqual(lines(f.stderr)[0], LEGACY_ERR);
    assert.strictEqual(lines(f.stderr).length, 2, `error + one warning, got: ${f.stderr}`);
    assert(!f.stderr.includes('hunter2'), 'the warning must not echo the value');
    // A read-only directory (POSIX; root ignores permissions).
    if (process.platform !== 'win32' && !(process.getuid && process.getuid() === 0)) {
      const home2 = newHome();
      fs.mkdirSync(logDir(home2), { recursive: true });
      fs.chmodSync(logDir(home2), 0o500);
      try {
        const ro = cli(home2, ['fill', '#pw', SECRET]);
        assert.strictEqual(ro.status, 1, ro.stderr);
        assert.strictEqual(lines(ro.stderr)[0], LEGACY_ERR);
        assert(lines(ro.stderr)[1].includes('session log not written'), ro.stderr);
      } finally {
        fs.chmodSync(logDir(home2), 0o700);
      }
    }
  });

  test('log: `log --json` round-trips the file; table/--md/--path; reading adds nothing', () => {
    const home = newHome();
    cli(home, ['fill', '#pw', SECRET]);
    cli(home, ['version']);
    cli(home, ['go', 'https://example.com/?session=abc123&page=2']);
    const before = logFileLines(home);
    assert.strictEqual(before.length, 3);
    const j = cli(home, ['log', '--json']);
    assert.strictEqual(j.status, 0, j.stderr);
    assert.deepStrictEqual(lines(j.stdout), before, '--json prints the raw lines');
    assert.deepStrictEqual(lines(j.stdout).map((l) => JSON.parse(l)), before.map((l) => JSON.parse(l)));
    // Windows pipes are cp1252 by default; the output must still be the UTF-8 lines.
    const cp = cli(home, ['log', '--json'], { PYTHONIOENCODING: 'cp1252' });
    assert.deepStrictEqual(lines(cp.stdout), before, 'cp1252 stdout must still print UTF-8');
    const t = cli(home, ['log']);
    assert.strictEqual(t.status, 0, t.stderr);
    assert(t.stdout.includes('fill #pw «redacted:') && t.stdout.includes('version'), t.stdout);
    assert(t.stdout.includes('! ' + LEGACY_ERR.slice(0, 20)), 'failed commands show their error');
    const md = cli(home, ['log', '--md']);
    assert.strictEqual(md.status, 0, md.stderr);
    for (const h of ['### Pages visited', '### Actions', '### Errors', '### Files produced']) {
      assert(md.stdout.includes(h), `--md must have "${h}"`);
    }
    assert(md.stdout.includes('session=«redacted:6 chars»&page=2'), md.stdout);
    for (const out of [j.stdout, t.stdout, md.stdout]) {
      assert(!out.includes('hunter2') && !out.includes('abc123'), 'no secret in any view');
    }
    const p = cli(home, ['log', '--path']);
    assert.strictEqual(p.stdout.trim(), logDir(home));
    assert.strictEqual(cli(home, ['log', '--days', '3']).status, 0);
    assert.strictEqual(cli(home, ['log', '--days=0']).status, 1, '--days must be >= 1');
    assert.deepStrictEqual(logFileLines(home), before, '`log` must not log itself');
  });

  test('log: retention deletes day files older than CDPILOT_LOG_DAYS on the first write of a day', () => {
    const home = newHome();
    const dir = logDir(home);
    fs.mkdirSync(dir, { recursive: true });
    for (const f of ['2000-01-01.jsonl', `${localDay(20)}.jsonl`, `${localDay(14)}.jsonl`,
      `${localDay(3)}.jsonl`, 'notes.txt']) fs.writeFileSync(path.join(dir, f), '{}\n');
    cli(home, ['version']);
    const left = fs.readdirSync(dir).sort();
    assert.deepStrictEqual(left,
      [`${localDay(14)}.jsonl`, `${localDay(3)}.jsonl`, `${localDay()}.jsonl`, 'notes.txt'].sort(),
      `default 14 days: ${left}`);

    const home2 = newHome();
    fs.mkdirSync(logDir(home2), { recursive: true });
    fs.writeFileSync(path.join(logDir(home2), `${localDay(3)}.jsonl`), '{}\n');
    cli(home2, ['version'], { CDPILOT_LOG_DAYS: '2' });
    assert(!fs.existsSync(path.join(logDir(home2), `${localDay(3)}.jsonl`)), 'CDPILOT_LOG_DAYS=2');

    // Not the first write today: nothing is pruned.
    const home3 = newHome();
    fs.mkdirSync(logDir(home3), { recursive: true });
    fs.writeFileSync(path.join(logDir(home3), `${localDay()}.jsonl`), '');
    fs.writeFileSync(path.join(logDir(home3), '2000-01-01.jsonl'), '{}\n');
    cli(home3, ['version']);
    assert(fs.existsSync(path.join(logDir(home3), '2000-01-01.jsonl')), 'prune only on a day\'s first write');
  });

  test('log: a command killed by --timeout still writes its line (exit 124)', () => {
    const home = newHome();
    const wrapper = [
      'import json, os, socket, subprocess, sys',
      'srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)',
      'srv.bind(("127.0.0.1", 0))',
      'srv.listen(16)',
      'env = dict(os.environ, CDP_PORT=str(srv.getsockname()[1]))',
      'r = subprocess.run(sys.argv[1:], env=env, capture_output=True, text=True, timeout=60)',
      'print(json.dumps({"code": r.returncode, "stderr": r.stderr}))',
    ].join('\n');
    const r = spawnSync(PY_BIN, ['-c', wrapper, process.execPath, CLI, '--timeout', '1', 'content'], {
      encoding: 'utf-8', timeout: 90000, env: baseEnv(home, {}),
    });
    assert.strictEqual(r.status, 0, r.stderr);
    assert.strictEqual(JSON.parse(r.stdout.trim()).code, 124);
    const got = logFileLines(home).map((l) => JSON.parse(l));
    assert.strictEqual(got.length, 1, `lines: ${got.length}`);
    assert.strictEqual(got[0].exit, 124);
    assert.strictEqual(got[0].error, 'cdpilot: timed out after 1s (content)');
  });

  test('log: MCP lists browser_log; a tool call is logged once (via mcp:<tool>), browser_log reads it', () => {
    const home = newHome();
    const reqs = [
      { jsonrpc: '2.0', id: 1, method: 'tools/list' },
      { jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'browser_fill', arguments: { selector: '#pw', value: SECRET } } },
      { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'browser_log', arguments: { format: 'json' } } },
    ];
    const r = spawnSync(PY_BIN, [PY_PATH, 'mcp'], {
      input: reqs.map((x) => JSON.stringify(x)).join('\n') + '\n',
      encoding: 'utf-8', timeout: 60000, env: baseEnv(home, {}),
    });
    const res = lines(r.stdout).map((l) => JSON.parse(l));
    const tool = res.find((x) => x.id === 1).result.tools.find((t) => t.name === 'browser_log');
    assert(tool, 'browser_log must be in tools/list');
    assert(tool.description.length > 80 && /read-only/i.test(tool.description), tool.description);
    assert.deepStrictEqual(tool.inputSchema.properties.format.enum, ['table', 'md', 'json']);
    assert(/"browser_log":\s*lambda a: \["log"\]/.test(PY_CONTENT), 'tool_map must route browser_log to `log`');
    const logged = logFileLines(home).map((l) => JSON.parse(l));
    assert.strictEqual(logged.length, 1, `one line per tool call (no double logging), got ${logged.length}`);
    assert.strictEqual(logged[0].cmd, 'fill');
    assert.strictEqual(logged[0].via, 'mcp:browser_fill');
    assert.strictEqual(logged[0].exit, 1);
    const call = res.find((x) => x.id === 3).result;
    assert.strictEqual(call.isError, false);
    assert.deepStrictEqual(JSON.parse(call.content[0].text), logged[0]);
    assert(!r.stdout.includes('hunter2') && !logFileLines(home).join('').includes('hunter2'));
  });

  test('log: wired into dispatch, never auto-launches, documented (README, CHANGELOG, help)', () => {
    assert(/'log':\s*lambda:\s*cmd_log\(\*args\)/.test(PY_CONTENT), "'log' must be in sync_cmds");
    const main = PY_CONTENT.slice(PY_CONTENT.indexOf('if __name__ == "__main__":'));
    assert(/_slog_begin\(_argv\)/.test(main), '__main__ must start the session log');
    const skip = PY_CONTENT.match(/AUTOLAUNCH_SKIP_CMDS = frozenset\(\{([\s\S]*?)\}\)/)[1];
    assert(/'log'/.test(skip), "'log' must never launch the browser");
    const root = path.join(__dirname, '..');
    const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
    for (const s of ['cdpilot log --md', '`CDPILOT_LOG`', '`CDPILOT_LOG_DAYS`']) {
      assert(readme.includes(s), `README must mention ${s}`);
    }
    const changelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8');
    // The newest release, plus the [Unreleased] section above it if there is one.
    const secs = changelog.split(/^## \[/m);
    const unreleased = (secs[1] || '').startsWith('Unreleased]') ? secs[1] + (secs[2] || '') : (secs[1] || '');
    assert(unreleased && unreleased.includes('cdpilot log'), 'CHANGELOG [Unreleased] must describe `cdpilot log`');
    const help = run('--help');
    assert(help.includes('log --md') && help.includes('CDPILOT_LOG'), 'bin help must document log');
    assert(PY_CONTENT.slice(0, 2000).includes('CDPILOT_LOG=0'), 'python __doc__ must document CDPILOT_LOG');
  });
})();

// ── Summary ──

console.log(`\n  ${passed} passed, ${failed} failed\n`);
process.exit(failed > 0 ? 1 : 0);

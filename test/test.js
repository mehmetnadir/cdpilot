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

// One private home for run(): without it every run() wrote last-activity (and
// a profile dir) under the real ~/.cdpilot/projects/<cwd project>/. The Node
// launcher ignores CDPILOT_HOME when it derives the profile path, so
// CDPILOT_PROFILE is set too.
const RUN_HOME = fs.mkdtempSync(path.join(require('os').tmpdir(), 'cdpilot-run-'));

function run(args = '') {
  return execSync(`node ${CLI} ${args} 2>&1`, {
    timeout: 10000,
    encoding: 'utf-8',
    // CDP_PORT avoids a conflict with a real browser; CDPILOT_LOG=0 keeps its
    // commands out of the session log.
    env: { ...process.env, CDP_PORT: '19222', CDPILOT_LOG: '0',
           CDPILOT_HOME: RUN_HOME, CDPILOT_PROFILE: path.join(RUN_HOME, 'profile') },
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

// ── CDPILOT_HOME honored everywhere (bin/cdpilot.js) ──
// bin/cdpilot.js used to build the registry/profile paths straight from
// os.homedir(), ignoring CDPILOT_HOME even when it was set — a test run
// that isolated CDPILOT_HOME still wrote real project dirs into the
// developer's actual ~/.cdpilot (src/cdpilot.py already honored it; the
// Node entry point didn't). Every path must go through the cdpilotHome()
// helper, which mirrors src/cdpilot.py's
// `os.environ.get("CDPILOT_HOME") or os.path.expanduser("~/.cdpilot")`.
(function() {
  const os = require('os');
  const tmpCdpilotHome = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-home-test-'));
  const fakeUserHome = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-fakehome-test-'));

  test('CDPILOT_HOME: setup writes only under CDPILOT_HOME, never under HOME/.cdpilot', () => {
    execSync(`node ${CLI} setup`, {
      timeout: 15000,
      encoding: 'utf-8',
      env: {
        ...process.env,
        CDP_PORT: '19222',
        CDPILOT_LOG: '0',
        CDPILOT_HOME: tmpCdpilotHome,
        HOME: fakeUserHome,
        // os.homedir() reads USERPROFILE first on Windows — override both
        // so this test isolates HOME on every CI platform.
        USERPROFILE: fakeUserHome,
        // An explicit CDPILOT_PROFILE (a caller isolating its run) would put
        // the profile elsewhere; this test is about the default location.
        CDPILOT_PROFILE: '',
      },
    });

    const fakeHomeCdpilotDir = path.join(fakeUserHome, '.cdpilot');
    assert(!fs.existsSync(fakeHomeCdpilotDir),
      `Nothing should be created under HOME/.cdpilot, found: ${fakeHomeCdpilotDir}`);

    // `setup` creates the project's profile dir under
    // CDPILOT_HOME/projects/<project-id>/profile — that's the file this
    // regression checks lands in the right place.
    const projectsDir = path.join(tmpCdpilotHome, 'projects');
    assert(fs.existsSync(projectsDir),
      `Expected CDPILOT_HOME/projects to exist, found none under ${tmpCdpilotHome}`);
    const projectDirs = fs.readdirSync(projectsDir);
    assert(projectDirs.length > 0, 'Expected at least one project dir under CDPILOT_HOME/projects');
    const profileDir = path.join(projectsDir, projectDirs[0], 'profile');
    assert(fs.existsSync(profileDir),
      `Expected the profile dir under CDPILOT_HOME, found none: ${profileDir}`);
  });

  fs.rmSync(tmpCdpilotHome, { recursive: true, force: true });
  fs.rmSync(fakeUserHome, { recursive: true, force: true });
})();

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
# Ownership proof (#26 re-review): d1 is the pid cdpilot recorded for this
# port, the way launch registers the browser it started.
os.makedirs(os.environ["CDPILOT_HOME"], exist_ok=True)
with open(os.path.join(os.environ["CDPILOT_HOME"], "registry.json"), "w") as f:
    json.dump({"version": 1, "projects": {"stop-proj": {"cwd": "/x", "port": P, "pid": d1.pid,
        "profile_dir": "/x", "status": "running"}}}, f)
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
  // (PUT since Chrome refuses GET /json/new; see the new-tab behaviour test.)
  const newTab = PY_CONTENT.match(/async def cmd_new_tab[\s\S]*?\/json\/new\?[\s\S]*?_mark_owned_tab\(data\.get\("id"\)\)/);
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
      for (const k of ['CDPILOT_WS_POOL', 'CDPILOT_TARGET', 'CDPILOT_TIMEOUT', 'CDPILOT_PRESS_MS']) delete env[k];
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

  test('frames: rewrite sends Runtime/DOM into the frame and maps mouse x/y by the frame scale and offset', () => {
    const src = extractPyFunc(PY_CONTENT, '_frame_route_rewrite');
    assert(src, '_frame_route_rewrite must be extractable');
    const out = execFileSync(PYB, ['-c', src + `

import asyncio, json
class Route:
    context_id, session_id, chain, dirty, xform = 42, 'S1', [('p', 'o')], True, (1.0, 1.0, 0.0, 0.0)
calls = []
async def _frame_route_settle(route):
    calls.append('settle')
async def _frame_route_refresh_offset(route):
    calls.append('measure')
    route.xform, route.dirty = (0.5, 2.0, 100.0, 1000.0), False  # scale .5 / 2, then offset
    return route.xform
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
print(json.dumps({'out': res, 'calls': calls, 'orig': cmds[2][2]}))
`], { encoding: 'utf-8', timeout: 10000 });
    const r = JSON.parse(out.trim());
    assert.deepStrictEqual(r.out, [
      [1, 'Runtime.evaluate', { expression: '1', contextId: 42 }, 'S1'],
      [2, 'DOM.describeNode', { objectId: 'o' }, 'S1'],
      [3, 'Input.dispatchMouseEvent', { type: 'mousePressed', x: 105, y: 1040 }],
      [4, 'Input.dispatchMouseEvent', { type: 'mouseReleased', x: 105, y: 1040 }],
      [5, 'Input.dispatchKeyEvent', { type: 'keyDown', key: 'a' }],
      [6, 'Page.navigate', { url: 'about:blank' }],
      [7, 'Runtime.evaluate', { expression: '2', contextId: 99 }, 'S1'],
      [8, 'Runtime.evaluate', { expression: '3' }, 'EXPLICIT'],
      [9, 'Input.dispatchMouseEvent', { type: 'mouseMoved', x: 102.5, y: 1010 }],
    ]);
    // Once per page-JS run before mouse input, not per event; the page first
    // settles (two drawn frames), then the offset is measured.
    assert.deepStrictEqual(r.calls, ['settle', 'measure', 'settle', 'measure']);
    assert.deepStrictEqual(r.orig, { type: 'mousePressed', x: 10, y: 20 }, "caller's params must not be mutated");
  });

  test('frames: a frame point maps through every hop with its scale (transform: scale, zoom), nested', () => {
    // Hop box: [left, top, border+padding x, y, scale x, y] (_FRAME_BOX_FN).
    // Outer iframe at (100, 1000), 16 px border+padding, transform: scale(.5);
    // inner at (10, 20), 6 px border, zoom: 2. The point (40, 50) in the inner
    // frame: (10 + (6 + 40) * 2, 20 + (6 + 50) * 2) = (102, 132) in the outer
    // frame, (100 + (16 + 102) * .5, 1000 + (16 + 132) * .5) = (159, 1074) on the page.
    const src = pyFuncs(['_frame_points', '_frame_xform']) + `
import json, sys
boxes = [[100, 1000, 16, 16, 0.5, 0.5], [10, 20, 6, 6, 2, 2]]
sx, sy, tx, ty = _frame_xform(boxes)
print(json.dumps({'points': _frame_points(boxes, 40, 50), 'xform': [sx, sy, tx, ty],
                  'via_xform': [tx + sx * 40, ty + sy * 50], 'none': _frame_points([], 7, 8)}))
`;
    const r = JSON.parse(execFileSync(PYB, ['-c', src], { encoding: 'utf-8', timeout: 10000 }).trim());
    assert.deepStrictEqual(r.points, [[159, 1074], [102, 132], [40, 50]], 'page, outer frame, inner frame');
    assert.deepStrictEqual(r.via_xform, [159, 1074], 'the rewrite\'s single transform agrees');
    assert.deepStrictEqual(r.xform, [1, 1, 119, 1024]);
    assert.deepStrictEqual(r.none, [[7, 8]], 'no hops: the page point');
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
    assert.strictEqual(fakeResults._released['cdpilot-frame'], sent['DOM.resolveNode'],
      'every resolved frame document is released');
    assert(fakeResults._released['cdpilot-click'] > 0, 'real-click objects are released too');
    assert(sent['Target.attachToTarget'] > 0, 'out-of-process frames: flat session');
    const r = fake('routing');
    assert.strictEqual(r.css.context, r.contexts.card, 'the main-world context id');
    assert.strictEqual(r.nested.context, r.contexts.nested);
  });

  test('frames (fake CDP): no usable main-world id: isolated world, one note line for every frame command', () => {
    // A V8 objectId format change would land every frame command here: say so.
    const r = fake('isolated_fallback');
    assert.deepStrictEqual(r.eval.contexts, r.eval.isolated, 'eval ran in the isolated world');
    assert.strictEqual(r.eval.stdout, 'Result: card|z\n');
    const note = "note: frame 'iframe#card': its page context was not reachable; using an isolated world"
      + ' (same DOM, no page JS globals)\n';
    for (const key of ['eval', 'list', 'click', 'twice']) {
      assert.strictEqual(r[key].stderr, note, `${key}: exactly one note line`);
    }
    assert.deepStrictEqual(r.twice.res.map((x) => x[0]), ['ok', 'ok'], 'both commands ran');
  });

  test('frames (fake CDP): click is one click; real mouse input with --entropy=on and in frames', () => {
    // clicks: el.click() calls cdpilot caused; pressed: Input mousePressed
    // events; hits: hit-tests, [object, x, y] per document (the <iframe> on
    // the way, then the target), before the press and again with the
    // release. Main used el.click() and
    // then the mouse with entropy (two clicks), el.click() in frames
    // (isTrusted false), and put window.__cdpilot_waitFor on every page.
    const r = fake('click_input');
    const near = (p, x, y) => Math.abs(p[0] - x) <= 2 && Math.abs(p[1] - y) <= 2; // entropy jitter: +-2
    for (const [key, at] of [['page_entropy', [40, 50]], ['frame', [140, 1050]],
      ['frame_entropy', [150, 1070]], ['oopif', [45, 57]], ['scaled', [145, 1060]]]) {
      const k = r[key];
      assert.deepStrictEqual(k.res, ['ok', null], `${key}: ${k.stderr}`);
      assert.deepStrictEqual(k.clicks, [], `${key}: no script click`);
      assert.strictEqual(k.pressed.length, 1, `${key}: one mousePressed`);
      assert.strictEqual(k.released.length, 1, `${key}: one mouseReleased`);
      assert(near(k.pressed[0], ...at), `${key}: pressed at ${k.pressed[0]}, want ${at} (page coordinates)`);
      assert.strictEqual(k.stderr, '', `${key}: no note`);
    }
    const twice = (a) => a.concat(a);  // before the press, and with the release
    assert.deepStrictEqual(r.frame.hits, twice([['owner:card', 140, 1050], ['el:card:#btn', 40, 50]]));
    assert.deepStrictEqual(r.oopif.hits, twice([['owner:pay', 45, 57], ['el:pay:#btn', 40, 50]]));
    // #card: transform: scale(.5) at (100, 1000); #nested inside: zoom: 2 at (10, 20).
    assert.deepStrictEqual(r.scaled.hits, twice([['owner:card', 145, 1060], ['owner:nested', 90, 120],
      ['el:nested:#btn', 40, 50]]), 'each hop checked at its own point');
    assert.strictEqual(r.frame_entropy.hits.length, 6, 'nested: top, the outer frame, the target; twice');
    assert.deepStrictEqual(r.page_plain.clicks, [['top', 'script']], 'plain page click: unchanged (el.click())');
    assert.strictEqual(r.page_plain.pressed.length + r.page_plain.hits.length, 0, 'plain page click: no mouse');
    assert.deepStrictEqual(r.frame_nobox.clicks, [['card', 'script']], 'no box: el.click() is the fallback');
    assert.strictEqual(r.frame_nobox.pressed.length, 0, 'no box: no mouse events');
    for (const [key, k] of Object.entries(r)) {
      if (typeof k !== 'object') continue;
      assert.deepStrictEqual(k.leaks, [], `${key}: no helper on window`);
      if (key === 'moved' || key === 'moved_entropy') continue;  // released elsewhere: not claimed
      if (key !== 'blocker_error') assert(/^Clicked: BUTTON /.test(k.stdout), `${key}: ${k.stdout}`);
    }
  });

  test('frames (fake CDP): hit-test fails (banner over the iframe or the target): script click + one note, no mouse', () => {
    const r = fake('click_input');
    const cases = [
      ['covered_frame', 'card', 'iframe#card >>> #btn is covered by div#cookie.banner'],
      ['covered_target', 'nested', 'iframe#card >>> iframe#nested >>> #btn is covered by div.overlay'],
      ['covered_page', 'top', '#btn is covered by div#cookie'],  // --entropy=on on the page
    ];
    for (const [key, frame, what] of cases) {
      const k = r[key];
      assert.deepStrictEqual(k.res, ['ok', null], key);
      assert.strictEqual(k.stderr, `note: ${what} at the click point; used a script click\n`, key);
      assert.deepStrictEqual(k.clicks, [[frame, 'script']], `${key}: the target, by script`);
      assert.deepStrictEqual(k.pressed, [], `${key}: no mouse press (it would hit the cover)`);
      assert.strictEqual(k.stdout, 'Clicked: BUTTON #btn\n', key);
    }
    assert.strictEqual(r.covered_frame.hits.length, 2, 'the target frame is checked too, in one batch');
  });

  test('frames (fake CDP): the hit-test is repeated with the release; a target that moved: note, no script click', () => {
    // The target moves once the page handled mousedown: the press is
    // completed (one press, one release) and the mouse click is not claimed.
    // No el.click(): the page already got a trusted mousedown/mouseup (and,
    // on a menu that opens on mousedown, a native click on a common
    // ancestor), so a script click would click twice.
    const r = fake('click_input');
    for (const [key, label, was] of [['moved', 'iframe#card >>> #btn', 'div#wrap'],
      ['moved_entropy', '#btn', 'body']]) {
      const k = r[key];
      assert.deepStrictEqual(k.res, ['ok', null], key);
      assert.strictEqual(k.pressed.length, 1, `${key}: one press`);
      assert.strictEqual(k.released.length, 1, `${key}: the release completed`);
      assert.deepStrictEqual(k.clicks, [], `${key}: no script click`);
      assert.strictEqual(k.stderr, `note: ${label} was no longer under the mouse when the button was released`
        + ` (${was} was); the press and release reached the page, so no script click (it could click twice)\n`, key);
      assert.strictEqual(k.stdout, 'Pressed (released elsewhere, not clicked): BUTTON #btn\n', `${key}: not "Clicked"`);
      assert.strictEqual(k.hits.length % 2, 0, `${key}: the same checks, twice`);
    }
  });

  test('frames (fake CDP): pointer-events: none on the target or its iframe is named so in the note', () => {
    const r = fake('click_input');
    assert.strictEqual(r.pe_target.stderr,
      'note: iframe#card >>> #btn has pointer-events: none; used a script click\n');
    assert.strictEqual(r.pe_frame.stderr,
      'note: iframe#card >>> #btn is inside iframe#card, which has pointer-events: none; used a script click\n');
    for (const key of ['pe_target', 'pe_frame']) {
      assert.deepStrictEqual(r[key].clicks, [['card', 'script']], key);
      assert.deepStrictEqual(r[key].pressed, [], `${key}: no press`);
    }
  });

  test("frames (fake CDP): hover/dblclick/rightclick go through cdpilot's input blocker, restored after an error", () => {
    const r = fake('mouse_cmds');
    for (const key of ['dblclick_page', 'rightclick_page', 'hover_page', 'dblclick_frame', 'rightclick_oopif',
      'hover_frame']) {
      assert.deepStrictEqual(r[key].res, ['ok', null], `${key}: ${r[key].stderr}`);
      assert.deepStrictEqual(r[key].blocker, ['none', ''], `${key}: opened around the input, restored`);
      assert(r[key].mouse.length > 0, `${key}: mouse input sent`);
    }
    assert.deepStrictEqual(r.dblclick_frame.mouse[0], ['mousePressed', 140, 1050], 'frame: page coordinates');
    assert.deepStrictEqual(r.dblclick_error.res, ['raise', 'RuntimeError']);
    assert.deepStrictEqual(r.dblclick_error.blocker, ['none', ''], 'restored in finally');
    for (const key of ['dblclick_visual_off', 'hover_visual_off']) {
      assert.strictEqual(r[key].blocker_calls, 0, `${key}: visual feedback off: no blocker call`);
      assert(r[key].mouse.length > 0, key);
    }
  });

  test('frames (fake CDP): --timeout while the blocker is open: the watchdog restores it before exiting', () => {
    // os._exit skips `finally`; the watchdog thread restores the blocker first.
    const r = fake('timeout_restore');
    assert.deepStrictEqual(r.exits, [124]);
    assert.strictEqual(r.fd2, 'cdpilot: timed out after 0.05s (click)\n');
    assert.deepStrictEqual(r.open_before, ['ws://fake/devtools/page/1']);
    assert.deepStrictEqual(r.blocker, ['none', ''], 'made opaque again by the watchdog');
    assert.deepStrictEqual(r.open_after, []);
  });

  // Real clicks hold the button like a person (CDPILOT_PRESS_MS, default
  // 40-120 ms): main sent mousePressed and mouseReleased 0.1-6 ms apart.
  // The events' own timestamps (what the page's event.timeStamp shows) are
  // exactly the drawn hold apart. On the wire, the fake stamps each event as
  // it arrives: the hold starts at the press's reply, so the release is never
  // early; a busy machine can wake it late (240 ms seen under load), so the
  // wire has only a sanity cap (a seconds-for-ms bug) above.
  const HOLD_SLACK_MS = 1000;
  const heldOk = (press, what) => {
    assert(press.gaps.length > 0, `${what}: a press and a release`);
    assert.strictEqual(press.stamps.length, press.gaps.length, `${what}: every event carries a timestamp`);
    for (const g of press.stamps) {
      assert(g >= 40 && g <= 120, `${what}: timestamps ${g.toFixed(2)} ms apart, want 40-120`);
    }
    for (const g of press.gaps) {
      assert(g >= 40 && g <= HOLD_SLACK_MS, `${what}: held ${g.toFixed(2)} ms on the wire, want >= 40`);
    }
  };

  test('press hold (fake CDP): real clicks hold the button 40-120 ms (frames, OOPIF, --entropy=on, rightclick, bot clicks)', () => {
    const r = fake('press_hold');
    for (const key of ['frame', 'oopif', 'page_entropy', 'frame_entropy', 'rightclick', 'dblclick', 'dblclick_page',
      'humanize_click', 'click_held', 'tw_plain', 'tw_humanized']) {
      const k = r[`default_${key}`];
      if (Array.isArray(k.res)) assert.deepStrictEqual(k.res, ['ok', null], `${key}: ${k.stderr}`);
      assert.strictEqual(k.stderr, '', `${key}: no note`);
      heldOk(k.press, key);
    }
    assert.deepStrictEqual(r.default_rightclick.press.buttons, ['right']);
    const [lo, median, hi] = r.draws.hold;  // 2000 draws of the hold itself
    assert(lo >= 40 && hi <= 120, `draws inside 40-120: ${lo}..${hi}`);
    assert(median > 55 && median < 90, `log-normal around the geometric mean (~69 ms): ${median}`);
    assert(hi - lo > 60, `spread over the range: ${lo}..${hi}`);
  });

  test('press hold (fake CDP): a release that misses (moved, replaced, page navigated): note, no script click, not "Clicked"', () => {
    const r = fake('press_hold');
    const tail = '; the press and release reached the page, so no script click (it could click twice)\n';
    const gone = 'was gone by the time the mouse button was released (the page replaced or left it)';
    const moved = 'Pressed (released elsewhere, not clicked): BUTTON #btn\n';
    const replaced = 'Pressed (the page replaced or left it, not clicked): BUTTON #btn\n';
    for (const [key, why, line] of [
      ['moved', 'was no longer under the mouse when the button was released (div#wrap was)', moved],
      ['removed', gone, replaced], ['navigated', gone, replaced]]) {
      for (const tag of ['default', 'instant']) {
        const k = r[`${tag}_${key}`];
        assert.deepStrictEqual(k.res, ['ok', null], `${tag} ${key}: ${k.stderr}`);
        if (tag === 'default') heldOk(k.press, key);
        assert.deepStrictEqual(k.clicks, [], `${tag} ${key}: no script click`);
        assert.strictEqual(k.stderr, `note: iframe#card >>> #btn ${why}${tail}`, `${tag} ${key}`);
        assert.strictEqual(k.stdout, line, `${tag} ${key}`);
        assert.deepStrictEqual(k.blocker, ['none', ''], `${tag} ${key}: blocker restored`);
      }
    }
  });

  test('click outcome (fake CDP): release missed -> exit 3 ("moved"); target replaced / page left -> exit 0 ("gone")', () => {
    // #30 script-clicked a target that moved; the held press made that a
    // double click, so it is not clicked now, and exit 3 keeps `click && next`
    // from going on as if it had been (1 stays "error").
    const r = fake('click_outcome');
    const m = r.moved;
    assert.deepStrictEqual([m.res, m.exit, m.misses, m.clicks], [['ok', null], 3, ['moved'], []]);
    assert.strictEqual(m.stdout, 'Pressed (released elsewhere, not clicked): BUTTON #btn\n');
    for (const key of ['gone', 'navigated']) {
      const g = r[key];
      assert.deepStrictEqual([g.res, g.exit, g.misses, g.clicks], [['ok', null], 0, ['gone'], []], key);
      assert.strictEqual(g.stdout, 'Pressed (the page replaced or left it, not clicked): BUTTON #btn\n', key);
      assert.strictEqual(g.pressed.length + g.released.length, 2, `${key}: one press, one release`);
    }
    const c = r.clicked;
    assert.deepStrictEqual([c.res, c.exit, c.misses, c.stdout], [['ok', null], 0, [], 'Clicked: BUTTON #btn\n']);
  });

  test('click outcome (fake CDP): no reply to the release check is "unknown" (exit 3), not "gone"', () => {
    const u = fake('click_outcome').no_reply;
    assert.deepStrictEqual([u.res, u.exit, u.misses, u.clicks], [['ok', null], 3, ['unknown'], []]);
    assert.strictEqual(u.stdout, 'Pressed (release not confirmed, not clicked): BUTTON #btn\n');
    assert.strictEqual(u.stderr, 'note: iframe#card >>> #btn could not be checked when the mouse button was released'
      + ' (no reply from the page in time); the press and release were sent, so no script click (it could click twice)\n');
    assert.deepStrictEqual(u.blocker, ['none', '']);
  });

  test('click outcome (fake CDP): a target detached before the press is an error (exit 1), no press, no script click', () => {
    const d = fake('click_outcome').detached;
    assert.deepStrictEqual(d.res, ['exit', 1]);
    assert.strictEqual(d.stderr, 'Error: iframe#card >>> #btn: the target is no longer in the page\n');
    assert.deepStrictEqual([d.clicks, d.pressed, d.stdout, d.misses], [[], [], '', []]);
    assert.deepStrictEqual(d.blocker, ['none', ''], 'blocker restored');
  });

  test('click outcome (fake CDP): batch runs every step; exit 1 if one failed, else 3 if one was not clicked, else 0', () => {
    // batch used to exit 0 even when steps failed; exit 3 must not hide them.
    const b = fake('click_outcome').batch;
    const notClicked = { cmd: 'click', status: 'not_clicked', clicked: false, reason: 'moved' };
    const unsupported = { cmd: 'nope', status: 'error', error: 'Unsupported command: nope' };
    const evalOk = { cmd: 'eval', status: 'ok' };
    assert.deepStrictEqual(b.miss.res, ['exit', 3], 'miss only: 3');
    assert.deepStrictEqual(b.miss.steps, [notClicked, evalOk], 'every step ran');
    assert.deepStrictEqual(b.mixed.res, ['exit', 1], 'a failed step and a miss: 1');
    assert.deepStrictEqual(b.mixed.steps, [notClicked, unsupported, evalOk]);
    assert.deepStrictEqual(b.errors.res, ['exit', 1], 'errors only: 1 (was 0)');
    assert.deepStrictEqual(b.errors.steps, [unsupported, evalOk]);
    assert.deepStrictEqual(b.ok.res, ['ok', null], 'all ok: 0');
    assert.deepStrictEqual(b.ok.steps, [{ cmd: 'click', status: 'ok' }, evalOk]);
  });

  test('click outcome (fake CDP): run goes on after every line; exit 1 if one failed, else 3 if one was not clicked, else 0', () => {
    const r = fake('click_outcome').run;
    assert.deepStrictEqual(r.miss, { res: ['exit', 3], result: 'Result: 1 passed, 0 failed, 1 not clicked, 2 total' });
    assert.deepStrictEqual(r.mixed, { res: ['exit', 1], result: 'Result: 0 passed, 1 failed, 1 not clicked, 2 total' });
    assert.deepStrictEqual(r.errors, { res: ['exit', 1], result: 'Result: 1 passed, 1 failed, 2 total' });
    assert.deepStrictEqual(r.ok, { res: ['ok', null], result: 'Result: 1 passed, 0 failed, 1 total' });
  });

  test('click outcome (fake CDP): MCP: exit 3 and "gone" are not errors; a JSON first line says clicked: false', () => {
    const r = fake('click_outcome').mcp;
    for (const [key, reason] of [['moved', 'moved'], ['gone', 'gone'], ['unknown', 'unknown']]) {
      assert.strictEqual(r[key].isError, false, key);
      assert.deepStrictEqual(JSON.parse(r[key].content[0].text), { clicked: false, reason }, key);
      assert(/^Pressed \(/.test(r[key].content[1].text), key);
    }
    assert.deepStrictEqual(r.clicked, { content: [{ type: 'text', text: 'Clicked: BUTTON Pay' }], isError: false });
    assert.strictEqual(r.error.isError, true, 'exit 1 is still an error');
    assert(!/clicked/.test(r.error.content[0].text), 'no status line for an error');
    // Only the click tools: page text from browser_eval that starts with the
    // same words gets no status line, and its exit 3 stays an error.
    assert.deepStrictEqual(r.eval_text, { content: [{ type: 'text',
      text: 'Pressed (released elsewhere, not clicked): BUTTON fake' }], isError: false });
    assert.strictEqual(r.eval_exit3.isError, true);
    assert.strictEqual(r.eval_exit3.content.length, 1, 'no status line');
    assert.strictEqual(r.smart_click.isError, false);
    assert.deepStrictEqual(JSON.parse(r.smart_click.content[0].text), { clicked: false, reason: 'moved' });
  });

  test('click outcome: exit 3 is documented (help in src and bin, README, CHANGELOG)', () => {
    const root = path.join(__dirname, '..');
    const bin = fs.readFileSync(path.join(root, 'bin', 'cdpilot.js'), 'utf8');
    const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
    const changelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8');
    const unreleased = changelog.slice(changelog.indexOf('## [Unreleased]'), changelog.indexOf('## [0.9.3]'));
    for (const [name, text] of [['src help', PY_CONTENT.slice(0, PY_CONTENT.indexOf('__version__ = '))], ['bin help', bin], ['README', readme],
      ['CHANGELOG [Unreleased]', unreleased]]) {
      assert(/exit 3/i.test(text) && /release missed the target, not clicked/.test(text), `${name} documents exit 3`);
    }
  });

  test('x bot (fake CDP): _tw_click_sel clicks the box it found (the reply\'s result.value), held', () => {
    // _tw_click_sel read res[802].value, which is never there: it returned
    // False and never clicked. It reads result.value now.
    const r = fake('press_hold');
    for (const key of ['tw_plain', 'tw_humanized']) {
      const k = r[`default_${key}`];
      assert.strictEqual(k.res, true, `${key}: found and clicked`);
      assert.strictEqual(k.pressed.length, 1, key);
      assert(Math.abs(k.pressed[0][0] - 25) <= 2 && Math.abs(k.pressed[0][1] - 40) <= 2,
        `${key}: the centre of {x:10,y:20,w:30,h:40}: ${k.pressed[0]}`);
      assert.strictEqual(k.press.gaps.length, 1, `${key}: one press and release`);
    }
    assert.strictEqual(r.instant_tw_plain.res, true);
  });

  test('press hold (fake CDP): dblclick is two held clicks, clickCount 1 then 2, 60-140 ms apart', () => {
    const r = fake('press_hold');
    for (const key of ['default_dblclick', 'default_dblclick_page']) {
      const p = r[key].press;
      assert.deepStrictEqual(p.counts, [1, 2], `${key}: clickCount 1, then 2`);
      assert.strictEqual(p.gaps.length, 2, `${key}: two press/release pairs`);
      heldOk(p, key);
      assert.strictEqual(p.between.length, 1, key);
      assert(p.between[0] >= 60 && p.between[0] <= HOLD_SLACK_MS,
        `${key}: pause ${p.between[0]} ms, want 60-140`);
    }
    const [glo, ghi] = r.draws.gap;
    assert(glo >= 60 && ghi <= 140, `gap draws inside 60-140: ${glo}..${ghi}`);
  });

  test("press hold (fake CDP): cdpilot's input blocker is transparent around the whole held press, and only then", () => {
    const r = fake('press_hold');
    for (const key of ['frame', 'oopif', 'page_entropy', 'frame_entropy', 'moved', 'dblclick', 'dblclick_page',
      'rightclick']) {
      const k = r[`default_${key}`];
      assert.deepStrictEqual(k.blocker, ['none', ''], `${key}: opened once, restored once`);
      assert.strictEqual(k.press.blocker, true, `${key}: press and release inside the open window`);
    }
  });

  test('press hold (fake CDP): CDPILOT_PRESS_MS=0-0 restores the instant click (dblclick pause too)', () => {
    const r = fake('press_hold');
    const gaps = [];
    for (const key of ['frame', 'oopif', 'page_entropy', 'frame_entropy', 'moved', 'rightclick', 'dblclick',
      'dblclick_page', 'humanize_click', 'click_held']) {
      const k = r[`instant_${key}`];
      if (k.res) assert.deepStrictEqual(k.res, ['ok', null], key);
      gaps.push(...k.press.gaps);
    }
    gaps.sort((a, b) => a - b);
    assert(gaps[Math.floor(gaps.length / 2)] < 15, `median gap under 15 ms: ${gaps}`);
    assert(gaps[0] < 15, `min gap under 15 ms: ${gaps}`);
    for (const key of ['frame', 'dblclick', 'rightclick']) {
      for (const g of r[`instant_${key}`].press.stamps) assert(g === 0, `${key}: timestamps equal: ${g}`);
    }
    assert.deepStrictEqual(r.instant_dblclick.press.counts, [1, 2]);
    assert(r.instant_dblclick.press.between[0] < 15, `no dblclick pause: ${r.instant_dblclick.press.between}`);
    assert.deepStrictEqual(r.instant_frame.blocker, ['none', '']);
  });

  test('press hold: CDPILOT_PRESS_MS min-max is validated; a bad value warns once and falls back to 40-120', () => {
    const p = fake('press_hold').parse;
    assert.deepStrictEqual(p.None.range, [40, 120]);
    assert.deepStrictEqual(p['0-0'].range, [0, 0]);
    assert.strictEqual(p['0-0'].zero_gap, 0, '0-0: no dblclick pause');
    assert.deepStrictEqual(p[' 30 - 60 '].range, [30, 60]);
    assert.deepStrictEqual(p['10.5-20'].range, [10.5, 20]);
    assert.deepStrictEqual(p['0-2000'].range, [0, 2000]);
    for (const good of ['None', '0-0', ' 30 - 60 ', '10.5-20', '0-2000']) assert.strictEqual(p[good].stderr, '', good);
    for (const bad of ['abc', '50', '120-40', '5-3000', '-5-10']) {
      assert.deepStrictEqual(p[bad].range, [40, 120], `${bad}: the default`);
      assert.deepStrictEqual(p[bad].again, [40, 120], bad);
      assert.strictEqual(p[bad].stderr, `cdpilot: warning: ignoring CDPILOT_PRESS_MS='${bad}' (min-max in ms,`
        + ' 0 <= min <= max <= 2000); using 40-120\n', `${bad}: one warning`);
    }
  });

  test('press hold (fake CDP): --timeout fires mid-hold: the watchdog releases the button, then restores the blocker', () => {
    const r = fake('timeout_hold');  // CDPILOT_PRESS_MS=1000-1000, --timeout 0.3 s
    for (const key of ['click', 'dblclick']) {
      const k = r[key];
      assert.strictEqual(k.exits.length, 1, `${key}: the watchdog fired`);
      const e = k.exits[0];
      assert.strictEqual(e.code, 124, key);
      // The command was still inside its 1 s hold: this release is the watchdog's.
      assert.deepStrictEqual(e.mouse.filter((m) => m !== 'mouseMoved'), ['mousePressed', 'mouseReleased'],
        `${key}: the page is not left with the button down: ${e.mouse}`);
      assert.strictEqual(e.released_before_restore, true, `${key}: released while the blocker was still open`);
      assert.deepStrictEqual(e.blocker, ['none', ''], `${key}: made opaque again by the watchdog`);
      assert.deepStrictEqual(e.open, [], key);
      assert.deepStrictEqual(e.presses_open, [], key);
      assert.strictEqual(k.fd2, `cdpilot: timed out after 0.3s (${key})\n`);
    }
  });

  test('press hold (fake CDP): a command cancelled mid-hold releases the button in finally (page coordinates)', () => {
    const r = fake('timeout_hold');
    for (const key of ['cancel_click', 'cancel_dblclick']) {
      const k = r[key];
      const m = k.mouse.filter((e) => e[0] !== 'mouseMoved');
      assert.deepStrictEqual(m.map((e) => e[0]), ['mousePressed', 'mouseReleased'], `${key}: ${JSON.stringify(k.mouse)}`);
      assert.deepStrictEqual(m[1].slice(1).map(Number), [140, 1050], `${key}: released where it was pressed`);
      assert.deepStrictEqual(k.blocker, ['none', ''], key);
      assert.deepStrictEqual(k.presses_open, [], key);
      assert.deepStrictEqual(k.open_after, [], key);
    }
  });

  test('input blocker: a blocker left transparent is made opaque again by the next command', () => {
    // INPUT_BLOCKER_ON runs at the start of every command (visual feedback on).
    const js = fake('timeout_restore').blocker_on_js;
    const stale = { id: 'cdpilot-input-blocker', style: { pointerEvents: 'none' } };
    const document = { getElementById: (id) => (id === stale.id ? stale : null) };
    const out = require('vm').runInNewContext(js, { document });
    assert.strictEqual(out, 'blocker already active');
    assert.strictEqual(stale.style.pointerEvents, '', 'opaque again');
  });

  test("frames (fake CDP): cdpilot's input blocker is transparent only around the click, restored after an error", () => {
    const r = fake('click_input');
    for (const key of ['blocker', 'blocker_entropy']) {
      assert.deepStrictEqual(r[key].blocker, ['none', ''], `${key}: opened, then restored`);
      assert.strictEqual(r[key].pressed.length, 1, `${key}: the click went through`);
    }
    const e = r.blocker_error;  // the mouse press raises
    assert.deepStrictEqual(e.res, ['raise', 'RuntimeError']);
    assert.deepStrictEqual(e.blocker, ['none', ''], 'restored in finally');
    assert.deepStrictEqual(r.frame.blocker, [], 'no blocker on the page: nothing toggled');
  });

  test('frames (fake CDP): the settle wait runs in isolated worlds and is cut off after 0.3 s', () => {
    const r = fake('click_input');
    assert.strictEqual(r.settle_timeout, 0.3);
    // [frame, context is an isolated world]: the page's own rAF/setTimeout are never used.
    assert.deepStrictEqual(r.frame.settles, [['card', true], ['top', true]], 'the frame, then the top page');
    assert.deepStrictEqual(r.oopif.settles, [['pay', true], ['top', true]]);
    assert.deepStrictEqual(r.frame_entropy.settles, [['nested', true], ['top', true]]);
    assert.deepStrictEqual(r.page_entropy.settles, [['top', true]]);
    assert.deepStrictEqual(r.page_plain.settles, [], 'plain page click: no wait');
    const h = r.settle_hang;  // neither wait ever answers
    assert.deepStrictEqual(h.pressed, [[140, 1050]], 'the click still happens');
    assert(h.elapsed >= 0.55 && h.elapsed < 1.2, `two 0.3 s caps: ${h.elapsed}`);
    assert(r.settle_ok.elapsed < 0.3, `answered waits cost nothing: ${r.settle_ok.elapsed}`);
  });

  test('frames (fake CDP): smart-click in a frame: the finder picks, the mouse clicks (hit-tested); page act unchanged', () => {
    const r = fake('smart_real_click');
    const f = r.smart_frame;
    assert.deepStrictEqual(f.acts, [['card', 'strict']]);
    assert.deepStrictEqual(f.act_real, [true], 'frame search act: __cdpilotRealClick');
    assert.deepStrictEqual([f.res.x, f.res.y, f.res.via], [140, 1050, 'mouse'], 'page coordinates');
    assert.deepStrictEqual(f.pressed, [[140, 1050]]);
    assert.deepStrictEqual(f.clicks, []);
    const c = r.smart_covered;
    assert.strictEqual(c.res.via, 'script');
    assert.deepStrictEqual(c.clicks, [['card', 'script']]);
    assert.deepStrictEqual(c.pressed, []);
    assert(c.stderr.includes('note: "Pay" is covered by div#cookie at the click point; used a script click'),
      c.stderr);
    assert.deepStrictEqual(r.smart_page.act_real, [false], 'page act unchanged');
    assert.deepStrictEqual(r.smart_page.pressed, []);
    assert.deepStrictEqual(r.smart_routed.acts, [['card', 'loose']]);
    assert.deepStrictEqual(r.smart_routed.act_real, [true], '--frame act: __cdpilotRealClick');
    assert.deepStrictEqual(r.smart_routed.pressed, [[140, 1050]]);
  });

  test('frames (fake CDP): CDPILOT_CDP_TRACE lists each CDP method sent, names only', () => {
    fake('routing');
    const lines = fs.readFileSync(fakeTrace, 'utf8').trim().split(/\r?\n/); // Windows text mode: \r\n
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
    // Visual feedback on (as in MCP sessions): cdpilot's input blocker covers the page.
    const cShow = (...args) => spawnSync(process.execPath, [CLI, ...args],
      { encoding: 'utf-8', timeout: 60000, env: { ...env, CDPILOT_SHOW: '1' } });
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
    e2e = { c, cShow, p1, p2, stop, trace, env };
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

    test('frames e2e: clicks are single and trusted (--entropy=on, frames, smart-click); no helper global on window', () => {
      const { c, p1, p2 } = needE2E();
      const child = `http://localhost:${p2}/inner.html?nested=http://127.0.0.1:${p1}/nested.html`;
      const count = (log, re) => (log.match(re) || []).length;
      for (const url of [`http://127.0.0.1:${p1}/top.html`,
        `http://127.0.0.1:${p1}/top.html?child=${encodeURIComponent(child)}`]) {
        c('go', url);
        const pageLog = () => c('eval', 'document.body.dataset.log').stdout;
        ok(c('click', '#top-btn', '--entropy=on'), /Clicked: BUTTON Top button/, `entropy click ${url}`);
        assert.strictEqual(pageLog().trim(), 'top-click:trusted;', 'one trusted click');
        assert.strictEqual(c('eval', 'typeof window.__cdpilot_waitFor').stdout.trim(), 'undefined',
          'no page global after click');

        ok(c('click', '#card >>> #pay-btn'), /Clicked: BUTTON Pay now/, 'frame click');
        const payLog = c('frame', 'eval', '--frame', '#card', 'document.body.dataset.log').stdout;
        assert.strictEqual(count(payLog, /pay-click:/g), 1, `one click: ${payLog}`);
        assert(payLog.includes('pay-click:trusted'), `real mouse input: ${payLog}`);
        ok(c('frame', 'eval', '--frame', '#card', 'typeof window.__cdpilot_waitFor'), /Result: undefined\s*$/,
          'no global in the frame');

        const deepLog = () => c('frame', 'eval', '--frame', '#card >>> #nested', 'document.body.dataset.log').stdout;
        ok(c('click', '#card >>> #nested >>> #deep-btn', '--entropy=on'), /Clicked: BUTTON Deep button/, 'nested');
        assert.strictEqual(count(deepLog(), /deep-click:/g), 1, `entropy: one click: ${deepLog()}`);
        ok(c('smart-click', 'Deep button'), /matched inside frame iframe#card >>> iframe#nested/, 'smart-click');
        const log = deepLog();
        assert.strictEqual(count(log, /deep-click:trusted/g), 2, `smart-click in a frame is trusted: ${log}`);
        assert.strictEqual(count(log, /deep-click:script/g), 0, log);
        assert.strictEqual(pageLog().trim(), 'top-click:trusted;', 'frame clicks stayed in the frames');
      }
    });

    // Each page on its own origin, and with its frame cross-origin (out of process).
    const bothOrigins = (p1, p2, page) => {
      const child = `http://localhost:${p2}/inner.html?nested=http://127.0.0.1:${p1}/nested.html`;
      return [`http://127.0.0.1:${p1}/${page}`, `http://127.0.0.1:${p1}/${page}?child=${encodeURIComponent(child)}`];
    };

    // Mouse events into <body data-presses> as type:button:detail:timeStamp;
    // reading returns them with performance.now() of the same document.
    const PRESS_TYPES = "['mousemove', 'pointerdown', 'mousedown', 'mouseup', 'dblclick', 'contextmenu']";
    const LISTEN_JS = `document.body.dataset.presses = ''; ${PRESS_TYPES}.forEach(function (t) {`
      + ' document.addEventListener(t, function (e) { document.body.dataset.presses += t + ":" + e.button'
      + ' + ":" + e.detail + ":" + e.timeStamp.toFixed(2) + ";"; }, true); }); "listening"';
    const READ_JS = 'document.body.dataset.presses + "|now:" + performance.now().toFixed(2)';
    const pressEvents = (out) => {
      const now = +(/\|now:([\d.]+)/.exec(out) || [])[1];
      const ev = [...out.matchAll(/(mousemove|pointerdown|mousedown|mouseup|dblclick|contextmenu):(\d):(\d):([\d.]+);/g)]
        .map((m) => ({ t: m[1], button: +m[2], detail: +m[3], ts: +m[4] }));
      assert(now > 0 && ev.length > 0, `events read: ${out}`);
      // No event is stamped in the future, and a press never precedes the move before it.
      let lastMove = -Infinity;
      for (const e of ev) {
        assert(e.ts <= now, `${e.t} at ${e.ts} is after performance.now() ${now}`);
        if (e.t === 'mousemove') lastMove = e.ts;
        if (e.t === 'pointerdown' || e.t === 'mousedown') {
          assert(e.ts >= lastMove, `${e.t} at ${e.ts} precedes the mousemove at ${lastMove}: ${out}`);
        }
      }
      return ev;
    };
    const holds = (ev) => {
      const downs = ev.filter((e) => e.t === 'mousedown');
      const ups = ev.filter((e) => e.t === 'mouseup');
      assert.strictEqual(downs.length, ups.length, 'a mouseup for every mousedown');
      return downs.map((d, i) => {
        const held = ups[i].ts - d.ts;
        // The events carry their own timestamps; timeStamp is coarsened (0.1 ms).
        assert(held >= 39.8 && held <= 120.2, `press ${i}: held ${held.toFixed(1)} ms, want 40-120`);
        return held;
      });
    };

    test('frames e2e: real clicks hold the button 40-120 ms, stamped after the last move (page, click @ref, dblclick 1/2)', () => {
      const { c, p1 } = needE2E();
      c('go', `http://127.0.0.1:${p1}/top.html`);
      ok(c('eval', LISTEN_JS), /listening/, 'listeners');
      ok(c('click', '#top-btn', '--entropy=on'), /Clicked: BUTTON Top button/, 'entropy click');
      ok(c('dblclick', '#top-btn'), /Double-clicked/, 'dblclick');
      ok(c('rightclick', '#top-btn'), /Right-clicked/, 'rightclick');
      const snap = c('a11y-snapshot').stdout;
      const ref = (/@(\d+) \[button\] "Top button"/.exec(snap) || [])[1];
      assert(ref, `a11y-snapshot lists the button: ${snap}`);
      ok(c('click', `@${ref}`), new RegExp(`Clicked @${ref}`), 'click @ref');
      const out = c('eval', READ_JS).stdout;
      const ev = pressEvents(out);
      const downs = ev.filter((e) => e.t === 'mousedown');
      assert.deepStrictEqual(downs.map((e) => [e.button, e.detail]), [[0, 1], [0, 1], [0, 2], [2, 1], [0, 1]], out);
      holds(ev);
      const ups = ev.filter((e) => e.t === 'mouseup');
      const pause = downs[2].ts - ups[1].ts;
      assert(pause >= 59.8 && pause <= HOLD_SLACK_MS, `dblclick pause ${pause.toFixed(1)} ms, want 60-140`);
      assert.strictEqual(ev.filter((e) => e.t === 'dblclick').length, 1, `one dblclick event: ${out}`);
      assert.strictEqual(ev.filter((e) => e.t === 'contextmenu').length, 1, `one contextmenu event: ${out}`);
    });

    test('frames e2e: frame clicks (same-origin and OOPIF) hold 40-120 ms, the press stamped after the last move', () => {
      const { c, p1, p2 } = needE2E();
      for (const url of bothOrigins(p1, p2, 'top.html')) {
        c('go', url);
        ok(c('frame', 'eval', '--frame', '#card', LISTEN_JS), /listening/, `listeners ${url}`);
        ok(c('click', '#card >>> #pay-btn'), /Clicked: BUTTON Pay now/, `frame click ${url}`);
        ok(c('click', '#card >>> #pay-btn', '--entropy=on'), /Clicked: BUTTON Pay now/, `entropy frame click ${url}`);
        const out = c('frame', 'eval', '--frame', '#card', READ_JS).stdout;
        assert.strictEqual(holds(pressEvents(out)).length, 2, `two presses in the frame: ${out}`);
      }
    });

    test('frames e2e: a menu that opens on mousedown / a view replaced on mousedown: one native click, no script click, not "Clicked"', () => {
      const { c, p1 } = needE2E();
      const tail = '; the press and release reached the page, so no script click (it could click twice)';
      for (const [url, prefix, flags, read] of [
        [`http://127.0.0.1:${p1}/pressmenu.html`, '', ['--entropy=on'], (js) => c('eval', js).stdout],
        [`http://127.0.0.1:${p1}/top.html?child=pressmenu.html`, '#card >>> ', [],
          (js) => c('frame', 'eval', '--frame', '#card', js).stdout.replace(/^Result: /, '')]]) {
        c('go', url);
        const label = prefix ? 'iframe#card >>> ' : '';
        const m = c('click', `${prefix}#menu-btn`, ...flags);
        ok(m, /^Pressed \(released elsewhere, not clicked\): BUTTON Menu/m, `menu ${url}`);
        assert.strictEqual(m.status, 3, `menu: exit 3 (pressed, release missed the target): ${m.stderr}`);
        assert(!/Clicked/.test(m.stdout), m.stdout);
        assert(m.stderr.includes(`note: ${label}#menu-btn was no longer under the mouse when the button was released`)
          && m.stderr.includes(tail), m.stderr);
        const s = c('click', `${prefix}#spa-btn`, ...flags);
        ok(s, /^Pressed \(the page replaced or left it, not clicked\): BUTTON Next page/m, `spa ${url}`);
        assert.strictEqual(s.status, 0, `spa: the page reacted, exit 0: ${s.stderr}`);
        assert(s.stderr.includes(`note: ${label}#spa-btn was gone by the time the mouse button was released`), s.stderr);
        // The release landed on the menu item; the browser's own click went
        // to div#wrap once; nothing was clicked again by script.
        assert.strictEqual(read('document.body.dataset.log').trim(), 'item-up;wrap-click:trusted;spa-down;', url);
      }
    });

    const count = (log, re) => (log.match(re) || []).length;
    const inFrame = (c, frame, js) => c('frame', 'eval', '--frame', frame, js).stdout;

    test('frames e2e: a cookie banner over the iframe: script click on the target, note, banner not clicked', () => {
      const { c, p1, p2 } = needE2E();
      for (const url of bothOrigins(p1, p2, 'covered.html')) {
        c('go', url);
        const r = c('click', '#card >>> #pay-btn');
        ok(r, /Clicked: BUTTON Pay now/, `click ${url}`);
        assert(r.stderr.includes('note: iframe#card >>> #pay-btn is covered by div#cookie.banner.consent'
          + ' at the click point; used a script click'), r.stderr);
        assert(/Result: pay-click:script;\s*$/.test(inFrame(c, '#card', 'document.body.dataset.log')),
          'the target, clicked once by the script fallback');
        assert.strictEqual(c('eval', 'document.body.dataset.log').stdout.trim(), '', 'the banner was not clicked');
      }
    });

    test('frames e2e: iframes with transform: scale(.5) and zoom: 2: a trusted click lands on the target', () => {
      const { c, p1, p2 } = needE2E();
      for (const url of bothOrigins(p1, p2, 'scaled.html')) {
        c('go', url);
        for (const frame of ['#scaled', '#zoomed']) {
          const r = c('click', `${frame} >>> #pay-btn`);
          ok(r, /Clicked: BUTTON Pay now/, `${frame} ${url}`);
          assert(!/note:/.test(r.stderr), r.stderr);
          const log = inFrame(c, frame, 'document.body.dataset.log');
          assert.strictEqual(count(log, /pay-click:/g), 1, `${frame}: one click: ${log}`);
          assert(log.includes('pay-click:trusted'), `${frame}: real mouse input: ${log}`);
        }
        const page = c('eval', 'document.body.dataset.log').stdout;
        assert(!/page-click/.test(page), `no click landed on the page: ${page}`);
      }
    });

    test('frames e2e: a page whose requestAnimationFrame/setTimeout never call back: frame click within 1 s of normal', () => {
      const { c, p1, p2 } = needE2E();
      const [plain, stubbed] = [bothOrigins(p1, p2, 'top.html'), bothOrigins(p1, p2, 'raf.html')];
      for (let i = 0; i < 2; i++) {
        const timed = (url) => {
          c('go', url);
          const t0 = Date.now();
          const r = c('click', '#card >>> #pay-btn');
          const ms = Date.now() - t0;
          ok(r, /Clicked: BUTTON Pay now/, url);
          assert(inFrame(c, '#card', 'document.body.dataset.log').includes('pay-click:trusted'), `trusted: ${url}`);
          return ms;
        };
        const normalMs = timed(plain[i]);
        const stubbedMs = timed(stubbed[i]);
        assert(stubbedMs < normalMs + 1000, `stubbed timers: ${stubbedMs} ms vs ${normalMs} ms`);
      }
    });

    test('frames e2e: CDPILOT_SHOW=1 (input blocker): frame, smart and --entropy=on clicks land, trusted; blocker restored', () => {
      const { c, cShow, p1, p2 } = needE2E();
      for (const url of bothOrigins(p1, p2, 'top.html')) {
        c('go', url);
        const blocker = () => c('eval', 'document.body.dataset.blocker').stdout.trim();
        const r = cShow('click', '#card >>> #pay-btn');
        ok(r, /Clicked: BUTTON Pay now/, `click ${url}`);
        assert(!/note:/.test(r.stderr), r.stderr);
        const pay = inFrame(c, '#card', 'document.body.dataset.log');
        assert.strictEqual(count(pay, /pay-click:/g), 1, pay);
        assert(pay.includes('pay-click:trusted'), `landed in the frame, trusted: ${pay}`);
        // Blocker added by the command, made transparent for the click only,
        // restored, then removed when the command ended.
        assert.strictEqual(blocker(), 'added;pe:none;pe:auto;removed;');

        ok(cShow('click', '#top-btn', '--entropy=on'), /Clicked: BUTTON Top button/, 'entropy on the page');
        assert.strictEqual(c('eval', 'document.body.dataset.log').stdout.trim(), 'top-click:trusted;');
        ok(cShow('click', '#card >>> #nested >>> #deep-btn', '--entropy=on'), /Clicked: BUTTON Deep button/, 'nested');
        ok(cShow('smart-click', 'Deep button'), /Clicked: BUTTON "Deep button"/, 'smart-click in a frame');
        const deep = inFrame(c, '#card >>> #nested', 'document.body.dataset.log');
        assert.strictEqual(count(deep, /deep-click:trusted/g), 2, deep);
        assert.strictEqual(count(deep, /deep-click:script/g), 0, deep);
        assert.strictEqual(blocker(), 'added;pe:none;pe:auto;removed;'.repeat(4), 'every click restored it');
      }
    });

    test('frames e2e: run and batch go on after a click pressed but not clicked: exit 3; with a failed step: exit 1', () => {
      const { c, p1, env } = needE2E();
      const url = `http://127.0.0.1:${p1}/moving.html`;
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-run-'));
      const script = path.join(dir, 'jump.cdp');
      fs.writeFileSync(script, `go ${url}\nclick #jump --entropy=on\neval document.body.dataset.log\n`);
      const r = c('run', script);
      assert.strictEqual(r.status, 3, `run: exit 3: ${r.stdout}${r.stderr}`);
      assert(/NOT CLICKED \(exit 3\): note: #jump was no longer under the mouse/.test(r.stdout), r.stdout);
      assert(/jump-down;/.test(r.stdout), 'the step after it ran');
      assert(/Result: 2 passed, 0 failed, 1 not clicked, 3 total/.test(r.stdout), r.stdout);
      c('go', `http://127.0.0.1:${p1}/top.html?child=moving.html`);
      const b = spawnSync(process.execPath, [CLI, 'batch'], { encoding: 'utf-8', timeout: 60000, env,
        input: JSON.stringify([{ cmd: 'click', args: ['#card >>> #jump'] }, { cmd: 'eval', args: ['1 + 1'] }]) });
      assert.strictEqual(b.status, 3, `batch: exit 3: ${b.stdout}${b.stderr}`);
      const steps = JSON.parse(b.stdout.slice(b.stdout.indexOf('[')));
      assert.deepStrictEqual(steps, [{ cmd: 'click', status: 'not_clicked', clicked: false, reason: 'moved' },
        { cmd: 'eval', status: 'ok' }]);
      // A failed step wins over a miss: exit 1 (batch and run used to exit 0 on failures).
      fs.writeFileSync(script, `go ${url}\nclick #jump --entropy=on\nclick #does-not-exist\n`);
      const rf = c('run', script);
      assert.strictEqual(rf.status, 1, `run with a failed step: exit 1: ${rf.stdout}${rf.stderr}`);
      assert(/Result: 1 passed, 1 failed, 1 not clicked, 3 total/.test(rf.stdout), rf.stdout);
      c('go', `http://127.0.0.1:${p1}/top.html?child=moving.html`);
      const bf = spawnSync(process.execPath, [CLI, 'batch'], { encoding: 'utf-8', timeout: 60000, env,
        input: JSON.stringify([{ cmd: 'click', args: ['#card >>> #jump'] }, { cmd: 'nope', args: [] }]) });
      assert.strictEqual(bf.status, 1, `batch with a failed step: exit 1: ${bf.stdout}${bf.stderr}`);
      assert.deepStrictEqual(JSON.parse(bf.stdout.slice(bf.stdout.indexOf('['))).map((s) => s.status),
        ['not_clicked', 'error']);
    });

    test('frames e2e: a target that moves on mousedown: note, no script click; pointer-events: none: script click + note', () => {
      const { c, p1 } = needE2E();
      const cases = [
        [`http://127.0.0.1:${p1}/moving.html`, '', ['--entropy=on'], (js) => c('eval', js).stdout],
        [`http://127.0.0.1:${p1}/top.html?child=moving.html`, '#card >>> ', [],
          (js) => c('frame', 'eval', '--frame', '#card', js).stdout.replace(/^Result: /, '')],
      ];
      for (const [url, prefix, flags, read] of cases) {
        c('go', url);
        const label = prefix ? 'iframe#card >>> ' : '';
        const j = c('click', `${prefix}#jump`, ...flags);
        ok(j, /Pressed \(released elsewhere, not clicked\): BUTTON/, `jump ${url}`);
        assert.strictEqual(j.status, 3, `jump: exit 3: ${j.stderr}`);
        assert(j.stderr.includes(`note: ${label}#jump was no longer under the mouse when the button was released`)
          && j.stderr.includes('so no script click'), j.stderr);
        const g = c('click', `${prefix}#ghost`, ...flags);
        ok(g, /Clicked: BUTTON Ghost/, `ghost ${url}`);
        assert(g.stderr.includes(`note: ${label}#ghost has pointer-events: none; used a script click`), g.stderr);
        // #jump: pressed, released elsewhere, not clicked again by script; #ghost: by script.
        assert.strictEqual(read('document.body.dataset.log').trim(), 'jump-down;ghost-click:script;');
      }
    });

    test('frames e2e: CDPILOT_SHOW=1: hover/dblclick/rightclick reach the page and frames through the blocker', () => {
      const { c, cShow, p1, p2 } = needE2E();
      for (const url of bothOrigins(p1, p2, 'top.html')) {
        c('go', url);
        for (const target of ['#top-btn', '#card >>> #pay-btn']) {
          for (const cmd of ['hover', 'dblclick', 'rightclick']) {
            const r = cShow(cmd, target);
            assert.strictEqual(r.status, 0, `${cmd} ${target}: ${r.stderr}`);
          }
        }
        const page = c('eval', 'document.body.dataset.mouse').stdout;
        const pay = inFrame(c, '#card', 'document.body.dataset.mouse');
        for (const [log, who] of [[page, 'top'], [pay, 'pay']]) {
          for (const ev of ['mouseover', 'dblclick', 'contextmenu']) {
            assert(log.includes(`${who}-${ev}:trusted`), `${who} ${ev} under the blocker: ${log}`);
          }
        }
        assert.strictEqual(c('eval', 'document.body.dataset.blocker').stdout.trim(),
          'added;pe:none;pe:auto;removed;'.repeat(6), 'opened and restored for each command');
      }
    });

    test('frames e2e: a blocker left transparent (a --timeout mid-click) is opaque again in the next command', () => {
      const { c, cShow, p1 } = needE2E();
      c('go', `http://127.0.0.1:${p1}/top.html`);
      c('eval', "(function () { var b = document.createElement('div'); b.id = 'cdpilot-input-blocker';"
        + " b.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;pointer-events:none';"
        + ' document.body.appendChild(b); return 1; })()');
      const r = cShow('eval', "getComputedStyle(document.getElementById('cdpilot-input-blocker')).pointerEvents");
      assert.strictEqual(r.stdout.trim(), 'auto', `during the next command: ${r.stdout}${r.stderr}`);
      assert.strictEqual(c('eval', 'document.body.dataset.blocker').stdout.trim(), 'added;pe:auto;removed;');
    });

    test('frames e2e: no command above sent Runtime.enable (CDPILOT_CDP_TRACE)', () => {
      const { trace } = needE2E();
      const lines = fs.readFileSync(trace, 'utf8').trim().split(/\r?\n/);
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
    const homeSrc = (js.match(/function cdpilotHome\(\) \{[\s\S]*?\n\}\n/) || [])[0];
    assert(homeSrc, 'bin/cdpilot.js must define cdpilotHome');
    const src = (js.match(/function idleCloseLabel\(port\) \{[\s\S]*?\n\}\n/) || [])[0];
    assert(src, 'bin/cdpilot.js must define idleCloseLabel');
    assert(/idleCloseLabel\(port\) \{\s*\n\s*const home = cdpilotHome\(\);/.test(js),
      'idleCloseLabel must resolve home via the shared cdpilotHome() helper');
    assert(/console\.log\(`\s*\$\{idleCloseLabel\(port\)\}/.test(js), 'runStatus must print the label');
    const label = new Function('fs', 'path', 'os', 'process', `${homeSrc}\n${src}\nreturn idleCloseLabel;`)(
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

// ── Connect / Disconnect (human-in-the-loop) ──

(function() {
  const { spawnSync, spawn, execFileSync } = require('child_process');
  const os = require('os');
  const PY_BIN = process.platform === 'win32' ? 'python' : 'python3';
  const FAKE_CDP = path.join(__dirname, 'connect_fake_cdp.py');
  const LEFT_RUNNING = 'connected browser left running; run `cdpilot disconnect` to forget it';
  const GONE = 'your connected browser is gone; run `cdpilot connect` again or `cdpilot disconnect`';
  // Every CDP call that closes a browser or its tabs, as the fake records it.
  const CLOSERS = ['Browser.close', 'Target.closeTarget', 'Page.close'];

  function freePort() {
    const r = spawnSync(PY_BIN, ['-c',
      'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); '
      + 'print(s.getsockname()[1]); s.close()'], { encoding: 'utf-8', timeout: 10000 });
    assert.strictEqual(r.status, 0, `freePort failed: ${r.stderr}`);
    return r.stdout.trim();
  }

  function mkHome() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-connect-test-'));
  }

  function sleep(s) { spawnSync(PY_BIN, ['-c', `import time; time.sleep(${s})`]); }

  // Alive = the process exists and is not a zombie (a child node has not
  // reaped yet still answers kill(pid, 0), which would hide a kill).
  function procAlive(pid) {
    if (process.platform === 'win32') {
      try { process.kill(pid, 0); return true; } catch { return false; }
    }
    const r = spawnSync('ps', ['-o', 'stat=', '-p', String(pid)], { encoding: 'utf-8' });
    const stat = (r.stdout || '').trim();
    return stat !== '' && !stat.startsWith('Z');
  }

  function cdpAnswers(port) {
    const r = spawnSync(PY_BIN, ['-c',
      `import urllib.request; urllib.request.urlopen("http://127.0.0.1:${port}/json/version", timeout=2)`],
      { encoding: 'utf-8', timeout: 10000 });
    return r.status === 0;
  }

  // A stand-in for the user's own browser: test/connect_fake_cdp.py on a random
  // free port, carrying --remote-debugging-port=<port> like a real browser (so a
  // missing guard in cdpilot's kill path would find and signal it).
  function startFake(mode = 'full', guid = 'guid-user') {
    const dir = mkHome();
    const port = freePort();
    const log = path.join(dir, 'fake-cdp.jsonl');
    const proc = spawn(PY_BIN, [FAKE_CDP, port, log, mode, guid, `--remote-debugging-port=${port}`],
      { stdio: 'ignore' });
    for (let i = 0; i < 50 && !(fs.existsSync(log) && fs.readFileSync(log, 'utf-8').includes('"ready"')); i++) {
      sleep(0.1);
    }
    if (!fs.existsSync(log)) {
      try { proc.kill('SIGKILL'); } catch {}
      throw new Error(`fake CDP on ${port} did not start`);
    }
    const entries = () => fs.readFileSync(log, 'utf-8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    return {
      port, log, pid: proc.pid, guid,
      entries,
      methods: () => entries().filter((e) => e.method).map((e) => e.method),
      closers: () => entries().filter((e) => CLOSERS.includes(e.method)
        || (e.http || '').startsWith('/json/close')),
      alive: () => procAlive(proc.pid) && (mode !== 'full' || cdpAnswers(port)),
      stop: () => { try { proc.kill('SIGKILL'); } catch {} },
    };
  }

  function writeRegistry(home, projects) {
    fs.mkdirSync(home, { recursive: true });
    fs.writeFileSync(path.join(home, 'registry.json'), JSON.stringify({ version: 1, projects }));
  }

  function readRegistry(home) {
    return JSON.parse(fs.readFileSync(path.join(home, 'registry.json'), 'utf-8')).projects;
  }

  function externalEntry(port, name = 'TestBrowser') {
    return {
      cwd: process.cwd(), port: parseInt(port, 10), profile_dir: '/nonexistent/profile',
      pid: null, created: '2026-01-01T00:00:00', last_used: '2026-01-01T00:00:00',
      status: 'connected', external: true, browser_name: name,
    };
  }

  // Fully isolated env: registry, profile, port, project, no browser to launch.
  function isoEnv(home, port, projectId, extra = {}) {
    const env = {
      ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: String(port), CDPILOT_PROJECT_ID: projectId, CDPILOT_LOG: '0',
      CHROME_BIN: '/no/such/browser', ...extra,
    };
    for (const k of ['CDPILOT_TARGET', 'CDPILOT_NO_AUTOLAUNCH', 'CDPILOT_MODE', 'CDPILOT_STEALTH',
      'CDPILOT_SHOW', 'CDPILOT_MCP_SESSION', 'CDPILOT_BROWSER_SEARCH_ROOT']) {
      if (!(k in extra)) delete env[k];
    }
    return env;
  }

  function cli(args, env, timeout = 60000) {
    return spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf-8', timeout, env });
  }

  // ── Unit: _parse_devtools_active_port ──

  test('connect: _parse_devtools_active_port parses valid 2-line content', () => {
    const home = mkHome();
    const r = spawnSync(PY_BIN, ['-c', [
      'import sys; sys.path.insert(0, "src")',
      'from cdpilot import _parse_devtools_active_port',
      'port, ws_path = _parse_devtools_active_port("51234\\n/devtools/browser/abc-def-123\\n")',
      'assert port == 51234, f"port: {port}"',
      'assert ws_path == "/devtools/browser/abc-def-123", f"ws_path: {ws_path}"',
      'print("OK")',
    ].join('\n')], { encoding: 'utf-8', timeout: 10000, cwd: path.join(__dirname, '..'),
      env: { ...process.env, CDP_PORT: '19999', CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile') }
    });
    assert.strictEqual(r.status, 0, `parse valid: ${r.stderr}`);
    assert(r.stdout.includes('OK'), r.stdout);
  });

  test('connect: _parse_devtools_active_port rejects single-line content', () => {
    const home = mkHome();
    const r = spawnSync(PY_BIN, ['-c', [
      'import sys; sys.path.insert(0, "src")',
      'from cdpilot import _parse_devtools_active_port',
      'try:',
      '    _parse_devtools_active_port("51234\\n")',
      '    print("ERROR: should have raised")',
      'except ValueError as e:',
      '    assert "need 2 lines" in str(e), str(e)',
      '    print("OK")',
    ].join('\n')], { encoding: 'utf-8', timeout: 10000, cwd: path.join(__dirname, '..'),
      env: { ...process.env, CDP_PORT: '19999', CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile') }
    });
    assert.strictEqual(r.status, 0, `parse single-line: ${r.stderr}`);
    assert(r.stdout.includes('OK'), r.stdout);
  });

  test('connect: _parse_devtools_active_port rejects port out of range', () => {
    const home = mkHome();
    const r = spawnSync(PY_BIN, ['-c', [
      'import sys; sys.path.insert(0, "src")',
      'from cdpilot import _parse_devtools_active_port',
      'try:',
      '    _parse_devtools_active_port("99999\\n/devtools/browser/x\\n")',
      '    print("ERROR: should have raised")',
      'except ValueError as e:',
      '    assert "out of range" in str(e), str(e)',
      '    print("OK")',
    ].join('\n')], { encoding: 'utf-8', timeout: 10000, cwd: path.join(__dirname, '..'),
      env: { ...process.env, CDP_PORT: '19999', CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile') }
    });
    assert.strictEqual(r.status, 0, `parse out-of-range: ${r.stderr}`);
    assert(r.stdout.includes('OK'), r.stdout);
  });

  // ── Unit: remote address rejection (exit 2) ──

  test('connect: remote address exits 2', () => {
    const home = mkHome();
    const r = spawnSync(process.execPath, [CLI, 'connect', 'ws://192.168.1.5:9222/devtools/browser/abc'], {
      encoding: 'utf-8', timeout: 10000,
      env: { ...process.env, CDPILOT_HOME: home, CDP_PORT: '19999', CDPILOT_LOG: '0',
             CDPILOT_PROFILE: path.join(home, 'profile') },
    });
    assert.strictEqual(r.status, 2, `exit: ${r.status}, stderr: ${r.stderr}`);
    assert(/only 127\.0\.0\.1/.test(r.stdout + r.stderr), 'should mention localhost');
  });

  test('connect: [::1] is rejected with exit 2 (the old allow-list entry could never match)', () => {
    const home = mkHome();
    const port = freePort();
    const r = cli(['connect', `ws://[::1]:${port}/devtools/browser/abc`], isoEnv(home, port, 'v6'));
    assert.strictEqual(r.status, 2, `exit: ${r.status}, stderr: ${r.stderr}`);
    assert(/got '\[::1\]'/.test(r.stderr), `must name the host it refused: ${r.stderr}`);
    assert(!/'\[::1\]'/.test(PY_CONTENT.match(/def _validate_localhost[\s\S]*?\n\n\n/)[0]
      .split('if host not in')[1].split('\n')[0]), '[::1] must not be in the allow-list');
  });

  // ── Unit: external registry — stop keeps the browser AND the entry ──

  test('connect: stop on external registry leaves the browser running and keeps the entry', () => {
    const home = mkHome();
    const port = freePort();
    writeRegistry(home, { 'test-proj': externalEntry(port) });
    const r = spawnSync(process.execPath, [CLI, 'stop'], {
      encoding: 'utf-8', timeout: 10000,
      env: { ...process.env, CDPILOT_HOME: home, CDP_PORT: port,
             CDPILOT_PROFILE: path.join(home, 'profile'),
             CDPILOT_PROJECT_ID: 'test-proj', CDPILOT_LOG: '0' },
    });
    assert.strictEqual(r.status, 0, `stop exit: ${r.status}, stderr: ${r.stderr}`);
    assert((r.stdout + r.stderr).includes(LEFT_RUNNING), `should say left running: ${r.stdout}`);
    // Decision B: only `disconnect` removes an external entry.
    const reg2 = readRegistry(home);
    assert(reg2['test-proj'] && reg2['test-proj'].external, 'registry entry must be kept');
  });

  test('connect: disconnect is the only command that forgets the external entry', () => {
    const home = mkHome();
    const port = freePort();
    writeRegistry(home, { 'test-proj': externalEntry(port, 'TestBrowser') });
    const r = cli(['disconnect'], isoEnv(home, port, 'test-proj'));
    assert.strictEqual(r.status, 0, `disconnect exit: ${r.status}, stderr: ${r.stderr}`);
    assert(/Disconnected.*TestBrowser/.test(r.stdout), `should say disconnected: ${r.stdout}`);
    assert(/your browser keeps running/.test(r.stdout), `should say keeps running: ${r.stdout}`);
    assert(!readRegistry(home)['test-proj'], 'disconnect must remove the entry');
  });

  // ── Unit: autolaunch refuses when external browser is gone ──

  test('connect: autolaunch refuses when external browser is registered but gone', () => {
    const home = mkHome();
    const port = freePort();
    writeRegistry(home, { 'test-ext': externalEntry(port, 'GoneChrome') });
    const r = spawnSync(process.execPath, [CLI, 'content'], {
      encoding: 'utf-8', timeout: 15000,
      env: { ...process.env, CDPILOT_HOME: home, CDP_PORT: port,
             CDPILOT_PROFILE: path.join(home, 'profile'),
             CDPILOT_PROJECT_ID: 'test-ext', CDPILOT_LOG: '0',
             CHROME_BIN: '/no/such/browser' },
    });
    assert.notStrictEqual(r.status, 0, 'should fail');
    assert(/your connected browser is gone/.test(r.stdout + r.stderr),
      `should say browser is gone: ${r.stderr}`);
  });

  for (const args of [['content'], ['go', 'https://example.com/'], ['tabs'], ['new-tab'],
    ['launch']]) {
    test(`external guard: gone connected browser → \`${args.join(' ')}\` exits 1, never launches`, () => {
      const home = mkHome();
      const port = freePort();
      writeRegistry(home, { gone: externalEntry(port, 'GoneChrome') });
      // CHROME_BIN points nowhere: any launch attempt would print "Cannot start
      // browser '/no/such/browser'" (directly or as the auto-launch failure).
      const r = cli(args, isoEnv(home, port, 'gone'), 30000);
      const out = r.stdout + r.stderr;
      assert.strictEqual(r.status, 1, `exit ${r.status}: ${out}`);
      assert(out.includes(GONE), `must say the connected browser is gone: ${out}`);
      assert(!/no\/such\/browser|Launching browser|auto-launch|launched it/.test(out),
        `must not try to launch a browser: ${out}`);
      assert.deepStrictEqual(readRegistry(home).gone, externalEntry(port, 'GoneChrome'),
        'the external entry must be left exactly as it was');
    });
  }

  test('external guard: `projects` and a port allocation keep a gone external entry', () => {
    const home = mkHome();
    const port = freePort();  // nothing listens: the old cleanup called this entry dead
    writeRegistry(home, { gone: externalEntry(port) });
    const p = cli(['projects'], isoEnv(home, freePort(), 'someone-else'));
    assert.strictEqual(p.status, 0, `projects: ${p.stdout}${p.stderr}`);
    assert(/gone\s+\d+\s+\S+\s+gone\s+\(ext\)/.test(p.stdout), `projects must list it as gone: ${p.stdout}`);
    assert(readRegistry(home).gone, '`projects` must not prune the external entry');
    // Port allocation (every new project runs it) over a private random range.
    const lo = parseInt(freePort(), 10);
    const r = spawnSync(PY_BIN, ['-c', [
      'import json, sys',
      `sys.path.insert(0, ${JSON.stringify(path.join(__dirname, '..', 'src'))})`,
      'import cdpilot as m',
      `m.CDPILOT_PORT_RANGE_START, m.CDPILOT_PORT_RANGE_END = ${lo}, ${lo + 3}`,
      'print("PORT", m._allocate_port("new-project"))',
      'print("LEFT", json.dumps(sorted(m._cleanup_registry())))',
    ].join('\n')], { encoding: 'utf-8', timeout: 20000,
      env: isoEnv(home, freePort(), 'importer') });
    assert.strictEqual(r.status, 0, `allocate: ${r.stdout}${r.stderr}`);
    assert(/LEFT \["gone"\]/.test(r.stdout), `cleanup must keep the external entry: ${r.stdout}`);
    assert(readRegistry(home).gone, 'a port allocation must not prune the external entry');
  });

  // ── Behaviour: no destructive command reaches a connected browser ──

  const DESTRUCTIVE = [
    ['close'], ['close', '--force'], ['stop'], ['stop', '--smart'], ['stop', '--smart', '--force'],
    ['project-stop', 'ext-proj'], ['stop-all'], ['session-close'], ['tabs', '--reap', '--all'],
    ['close-tab'],
  ];
  for (const args of DESTRUCTIVE) {
    test(`external guard: \`${args.join(' ')}\` leaves a connected browser alive, sends no close`, () => {
      const fake = startFake();
      try {
        const home = mkHome();
        writeRegistry(home, { 'ext-proj': externalEntry(fake.port) });
        const r = cli(args, isoEnv(home, fake.port, 'ext-proj'));
        const out = r.stdout + r.stderr;
        assert.strictEqual(r.status, 0, `exit ${r.status}: ${out}`);
        assert(out.includes(LEFT_RUNNING), `must say it left the browser running: ${out}`);
        assert.deepStrictEqual(fake.closers(), [], `no close may reach the browser: ${out}`);
        assert(fake.alive(), `the connected browser (pid ${fake.pid}) must still be running`);
        assert(readRegistry(home)['ext-proj'].external, 'the external entry must be kept');
      } finally { fake.stop(); }
    });
  }

  test('external guard: `wipe` is refused on a connected browser (cookies, storage, tabs)', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      writeRegistry(home, { 'ext-proj': externalEntry(fake.port) });
      const r = cli(['wipe', '--all'], isoEnv(home, fake.port, 'ext-proj'));
      assert.strictEqual(r.status, 1, `exit ${r.status}: ${r.stdout}${r.stderr}`);
      assert(/wipe refused/.test(r.stderr), r.stderr);
      const sent = fake.methods();
      assert(!sent.some((m) => /deleteCookies|clearDataForOrigin|closeTarget/.test(m)),
        `nothing may be cleared: ${sent}`);
      assert(fake.alive(), 'the connected browser must still be running');
    } finally { fake.stop(); }
  });

  test('external guard: MCP browser_close {force:true} leaves a connected browser alive', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      writeRegistry(home, { 'ext-proj': externalEntry(fake.port) });
      const input = [
        { jsonrpc: '2.0', id: 1, method: 'initialize', params: {} },
        { jsonrpc: '2.0', id: 2, method: 'tools/call',
          params: { name: 'browser_close', arguments: { force: true } } },
        { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'browser_launch', arguments: {} } },
      ].map((m) => JSON.stringify(m)).join('\n') + '\n';
      const r = spawnSync(PY_BIN, [PY_PATH, 'mcp'], { encoding: 'utf-8', timeout: 90000, input,
        env: isoEnv(home, fake.port, 'ext-proj') });
      const replies = r.stdout.split('\n').filter(Boolean).map((l) => JSON.parse(l));
      const text = (id) => JSON.stringify((replies.find((x) => x.id === id) || {}).result || {});
      assert(text(2).includes(LEFT_RUNNING), `browser_close must only disconnect: ${r.stdout}${r.stderr}`);
      assert(/Connected browser in use/.test(text(3)), `browser_launch must not launch: ${text(3)}`);
      assert.deepStrictEqual(fake.closers(), [], 'no close may reach the browser');
      assert(fake.alive(), 'the connected browser must still be running');
    } finally { fake.stop(); }
  });

  test('external guard: idle watcher, serve teardown and the stop helpers never close a connected browser', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      // The entry even carries the fake's pid, so the watcher's ownership test
      // alone would accept it: only the external guard keeps it from closing.
      writeRegistry(home, { ext: { ...externalEntry(fake.port), pid: fake.pid } });
      const r = spawnSync(PY_BIN, ['-c', [
        'import json, sys, time',
        `sys.path.insert(0, ${JSON.stringify(path.join(__dirname, '..', 'src'))})`,
        'import cdpilot as m',
        `P, FPID = ${fake.port}, ${fake.pid}`,
        'ver = m._idle_version(P)',
        'state = {"token": "t1", "pid": None, "port": P, "project_id": "ext", "browser_pid": FPID,',
        '         "browser_ws": ver["webSocketDebuggerUrl"], "minutes": 0.01, "started": time.time() - 3600}',
        'm._idle_save_state(P, state)',
        'out = {"owns": m._idle_owns_browser(state, m._load_registry(), ver)}',
        'out["step"] = m._idle_watcher_step(P, "t1", now=time.time() + 3600)',
        'm._api_session_store["sess_x"] = {"id": "sess_x", "port": P}',
        'out["release"] = m._api_release_session("sess_x")',
        'out["stop"] = m._stop_browser_on_port(P, verbose=True)',
        'out["cdp_close"] = m._cdp_browser_close(P)',
        'print("RESULT=" + json.dumps(out))',
      ].join('\n')], { encoding: 'utf-8', timeout: 60000,
        env: isoEnv(home, freePort(), 'importer') });
      const line = (r.stdout || '').split('\n').find((l) => l.startsWith('RESULT='));
      assert(line, `no result: ${r.stdout}${r.stderr}`);
      const res = JSON.parse(line.slice(7));
      assert.strictEqual(res.owns, true, 'precondition: without the guard the watcher would own it');
      assert.strictEqual(res.step, 'exit', `the idle watcher must stand down: ${line}`);
      assert.strictEqual(res.stop, false, `_stop_browser_on_port must stop nothing: ${line}`);
      assert.strictEqual(res.cdp_close, false, `_cdp_browser_close must send nothing: ${line}`);
      assert.deepStrictEqual(fake.closers(), [], 'no close may reach the browser');
      assert(fake.alive(), 'the connected browser must still be running');
      assert(readRegistry(home).ext.external, 'the external entry must be kept');
    } finally { fake.stop(); }
  });

  test('external guard: harness control — a cdpilot-owned entry DOES get Browser.close', () => {
    // Proves the fake records what the guard is supposed to prevent. The
    // entry carries the browser GUID `launch` records: positive ownership.
    const fake = startFake();
    try {
      const home = mkHome();
      writeRegistry(home, { own: { ...externalEntry(fake.port), external: undefined,
        status: 'running', browser_name: undefined, browser_guid: fake.guid } });
      const r = cli(['close', '--force'], isoEnv(home, fake.port, 'own'));
      assert.strictEqual(r.status, 0, `${r.stdout}${r.stderr}`);
      assert(fake.methods().includes('Browser.close'), `control must see Browser.close: ${fake.methods()}`);
    } finally { fake.stop(); }
  });

  test('external guard: no stealth/glow/input blocker into a connected browser (mode.json stealth, MCP)', () => {
    const run = (external) => {
      const fake = startFake();
      try {
        const home = mkHome();
        const entry = external ? externalEntry(fake.port)
          : { ...externalEntry(fake.port), external: undefined, status: 'running' };
        writeRegistry(home, { proj: entry });
        fs.mkdirSync(path.join(home, 'profile'), { recursive: true });
        fs.writeFileSync(path.join(home, 'profile', 'mode.json'), JSON.stringify({ tier: 'stealth' }));
        const r = cli(['go', 'https://example.com/'],
          isoEnv(home, fake.port, 'proj', { CDPILOT_MCP_SESSION: '1' }));
        assert.strictEqual(r.status, 0, `go exit ${r.status}: ${r.stdout}${r.stderr}`);
        const entries = fake.entries().filter((e) => e.method);
        return {
          methods: entries.map((e) => e.method),
          tags: [...new Set(entries.flatMap((e) => e.tags || []))].sort(),
        };
      } finally { fake.stop(); }
    };
    const ext = run(true);
    assert(ext.methods.includes('Page.navigate'), `go must still navigate: ${ext.methods}`);
    assert(!ext.methods.includes('Page.addScriptToEvaluateOnNewDocument'),
      `no addScriptToEvaluateOnNewDocument into a connected browser: ${ext.methods}`);
    assert(!ext.methods.includes('Emulation.setUserAgentOverride'), 'no UA override');
    assert.deepStrictEqual(ext.tags, [], `no stealth/glow/input-blocker script: ${ext.tags}`);
    // Control: the same go into a cdpilot-launched browser injects all three.
    const own = run(false);
    assert(own.methods.includes('Page.addScriptToEvaluateOnNewDocument'), `control: ${own.methods}`);
    assert.deepStrictEqual(own.tags, ['glow', 'input-blocker', 'stealth'], `control tags: ${own.tags}`);
  });

  test('external guard: connect refuses over a live cdpilot-launched browser (no orphan)', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      const own = { ...externalEntry(fake.port), external: undefined, browser_name: undefined,
        pid: fake.pid, status: 'running' };
      writeRegistry(home, { mine: own });
      const r = cli(['connect', String(fake.port)], isoEnv(home, fake.port, 'mine'));
      assert.strictEqual(r.status, 1, `exit ${r.status}: ${r.stdout}${r.stderr}`);
      assert(/stop it first \(`cdpilot stop`\) or use another project/i.test(r.stderr), r.stderr);
      // Another project may not take over that browser's port either.
      const r2 = cli(['connect', String(fake.port)], isoEnv(home, freePort(), 'other'));
      assert.strictEqual(r2.status, 1, `other project: ${r2.stdout}${r2.stderr}`);
      const reg = readRegistry(home);
      assert.strictEqual(reg.mine.pid, fake.pid, 'the cdpilot browser keeps its pid (not orphaned)');
      assert(!reg.mine.external && !reg.other, `registry must be unchanged: ${JSON.stringify(reg)}`);
    } finally { fake.stop(); }
  });

  test('external guard: page commands open a tab of their own, never touch the user\'s tab', () => {
    const run = (external) => {
      const fake = startFake();
      try {
        const home = mkHome();
        const entry = external ? externalEntry(fake.port)
          : { ...externalEntry(fake.port), external: undefined, status: 'running' };
        writeRegistry(home, { proj: entry });
        // A session record naming the user's tab (what the old reuse wrote):
        // on a connected browser it must not be trusted.
        fs.mkdirSync(path.join(home, 'profile'), { recursive: true });
        if (external) {
          fs.writeFileSync(path.join(home, 'profile', 'sessions.json'), JSON.stringify({
            'cdpilot-default': { target_id: 'PAGE1', created: 'x', last_used: Date.now() / 1000 } }));
        }
        const env = isoEnv(home, fake.port, 'proj');
        const outs = [['go', 'https://example.com/'], ['content'], ['eval', 'document.title'],
          ['html']].map((a) => {
          const r = cli(a, env);
          assert.strictEqual(r.status, 0, `${a.join(' ')} exit ${r.status}: ${r.stdout}${r.stderr}`);
          return r;
        });
        const listed = JSON.parse(spawnSync(PY_BIN, ['-c',
          `import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:${fake.port}/json").read().decode())`],
          { encoding: 'utf-8', timeout: 10000 }).stdout);
        return { fake, outs, entries: fake.entries(), listed };
      } finally { fake.stop(); }
    };
    const ext = run(true);
    const creates = ext.entries.filter((e) => e.method === 'Target.createTarget');
    assert.strictEqual(creates.length, 1, `one tab of its own for all four commands: ${JSON.stringify(creates)}`);
    const onUser = ext.entries.filter((e) => (e.ws || e.ws_open || '').endsWith('/PAGE1'));
    assert.deepStrictEqual(onUser, [], 'no socket may touch the user\'s tab');
    const pageMethods = ext.entries.filter((e) => e.method && (e.ws || '').includes('/devtools/page/'));
    assert(pageMethods.length > 0 && pageMethods.every((e) => e.ws === '/devtools/page/PAGE2'),
      `every page command must run in cdpilot's own tab: ${JSON.stringify(pageMethods)}`);
    const user = ext.listed.find((t) => t.id === 'PAGE1');
    assert.strictEqual(user.url, 'https://user.example/inbox', 'the user tab keeps its URL');
    assert.strictEqual(user.title, "The user's own tab", 'the user tab keeps its title');
    assert(ext.listed.some((t) => t.id === 'PAGE2' && t.url === 'https://example.com/'),
      `go navigated cdpilot's tab: ${JSON.stringify(ext.listed)}`);
    // Control: a cdpilot browser reuses its open tab, so the fake would show it.
    const own = run(false);
    assert(own.entries.some((e) => e.method === 'Page.navigate' && e.ws === '/devtools/page/PAGE1'),
      'control: without the external rule the open tab is reused');
  });

  // ── Ownership proof (#26 re-review: a stale entry + the user's Chrome) ──

  function deadPid() {
    const r = spawnSync(PY_BIN, ['-c', 'import subprocess, sys; p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait(); print(p.pid)'],
      { encoding: 'utf-8', timeout: 10000 });
    return parseInt(r.stdout.trim(), 10);
  }

  for (const [label, stale] of [
    ['dead pid, no GUID (older entry)', (port) => ({ pid: deadPid() })],
    ['dead pid, GUID of an old browser', (port) => ({ pid: deadPid(), browser_guid: 'guid-old-run' })],
    ['live pid that does not hold the port', (port) => ({ pid: process.pid })],
  ]) {
    test(`ownership: stale entry (${label}) + a foreign browser on the port → stop/close send nothing, connect replaces it`, () => {
      const fake = startFake();
      try {
        const home = mkHome();
        const entry = { cwd: '/x', port: parseInt(fake.port, 10), profile_dir: path.join(home, 'profile'),
          status: 'running', created: 'x', last_used: 'x', ...stale(fake.port) };
        const env = isoEnv(home, fake.port, 'proj');
        for (const args of [['stop'], ['close', '--force'], ['project-stop', 'proj'], ['stop-all']]) {
          writeRegistry(home, { proj: { ...entry } });  // each command meets the stale entry
          const r = cli(args, env);
          const out = r.stdout + r.stderr;
          assert.strictEqual(r.status, 0, `${args.join(' ')} exit ${r.status}: ${out}`);
          assert(/not one cdpilot launched/.test(out), `${args.join(' ')} must say why: ${out}`);
          assert.deepStrictEqual(fake.closers(), [], `${args.join(' ')}: no close may reach it`);
          assert(fake.alive(), `${args.join(' ')}: the user's browser (pid ${fake.pid}) must be alive`);
        }
        const c = cli(['connect', String(fake.port)], env);
        assert.strictEqual(c.status, 0, `connect must replace the stale entry: ${c.stdout}${c.stderr}`);
        const reg = readRegistry(home).proj;
        assert(reg.external && reg.browser_guid === fake.guid, JSON.stringify(reg));
        const s = cli(['stop'], env);
        assert((s.stdout + s.stderr).includes(LEFT_RUNNING), s.stdout + s.stderr);
        assert.deepStrictEqual(fake.closers(), []);
        assert(fake.alive(), 'still alive after connect + stop');
      } finally { fake.stop(); }
    });
  }

  test('ownership: a browser cdpilot launched (GUID recorded) still stops: Browser.close, then its pid', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      // What `launch` records: the pid it started and the browser GUID.
      writeRegistry(home, { mine: { cwd: '/x', port: parseInt(fake.port, 10), profile_dir: '/x',
        status: 'running', pid: fake.pid, browser_guid: fake.guid, created: 'x', last_used: 'x' } });
      const r = cli(['stop'], isoEnv(home, fake.port, 'mine'));
      assert.strictEqual(r.status, 0, `${r.stdout}${r.stderr}`);
      assert(new RegExp(`Browser stopped \\(port ${fake.port}\\)`).test(r.stdout), r.stdout + r.stderr);
      assert(fake.methods().includes('Browser.close'), `Browser.close first: ${fake.methods()}`);
      sleep(0.3);
      assert(!procAlive(fake.pid), 'the fake ignores Browser.close, so its recorded pid is signalled');
      assert.strictEqual(readRegistry(home).mine.pid, null);
    } finally { fake.stop(); }
  });

  test('ownership: a GUID mismatch is not proof even with the recorded pid alive (no signal)', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      writeRegistry(home, { mine: { cwd: '/x', port: parseInt(fake.port, 10), profile_dir: '/x',
        status: 'running', pid: fake.pid, browser_guid: 'guid-previous-run', created: 'x', last_used: 'x' } });
      const r = cli(['stop'], isoEnv(home, fake.port, 'mine'));
      assert(/not one cdpilot launched/.test(r.stdout + r.stderr), r.stdout + r.stderr);
      assert.deepStrictEqual(fake.closers(), []);
      assert(fake.alive(), 'no signal on a GUID mismatch');
    } finally { fake.stop(); }
  });

  test('ownership: launch records the browser GUID in the registry', () => {
    assert(/_register_project\(PROJECT_ID, CDP_PORT, PROFILE_DIR, pid=proc\.pid,\s*\n\s*browser_guid=_browser_guid\(/.test(PY_CONTENT),
      'cmd_launch must pass browser_guid');
  });

  // A stand-in Web Bot Auth signer: a sleeping process whose command line is
  // the signer's (`--_bot-auth-signer <port> <token>`) and its state file, so
  // _bot_auth_pid_is_signer accepts it and a stop is free to signal it.
  function fakeSigner(home, port, browserWs) {
    const token = 'feedc0de12345678';
    const proc = spawn(PY_BIN, ['-c', 'import time; time.sleep(60)', '--_bot-auth-signer', String(port), token],
      { stdio: 'ignore' });
    const dir = path.join(home, 'bot-auth', 'signers');
    fs.mkdirSync(dir, { recursive: true });
    const state = path.join(dir, `${port}.json`);
    // Written by Python: Windows proves a signer by its creation time, a
    // 64-bit FILETIME a JS number would round (the real signer records it).
    const w = spawnSync(PY_BIN, ['-c', [
      'import json, sys, time', `sys.path.insert(0, ${JSON.stringify(path.join(__dirname, '..', 'src'))})`,
      'import cdpilot', `pid = ${proc.pid}`,
      `state = {"token": ${JSON.stringify(token)}, "pid": pid, "pid_ctime": cdpilot._proc_create_time(pid),`,
      `         "ready": True, "port": ${parseInt(port, 10)}, "browser_ws": ${JSON.stringify(browserWs)},`,
      '         "keyid": "k", "started": time.time()}',
      'assert sys.platform != "win32" or state["pid_ctime"] is not None, "no creation time"',
      `json.dump(state, open(${JSON.stringify(state)}, "w"))`,
    ].join('\n')], { encoding: 'utf-8', timeout: 20000, env: isoEnv(home, port, 'signer') });
    assert.strictEqual(w.status, 0, `stand-in signer state: ${w.stdout}${w.stderr}`);
    sleep(0.3);
    return { pid: proc.pid, state, stop: () => { try { proc.kill('SIGKILL'); } catch {} } };
  }

  test('ownership + bot-auth: no signal to a signer next to a browser without proof; proven or gone → signer ended', () => {
    const fake = startFake();
    const home = mkHome();
    const wsUrl = `ws://127.0.0.1:${fake.port}/devtools/browser/${fake.guid}`;
    const signers = [];
    try {
      const env = isoEnv(home, fake.port, 'ba');
      // 1. Stale entry, the user's browser on the port: browser AND signer untouched.
      let sg = fakeSigner(home, fake.port, wsUrl); signers.push(sg);
      for (const args of [['stop'], ['project-stop', 'ba'], ['stop-all']]) {
        writeRegistry(home, { ba: { cwd: '/x', port: parseInt(fake.port, 10), profile_dir: '/x',
          status: 'running', pid: deadPid(), browser_guid: 'guid-old', created: 'x', last_used: 'x' } });
        const r = cli(args, env);
        assert.strictEqual(r.status, 0, `${args.join(' ')}: ${r.stdout}${r.stderr}`);
        assert(procAlive(sg.pid), `${args.join(' ')} must not signal the signer (no browser proof)`);
        assert(fake.alive() && fake.closers().length === 0, `${args.join(' ')}: browser untouched`);
      }
      // 2. Connected (external) browser: the same.
      writeRegistry(home, { ba: externalEntry(fake.port) });
      assert.strictEqual(cli(['stop'], env).status, 0);
      assert(procAlive(sg.pid) && fake.alive(), 'external: signer and browser untouched');
      // 3. Proven (the GUID launch recorded): browser closed, signer ended.
      writeRegistry(home, { ba: { cwd: '/x', port: parseInt(fake.port, 10), profile_dir: '/x',
        status: 'running', pid: null, browser_guid: fake.guid, created: 'x', last_used: 'x' } });
      let r = cli(['stop'], env);
      assert(fake.methods().includes('Browser.close'), `proven browser gets Browser.close: ${r.stdout}${r.stderr}`);
      sleep(0.3);
      assert(!procAlive(sg.pid), 'the signer of a proven browser is ended');
      assert(!fs.existsSync(sg.state), 'its state is cleared');
      // 4. Nothing on the port any more: an orphan signer is ended.
      fake.stop();
      sleep(0.3);
      sg = fakeSigner(home, fake.port, wsUrl); signers.push(sg);
      writeRegistry(home, { ba: { cwd: '/x', port: parseInt(fake.port, 10), profile_dir: '/x',
        status: 'running', pid: deadPid(), created: 'x', last_used: 'x' } });
      r = cli(['project-stop', 'ba'], env);
      assert.strictEqual(r.status, 0, r.stdout + r.stderr);
      r = cli(['stop'], env);
      sleep(0.3);
      assert(!procAlive(sg.pid), `an orphan signer (port free) is ended: ${r.stdout}${r.stderr}`);
    } finally { fake.stop(); signers.forEach((x) => x.stop()); }
  });

  test('ownership + bot-auth: launch --bot-auth attaches no signer to a browser without proof', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      const env = isoEnv(home, fake.port, 'bl');
      const init = cli(['bot-auth', 'init', '--agent-url', 'https://agent.test'], env);
      if (/pip install cryptography/.test(init.stdout + init.stderr)) {
        console.log('    (cryptography missing for the CLI interpreter: launch part not exercised)');
        return;
      }
      assert.strictEqual(init.status, 0, init.stdout + init.stderr);
      writeRegistry(home, { bl: { cwd: '/x', port: parseInt(fake.port, 10), profile_dir: '/x',
        status: 'running', pid: deadPid(), created: 'x', last_used: 'x' } });
      const r = cli(['launch', '--bot-auth'], env);
      assert.strictEqual(r.status, 1, r.stdout + r.stderr);
      assert(/not one cdpilot launched \(no ownership proof\); no signer attached/.test(r.stderr), r.stderr);
      assert(!fs.existsSync(path.join(home, 'bot-auth', 'signers', `${fake.port}.json`)), 'no signer state');
      assert.deepStrictEqual(fake.entries().filter((e) => e.ws_open), [], 'no CDP connection at all');
      assert(fake.alive());
    } finally { fake.stop(); }
  });

  test('connect: clicks and presses in a connected browser touch no input blocker (nothing but the click)', () => {
    const home = mkHome();
    const port = freePort();
    writeRegistry(home, { blk: externalEntry(port) });
    const src = path.join(__dirname, '..', 'src');
    const r = spawnSync(PY_BIN, ['-c', [
      'import asyncio, socket, sys, threading', `sys.path.insert(0, ${JSON.stringify(src)})`,
      'import cdpilot as m',
      // A listener that counts connections: the page must not be contacted.
      'srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)',
      'hits = []',
      'def accept():',
      '    while True:',
      '        c, _ = srv.accept(); hits.append(1); c.close()',
      'threading.Thread(target=accept, daemon=True).start()',
      'route = m._FrameRoute(f"ws://127.0.0.1:{srv.getsockname()[1]}/devtools/page/OWN")',
      'r1 = asyncio.run(m._blocker_pointer(route, "none"))',
      'r2 = asyncio.run(m._blocker_pointer(route, ""))',
      'assert (r1, r2, hits, m._BLOCKER_OPEN) == (False, False, [], set()), (r1, r2, hits, m._BLOCKER_OPEN)',
      'print("OK")',
    ].join('\n')], { encoding: 'utf-8', timeout: 20000, env: isoEnv(home, port, 'blk') });
    assert.strictEqual(r.status, 0, r.stdout + r.stderr);
    assert(r.stdout.includes('OK'), r.stdout + r.stderr);
  });

  // ── Connected browser housekeeping ──

  test('connect: a session made before connect (CDP_PORT at that browser) is not reused after it', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      const env = isoEnv(home, fake.port, 'pre');
      // Before connect: no registry entry, CDP_PORT points at the browser;
      // the old path adopts the open tab and marks it owned.
      const g0 = cli(['go', 'https://example.com/'], env);
      assert.strictEqual(g0.status, 0, g0.stdout + g0.stderr);
      assert(fake.entries().some((e) => e.ws === '/devtools/page/PAGE1'), 'precondition: PAGE1 was adopted');
      const mark = fake.entries().length;
      assert.strictEqual(cli(['connect', String(fake.port)], env).status, 0);
      for (const a of [['go', 'https://example.org/'], ['content']]) {
        const r = cli(a, env);
        assert.strictEqual(r.status, 0, `${a.join(' ')}: ${r.stdout}${r.stderr}`);
      }
      const after = fake.entries().slice(mark);
      assert.deepStrictEqual(after.filter((e) => (e.ws || e.ws_open || '').endsWith('/PAGE1')), [],
        'after connect the pre-connect session tab (the user tab) is never used');
      assert.strictEqual(after.filter((e) => e.method === 'Target.createTarget').length, 1, 'one own tab');
    } finally { fake.stop(); }
  });

  test('connect: close / session-close / idle cleanup close only the tabs cdpilot opened (inactive window), never a user tab', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      writeRegistry(home, {});
      const env = isoEnv(home, fake.port, 'ext');
      assert.strictEqual(cli(['connect', String(fake.port)], env).status, 0);
      const list = () => JSON.parse(spawnSync(PY_BIN, ['-c',
        `import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:${fake.port}/json").read().decode())`],
        { encoding: 'utf-8', timeout: 10000 }).stdout);
      const ids = () => list().map((t) => t.id).sort();
      // owned-tabs.json poisoned with the user tab (CDPILOT_TARGET / smart-click can do this).
      fs.writeFileSync(path.join(home, 'profile', 'owned-tabs.json'), JSON.stringify({ owned: ['PAGE1'] }));
      assert.strictEqual(cli(['go', 'https://a.test/'], env).status, 0);
      const own = list().find((t) => t.id === 'PAGE2');
      assert(own && own.background === true && own.newWindow === true,
        `own tab opened in a window of its own, without focus: ${JSON.stringify(list())}`);
      let r = cli(['session-close'], env);
      assert.strictEqual(r.status, 0, r.stdout + r.stderr);
      assert.deepStrictEqual(ids(), ['PAGE1'], 'session-close closed cdpilot\'s tab only');
      assert.strictEqual(cli(['go', 'https://b.test/'], env).status, 0);
      assert.strictEqual(cli(['new-tab', 'https://c.test/'], env).status, 0);
      assert.deepStrictEqual(ids(), ['PAGE1', 'PAGE3', 'PAGE4']);
      r = cli(['close', '--force'], env);
      assert.strictEqual(r.status, 0, r.stdout + r.stderr);
      assert(/Closed 2 cdpilot tab\(s\)/.test(r.stdout) && r.stdout.includes(LEFT_RUNNING), r.stdout);
      assert.deepStrictEqual(ids(), ['PAGE1'], 'close closed cdpilot\'s tabs only');
      assert(!fake.methods().includes('Browser.close'));
      // Idle session cleanup (runs before the next page command): only
      // cdpilot's tab goes; an idle session naming the user tab only forgets it.
      assert.strictEqual(cli(['go', 'https://d.test/'], env).status, 0);
      const idleTab = ids().find((id) => id !== 'PAGE1');
      const sfile = path.join(home, 'profile', 'sessions.json');
      const sess = JSON.parse(fs.readFileSync(sfile, 'utf-8'));
      sess['cdpilot-default'].last_used = 1;
      sess['stale-user'] = { target_id: 'PAGE1', created: 'x', last_used: 1 };
      fs.writeFileSync(sfile, JSON.stringify(sess));
      assert.strictEqual(cli(['go', 'https://e.test/'], env).status, 0);
      const afterIdle = ids();
      assert(afterIdle.includes('PAGE1') && !afterIdle.includes(idleTab) && afterIdle.length === 2,
        `idle cleanup closed cdpilot's tab ${idleTab}, kept the user tab: ${afterIdle}`);
      assert(!('stale-user' in JSON.parse(fs.readFileSync(sfile, 'utf-8'))), 'idle session forgotten');
      // The last page is never closed, even when it is cdpilot's own.
      const lastOwn = afterIdle.find((id) => id !== 'PAGE1');
      spawnSync(PY_BIN, ['-c', `import urllib.request; urllib.request.urlopen("http://127.0.0.1:${fake.port}/json/close/PAGE1")`]);
      assert.deepStrictEqual(ids(), [lastOwn]);
      assert.strictEqual(cli(['close'], env).status, 0);
      assert.deepStrictEqual(ids(), [lastOwn], 'never the last page');
      assert(fake.alive());
    } finally { fake.stop(); }
  });

  test('new-tab: PUT /json/new (Chrome refuses GET) on a cdpilot browser', () => {
    const fake = startFake();
    try {
      const home = mkHome();
      writeRegistry(home, {});
      const r = cli(['new-tab', 'https://example.com/'], isoEnv(home, fake.port, 'nt'));
      assert.strictEqual(r.status, 0, r.stdout + r.stderr);
      assert(/New tab opened/.test(r.stdout), `the fake answers GET /json/new with 405 like Chrome: ${r.stdout}${r.stderr}`);
      const reqs = fake.entries().filter((e) => (e.http || '').startsWith('/json/new'));
      assert(reqs.length === 1 && reqs[0].verb === 'PUT', JSON.stringify(reqs));
    } finally { fake.stop(); }
  });

  test('disconnect: stops this project\'s watch daemon', () => {
    const home = mkHome();
    const port = freePort();
    writeRegistry(home, { wproj: externalEntry(port) });
    const daemon = spawn(PY_BIN, ['-c', 'import time; time.sleep(60)'], { stdio: 'ignore' });
    try {
      const wdir = path.join(home, 'projects', 'wproj', 'watch');
      fs.mkdirSync(wdir, { recursive: true });
      fs.writeFileSync(path.join(wdir, 'state.json'), JSON.stringify({ pid: daemon.pid }));
      const r = cli(['disconnect'], isoEnv(home, port, 'wproj'));
      assert.strictEqual(r.status, 0, r.stdout + r.stderr);
      assert(/Stopped this project's watch daemon/.test(r.stdout), r.stdout);
      sleep(0.3);
      assert(!procAlive(daemon.pid), 'the watch daemon must be stopped');
    } finally { try { daemon.kill('SIGKILL'); } catch {} }
  });

  test('registry: concurrent registrations lose nothing (file lock), external flag kept', () => {
    const home = mkHome();
    const src = path.join(__dirname, '..', 'src');
    const worker = (id, ext) => spawn(PY_BIN, ['-c', [
      'import sys', `sys.path.insert(0, ${JSON.stringify(src)})`, 'import cdpilot as m',
      `for i in range(15): m._register_project(${JSON.stringify(id)}, 40000 + i, "/x", external=${ext ? 'True' : 'False'})`,
    ].join('\n')], { stdio: 'ignore', env: isoEnv(home, freePort(), 'w') });
    const procs = ['ext', ...Array.from({ length: 9 }, (_, i) => `p${i}`)].map((id) => worker(id, id === 'ext'));
    const deadline = Date.now() + 60000;
    while (procs.some((p) => p.exitCode === null && p.signalCode === null) && Date.now() < deadline) sleep(0.2);
    const reg = readRegistry(home);
    assert.deepStrictEqual(Object.keys(reg).sort(), ['ext', 'p0', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8']);
    assert.strictEqual(reg.ext.external, true);
    assert(/def _atomic_write_json[\s\S]*?tempfile\.mkstemp/.test(PY_CONTENT), 'unique temp files');
    assert(/def _save_owned_tabs[\s\S]*?_atomic_write_json\(OWNED_TABS_FILE/.test(PY_CONTENT));
    assert(/def _mark_owned_context[\s\S]*?_atomic_write_json\(OWNED_CONTEXTS_FILE/.test(PY_CONTENT));
  });

  // ── connect --auto ──

  test('connect: --auto finds DevToolsActivePort via CDPILOT_BROWSER_SEARCH_ROOT', () => {
    const home = mkHome();
    const searchRoot = path.join(home, 'browsers');
    const chromeDir = path.join(searchRoot, 'FakeChrome');
    fs.mkdirSync(chromeDir, { recursive: true });
    // A port nothing listens on: the file is found, the browser is not.
    fs.writeFileSync(path.join(chromeDir, 'DevToolsActivePort'), '19998\n/devtools/browser/fake-uuid\n');
    const r = spawnSync(process.execPath, [CLI, 'connect', '--auto'], {
      encoding: 'utf-8', timeout: 10000,
      env: { ...process.env, CDPILOT_HOME: home, CDP_PORT: '19999',
             CDPILOT_PROFILE: path.join(home, 'profile'),
             CDPILOT_BROWSER_SEARCH_ROOT: searchRoot, CDPILOT_LOG: '0' },
    });
    // It finds the file but CDP won't be responding, so it should fail gracefully
    assert.notStrictEqual(r.status, 0, 'should fail when CDP not responding');
    assert(/FakeChrome.*port 19998.*not responding/.test(r.stdout + r.stderr)
           || /CDP not responding/.test(r.stdout + r.stderr),
      `should mention FakeChrome or not responding: ${r.stderr}`);
  });

  test('connect --auto: skips stale files (dead port, other GUID) and connects to the live one', () => {
    const other = startFake('full', 'guid-someone-else');
    const live = startFake('full', 'guid-live');
    try {
      const home = mkHome();
      const root = path.join(home, 'browsers');
      const put = (name, port, guid) => {
        fs.mkdirSync(path.join(root, name), { recursive: true });
        fs.writeFileSync(path.join(root, name, 'DevToolsActivePort'), `${port}\n/devtools/browser/${guid}\n`);
      };
      put('A-dead', freePort(), 'guid-dead');           // nothing listens any more
      put('B-reused', other.port, 'guid-left-over');     // port now another browser's
      put('C-live', live.port, 'guid-live');
      const r = cli(['connect', '--auto'], isoEnv(home, freePort(), 'auto',
        { CDPILOT_BROWSER_SEARCH_ROOT: root }));
      assert.strictEqual(r.status, 0, `exit ${r.status}: ${r.stdout}${r.stderr}`);
      assert(new RegExp(`Connected to FakeChrome.* on port ${live.port}`).test(r.stdout), r.stdout);
      assert(/skipped A-dead .*not responding/.test(r.stderr), r.stderr);
      assert(/skipped B-reused .*another browser answers there/.test(r.stderr), r.stderr);
      const entry = readRegistry(home).auto;
      assert(entry.external && entry.port === parseInt(live.port, 10), JSON.stringify(entry));
      assert.deepStrictEqual(other.methods(), [], 'the stale candidate gets no CDP command');
    } finally { other.stop(); live.stop(); }
  });

  test('connect --auto: chrome://inspect ws-only endpoint → unsupported message, exit 2', () => {
    const ws = startFake('ws-only', 'guid-inspect');
    try {
      const home = mkHome();
      const root = path.join(home, 'browsers');
      fs.mkdirSync(path.join(root, 'Chrome'), { recursive: true });
      fs.writeFileSync(path.join(root, 'Chrome', 'DevToolsActivePort'),
        `${ws.port}\n/devtools/browser/guid-inspect\n`);
      const r = cli(['connect', '--auto'], isoEnv(home, freePort(), 'inspect',
        { CDPILOT_BROWSER_SEARCH_ROOT: root }));
      assert.strictEqual(r.status, 2, `exit ${r.status}: ${r.stdout}${r.stderr}`);
      assert(/chrome:\/\/inspect remote-debugging mode/.test(r.stderr), r.stderr);
      assert(/does not support that mode yet/.test(r.stderr), r.stderr);
      for (const os_ of ['macOS', 'Linux', 'Windows']) {
        assert(new RegExp(`${os_}:.*--remote-debugging-port=\\d+ --user-data-dir=`).test(r.stderr),
          `exact ${os_} command expected: ${r.stderr}`);
      }
      assert(!fs.existsSync(path.join(home, 'registry.json')) || !readRegistry(home).inspect,
        'nothing may be registered');
      assert(ws.entries().some((e) => e.ws_open), 'the WebSocket path must have been probed');
      assert.deepStrictEqual(ws.methods(), [], 'the probe sends no CDP command');
    } finally { ws.stop(); }
  });

  test('connect --auto: no WebSocket probe at all once a live browser is found', () => {
    const ws = startFake('ws-only', 'guid-inspect');
    const live = startFake('full', 'guid-live');
    try {
      const home = mkHome();
      const root = path.join(home, 'browsers');
      const put = (name, port, guid) => {
        fs.mkdirSync(path.join(root, name), { recursive: true });
        fs.writeFileSync(path.join(root, name, 'DevToolsActivePort'), `${port}\n/devtools/browser/${guid}\n`);
      };
      put('A-inspect', ws.port, 'guid-inspect');  // searched first
      put('B-live', live.port, 'guid-live');
      const r = cli(['connect', '--auto'], isoEnv(home, freePort(), 'auto2', { CDPILOT_BROWSER_SEARCH_ROOT: root }));
      assert.strictEqual(r.status, 0, r.stdout + r.stderr);
      assert(new RegExp(`on port ${live.port}`).test(r.stdout), r.stdout);
      assert.deepStrictEqual(ws.entries().filter((e) => e.ws_open), [],
        'the chrome://inspect-mode candidate gets no WebSocket upgrade (it may prompt the user)');
    } finally { ws.stop(); live.stop(); }
  });

  test('connect --auto: finds the README setup, --user-data-dir="$HOME/cdpilot-chrome"', () => {
    const live = startFake('full', 'guid-readme');
    try {
      const home = mkHome();
      const fakeHome = path.join(home, 'home');
      fs.mkdirSync(path.join(fakeHome, 'cdpilot-chrome'), { recursive: true });
      fs.writeFileSync(path.join(fakeHome, 'cdpilot-chrome', 'DevToolsActivePort'),
        `${live.port}\n/devtools/browser/guid-readme\n`);
      const r = cli(['connect', '--auto'], isoEnv(home, freePort(), 'readme',
        { HOME: fakeHome, USERPROFILE: fakeHome }));
      assert.strictEqual(r.status, 0, r.stdout + r.stderr);
      assert(/Connected to .* on port/.test(r.stdout), r.stdout);
      assert.strictEqual(readRegistry(home).readme.port, parseInt(live.port, 10));
    } finally { live.stop(); }
  });

  // ── Tripwire: every destructive call site goes through the guard ──

  test('external guard: tripwire — Browser.close / kill / tab-close call sites are all known', () => {
    // A static check, on purpose, next to the behaviour tests above: a NEW
    // function that closes a browser, closes tabs or signals a process fails
    // here until it is either guarded by _is_external() or listed as not
    // touching a browser.
    assert(/def _refuse_external[\s\S]*?if _is_external\(\):[\s\S]*?sys\.exit\(1\)/.test(PY_CONTENT),
      '_refuse_external must check _is_external() and exit');
    const GUARDED = [  // must call _is_external( themselves
      '_external_close_own_tabs',
      '_idle_watcher_step', '_cleanup_idle_sessions', 'cmd_wipe', '_close_target', '_reap_tabs',
      '_browser_close_graceful', 'cmd_close', 'cmd_session_close', 'cmd_close_tab',
      '_cdp_browser_close', '_stop_browser_on_port', '_stop_browser_processes_on_port',
      'cmd_stop', 'cmd_project_stop', 'cmd_stop_all',
      // Network.deleteCookies + Storage.clearDataForOrigin: cmd_wipe (above).
      'cmd_context_close',  // disposeBrowserContext: only contexts `context create` made
      'cmd_permission',     // Browser.resetPermissions (+ grant/deny): refused
    ];
    // Target.disposeBrowserContext that cannot reach a user context: each one
    // disposes a context the same function created a moment earlier (a
    // rollback after createTarget failed), or the per-`go` isolated context
    // cmd_go made through _new_isolated_context. A user's context id never
    // reaches them.
    const OWN_CONTEXT_ONLY = ['cmd_context_create', '_new_isolated_context', '_dispose_context'];
    const VIA_GUARDED_HELPER = {  // reach a browser only through a guarded helper
      _api_create_session: /_stop_browser_on_port\(/, _api_release_session: /_stop_browser_on_port\(|Browser\.close/,
      cmd_launch: /_stop_browser_on_port\(/,  // a signed launch whose signer failed
    };
    const NOT_A_BROWSER = [  // signal 0 probes / cdpilot's own helper processes
      '_pid_alive', '_watch_pid_alive', '_watch_daemon_run', 'cmd_watch_start', 'cmd_watch_stop',
      '_arm_timeout_watchdog',
      // Web Bot Auth: the spawn lock (a docstring), the signer a launch just
      // spawned, and the signer stop, which signals only a pid proven to be
      // this port's signer and is reached only through _stop_browser_on_port
      // (checked below).
      '_bot_auth_acquire_lock', '_bot_auth_spawn_locked', '_bot_auth_stop_helper',
    ];
    const PAT = /Browser\.close|os\.kill\(|taskkill|Target\.closeTarget|\/json\/close|Page\.close|_stop_browser_on_port\(|_cdp_browser_close\(|_browser_close_graceful\(|_close_target\(|\.kill\(\)|\.terminate\(\)|SIGKILL|SIGTERM|Target\.disposeBrowserContext|Storage\.clearDataForOrigin|Network\.deleteCookies|Network\.clearBrowserCookies|Storage\.clearCookies|Browser\.resetPermissions/;
    const lines = PY_CONTENT.split('\n');
    const bodies = {};
    const hits = {};
    let cur = '<module>';
    for (const line of lines) {
      const m = line.match(/^(?:async\s+)?def\s+(\w+)|^class\s+(\w+)/);
      if (m) cur = m[1] || m[2];
      else if (/^[A-Za-z_]/.test(line)) cur = '<module>';
      bodies[cur] = (bodies[cur] || '') + line + '\n';
      if (/^\s*#/.test(line)) continue;
      if (PAT.test(line)) (hits[cur] = hits[cur] || []).push(line.trim());
    }
    const known = new Set([...GUARDED, ...Object.keys(VIA_GUARDED_HELPER), ...NOT_A_BROWSER,
      ...OWN_CONTEXT_ONLY]);
    for (const f of OWN_CONTEXT_ONLY) {
      for (const h of hits[f] || []) {
        assert(/Target\.disposeBrowserContext/.test(h), `${f} may only dispose its own context: ${h}`);
      }
      if (f !== '_dispose_context') {
        assert(/Target\.createBrowserContext/.test(bodies[f]), `${f} must create the context it disposes`);
      }
    }
    const disposeCallers = Object.keys(bodies).filter((f) => f !== '_dispose_context'
      && /_dispose_context\(/.test(bodies[f]));
    assert.deepStrictEqual(disposeCallers, ['cmd_go'], `_dispose_context callers: ${disposeCallers}`);
    assert(/ctx_id_to_dispose = ctx_id/.test(bodies.cmd_go) && /_new_isolated_context\(/.test(bodies.cmd_go),
      'cmd_go may only dispose the context _new_isolated_context made');
    assert(/_bot_auth_pid_is_signer\(state, port\):\s*\n\s*pid = int\(state\["pid"\]\)[\s\S]*?os\.kill\(pid, signal\.SIGTERM\)/
      .test(bodies._bot_auth_stop_helper), '_bot_auth_stop_helper signals only a proven signer');
    const signerStoppers = Object.keys(bodies).filter((f) => f !== '_bot_auth_stop_helper'
      && /_bot_auth_stop_helper\(/.test(bodies[f]));
    assert.deepStrictEqual(signerStoppers, ['_stop_browser_on_port'], `signer stop callers: ${signerStoppers}`);
    assert(/proven = _owned_browser\(port\) is not None[\s\S]*?if proven or _is_port_free\(port\):\s*\n\s*_bot_auth_stop_helper\(port\)/
      .test(bodies._stop_browser_on_port), 'the signer is stopped only next to a proven browser or a free port');
    const unknown = Object.keys(hits).filter((f) => !known.has(f));
    assert.deepStrictEqual(unknown, [],
      `new destructive call site(s) outside the guarded helpers: ${unknown.map((f) => `${f}: ${hits[f][0]}`).join(' | ')}`);
    for (const f of GUARDED) {
      assert(bodies[f], `guarded function ${f} is gone — update the tripwire`);
      assert(/_is_external\(|_refuse_external\(/.test(bodies[f]),
        `${f} must call _is_external() (or _refuse_external()) before closing/killing`);
    }
    for (const [f, allowed] of Object.entries(VIA_GUARDED_HELPER)) {
      for (const h of hits[f] || []) {
        assert(allowed.test(h), `${f} may only reach a browser via a guarded helper: ${h}`);
      }
    }
    // The helpers that actually send Browser.close / signal: the guard comes first.
    for (const f of ['_stop_browser_on_port', '_cdp_browser_close', '_browser_close_graceful']) {
      const body = bodies[f];
      const guard = body.search(/_is_external\(/);
      const act = body.search(/\n\s+(?!#)[^\n]*(Browser\.close"|_cdp_browser_close\(port\)|os\.kill\()/);
      assert(guard > 0 && (act < 0 || guard < act), `${f}: _is_external() must run before it acts`);
    }
  });

  // ── Unit: connect wired into dispatch, documented ──

  test('connect: wired into dispatch, documented (CHANGELOG, help, python __doc__)', () => {
    assert(/'connect':\s*lambda:\s*cmd_connect\(\*args\)/.test(PY_CONTENT),
      "'connect' must be in sync_cmds");
    assert(/'disconnect':\s*cmd_disconnect/.test(PY_CONTENT),
      "'disconnect' must be in sync_cmds");
    const skip = PY_CONTENT.match(/AUTOLAUNCH_SKIP_CMDS = frozenset\(\{([\s\S]*?)\}\)/)[1];
    assert(/'connect'/.test(skip), "'connect' must never launch the browser");
    assert(/'disconnect'/.test(skip), "'disconnect' must never launch the browser");
    const changelog = fs.readFileSync(path.join(__dirname, '..', 'CHANGELOG.md'), 'utf8');
    const unreleased = changelog.split(/^## \[/m)[1] || '';
    assert(unreleased && unreleased.includes('cdpilot connect'),
      'CHANGELOG [Unreleased] must describe `cdpilot connect`');
    const readme = fs.readFileSync(path.join(__dirname, '..', 'README.md'), 'utf8');
    assert(readme.includes('Use your own browser'), 'README must have connect section');
    assert(readme.includes('cdpilot connect --auto'), 'README must mention --auto');
    const help = run('--help');
    assert(help.includes('connect'), 'help must mention connect');
    assert(help.includes('disconnect'), 'help must mention disconnect');
    assert(/browser_connect/.test(PY_CONTENT), 'MCP must have browser_connect tool');
    assert(/browser_disconnect/.test(PY_CONTENT), 'MCP must have browser_disconnect tool');
    assert(PY_CONTENT.slice(0, 2500).includes('CDPILOT_BROWSER_SEARCH_ROOT'),
      'python __doc__ must document CDPILOT_BROWSER_SEARCH_ROOT');
  });

  test('connect: README and CHANGELOG say what the code does', () => {
    const readme = fs.readFileSync(path.join(__dirname, '..', 'README.md'), 'utf8');
    const sec = readme.split('### Use your own browser')[1].split('\n### ')[0];
    assert(!/--mode stealth/.test(sec), 'README: there is no --mode stealth flag');
    assert(!/Chrome\/131/.test(sec), 'README: no Chrome/131 in a Chrome 144+ flow');
    assert(!/fingerprint stays untouched|not applied automatically/.test(sec),
      'README: old claims about stealth must be gone');
    assert(/not supported yet[\s\S]{0,40}chrome:\/\/inspect|chrome:\/\/inspect[\s\S]*not (yet )?supported/i.test(sec),
      'README must say the chrome://inspect mode is not supported yet');
    assert(/--remote-debugging-port=\d+ --user-data-dir=/.test(sec),
      'README must show the supported --remote-debugging-port + --user-data-dir start');
    assert(/visible window|headless/i.test(sec), 'README must mention the no-connect path (own visible window)');
    assert(/Risks/i.test(sec), 'README must list the risks');
    const changelog = fs.readFileSync(path.join(__dirname, '..', 'CHANGELOG.md'), 'utf8');
    const unreleased = changelog.split(/^## \[/m)[1] || '';
    assert(!/Chrome 144\+ with remote debugging enabled via `chrome:\/\/inspect/.test(unreleased),
      'CHANGELOG must not promise chrome://inspect support');
    assert(!/Stealth injections are NOT applied automatically/.test(unreleased),
      'CHANGELOG: stale stealth claim');
  });

  // ── E2E: connect to a headless Chrome started by the test itself ──

  function findBrowserBin() {
    const candidates = [
      process.env.CHROME_BIN,
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
      '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
      '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
      '/usr/bin/chromium', '/usr/bin/chromium-browser',
    ].filter(Boolean);
    return candidates.find((c) => fs.existsSync(c)) || null;
  }

  // The first page target titled USER-MAIL (or the first page), read straight
  // over CDP (not through cdpilot); `expr` is evaluated in it.
  function userTab(cdpPort, expr) {
    const r = spawnSync(PY_BIN, ['-c', [
      'import asyncio, json, sys, urllib.request, websockets',
      `pages = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:${cdpPort}/json").read()) if t.get("type") == "page"]`,
      'tab = next((t for t in pages if t.get("title") == "USER-MAIL"), pages[0] if pages else None)',
      'async def ev():',
      '    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2**24) as ws:',
      `        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": ${JSON.stringify(expr)}, "returnByValue": True}}))`,
      '        while True:',
      '            m = json.loads(await ws.recv())',
      '            if m.get("id") == 1:',
      '                return m["result"]["result"].get("value")',
      // A headless background tab sometimes leaves one evaluate unanswered for
      // seconds (measured: 3 of 17 probes, each fine on the next try): retry.
      'value, err = None, None',
      'for _ in range(6):',
      '    try:',
      '        value = asyncio.run(asyncio.wait_for(ev(), 5)) if tab else None',
      '        err = None',
      '        break',
      '    except Exception as e:',
      '        err = repr(e)',
      'if err:',
      '    sys.exit("probe failed: " + err)',
      'print(json.dumps({"id": tab and tab["id"], "title": tab and tab["title"], "url": tab and tab["url"], "value": value, "pages": len(pages)}))',
    ].join('\n')], { encoding: 'utf-8', timeout: 20000 });
    try { return JSON.parse(r.stdout.trim()); } catch { return { error: `${r.status} ${r.stdout} ${r.stderr}`.slice(-600) }; }
  }

  function startHeadless(browserBin, cdpPort, userDataDir, startUrl = 'about:blank') {
    const chrome = spawn(browserBin, [
      `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${userDataDir}`,
      '--headless=new', '--no-first-run', '--no-default-browser-check',
      '--disable-background-networking', '--remote-allow-origins=*', startUrl,
    ], { stdio: 'ignore', detached: true });
    chrome.unref();
    let wsPath = '';
    for (let i = 0; i < 60 && !wsPath; i++) {
      try {
        const vr = execFileSync(PY_BIN, ['-c',
          `import json, urllib.request; d = json.loads(urllib.request.urlopen("http://127.0.0.1:${cdpPort}/json/version", timeout=1).read()); print(d.get("webSocketDebuggerUrl",""))`
        ], { encoding: 'utf-8', timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'] });
        if (vr.trim()) wsPath = new URL(vr.trim()).pathname;
      } catch {}
      if (!wsPath) sleep(0.25);
    }
    const stop = () => {
      // The whole detached group: the browser and its helpers.
      try { process.kill(-chrome.pid, 'SIGTERM'); } catch {}
      sleep(0.5);
      try { process.kill(-chrome.pid, 'SIGKILL'); } catch {}
    };
    if (!wsPath) { stop(); throw new Error('Chrome did not start in time'); }
    return { chrome, pid: chrome.pid, wsPath, stop };
  }

  if (process.env.CDPILOT_E2E !== '1') {
    console.log('  - skipped: connect e2e (set CDPILOT_E2E=1)');
  } else {
    let e2eConnect = null;

    test('connect e2e: start a headless Chrome and connect to it', () => {
      const home = mkHome();
      const userDataDir = path.join(home, 'chrome-profile');
      fs.mkdirSync(userDataDir, { recursive: true });
      const cdpPort = freePort();
      const browserBin = findBrowserBin();
      assert(browserBin, 'No browser found for e2e connect test');

      // Start the browser ourselves (NOT via cdpilot) with --user-data-dir and
      // --remote-debugging-port. Its one tab is "the user's": a known title and
      // a form with text typed but never saved.
      const userUrl = 'data:text/html,<title>USER-MAIL</title><textarea id="draft"></textarea>';
      const browser = startHeadless(browserBin, cdpPort, userDataDir, userUrl);
      const user = userTab(cdpPort, 'document.getElementById("draft").value = "unsaved draft 42"; document.title');
      assert(user && user.title === 'USER-MAIL', `user tab not ready: ${JSON.stringify(user)}`);
      const env = isoEnv(home, cdpPort, 'connect-e2e', { CDPILOT_PROFILE: path.join(home, 'cdpilot-profile') });
      const c = (...cArgs) => spawnSync(process.execPath, [CLI, ...cArgs], {
        encoding: 'utf-8', timeout: 60000, env,
      });
      e2eConnect = { c, browser, cdpPort, home, env, pid: browser.pid, user };
    });

    const needConnect = () => { assert(e2eConnect, 'connect e2e setup failed'); return e2eConnect; };
    const browserAlive = () => {
      const { pid, cdpPort } = needConnect();
      return procAlive(pid) && cdpAnswers(cdpPort);
    };

    try {
      test('connect e2e: connect <port> registers external browser', () => {
        const { c, cdpPort } = needConnect();
        const r = c('connect', String(cdpPort));
        assert.strictEqual(r.status, 0, `connect exit: ${r.status}\nstdout: ${r.stdout}\nstderr: ${r.stderr}`);
        assert(/Connected to/.test(r.stdout), `should say Connected: ${r.stdout}`);
        assert(/will never close/.test(r.stdout), `should say never close: ${r.stdout}`);
        assert(/cookies and sessions/.test(r.stderr), `should warn about cookies: ${r.stderr}`);
      });

      test('connect e2e: the user tab survives connect + go + content unchanged (title, URL, unsaved text)', () => {
        const { c, cdpPort, user } = needConnect();
        const g = c('go', 'data:text/html,<title>AGENT</title><p>agent page</p>');
        assert.strictEqual(g.status, 0, `go: ${g.stdout}${g.stderr}`);
        const t = c('content');
        assert.strictEqual(t.status, 0, `content: ${t.stdout}${t.stderr}`);
        assert(/agent page/.test(t.stdout), `content reads cdpilot's own tab: ${t.stdout}`);
        const after = userTab(cdpPort, 'document.getElementById("draft").value');
        assert(after, 'user tab must still exist');
        assert.strictEqual(after.id, user.id, 'same user tab (not closed and reopened)');
        assert.strictEqual(after.title, 'USER-MAIL', `user tab title changed: ${JSON.stringify(after)}`);
        assert.strictEqual(after.url, user.url, 'user tab URL changed');
        assert.strictEqual(after.value, 'unsaved draft 42', 'unsaved text in the user tab was lost');
        assert.strictEqual(after.pages, user.pages + 1, 'cdpilot opened exactly one tab of its own');
      });

      test('connect e2e: go, content, smart-click work on the connected browser', () => {
        const { c } = needConnect();
        const g = c('go', 'data:text/html,<h1>Hello</h1><button onclick="document.title=\'clicked\'">Click me</button>');
        assert.strictEqual(g.status, 0, `go: ${g.stdout}${g.stderr}`);
        const t = c('content');
        assert.strictEqual(t.status, 0, `content: ${t.stdout}${t.stderr}`);
        assert(/Hello/.test(t.stdout), `content should have Hello: ${t.stdout}`);
        const cl = c('smart-click', 'Click me');
        assert.strictEqual(cl.status, 0, `smart-click: ${cl.stdout}${cl.stderr}`);
        const title = c('eval', 'document.title');
        assert(/clicked/.test(title.stdout), `title should be clicked: ${title.stdout}`);
      });

      for (const args of [['close', '--force'], ['stop', '--smart', '--force'],
        ['project-stop', 'connect-e2e'], ['stop'], ['stop-all']]) {
        test(`connect e2e: \`${args.join(' ')}\` leaves the connected Chrome running`, () => {
          const { c } = needConnect();
          const r = c(...args);
          assert.strictEqual(r.status, 0, `${args.join(' ')} exit: ${r.status}\nstdout: ${r.stdout}\nstderr: ${r.stderr}`);
          assert((r.stdout + r.stderr).includes(LEFT_RUNNING), `should say left running: ${r.stdout}${r.stderr}`);
          sleep(1);  // a Browser.close would have ended it by now
          assert(browserAlive(), `Chrome must still be running after ${args.join(' ')}`);
          const t = c('content');
          assert.strictEqual(t.status, 0, `still connected after ${args.join(' ')}: ${t.stdout}${t.stderr}`);
        });
      }

      test('connect e2e: disconnect forgets the browser, which keeps running', () => {
        const { c, home } = needConnect();
        const r = c('disconnect');
        assert.strictEqual(r.status, 0, `disconnect exit: ${r.status}\nstdout: ${r.stdout}\nstderr: ${r.stderr}`);
        assert(/Disconnected/.test(r.stdout + r.stderr), `should say Disconnected: ${r.stdout}`);
        assert(/keeps running/.test(r.stdout + r.stderr), `should say keeps running: ${r.stdout}`);
        assert(!readRegistry(home)['connect-e2e'], 'entry must be gone after disconnect');
        assert(browserAlive(), 'browser process should still be alive after disconnect');
        const { cdpPort, user } = needConnect();
        const after = userTab(cdpPort, 'document.getElementById("draft").value');
        assert(after && after.id === user.id && after.title === 'USER-MAIL'
          && after.value === 'unsaved draft 42', `user tab after the whole run: ${JSON.stringify(after)}`);
      });
    } finally {
      if (e2eConnect) e2eConnect.browser.stop();
    }

    // ── E2E: --auto with a DevToolsActivePort pointing at the test's Chrome ──

    test('connect e2e: --auto finds DevToolsActivePort written by test', () => {
      const home = mkHome();
      const userDataDir = path.join(home, 'chrome-profile');
      fs.mkdirSync(userDataDir, { recursive: true });
      const cdpPort = freePort();
      const browserBin = findBrowserBin();
      if (!browserBin) {
        console.log('  - skipped: connect --auto e2e (no browser found)');
        return;
      }
      const browser = startHeadless(browserBin, cdpPort, userDataDir);
      try {
        // Chrome wrote its own DevToolsActivePort into the profile: use that
        // dir as a search root entry, plus a stale file next to it.
        const searchRoot = path.join(home, 'browsers');
        fs.mkdirSync(path.join(searchRoot, 'AStale'), { recursive: true });
        fs.writeFileSync(path.join(searchRoot, 'AStale', 'DevToolsActivePort'),
          `${freePort()}\n/devtools/browser/left-over\n`);
        const browserDir = path.join(searchRoot, 'TestChrome');
        fs.mkdirSync(browserDir, { recursive: true });
        const own = path.join(userDataDir, 'DevToolsActivePort');
        fs.writeFileSync(path.join(browserDir, 'DevToolsActivePort'),
          fs.existsSync(own) ? fs.readFileSync(own, 'utf-8') : `${cdpPort}\n${browser.wsPath}\n`);
        const r = cli(['connect', '--auto'], isoEnv(home, freePort(), 'auto-e2e',
          { CDPILOT_BROWSER_SEARCH_ROOT: searchRoot }), 15000);
        assert.strictEqual(r.status, 0, `--auto exit: ${r.status}\nstdout: ${r.stdout}\nstderr: ${r.stderr}`);
        assert(/Connected to/.test(r.stdout), `should say Connected: ${r.stdout}`);
        assert(/will never close/.test(r.stdout), `should say never close: ${r.stdout}`);
        assert(/skipped AStale/.test(r.stderr), `stale file must be skipped: ${r.stderr}`);
        assert.strictEqual(readRegistry(home)['auto-e2e'].port, parseInt(cdpPort, 10));
      } finally {
        browser.stop();
      }
    });

    // ── E2E repro (#26 re-review): the user's Chrome on a port that a stale
    // registry entry (a cdpilot browser that died) still names ──

    test('connect e2e: stale entry + the user\'s Chrome on its port → stop/close leave Chrome and its tab alone, connect works', () => {
      const home = mkHome();
      const userDataDir = path.join(home, 'chrome-profile');
      fs.mkdirSync(userDataDir, { recursive: true });
      const cdpPort = freePort();
      const browserBin = findBrowserBin();
      assert(browserBin, 'No browser found for e2e stale-entry test');
      const userUrl = 'data:text/html,<title>USER-MAIL</title><textarea id="draft"></textarea>';
      const browser = startHeadless(browserBin, cdpPort, userDataDir, userUrl);
      try {
        // /json can list the tab before its title is set: wait for both.
        let user = null;
        for (let i = 0; i < 20 && !(user && user.title === 'USER-MAIL'); i++) {
          if (i) sleep(0.25);
          user = userTab(cdpPort, 'document.getElementById("draft").value = "unsaved draft 7"; document.title');
        }
        assert(user && user.title === 'USER-MAIL', `user tab not ready: ${JSON.stringify(user)}`);
        const env = isoEnv(home, cdpPort, 'stale-e2e', { CDPILOT_PROFILE: path.join(home, 'cdpilot-profile') });
        const stale = [
          { pid: deadPid() },                                     // older entry, no GUID
          { pid: deadPid(), browser_guid: 'guid-of-a-dead-run' },  // GUID of the dead browser
        ];
        for (const extra of stale) {
          for (const args of [['stop'], ['close', '--force'], ['project-stop', 'stale-e2e'], ['stop-all']]) {
            writeRegistry(home, { 'stale-e2e': { cwd: '/x', port: parseInt(cdpPort, 10),
              profile_dir: path.join(home, 'cdpilot-profile'), status: 'running',
              created: 'x', last_used: 'x', ...extra } });
            const r = cli(args, env);
            assert.strictEqual(r.status, 0, `${args.join(' ')}: ${r.stdout}${r.stderr}`);
            sleep(1);  // a Browser.close or a signal would have ended it by now
            assert(procAlive(browser.pid) && cdpAnswers(cdpPort),
              `the user's Chrome must survive \`${args.join(' ')}\` (${JSON.stringify(extra)}): ${r.stdout}${r.stderr}`);
          }
        }
        const r = cli(['connect', String(cdpPort)], env);
        assert.strictEqual(r.status, 0, `connect must replace the stale entry: ${r.stdout}${r.stderr}`);
        assert(readRegistry(home)['stale-e2e'].external, 'registered as external');
        const after = userTab(cdpPort, 'document.getElementById("draft").value');
        assert(after && after.id === user.id && after.value === 'unsaved draft 7',
          `user tab unchanged: ${JSON.stringify(after)}`);
        cli(['disconnect'], env);
      } finally {
        browser.stop();
      }
    });
  }
})();

// ── WebMCP tests ──
// Browserless: test/webmcp_fake_cdp.py runs the real `tools list/call` code
// over a fake CDP wire; each Runtime.evaluate it sends is executed by
// test/webmcp_fake_page.js against a recording document.modelContext, so
// these tests check what the evaluated code did (getTools, executeTool and
// its options), not its source. Opt-in e2e (CDPILOT_E2E=1): a real headless
// browser started with `launch --webmcp` only, fixtures in test/fixtures/webmcp.
(function() {
  const { execFileSync, spawn, spawnSync } = require('child_process');
  const os = require('os');
  const PYB = process.env.CDPILOT_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const PY_PATH = path.join(__dirname, '..', 'src', 'cdpilot.py');

  let fakeResults = null;
  function fake(name) {
    if (!fakeResults) {
      const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-webmcp-fake-'));
      const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
        CDP_PORT: '19225', CDPILOT_LOG: '0' };
      delete env.CDPILOT_WEBMCP;
      delete env.CDPILOT_TIMEOUT;
      const out = execFileSync(PYB, [path.join(__dirname, 'webmcp_fake_cdp.py'), PY_PATH,
        process.execPath], { encoding: 'utf-8', timeout: 120000, env });
      fakeResults = JSON.parse(out.trim().split('\n').pop());
    }
    const r = fakeResults[name];
    assert(r, `fake-CDP scenario ${name} missing`);
    assert(!r.error, `fake-CDP scenario ${name} failed:\n${r.error}`);
    return r;
  }
  // A tools command only asks for cdpilot's isolated world in the top frame and
  // evaluates there (contextId 77 in the fake): no Runtime.enable, nothing
  // injected, no main-world evaluate.
  const isolatedOnly = (run, what) => {
    assert(run.wire.length > 0, `${what}: sent nothing`);
    for (const m of run.wire) {
      if (m.method === 'Page.getFrameTree') continue;
      if (m.method === 'Page.createIsolatedWorld') {
        assert.strictEqual(m.params.frameId, 'TOP', what);
        assert.strictEqual(m.params.worldName, 'cdpilot', what);
        continue;
      }
      assert.strictEqual(m.method, 'Runtime.evaluate', `${what}: sent ${m.method}`);
      assert.deepStrictEqual(m.params, { returnByValue: true, awaitPromise: true, contextId: 77 },
        `${what}: evaluate params ${JSON.stringify(m.params)}`);
    }
    for (const c of [].concat(...run.calls)) assert.strictEqual(c.world, 'isolated', `${what}: ${c.fn} ran in ${c.world}`);
  };

  test('webmcp: tools list calls getTools() in an isolated world and reports title/annotations/frame/form', () => {
    const r = fake('list_routing');
    for (const shape of ['spec', 'legacy']) {
      const run = r[shape];
      isolatedOnly(run, shape);
      assert.strictEqual(run.exit, 0, run.stderr);
      assert.strictEqual(run.stderr, '', 'no main-world note');
      assert.deepStrictEqual(run.calls, [[{ fn: 'getTools', world: 'isolated', argc: 0 }]], shape);
      const tools = JSON.parse(run.stdout).tools;
      assert.deepStrictEqual(tools.map((t) => t.name), ['add_to_cart', 'frame_echo', 'subscribe_newsletter']);
      const [cart, frame, form] = tools;
      // Chrome 154 returns inputSchema as a JSON string; the spec as an object.
      assert.deepStrictEqual(cart.inputSchema.required, ['sku', 'qty'], `${shape}: schema is an object`);
      assert.strictEqual(cart.title, 'Add to cart');
      assert.strictEqual(cart.annotations.consequentialHint, true);
      assert.strictEqual(cart.frame, null);
      assert.strictEqual(frame.frame, 'https://shop.test/frame.html');
      assert.strictEqual(form.declarative, true);
      assert.strictEqual(form.autosubmit, true);
      assert.strictEqual(cart.declarative, false);
    }
  });

  test('webmcp: tools call runs executeTool(tool, input, {signal}) in an isolated world', () => {
    const r = fake('call_routing');
    for (const key of ['spec', 'legacy', 'frame', 'frame_filter']) {
      isolatedOnly(r[key], key);
      assert.strictEqual(r[key].exit, 0, `${key}: ${r[key].stderr}`);
    }
    const exec = (run) => run.calls[1].filter((c) => c.fn === 'executeTool');
    // Spec shape: the input object itself, and options carrying an AbortSignal.
    const [spec] = exec(r.spec);
    assert.strictEqual(exec(r.spec).length, 1);
    assert.strictEqual(spec.name, 'add_to_cart');
    assert.deepStrictEqual(spec.input, { sku: 'A1', qty: 2 });
    assert.strictEqual(spec.inputType, 'object');
    assert.strictEqual(spec.argc, 3);
    assert.strictEqual(spec.signal, true, 'options.signal must be an AbortSignal');
    // Chrome 154 shape (executeTool.length 2): the JSON string, same options.
    const [legacy] = exec(r.legacy);
    assert.strictEqual(exec(r.legacy).length, 1, 'no failed first attempt');
    assert.strictEqual(legacy.inputType, 'string');
    assert.deepStrictEqual(JSON.parse(legacy.input), { sku: 'A1', qty: 2 });
    assert.strictEqual(legacy.signal, true);
    // The tool's JSON result string is printed as JSON.
    assert.deepStrictEqual(JSON.parse(r.spec.stdout), { ok: true, tool: 'add_to_cart', got: { sku: 'A1', qty: 2 } });
    // A same-origin iframe's tool runs on that frame's tool object.
    assert.strictEqual(exec(r.frame)[0].frame, 'frame');
    assert.strictEqual(exec(r.frame_filter)[0].name, 'frame_echo');
  });

  test('webmcp: tools call aborts the execution signal when its time budget ends (exit 124)', () => {
    const r = fake('call_timeout');
    isolatedOnly(r, 'timeout');
    assert.strictEqual(r.exit, 124, r.stderr);
    assert.deepStrictEqual(r.calls[1].map((c) => c.fn), ['getTools', 'executeTool', 'aborted']);
    assert.strictEqual(r.calls[1][2].reason, 'TimeoutError');
    assert(/timed out after 0\.3s; its execution was aborted/.test(r.stderr), r.stderr);
  });

  test('webmcp: a page that wraps getTools/executeTool cannot add tools, change results or see the calls', () => {
    const r = fake('hostile_page');
    for (const key of ['list', 'call', 'fake']) isolatedOnly(r[key], key);
    const seen = (run) => [].concat(...run.calls).map((c) => c.fn);
    for (const key of ['list', 'call', 'fake']) {
      assert(!seen(r[key]).some((f) => f.startsWith('patched:')), `${key}: the page's wrappers ran`);
    }
    assert.deepStrictEqual(JSON.parse(r.list.stdout).tools.map((t) => t.name),
      ['add_to_cart', 'frame_echo', 'subscribe_newsletter'], 'only the real tools');
    assert.strictEqual(r.call.exit, 0, r.call.stderr);
    assert.deepStrictEqual(JSON.parse(r.call.stdout), { ok: true, tool: 'add_to_cart', got: { sku: 'A1', qty: 2 } },
      'the real result, not the hijacked one');
    assert.strictEqual(r.fake.exit, 1);
    assert(/tool 'fake_tool' not found/.test(r.fake.stderr), r.fake.stderr);
  });

  test('webmcp: without a usable isolated world it falls back to the main world with one note', () => {
    const r = fake('world_fallback');
    for (const s of ['isoblind', 'noworld']) {
      const { list, call } = r[s];
      assert.strictEqual(list.exit, 0, list.stderr);
      assert.strictEqual(JSON.parse(list.stdout).tools.length, 3, s);
      assert.strictEqual(call.exit, 0, call.stderr);
      assert.deepStrictEqual(JSON.parse(call.stdout).got, { sku: 'A1', qty: 2 });
      for (const run of [list, call]) {
        assert.strictEqual(run.stderr.trim().split('\n').length, 1, `${s}: one note: ${run.stderr}`);
        assert(/not visible from an isolated world.*main world/.test(run.stderr), run.stderr);
      }
      const exec = [].concat(...call.calls).filter((c) => c.fn === 'executeTool');
      assert.deepStrictEqual(exec.map((c) => c.world), ['main'], `${s}: the call follows the list's world`);
      assert(!call.wire.some((m) => m.method === 'Runtime.enable'));
    }
  });

  test('webmcp: one tool name in two frames: ambiguous without --frame, --frame picks one', () => {
    const r = fake('two_frames');
    const frames = JSON.parse(r.list.stdout).tools.filter((t) => t.name === 'frame_echo').map((t) => t.frame);
    assert.deepStrictEqual(frames, ['https://shop.test/frame.html', 'https://shop.test/frame.html?who=right']);
    const exec = (run) => [].concat(...run.calls).filter((c) => c.fn === 'executeTool');
    for (const key of ['ambiguous', 'both']) {
      assert.strictEqual(r[key].exit, 1, key);
      assert(/registered in several frames .*pick one with --frame/.test(r[key].stderr), r[key].stderr);
      assert.strictEqual(exec(r[key]).length, 0, `${key} must not execute`);
    }
    assert.strictEqual(r.right.exit, 0, r.right.stderr);
    assert.deepStrictEqual(exec(r.right).map((c) => c.frame), ['frame2']);
    assert.strictEqual(r.left.exit, 0, r.left.stderr);
    assert.deepStrictEqual(exec(r.left).map((c) => c.frame), ['frame'], 'an exact frame URL wins');
    assert.strictEqual(r.nomatch.exit, 1);
    assert(/not found in a frame matching 'nowhere'/.test(r.nomatch.stderr), r.nomatch.stderr);
  });

  test('webmcp: bad args and unknown tools never reach executeTool (exit 1)', () => {
    const r = fake('call_refusals');
    for (const [key, re] of [['missing', /missing required argument: qty/],
      ['bool_int', /qty: expected integer, got boolean/], ['unknown', /tool 'nope' not found/],
      ['noapi', /cannot call 'add_to_cart': document\.modelContext is missing/]]) {
      assert.strictEqual(r[key].exit, 1, key);
      assert(re.test(r[key].stderr), `${key}: ${r[key].stderr}`);
      const executed = [].concat(...r[key].calls).filter((c) => c.fn === 'executeTool');
      assert.strictEqual(executed.length, 0, `${key} must not execute`);
    }
  });

  test('webmcp: tools list with no usable tools exits 0 and says why', () => {
    const r = fake('list_diagnosis');
    for (const [key, reason] of [['noapi', 'flag-off'], ['insecure', 'insecure-context'],
      ['refused', 'not-origin-keyed']]) {
      assert.strictEqual(r[key].exit, 0, key);
      const out = JSON.parse(r[key].stdout);
      assert.deepStrictEqual(out.tools, []);
      assert.strictEqual(out.reason, reason, key);
      assert.strictEqual(out.available, false);
    }
    assert(/launch --webmcp/.test(JSON.parse(r.noapi.stdout).hint));
  });

  test('webmcp: argument validator (required, type with bool != integer, enum, const, unions, nested)', () => {
    const v = fake('validate');
    const pass = ['ok', 'int_is_number', 'float_integral_is_integer', 'enum_ok', 'enum_1_ok',
      'const_ok', 'union_null_ok', 'unsupported_keywords_deferred', 'no_schema', 'empty_schema'];
    for (const k of pass) assert.deepStrictEqual(v[k], [true, null], k);
    const fail = {
      missing_required: 'missing required argument: n',
      bool_not_integer: 'n: expected integer, got boolean',
      bool_not_number: 'x: expected number, got boolean',
      float_not_integer: 'n: expected integer, got number',
      string_not_integer: 'n: expected integer, got string',
      enum_bad: 's: must be one of ["a", "b"]',
      enum_true_is_not_1: 'one: must be one of [1, "1"]',
      const_bad: 'c: must be true',
      union_bad: 'u: expected string or null, got integer',
      items_bad: 'arr[1]: expected integer, got string',
      nested_required: 'o: missing required argument: k',
      nested_type: 'o.k: expected string, got integer',
      not_object: 'arguments must be a JSON object',
    };
    for (const [k, msg] of Object.entries(fail)) assert.deepStrictEqual(v[k], [false, msg], k);
  });

  test('webmcp: diagnosis names the cause (flag off, insecure, old browser, legacy API, policy)', () => {
    const d = fake('diagnose');
    assert.strictEqual(d.no_tools[0], 'no-tools');
    assert.strictEqual(d.insecure[0], 'insecure-context');
    assert.strictEqual(d.old[0], 'old-browser');
    assert(/Chromium 146/.test(d.old[1]), d.old[1]);
    assert.strictEqual(d.legacy[0], 'legacy-api');
    assert.strictEqual(d.flag_off_mode_off[0], 'flag-off');
    assert(/launch --webmcp/.test(d.flag_off_mode_off[1]), d.flag_off_mode_off[1]);
    assert(/mode is on/.test(d.flag_off_mode_on[1]) && !/--webmcp`/.test(d.flag_off_mode_on[1]),
      d.flag_off_mode_on[1]);
    assert.strictEqual(d.not_origin_keyed[0], 'not-origin-keyed');
    assert.strictEqual(d.policy[0], 'policy');
  });

  test('webmcp: mode persists in webmcp.json, CDPILOT_WEBMCP overrides, launch merges --enable-features', () => {
    const m = fake('mode_and_flags');
    assert.strictEqual(m.absent, false);
    assert.strictEqual(m.saved_on, true);
    assert.strictEqual(m.env_off_wins, false);
    assert.strictEqual(m.saved_off, false);
    assert.strictEqual(m.env_on_wins, true);
    assert.strictEqual(m.corrupt, false);
    assert.deepStrictEqual(m.flag, [true, false, null, null]);
    assert.deepStrictEqual(m.args_plain, ['chrome', '--disable-features=Translate', '--enable-features=WebMCP']);
    assert.deepStrictEqual(m.args_merge, ['chrome', '--enable-features=Foo,WebMCP']);
    assert.deepStrictEqual(m.args_dedup, ['chrome', '--enable-features=WebMCP']);
  });

  test('webmcp: session log redacts secret-named fields in tools call args and in results', () => {
    const r = fake('redaction');
    const json = JSON.parse(r.args[2]);
    assert.strictEqual(json.user, 'ann');
    assert.strictEqual(json.password, '«redacted:7 chars»');
    assert.strictEqual(json.nested.api_key, '«redacted:6 chars»');
    assert.strictEqual(r.args[4], 'token=«redacted:9 chars»');
    assert.strictEqual(r.args[5], '--arg=qty=2');
    assert.strictEqual(r.args[7], 'frame.html');
    for (const s of ['hunter2', 'sk-abc', 't0ps3cret']) assert(r.secrets.includes(s), s);
    const sum = JSON.parse(r.summary);
    assert.strictEqual(sum.user, 'ann');
    assert.strictEqual(sum.session_token, '«redacted:10 chars»');
    assert.strictEqual(sum.profile.secret, '«redacted:12 chars»');
    assert.strictEqual(sum.profile.name, 'Ann');
    assert.strictEqual(sum.items[0].auth, '«redacted:7 chars»');
    for (const s of ['zz-9876543', 's3cr3t-value', 'abc-123']) assert(!r.summary.includes(s), s);
    assert.deepStrictEqual(JSON.parse(r.plain), { ok: true, qty: 2 });
  });

  // One MCP server per mode: tools/list, and a browser_site_tools call.
  function mcpTools(extraEnv, modeFile) {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-webmcp-mcp-'));
    const profile = path.join(home, 'profile');
    if (modeFile !== undefined) {
      fs.mkdirSync(profile, { recursive: true });
      fs.writeFileSync(path.join(profile, 'webmcp.json'), JSON.stringify({ webmcp: modeFile }));
    }
    const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: profile, CDP_PORT: '19226',
      CDPILOT_LOG: '0', CDPILOT_NO_AUTOLAUNCH: '1', ...extraEnv };
    if (!('CDPILOT_WEBMCP' in extraEnv)) delete env.CDPILOT_WEBMCP;
    const reqs = [{ jsonrpc: '2.0', id: 1, method: 'tools/list' },
      { jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'browser_site_tools', arguments: {} } }];
    const r = spawnSync(PYB, [PY_PATH, 'mcp'], { input: reqs.map((x) => JSON.stringify(x)).join('\n') + '\n',
      encoding: 'utf-8', timeout: 60000, env });
    const res = r.stdout.trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
    return { names: res.find((x) => x.id === 1).result.tools.map((t) => t.name), call: res.find((x) => x.id === 2) };
  }

  test('webmcp: MCP tools/list is 45 tools with WebMCP off (43 + browser_connect/browser_disconnect), 47 with it on', () => {
    const off = mcpTools({});
    assert.strictEqual(off.names.length, 45, `off: ${off.names.length}`);
    assert(!off.names.some((n) => n.startsWith('browser_site_')), 'off: no browser_site_* tools');
    assert(off.names.includes('browser_connect') && off.names.includes('browser_disconnect'), 'connect tools');
    assert(/Unknown tool: browser_site_tools/.test(JSON.stringify(off.call)), 'off: not callable');
    const offByFile = mcpTools({}, false);
    assert.strictEqual(offByFile.names.length, 45);
    for (const on of [mcpTools({ CDPILOT_WEBMCP: '1' }), mcpTools({}, true)]) {
      assert.strictEqual(on.names.length, 47, `on: ${on.names.length}`);
      assert.deepStrictEqual(on.names.slice(0, 45), off.names, 'the 45 base tools are unchanged');
      assert.deepStrictEqual(on.names.slice(45), ['browser_site_tools', 'browser_site_tool_call']);
      assert(!/Unknown tool/.test(JSON.stringify(on.call)), 'on: browser_site_tools routes to the CLI');
    }
  });

  test('webmcp: launch --webmcp saves the mode for later processes; status shows it only while on', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-webmcp-mode-'));
    const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: '19227', CDPILOT_LOG: '0', CHROME_BIN: path.join(home, 'no-such-browser') };
    delete env.CDPILOT_WEBMCP;
    const status = () => spawnSync(process.execPath, [CLI, 'status'], { encoding: 'utf-8', timeout: 20000, env }).stdout;
    // Mode off: the output is exactly what it was before WebMCP existed.
    const plain = '\n  cdpilot status (port 19227)\n\n  ❌ No browser connected on this port.\n  Run: cdpilot launch\n\n';
    assert.strictEqual(status(), plain, 'default status unchanged');
    // No browser here: launch fails to start one, the mode is saved first.
    spawnSync(PYB, [PY_PATH, 'launch', '--webmcp'], { encoding: 'utf-8', timeout: 30000, env });
    assert.deepStrictEqual(JSON.parse(fs.readFileSync(path.join(home, 'profile', 'webmcp.json'), 'utf8')), { webmcp: true });
    const on = status();
    assert(/\n  ❌ No browser connected on this port\.\n  WebMCP: on \(launch --webmcp; browsers start with --enable-features=WebMCP\)\n  Run: cdpilot launch\n/.test(on), on);
    spawnSync(PYB, [PY_PATH, 'launch', '--no-webmcp'], { encoding: 'utf-8', timeout: 30000, env });
    assert.strictEqual(status(), plain, 'status after launch --no-webmcp');
    assert(/WebMCP: on \(CDPILOT_WEBMCP;/.test(spawnSync(process.execPath, [CLI, 'status'],
      { encoding: 'utf-8', timeout: 20000, env: { ...env, CDPILOT_WEBMCP: '1' } }).stdout), 'env override');
  });

  test('webmcp: `tools` is in Available commands; help documents tools list/call and --webmcp', () => {
    const r = spawnSync(process.execPath, [CLI, 'no-such-command-xyz'], { encoding: 'utf-8', timeout: 20000,
      env: { ...process.env, CDP_PORT: '19222', CDPILOT_LOG: '0' } });
    const m = /Available commands: (.*)/.exec(r.stderr);
    assert(m, r.stderr);
    assert(m[1].split(', ').includes('tools'), m[1]);
    const help = run('--help');
    assert(/tools list/.test(help) && /tools call/.test(help) && /--webmcp/.test(help), 'help');
    const usage = spawnSync(PYB, [PY_PATH, 'tools'], { encoding: 'utf-8', timeout: 20000,
      env: { ...process.env, CDP_PORT: '19222', CDPILOT_LOG: '0' } });
    assert.strictEqual(usage.status, 1);
    assert(/Usage: tools list/.test(usage.stderr), usage.stderr);
  });

  if (process.env.CDPILOT_E2E !== '1') {
    console.log('  - skipped: webmcp e2e (set CDPILOT_E2E=1 to run it against a headless browser)');
    return;
  }

  const fixtures = path.join(__dirname, 'fixtures', 'webmcp');
  let e2e = null;
  test('webmcp e2e: headless browser started with `launch --webmcp` only, fixture server up', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-webmcp-e2e-'));
    const [cdpPort, httpPort] = JSON.parse(execFileSync(PYB, ['-c', [
      'import json, socket', 'ss = [socket.socket() for _ in range(2)]',
      '[s.bind(("127.0.0.1", 0)) for s in ss]',
      'print(json.dumps([s.getsockname()[1] for s in ss]))', '[s.close() for s in ss]',
    ].join('\n')], { encoding: 'utf-8', timeout: 10000 }).trim());
    const server = spawn(PYB, ['-m', 'http.server', String(httpPort), '--bind', '127.0.0.1'],
      { cwd: fixtures, stdio: 'ignore' });
    const trace = path.join(home, 'cdp-trace.txt');
    // No CDPILOT_WEBMCP anywhere: the mode must come from `launch --webmcp`.
    const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: String(cdpPort), CHROME_HEADLESS: '1', CDPILOT_LOG: '0', CDPILOT_CDP_TRACE: trace };
    delete env.CDPILOT_TARGET;
    delete env.CDPILOT_WEBMCP;
    delete env.CDPILOT_TIMEOUT;
    const c = (...args) => spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf-8', timeout: 60000, env });
    const stop = () => {
      c('stop');
      try { server.kill(); } catch (err) { /* already gone */ }
    };
    try {
      execFileSync(PYB, ['-c', [
        'import time, urllib.request',
        `url = "http://127.0.0.1:${httpPort}/shop.html"`,
        'for _ in range(50):',
        '    try: urllib.request.urlopen(url, timeout=1); break',
        '    except Exception: time.sleep(0.1)',
      ].join('\n')], { timeout: 20000 });
      const r = c('launch', '--webmcp');
      assert(/CDP ready/.test(r.stdout + r.stderr), `launch: ${r.stdout}${r.stderr}`);
      assert(/WebMCP: on \(--enable-features=WebMCP\)/.test(r.stdout), r.stdout);
    } catch (err) {
      stop();
      throw err;
    }
    e2e = { c, httpPort, stop, trace, skip: null };
    // Skip (never fail) only when this browser really has no native WebMCP:
    // started with the flag, on a secure page, and document.modelContext is
    // still missing in the page itself.
    c('go', `http://127.0.0.1:${httpPort}/shop.html`);
    const probe = c('eval', 'JSON.stringify([isSecureContext, typeof document.modelContext])');
    const [secure, api] = JSON.parse(probe.stdout.trim());
    if (secure === true && api === 'undefined') {
      const browser = (/Browser: (.*)/.exec(c('status').stdout) || [])[1] || 'this browser';
      e2e.skip = `${browser} has no native document.modelContext even with --enable-features=WebMCP`;
    } else {
      assert.deepStrictEqual([secure, api], [true, 'object'], probe.stdout + probe.stderr);
    }
  });
  if (e2e && e2e.skip) {
    console.log(`  - skipped: webmcp e2e (${e2e.skip})`);
    e2e.stop();
    return;
  }

  const ok = (r, re, what) => assert(re.test(r.stdout + r.stderr),
    `${what}: exit ${r.status}\nstdout: ${r.stdout}\nstderr: ${r.stderr}`);
  const needE2E = () => { assert(e2e, 'browser setup failed'); return e2e; };
  const listJson = (c) => {
    const r = c('tools', 'list', '--json');
    assert.strictEqual(r.status, 0, `tools list: ${r.stderr}`);
    return JSON.parse(r.stdout);
  };
  // Poll `cmd` until pred(result) (a navigation lands between two commands).
  const until = (fn, pred, what) => {
    let last;
    for (let i = 0; i < 25; i++) {
      last = fn();
      if (pred(last)) return last;
      execFileSync(process.execPath, ['-e', 'setTimeout(() => {}, 200)']);
    }
    assert.fail(`${what}: ${JSON.stringify(last)}`);
  };
  const evalJson = (c, js) => {
    const r = c('eval', `(async () => JSON.stringify(await (${js})))()`);
    assert.strictEqual(r.status, 0, r.stderr);
    return JSON.parse(r.stdout.trim());
  };

  try {
    test('webmcp e2e: go + tools list shows imperative, declarative and iframe tools with title/annotations', () => {
      const { c, httpPort, trace } = needE2E();
      ok(c('status'), /WebMCP: on/, 'status');
      ok(c('go', `http://127.0.0.1:${httpPort}/shop.html`), /WebMCP fixture shop/, 'go');
      fs.writeFileSync(trace, '');
      const out = until(() => listJson(c), (o) => o.tools.length === 4, 'four tools');
      const byName = Object.fromEntries(out.tools.map((t) => [t.name, t]));
      assert.deepStrictEqual(Object.keys(byName).sort(),
        ['add_to_cart', 'frame_echo', 'subscribe_newsletter', 'wait_for_abort']);
      assert.strictEqual(byName.add_to_cart.title, 'Add to cart');
      // Titles and annotations are passed through as the browser reports them;
      // which hints exist depends on the Chrome version (153 has no
      // consequentialHint), so compare with the page's own getTools().
      const native = evalJson(c, 'document.modelContext.getTools().then((ts) => Object.fromEntries('
        + 'ts.map((t) => [t.name, { title: t.title, annotations: t.annotations || null }])))');
      for (const t of out.tools) {
        assert.strictEqual(t.title, native[t.name].title || '', `${t.name} title`);
        assert.deepStrictEqual(t.annotations || null, native[t.name].annotations, `${t.name} annotations`);
      }
      const hasConsequential = 'consequentialHint' in (native.add_to_cart.annotations || {});
      if (hasConsequential) assert.strictEqual(byName.add_to_cart.annotations.consequentialHint, true);
      assert.deepStrictEqual(byName.add_to_cart.inputSchema.required, ['sku', 'qty']);
      const form = byName.subscribe_newsletter;
      assert.strictEqual(form.title, 'Subscribe', 'tooltitle');
      assert.strictEqual(form.declarative, true);
      assert.strictEqual(form.autosubmit, true, 'toolautosubmit');
      assert.strictEqual(form.inputSchema.properties.email.description, 'Customer email address',
        'toolparamdescription');
      assert.deepStrictEqual(form.inputSchema.required, ['email']);
      assert(/\/frame\.html$/.test(byName.frame_echo.frame), `frame: ${byName.frame_echo.frame}`);
      ok(c('tools', 'list'), hasConsequential
        ? /4 WebMCP tools on .*\n\s+add_to_cart\s+"Add to cart"\s+\[consequential\]/
        : /4 WebMCP tools on .*\n\s+add_to_cart\s+"Add to cart"/, 'human list');
      const sent = fs.readFileSync(trace, 'utf8').split('\n').filter(Boolean);
      assert(sent.includes('Runtime.evaluate') && sent.includes('Page.createIsolatedWorld'), sent.join(','));
      for (const bad of ['Runtime.enable', 'Page.addScriptToEvaluateOnNewDocument']) {
        assert(!sent.includes(bad), `tools list sent ${bad}`);
      }
      // Nothing of cdpilot's is left on the page (Chrome's own interfaces such as
      // WebMCPEvent are native functions); the API is the browser's own.
      assert.deepStrictEqual(evalJson(c, 'Object.getOwnPropertyNames(window).filter((k) => '
        + '/cdpilot|webmcp|modelcontext/i.test(k) && !/\\[native code\\]/.test(String(window[k])))'), []);
      assert.strictEqual(evalJson(c, 'String(document.modelContext.getTools).includes("[native code]")'), true);
    });

    test('webmcp e2e: tools call returns the real result and changes the page (imperative, form, iframe)', () => {
      const { c } = needE2E();
      const r = c('tools', 'call', 'add_to_cart', '{"sku":"A1","qty":2}');
      assert.strictEqual(r.status, 0, r.stderr);
      assert.deepStrictEqual(JSON.parse(r.stdout), { ok: true, sku: 'A1', qty: 2, cart_size: 1 });
      assert.deepStrictEqual(evalJson(c, 'window.__cart'), [{ sku: 'A1', qty: 2 }]);
      assert.strictEqual(evalJson(c, 'document.getElementById("status").textContent'), 'Cart: 1 items');
      const f = c('tools', 'call', 'subscribe_newsletter', '--arg', 'email=ann@example.com');
      assert.strictEqual(f.status, 0, f.stderr);
      assert.deepStrictEqual(JSON.parse(f.stdout), { subscribed: 'ann@example.com' }, 'respondWith() result');
      assert.deepStrictEqual(evalJson(c, '[window.__subscribed, window.__agentInvoked]'), ['ann@example.com', true]);
      const e = c('tools', 'call', 'frame_echo', '{"text":"hi"}');
      assert.strictEqual(e.status, 0, e.stderr);
      assert.deepStrictEqual(JSON.parse(e.stdout), { echo: 'hi', from: 'frame' });
      assert.strictEqual(evalJson(c,
        'document.getElementById("widget").contentDocument.getElementById("frame-status").textContent'), 'echoed: hi');
    });

    test('webmcp e2e: a page that wraps getTools/executeTool gets no fake tool, no hijacked result, no view of the calls', () => {
      const { c, httpPort } = needE2E();
      ok(c('go', `http://127.0.0.1:${httpPort}/patched.html`), /Patched API/, 'go');
      const out = until(() => listJson(c), (o) => o.tools.length > 0, 'patched page tools');
      assert.deepStrictEqual(out.tools.map((t) => t.name), ['real_counter'], 'only the real tool');
      const r = c('tools', 'call', 'real_counter', '{"by":3}');
      assert.strictEqual(r.status, 0, r.stderr);
      assert.deepStrictEqual(JSON.parse(r.stdout), { count: 3 }, 'the real result');
      const human = c('tools', 'list');
      assert(!/main world/.test(r.stderr + human.stderr), 'no main-world fallback');
      ok(human, /1 WebMCP tool on .*patched\.html/, 'human list');
      assert.strictEqual(evalJson(c, 'window.__count'), 3, 'the real tool ran');
      const fakeCall = c('tools', 'call', 'fake_tool', '{}');
      assert.strictEqual(fakeCall.status, 1);
      ok(fakeCall, /tool 'fake_tool' not found/, 'fake tool');
      assert.deepStrictEqual(evalJson(c, 'window.__seen'), [], "the page's wrappers never ran");
      // Sanity: in the page's own world the wrappers are live.
      assert.deepStrictEqual(evalJson(c, 'document.modelContext.getTools().then((t) => t.map((x) => x.name))'),
        ['real_counter', 'fake_tool']);
    });

    test('webmcp e2e: one tool name in two same-origin frames: --frame picks which one runs', () => {
      const { c, httpPort } = needE2E();
      c('go', `http://127.0.0.1:${httpPort}/twoframes.html`);
      const out = until(() => listJson(c), (o) => o.tools.length === 2, 'two frame tools');
      assert.deepStrictEqual(out.tools.map((t) => t.name), ['frame_echo', 'frame_echo']);
      assert.deepStrictEqual(out.tools.map((t) => t.frame.replace(/^.*\//, '')).sort(),
        ['frame.html?who=left', 'frame.html?who=right']);
      const amb = c('tools', 'call', 'frame_echo', '{"text":"x"}');
      assert.strictEqual(amb.status, 1);
      ok(amb, /registered in several frames .*--frame/, 'ambiguous');
      for (const who of ['left', 'right']) {
        const r = c('tools', 'call', 'frame_echo', '{"text":"x"}', '--frame', `who=${who}`);
        assert.strictEqual(r.status, 0, r.stderr);
        assert.deepStrictEqual(JSON.parse(r.stdout), { echo: 'x', from: who });
      }
      assert.deepStrictEqual(evalJson(c, '["a", "b"].map((id) => '
        + 'document.getElementById(id).contentDocument.getElementById("frame-status").textContent)'),
      ['echoed: x', 'echoed: x']);
    });

    test('webmcp e2e: a --timeout aborts the running tool through its signal (exit 124)', () => {
      const { c, httpPort } = needE2E();
      c('go', `http://127.0.0.1:${httpPort}/shop.html`);
      until(() => listJson(c), (o) => o.tools.length === 4, 'shop tools');
      const r = c('--timeout', '4', 'tools', 'call', 'wait_for_abort');
      assert.strictEqual(r.status, 124, `${r.stdout}${r.stderr}`);
      ok(r, /its execution was aborted/, 'timeout message');
      assert.strictEqual(evalJson(c, 'window.__slowAborted'), true, "the tool's signal was aborted");
    });

    test('webmcp e2e: the list follows a reload and a link navigation to another page', () => {
      const { c } = needE2E();
      c('eval', 'location.reload()');
      until(() => evalJson(c, 'window.__cart ? window.__cart.length : -1'), (n) => n === 0, 'reloaded');
      const again = until(() => listJson(c), (o) => o.tools.length === 4, 'tools after reload');
      assert(again.tools.some((t) => t.name === 'add_to_cart'));
      ok(c('click', '#next'), /Clicked/, 'click link');
      const p2 = until(() => listJson(c), (o) => o.tools.length === 1, 'page two tools');
      assert.strictEqual(p2.tools[0].name, 'lookup_order');
      assert.strictEqual(p2.tools[0].annotations.readOnlyHint, true);
      assert(/page2\.html$/.test(p2.url), p2.url);
      const r = c('tools', 'call', 'lookup_order', '{"id":"42"}');
      assert.strictEqual(r.status, 0, r.stderr);
      assert.deepStrictEqual(JSON.parse(r.stdout), { id: '42', state: 'shipped' });
      const gone = c('tools', 'call', 'add_to_cart', '{"sku":"A","qty":1}');
      assert.strictEqual(gone.status, 1);
      ok(gone, /tool 'add_to_cart' not found/, 'old page tool gone');
    });

    test('webmcp e2e: bad arguments exit 1 before the tool runs', () => {
      const { c, httpPort } = needE2E();
      c('go', `http://127.0.0.1:${httpPort}/shop.html`);
      until(() => listJson(c), (o) => o.tools.length === 4, 'shop again');
      for (const [args, re] of [[['{"sku":"B1"}'], /missing required argument: qty/],
        [['{"sku":"B1","qty":true}'], /qty: expected integer, got boolean/],
        [['{"sku":"B1","qty":"2"}'], /qty: expected integer, got string/],
        [['[1,2]'], /arguments must be a JSON object/],
        [['not json'], /invalid JSON arguments/]]) {
        const r = c('tools', 'call', 'add_to_cart', ...args);
        assert.strictEqual(r.status, 1, `${args}: ${r.stdout}${r.stderr}`);
        ok(r, re, String(args));
      }
      assert.deepStrictEqual(evalJson(c, 'window.__cart'), [], 'nothing was added');
    });

    test('webmcp e2e: a browser without WebMCP gets the diagnosis (exit 0)', () => {
      const { c, httpPort } = needE2E();
      ok(c('stop'), /stopped/i, 'stop');
      const l = c('launch', '--no-webmcp');
      assert(/CDP ready/.test(l.stdout), l.stdout + l.stderr);
      assert(!/WebMCP/.test(l.stdout), l.stdout);
      assert(!/WebMCP/.test(c('status').stdout), 'status: no WebMCP line while the mode is off');
      c('go', `http://127.0.0.1:${httpPort}/shop.html`);
      const out = listJson(c);
      assert.deepStrictEqual(out.tools, []);
      assert.strictEqual(out.reason, 'flag-off');
      assert(/launch --webmcp/.test(out.hint), out.hint);
      const human = c('tools', 'list');
      assert.strictEqual(human.status, 0);
      ok(human, /No WebMCP tools on .*shop\.html\.\n\s+document\.modelContext is missing/, 'human diagnosis');
      const call = c('tools', 'call', 'add_to_cart', '{"sku":"A","qty":1}');
      assert.strictEqual(call.status, 1);
      ok(call, /cannot call 'add_to_cart'/, 'call diagnosis');
    });
  } finally {
    if (e2e) {
      try { e2e.stop(); } catch (err) { /* best effort */ }
    }
  }
})();

// ── Web Bot Auth (signed agent) ──
// Signing code, the draft's vectors and the signer helper's CDP loop run in
// test/bot_auth_fake_cdp.py (the real cdpilot.py, a fake browser socket);
// the CLI paths run through bin/cdpilot.js; the real browser path is the
// opt-in e2e test (CDPILOT_E2E=1) with test/fixtures/bot_auth_server.py, an
// origin that verifies every request it gets. `cryptography` is optional:
// without it the bot-auth commands must print the install hint and exit 2.
(function() {
  const os = require('os');
  const { spawnSync, spawn, execFileSync } = require('child_process');
  const PYB = process.env.CDPILOT_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  // HAS_CRYPTO is probed with PYB, so the CLI tests that need cryptography pin
  // CDPILOT_PYTHON to PYB: bin/cdpilot.js otherwise may pick another interpreter
  // (python3.13 before python3) that lacks it.
  const HAS_CRYPTO = spawnSync(PYB, ['-c', 'import cryptography.hazmat.primitives.asymmetric.ed25519'],
    { encoding: 'utf-8', timeout: 20000 }).status === 0;
  const HINT = /needs the optional 'cryptography' package[\s\S]*pip install cryptography/;

  test('bot auth signature base generation matches RFC 9421 test vector', () => {
    const script = `
import sys
sys.path.insert(0, "./src")
from cdpilot import _bot_auth_signature_base
params_str = '("@authority");created=1735689600;keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=1735693200;nonce="mYotfW3CUjI68sbGw6oKd7kyXqPjZEtU8xFPGWFrqOAf5qC6MDe3pys3SWWCudB0MvwslHy32WXUpkR7u0lt/w==";tag="web-bot-auth"'
expected_sig_base = b'"@authority": example.com' + bytes([10]) + b'"@signature-params": ' + params_str.encode()
sig_base = _bot_auth_signature_base("GET", "example.com", "/path/to/resource", None, params_str)
if sig_base != expected_sig_base:
    sys.exit(1)
print("ok")
`;
    const r = spawnSync(PYB, ['-c', script], { encoding: 'utf-8', timeout: 20000,
      cwd: path.join(__dirname, '..'), env: { ...process.env, CDPILOT_LOG: '0' } });
    assert.strictEqual(r.status, 0, r.stdout + r.stderr);
    assert.strictEqual(r.stdout.trim(), 'ok');
  });

  let fakeResults = null;
  function fake(name) {
    if (!fakeResults) {
      const env = { ...process.env, CDP_PORT: '19226', CDPILOT_LOG: '0' };
      for (const k of ['CDPILOT_MODE', 'CDPILOT_BOT_AUTH', 'CDPILOT_TIMEOUT']) delete env[k];
      const out = execFileSync(PYB, [path.join(__dirname, 'bot_auth_fake_cdp.py'), PY_PATH], {
        encoding: 'utf-8', timeout: 60000, env,
      });
      fakeResults = JSON.parse(out.trim().split('\n').pop());
    }
    const r = fakeResults[name];
    assert(r, `bot-auth scenario ${name} missing`);
    assert(!r.error, `bot-auth scenario ${name} crashed:\n${r.error}`);
    return r;
  }
  const skipNote = (what) => console.log(`  - skipped: ${what} (cryptography not installed)`);

  test('bot-auth: signature bases of draft-05 A.2 (legacy A.2.3 too), Cloudflare v2 and directory vectors', () => {
    const v = fake('vectors');
    for (const k of ['sig1_base', 'sig2_base', 'draft_a22_base', 'draft_a23_legacy_base', 'directory_base',
      'directory_content_digest']) assert.strictEqual(v[k], true, k);
  });

  if (HAS_CRYPTO) {
    test('bot-auth: Ed25519 vectors reproduce byte for byte (Signature, Signature-Input, Signature-Agent)', () => {
      const v = fake('vectors');
      for (const k of ['sig1_headers', 'sig2_headers', 'draft_a21_signature', 'draft_a23_legacy_signature']) {
        assert.strictEqual(v[k], true, `${k}: ${JSON.stringify(v)}`);
      }
    });
    test('bot-auth: the DEFAULT wire format is legacy — draft-05 A.2.3 headers byte for byte', () => {
      // Signature-Agent: "https://…" covered as bare "signature-agent": the form
      // Cloudflare's verifier accepts (it rejects the dictionary form).
      assert.strictEqual(fake('vectors').draft_a23_legacy_headers, true);
    });
    test('bot-auth: signed directory response reproduces the reference vector (directory_response_v1)', () => {
      assert.strictEqual(fake('vectors').directory_vector, true);
    });
  } else {
    skipNote('bot-auth vector signatures');
  }

  test('bot-auth: RFC 7638 JWK thumbprint (RFC 8037 A.3, vector key) and RFC 9421 @authority', () => {
    const t = fake('thumbprint');
    assert.strictEqual(t.rfc8037_a3, true, 'RFC 8037 A.3 thumbprint');
    assert.strictEqual(t.vector_key, true, 'vector key thumbprint');
    assert.deepStrictEqual(t.authority, ['example.com', 'example.com', 'example.com',
      '127.0.0.1:8080', 'example.com:8443', '[::1]:9000']);
  });

  test('bot-auth helper: flat auto-attach; Fetch (Request stage) before the paused target runs', () => {
    const h = fake('helper');
    const aa = { autoAttach: true, waitForDebuggerOnStart: true, flatten: true };
    assert.deepStrictEqual(h.first, ['Target.setAutoAttach', aa, null]);
    assert.deepStrictEqual(h.ready, [null], 'ready once the browser accepted auto-attach');
    assert.deepStrictEqual(h.attach, [
      ['Fetch.enable', 'S1', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] }],
      ['Target.setAutoAttach', 'S1', aa],
      ['Runtime.runIfWaitingForDebugger', 'S1', {}],
    ], 'a page gets Fetch + nested auto-attach, then runs; an "other" target gets nothing');
  });

  test('bot-auth helper: requestPaused -> continueRequest carries Signature, Signature-Input, Signature-Agent', () => {
    const h = fake('helper');
    assert.strictEqual(h.r1_session, 'S1', 'continued on the session that paused it');
    assert.deepStrictEqual(h.r1_headers, ['Accept', 'X-Keep', 'Signature-Agent', 'Signature-Input', 'Signature'],
      'page headers kept, a stale signature replaced, the three added');
    assert.strictEqual(h.r1_values.Signature, 'sig1=:AAAA:');
  });

  test('bot-auth helper: data:/blob:/chrome-extension: and a signing error continue unsigned; one log line', () => {
    const h = fake('helper');
    for (const rid of ['R2', 'R3', 'R4', 'R5']) {
      assert.deepStrictEqual(h.unsigned[rid] && h.unsigned[rid][1], ['requestId'], `${rid} continued without headers`);
    }
    assert.strictEqual(h.unsigned.R5[0], 'S2');
    assert.deepStrictEqual(h.signed_urls, ['https://example.com/p?q=1', 'https://example.com/boom?token=SECRET123'],
      'only http(s) reaches the signer');
    assert.strictEqual(h.logs.length, 1, 'one line per failure');
    assert(!/SECRET123|boom|token/.test(h.logs[0]), `the log line carries no path or query: ${h.logs[0]}`);
    assert.strictEqual(h.finished, true, 'the helper returns when the browser socket closes');
  });

  if (HAS_CRYPTO) {
    test('bot-auth helper: real signatures verify with the directory key; tampering fails; sign < 1 ms', () => {
      const r = fake('helper_real_signature');
      assert.deepStrictEqual(r.verified, [[true, 'sig1'], [true, 'sig1'], [true, 'sig1'], [true, 'sig1']]);
      assert.deepStrictEqual(r.agents, Array(4).fill('"https://agent.example"'), 'legacy Signature-Agent');
      assert.deepStrictEqual(r.dict, Array(4).fill([true, false]),
        'dict format verifies with a dict verifier, and the legacy verifier rejects it');
      assert.strictEqual(r.tampered[0], false, 'another Host must not verify');
      assert(r.median_ms < 1, `median sign time ${r.median_ms} ms`);
    });
    test('bot-auth directory --headers: ("@authority";req), tag, one signature per key; verifies independently', () => {
      const d = fake('directory');
      assert(/^sig1=\("@authority";req\);created=\d+;keyid="[\w-]{43}";alg="ed25519";expires=\d+;nonce="[^"]{88}";tag="http-message-signatures-directory"$/
        .test(d.input), d.input);
      assert.deepStrictEqual(d.ok, [true, '1 key(s)']);
      assert.deepStrictEqual(d.ok_digest, [true, '1 key(s)']);
      assert.deepStrictEqual(d.two_keys, [true, '2 key(s)']);
      for (const k of ['other_host', 'expired', 'edited_body', 'two_keys_one_signed']) {
        assert.strictEqual(d[k], false, `${k} must not verify`);
      }
    });
  } else {
    skipNote('bot-auth real-signature helper test');
  }

  test('bot-auth: navigate sends no stealth script or UA override while the signer runs', () => {
    const r = fake('navigate_skips_stealth');
    assert.deepStrictEqual(r.off, { stealth_script: true, ua_override: true, navigated: true },
      'stealth mode without bot-auth injects as before');
    assert.deepStrictEqual(r.on, { stealth_script: false, ua_override: false, navigated: true });
  });

  test('bot-auth: stealth conflict is one warning line; the session log masks signatures', () => {
    const r = fake('conflict_and_log');
    assert.deepStrictEqual(r.flag, [true, 1, true], '--stealth with --bot-auth');
    assert.deepStrictEqual(r.mode, [true, 1, true], 'undetected mode with --bot-auth');
    assert.deepStrictEqual(r.none, [false, 0, false], 'regular mode: no warning');
    assert.deepStrictEqual(r.slog, { signature_masked: true, input_masked: true, status_kept: true,
      prose_kept: true, dump_masked: true }, 'only real header lines / header dumps are masked');
  });

  test('bot-auth: signer state is trusted only for this port\'s signer and browser; stale = dropped + warning', () => {
    const r = fake('state');
    assert.strictEqual(r.off, 'bot-auth: off');
    assert.strictEqual(r.on, 'bot-auth: on (keyid KID123)', 'command line --_bot-auth-signer <port> <token> + same browser');
    assert.strictEqual(r.active, true);
    assert.strictEqual(r.kept_while_on, true);
    assert.deepStrictEqual(r.unreachable, [true, 'bot-auth: on (keyid KID123)', false, '', true, false],
      '/json/version timing out: still active (no stealth/escalation), no warning, state kept');
    for (const k of ['other_token', 'browser_restarted', 'reused_pid']) {
      assert.deepStrictEqual(r[k], ['bot-auth: off', null, true], `${k}: off, state file dropped, stale marker left`);
    }
    const w = 'bot-auth: signer not running, requests go out unsigned — run `cdpilot launch --bot-auth` again\n';
    assert.deepStrictEqual(r.warning, [true, true, w + w], 'one line per command, until launch or stop');
    assert.strictEqual(r.dead_pid, 'bot-auth: off');
  });

  test('bot-auth: stop never signals a reused pid (live sleep survives), ends a real signer, clears state', () => {
    const r = fake('state');
    assert.strictEqual(r.stop_reused, true);
    assert.strictEqual(r.sleeper_alive_after_stop, true, 'stop killed an unrelated process');
    assert.strictEqual(r.marker_after_stop, false, 'stop clears the stale marker');
    assert.strictEqual(r.real_signer_stopped, true);
    assert.strictEqual(r.state_after_stop, null);
  });

  test('bot-auth: spawn lock — holder SIGKILLed, three concurrent launches -> exactly one signer', () => {
    const r = fake('lock');
    assert.strictEqual(r.held, 'held');
    assert.strictEqual(r.lock_left, true, 'the dead holder left its lock file behind');
    assert.deepStrictEqual(r.errors, []);
    assert.strictEqual(r.spawned, 1, `signers spawned: ${r.spawned}`);
    assert.strictEqual(r.all_same, true, 'all three launches report the one signer');
  });

  test('bot-auth: health has no bot_auth key while bot-auth is unused (same keys as before), one once set up', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-botauth-health-'));
    const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: '19229', CDPILOT_LOG: '0', CDPILOT_NO_AUTOLAUNCH: '1' };
    for (const k of ['CDPILOT_WEBMCP', 'CDPILOT_BOT_AUTH', 'CDPILOT_TIMEOUT']) delete env[k];
    const health = () => {
      const r = spawnSync(PYB, [PY_PATH, 'health'], { encoding: 'utf-8', timeout: 30000, env });
      return JSON.parse(r.stdout.trim().split('\n').pop());
    };
    assert.deepStrictEqual(Object.keys(health()), ['alive', 'port', 'project_id', 'tabs', 'browser',
      'crashes_today', 'stealth', 'uptime_warning', 'idle_close', 'idle_close_in_s'], 'health keys unchanged');
    fs.mkdirSync(path.join(home, 'bot-auth'), { recursive: true });
    fs.writeFileSync(path.join(home, 'bot-auth', 'config.json'), '{"agent_url": "https://agent.test"}');
    assert.strictEqual(health().bot_auth, 'bot-auth: off', 'configured: bot_auth key present');
  });

  test('bot-auth: idle close counts CDP clients other than the signer (socket owners per OS)', () => {
    const r = fake('clients');
    for (const k of ['lsof', 'netstat', 'bsd_netstat', 'ss']) assert.deepStrictEqual(r[k], [101, 303], k);
    assert.strictEqual(typeof r.live, 'object', `live check: ${JSON.stringify(r.live)}`);
    if (r.live.tool) {
      assert.strictEqual(r.live.child_seen, true, 'a connected client is seen');
      assert.strictEqual(r.live.server_side_not_counted, true);
      assert.strictEqual(r.live.other_than_child, false, 'the signer alone is not a client');
      assert.strictEqual(r.live.other_than_signer, true, 'another client keeps the browser open');
    } else {
      console.log('  - note: no socket-owner tool on this machine; idle close ignores clients while signing');
    }
  });

  test('bot-auth: status prints a bot-auth line only when bot-auth is set up (default output unchanged)', () => {
    // A stand-in CDP endpoint (a node child serving /json/version) on a free
    // port in 58680-58699: the child tries them in turn and prints the one it got.
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-botauth-status-'));
    const ws = 'ws://127.0.0.1/devtools/browser/status-test';
    const version = JSON.stringify({ Browser: 'Chrome/150.0.0.0', 'Protocol-Version': '1.3',
      webSocketDebuggerUrl: ws });
    const portFile = path.join(root, 'port');
    const srv = spawn(process.execPath, ['-e', `
      const http = require('http'), fs = require('fs');
      const body = ${JSON.stringify(version)};
      const tryPort = (p) => {
        if (p > 58699) process.exit(3);
        const s = http.createServer((req, res) => {
          res.writeHead(req.url === '/json/version' ? 200 : 404, { 'Content-Type': 'application/json' });
          res.end(req.url === '/json/version' ? body : '');
        });
        s.once('error', () => tryPort(p + 1));
        s.listen(p, '127.0.0.1', () => fs.writeFileSync(${JSON.stringify(portFile)}, String(p)));
      };
      tryPort(58680);
      setTimeout(() => process.exit(0), 120000);`], { stdio: 'ignore' });
    let port = null;
    const probe = spawnSync(process.execPath, ['-e', `
      const fs = require('fs'), http = require('http');
      const end = Date.now() + 30000;
      const again = () => (Date.now() > end ? process.exit(3) : setTimeout(tick, 100));
      const tick = () => {
        let p;
        try { p = fs.readFileSync(${JSON.stringify(portFile)}, 'utf8'); } catch (e) { return again(); }
        http.get({ host: '127.0.0.1', port: Number(p), path: '/json/version', timeout: 3000 }, (res) => {
          res.resume(); res.on('end', () => { process.stdout.write(p); process.exit(0); });
        }).on('error', again).on('timeout', function () { this.destroy(); });
      };
      tick();`], { encoding: 'utf-8', timeout: 60000 });
    if (probe.status === 0) port = Number(probe.stdout.trim());
    const home = path.join(root, 'home');
    const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(root, 'profile'),
      CDP_PORT: String(port), CDPILOT_LOG: '0' };
    for (const k of ['CDPILOT_WEBMCP', 'CDPILOT_BOT_AUTH', 'CDPILOT_TIMEOUT']) delete env[k];
    const status = () => spawnSync(process.execPath, [CLI, 'status'], { encoding: 'utf-8', timeout: 30000, env });
    try {
      assert(port, `stand-in /json/version never answered (exit ${probe.status}): ${probe.stderr}`);
      const plain = `\n  cdpilot status (port ${port})\n\n  ✓ Connected\n  Browser: Chrome/150.0.0.0\n`
        + `  Protocol: 1.3\n  WebSocket: ${ws}\n  idle close off\n\n`;
      assert.strictEqual(status().stdout, plain, 'no bot-auth set up: status output unchanged');
      fs.mkdirSync(path.join(home, 'bot-auth', 'signers'), { recursive: true });
      fs.writeFileSync(path.join(home, 'bot-auth', 'config.json'), '{"agent_url": "https://agent.test"}');
      assert.strictEqual(status().stdout, plain.replace('idle close off\n', 'idle close off\n  bot-auth: off\n'),
        'configured, no signer: bot-auth: off');
      // A signer that died without cleaning up: off, and the one-line warning.
      fs.writeFileSync(path.join(home, 'bot-auth', 'signers', `${port}.json`), JSON.stringify({
        token: 'dead', pid: 2 ** 22 + 12345, ready: true, port, keyid: 'K', browser_ws: ws }));
      let r = status();
      assert(r.stdout.includes('  idle close off\n  bot-auth: off\n\n'), r.stdout);
      assert.strictEqual(r.stderr.replace(/\r\n/g, '\n'), 'bot-auth: signer not running, requests go '
        + 'out unsigned — run `cdpilot launch --bot-auth` again\n');
      assert(!fs.existsSync(path.join(home, 'bot-auth', 'signers', `${port}.json`)), 'stale state dropped');
      r = status();
      assert(/requests go out unsigned/.test(r.stderr), 'still warns until launch --bot-auth or stop');
    } finally {
      try { srv.kill(); } catch (err) { /* already gone */ }
    }
  });

  // A `cryptography` that fails to import, whatever the interpreter has.
  function noCryptoEnv(home) {
    const shim = path.join(home, 'no-crypto');
    fs.mkdirSync(path.join(shim, 'cryptography'), { recursive: true });
    fs.writeFileSync(path.join(shim, 'cryptography', '__init__.py'),
      'raise ImportError("cryptography blocked by the cdpilot test")\n');
    const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: '19227', CDPILOT_LOG: '0', PYTHONPATH: shim,
      CHROME_BIN: path.join(home, 'no-such-browser', 'chrome'), CDPILOT_NO_AUTOLAUNCH: '1' };
    for (const k of ['CDPILOT_MODE', 'CDPILOT_BOT_AUTH', 'CDPILOT_TIMEOUT']) delete env[k];
    return env;
  }

  test('bot-auth without cryptography: init/status/directory/launch --bot-auth -> install hint, exit 2', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-botauth-nocrypto-'));
    const env = noCryptoEnv(home);
    // launch goes straight to Python: the node launcher's first-run preflight
    // is about the browser and websockets, not this check.
    for (const args of [['bot-auth', 'init', '--agent-url', 'https://agent.test'], ['bot-auth', 'status'],
      ['bot-auth', 'directory'], ['launch', '--bot-auth']]) {
      const r = args[0] === 'launch'
        ? spawnSync(PYB, [PY_PATH, ...args], { env, encoding: 'utf-8', timeout: 30000 })
        : spawnSync(process.execPath, [CLI, ...args], { env, encoding: 'utf-8', timeout: 30000 });
      assert.strictEqual(r.status, 2, `${args.join(' ')}: exit ${r.status}\n${r.stdout}${r.stderr}`);
      assert(HINT.test(r.stderr), `${args.join(' ')}: install hint missing:\n${r.stderr}`);
      assert(!/Launching browser/.test(r.stdout), `${args.join(' ')} must not start a browser`);
    }
    assert(!fs.existsSync(path.join(home, 'bot-auth', 'ed25519.key')), 'no key written');
  });

  test('bot-auth without cryptography: other commands are unaffected', () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-botauth-nocrypto-'));
    const env = noCryptoEnv(home);
    const c = (...args) => spawnSync(process.execPath, [CLI, ...args], { env, encoding: 'utf-8', timeout: 30000 });
    let r = c('version');
    assert(r.status === 0 && r.stdout.includes(require('../package.json').version), `version: ${r.stdout}${r.stderr}`);
    r = c('mode');
    assert(r.status === 0 && /Mode: regular/.test(r.stdout), `mode: ${r.stdout}${r.stderr}`);
    r = c('bot-auth', '--help');
    assert(r.status === 0 && /bot-auth <init\|status\|directory\|format>/.test(r.stdout), `bot-auth --help: ${r.stdout}${r.stderr}`);
    r = c('status');
    assert(r.status === 0, `status: ${r.stdout}${r.stderr}`);
    assert(!HINT.test(r.stderr + r.stdout), 'no hint outside bot-auth');
  });

  if (HAS_CRYPTO) {
    test('bot-auth init/directory/status: 0600 key, kid = RFC 7638 of x, key never printed, safe re-init', () => {
      const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-botauth-cli-'));
      const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
        CDP_PORT: '19228', CDPILOT_LOG: '0', CDPILOT_PYTHON: PYB };
      const c = (...args) => spawnSync(process.execPath, [CLI, ...args], { env, encoding: 'utf-8', timeout: 30000 });
      for (const bad of ['http://agent.test', 'https://agent.test/bots', 'https://agent.test?a=1', 'agent.test']) {
        const r = c('bot-auth', 'init', '--agent-url', bad);
        assert.strictEqual(r.status, 1, `${bad} must be rejected: ${r.stdout}${r.stderr}`);
      }
      const init = c('bot-auth', 'init', '--agent-url', 'https://agent.test/');
      assert.strictEqual(init.status, 0, init.stderr);
      const keyFile = path.join(home, 'bot-auth', 'ed25519.key');
      const pem = fs.readFileSync(keyFile, 'utf-8');
      if (process.platform !== 'win32') {
        assert.strictEqual(fs.statSync(keyFile).mode & 0o777, 0o600, 'key file 0600');
      }
      const dir = c('bot-auth', 'directory');
      assert.strictEqual(dir.status, 0, dir.stderr);
      const jwks = JSON.parse(dir.stdout);
      assert.strictEqual(jwks.keys.length, 1);
      const k = jwks.keys[0];
      assert.deepStrictEqual([k.kty, k.crv, k.use], ['OKP', 'Ed25519', 'sig']);
      assert(!('d' in k), 'the directory holds no private part');
      const thumb = require('crypto').createHash('sha256')
        .update(`{"crv":"Ed25519","kty":"OKP","x":"${k.x}"}`).digest('base64url');
      assert.strictEqual(k.kid, thumb, 'kid is the RFC 7638 thumbprint');
      const status = c('bot-auth', 'status');
      assert(status.stdout.includes(`keyid     : ${thumb}`) && /agent URL : https:\/\/agent\.test$/m.test(status.stdout),
        status.stdout);
      assert(/bot-auth: off/.test(status.stdout), 'no signer running');
      assert(/format    : Signature-Agent legacy$/m.test(status.stdout), `legacy is the default: ${status.stdout}`);
      // The signed directory response: headers + the exact body, verified by the fixture.
      const dh = c('bot-auth', 'directory', '--headers', '--json');
      assert.strictEqual(dh.status, 0, dh.stderr);
      const signed = JSON.parse(dh.stdout);
      assert.strictEqual(signed.authority, 'agent.test', 'authority defaults to the agent URL host');
      assert.strictEqual(signed.headers['Content-Type'], 'application/http-message-signatures-directory+json');
      assert.deepStrictEqual(JSON.parse(signed.body), jwks, 'same JWKS as `bot-auth directory`');
      const verifyDir = (headers, host, body) => JSON.parse(execFileSync(PYB, ['-c', [
        'import json, sys', `sys.path.insert(0, ${JSON.stringify(path.join(__dirname, 'fixtures'))})`,
        'import bot_auth_server as s', 'a = json.loads(sys.stdin.read())',
        'print(json.dumps(s.verify_directory(a[0], a[1], a[2])))'].join('\n')],
      { input: JSON.stringify([headers, host, body]), encoding: 'utf-8', timeout: 20000 }));
      assert.deepStrictEqual(verifyDir(signed.headers, 'agent.test', signed.body), [true, '1 key(s)']);
      assert.strictEqual(verifyDir(signed.headers, 'other.test', signed.body)[0], false);
      const plain = c('bot-auth', 'directory', '--headers', '--authority', 'bots.agent.test', '--ttl', '60');
      assert.strictEqual(plain.status, 0, plain.stderr);
      const [head, ...rest] = plain.stdout.split('\n\n');
      assert(/^Content-Type: application\/http-message-signatures-directory\+json$/m.test(head), head);
      assert(/^Signature-Input: sig1=\("@authority";req\);created=(\d+);.*expires=(\d+);.*tag="http-message-signatures-directory"$/m
        .test(head), head);
      assert(/^Signature: sig1=:[A-Za-z0-9+/]{86}==:$/m.test(head), head);
      const hdrs = Object.fromEntries(head.split('\n').map((l) => [l.slice(0, l.indexOf(':')), l.slice(l.indexOf(':') + 2)]));
      assert.deepStrictEqual(verifyDir(hdrs, 'bots.agent.test', rest.join('\n\n')), [true, '1 key(s)']);
      const [, created, expires] = head.match(/created=(\d+);.*expires=(\d+)/);
      assert.strictEqual(Number(expires) - Number(created), 60, '--ttl');
      // Opt-in dictionary format, and back.
      let f = c('bot-auth', 'format', 'dict');
      assert(f.status === 0 && /format: dict/.test(f.stdout), f.stdout + f.stderr);
      assert(/format    : Signature-Agent dict$/m.test(c('bot-auth', 'status').stdout), 'format dict persisted');
      f = c('bot-auth', 'format', 'bogus');
      assert.strictEqual(f.status, 2, 'unknown format rejected');
      f = c('bot-auth', 'format', 'legacy');
      assert(f.status === 0 && /Signature-Agent format: legacy/.test(c('bot-auth', 'format').stdout));
      const body = pem.split('\n').filter((l) => l && !l.startsWith('-----')).join('');
      for (const r of [init, dir, status, dh, plain]) {
        assert(!/PRIVATE KEY/.test(r.stdout + r.stderr) && !(r.stdout + r.stderr).includes(body.slice(0, 24)),
          'the private key is never printed');
      }
      const again = c('bot-auth', 'init', '--agent-url', 'https://agent.test');
      assert.strictEqual(again.status, 1, 're-init without --force must refuse');
      assert.strictEqual(fs.readFileSync(keyFile, 'utf-8'), pem, 'key unchanged');
      if (process.platform !== 'win32') {
        fs.chmodSync(keyFile, 0o644);
        const warn = c('bot-auth', 'status');
        assert(/private key is 0o644, should be 0600/.test(warn.stderr), `perm warning: ${warn.stderr}`);
      }
    });
  } else {
    skipNote('bot-auth init/directory/status CLI test');
  }

  test('bot-auth docs: README section, bin help, __doc__, CHANGELOG [Unreleased]', () => {
    const root = path.join(__dirname, '..');
    const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
    const sec = readme.split(/^### Web Bot Auth \(signed agent\)$/m)[1];
    assert(sec, 'README needs a "### Web Bot Auth (signed agent)" section');
    for (const s of ['bot-auth init --agent-url', 'bot-auth directory', 'launch --bot-auth',
      '/.well-known/http-message-signatures-directory', 'application/http-message-signatures-directory+json',
      'pip install cryptography', 'stealth', 'Signature-Agent', '"signature-agent";key="sig1"',
      'bot-auth directory --headers', '("@authority" "signature-agent")', 'bot-auth format dict',
      'WebSocket', 'requests go out unsigned']) {
      assert(sec.includes(s), `README section must mention ${s}`);
    }
    const help = run('--help');
    assert(help.includes('launch --bot-auth') && help.includes('bot-auth directory --headers')
      && help.includes('bot-auth format'), 'bin help documents bot-auth');
    assert(PY_CONTENT.slice(0, 3000).includes('launch --bot-auth'), 'python __doc__ documents bot-auth');
    const changelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8');
    const secs = changelog.split(/^## \[/m);
    assert((secs[1] || '').startsWith('Unreleased]') && secs[1].includes('launch --bot-auth'),
      'CHANGELOG [Unreleased] describes Web Bot Auth');
    for (const s of ['`bot-auth:` line', '`bot_auth` key', 'directory --headers', 'legacy']) {
      assert(secs[1].includes(s), `CHANGELOG [Unreleased] must mention ${s}`);
    }
  });

  // ── Real browser (CDPILOT_E2E=1): every request the browser makes is signed ──
  if (process.env.CDPILOT_E2E !== '1') {
    console.log('  - skipped: bot-auth e2e (set CDPILOT_E2E=1 to run it against a headless browser)');
    return;
  }
  let e2e = null;
  test('bot-auth e2e: launch --bot-auth starts the signer; status shows bot-auth: on (keyid …)', () => {
    assert(HAS_CRYPTO, `the bot-auth e2e needs cryptography in ${PYB} (pip install cryptography)`);
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-botauth-e2e-'));
    // Two free ports in 58600-58699 (never the default CDP port).
    const [cdpPort, port] = JSON.parse(execFileSync(PYB, ['-c', [
      'import json, socket', 'got = []',
      'for p in range(58600, 58700):',
      '    s = socket.socket()',
      '    try: s.bind(("127.0.0.1", p)); got.append(p)',
      '    except OSError: pass',
      '    finally: s.close()',
      '    if len(got) == 2: break',
      'print(json.dumps(got))',
    ].join('\n')], { encoding: 'utf-8', timeout: 10000 }).trim());
    const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
      CDP_PORT: String(cdpPort), CHROME_HEADLESS: '1', CDPILOT_LOG: '0', CDPILOT_PYTHON: PYB };
    for (const k of ['CDPILOT_TARGET', 'CDPILOT_MODE', 'CDPILOT_BOT_AUTH', 'CDPILOT_TIMEOUT']) delete env[k];
    const c = (...args) => spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf-8', timeout: 60000, env });
    let r = c('bot-auth', 'init', '--agent-url', 'https://agent.test');
    assert.strictEqual(r.status, 0, r.stderr);
    r = c('bot-auth', 'directory');
    assert.strictEqual(r.status, 0, r.stderr);
    const jwksFile = path.join(home, 'jwks.json');
    fs.writeFileSync(jwksFile, r.stdout);
    const keyid = JSON.parse(r.stdout).keys[0].kid;
    const logFile = path.join(home, 'origin.jsonl');
    const srv = spawn(PYB, [path.join(__dirname, 'fixtures', 'bot_auth_server.py'), '--port', String(port),
      '--jwks-file', jwksFile, '--log-file', logFile], { stdio: 'ignore' });
    // A stale signer state whose pid now belongs to an unrelated live process
    // (a reused pid): launch must not trust it, and stop must not kill it.
    const sleeper = spawn(process.platform === 'win32' ? PYB : 'sleep',
      process.platform === 'win32' ? ['-c', 'import time; time.sleep(120)'] : ['120'], { stdio: 'ignore' });
    fs.mkdirSync(path.join(home, 'bot-auth', 'signers'), { recursive: true });
    fs.writeFileSync(path.join(home, 'bot-auth', 'signers', `${cdpPort}.json`), JSON.stringify({
      token: 'stale', pid: sleeper.pid, ready: true, port: cdpPort, keyid: 'OLDKEY',
      browser_ws: `ws://127.0.0.1:${cdpPort}/devtools/browser/gone`, started: Date.now() / 1000 - 3600 }));
    const stop = () => {
      c('stop');
      try { srv.kill(); } catch (err) { /* already gone */ }
      try { sleeper.kill(); } catch (err) { /* already gone */ }
    };
    try {
      execFileSync(PYB, ['-c', [
        'import time, urllib.request',
        'for _ in range(100):',
        `    try: urllib.request.urlopen("http://127.0.0.1:${port}/ping", timeout=1); break`,
        '    except Exception: time.sleep(0.1)',
      ].join('\n')], { timeout: 20000 });
      r = c('launch', '--bot-auth');
      assert(r.status === 0 && /Bot Auth: signing every request as https:\/\/agent\.test/.test(r.stdout),
        `launch: ${r.status}\n${r.stdout}${r.stderr}`);
      assert(/Signature-Agent legacy/.test(r.stdout), `legacy is the default wire format: ${r.stdout}`);
      const state = JSON.parse(fs.readFileSync(path.join(home, 'bot-auth', 'signers', `${cdpPort}.json`), 'utf-8'));
      assert(state.pid && state.ready, 'signer state names a ready pid');
      assert(state.pid !== sleeper.pid && state.token !== 'stale' && state.keyid === keyid,
        `launch trusted a stale state with a reused pid: ${JSON.stringify(state)}`);
      const st = c('status');
      assert(st.stdout.includes(`bot-auth: on (keyid ${keyid})`), `status: ${st.stdout}`);
      assert(!/requests go out unsigned/.test(st.stderr), `no stale warning while signing: ${st.stderr}`);
    } catch (err) {
      stop();
      throw err;
    }
    const readLog = () => fs.readFileSync(logFile, 'utf-8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
      .filter((e) => e.path !== '/ping');
    e2e = { c, port, keyid, stop, readLog, home, cdpPort, sleeper };
  });
  const need = () => { assert(e2e, 'bot-auth e2e setup failed'); return e2e; };
  const waitFor = (fn, ms) => {
    const end = Date.now() + ms;
    for (;;) {
      const v = fn();
      if (v || Date.now() > end) return v;
      spawnSync(PYB, ['-c', 'import time; time.sleep(0.2)']);
    }
  };
  // The legacy wire format, verified by the fixture in its default (legacy) mode.
  const signedBy = (e, keyid) => e.verified === true
    && e.signature_agent === '"https://agent.test"'
    && e.signature_input.startsWith('sig1=("@authority" "signature-agent");')
    && e.signature_input.includes(`keyid="${keyid}"`) && e.signature_input.includes('tag="web-bot-auth"');
  try {
    let goDone = 0;
    test('bot-auth e2e (a): go — the document, a subresource and both redirect hops are signed', () => {
      const { c, port, keyid, readLog } = need();
      const r = c('go', `http://127.0.0.1:${port}/start?late=4000&popup=5000&worker=1`);
      goDone = Date.now() / 1000;
      assert.strictEqual(r.status, 0, `go: ${r.stdout}${r.stderr}`);
      const log = waitFor(() => { const l = readLog(); return ['/sub.json', '/after-redirect']
        .every((p) => l.some((e) => e.path === p)) && l; }, 10000);
      assert(log, `origin missed /sub.json or /after-redirect: ${JSON.stringify(readLog().map((e) => e.path))}`);
      for (const p of ['/start?late=4000&popup=5000&worker=1', '/sub.json', '/redirect', '/after-redirect']) {
        const e = log.find((x) => x.path === p);
        assert(e && signedBy(e, keyid), `${p}: ${JSON.stringify(e)}`);
      }
    });
    test('bot-auth e2e (b): a fetch() the page makes after the cdpilot command exited is signed', () => {
      const { keyid, readLog } = need();
      const log = waitFor(() => { const l = readLog(); return l.some((e) => e.path === '/late?x=1') && l; }, 15000);
      assert(log, 'origin saw no /late request');
      const e = log.find((x) => x.path === '/late?x=1');
      assert(goDone && e.t > goDone, `the late fetch (t=${e.t}) must come after go exited (t=${goDone})`);
      assert(signedBy(e, keyid), JSON.stringify(e));
    });
    test('bot-auth e2e (c): a new tab opened by the page is signed (document and image)', () => {
      const { keyid, readLog } = need();
      const log = waitFor(() => { const l = readLog(); return l.some((e) => e.path === '/popup.png') && l; }, 15000);
      assert(log, 'origin saw no popup requests');
      for (const p of ['/popup', '/popup.png']) {
        const e = log.find((x) => x.path === p);
        assert(e && signedBy(e, keyid), `${p}: ${JSON.stringify(e)}`);
      }
    });
    test('bot-auth e2e (d): a dedicated Worker the page starts is signed (script and its fetch)', () => {
      const { keyid, readLog } = need();
      const log = waitFor(() => { const l = readLog(); return l.some((e) => e.path === '/from-worker') && l; }, 10000);
      assert(log, 'origin saw no request from the worker');
      for (const p of ['/worker.js', '/from-worker']) {
        const e = log.find((x) => x.path === p);
        assert(e && signedBy(e, keyid), `${p}: ${JSON.stringify(e)}`);
      }
    });
    test('bot-auth e2e: every request the origin received verifies with the directory key', () => {
      const { keyid, readLog } = need();
      const log = readLog();
      assert(log.length >= 5, `requests seen: ${log.length}`);
      const bad = log.filter((e) => !signedBy(e, keyid));
      assert.deepStrictEqual(bad, [], 'unsigned or unverified requests');
    });
    test('bot-auth e2e: stop ends the signer process and status says off', () => {
      const { c, home, cdpPort, sleeper } = need();
      const state = JSON.parse(fs.readFileSync(path.join(home, 'bot-auth', 'signers', `${cdpPort}.json`), 'utf-8'));
      const r = c('stop');
      assert.strictEqual(r.status, 0, r.stderr);
      const alive = (pid) => { try { process.kill(pid, 0); return true; } catch (err) { return err.code === 'EPERM'; } };
      assert(waitFor(() => !alive(state.pid), 5000), `signer pid ${state.pid} still alive after stop`);
      assert(!fs.existsSync(path.join(home, 'bot-auth', 'signers', `${cdpPort}.json`)), 'signer state cleared');
      assert(/bot-auth: off/.test(c('bot-auth', 'status').stdout), 'bot-auth status: off');
      assert(alive(sleeper.pid), 'the process that reused the stale pid must survive launch and stop');
    });
  } finally {
    if (e2e) e2e.stop();
  }
})();

// ── Summary ──

console.log(`\n  ${passed} passed, ${failed} failed\n`);
process.exit(failed > 0 ? 1 : 0);

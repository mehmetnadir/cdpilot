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
    env: { ...process.env, CDP_PORT: '19222' }, // avoid conflict with real browser
  });
}

console.log('\n  cdpilot tests\n');

// ── CLI basics ──

test('--version prints version', () => {
  const out = run('--version');
  assert(out.includes('0.8.0'), 'Should print version');
});

test('-v prints version', () => {
  const out = run('-v');
  assert(out.includes('0.8.0'), 'Should print version');
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
  assert(PY_CONTENT.includes('STEALTH_JS = r"""'), 'Should define STEALTH_JS');
});

test('STEALTH_JS is syntactically valid JavaScript', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS');
  assert(js, 'STEALTH_JS body should be extractable');
  const vm = require('vm');
  // new Script validates syntax without executing
  assert.doesNotThrow(() => new vm.Script(js), 'STEALTH_JS should parse as valid JS');
});

test('STEALTH_JS is idempotent (guards with __cdpilot_stealth flag)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS');
  assert(js.includes('__cdpilot_stealth'), 'Should guard against double-injection');
  assert(js.includes('if (window.__cdpilot_stealth) return'), 'Should early-return on repeat');
});

test('STEALTH_JS patches the documented fingerprint surfaces', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS');
  assert(js.includes("'webdriver'") || js.includes('"webdriver"'), 'Should patch navigator.webdriver');
  assert(js.includes('chrome.runtime') || js.includes("chrome.runtime"), 'Should patch chrome.runtime');
  assert(js.includes("'plugins'") || js.includes('"plugins"'), 'Should patch navigator.plugins');
  assert(js.includes('37445'), 'Should spoof WebGL UNMASKED_VENDOR (37445)');
  assert(js.includes('37446'), 'Should spoof WebGL UNMASKED_RENDERER (37446)');
  assert(js.includes('permissions.query') || js.includes('permissions'), 'Should patch permissions.query');
});

test('STEALTH_JS only patches webdriver when value is actually true (smart no-op)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS');
  assert(/wdValue\s*===\s*true/.test(js),
    'webdriver patch must be conditional on actual value being true — patching a benign Chrome creates a worse fingerprint');
});

test('STEALTH_JS plugins inherit from PluginArray.prototype (instanceof check)', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS');
  assert(js.includes('PluginArray.prototype') || js.includes('PluginArrayProto'),
    'plugins must inherit from PluginArray.prototype, not vanilla Array');
  assert(js.includes('Plugin.prototype') || js.includes('PluginProto'),
    'individual plugins must inherit from Plugin.prototype');
});

test('STEALTH_JS patches Worker constructor for worker-context webdriver', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS');
  assert(/window\.Worker/.test(js), 'Should wrap window.Worker');
  assert(/createObjectURL/.test(js), 'Should use blob URL to inject patch');
  assert(/__cdpilot_worker_patched/.test(js), 'Should guard against double-patching Worker');
  assert(/options\s*&&\s*options\.type\s*===\s*'module'/.test(js),
    'Must skip module workers (importScripts incompatible)');
});

test('STEALTH_JS does NOT weaken web security primitives', () => {
  const js = extractRawTripleString(PY_CONTENT, 'STEALTH_JS');
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

test('navigate_collect gates stealth injection behind get_stealth_config', () => {
  // STEALTH_JS must be registered on the SAME WS as Page.navigate so the
  // session-bound script survives until loadEventFired. Therefore the gate
  // lives in navigate_collect, not _control_start.
  const m = PY_CONTENT.match(/async def navigate_collect[\s\S]*?stealth_active = get_stealth_config\(\)[\s\S]*?if stealth_active:[\s\S]*?addScriptToEvaluateOnNewDocument[\s\S]*?STEALTH_JS/);
  assert(m, 'navigate_collect should read get_stealth_config() and conditionally register STEALTH_JS via addScriptToEvaluateOnNewDocument');
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

test('cmd_go: adaptive auto-enables stealth for known host before navigate', () => {
  // Invariant: when adaptive is ON and the URL's host is in the learned list,
  // cmd_go must set CDPILOT_STEALTH=1 BEFORE navigate_collect runs (otherwise
  // the stealth script wouldn't be registered in time).
  // v0.5.1: Fix 1 isolation block sits between CDPILOT_STEALTH and navigate_collect,
  // so we verify the two invariants separately.
  const hasHostCheck = /async def cmd_go[\s\S]*?_adaptive_host_requires_stealth\(url\)[\s\S]{0,600}?CDPILOT_STEALTH/.test(PY_CONTENT);
  const hasNavCollect = /async def cmd_go[\s\S]*?navigate_collect\(active_ws,\s*url\)/.test(PY_CONTENT);
  assert(hasHostCheck && hasNavCollect,
    "cmd_go must check _adaptive_host_requires_stealth and set CDPILOT_STEALTH=1 BEFORE navigate_collect");
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
  // Verify boundary values via Python (inline pure function extract)
  const { execSync } = require('child_process');
  const out = execSync(`python3 -c "
def _quartic_easeout(t): return 1.0 - (1.0 - t) ** 4
print(_quartic_easeout(0), _quartic_easeout(1))
"`, { encoding: 'utf-8', timeout: 5000 });
  const [v0, v1] = out.trim().split(' ').map(Number);
  assert(Math.abs(v0 - 0.0) < 0.001, "_quartic_easeout(0) must be 0.0");
  assert(Math.abs(v1 - 1.0) < 0.001, "_quartic_easeout(1) must be 1.0");
});

test('_bezier_path returns correct point count', () => {
  // Verify formula via inline Python (stdlib only, no cdpilot.py load needed)
  const { execSync } = require('child_process');
  const out = execSync(`python3 -c "
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
"`, { encoding: 'utf-8', timeout: 5000 });
  assert.strictEqual(parseInt(out.trim()), 10, "_bezier_path must return exactly N points");
});

test('_gauss stays within [lo, hi] bounds (1000 samples)', () => {
  const { execSync } = require('child_process');
  const out = execSync(`python3 -c "
import random
_ENTROPY_SEED = '42'
def _gauss(mu, sigma, lo, hi):
    r = random.Random(int(_ENTROPY_SEED)) if _ENTROPY_SEED else random
    return max(lo, min(hi, r.gauss(mu, sigma)))
failures = [v for i in range(1000) for v in [_gauss(85, 25, 40, 200)] if v < 40 or v > 200]
print(len(failures))
"`, { encoding: 'utf-8', timeout: 5000 });
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
  const { spawn, spawnSync } = require('child_process');

  const API_PORT = 19333;
  const PY_SCRIPT = path.join(__dirname, '..', 'src', 'cdpilot.py');

  // Check curl availability
  const curlCheck = spawnSync('curl', ['--version'], { encoding: 'utf-8' });
  if (curlCheck.error) {
    console.log('  ⚠ curl not available — skipping live API server tests');
    return;
  }

  // Start server
  const serverProc = spawn(
    'python3', [PY_SCRIPT, 'serve', '--api', `--port=${API_PORT}`],
    {
      env: { ...process.env, CDPILOT_API_TEST_MODE: '1', CDP_PORT: '19222' },
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

// ── Summary ──

console.log(`\n  ${passed} passed, ${failed} failed\n`);
process.exit(failed > 0 ? 1 : 0);

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
  assert(out.includes('0.5.0'), 'Should print version');
});

test('-v prints version', () => {
  const out = run('-v');
  assert(out.includes('0.5.0'), 'Should print version');
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
  const m = PY_CONTENT.match(/async def cmd_go[\s\S]*?_adaptive_host_requires_stealth\(url\)[\s\S]{0,500}?CDPILOT_STEALTH[\s\S]{0,200}?navigate_collect/);
  assert(m, "cmd_go must check _adaptive_host_requires_stealth and set CDPILOT_STEALTH=1 BEFORE navigate_collect");
});

test('cmd_go: CAPTCHA detection → remember host + retry once with stealth', () => {
  // The escalation loop: after navigate, if CAPTCHA is detected AND adaptive
  // mode is enabled, the host is added to the persistent list. If stealth
  // was OFF during this navigation, retry exactly once with stealth enabled.
  const m = PY_CONTENT.match(/info\.get\("detected"\)[\s\S]*?_adaptive_remember_host\(host\)[\s\S]*?navigate_collect\(ws,\s*url\)/);
  assert(m, "cmd_go must call _adaptive_remember_host(host) and re-navigate when CAPTCHA is detected with adaptive on");
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

// ── Summary ──

console.log(`\n  ${passed} passed, ${failed} failed\n`);
process.exit(failed > 0 ? 1 : 0);

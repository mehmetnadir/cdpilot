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
  assert(out.includes('0.4.4'), 'Should print version');
});

test('-v prints version', () => {
  const out = run('-v');
  assert(out.includes('0.4.4'), 'Should print version');
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

// ── Summary ──

console.log(`\n  ${passed} passed, ${failed} failed\n`);
process.exit(failed > 0 ? 1 : 0);

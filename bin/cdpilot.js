#!/usr/bin/env node

/**
 * cdpilot — Zero-dependency browser automation CLI
 * Entry point: detects Python, finds browser, delegates to cdpilot.py
 */

const { execSync, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const SCRIPT = path.join(__dirname, '..', 'src', 'cdpilot.py');
const VERSION = require('../package.json').version;

// ── Browser Detection ──

function findBrowser() {
  // User override
  if (process.env.CHROME_BIN) {
    if (fs.existsSync(process.env.CHROME_BIN)) return process.env.CHROME_BIN;
  }

  const platform = os.platform();
  const candidates = [];

  if (platform === 'darwin') {
    candidates.push(
      '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
    );
  } else if (platform === 'linux') {
    candidates.push(
      'brave-browser',
      'brave',
      'google-chrome',
      'google-chrome-stable',
      'chromium-browser',
      'chromium',
    );
  } else if (platform === 'win32') {
    const programFiles = process.env['PROGRAMFILES'] || 'C:\\Program Files';
    const programFilesX86 = process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)';
    const localAppData = process.env.LOCALAPPDATA || '';
    candidates.push(
      path.join(programFiles, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
      path.join(programFilesX86, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
      path.join(localAppData, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
      path.join(programFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'),
      path.join(programFilesX86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
      path.join(localAppData, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    );
  }

  for (const bin of candidates) {
    if (bin.startsWith('/') || bin.includes('\\')) {
      if (fs.existsSync(bin)) return bin;
    } else {
      try {
        execSync(`which ${bin} 2>/dev/null`, { stdio: 'pipe' });
        return bin;
      } catch {}
    }
  }
  return null;
}

// ── Python Detection ──

function findPython() {
  for (const cmd of ['python3', 'python']) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { stdio: 'pipe' }).toString().trim();
      const match = ver.match(/(\d+)\.(\d+)/);
      if (match && parseInt(match[1]) >= 3 && parseInt(match[2]) >= 8) {
        return cmd;
      }
    } catch {}
  }
  return null;
}

// ── Python websockets Detection ──

function findWebsockets() {
  for (const cmd of ['pip3', 'pip']) {
    try {
      const ver = execSync(`${cmd} show websockets 2>&1`, { stdio: 'pipe' }).toString().trim();
      const match = ver.match(/Name: websockets/);
      if (match) {
        return cmd;
      }
    } catch {}
  }
  return null;
}

// ── Setup Command ──

function runSetup() {
  const browser = findBrowser();
  const config = resolveProjectConfig();

  console.log('\n  cdpilot setup\n');
  console.log(`  Browser:    ${browser || '❌ Not found'}`);
  console.log(`  Profile:    ${config.profileDir}`);
  console.log(`  CDP Port:   ${config.port === '0' ? 'auto' : config.port}`);
  console.log(`  Project:    ${config.projectId || 'manual mode'}`);
  console.log(`  Python:     ${findPython() || '❌ Not found'}`);
  console.log(`  websockets: ${findWebsockets() || '❌ Not found'}`);

  if (!browser) {
    console.log('\n  ❌ No compatible browser found.');
    console.log('  Install Brave (recommended): https://brave.com/download/');
    console.log('  Or Google Chrome: https://www.google.com/chrome/\n');
    process.exit(1);
  }

  if (!findPython()) {
    console.log('\n  ❌ Python 3.8+ not found.');
    console.log('  Install: https://www.python.org/downloads/\n');
    process.exit(1);
  }

  if (!findWebsockets()) {
    console.log('\n  ❌ Python websockets not found.');
    console.log('  Install: pip install websockets\n');
    process.exit(1);
  }

  // Create profile directory
  if (!fs.existsSync(config.profileDir)) {
    fs.mkdirSync(config.profileDir, { recursive: true });
    console.log(`\n  ✓ Created profile: ${config.profileDir}`);
  } else {
    console.log(`\n  ✓ Profile exists: ${config.profileDir}`);
  }

  console.log('  ✓ Setup complete! Run: cdpilot launch\n');
}

// ── Pre-flight Check (runs on first launch) ──

function checkWebsockets(python) {
  try {
    execSync(`${python} -c "import websockets"`, { stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

function preflight() {
  const markerFile = path.join(os.homedir(), '.cdpilot', '.preflight-done');

  // Skip if already passed (not first run) and all deps present
  const python = findPython();
  const browser = findBrowser();
  if (fs.existsSync(markerFile) && python && browser && checkWebsockets(python)) {
    return; // All good, skip silently
  }

  console.log(`\n  cdpilot v${VERSION} — Pre-flight Check`);
  console.log('  ' + '─'.repeat(35) + '\n');

  // 1. Python
  if (python) {
    const ver = execSync(`${python} --version 2>&1`, { stdio: 'pipe' }).toString().trim();
    console.log(`  ✓ ${ver}`);
  } else {
    console.log('  ✗ Python 3.8+ not found');
    console.log('    → Install: https://www.python.org/downloads/\n');
    process.exit(1);
  }

  // 2. websockets
  if (checkWebsockets(python)) {
    console.log('  ✓ websockets');
  } else {
    console.log('  ✗ websockets — installing...');
    try {
      execSync(`${python} -m pip install websockets --quiet --disable-pip-version-check`, { stdio: 'pipe' });
      if (checkWebsockets(python)) {
        console.log('  ✓ websockets (installed)');
      } else {
        console.log('  ✗ websockets install failed');
        console.log('    → Run manually: pip install websockets\n');
        process.exit(1);
      }
    } catch {
      console.log('  ✗ websockets auto-install failed');
      console.log('    → Run manually: pip install websockets\n');
      process.exit(1);
    }
  }

  // 3. Browser
  if (browser) {
    const name = path.basename(browser).replace(/\.exe$/i, '');
    console.log(`  ✓ ${name} (${browser})`);
  } else {
    console.log('  ✗ No compatible browser found');
    console.log('    → Install Brave (recommended): https://brave.com/download/');
    console.log('    → Or Chrome: https://www.google.com/chrome/\n');
    process.exit(1);
  }

  // Mark as done
  const dir = path.dirname(markerFile);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(markerFile, new Date().toISOString());

  console.log('\n  Ready!\n');
}

// ── Status Command ──

function runStatus() {
  const config = resolveProjectConfig();
  const port = config.port === '0' ? '9222' : config.port;
  const projLabel = config.projectId ? ` [${config.projectId}]` : '';
  console.log(`\n  cdpilot status (port ${port})${projLabel}\n`);

  try {
    const http = require('http');
    const req = http.get(`http://127.0.0.1:${port}/json/version`, { timeout: 2000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try {
          const info = JSON.parse(data);
          console.log(`  ✓ Connected`);
          console.log(`  Browser: ${info.Browser || 'Unknown'}`);
          console.log(`  Protocol: ${info['Protocol-Version'] || 'Unknown'}`);
          console.log(`  WebSocket: ${info.webSocketDebuggerUrl || 'N/A'}\n`);
        } catch {
          console.log('  ✓ CDP responding but version info unavailable\n');
        }
      });
    });
    req.on('error', () => {
      console.log('  ❌ No browser connected on this port.');
      console.log('  Run: cdpilot launch\n');
    });
    req.on('timeout', () => {
      req.destroy();
      console.log('  ❌ Connection timeout.');
      console.log('  Run: cdpilot launch\n');
    });
  } catch {
    console.log('  ❌ Could not check status.\n');
  }
}

// ── Version ──

function showVersion() {
  console.log(`cdpilot v${VERSION}`);
}

// ── Project-Based Multi-Instance ──

function getProjectId() {
  const cwd = process.cwd();
  const dirName = path.basename(cwd).replace(/[^a-zA-Z0-9-]/g, '').slice(0, 20);
  const crypto = require('crypto');
  const hash = crypto.createHash('md5').update(cwd).digest('hex').slice(0, 6);
  return dirName ? `${dirName}-${hash}` : hash;
}

function resolveProjectConfig() {
  const envPort = process.env.CDP_PORT;
  const envProfile = process.env.CDPILOT_PROFILE;

  // Full manual override
  if (envPort && envProfile) {
    return { port: envPort, profileDir: envProfile, projectId: null };
  }

  const projectId = getProjectId();
  const registryFile = path.join(os.homedir(), '.cdpilot', 'registry.json');
  const defaultProfile = path.join(os.homedir(), '.cdpilot', 'projects', projectId, 'profile');

  let registry = {};
  try {
    const data = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
    registry = data.projects || {};
  } catch {}

  const info = registry[projectId];
  if (info) {
    return {
      port: envPort || String(info.port || 9222),
      profileDir: envProfile || info.profile_dir || defaultProfile,
      projectId,
    };
  }

  // New project: let Python allocate port (pass 0 for auto)
  return {
    port: envPort || '0',
    profileDir: envProfile || defaultProfile,
    projectId,
  };
}

// ── Help ──

function showHelp() {
  console.log(`
  cdpilot v${VERSION} — Zero-dependency browser automation

  USAGE
    cdpilot <command> [args]

  SETUP
    setup              Auto-detect browser, create isolated profile
    launch             Start browser with CDP enabled
    status             Check browser connection
    stop [--smart]     Stop browser (--smart = close owned tabs, quit if empty)
    close [--force|--keep]  Smart close: close cdpilot's tabs; quit browser only
                       if no user tabs remain (--force quits anyway, --keep never quits)

  NAVIGATION
    go <url>           Navigate to URL
    content            Get page text content
    html               Get page HTML
    shot [file]        Take screenshot
    pdf [file]         Save page as PDF

  INTERACTION
    click <sel>        Click element
    type <sel> <text>  Type into input
    fill <sel> <val>   Set input value (React-compatible)
    submit <form>      Submit form
    hover <sel>        Hover element
    keys <combo>       Keyboard shortcut

  DEBUGGING
    console [url]      Capture console logs
    network [url]      Monitor network requests
    debug [url]        Full diagnostic
    eval <js>          Execute JavaScript
    eval-batch <json>  Run N JS expressions in 1 roundtrip (perf)

  PERFORMANCE
    block [on|off|preset|patterns|clear]
                       Block requests via Network.setBlockedURLs (perf opt-in,
                       breaks fingerprint plausibility — not for stealth targets)
    fast [on|off]      Fast mode — auto-wait 5s→2s (env CDPILOT_WAIT_MS overrides)
    show [on|off]      Visual feedback (glow + cursor + ripples).
                       Default OFF since 0.4.4 — opt-in for "see automation" mode.

  SMART NAVIGATION
    dismiss [N|aggressive]
                       Click best "Stay signed out / No thanks / Skip" button.
                       English + Turkish patterns; never clicks destructive
                       lookalikes (Delete account, Sign out, Subscribe).
                       Pass N (1-10) or "aggressive" for chained modals.

  TABS
    tabs               List open tabs
    new-tab [url]      Open new tab
    close-tab [id]     Close tab

  PARALLEL CONTEXTS (isolated cookies/storage inside one browser)
    context create [url]     Make a fresh browser context + tab; prints JSON
    context list             List all browser contexts and their tabs
    context close <ctx-id>   Destroy a browser context (closes all its tabs)
    (Address a context's tab in subsequent commands via CDPILOT_TARGET=<tgt-id>)

  STEALTH & CAPTCHA
    mode [regular|stealth|undetected]
                       Three-tier stealth (crawl4ai-style). regular = no patch
                       (cleanest, default); stealth = light patch (webdriver/
                       chrome.runtime/permissions); undetected = full patch
                       (+ plugins + WebGL + Worker). Adaptive auto-escalates.
    stealth [on|off]   Legacy binary toggle (on -> undetected tier)
    captcha-check      Detect CAPTCHA on active page (JSON output)
    captcha-wait [s]   Pause until user solves CAPTCHA (default 300s)
    captcha-solve [--provider P]
                       Solve Amazon classic image CAPTCHA (opt-in). amazon-local
                       (optional amazoncaptcha lib) or BYOK capsolver/2captcha.
                       Auto-routes PerimeterX 'Press & Hold' to press-hold.
    press-hold [selector]
                       Solve a PerimeterX/HUMAN 'Press & Hold' challenge with a
                       humanized press->hold(jitter)->release gesture (no token,
                       no provider). Auto-finds #px-captcha if no selector given.
    friction           Detect highest anti-bot rung (none/rate_limited/
                       soft_captcha/login_wall/otp_sms/hard_block) + policy.
                       rate_limit auto-backoff in 'go'; login/OTP/block = human
                       handoff (no autonomous bypass). Env: CDPILOT_FRICTION_BACKOFF,
                       CDPILOT_FRICTION_MAX_RETRY.
    profile warm [--minutes N]
                       Age cookies/history on safe sites to boost reCAPTCHA v3 score.
    adaptive [on|off]  Auto-escalate to stealth on hosts that show CAPTCHA.
                       Remembers per-host. Use 'adaptive forget <host>' to reset.
    cookies save <file> [<dom>]
                       Export cookies (all or scoped). Replay clearance cookies
                       across cdpilot runs to skip Cloudflare walls.
    cookies load <file>
                       Import previously-saved cookies into the current jar.

  RELIABILITY
    browser [name]     Show or set preferred browser (chrome|brave|chromium|edge|vivaldi|auto)
    health             JSON status: alive, port, tabs, browser, today's crashes

  PROJECTS
    projects           List all project browser instances
    project-stop <id>  Stop a specific project's browser
    stop-all           Stop all browser instances

  AI AGENT
    mcp                Start MCP server (stdin/stdout JSON-RPC)

  WATCH (continuous screencast for AI video understanding)
    watch start <url>  Begin JPEG screencast at N fps to a disk ring buffer
                       (default 10fps, 5min retention, 100MB cap). Background
                       daemon — command returns immediately.
    watch query --at MM:SS --window 5s
                       Return JSON list of frame paths around a video time.
    watch query --last 5s | --since-last
                       Recent frames or everything new since the last query.
    watch status       Daemon state, frame count, disk usage.
    watch stop         Stop daemon + clean up frames (--keep-frames to retain).
    watch ask "<q>"    Tiny NL parser: extracts time window from a question.

  More: https://github.com/mehmetnadir/cdpilot#commands
`);
}

// ── Internal Test Runner ──

function runInternalTestRunner(testFile, traceDir, traceMode, grepPattern) {
  if (traceDir) {
    fs.mkdirSync(path.join(traceDir, 'screenshots'), { recursive: true });
    fs.mkdirSync(path.join(traceDir, 'a11y'), { recursive: true });
  }

  const metaPath = traceDir ? path.join(traceDir, 'meta.json') : null;
  const stepsPath = traceDir && traceMode !== 'off' ? path.join(traceDir, 'steps.jsonl') : null;

  const meta = { name: path.basename(testFile), started_at: new Date().toISOString(), status: 'running', tests: [] };
  if (metaPath) fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2));

  const testQueue = [];
  global.test = (name, fn) => testQueue.push({ name, fn });

  try {
    require(path.resolve(testFile));
  } catch (err) {
    const out = { passed: 0, failed: 1, skipped: 0, tests: [{ name: testFile, status: 'failed', duration_ms: 0, error: err.message }] };
    process.stdout.write(JSON.stringify(out) + '\n');
    process.exit(1);
  }

  const results = { passed: 0, failed: 0, skipped: 0, tests: [] };
  const cdpPort = process.env.CDP_PORT || '9222';
  const SCRIPT = path.join(__dirname, '..', 'src', 'cdpilot.py');
  const python = 'python3';
  let stepIdx = 0;

  const makeT = () => {
    const runCmd = (cmd, ...cargs) => {
      const padded = String(stepIdx).padStart(3, '0');
      const step = { action: cmd + ' ' + cargs.join(' '), ts_ms: Date.now(), duration_ms: 0, error: null };
      const t0 = Date.now();
      try {
        const quoted = cargs.map(a => JSON.stringify(String(a))).join(' ');
        execSync(`${python} ${SCRIPT} ${cmd} ${quoted}`, {
          stdio: 'pipe',
          env: { ...process.env, CDP_PORT: cdpPort },
          timeout: 30000,
        });
        step.duration_ms = Date.now() - t0;
        if (stepsPath) fs.appendFileSync(stepsPath, JSON.stringify(step) + '\n');
        // Screenshot after each step (best-effort — no browser = skipped)
        if (traceDir && traceMode !== 'off') {
          try {
            const shotPath = path.join(traceDir, 'screenshots', `step-${padded}.png`);
            execSync(`${python} ${SCRIPT} shot ${shotPath}`, { stdio: 'pipe', env: { ...process.env, CDP_PORT: cdpPort }, timeout: 10000 });
          } catch (_) { /* no browser is OK in unit-style tests */ }
        }
        stepIdx++;
      } catch (err) {
        step.duration_ms = Date.now() - t0;
        step.error = err.stderr ? err.stderr.toString().trim() : err.message;
        if (stepsPath) fs.appendFileSync(stepsPath, JSON.stringify(step) + '\n');
        stepIdx++;
        throw new Error(`${cmd} failed: ${step.error}`);
      }
    };

    const t = {
      goto: (url) => runCmd('go', url),
      click: (sel) => runCmd('click', sel),
      fill: (sel, val) => runCmd('fill', sel, val),
      type: (sel, val) => runCmd('type', sel, val),
      hover: (sel) => runCmd('hover', sel),
      screenshot: (p) => runCmd('shot', p),
      eval: (js) => {
        try {
          const out = execSync(`${python} ${SCRIPT} eval ${JSON.stringify(js)}`, { stdio: 'pipe', env: { ...process.env, CDP_PORT: cdpPort }, timeout: 10000 });
          return out.toString().trim();
        } catch (e) { throw new Error('eval failed: ' + e.message); }
      },
      a11y: () => runCmd('a11y-snapshot'),
    };

    t.expect = (textOrSel) => runCmd('assert', textOrSel);
    t.expect.url = (expected) => runCmd('assert-url', expected);
    t.expect.visible = (sel) => runCmd('assert-visible', sel);
    t.expect.hidden = (sel) => runCmd('assert-hidden', sel);

    return t;
  };

  // Run tests sequentially (parallel is managed at the Python level across files)
  const runAll = async () => {
    for (const tst of testQueue) {
      if (grepPattern && !tst.name.match(new RegExp(grepPattern, 'i'))) {
        results.skipped++;
        continue;
      }
      const t0 = Date.now();
      const rec = { name: tst.name, status: 'passed', duration_ms: 0, error: null };
      try {
        await tst.fn(makeT());
        rec.status = 'passed';
        results.passed++;
      } catch (err) {
        rec.status = 'failed';
        rec.error = err.message;
        results.failed++;
      }
      rec.duration_ms = Date.now() - t0;
      results.tests.push(rec);
      if (metaPath) {
        meta.tests.push(rec);
        meta.status = 'running';
        fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2));
      }
    }

    // Finalize meta
    if (metaPath) {
      meta.status = results.failed > 0 ? 'failed' : 'passed';
      meta.passed = results.passed;
      meta.failed = results.failed;
      meta.skipped = results.skipped;
      meta.ended_at = new Date().toISOString();
      fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2));
    }

    process.stdout.write(JSON.stringify(results) + '\n');
    process.exit(results.failed > 0 ? 1 : 0);
  };

  runAll().catch(err => {
    process.stderr.write('Test runner error: ' + err.message + '\n');
    process.exit(1);
  });
}

// ── Main ──

// Internal test runner mode — intercept before normal CLI dispatch
if (process.argv.includes('--internal-test-runner')) {
  const idx = process.argv.indexOf('--internal-test-runner');
  const testFile = process.argv[idx + 1];
  const traceDirArg = process.argv.find(a => a.startsWith('--trace-dir='));
  const traceArg = process.argv.find(a => a.startsWith('--trace='));
  const grepArg = process.argv.find(a => a.startsWith('--grep='));
  runInternalTestRunner(
    testFile,
    traceDirArg ? traceDirArg.split('=').slice(1).join('=') : null,
    traceArg ? traceArg.split('=')[1] : 'default',
    grepArg ? grepArg.split('=').slice(1).join('=') : null,
  );
  return; // runAll() is async, this exits via process.exit
}

const args = process.argv.slice(2);
const cmd = args[0];

if (!cmd || cmd === 'help' || cmd === '--help' || cmd === '-h') {
  showHelp();
  process.exit(0);
}

if (cmd === '--version' || cmd === '-v') {
  showVersion();
  process.exit(0);
}

if (cmd === 'setup') {
  runSetup();
  process.exit(0);
}

if (cmd === 'status') {
  runStatus();
  // Don't exit immediately — let http callback complete
} else {
  // Pre-flight check on first run or 'launch' command
  if (cmd === 'launch') {
    preflight();
  }

  // Delegate to Python
  const python = findPython();
  if (!python) {
    console.error('Error: Python 3.8+ required. Install: https://www.python.org/downloads/');
    process.exit(1);
  }

  const browser = findBrowser();
  const config = resolveProjectConfig();

  const env = {
    ...process.env,
    CDPILOT_PROFILE: config.profileDir,
  };

  // Only pass CDP_PORT if explicitly set or resolved from registry (not 0)
  if (config.port !== '0') {
    env.CDP_PORT = config.port;
  }

  if (config.projectId) {
    env.CDPILOT_PROJECT_ID = config.projectId;
  }

  if (browser && !process.env.CHROME_BIN) {
    env.CHROME_BIN = browser;
  }

  const child = spawn(python, [SCRIPT, ...args], {
    stdio: 'inherit',
    env,
  });

  child.on('close', (code) => {
    process.exit(code || 0);
  });
}

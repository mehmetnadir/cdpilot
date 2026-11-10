#!/usr/bin/env node

/**
 * cdpilot — Browser automation CLI, zero npm dependencies
 * Entry point: detects Python, finds browser, delegates to cdpilot.py
 */

const { execSync, spawn, spawnSync } = require('child_process');

// Output the launcher prints itself (help, status) must survive process.exit():
// on macOS a piped stdout is asynchronous, and exiting right after a write
// longer than the pipe buffer (8 KB) cut --help off mid-text.
for (const stream of [process.stdout, process.stderr]) {
  if (stream._handle && typeof stream._handle.setBlocking === 'function') stream._handle.setBlocking(true);
}
const path = require('path');
const fs = require('fs');
const os = require('os');

const SCRIPT = path.join(__dirname, '..', 'src', 'cdpilot.py');
const VERSION = require('../package.json').version;
const SRC_DIR = path.join(__dirname, '..', 'src');

// Python runs src/cdpilot.py through the import system (runpy) instead of as a
// script: a script named on the command line is recompiled on every call —
// 0.15 s of the ~0.3 s Python start-up measured on 2026-11-08 for the 23k-line
// file — while an imported module keeps its bytecode in src/__pycache__/.
// sys.argv ends up exactly as for `python cdpilot.py <args>` (alter_sys), and
// an unwritable src/ only means Python skips the cache, never an error.
// An interpreter started with -c puts '' (the working directory) first on
// sys.path, so a runpy.py or json.py planted in an untrusted checkout would run
// before cdpilot does (2026-11-10 review); the loader drops that entry before
// any other import. `python src/cdpilot.py` had src/ there instead.
const PY_LOADER = "import sys; sys.path[:] = [p for p in sys.path if p]; sys.path.insert(0, sys.argv[1]); del sys.argv[1]; "
  + "import runpy; runpy.run_module('cdpilot', run_name='__main__', alter_sys=True)";
function pyArgs(...args) {
  return ['-c', PY_LOADER, SRC_DIR, ...args];
}

// The interpreter choice is remembered in CDPILOT_HOME/python.json for a day:
// probing candidates with `--version` cost 50-150 ms per command (a shell and
// a Python start per candidate tried). CDPILOT_PYTHON is part of the key, an
// absolute path that vanished is re-probed, and a failed spawn clears the entry.
const PYTHON_CACHE_TTL_MS = 24 * 3600 * 1000;
function pythonCachePath() {
  return path.join(cdpilotHome(), 'python.json');
}
function readPythonCache() {
  try {
    const c = JSON.parse(fs.readFileSync(pythonCachePath(), 'utf8'));
    if (c.python && c.key === (process.env.CDPILOT_PYTHON || '')
        && Date.now() - c.at < PYTHON_CACHE_TTL_MS
        && (!path.isAbsolute(c.python) || fs.existsSync(c.python))) {
      return c.python;
    }
  } catch {}
  return null;
}
function writePythonCache(python) {
  try {
    fs.mkdirSync(cdpilotHome(), { recursive: true });
    fs.writeFileSync(pythonCachePath(),
      JSON.stringify({ python, key: process.env.CDPILOT_PYTHON || '', at: Date.now() }));
  } catch {}
}
function clearPythonCache() {
  try { fs.unlinkSync(pythonCachePath()); } catch {}
}

// ── Warm process (daemon) ──
// CDPILOT_DAEMON=1: page commands go to one warm Python process per project
// (src/cdpilot.py --_daemon-serve) over a Unix socket; it keeps the module and
// the asyncio loop between calls — the CDP connections a request opened are
// closed at its end, as a process exit closed them (2026-11-08: a
// fresh process spent ~110 ms in node, ~140 ms starting Python and ~500 ms
// setting the CDP session up before `go` even began). The client falls back
// to a fresh process whenever the daemon is missing, busy (no hello within
// DAEMON_HELLO_MS), of another version, or refuses the command — always before
// anything ran, so a command never runs twice. POSIX only for now.
const net = require('net');
const DAEMON_SERVE_FLAG = '--_daemon-serve';
const DAEMON_HELLO_MS = 150;
// Mirrors DAEMON_SPAWN_CMDS in src/cdpilot.py (a test keeps them identical):
// lifecycle, servers and forks, long-running loops, the daemon itself.
const DAEMON_SPAWN_CMDS = new Set([
  'launch', 'stop', 'stop-all', 'project-stop', 'connect', 'disconnect',
  'serve', 'mcp', 'watch', 'setup', 'status', 'daemon', 'replay', 'run',
  'blog', 'bot-auth', 'browser', 'test', 'trace', 'heal', 'health',
  'session', 'sessions', 'session-close', 'projects', 'proxy', 'extensions',
  'tls-proxy', 'captcha-wait', 'help', '--help', '-h']);
// "cmd sub" pairs that run fresh while the command itself is served warm
// (agent observe/act are page steps; agent twitter logs in and posts).
const DAEMON_SPAWN_SUBCMDS = new Set(['agent twitter', 'canvas open', 'canvas stream',
  'canvas watch', 'canvas events']);

function daemonEnabled() {
  return process.env.CDPILOT_DAEMON === '1' && process.platform !== 'win32';
}

function daemonEligible(cmd, args) {
  if (!daemonEnabled() || !cmd || DAEMON_SPAWN_CMDS.has(cmd) || cmd.startsWith('--_')) return false;
  if (DAEMON_SPAWN_SUBCMDS.has(`${cmd} ${args[1] || ''}`)) return false;
  // --timeout ends its process with os._exit: a fresh process for it.
  if (commandIndex(args) !== 0 || process.env.CDPILOT_TIMEOUT) return false;
  return true;
}

// stdin a command reads (cmd_batch: always; cmd_check: without an argument)
// travels inside the request; the daemon has no terminal.
function daemonStdin(cmd, args) {
  if (process.stdin.isTTY) return undefined;
  if (cmd !== 'batch' && !(cmd === 'check' && args.length === 1)) return undefined;
  try { return fs.readFileSync(0, 'utf8'); } catch { return ''; }
}

// The daemon is keyed by everything src/cdpilot.py reads at import time, so a
// request never meets a process set up for another project, port, browser,
// home or interpreter: a different key is a different socket and daemon.
function daemonKey(env, python) {
  const parts = { python, version: VERSION, src: SRC_DIR, home: env.HOME || '' };
  for (const k of Object.keys(env).sort()) {
    if (k.startsWith('CDPILOT_') || k.startsWith('CDP_') || k === 'CHROME_BIN') parts[k] = env[k];
  }
  return require('crypto').createHash('sha1').update(JSON.stringify(parts)).digest('hex').slice(0, 16);
}

// sun_path holds 104 bytes on macOS: a long CDPILOT_HOME moves the socket to
// a private per-user directory — $XDG_RUNTIME_DIR when set (Linux desktops),
// else one under the temp dir (the key still includes the home).
function daemonDirs() {
  const uid = typeof process.getuid === 'function' ? process.getuid() : 0;
  const runtime = process.env.XDG_RUNTIME_DIR
    ? path.join(process.env.XDG_RUNTIME_DIR, 'cdpilot-daemon')
    : path.join(os.tmpdir(), `cdpilot-${uid}-daemon`);
  return [path.join(cdpilotHome(), 'daemon'), runtime];
}

function daemonSockPath(key) {
  const [home, runtime] = daemonDirs();
  const p = path.join(home, `${key}.sock`);
  return Buffer.byteLength(p) <= 100 ? p : path.join(runtime, `${key}.sock`);
}

// A socket is only used when its directory and the socket itself belong to
// this user and nobody else may write there: in a shared temp dir another
// user could otherwise plant a fake daemon and receive argv, cwd and stdin.
function daemonPathSafe(sockPath) {
  if (typeof process.getuid !== 'function') return true;
  const uid = process.getuid();
  try {
    const dir = fs.lstatSync(path.dirname(sockPath));
    if (!dir.isDirectory() || dir.uid !== uid || (dir.mode & 0o077) !== 0) return false;
  } catch (e) {
    return e.code === 'ENOENT';  // no directory yet: startDaemon creates it 0700
  }
  try {
    const st = fs.lstatSync(sockPath);
    return st.isSocket() && st.uid === uid;
  } catch (e) {
    return e.code === 'ENOENT';  // no socket yet: the daemon may be started here
  }
}

// One request on one connection. Resolves {handled: true, code} when the
// daemon ran the command (every output frame went through onFrame), or
// {handled: false, reason} when nothing ran and the caller must spawn.
function daemonRequest(sockPath, payload, onFrame) {
  return new Promise((resolve) => {
    let settled = false, hello = false, buf = '', scanFrom = 0, exitCode = null;
    const done = (v) => { if (!settled) { settled = true; resolve(v); } };
    if (!daemonPathSafe(sockPath)) { done({ handled: false, reason: 'unsafe' }); return; }
    const sock = net.createConnection(sockPath);
    sock.setEncoding('utf8');
    const timer = setTimeout(() => {
      if (!hello) { sock.destroy(); done({ handled: false, reason: 'busy' }); }
    }, DAEMON_HELLO_MS);
    sock.on('error', (e) => {
      clearTimeout(timer);
      done(hello ? { handled: true, code: 1, error: `daemon connection failed: ${e.message}` }
                 : { handled: false, reason: e.code || 'error' });
    });
    sock.on('data', (chunk) => {
      buf += chunk;
      let nl;
      while ((nl = buf.indexOf('\n', scanFrom)) >= 0) {
        const line = buf.slice(0, nl);
        buf = buf.slice(nl + 1);
        scanFrom = 0;
        let msg;
        try { msg = JSON.parse(line); } catch { continue; }
        if (!hello) {
          hello = true;
          clearTimeout(timer);
          if (msg.version !== VERSION) {
            // An older install's daemon: ask it to leave, run this call fresh.
            sock.end(JSON.stringify({ op: 'shutdown' }) + '\n');
            done({ handled: false, reason: 'version' });
            return;
          }
          sock.write(JSON.stringify(payload) + '\n');
          continue;
        }
        if (msg.fallback !== undefined) {
          done({ handled: false, reason: String(msg.fallback) });
          sock.destroy();
          return;
        }
        if (msg.exit !== undefined) {
          // The last frame: the command ran and every output frame is through. Do not wait
          // for the daemon to close the socket (K-0027: on Linux it held it open for 10 s).
          exitCode = msg.exit;
          done({ handled: true, code: exitCode });
          sock.destroy();
          return;
        }
        onFrame(msg);
      }
      scanFrom = buf.length;  // a frame longer than one chunk: do not rescan it
    });
    sock.on('close', () => {
      clearTimeout(timer);
      if (exitCode !== null) done({ handled: true, code: exitCode });
      else done(hello ? { handled: true, code: 1, error: 'connection to the daemon was lost' }
                      : { handled: false, reason: 'closed' });
    });
  });
}

// Fork the warm process for this key, detached; at most once per 5 s. The
// stamp is created exclusively (no symlink following, no second starter).
function startDaemon(sockPath, python, env) {
  if (!daemonPathSafe(sockPath)) return false;
  const stamp = `${sockPath}.starting`;
  try {
    fs.mkdirSync(path.dirname(sockPath), { recursive: true, mode: 0o700 });
    let fd;
    try {
      fd = fs.openSync(stamp, 'wx', 0o600);
    } catch (e) {
      if (e.code !== 'EEXIST') return false;
      try { if (Date.now() - fs.lstatSync(stamp).mtimeMs < 5000) return false; } catch { return false; }
      fs.unlinkSync(stamp);  // a starter that never got to bind: try once more
      fd = fs.openSync(stamp, 'wx', 0o600);
    }
    fs.writeSync(fd, String(process.pid));
    fs.closeSync(fd);
    const child = spawn(python, pyArgs(DAEMON_SERVE_FLAG, sockPath),
      { detached: true, stdio: 'ignore', env });
    child.on('error', () => {});
    child.unref();
    return true;
  } catch {
    return false;
  }
}

function daemonPing(sockPath) {
  return new Promise((resolve) => {
    let pong = null;
    daemonRequest(sockPath, { op: 'ping' }, (m) => { if (m.pong) pong = m; })
      .then(() => resolve(pong));
  });
}

function listDaemonSockets() {
  const out = [];
  for (const dir of daemonDirs()) {
    let names = [];
    try { names = fs.readdirSync(dir); } catch { continue; }
    for (const n of names) if (n.endsWith('.sock')) out.push(path.join(dir, n));
  }
  return out;
}

// `cdpilot daemon start|stop|status`
async function daemonCommand(sub, python, env) {
  const what = sub[0] || 'status';
  const mine = daemonSockPath(daemonKey(env, python));
  if (what === 'start') {
    if (process.platform === 'win32') {
      console.error('cdpilot daemon: not available on Windows yet');
      return 1;
    }
    let pong = await daemonPing(mine);
    if (!pong) {
      startDaemon(mine, python, env);
      for (let i = 0; i < 30 && !pong; i++) {
        await new Promise((r) => setTimeout(r, 100));
        pong = await daemonPing(mine);
      }
    }
    if (!pong) {
      console.error('cdpilot daemon: did not start (see `cdpilot daemon status`)');
      return 1;
    }
    console.log(`daemon running: pid ${pong.pid}, socket ${mine}`);
    if (!daemonEnabled()) console.log('set CDPILOT_DAEMON=1 to send commands to it');
    return 0;
  }
  if (what === 'stop') {
    let n = 0;
    for (const sock of listDaemonSockets()) {
      const r = await daemonRequest(sock, { op: 'shutdown' }, () => {});
      if (r.handled) n++;
      else if (r.reason === 'ECONNREFUSED' || r.reason === 'ENOENT') {
        try { fs.unlinkSync(sock); } catch {}  // nobody listens: a leftover of a crash
      }  // busy (no hello in time): leave it, it is serving a command
    }
    console.log(n ? `stopped ${n} daemon${n === 1 ? '' : 's'}` : 'no daemon running');
    return 0;
  }
  if (what === 'status') {
    const socks = listDaemonSockets();
    let live = 0;
    for (const sock of socks) {
      const pong = await daemonPing(sock);
      if (!pong) continue;
      live++;
      const up = Math.max(0, Math.round(Date.now() / 1000 - pong.started));
      console.log(`${sock === mine ? '*' : ' '} pid ${pong.pid}  served ${pong.served}  up ${up}s  idle-exit ${pong.idle}s  ${sock}`);
    }
    if (!live) {
      console.log('no daemon running' + (daemonEnabled() ? '' : ' (CDPILOT_DAEMON=1 starts one on the next command)'));
      console.log(`  socket: ${mine}`);
    } else if (socks.includes(mine)) {
      console.log('* = this project and environment');
    }
    return 0;
  }
  console.error(`cdpilot daemon: unknown subcommand '${what}' (start | stop | status)`);
  return 2;
}

// CDPILOT_HOME resolution — must match src/cdpilot.py exactly:
//   CDPILOT_HOME = os.environ.get("CDPILOT_HOME") or os.path.expanduser("~/.cdpilot")
// A set-but-empty CDPILOT_HOME falls back to the default (empty string is
// falsy in both Python's `or` and JS's `||`). A non-empty CDPILOT_HOME is
// used verbatim — no `~` expansion — same as Python's os.environ.get() here
// (expanduser is only applied to the hardcoded "~/.cdpilot" fallback).
function cdpilotHome() {
  return process.env.CDPILOT_HOME || path.join(os.homedir(), '.cdpilot');
}

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
  const cached = readPythonCache();
  if (cached) return cached;
  // cdpilot.py uses PEP 604 unions (dict | None) → requires Python 3.10+.
  // Prefer version-specific + Homebrew interpreters so a stale default python3
  // (e.g. macOS 3.9) is skipped instead of selected and crashing at runtime.
  const candidates = [
    process.env.CDPILOT_PYTHON,
    'python3.13', 'python3.12', 'python3.11', 'python3.10',
    '/opt/homebrew/bin/python3', '/usr/local/bin/python3',
    'python3', 'python',
  ].filter(Boolean);
  for (const cmd of candidates) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { stdio: 'pipe' }).toString().trim();
      const match = ver.match(/(\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 10))) {
        writePythonCache(cmd);
        return cmd;
      }
    } catch {}
  }
  return null;
}

// ── Python websockets Detection ──

function findWebsockets() {
  // Import via the interpreter cdpilot actually selects — pip metadata can
  // point at a different Python than findPython() resolves.
  const python = findPython();
  if (!python) return null;
  try {
    const out = execSync(`${python} -c "import websockets; print(getattr(websockets, '__version__', 'installed'))"`, { stdio: 'pipe' }).toString().trim();
    return out || 'installed';
  } catch {
    return null;
  }
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
    console.log('\n  ❌ Python 3.10+ not found.');
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
  const markerFile = path.join(cdpilotHome(), '.preflight-done');

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
    console.log('  ✗ Python 3.10+ not found');
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

  // Check if this project has an external (connect'ed) browser
  let isExternal = false;
  let browserName = '';
  try {
    const home = cdpilotHome();
    const regFile = path.join(home, 'registry.json');
    const data = JSON.parse(fs.readFileSync(regFile, 'utf-8'));
    const entry = (data.projects || {})[config.projectId];
    if (entry && entry.external) {
      isExternal = true;
      browserName = entry.browser_name || '';
    }
  } catch {}

  const extLabel = isExternal ? ' (external)' : '';
  console.log(`\n  cdpilot status (port ${port})${projLabel}${extLabel}\n`);

  try {
    const http = require('http');
    const req = http.get(`http://127.0.0.1:${port}/json/version`, { timeout: 2000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try {
          const info = JSON.parse(data);
          console.log(`  ✓ Connected`);
          console.log(`  Browser: ${info.Browser || 'Unknown'}${isExternal ? ' (external — your browser)' : ''}`);
          console.log(`  Protocol: ${info['Protocol-Version'] || 'Unknown'}`);
          console.log(`  WebSocket: ${info.webSocketDebuggerUrl || 'N/A'}`);
          if (isExternal) {
            console.log(`  cdpilot will never close this browser.\n`);
          } else {
            const extra = [webmcpLabel(config.profileDir), botAuthLabel(port)].filter(Boolean);
            console.log(`  ${idleCloseLabel(port)}${extra.length ? '' : '\n'}`);
            extra.forEach((l, i) => console.log(`  ${l}${i === extra.length - 1 ? '\n' : ''}`));
          }
        } catch {
          console.log('  ✓ CDP responding but version info unavailable\n');
        }
      });
    });
    req.on('error', () => {
      if (isExternal) {
        console.log(`  ❌ External browser (${browserName || 'unknown'}) is gone.`);
        console.log('  Run: cdpilot connect again or cdpilot disconnect\n');
      } else {
        console.log('  ❌ No browser connected on this port.');
        const webmcp = webmcpLabel(config.profileDir);
        if (webmcp) console.log(`  ${webmcp}`);
        console.log('  Run: cdpilot launch\n');
      }
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

// Idle auto-close countdown, from the files src/cdpilot.py keeps (see
// _idle_status there): CDPILOT_HOME/idle/<port>.json names the watcher and its
// minutes, CDPILOT_HOME/projects/<id>/last-activity the last command.
function idleCloseLabel(port) {
  const home = cdpilotHome();
  try {
    const st = JSON.parse(fs.readFileSync(path.join(home, 'idle', `${port}.json`), 'utf-8'));
    const minutes = Number(st.minutes) || 0;
    if (minutes <= 0 || !st.pid) return 'idle close off';
    try {
      process.kill(st.pid, 0); // existence probe; safe on Windows in Node
    } catch (e) {
      if (e.code !== 'EPERM') return 'idle close off';
    }
    let last = Number(st.started) || Date.now() / 1000;
    try {
      const file = path.join(home, 'projects', String(st.project_id), 'last-activity');
      const t = parseFloat(fs.readFileSync(file, 'utf-8'));
      if (t > last) last = t;
    } catch {}
    const left = Math.max(0, Math.floor(minutes * 60 - (Date.now() / 1000 - last)));
    return `idle close in ${Math.ceil(left / 60)}m`;
  } catch {
    return 'idle close off';
  }
}

// This project's WebMCP mode, as src/cdpilot.py reads it (get_webmcp_config):
// CDPILOT_WEBMCP=1|0 wins, else <profile>/webmcp.json written by
// `launch --webmcp` / `launch --no-webmcp`.
function webmcpMode(profileDir) {
  const raw = (process.env.CDPILOT_WEBMCP || '').trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(raw)) return { on: true, from: 'CDPILOT_WEBMCP' };
  if (['0', 'false', 'no', 'off'].includes(raw)) return { on: false, from: 'CDPILOT_WEBMCP' };
  try {
    const st = JSON.parse(fs.readFileSync(path.join(profileDir, 'webmcp.json'), 'utf-8'));
    return { on: st.webmcp === true, from: 'launch --webmcp' };
  } catch {
    return { on: false, from: null };
  }
}

// Printed by `status` only while the mode is on (the default output is unchanged).
function webmcpLabel(profileDir) {
  const m = webmcpMode(profileDir);
  if (!m.on) return null;
  return `WebMCP: on (${m.from}; browsers start with --enable-features=WebMCP)`;
}

// Web Bot Auth signer line, printed by `status` only when bot-auth is set up
// (a key in CDPILOT_HOME/bot-auth/, or signer state for this port), so the
// default output is unchanged. With no signer state file or stale marker in
// CDPILOT_HOME/bot-auth/signers/ it is "off" without starting Python.
// Otherwise Python decides (hidden --_bot-auth-label, see
// _bot_auth_helper_state there): a pid alone proves nothing, the signer is
// "on" only if that pid's command line is this port's signer and the browser
// is still the one it attached to; a dead or stale signer also prints the
// one-line "requests go out unsigned" warning on stderr.
function botAuthLabel(port) {
  const home = cdpilotHome();
  const dir = path.join(home, 'bot-auth', 'signers');
  const signer = fs.existsSync(path.join(dir, `${port}.json`)) || fs.existsSync(path.join(dir, `${port}.stale`));
  if (!signer) return fs.existsSync(path.join(home, 'bot-auth', 'config.json')) ? 'bot-auth: off' : null;
  const python = findPython();
  if (!python) return 'bot-auth: off';
  const r = spawnSync(python, pyArgs('--_bot-auth-label'), {
    encoding: 'utf-8', timeout: 20000,
    env: { ...process.env, CDP_PORT: String(port), CDPILOT_LOG: '0' },
  });
  if (r.stderr) process.stderr.write(r.stderr);
  const line = (r.stdout || '').trim().split('\n').pop();
  return /^bot-auth: /.test(line || '') ? line : 'bot-auth: off';
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
  const registryFile = path.join(cdpilotHome(), 'registry.json');
  const defaultProfile = path.join(cdpilotHome(), 'projects', projectId, 'profile');

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
  cdpilot v${VERSION} — browser automation, zero npm dependencies

  USAGE
    cdpilot [--timeout <s>] <command> [args]

  GLOBAL OPTIONS
    --timeout <s>      Abort the command after <s> seconds (exit 124). Before or
                       after the command; env CDPILOT_TIMEOUT sets a default
                       (the flag wins, 0 disables).
    Page commands start the browser if it is not running
                       (set CDPILOT_NO_AUTOLAUNCH=1 to get an error instead).
    An auto-launched (or MCP-launched) browser closes after 15 min without a
                       cdpilot command or page change (CDPILOT_IDLE_CLOSE=<minutes>,
                       0 = never); an explicit launch stays open unless asked (below).
    CDPILOT_DAEMON=1   Keep one warm Python process per project and send page
                       commands to it over a local socket (browser-free command
                       ~270 -> ~140 ms, content/eval ~360 -> ~110 ms, M1 Max;
                       a fresh process when it is missing or busy; not with
                       --timeout; 'daemon status|stop'; idle exit after
                       CDPILOT_DAEMON_IDLE seconds, default 1800).
    CDPILOT_VAR_HOSTS  Hosts (comma-separated) an agent flow may type
                       CDPILOT_VAR_* values on

  SETUP
    setup              Auto-detect browser, create isolated profile
    launch [--idle-close <min>] [--webmcp|--no-webmcp] [--bot-auth]
                       Start browser with CDP enabled (--idle-close or
                       CDPILOT_IDLE_CLOSE: close it after <min> idle minutes;
                       --webmcp: this project's browsers start with WebMCP on,
                       saved until --no-webmcp; see WEBMCP below; --bot-auth:
                       sign every request, see WEB BOT AUTH)
    status             Check browser connection (idle close; WebMCP and the
                       bot-auth signer when set up)
    stop [--smart]     Stop browser (--smart = close owned tabs, quit if empty)
    connect [<port> | <ws-url> | --auto]
                       Use a browser you started with --remote-debugging-port
                       and --user-data-dir; cdpilot never closes or injects
                       into it. --auto reads DevToolsActivePort files.
                       (chrome://inspect remote-debugging mode: not supported yet)
    disconnect         Forget the connected browser (it keeps running)
    close [--force|--keep]  Smart close: close cdpilot's tabs; quit browser only
                       if no user tabs remain (--force quits anyway, --keep never quits)

  NAVIGATION
    go <url>           Navigate to URL (alias: open)
    content            Get page text content
    html               Get page HTML
    shot [file]        Take screenshot
    pdf [file]         Save page as PDF

  INTERACTION
    click <sel>        Click element; exit 3 =
                       pressed, release missed the target, not clicked
    type <sel> <text>  Type into input
    fill <sel> <val>   Set input value (React-compatible)
    submit <form>      Submit form
    hover <sel>        Hover element
    keys <combo>       Keyboard shortcut
    Inside an iframe:  click "iframe#card >>> input[name=cardnumber]"
                       (nest: "iframe.a >>> iframe.b >>> button") or
                       --frame <selector|index|url-substring>; same-origin and
                       cross-origin frames. With no match in the page,
                       smart-click searches all frames, smart-fill and
                       smart-select only frames of the page's origin.
    frame list|eval [--frame <f>]
                       List iframes / run JS inside a frame

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

  WEB BOT AUTH (signed agent — the opposite of stealth; needs: pip install cryptography)
    bot-auth init --agent-url https://your-domain.com [--force]
                       Generate an Ed25519 key (0600, never printed) in CDPILOT_HOME/bot-auth/
    bot-auth directory Print the JWKS to serve at
                       https://your-domain.com/.well-known/http-message-signatures-directory
    bot-auth directory --headers [--authority <host>] [--ttl <s>] [--content-digest] [--json]
                       The same plus the Signature / Signature-Input headers that
                       response must carry (Cloudflare checks them; one per key)
    bot-auth format [legacy|dict]
                       Signature-Agent format. legacy (default): "https://…",
                       what Cloudflare verifies; dict: sig1="https://…" (draft-05)
    bot-auth status    Agent URL, keyid, and whether the signer is running
    launch --bot-auth  Launch with a signer that adds Signature, Signature-Input and
                       Signature-Agent to EVERY request the browser makes (new tabs,
                       popups, iframes, workers, page fetches after cdpilot exits).
                       Or CDPILOT_BOT_AUTH=1. With stealth mode: one warning, stealth
                       injection skipped. "stop" ends the signer.

  RELIABILITY
    browser [name]     Show or set preferred browser
                       (chrome|brave|chromium|edge|vivaldi|chrome-for-testing|auto)
    browser install chrome-for-testing [--channel stable|beta|dev|canary] [--version X]
                       Download Chrome for Testing (~150-190 MB, only on this
                       command) for extension development: Chrome 137+ ignores
                       --load-extension, CfT does not. Used instead of Chrome
                       while dev extensions are registered. Not for stealth.
    health             JSON status: alive, port, tabs, browser, today's crashes
    daemon start|stop|status
                       The warm process behind CDPILOT_DAEMON=1: start it ahead
                       of time, stop every running one, or list them (pid,
                       requests served, uptime, socket).

  PROJECTS
    projects           List all project browser instances
    project-stop <id>  Stop a specific project's browser
    stop-all           Stop all browser instances

  AI AGENT
    agent observe [--diff]
                       Page state as numbered @refs (+text); --diff = only
                       changes since last
    agent act --ref @N [--action click|type|fill|hover|submit] [--text X]
                       Acts, prints the diff
    agent act --url URL
                       Navigates silently, prints the diff
    agent flow save <name> [--last N] | list | show <name> | delete <name>
                       Save the acts since the last navigation as a replayable
                       flow
    agent run <name> [--var k=v] [--dry-run]
                       Replay by anchors, no model; exit 4 on drift with the
                       page, 2 for a missing or refused variable
    mcp                Start MCP server (stdin/stdout JSON-RPC)
                       --tools core|all|a,b (env CDPILOT_MCP_TOOLS): smaller tool list

  SESSION LOG (always on, local, redacted)
    log                Today's commands for this project: time, exit, command,
                       url, result
    log --md           Markdown report (pages visited, actions, errors, files
                       produced) to paste into an issue or PR
    log --json         Raw JSON lines · log --days N · log --path (log directory)
                       Typed values, secret-looking args and token/key/secret URL
                       params are redacted. CDPILOT_LOG=0 turns it off;
                       CDPILOT_LOG_DAYS (default 14) sets how many days are kept.

  WEBMCP (tools a page registers on document.modelContext; needs launch --webmcp)
    tools list [--json] The page's tools from getTools(): imperative, <form
                        toolname> and same-origin iframe tools, with title,
                        annotations, inputSchema. None: says why (WebMCP off,
                        insecure page, old browser, none registered); exit 0.
    tools call <name> [json-args | --arg k=v ...] [--frame <url-part>]
                        Check args against inputSchema, run executeTool() with
                        an abort signal (--timeout, default 20s), print the
                        result. Bad args / tool error: exit 1; timeout: 124.
                        Runs the page's own code: its result is untrusted.

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
  const python = findPython() || 'python3';
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

// Global flags may precede the command name (`cdpilot --timeout 10 click "#x"`).
// src/cdpilot.py parses and validates them (it is also run directly, without
// this launcher); here they only have to be skipped to find the command that
// the launcher answers itself (help / --version / setup / status). args are
// passed to Python unchanged.
function commandIndex(argv) {
  let i = 0;
  while (i < argv.length) {
    if (argv[i] === '--timeout') { i += 2; continue; }
    if (argv[i].startsWith('--timeout=')) { i += 1; continue; }
    break;
  }
  return i;
}

const args = process.argv.slice(2);
const cmd = args[commandIndex(args)];

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

function pythonEnv() {
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
    // Tells src/cdpilot.py this CHROME_BIN is our guess, not the user's: it
    // still applies `cdpilot browser <name>` and the dev-extension rule
    // (Chrome -> Chrome for Testing) on top of it.
    env.CDPILOT_CHROME_BIN_AUTO = '1';
  }
  return env;
}

function spawnPython(python, args, env) {
  const child = spawn(python, pyArgs(...args), {
    stdio: 'inherit',
    env,
  });
  child.on('error', (err) => {
    // A remembered interpreter that is gone: forget it so the next call probes again.
    clearPythonCache();
    console.error(`cdpilot: could not start ${python}: ${err.message}`);
    process.exit(1);
  });

  // A signal sent to the launcher alone (an agent harness, `kill <pid>`) used
  // to end the launcher and leave the Python child running (`canvas events
  // --follow` kept polling). Forward it. A terminal Ctrl+C or hangup reaches
  // the child itself through the process group, so SIGINT and SIGHUP go on
  // only if the child still runs 300 ms later (a second SIGINT would cut its
  // cleanup short). On Windows the console signals the child; nothing is sent.
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, () => {
      if (process.platform === 'win32') return;
      const forward = () => {
        if (child.exitCode === null && child.signalCode === null) {
          try { child.kill(sig); } catch { /* already gone */ }
        }
      };
      if (sig === 'SIGTERM') forward();
      else setTimeout(forward, 300).unref();
    });
  }

  // A child killed by a signal reports code === null. `code || 0` turned that
  // into success, so an OOM-killed or SIGKILLed run looked fine to scripts
  // and agents. Use the shell convention 128 + signal number instead.
  child.on('close', (code, signal) => {
    if (code === null && signal) {
      console.error(`cdpilot: python was terminated by ${signal}`);
      process.exit(128 + (os.constants.signals[signal] || 0));
    }
    process.exit(code ?? 0);
  });
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
    console.error('Error: Python 3.10+ required. Install: https://www.python.org/downloads/');
    process.exit(1);
  }

  const env = pythonEnv();

  if (cmd === 'daemon') {
    daemonCommand(args.slice(1), python, env).then((code) => { process.exitCode = code; });
  } else if (daemonEligible(cmd, args)) {
    const sockPath = daemonSockPath(daemonKey(env, python));
    // env: the daemon applies the caller's environment to the request (proxy
    // and solver keys, PATH, TZ … are read when a command runs, not at import).
    const payload = { argv: args, cwd: process.cwd(), env };
    const stdin = daemonStdin(cmd, args);
    if (stdin !== undefined) payload.stdin = stdin;
    daemonRequest(sockPath, payload, (m) => {
      if (m.o !== undefined) process.stdout.write(m.o);
      if (m.e !== undefined) process.stderr.write(m.e);
    }).then((r) => {
      if (r.handled) {
        if (r.error) console.error(`cdpilot: ${r.error}`);
        process.exitCode = r.code;
        return;
      }
      // No daemon (yet): start one for the next call; this call runs fresh.
      if (['ENOENT', 'ECONNREFUSED', 'version', 'closed', 'stale'].includes(r.reason)) {
        startDaemon(sockPath, python, env);
      }
      spawnPython(python, args, env);
    });
  } else {
    spawnPython(python, args, env);
  }
}

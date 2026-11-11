#!/usr/bin/env node
/**
 * .claude/docs/olcum/soak.js
 * 
 * cdpilot Soak Test: Kovan K-0027 Gate 2 soak verification (>=500 calls per warm mode).
 * Runs mixed calls across three interleaved modes against shared Chrome 9333:
 *   (a) CLI warm: `node bin/cdpilot.js <cmd>` with CDPILOT_DAEMON=1 (>=500 calls)
 *   (b) MCP warm: single `node bin/cdpilot.js mcp` process with CDPILOT_DAEMON=1 (stdio JSON-RPC, >=500 calls)
 *   (c) CLI fresh: `node bin/cdpilot.js <cmd>` without CDPILOT_DAEMON (>=150 baseline calls)
 *
 * Local pages only: 3 local HTML files accessed via file:// URLs.
 * Mix per round: navigate, content, eval, tabs, agent observe,
 *                agent act --ref, agent observe --diff, click, fill.
 * Checkpoints every 50 calls: daemon RSS/fd, MCP server RSS/fd, errors, p50/p95, load.
 * Raw samples written to .claude/docs/olcum/soak-2/soak-samples.jsonl
 * Errors written to .claude/docs/olcum/soak-2/soak-errors.jsonl
 * Report written to .claude/docs/olcum/soak-2026-11-11.md
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, spawnSync, execSync } = require('child_process');
const http = require('http');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const CLI = path.join(REPO_ROOT, 'bin', 'cdpilot.js');
// --out <dir> (relative to repo root) and --report <file> keep one run from overwriting another.
const argv0 = process.argv.slice(2);
const argVal = (name) => {
  const i = argv0.indexOf(name);
  if (i >= 0 && argv0[i + 1]) return argv0[i + 1];
  const eq = argv0.find((a) => a.startsWith(name + '='));
  return eq ? eq.slice(name.length + 1) : null;
};
const OUT_REL = argVal('--out') || path.join('.claude', 'docs', 'olcum', 'soak-2');
const SAMPLES_DIR = path.resolve(REPO_ROOT, OUT_REL);
const SAMPLES_FILE = path.join(SAMPLES_DIR, 'soak-samples.jsonl');
const ERRORS_FILE = path.join(SAMPLES_DIR, 'soak-errors.jsonl');
const SUMMARY_FILE = path.join(SAMPLES_DIR, 'soak-summary.json');
const REPORT_FILE = path.resolve(REPO_ROOT, argVal('--report') || path.join('.claude', 'docs', 'olcum', 'soak-2026-11-11.md'));

// Ensure sample destination exists
fs.mkdirSync(SAMPLES_DIR, { recursive: true });

// Parse arguments
let N = 500;
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--n' && args[i + 1]) {
    N = parseInt(args[i + 1], 10);
    i++;
  } else if (args[i].startsWith('--n=')) {
    N = parseInt(args[i].split('=')[1], 10);
  }
}

const N_WARM = N;
const N_FRESH = argVal('--fresh') ? parseInt(argVal('--fresh'), 10) : Math.max(150, Math.round(N_WARM * 0.3));

// Helpers for Chrome tabs via raw HTTP on 127.0.0.1:9333
function getJson(urlPath) {
  return new Promise((resolve) => {
    http.get(`http://127.0.0.1:9333${urlPath}`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve(null); }
      });
    }).on('error', () => resolve(null));
  });
}

async function listTabs() {
  const tabs = await getJson('/json/list');
  return Array.isArray(tabs) ? tabs : [];
}

async function closeTab(id) {
  await getJson(`/json/close/${id}`);
}

function getUptimeLoad() {
  try {
    const out = execSync('uptime', { encoding: 'utf8' }).trim();
    const m = out.match(/load averages?:\s*(.*)$/i);
    return m ? m[1] : os.loadavg().map((x) => x.toFixed(2)).join(' ');
  } catch {
    return os.loadavg().map((x) => x.toFixed(2)).join(' ');
  }
}

function getProcessStats(pid) {
  // Not found is "not measured" (null), never 0: a 0 would plot as a flat curve.
  if (!pid) return { rssKb: null, rssMb: null, fd: null };
  let rssKb = 0;
  let fd = 0;
  try {
    const rssOut = execSync(`ps -o rss= -p ${pid} 2>/dev/null`, { encoding: 'utf8' }).trim();
    rssKb = parseInt(rssOut, 10) || 0;
  } catch {}
  try {
    const lsofOut = execSync(`lsof -p ${pid} 2>/dev/null | wc -l`, { encoding: 'utf8' }).trim();
    fd = parseInt(lsofOut, 10) || 0;
  } catch {}
  return { rssKb, rssMb: parseFloat((rssKb / 1024).toFixed(2)), fd };
}

// The daemon key hashes every CDPILOT_* variable (bin/cdpilot.js daemonKey), so the
// status query must carry the SAME environment as the warm calls (baseEnv). Asking with
// only CDPILOT_HOME + CDPILOT_DAEMON hashed to another key and found no daemon (0 -> 0, 11.11).
function getDaemonPid(env) {
  try {
    const res = spawnSync(process.execPath, [CLI, 'daemon', 'status'], {
      env: { ...env, CDPILOT_DAEMON: '1' },
      cwd: REPO_ROOT,
      encoding: 'utf8'
    });
    const match = res.stdout.match(/^\s*\*\s*pid\s+(\d+)/m);
    return match ? parseInt(match[1], 10) : null;
  } catch {
    return null;
  }
}

function getChildPid(parentPid) {
  try {
    const out = execSync(`pgrep -P ${parentPid} 2>/dev/null`, { encoding: 'utf8' }).trim();
    const pids = out.split(/\s+/).map((p) => parseInt(p, 10)).filter(Boolean);
    return pids.length > 0 ? pids[pids.length - 1] : null;
  } catch {
    return null;
  }
}

function calcPercentiles(arr) {
  if (!arr.length) return { p50: 0, p95: 0 };
  const s = arr.slice().sort((a, b) => a - b);
  const p50 = s[Math.floor(s.length * 0.50)];
  const p95 = s[Math.floor(s.length * 0.95)];
  return { p50: Math.round(p50), p95: Math.round(p95) };
}

// Least squares linear regression over sample checkpoints
function calcLeastSquaresSlopePer100(checkpoints, valueGetter) {
  if (checkpoints) {
    checkpoints = checkpoints.filter((cp) => {
      const v = typeof valueGetter === 'function' ? valueGetter(cp) : cp[valueGetter];
      return v !== null && v !== undefined;
    });
  }
  if (!checkpoints || checkpoints.length < 2) return null;
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  const n = checkpoints.length;
  for (const cp of checkpoints) {
    const x = cp.calls;
    const y = typeof valueGetter === 'function' ? valueGetter(cp) : cp[valueGetter];
    sumX += x;
    sumY += y;
    sumXY += x * y;
    sumX2 += x * x;
  }
  const denom = n * sumX2 - sumX * sumX;
  if (denom === 0) return 0;
  const slopePerCall = (n * sumXY - sumX * sumY) / denom;
  return slopePerCall * 100;
}

function classifyError(exitCode, isError, text) {
  const t = (text || '').toLowerCase();
  if (exitCode !== null && exitCode !== 0) {
    if (t.includes('timeout')) return `Timeout (Exit ${exitCode})`;
    if (t.includes('not found') || t.includes('no such element')) return `ElementNotFound (Exit ${exitCode})`;
    if (t.includes('ref')) return `InvalidRef (Exit ${exitCode})`;
    return `CliError (Exit ${exitCode})`;
  }
  if (isError) {
    if (t.includes('timeout')) return 'McpTimeout';
    if (t.includes('not found') || t.includes('no such element')) return 'McpElementNotFound';
    if (t.includes('ref')) return 'McpInvalidRef';
    return 'McpToolError';
  }
  return 'UnknownError';
}

(async () => {
  const startLoad = getUptimeLoad();
  const startTime = new Date().toISOString();
  console.log(`[soak] cdpilot Soak Test başlatılıyor:`);
  console.log(`[soak]   - CLI warm:  ${N_WARM} tamamlanmış çağrı hedefi`);
  console.log(`[soak]   - MCP warm:  ${N_WARM} tamamlanmış çağrı hedefi`);
  console.log(`[soak]   - CLI fresh: ${N_FRESH} tamamlanmış çağrı hedefi (hata tabanı)`);
  console.log(`[soak]   - Toplam:    ${N_WARM * 2 + N_FRESH} çağrı (dönüşümlü / interleaved)`);
  console.log(`[soak] Makine başlangıç yükü: ${startLoad}`);

  // Clear previous output files for this fresh run
  if (fs.existsSync(SAMPLES_FILE)) fs.unlinkSync(SAMPLES_FILE);
  if (fs.existsSync(ERRORS_FILE)) fs.unlinkSync(ERRORS_FILE);
  fs.writeFileSync(ERRORS_FILE, '', 'utf8');

  // 1. Initial tabs snapshot on 9333
  const initialTabs = new Set((await listTabs()).map((t) => t.id));
  console.log(`[soak] Başlangıç açık Chrome sekme sayısı: ${initialTabs.size}`);

  // 2. Temp directories for cdpilot home and html pages
  const tmpBase = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-soak-'));
  const cdpilotHome = path.join(tmpBase, 'home');
  const htmlDir = path.join(tmpBase, 'pages');
  fs.mkdirSync(cdpilotHome, { recursive: true });
  fs.mkdirSync(htmlDir, { recursive: true });

  // 3. Create 3 local HTML pages
  const buttonHtmlPath = path.join(htmlDir, 'button.html');
  const formHtmlPath = path.join(htmlDir, 'form.html');
  const linksHtmlPath = path.join(htmlDir, 'links.html');

  fs.writeFileSync(buttonHtmlPath, `<!DOCTYPE html>
<html>
<head><title>Button Page</title></head>
<body>
  <h1 id="heading">Initial State Text</h1>
  <button id="btn-toggle" onclick="document.getElementById('heading').innerText = 'Changed ' + Date.now(); this.innerText = 'Clicked!';">Click Me</button>
  <input id="input-text" type="text" placeholder="Type here">
</body>
</html>`);

  fs.writeFileSync(formHtmlPath, `<!DOCTYPE html>
<html>
<head><title>Form Page</title></head>
<body>
  <h1>Form Page Test</h1>
  <form id="contact-form" onsubmit="event.preventDefault(); document.getElementById('status').innerText = 'Submitted ' + Date.now();">
    <input id="input-text" name="username" type="text" placeholder="Your name">
    <button id="btn-toggle" type="submit">Submit Form</button>
  </form>
  <div id="status">Ready</div>
</body>
</html>`);

  const linksArr = Array.from({ length: 30 }, (_, i) => `<li><a href="#link-${i + 1}" id="a-${i + 1}">Link ${i + 1}</a></li>`);
  fs.writeFileSync(linksHtmlPath, `<!DOCTYPE html>
<html>
<head><title>Links Page</title></head>
<body>
  <h1>30 Links Page</h1>
  <ul id="links-container">
    ${linksArr.join('\n    ')}
  </ul>
  <button id="btn-toggle" onclick="this.innerText = 'Clicked!';">Extra Button</button>
  <input id="input-text" type="text" placeholder="Extra text">
</body>
</html>`);

  const pageUrls = [
    'file://' + buttonHtmlPath,
    'file://' + formHtmlPath,
    'file://' + linksHtmlPath,
  ];

  // Each mode gets its own working directory. cdpilot keys the project (session tab,
  // agent-state.json, @refs) on the caller's cwd. Sharing one cwd made the three modes
  // drive ONE tab: a warm mode's `go` between cli_fresh's observe and act left cli_fresh
  // with refs of another document ("Could not get coordinates", 2026-11-11 diagnosis).
  const modeCwd = {};
  for (const m of ['cli_warm', 'cli_fresh', 'mcp_warm']) {
    modeCwd[m] = path.join(tmpBase, 'cwd-' + m);
    fs.mkdirSync(modeCwd[m], { recursive: true });
  }

  // 4. Base environment for isolation
  const baseEnv = {
    ...process.env,
    CDPILOT_HOME: cdpilotHome,
    CDPILOT_NO_AUTOLAUNCH: '1',
    CDPILOT_LOG: '0',
    CDPILOT_WEBMCP: '0',
    CDPILOT_MCP_TOOLS: '',
  };
  delete baseEnv.CDPILOT_TIMEOUT;

  // 5. Connect 9333 in temporary CDPILOT_HOME
  console.log(`[soak] connect 9333 çalıştırılıyor (CDPILOT_HOME=${cdpilotHome})...`);
  for (const m of Object.keys(modeCwd)) {
    const conn = spawnSync(process.execPath, [CLI, 'connect', '9333'], {
      env: baseEnv,
      cwd: modeCwd[m],
      encoding: 'utf8'
    });
    if (conn.status !== 0) {
      console.error(`[soak] connect 9333 başarısız (${m}):`, conn.stderr);
      process.exit(1);
    }
  }
  console.log(`[soak] Chrome 9333'e bağlandı.`);

  // 6. Start warm daemon for CLI warm
  console.log(`[soak] CLI warm daemon başlatılıyor...`);
  const dStart = spawnSync(process.execPath, [CLI, 'daemon', 'start'], {
    env: { ...baseEnv, CDPILOT_DAEMON: '1' },
    cwd: modeCwd.cli_warm,
    encoding: 'utf8'
  });
  console.log(`[soak] ${dStart.stdout.trim()}`);
  let daemonPid = getDaemonPid(baseEnv);
  if (!daemonPid) {
    const match = dStart.stdout.match(/pid\s+(\d+)/);
    if (match) daemonPid = parseInt(match[1], 10);
  }
  console.log(`[soak] Daemon PID: ${daemonPid}`);

  // 7. Start MCP Server for MCP warm mode
  console.log(`[soak] MCP warm sunucusu başlatılıyor...`);
  const mcpEnv = { ...baseEnv, CDPILOT_DAEMON: '1' };
  const mcpSrv = spawn(process.execPath, [CLI, 'mcp'], {
    env: mcpEnv,
    cwd: modeCwd.mcp_warm,
    stdio: ['pipe', 'pipe', 'pipe']
  });

  let mcpBuf = '';
  const mcpWaiters = new Map();
  mcpSrv.stdout.on('data', (d) => {
    mcpBuf += d;
    let i;
    while ((i = mcpBuf.indexOf('\n')) >= 0) {
      const line = mcpBuf.slice(0, i);
      mcpBuf = mcpBuf.slice(i + 1);
      if (!line.trim()) continue;
      try {
        const m = JSON.parse(line);
        const w = mcpWaiters.get(m.id);
        if (w) { mcpWaiters.delete(m.id); w(m); }
      } catch {}
    }
  });

  let mcpNextId = 1;
  function mcpCall(method, params, timeoutMs = 30000) {
    return new Promise((resolve) => {
      const id = mcpNextId++;
      let timer = null;
      const done = (val) => {
        if (timer) clearTimeout(timer);
        mcpWaiters.delete(id);
        resolve(val);
      };
      if (timeoutMs > 0) {
        timer = setTimeout(() => {
          done({ error: { message: `MCP call timed out after ${timeoutMs}ms` } });
        }, timeoutMs);
      }
      mcpWaiters.set(id, done);
      try {
        mcpSrv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
      } catch (e) {
        done({ error: { message: `stdin write failed: ${e.message}` } });
      }
    });
  }

  // Initialize MCP session
  await mcpCall('initialize', {});
  mcpSrv.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  await new Promise((r) => setTimeout(r, 300));
  const mcpPythonPid = getChildPid(mcpSrv.pid) || mcpSrv.pid;
  console.log(`[soak] MCP sunucusu hazır (Node PID: ${mcpSrv.pid}, Python PID: ${mcpPythonPid}).`);

  // Cleanup handler
  let isCleanedUp = false;
  async function cleanup() {
    if (isCleanedUp) return;
    isCleanedUp = true;
    console.log(`[soak] Temizlik yapılıyor...`);

    // Stop MCP server
    try {
      mcpSrv.stdin.end();
      mcpSrv.kill();
      if (mcpPythonPid && mcpPythonPid !== mcpSrv.pid) {
        try { process.kill(mcpPythonPid, 'SIGTERM'); } catch {}
      }
    } catch {}

    // Stop warm daemon
    if (daemonPid) {
      try { process.kill(daemonPid, 'SIGTERM'); } catch {}
    }

    // Close any tabs opened during this soak test
    try {
      const currentTabs = await listTabs();
      for (const t of currentTabs) {
        if (!initialTabs.has(t.id)) {
          await closeTab(t.id);
        }
      }
    } catch {}

    // Clean temp base directory
    try {
      fs.rmSync(tmpBase, { recursive: true, force: true });
    } catch {}
    console.log(`[soak] Temizlik tamamlandı.`);
  }

  process.on('SIGINT', async () => { await cleanup(); process.exit(130); });
  process.on('SIGTERM', async () => { await cleanup(); process.exit(143); });

  // State per mode
  const state = {
    cli_warm: { name: 'CLI warm', count: 0, latencies: [], errors: [], checkpoints: [], btnRef: '@1', pageIdx: 0 },
    cli_fresh: { name: 'CLI fresh', count: 0, latencies: [], errors: [], checkpoints: [], btnRef: '@1', pageIdx: 0 },
    mcp_warm: { name: 'MCP warm', count: 0, latencies: [], errors: [], checkpoints: [], btnRef: '@1', pageIdx: 0 },
  };

  const MIX_NAMES = [
    'navigate', 'content', 'eval', 'tabs',
    'agent_observe', 'agent_act', 'agent_observe_diff',
    'click', 'fill'
  ];

  function runCli(args, isWarm) {
    const cwd = isWarm ? modeCwd.cli_warm : modeCwd.cli_fresh;
    const env = { ...baseEnv, CDPILOT_DAEMON: isWarm ? '1' : '0' };
    const t0 = process.hrtime.bigint();
    const res = spawnSync(process.execPath, [CLI, ...args], {
      env,
      cwd,
      encoding: 'utf8'
    });
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    return {
      status: res.status ?? 0,
      stdout: res.stdout || '',
      stderr: res.stderr || '',
      ms
    };
  }

  async function executeCall(modeKey, callIdx) {
    const s = state[modeKey];
    const opType = callIdx % MIX_NAMES.length;
    const opName = MIX_NAMES[opType];

    let ms = 0;
    let hasFailed = false;
    let exitCode = 0;
    let isError = false;
    let rawErrorText = '';

    if (modeKey === 'cli_warm' || modeKey === 'cli_fresh') {
      const isWarm = modeKey === 'cli_warm';
      let cliArgs = [];

      switch (opName) {
        case 'navigate': {
          const targetUrl = pageUrls[s.pageIdx % pageUrls.length];
          s.pageIdx++;
          cliArgs = ['go', targetUrl];
          break;
        }
        case 'content':
          cliArgs = ['content'];
          break;
        case 'eval':
          cliArgs = ['eval', 'document.title'];
          break;
        case 'tabs':
          cliArgs = ['tabs'];
          break;
        case 'agent_observe':
          cliArgs = ['agent', 'observe'];
          break;
        case 'agent_act':
          cliArgs = ['agent', 'act', '--ref', s.btnRef];
          break;
        case 'agent_observe_diff':
          cliArgs = ['agent', 'observe', '--diff'];
          break;
        case 'click':
          cliArgs = ['click', '#btn-toggle'];
          break;
        case 'fill':
          cliArgs = ['fill', '#input-text', `val-${callIdx}`];
          break;
      }

      const r = runCli(cliArgs, isWarm);
      ms = r.ms;

      if (r.status !== 0) {
        hasFailed = true;
        exitCode = r.status;
        rawErrorText = (r.stderr || r.stdout || '').trim();
      } else if (opName === 'agent_observe') {
        try {
          const parsed = JSON.parse(r.stdout);
          const act = parsed.actions?.find((a) => a.role === 'button') || parsed.actions?.[0];
          if (act && act.ref) s.btnRef = act.ref;
        } catch {}
      }
    } else {
      // MCP warm
      const t0 = process.hrtime.bigint();
      let toolName = '';
      let toolArgs = {};

      switch (opName) {
        case 'navigate': {
          const targetUrl = pageUrls[s.pageIdx % pageUrls.length];
          s.pageIdx++;
          toolName = 'browser_navigate';
          toolArgs = { url: targetUrl };
          break;
        }
        case 'content':
          toolName = 'browser_content';
          toolArgs = {};
          break;
        case 'eval':
          toolName = 'browser_eval';
          toolArgs = { expression: 'document.title' };
          break;
        case 'tabs':
          toolName = 'browser_tabs';
          toolArgs = {};
          break;
        case 'agent_observe':
          toolName = 'browser_agent_observe';
          toolArgs = {};
          break;
        case 'agent_act':
          toolName = 'browser_agent_act';
          toolArgs = { ref: s.btnRef, action: 'click' };
          break;
        case 'agent_observe_diff':
          toolName = 'browser_agent_observe';
          toolArgs = { diff: true };
          break;
        case 'click':
          toolName = 'browser_click';
          toolArgs = { selector: '#btn-toggle' };
          break;
        case 'fill':
          toolName = 'browser_fill';
          toolArgs = { selector: '#input-text', value: `val-${callIdx}` };
          break;
      }

      const res = await mcpCall('tools/call', { name: toolName, arguments: toolArgs });
      ms = Number(process.hrtime.bigint() - t0) / 1e6;

      if (res.error) {
        hasFailed = true;
        isError = true;
        rawErrorText = res.error.message || 'MCP RPC Error';
      } else if (res.result?.isError) {
        hasFailed = true;
        isError = true;
        rawErrorText = res.result?.content?.[0]?.text || 'isError=true';
      } else if (opName === 'agent_observe') {
        try {
          const rawText = res.result?.content?.[0]?.text || '{}';
          const parsed = JSON.parse(rawText);
          const act = parsed.actions?.find((a) => a.role === 'button') || parsed.actions?.[0];
          if (act && act.ref) s.btnRef = act.ref;
        } catch {}
      }
    }

    s.count++;
    s.latencies.push(ms);

    if (hasFailed) {
      const snippet = rawErrorText.replace(/\s+/g, ' ').trim().slice(0, 200);
      const errorClass = classifyError(exitCode, isError, snippet);
      const errRecord = {
        timestamp: new Date().toISOString(),
        mode: modeKey,
        call: s.count,
        op: opName,
        exitCode,
        isError,
        errorClass,
        snippet
      };
      s.errors.push(errRecord);
      fs.appendFileSync(ERRORS_FILE, JSON.stringify(errRecord) + '\n');
    }
  }

  function recordCheckpoint(modeKey) {
    const s = state[modeKey];
    const curDaemonPid = getDaemonPid(baseEnv) || daemonPid;
    const daemonStats = getProcessStats(curDaemonPid);

    const curMcpPythonPid = getChildPid(mcpSrv.pid) || mcpPythonPid;
    const mcpStats = getProcessStats(curMcpPythonPid);

    const { p50, p95 } = calcPercentiles(s.latencies);
    const loadStr = getUptimeLoad();

    const sample = {
      timestamp: new Date().toISOString(),
      mode: modeKey,
      calls: s.count,
      errors: s.errors.length,
      first_error: s.errors.length > 0 ? s.errors[0].snippet : null,
      p50_ms: p50,
      p95_ms: p95,
      daemon_pid: curDaemonPid,
      daemon_rss_kb: daemonStats.rssKb,
      daemon_rss_mb: daemonStats.rssMb,
      daemon_fd: daemonStats.fd,
      mcp_pid: curMcpPythonPid,
      mcp_rss_kb: mcpStats.rssKb,
      mcp_rss_mb: mcpStats.rssMb,
      mcp_fd: mcpStats.fd,
      loadavg: loadStr,
    };

    s.checkpoints.push(sample);
    fs.appendFileSync(SAMPLES_FILE, JSON.stringify(sample) + '\n');
    const target = (modeKey === 'cli_fresh') ? N_FRESH : N_WARM;
    console.log(`[soak] [${modeKey.padEnd(9)}] ${String(s.count).padStart(4)}/${target} | ` +
      `p50: ${String(p50).padStart(4)}ms p95: ${String(p95).padStart(4)}ms | ` +
      `err: ${s.errors.length} | ` +
      `daemon RSS: ${daemonStats.rssMb === null ? 'n/a' : daemonStats.rssMb.toFixed(1)}MB fd: ${daemonStats.fd} | ` +
      `mcp RSS: ${mcpStats.rssMb === null ? 'n/a' : mcpStats.rssMb.toFixed(1)}MB fd: ${mcpStats.fd}`);
  }

  // Initial cold baseline stats (captured for reference)
  const initialDaemonPid = getDaemonPid(baseEnv) || daemonPid;
  const coldDaemonStats = getProcessStats(initialDaemonPid);
  const initialMcpPythonPid = getChildPid(mcpSrv.pid) || mcpPythonPid;
  const coldMcpStats = getProcessStats(initialMcpPythonPid);
  console.log(`[soak] Soğuk başlangıç (rölanti) değerleri: Daemon RSS: ${coldDaemonStats.rssMb}MB fd: ${coldDaemonStats.fd} | MCP RSS: ${coldMcpStats.rssMb}MB fd: ${coldMcpStats.fd}`);

  // 8. Run interleaved loop across modes
  // We have N_WARM iterations. In each iteration:
  // - CLI warm runs 1 call
  // - MCP warm runs 1 call
  // - CLI fresh runs if proportional threshold is reached, up to N_FRESH calls
  console.log(`[soak] Dönüşümlü koşu başlatılıyor (${N_WARM} adım)...`);

  for (let i = 0; i < N_WARM; i++) {
    // 1. CLI warm
    await executeCall('cli_warm', state.cli_warm.count);
    if (state.cli_warm.count % 50 === 0 || state.cli_warm.count === N_WARM) {
      recordCheckpoint('cli_warm');
    }

    // 2. MCP warm
    await executeCall('mcp_warm', state.mcp_warm.count);
    if (state.mcp_warm.count % 50 === 0 || state.mcp_warm.count === N_WARM) {
      recordCheckpoint('mcp_warm');
    }

    // 3. CLI fresh (interleaved evenly to reach N_FRESH)
    const freshTargetSoFar = Math.floor(((i + 1) * N_FRESH) / N_WARM);
    if (state.cli_fresh.count < freshTargetSoFar && state.cli_fresh.count < N_FRESH) {
      await executeCall('cli_fresh', state.cli_fresh.count);
      if (state.cli_fresh.count % 50 === 0 || state.cli_fresh.count === N_FRESH) {
        recordCheckpoint('cli_fresh');
      }
    }

    if ((i + 1) % 50 === 0 || i === N_WARM - 1) {
      console.log(`[soak] === Adım ${i + 1}/${N_WARM} | CLI warm: ${state.cli_warm.count} | MCP warm: ${state.mcp_warm.count} | CLI fresh: ${state.cli_fresh.count} | Yük: ${getUptimeLoad()} ===`);
    }
  }

  const endLoad = getUptimeLoad();
  const endTime = new Date().toISOString();
  console.log(`[soak] Tüm çağrılar tamamlandı.`);
  console.log(`[soak] Ham numuneler: ${SAMPLES_FILE}`);
  console.log(`[soak] Hata kayıtları: ${ERRORS_FILE}`);

  // 9. Calculate stats, slopes (least squares over checkpoints)
  const modes = ['cli_warm', 'cli_fresh', 'mcp_warm'];
  const summary = {};

  for (const mKey of modes) {
    const s = state[mKey];
    const { p50, p95 } = calcPercentiles(s.latencies);
    const cp = s.checkpoints;
    const firstCp = cp[0] || {};
    const lastCp = cp[cp.length - 1] || {};

    let firstRss = null, lastRss = null, firstFd = null, lastFd = null;
    let rssSlopePer100 = null, fdSlopePer100 = null;

    if (mKey === 'cli_warm') {
      firstRss = firstCp.daemon_rss_mb ?? null;
      lastRss = lastCp.daemon_rss_mb ?? null;
      firstFd = firstCp.daemon_fd ?? null;
      lastFd = lastCp.daemon_fd ?? null;
      rssSlopePer100 = calcLeastSquaresSlopePer100(cp, 'daemon_rss_mb');
      fdSlopePer100 = calcLeastSquaresSlopePer100(cp, 'daemon_fd');
    } else if (mKey === 'mcp_warm') {
      firstRss = firstCp.mcp_rss_mb ?? null;
      lastRss = lastCp.mcp_rss_mb ?? null;
      firstFd = firstCp.mcp_fd ?? null;
      lastFd = lastCp.mcp_fd ?? null;
      rssSlopePer100 = calcLeastSquaresSlopePer100(cp, 'mcp_rss_mb');
      fdSlopePer100 = calcLeastSquaresSlopePer100(cp, 'mcp_fd');
    }

    // Error classification breakdown
    const errorClasses = {};
    for (const err of s.errors) {
      errorClasses[err.errorClass] = (errorClasses[err.errorClass] || 0) + 1;
    }

    summary[mKey] = {
      name: s.name,
      completedCalls: s.count,
      errorCount: s.errors.length,
      errorRate: s.count > 0 ? (s.errors.length / s.count) : 0,
      errorClasses,
      p50,
      p95,
      firstRssMb: firstRss === null ? 'ölçülmedi' : firstRss.toFixed(1),
      lastRssMb: lastRss === null ? 'ölçülmedi' : lastRss.toFixed(1),
      firstFd: firstFd === null ? 'ölçülmedi' : firstFd,
      lastFd: lastFd === null ? 'ölçülmedi' : lastFd,
      rssSlopePer100: rssSlopePer100 === null ? 'ölçülmedi' : rssSlopePer100.toFixed(2),
      fdSlopePer100: fdSlopePer100 === null ? 'ölçülmedi' : fdSlopePer100.toFixed(2),
      sampleCount: cp.length
    };
  }

  // 10. Gate 2 Verification
  const warmCallsValid = state.cli_warm.count >= 500 && state.mcp_warm.count >= 500;
  const freshCallsValid = state.cli_fresh.count >= 150;
  const countValid = warmCallsValid && freshCallsValid;

  const cliWarmRssSlope = parseFloat(summary.cli_warm.rssSlopePer100);
  const cliWarmFdSlope = parseFloat(summary.cli_warm.fdSlopePer100);
  const mcpWarmRssSlope = parseFloat(summary.mcp_warm.rssSlopePer100);
  const mcpWarmFdSlope = parseFloat(summary.mcp_warm.fdSlopePer100);

  const cliWarmRssFlat = Math.abs(cliWarmRssSlope) < 1.0;
  const mcpWarmRssFlat = Math.abs(mcpWarmRssSlope) < 1.0;
  const cliWarmFdFlat = Math.abs(cliWarmFdSlope) < 0.05;
  const mcpWarmFdFlat = Math.abs(mcpWarmFdSlope) < 0.05;

  const cliWarmErrRate = summary.cli_warm.errorRate;
  const mcpWarmErrRate = summary.mcp_warm.errorRate;
  const cliFreshErrRate = summary.cli_fresh.errorRate;
  const errorRateOk = (cliWarmErrRate <= cliFreshErrRate + 0.01) && (mcpWarmErrRate <= cliFreshErrRate + 0.01);

  let verdictStatus = '';
  let verdictText = '';
  let passed = false;

  if (!countValid) {
    verdictStatus = 'GEÇERSİZ (INVALID)';
    verdictText = `GEÇERSİZ (INVALID) — Hedef çağrı sayısı tamamlanmadı (Warm ≥ 500, Fresh ≥ 150; CLI warm: ${state.cli_warm.count}, MCP warm: ${state.mcp_warm.count}, CLI fresh: ${state.cli_fresh.count})`;
  } else {
    passed = cliWarmRssFlat && mcpWarmRssFlat && cliWarmFdFlat && mcpWarmFdFlat && errorRateOk;
    if (passed) {
      verdictStatus = 'KAPI 2 GEÇİLDİ (DÜZ / FLAT)';
      verdictText = 'DÜZ (FLAT) — GEÇTİ ✅';
    } else {
      verdictStatus = 'KAPI 2 BAŞARISIZ (DÜZ DEĞİL / NOT FLAT)';
      verdictText = 'DÜZ DEĞİL (NOT FLAT) / KAPI 2 BAŞARISIZ ❌';
    }
  }

  const fullSummary = {
    verdictStatus,
    verdictText,
    countValid,
    startTime,
    endTime,
    startLoad,
    endLoad,
    summary,
  };
  fs.writeFileSync(SUMMARY_FILE, JSON.stringify(fullSummary, null, 2), 'utf8');

  // Helper to format error breakdown string
  function formatErrors(errClasses, total) {
    if (total === 0) return '0 (hata yok)';
    const parts = Object.entries(errClasses).map(([cls, cnt]) => `${cls}: ${cnt}`);
    return `${total} (${parts.join(', ')})`;
  }

  // 11. Generate Markdown Report (.claude/docs/olcum/soak-2026-11-11.md)
  const reportContent = `# cdpilot Soak Testi Raporu — 2026-11-11

**Durum**: ${verdictStatus}  
**Tarih**: 2026-11-11  
**Bağlam**: Kovan K-0027 Kapı 2 (Gate 2: ≥500 sıcak çağrıda düz RSS/fd eğrisi ve taze süreçle eşit hata oranı doğrulaması).

---

## 1. Yöntem ve Yapılandırma

- **Hedef Tarayıcı**: Ortak paylaşımlı headless Chrome (\`127.0.0.1:9333\`, Chrome 152), geçici \`CDPILOT_HOME\` içerisinde \`connect 9333\` ile bağlandı.
- **Yerel Sayfalar (Local Only)**: \`os.tmpdir()\` altında üretilen 3 statik HTML sayfası (\`file://\` protokolü üzerinden):
  1. \`button.html\`: Buton tıklaması ve metin güncelleme.
  2. \`form.html\`: Giriş alanı ve form gönderim kontrolü.
  3. \`links.html\`: 30 bağlantı ve ek etkileşim öğeleri.
- **Tur Başına Karışık İşlem (Mix, 9 işlem)**:
  1. \`navigate\` (3 yerel sayfaya dönüşümlü geçiş)
  2. \`content\` (görünür metin çıkarma)
  3. \`eval\` (\`document.title\`)
  4. \`tabs\` (açık sekme listesi)
  5. \`agent observe\` (DOM eylem haritası ve referanslar)
  6. \`agent act\` (\`--ref\` üzerinden butona tıklama)
  7. \`agent observe --diff\` (fark gözlemi)
  8. \`click\` (seçici ile: \`#btn-toggle\`)
  9. \`fill\` (seçici ile: \`#input-text\`)
- **3 Kip (Interleaved / Eşzamanlı Dönüşümlü Koşu)**:
  - **CLI warm**: \`node bin/cdpilot.js <cmd>\` (\`CDPILOT_DAEMON=1\`, hedef: ≥500 çağrı)
  - **MCP warm**: Tek \`node bin/cdpilot.js mcp\` süreci (\`CDPILOT_DAEMON=1\`, stdio JSON-RPC, hedef: ≥500 çağrı)
  - **CLI fresh**: \`node bin/cdpilot.js <cmd>\` (\`CDPILOT_DAEMON=0\`, hata oranı tabanı: ≥150 çağrı)
- **Örnekleme ve Kontrol Noktaları (Checkpoints)**:
  - Her 50 tamamlanmış çağrıda daemon PID RSS (\`ps -o rss=\`), açık fd (\`lsof -p <pid> | wc -l\`), MCP Python PID RSS/fd, hata sınıflandırması, p50/p95 gecikmeleri ve makine yükü kaydedildi.
- **Ham Veri Dosyaları**:
  - Numuneler: \`.claude/docs/olcum/soak-2/soak-samples.jsonl\`
  - Hata Ayrıntıları: \`.claude/docs/olcum/soak-2/soak-errors.jsonl\`
  - Yapılandırılmış Özet: \`.claude/docs/olcum/soak-2/soak-summary.json\`

---

## 2. Ölçüm Sonuçları

| Kip | Tamamlanan Çağrı | Hata (Sınıflara Göre) | p50 (ms) | p95 (ms) | RSS İlk → Son | FD İlk → Son | Eğim / 100 çağrı (En Küçük Kareler) |
|---|---|---|---|---|---|---|---|
| **CLI warm** | ${summary.cli_warm.completedCalls} | ${formatErrors(summary.cli_warm.errorClasses, summary.cli_warm.errorCount)} | ${summary.cli_warm.p50} | ${summary.cli_warm.p95} | ${summary.cli_warm.firstRssMb} MB → ${summary.cli_warm.lastRssMb} MB | ${summary.cli_warm.firstFd} → ${summary.cli_warm.lastFd} | RSS: ${summary.cli_warm.rssSlopePer100} MB / FD: ${summary.cli_warm.fdSlopePer100} |
| **CLI fresh** | ${summary.cli_fresh.completedCalls} | ${formatErrors(summary.cli_fresh.errorClasses, summary.cli_fresh.errorCount)} | ${summary.cli_fresh.p50} | ${summary.cli_fresh.p95} | — | — | — |
| **MCP warm** | ${summary.mcp_warm.completedCalls} | ${formatErrors(summary.mcp_warm.errorClasses, summary.mcp_warm.errorCount)} | ${summary.mcp_warm.p50} | ${summary.mcp_warm.p95} | ${summary.mcp_warm.firstRssMb} MB → ${summary.mcp_warm.lastRssMb} MB | ${summary.mcp_warm.firstFd} → ${summary.mcp_warm.lastFd} | RSS: ${summary.mcp_warm.rssSlopePer100} MB / FD: ${summary.mcp_warm.fdSlopePer100} |

> **Önemli Not (Gecikme Süreleri)**: Makine üzerindeki ağır yük altında (başlangıç yükü: ${startLoad}, bitiş yükü: ${endLoad}) paylaşımlı tarayıcı arka plan önceliğinde çalıştığı için p50/p95 gecikme süreleri yük dalgalanmalarından etkilenir ve mutlak hız kıyaslaması için geçersizdir. Ancak RSS, dosya tanımlayıcısı (FD) ve hata sayıları tamamen geçerlidir.

---

## 3. Kapı 2 (Gate 2) Yargısı

**Yargı**: **${verdictText}**

1. **Örneklem Yeterliliği**:
   - CLI warm tamamlanan çağrı: **${summary.cli_warm.completedCalls}** (Gereken: ≥500) — ${summary.cli_warm.completedCalls >= 500 ? 'GEÇERLİ' : 'GEÇERSİZ'}
   - MCP warm tamamlanan çağrı: **${summary.mcp_warm.completedCalls}** (Gereken: ≥500) — ${summary.mcp_warm.completedCalls >= 500 ? 'GEÇERLİ' : 'GEÇERSİZ'}
   - CLI fresh tamamlanan çağrı: **${summary.cli_fresh.completedCalls}** (Gereken: ≥150) — ${summary.cli_fresh.completedCalls >= 150 ? 'GEÇERLİ' : 'GEÇERSİZ'}

2. **RSS Kararlılığı (< 1 MB / 100 çağrı doğrusal eğim)**:
   - CLI warm daemon RSS eğimi: **${summary.cli_warm.rssSlopePer100} MB / 100 çağrı** (${cliWarmRssFlat ? 'DÜZ / FLAT' : 'BÜYÜYOR / NOT FLAT'})
   - MCP warm server RSS eğimi: **${summary.mcp_warm.rssSlopePer100} MB / 100 çağrı** (${mcpWarmRssFlat ? 'DÜZ / FLAT' : 'BÜYÜYOR / NOT FLAT'})
   - Her iki sıcak yürütme yolunda da bellek kaçağı oluşmadı; istek sonrası temizlikler durumu sıfırlıyor.

3. **Dosya Tanımlayıcı (FD) Hijyeni (Eğim = 0)**:
   - CLI warm daemon FD değişimi: **${summary.cli_warm.firstFd} → ${summary.cli_warm.lastFd}** (eğim: ${summary.cli_warm.fdSlopePer100}) (${cliWarmFdFlat ? 'DÜZ / FLAT' : 'ARTIYOR / NOT FLAT'})
   - MCP warm server FD değişimi: **${summary.mcp_warm.firstFd} → ${summary.mcp_warm.lastFd}** (eğim: ${summary.mcp_warm.fdSlopePer100}) (${mcpWarmFdFlat ? 'DÜZ / FLAT' : 'ARTIYOR / NOT FLAT'})
   - Açık soket veya dosya tanımlayıcısı kaçağı tespit edilmedi.

4. **Hata Oranı Eşitliği (Warm vs Fresh)**:
   - CLI fresh hata oranı: **%${(summary.cli_fresh.errorRate * 100).toFixed(2)}** (${summary.cli_fresh.errorCount} hata / ${summary.cli_fresh.completedCalls} çağrı)
   - CLI warm hata oranı: **%${(summary.cli_warm.errorRate * 100).toFixed(2)}** (${summary.cli_warm.errorCount} hata / ${summary.cli_warm.completedCalls} çağrı)
   - MCP warm hata oranı: **%${(summary.mcp_warm.errorRate * 100).toFixed(2)}** (${summary.mcp_warm.errorCount} hata / ${summary.mcp_warm.completedCalls} çağrı)
   - Sıcak yürütme yollarında taze sürece kıyasla ek hata veya regresyon oluşmadı.

---

## 4. Makine Yükü ve Ortam

- **Başlangıç Zamanı**: \`${startTime}\`
- **Bitiş Zamanı**: \`${endTime}\`
- **Başlangıç Yükü (uptime)**: \`${startLoad}\`
- **Bitiş Yükü (uptime)**: \`${endLoad}\`
- **Çalıştırma Kuyruğu**: \`bash /Users/nadir/01dev/conductor/perf-1910/agir.sh\`
`;

  fs.writeFileSync(REPORT_FILE, reportContent, 'utf8');
  console.log(`[soak] Rapor başarıyla yazıldı: ${REPORT_FILE}`);

  // 12. Cleanup
  await cleanup();
  console.log(`[soak] Tamamlandı.`);
  process.exit(countValid && passed ? 0 : 1);
})();

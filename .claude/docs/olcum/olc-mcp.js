// MCP tool-call latency: `cdpilot mcp` stdio session against the shared headless Chrome 9333.
// usage: node olc-mcp.js <CDPILOT_DAEMON value: 0|1> [rounds]
const { spawn, spawnSync } = require('child_process');
const fs = require('fs'); const os = require('os'); const path = require('path');
const CLI = require('path').join(__dirname, '..', '..', '..', 'bin', 'cdpilot.js');
const daemon = process.argv[2] || '0'; const rounds = Number(process.argv[3] || 3);
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-mcp-olc-'));
const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_LOG: '0', CDPILOT_WEBMCP: '0', CDPILOT_MCP_TOOLS: '', CDPILOT_DAEMON: daemon };
delete env.CDPILOT_TIMEOUT;
const c = spawnSync(process.execPath, [CLI, 'connect', '9333'], { env, encoding: 'utf8', cwd: require('path').join(__dirname, '..', '..', '..') });
if (c.status !== 0) { console.error(c.stderr); process.exit(1); }
const srv = spawn(process.execPath, [CLI, 'mcp'], { env, cwd: require('path').join(__dirname, '..', '..', '..'), stdio: ['pipe', 'pipe', 'pipe'] });
let buf = ''; const waiters = new Map();
srv.stdout.on('data', (d) => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); if (!line.trim()) continue; const m = JSON.parse(line); const w = waiters.get(m.id); if (w) { waiters.delete(m.id); w(m); } } });
srv.stderr.on('data', (d) => { const s = String(d); if (!/ready/.test(s)) process.stderr.write(s); });
let nextId = 1;
function call(method, params) { return new Promise((res) => { const id = nextId++; waiters.set(id, res); srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); }); }
(async () => {
  await call('initialize', {}); srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  const tools = [['browser_eval', { expression: '1+1' }], ['browser_tabs', {}], ['browser_eval', { expression: 'document.title' }], ['browser_content', {}]];
  const rows = [];
  for (let r = 0; r < rounds; r++) for (const [name, args] of tools) {
    const t0 = process.hrtime.bigint(); const m = await call('tools/call', { name, arguments: args }); const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    rows.push({ r, name, ms: Math.round(ms), err: m.result && m.result.isError, len: JSON.stringify(m.result || m.error).length });
  }
  for (const x of rows) console.log(`${x.r} ${x.name.padEnd(16)} ${String(x.ms).padStart(5)} ms  err=${x.err}  len=${x.len}`);
  const warm = rows.filter((x) => x.r > 0); const med = (a) => { const s = a.slice().sort((p, q) => p - q); return s[Math.floor(s.length / 2)]; };
  for (const name of ['browser_eval', 'browser_tabs', 'browser_content']) console.log(`median ${name.padEnd(16)} ${med(warm.filter((x) => x.name === name).map((x) => x.ms))} ms (rounds>0)`);
  srv.stdin.end(); setTimeout(() => process.exit(0), 300);
})();

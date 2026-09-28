// Tight loop: go + first frame click + immediate state read. FX = fixture dir.
const { spawnSync, spawn } = require('child_process');
const fs = require('fs'); const path = require('path');
const WT = process.env.WT; const N = +(process.env.N || 50); const MODE = process.env.MODE || 'both';
const CLI = path.join(WT, 'bin', 'cdpilot.js');
const OUT = process.env.OUT; fs.mkdirSync(OUT, { recursive: true });
const home = path.join(OUT, 'home'); fs.mkdirSync(home, { recursive: true });
const base = +(process.env.PORTBASE || 59420); const [cdpPort, p1, p2] = [base, base + 1, base + 2];
const FX = process.env.FX || path.join(WT, 'test', 'fixtures', 'frames');
const servers = [p1, p2].map((p) => spawn((process.env.PYB || 'python'), ['-m', 'http.server', String(p), '--bind', '127.0.0.1'],
  { cwd: FX, stdio: 'ignore' }));
const env = { ...process.env, CDPILOT_HOME: home, CDPILOT_PROFILE: path.join(home, 'profile'),
  CDP_PORT: String(cdpPort), CHROME_HEADLESS: '1', CDPILOT_PYTHON: process.env.CDPILOT_PYTHON || (process.env.PYB || 'python') };
delete env.CDPILOT_TARGET;
const c = (trace, ...args) => spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf-8', timeout: 60000,
  env: trace ? { ...env, CDPILOT_CDP_TRACE: trace } : env });
spawnSync('sleep', ['1']);
const l = c(null, 'launch'); console.log('launch:', (l.stdout + l.stderr).trim().split('\n').pop());
let fails = 0, runs = 0; const fl = [];
try {
  for (let i = 0; i < N; i++) {
    const child = `http://localhost:${p2}/inner.html?nested=http://127.0.0.1:${p1}/nested.html`;
    const cases = [['same', `http://127.0.0.1:${p1}/top.html`],
      ['cross', `http://127.0.0.1:${p1}/top.html?child=${encodeURIComponent(child)}`]]
      .filter(([k]) => MODE === 'both' || MODE === k);
    for (const [k, url] of cases) {
      runs++;
      const tr = path.join(OUT, `trace-${i}-${k}.txt`);
      try { fs.renameSync(tr, tr + '.old'); } catch (e) {}
      c(null, 'go', url);
      const ck = c(tr, 'click', '#card >>> #pay-btn');
      const ev = c(null, 'frame', 'eval', '--frame', '#card',
        "[document.querySelector('#status').textContent, document.body.dataset.log, document.documentElement.dataset.diag||''].join('|')");
      const good = /Result: paid\|/.test(ev.stdout);
      let extra = '';
      if (!good) {
        fails++; fl.push(`${i}-${k}`);
        extra = ' TOP=' + c(null, 'eval', "document.documentElement.dataset.diag||''").stdout.trim()
          + ' TRACE=' + fs.readFileSync(tr, 'utf8').trim().split(/\n/).join(',');
      }
      console.log(`${i} ${k} ${good ? 'PASS' : 'FAIL'} click=[${(ck.stdout + ck.stderr).trim().replace(/\n/g, ' / ')}] eval=${ev.stdout.trim()}${extra}`);
    }
  }
} finally {
  c(null, 'stop'); servers.forEach((s) => s.kill());
  console.log(`SUMMARY fails=${fails}/${runs} ${fl.join(',')}`);
}

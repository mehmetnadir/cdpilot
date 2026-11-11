'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const assert = require('assert');
const { spawnSync } = require('child_process');
const { extractRuntimeFromPy } = require('./canvas_morph.js');

const STATE_HTML_PATH = path.join(__dirname, 'fixtures', 'canvas', 'state.html');
const CLI_PATH = path.join(__dirname, '..', 'bin', 'cdpilot.js');

// Which browser the canvas e2e tests use (B2 ORTA-2a; shared by every canvas e2e):
//   CDPILOT_CANVAS_E2E_CDP=127.0.0.1:<port> set -> that browser (local development: the shared
//   headless Chrome 127.0.0.1:9333); nothing is launched or stopped.
//   unset (CI: CDPILOT_E2E=1 and no browser on 9333) -> an own headless Chrome on a free port in
//   a temp CDPILOT_HOME, like the 'record & replay e2e' test (cdpilot launch, CHROME_HEADLESS=1,
//   CDP_PORT=<free>), stopped by stop().
function parseCdpHostPort(value) {
  const m = /^(127\.0\.0\.1|localhost):(\d{1,5})$/.exec(String(value || '').trim());
  if (!m) throw new Error(`CDPILOT_CANVAS_E2E_CDP must be 127.0.0.1:<port>, got ${JSON.stringify(value)}`);
  return { host: '127.0.0.1', port: Number(m[2]) };
}

function freePortSync() {
  const r = spawnSync(process.execPath, ['-e',
    "const s=require('net').createServer();s.listen(0,'127.0.0.1',()=>{process.stdout.write(String(s.address().port));s.close();});"],
  { encoding: 'utf8', timeout: 10000 });
  const port = Number((r.stdout || '').trim());
  if (r.status !== 0 || !port) throw new Error(`no free port: ${r.stderr}`);
  return port;
}

function waitCdpSync(port, timeoutMs) {
  const r = spawnSync(process.execPath, ['-e', `
    const http = require('http'); const end = Date.now() + ${Number(timeoutMs)};
    (function poll() {
      const req = http.get({ host: '127.0.0.1', port: ${Number(port)}, path: '/json/version', timeout: 2000 }, (res) => {
        let b = ''; res.on('data', (c) => { b += c; });
        res.on('end', () => { if (b.includes('webSocketDebuggerUrl')) process.exit(0); retry(); });
      });
      req.on('error', retry); req.on('timeout', () => req.destroy());
      function retry() { if (Date.now() > end) process.exit(1); setTimeout(poll, 250); }
    })();`], { timeout: Number(timeoutMs) + 5000 });
  return r.status === 0;
}

function canvasE2ECdp(label = 'canvas') {
  const preset = process.env.CDPILOT_CANVAS_E2E_CDP;
  if (preset) {
    const { host, port } = parseCdpHostPort(preset);
    return { hostPort: `${host}:${port}`, launched: false, stop() {} };
  }
  const home = fs.mkdtempSync(path.join(os.tmpdir(), `cdpilot-canvas-${label}-e2e-`));
  const port = freePortSync();
  const env = {
    ...process.env,
    CDPILOT_HOME: home,
    CDPILOT_PROFILE: path.join(home, 'profile'),
    CDP_PORT: String(port),
    CHROME_HEADLESS: '1',
    CDPILOT_LOG: '0',
  };
  delete env.CDPILOT_TARGET;
  delete env.CDPILOT_CANVAS_E2E_CDP;
  const stop = () => {
    spawnSync(process.execPath, [CLI_PATH, 'stop'], { env, encoding: 'utf8', timeout: 30000 });
  };
  const r = spawnSync(process.execPath, [CLI_PATH, 'launch'], { env, encoding: 'utf8', timeout: 120000 });
  if (r.status !== 0 || !waitCdpSync(port, 30000)) {
    stop();
    throw new Error(`own headless Chrome did not start on 127.0.0.1:${port} (exit ${r.status}): ${r.stderr || r.stdout}`);
  }
  return { hostPort: `127.0.0.1:${port}`, launched: true, home, stop };
}

const CDP_HOST = '127.0.0.1';
const CDP_PORT = process.env.CDPILOT_CANVAS_E2E_CDP ? parseCdpHostPort(process.env.CDPILOT_CANVAS_E2E_CDP).port : null;

function fetchJsonVersion() {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: CDP_HOST, port: CDP_PORT, path: '/json/version', timeout: 4000 }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(new Error('CDP /json/version timeout')); });
  });
}

function connectCDP(wsUrl) {
  return new Promise((resolve, reject) => {
    if (typeof WebSocket === 'undefined') {
      reject(new Error('skipped: canvas e2e needs Node 22+ (no global WebSocket on Node ' + process.versions.node + ')'));
      return;
    }
    const ws = new WebSocket(wsUrl);
    let seq = 1;
    const pending = new Map();

    ws.addEventListener('open', () => {
      const send = (method, params = {}, sessionId = undefined) => new Promise((res, rej) => {
        const id = seq++;
        pending.set(id, { res, rej });
        const payload = { id, method, params };
        if (sessionId) payload.sessionId = sessionId;
        ws.send(JSON.stringify(payload));
      });
      const close = () => {
        try { ws.close(); } catch (_) {}
      };
      resolve({ send, close });
    });

    ws.addEventListener('message', (ev) => {
      let msg;
      try { msg = JSON.parse(typeof ev.data === 'string' ? ev.data : ev.data.toString()); } catch (_) { return; }
      if (msg && msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) rej(new Error(`${msg.error.message || 'CDP error'} (${msg.error.code})`));
        else res(msg.result);
      }
    });

    ws.addEventListener('error', (err) => {
      reject(err.error || new Error('WebSocket error'));
    });
  });
}

async function runE2E() {
  assert(CDP_PORT, 'set CDPILOT_CANVAS_E2E_CDP=127.0.0.1:<port> (test.js sets it, see canvasE2ECdp)');
  const { js } = extractRuntimeFromPy();
  const stateHtml = fs.readFileSync(STATE_HTML_PATH, 'utf8');
  const ver = await fetchJsonVersion();
  assert(ver && ver.webSocketDebuggerUrl, `Missing webSocketDebuggerUrl on ${CDP_HOST}:${CDP_PORT}`);

  const cdp = await connectCDP(ver.webSocketDebuggerUrl);
  let browserContextId = null;
  let targetId = null;
  let sessionId = null;

  try {
    const ctxRes = await cdp.send('Target.createBrowserContext', { disposeOnDetach: true });
    browserContextId = ctxRes.browserContextId;

    const tgtRes = await cdp.send('Target.createTarget', { url: 'about:blank', browserContextId });
    targetId = tgtRes.targetId;

    const attRes = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    sessionId = attRes.sessionId;

    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    await cdp.send('Performance.enable', {}, sessionId);

    const navRes = await cdp.send('Page.navigate', { url: 'about:blank' }, sessionId);
    const frameTree = await cdp.send('Page.getFrameTree', {}, sessionId);
    const frameId = (frameTree.frameTree && frameTree.frameTree.frame && frameTree.frameTree.frame.id) || navRes.frameId;

    await cdp.send('Page.setDocumentContent', { frameId, html: stateHtml }, sessionId);

    const evalInPage = async (expression, awaitPromise = false) => {
      const r = await cdp.send('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise,
      }, sessionId);
      if (r.exceptionDetails) {
        throw new Error('Page exception: ' + JSON.stringify(r.exceptionDetails.exception || r.exceptionDetails.text));
      }
      return r.result ? r.result.value : undefined;
    };

    // Inject CANVAS_RUNTIME_JS
    const runtimeV = await evalInPage(`${js}.v`);
    assert.strictEqual(runtimeV, 1);

    // Phase 1: Focus, input selection, scroll, live form values, <details> open
    await evalInPage(`(() => {
      const inpB = document.getElementById('inp-b');
      inpB.value = 'user-edited-hello';
      inpB.focus();
      inpB.setSelectionRange(2, 7, 'forward');

      const sc = document.getElementById('scroll-box');
      sc.scrollTop = 120;
      sc.scrollLeft = 45;

      document.getElementById('chk-1').checked = true;
      document.getElementById('ta-1').value = 'user-ta';
      document.getElementById('opt-2').selected = true;
      document.getElementById('det-1').open = true;
    })()`);

    const patch1Html = `
      <div id="inputs-wrap">
        <input id="inp-c" value="gamma-2">
        <input id="inp-b" value="hello world">
        <input id="inp-a" value="alpha-2">
      </div>
      <div id="scroll-box" style="height:60px;width:100px;overflow:auto;">
        <div id="scroll-inner" style="height:400px;width:400px;">scroll-v2</div>
      </div>
      <p id="range-p">range target text here</p>
      <form id="live-form" data-action="save-form">
        <input id="chk-1" name="chk" type="checkbox">
        <textarea id="ta-1" name="ta">initial</textarea>
        <select id="sel-1" name="sel">
          <option id="opt-1" value="1" selected>One</option>
          <option id="opt-2" value="2">Two</option>
        </select>
      </form>
      <details id="det-1">
        <summary>More</summary>
        <p id="det-p">Hidden2</p>
      </details>
      <dialog id="dlg-1">
        <p id="dlg-p">Dialog1</p>
      </dialog>
      <button id="act-btn" data-action="ping-btn" data-val="7">Ping2</button>
      <script id="s-e2e">window.__e2eCount = (window.__e2eCount || 0) + 1;</script>
    `;

    const state1 = await evalInPage(`(async () => {
      const res = await window.__cdpilotCanvas.patch(${JSON.stringify(patch1Html)}, { final: true });
      const inpB = document.getElementById('inp-b');
      const sc = document.getElementById('scroll-box');
      return {
        res,
        activeId: document.activeElement ? document.activeElement.id : null,
        order: Array.from(document.getElementById('inputs-wrap').children).map((e) => e.id),
        inpBVal: inpB.value,
        selStart: inpB.selectionStart,
        selEnd: inpB.selectionEnd,
        scrollTop: sc.scrollTop,
        scrollLeft: sc.scrollLeft,
        chk: document.getElementById('chk-1').checked,
        ta: document.getElementById('ta-1').value,
        opt2: document.getElementById('opt-2').selected,
        detOpen: document.getElementById('det-1').open,
        detText: document.getElementById('det-p').textContent,
        scriptCount: window.__e2eCount || 0,
        hasHostCsp: !!document.head.querySelector('meta[data-cdpilot-csp]'),
      };
    })()`, true);

    assert.strictEqual(state1.res.ok, true);
    assert.strictEqual(typeof state1.res.ms, 'number');
    assert.strictEqual(typeof state1.res.t_paint, 'number');
    assert.strictEqual(state1.activeId, 'inp-b');
    assert.deepStrictEqual(state1.order, ['inp-c', 'inp-b', 'inp-a']);
    assert.strictEqual(state1.inpBVal, 'user-edited-hello');
    assert.strictEqual(state1.selStart, 2);
    assert.strictEqual(state1.selEnd, 7);
    assert.strictEqual(state1.scrollTop, 120);
    assert.strictEqual(state1.scrollLeft, 45);
    assert.strictEqual(state1.chk, true);
    assert.strictEqual(state1.ta, 'user-ta');
    assert.strictEqual(state1.opt2, true);
    assert.strictEqual(state1.detOpen, true);
    assert.strictEqual(state1.detText, 'Hidden2');
    assert.strictEqual(state1.scriptCount, 1);
    assert.strictEqual(state1.hasHostCsp, true);

    // Phase 2: Range selection across nodeValue write + Modal <dialog> open via showModal(), then patch
    const state2 = await evalInPage(`(async () => {
      const rp = document.getElementById('range-p');
      const r = document.createRange();
      r.setStart(rp.firstChild, 3);
      r.setEnd(rp.firstChild, 10);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);

      const dlg = document.getElementById('dlg-1');
      dlg.showModal();
      const html2 = ${JSON.stringify(patch1Html.replace('range target text here', 'range updated target text here!').replace('Dialog1', 'Dialog2'))};
      await window.__cdpilotCanvas.patch(html2, { final: true });
      const rng = sel.rangeCount > 0 ? sel.getRangeAt(0) : null;
      document.getElementById('act-btn').click();
      return {
        rangeStart: rng ? rng.startOffset : -1,
        rangeEnd: rng ? rng.endOffset : -1,
        dlgOpen: dlg.open,
        dlgModal: dlg.matches(':modal'),
        dlgText: document.getElementById('dlg-p').textContent,
        scriptCountAfterEqual: window.__e2eCount || 0,
        qLen: window.__cdpilotCanvas.q.length,
        lastEv: window.__cdpilotCanvas.q[window.__cdpilotCanvas.q.length - 1] || null,
      };
    })()`, true);

    assert.strictEqual(state2.rangeStart, 3);
    assert.strictEqual(state2.rangeEnd, 10);
    assert.strictEqual(state2.dlgOpen, true);
    assert.strictEqual(state2.dlgModal, true);
    assert.strictEqual(state2.dlgText, 'Dialog2');
    assert.strictEqual(state2.scriptCountAfterEqual, 1);
    assert.strictEqual(state2.qLen, 1);
    assert.strictEqual(state2.lastEv.action, 'ping-btn');

    // Phase 3: 1,000 patches heap check (JSHeapUsedSize <= 2x start)
    const getHeap = async () => {
      const m = await cdp.send('Performance.getMetrics', {}, sessionId);
      const item = (m.metrics || []).find((x) => x.name === 'JSHeapUsedSize');
      return item ? item.value : 0;
    };

    // Warm up one patch before measuring baseline heap
    await evalInPage(`window.__cdpilotCanvas.patch('<div id="w"><p>warmup</p></div>', { final: false })`, true);
    const heapStart = await getHeap();
    assert(heapStart > 0, 'JSHeapUsedSize should be > 0');

    await evalInPage(`(async () => {
      const c = window.__cdpilotCanvas;
      for (let b = 0; b < 5; b++) {
        const ps = [];
        for (let j = 0; j < 200; j++) {
          const i = b * 200 + j;
          const html = '<div id="inputs-wrap">' +
            '<input id="inp-a" value="v' + (i % 5) + '">' +
            '<input id="inp-b" value="hello world">' +
            '<span data-key="k1">item-' + i + '</span>' +
            '<span data-key="k2" data-i="' + i + '">sub</span>' +
            '</div>';
          ps.push(c.patch(html, { final: (i % 50 === 0) }));
        }
        await Promise.all(ps);
      }
    })()`, true);

    const heapEnd = await getHeap();
    const ratio = Math.round((heapEnd / heapStart) * 100) / 100;
    assert(heapEnd <= heapStart * 2, `JSHeapUsedSize grew > 2x: start=${heapStart}, end=${heapEnd} (${ratio}x)`);

    return {
      ok: true,
      focusKept: state1.activeId === 'inp-b',
      selectionKept: state1.selStart === 2 && state1.selEnd === 7,
      rangeKept: state2.rangeStart === 3 && state2.rangeEnd === 10,
      scrollKept: state1.scrollTop === 120 && state1.scrollLeft === 45,
      detailsKept: state1.detOpen,
      modalDialogKept: state2.dlgModal,
      heapStart,
      heapEnd,
      heapRatio: ratio,
    };
  } finally {
    if (targetId) {
      try { await cdp.send('Target.closeTarget', { targetId }); } catch (_) {}
    }
    if (browserContextId) {
      try { await cdp.send('Target.disposeBrowserContext', { browserContextId }); } catch (_) {}
    }
    cdp.close();
  }
}

if (require.main === module) {
  runE2E().then((res) => {
    process.stdout.write(JSON.stringify(res) + '\n');
    process.exit(0);
  }).catch((err) => {
    process.stderr.write((err && err.stack ? err.stack : String(err)) + '\n');
    process.exit(1);
  });
}

module.exports = { runE2E, canvasE2ECdp, parseCdpHostPort };

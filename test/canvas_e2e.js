'use strict';

const fs = require('fs');
const path = require('path');
const http = require('http');
const assert = require('assert');
const { extractRuntimeFromPy } = require('./canvas_morph.js');

const STATE_HTML_PATH = path.join(__dirname, 'fixtures', 'canvas', 'state.html');
const CDP_HOST = '127.0.0.1';
const CDP_PORT = 9333;

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
  const { js } = extractRuntimeFromPy();
  const stateHtml = fs.readFileSync(STATE_HTML_PATH, 'utf8');
  const ver = await fetchJsonVersion();
  assert(ver && ver.webSocketDebuggerUrl, 'Missing webSocketDebuggerUrl on 127.0.0.1:9333');

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

module.exports = { runE2E };

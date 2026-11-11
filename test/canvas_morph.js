'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const { createFakeDOM } = require('./canvas_fake_dom.js');

const ROOT = path.resolve(__dirname, '..');
const PY_PATH = path.join(ROOT, 'src', 'cdpilot.py');
const FAKE_DOM_PATH = path.join(__dirname, 'canvas_fake_dom.js');

function extractRuntimeFromPy() {
  const py = fs.readFileSync(PY_PATH, 'utf8');
  const vmMatch = py.match(/CANVAS_RUNTIME_V\s*=\s*(\d+)/);
  const jsMatch = py.match(/CANVAS_RUNTIME_JS\s*=\s*r"""([\s\S]*?)"""/);
  if (!vmMatch || !jsMatch) throw new Error('Could not extract CANVAS_RUNTIME_V / CANVAS_RUNTIME_JS from src/cdpilot.py');
  const v = Number(vmMatch[1]);
  const js = jsMatch[1];
  const coreSplit1 = js.split('// --- morph core begin ---');
  const coreSplit2 = coreSplit1[1] ? coreSplit1[1].split('// --- morph core end ---') : [''];
  const core = coreSplit2[0];
  return {
    v,
    js,
    totalBytes: Buffer.byteLength(js, 'utf8'),
    totalLines: js.split('\n').length,
    coreBytes: Buffer.byteLength(core, 'utf8'),
    coreLines: core.split('\n').length,
    fakeDomLines: fs.readFileSync(FAKE_DOM_PATH, 'utf8').split('\n').length - 1,
  };
}

function createRuntimeEnv(initialHtml = '<!doctype html><html><head></head><body></body></html>', opts = {}) {
  const { js } = extractRuntimeFromPy();
  const scriptsRun = [];
  const fake = createFakeDOM(initialHtml, {
    onScript(el) {
      scriptsRun.push({
        id: el.getAttribute('id') || '',
        type: el.getAttribute('type') || '',
        src: el.getAttribute('src') || '',
        text: el.textContent || '',
      });
    },
  });

  let nextTimerId = 1;
  const timers = new Map();
  const intervals = new Map();
  const rafs = new Map();
  const autoRaf = opts.autoRaf !== false;

  const win = {
    document: fake.document,
    DOMParser: fake.DOMParser,
    performance: { now: () => Date.now() },
    getSelection: () => fake.document._selection,
    setTimeout(fn, ms, ...args) {
      const id = nextTimerId++;
      timers.set(id, { fn, ms, args });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    setInterval(fn, ms, ...args) {
      const id = nextTimerId++;
      intervals.set(id, { fn, ms, args });
      return id;
    },
    clearInterval(id) { intervals.delete(id); },
    requestAnimationFrame(fn) {
      const id = nextTimerId++;
      if (autoRaf) {
        Promise.resolve().then(() => {
          if (rafs.has(id)) {
            rafs.delete(id);
            fn(Date.now());
          }
        });
      }
      rafs.set(id, fn);
      return id;
    },
    cancelAnimationFrame(id) { rafs.delete(id); },
  };
  win.window = win;
  win.globalThis = win;

  const ctx = vm.createContext(win);
  const api = vm.runInContext(js, ctx);

  return {
    win,
    ctx,
    api,
    js,
    document: fake.document,
    opCounts: fake.opCounts,
    resetOpCounts: fake.resetOpCounts,
    serializeNode: fake.serializeNode,
    serializeChildren: fake.serializeChildren,
    scriptsRun,
    timers,
    intervals,
    rafs,
  };
}

async function runAllTests() {
  const results = {};
  const plain = (x) => JSON.parse(JSON.stringify(x));

  // 1. Budget
  const meta = extractRuntimeFromPy();
  assert.strictEqual(meta.v, 1);
  assert(meta.totalBytes <= 14336, `totalBytes ${meta.totalBytes} > 14336`);
  assert(meta.coreBytes <= 10240, `coreBytes ${meta.coreBytes} > 10240`);
  assert(meta.coreLines <= 300, `coreLines ${meta.coreLines} > 300`);
  assert(meta.fakeDomLines <= 250, `fakeDomLines ${meta.fakeDomLines} > 250`);
  results.budget = {
    v: meta.v,
    totalBytes: meta.totalBytes,
    totalLines: meta.totalLines,
    coreBytes: meta.coreBytes,
    coreLines: meta.coreLines,
    fakeDomLines: meta.fakeDomLines,
  };

  // 2. Surface & idempotence of runtime load & empty input no-op
  {
    const env = createRuntimeEnv('<!doctype html><html><head></head><body><p>hi</p></body></html>');
    assert.strictEqual(Object.isFrozen(env.api), true);
    assert.strictEqual(env.api.v, 1);
    assert.deepStrictEqual(Object.keys(env.api).sort(), ['emit', 'patch', 'q', 'reset', 'v']);
    const second = vm.runInContext(env.js, env.ctx);
    assert.strictEqual(second, env.api);
    env.resetOpCounts();
    const nop1 = await env.api.patch('', { final: true });
    const nop2 = await env.api.patch('   ', { final: false });
    assert.strictEqual(nop1.ok, true);
    assert.deepStrictEqual(plain(nop1.ops), { add: 0, del: 0, move: 0, upd: 0 });
    assert.deepStrictEqual(plain(nop2.ops), { add: 0, del: 0, move: 0, upd: 0 });
    assert.strictEqual(typeof nop1.ms, 'number');
    assert.strictEqual(typeof nop1.t_paint, 'number');
    assert.strictEqual(env.serializeChildren(env.document.body), '<p>hi</p>');
    results.surface = { frozen: true, v: env.api.v, sameInstance: second === env.api, nopOps: plain(nop1.ops) };
  }

  // 3. Keyed reorder with minimum op count & Pass 1 deletion & tag replacement
  {
    const env = createRuntimeEnv('<!doctype html><html><head></head><body><ul><li id="a">A</li><li id="b">B</li><li id="c">C</li><li id="d">D</li></ul></body></html>');
    const ul = env.document.querySelector('ul');
    const [liA, liB, liC, liD] = ul.childNodes;
    env.resetOpCounts();
    const r1 = await env.api.patch('<ul><li id="d">D</li><li id="a">A</li><li id="b">B</li><li id="c">C</li></ul>', { final: true });
    assert.deepStrictEqual(plain(r1.ops), { add: 0, del: 0, move: 1, upd: 0 });
    assert.strictEqual(env.opCounts.insertBefore, 1);
    assert.deepStrictEqual(ul.childNodes, [liD, liA, liB, liC]);

    // data-key reorder
    const env2 = createRuntimeEnv('<!doctype html><html><head></head><body><div data-key="k1">1</div><div data-key="k2">2</div><div data-key="k3">3</div></body></html>');
    const [d1, d2, d3] = env2.document.body.childNodes;
    env2.resetOpCounts();
    const r2 = await env2.api.patch('<div data-key="k2">2</div><div data-key="k3">3</div><div data-key="k1">1</div>', { final: true });
    assert.deepStrictEqual(plain(r2.ops), { add: 0, del: 0, move: 1, upd: 0 });
    assert.strictEqual(env2.opCounts.insertBefore, 1);
    assert.deepStrictEqual(env2.document.body.childNodes, [d2, d3, d1]);

    // Pass 1 keyed removal + different tag -> replaceWith
    env2.resetOpCounts();
    const r3 = await env2.api.patch('<section data-key="k2">2</section><div data-key="k1">1</div>', { final: true });
    assert.strictEqual(r3.ops.del, 2); // k3 removed + k2 replaced
    assert.strictEqual(r3.ops.add, 1); // k2 replaced with <section>
    assert.strictEqual(env2.opCounts.replaceWith, 1);
    assert.strictEqual(env2.serializeChildren(env2.document.body), '<section data-key="k2">2</section><div data-key="k1">1</div>');
    results.keyed = { moveOps: r1.ops.move, dataKeyMoveOps: r2.ops.move, replaceWithCount: env2.opCounts.replaceWith };
  }

  // 4. Attribute diff
  {
    const env = createRuntimeEnv('<!doctype html><html><head></head><body><div id="box" class="old" data-old="1" title="same">txt</div></body></html>');
    const box = env.document.getElementById('box');
    const r1 = await env.api.patch('<div id="box" class="new" data-new="2" title="same">txt</div>', { final: true });
    assert.strictEqual(r1.ops.upd, 1);
    assert.strictEqual(box.getAttribute('class'), 'new');
    assert.strictEqual(box.getAttribute('data-old'), null);
    assert.strictEqual(box.getAttribute('data-new'), '2');
    assert.strictEqual(box.getAttribute('title'), 'same');
    const r2 = await env.api.patch('<div id="box" class="new" data-new="2" title="same">txt</div>', { final: true });
    assert.strictEqual(r2.ops.upd, 0);
    results.attrDiff = { upd1: r1.ops.upd, upd2: r2.ops.upd };
  }

  // 5. Focus kept on keyed input while siblings reorder (neighbors move instead, blur === 0)
  {
    const env = createRuntimeEnv('<!doctype html><html><head></head><body><input id="a" value="1"><input id="b" value="2"><input id="c" value="3"></body></html>');
    const [inA, inB, inC] = env.document.body.childNodes;
    inB.focus();
    inB.setSelectionRange(0, 1, 'forward');
    env.resetOpCounts();
    const r = await env.api.patch('<input id="c" value="3"><input id="b" value="2"><input id="a" value="1">', { final: true });
    assert.strictEqual(env.document.activeElement, inB);
    assert.strictEqual(env.opCounts.blur, 0);
    assert.deepStrictEqual(env.document.body.childNodes, [inC, inB, inA]);
    assert.strictEqual(r.ops.move, 2); // c and a moved around stationary b!
    assert.strictEqual(inB.selectionStart, 0);
    assert.strictEqual(inB.selectionEnd, 1);
    results.focus = { activeId: env.document.activeElement.id, blurCount: env.opCounts.blur, moveCount: r.ops.move };
  }

  // 6. Range selection offsets restored after nodeValue writes + element scroll kept
  {
    const env = createRuntimeEnv('<!doctype html><html><head></head><body><div id="sc"><p id="p">hello world</p></div></body></html>');
    const sc = env.document.getElementById('sc');
    const p = env.document.getElementById('p');
    const txt = p.firstChild;
    sc.scrollTop = 125;
    sc.scrollLeft = 40;
    const range = env.document.createRange();
    range.setStart(txt, 2);
    range.setEnd(txt, 8);
    env.document._selection.addRange(range);

    await env.api.patch('<div id="sc"><p id="p">hello brave new world</p></div>', { final: true });
    assert.strictEqual(range.startContainer, txt);
    assert.strictEqual(range.startOffset, 2);
    assert.strictEqual(range.endOffset, 8);
    assert.strictEqual(sc.scrollTop, 125);
    assert.strictEqual(sc.scrollLeft, 40);

    // Clamp when new text is shorter than old offsets
    await env.api.patch('<div id="sc"><p id="p">hi</p></div>', { final: true });
    assert.strictEqual(range.startOffset, 2);
    assert.strictEqual(range.endOffset, 2);
    results.selectionAndScroll = { startOffset: range.startOffset, endOffset: range.endOffset, scrollTop: sc.scrollTop, scrollLeft: sc.scrollLeft };
  }

  // 7. Live form values / <details open> / modal <dialog> kept unless new HTML changes attr relative to last applied
  {
    const env = createRuntimeEnv(
      '<!doctype html><html><head></head><body>' +
      '<input id="inp" value="init">' +
      '<input id="chk" type="checkbox">' +
      '<textarea id="ta">init-ta</textarea>' +
      '<select id="sel"><option id="o1" selected>1</option><option id="o2">2</option></select>' +
      '<details id="det"><summary>S</summary><p>A</p></details>' +
      '<dialog id="dlg"><p>M1</p></dialog>' +
      '</body></html>'
    );
    const inp = env.document.getElementById('inp');
    const chk = env.document.getElementById('chk');
    const ta = env.document.getElementById('ta');
    const o1 = env.document.getElementById('o1');
    const o2 = env.document.getElementById('o2');
    const det = env.document.getElementById('det');
    const dlg = env.document.getElementById('dlg');

    // Simulate live user state changes
    inp.value = 'typed-by-user';
    chk.checked = true;
    ta.value = 'typed-ta';
    o1.selected = false;
    o2.selected = true;
    det.open = true;
    dlg.showModal();

    // Patch 1: template attributes unchanged relative to initial -> live state MUST be preserved
    await env.api.patch(
      '<input id="inp" value="init" data-x="1">' +
      '<input id="chk" type="checkbox">' +
      '<textarea id="ta">init-ta</textarea>' +
      '<select id="sel"><option id="o1" selected>1</option><option id="o2">2</option></select>' +
      '<details id="det"><summary>S</summary><p>B</p></details>' +
      '<dialog id="dlg"><p>M2</p></dialog>',
      { final: true }
    );
    assert.strictEqual(inp.value, 'typed-by-user');
    assert.strictEqual(chk.checked, true);
    assert.strictEqual(ta.value, 'typed-ta');
    assert.strictEqual(o2.selected, true);
    assert.strictEqual(det.open, true);
    assert.strictEqual(dlg.open, true);
    assert.strictEqual(dlg._isModal, true);
    assert.strictEqual(dlg.firstChild.textContent, 'M2');

    // Patch 2: template explicitly changes value/checked/textarea/selected/open relative to last applied
    await env.api.patch(
      '<input id="inp" value="from-server" data-x="1">' +
      '<input id="chk" type="checkbox" checked>' +
      '<textarea id="ta">server-ta</textarea>' +
      '<select id="sel"><option id="o1">1</option><option id="o2" selected>2</option></select>' +
      '<details id="det" open><summary>S</summary><p>B</p></details>' +
      '<dialog id="dlg"><p>M3</p></dialog>',
      { final: true }
    );
    assert.strictEqual(inp.value, 'from-server');
    assert.strictEqual(ta.value, 'server-ta');

    // Patch 3: template removes checked and open (relative to Patch 2 where they were present)
    await env.api.patch(
      '<input id="inp" value="from-server" data-x="1">' +
      '<input id="chk" type="checkbox">' +
      '<textarea id="ta">server-ta</textarea>' +
      '<select id="sel"><option id="o1">1</option><option id="o2">2</option></select>' +
      '<details id="det"><summary>S</summary><p>B</p></details>' +
      '<dialog id="dlg"><p>M3</p></dialog>',
      { final: true }
    );
    assert.strictEqual(chk.checked, false);
    assert.strictEqual(o2.selected, false);
    assert.strictEqual(det.open, false);
    assert.strictEqual(dlg.open, true); // modal dialog stays open
    results.stateRules = { keptUserValue: true, updatedOnAttrChange: true, modalKept: dlg.open };
  }

  // 8. Scripts: run only on final:true, equal matched script not re-run, changed script runs, unclosed script ignored
  {
    const env = createRuntimeEnv('<!doctype html><html><head></head><body><div id="app">1</div><script id="s0">window.init=1;</script></body></html>');
    assert.strictEqual(env.scriptsRun.length, 0);

    // Non-final patch with new script -> does NOT run
    await env.api.patch('<div id="app">2</div><script id="s0">window.init=1;</script><script id="s1">window.a=1;</script>', { final: false });
    assert.strictEqual(env.scriptsRun.length, 0);

    // Final patch with same s1 -> s1 runs once, s0 (seeded at init) does NOT re-run
    await env.api.patch('<div id="app">3</div><script id="s0">window.init=1;</script><script id="s1">window.a=1;</script>', { final: true });
    assert.strictEqual(env.scriptsRun.length, 1);
    assert.strictEqual(env.scriptsRun[0].text, 'window.a=1;');

    // Subsequent final patch with identical s1 -> does NOT re-run
    await env.api.patch('<div id="app">4</div><script id="s0">window.init=1;</script><script id="s1">window.a=1;</script>', { final: true });
    assert.strictEqual(env.scriptsRun.length, 1);

    // Final patch modifying s1 text -> runs updated s1
    await env.api.patch('<div id="app">5</div><script id="s0">window.init=1;</script><script id="s1">window.a=2;</script>', { final: true });
    assert.strictEqual(env.scriptsRun.length, 2);
    assert.strictEqual(env.scriptsRun[1].text, 'window.a=2;');

    // Unclosed trailing <script> is stripped and never runs
    await env.api.patch('<div id="app">6</div><script id="s1">window.a=2;</script><script>window.unclosed=1;', { final: true });
    assert.strictEqual(env.scriptsRun.length, 2);
    results.scripts = { runCount: env.scriptsRun.length, texts: env.scriptsRun.map((s) => s.text) };
  }

  // 9. Strip <meta http-equiv=refresh|content-security-policy> and <base>; keep host CSP meta
  {
    const env = createRuntimeEnv(
      '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'"><title>Old</title></head><body><p>1</p></body></html>'
    );
    const hostMeta = env.document.head.firstChild;
    assert.strictEqual(hostMeta.hasAttribute('data-cdpilot-csp'), true);

    await env.api.patch(
      '<!doctype html><html><head>' +
      '<base href="https://evil.example/">' +
      '<meta http-equiv="refresh" content="0;url=https://evil.example/">' +
      '<meta http-equiv="Content-Security-Policy" content="default-src *">' +
      '<meta data-cdpilot-csp content="spoof">' +
      '<title>New</title>' +
      '</head><body>' +
      '<base href="https://evil2.example/">' +
      '<meta http-equiv="REFRESH" content="1">' +
      '<meta http-equiv="content-security-policy" content=" unsafe-inline ">' +
      '<p>2</p>' +
      '</body></html>',
      { final: true }
    );
    assert.strictEqual(env.document.head.firstChild, hostMeta);
    assert.strictEqual(hostMeta.getAttribute('content'), "default-src 'none'");
    assert.strictEqual(env.document.querySelectorAll('base').length, 0);
    const metas = env.document.querySelectorAll('meta');
    // Only hostMeta and the non-http-equiv meta (with data-cdpilot-csp stripped) remain
    for (const m of metas) {
      if (m !== hostMeta) {
        assert.strictEqual(m.hasAttribute('data-cdpilot-csp'), false);
        const he = (m.getAttribute('http-equiv') || '').toLowerCase();
        assert.notStrictEqual(he, 'refresh');
        assert.notStrictEqual(he, 'content-security-policy');
      }
    }
    results.security = { hostCspKept: env.document.head.firstChild === hostMeta, baseCount: env.document.querySelectorAll('base').length };
  }

  // 10. Delegated listeners & emit queue / binding / 1 KB cut
  {
    const env = createRuntimeEnv(
      '<!doctype html><html><head></head><body>' +
      '<button id="btn1" data-action="save-item" data-item-id="42"><span id="sp">Save</span></button>' +
      '<button id="btnBad" data-action="INVALID ACTION!"></button>' +
      '<form id="frm" data-emit="submit-form">' +
      '<input name="user" value="ada">' +
      '<input name="Admin" type="checkbox" checked>' +
      '<input name="ign" value="no" disabled>' +
      '</form>' +
      '</body></html>'
    );
    // Click on child of [data-action]
    const sp = env.document.getElementById('sp');
    env.document.dispatchEvent({ type: 'click', target: sp });
    assert.strictEqual(env.api.q.length, 1);
    assert.deepStrictEqual(plain(env.api.q[0]), { type: 'click', action: 'save-item', id: 'btn1', data: { 'item-id': '42' } });

    // Invalid data-action is ignored
    env.document.dispatchEvent({ type: 'click', target: env.document.getElementById('btnBad') });
    assert.strictEqual(env.api.q.length, 1);

    // Form submit with preventDefault
    let prevented = false;
    const frm = env.document.getElementById('frm');
    env.document.dispatchEvent({ type: 'submit', target: frm, preventDefault() { prevented = true; } });
    assert.strictEqual(prevented, true);
    assert.strictEqual(env.api.q.length, 2);
    assert.deepStrictEqual(plain(env.api.q[1]), { type: 'submit', action: 'submit-form', id: 'frm', data: { user: 'ada', Admin: true } });

    // Input event on form control
    const inp = frm.querySelector('input');
    inp.value = 'grace';
    env.document.dispatchEvent({ type: 'input', target: inp });
    assert.strictEqual(env.api.q.length, 3);
    assert.deepStrictEqual(plain(env.api.q[2]), { type: 'input', action: 'submit-form', id: 'user', data: { value: 'grace' } });

    // Queue cap at 100
    for (let i = 0; i < 105; i++) env.api.emit({ type: 'click', action: 'act', id: `i${i}`, data: { i } });
    assert.strictEqual(env.api.q.length, 100);
    assert.strictEqual(env.api.q[0].id, 'i5');

    // Binding attachment flushes q and receives new events, and cuts data at <= 1024 chars
    const delivered = [];
    env.win.__cdpilotCanvasEmit = (jsonStr) => delivered.push(JSON.parse(jsonStr));
    const huge = 'x'.repeat(2500);
    env.api.emit({ type: 'input', action: 'big-data', id: 'b1', data: { text: huge } });
    assert.strictEqual(env.api.q.length, 0);
    assert.strictEqual(delivered.length, 101);
    const lastEv = delivered[delivered.length - 1];
    assert.strictEqual(lastEv.action, 'big-data');
    assert(JSON.stringify(lastEv.data).length <= 1024, `data len ${JSON.stringify(lastEv.data).length} > 1024`);
    results.emit = { flushedCount: delivered.length, cutDataLen: JSON.stringify(lastEv.data).length };
  }

  // 11. Timer wrapper & reset()
  {
    const env = createRuntimeEnv('<!doctype html><html><head></head><body></body></html>', { autoRaf: false });
    env.win.setTimeout(() => {}, 50);
    env.win.setInterval(() => {}, 50);
    env.win.requestAnimationFrame(() => {});
    assert.strictEqual(env.timers.size, 1);
    assert.strictEqual(env.intervals.size, 1);
    assert.strictEqual(env.rafs.size, 1);
    env.api.reset();
    assert.strictEqual(env.timers.size, 0);
    assert.strictEqual(env.intervals.size, 0);
    assert.strictEqual(env.rafs.size, 0);
    results.timers = { cleared: true };
  }

  // 12. Idempotence on 200 seeded random trees (after morph(a->b) serialised DOM equals b, and morph(b->b) is 0 ops)
  {
    let seed = 0x13579bdf;
    const rand = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 0x100000000;
    };
    const pick = (arr) => arr[Math.floor(rand() * arr.length)];
    const tags = ['div', 'section', 'p', 'span', 'ul', 'li', 'article', 'header', 'footer', 'b'];

    function genTree(depth, prefix) {
      const count = depth === 0 ? 2 + Math.floor(rand() * 5) : Math.floor(rand() * 4);
      let out = '';
      let kIdx = 0;
      for (let i = 0; i < count; i++) {
        const r = rand();
        if (r < 0.25) {
          out += `txt-${prefix}-${i}-${Math.floor(rand() * 99)}`;
        } else {
          const tag = pick(tags);
          const attrs = [];
          if (rand() < 0.45) attrs.push(`id="${prefix}_k${kIdx++}"`);
          else if (rand() < 0.45) attrs.push(`data-key="${prefix}_dk${kIdx++}"`);
          if (rand() < 0.5) attrs.push(`class="c${Math.floor(rand() * 5)}"`);
          if (rand() < 0.3) attrs.push(`data-v="${Math.floor(rand() * 20)}"`);
          const aStr = attrs.length ? ' ' + attrs.join(' ') : '';
          const inner = depth < 2 ? genTree(depth + 1, `${prefix}_${i}`) : `leaf-${Math.floor(rand() * 50)}`;
          out += `<${tag}${aStr}>${inner}</${tag}>`;
        }
      }
      return out;
    }

    const env = createRuntimeEnv('<!doctype html><html><head></head><body></body></html>');
    for (let iter = 0; iter < 200; iter++) {
      const htmlA = genTree(0, `t${iter}a`);
      const htmlB = genTree(0, `t${iter}b`);
      const refDom = createFakeDOM(`<!doctype html><html><head></head><body>${htmlB}</body></html>`);
      const expectedB = refDom.serializeChildren(refDom.document.body);

      await env.api.patch(htmlA, { final: true });
      await env.api.patch(htmlB, { final: true });
      const actualB = env.serializeChildren(env.document.body);
      assert.strictEqual(actualB, expectedB, `Mismatch at tree ${iter}: got ${actualB} vs ${expectedB}`);

      // Idempotence: morph(b -> b) has 0 ops and identical serialisation
      const rIdem = await env.api.patch(htmlB, { final: true });
      assert.deepStrictEqual(plain(rIdem.ops), { add: 0, del: 0, move: 0, upd: 0 }, `Non-zero ops on idempotent patch at ${iter}`);
      assert.strictEqual(env.serializeChildren(env.document.body), expectedB);
    }
    results.random200 = { passed: 200 };
  }

  // 13. Malformed HTML does not throw
  {
    const env = createRuntimeEnv('<!doctype html><html><head></head><body><p>start</p></body></html>');
    const samples = [
      '<div><span><p>unclosed tags',
      '</p></div></span>stray closers<div>ok</div>',
      '<div attr="unterminated><p>still works</p>',
      '<<<><>!@#$%^&*()',
      '<table><tr><td>1<td>2<tr><td>3</table>',
      '<div id="x">before</div><script>unclosed script(1',
    ];
    for (const s of samples) {
      const res = await env.api.patch(s, { final: true });
      assert.strictEqual(res.ok, true);
    }
    results.malformed = { count: samples.length, ok: true };
  }

  return results;
}

if (require.main === module) {
  runAllTests().then((res) => {
    process.stdout.write(JSON.stringify({ ok: true, results: res }) + '\n');
  }).catch((err) => {
    process.stderr.write((err && err.stack ? err.stack : String(err)) + '\n');
    process.exit(1);
  });
}

module.exports = { extractRuntimeFromPy, createRuntimeEnv, runAllTests };

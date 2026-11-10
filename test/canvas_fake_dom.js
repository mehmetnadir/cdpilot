'use strict';
const VOID_TAGS = new Set(['AREA', 'BASE', 'BR', 'COL', 'EMBED', 'HR', 'IMG', 'INPUT', 'LINK', 'META', 'PARAM', 'SOURCE', 'TRACK', 'WBR']);
const decEnt = (s) => String(s).replace(/&(amp|lt|gt|quot|#39);/g, (_, e) => (e === 'amp' ? '&' : e === 'lt' ? '<' : e === 'gt' ? '>' : e === 'quot' ? '"' : "'"));
const encTxt = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const encAtt = (s) => encTxt(s).replace(/"/g, '&quot;');

function createFakeDOM(initialHtml = '<!doctype html><html><head></head><body></body></html>', hooks = {}) {
  const opCounts = { insertBefore: 0, removeChild: 0, replaceWith: 0, setAttribute: 0, removeAttribute: 0, nodeValue: 0, blur: 0 };
  const resetOpCounts = () => { for (const k of Object.keys(opCounts)) opCounts[k] = 0; };
  let doc = null;
  const isConn = (n) => {
    for (let c = n; c; c = c.parentNode) if (c === doc || (doc && (c === doc.documentElement || c === doc.body || c === doc.head))) return true;
    return false;
  };
  const chkBlur = (n) => {
    if (!doc || !doc.activeElement || doc.activeElement === doc.body || doc.activeElement === doc.documentElement) return;
    if (n === doc.activeElement || (n.contains && n.contains(doc.activeElement))) { opCounts.blur++; doc.activeElement = doc.body; }
  };
  const runScr = (n) => {
    if (!n || !isConn(n)) return;
    if (n.nodeType === 1 && n.nodeName === 'SCRIPT') {
      const tp = (n.getAttribute('type') || '').toLowerCase();
      if (!n.hasAttribute('data-ci') && !n.hasAttribute('data-cdpilot-inert') && tp !== 'text/ci' && tp !== 'text/cdpilot-inert') {
        if (typeof hooks.onScript === 'function') hooks.onScript(n);
      }
      return;
    }
    for (const c of (n.childNodes || [])) runScr(c);
  };

  class Node {
    constructor(nodeType, nodeName) {
      this.nodeType = nodeType; this.nodeName = nodeName; this.parentNode = null; this.childNodes = []; this.ownerDocument = doc;
    }
    get firstChild() { return this.childNodes[0] || null; }
    get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
    get nextSibling() {
      const p = this.parentNode, i = p ? p.childNodes.indexOf(this) : -1;
      return i >= 0 && i + 1 < p.childNodes.length ? p.childNodes[i + 1] : null;
    }
    get previousSibling() {
      const p = this.parentNode, i = p ? p.childNodes.indexOf(this) : -1;
      return i > 0 ? p.childNodes[i - 1] : null;
    }
    contains(o) { for (let c = o; c; c = c.parentNode) if (c === this) return true; return false; }
    appendChild(c) { return this.insertBefore(c, null, false); }
    insertBefore(c, ref = null, cnt = true) {
      if (c.nodeType === 11) { for (const x of [...c.childNodes]) this.insertBefore(x, ref, cnt); return c; }
      if (cnt) opCounts.insertBefore++;
      if (c.parentNode) {
        chkBlur(c);
        const idx = c.parentNode.childNodes.indexOf(c);
        if (idx >= 0) c.parentNode.childNodes.splice(idx, 1);
      }
      c.parentNode = this;
      const ri = ref ? this.childNodes.indexOf(ref) : -1;
      if (ri < 0) this.childNodes.push(c); else this.childNodes.splice(ri, 0, c);
      if (cnt) runScr(c);
      return c;
    }
    removeChild(c, cnt = true) {
      const idx = this.childNodes.indexOf(c);
      if (idx < 0) throw new Error('NotFoundError');
      if (cnt) opCounts.removeChild++;
      chkBlur(c); this.childNodes.splice(idx, 1); c.parentNode = null; return c;
    }
    replaceWith(nn) {
      if (!this.parentNode) return;
      opCounts.replaceWith++; chkBlur(this);
      const p = this.parentNode, idx = p.childNodes.indexOf(this);
      if (nn.parentNode) nn.parentNode.removeChild(nn, false);
      this.parentNode = null; nn.parentNode = p; p.childNodes.splice(idx, 1, nn);
      runScr(nn);
    }
  }

  class Text extends Node {
    constructor(t = '') { super(3, '#text'); this._val = String(t); }
    get nodeValue() { return this._val; }
    set nodeValue(v) {
      opCounts.nodeValue++; this._val = String(v ?? '');
      const r = doc && doc._selection && doc._selection._range;
      if (r) { if (r.startContainer === this) r.startOffset = 0; if (r.endContainer === this) r.endOffset = 0; }
    }
    get textContent() { return this._val; }
    set textContent(v) { this.nodeValue = v; }
  }
  class Comment extends Node {
    constructor(t = '') { super(8, '#comment'); this._val = String(t); }
    get nodeValue() { return this._val; }
    set nodeValue(v) { opCounts.nodeValue++; this._val = String(v ?? ''); }
  }
  class DocumentFragment extends Node { constructor() { super(11, '#document-fragment'); } }

  class Element extends Node {
    constructor(tag) {
      super(1, String(tag).toUpperCase());
      this.tagName = this.nodeName; this._attrs = new Map(); this._value = ''; this._dirtyValue = false;
      this.checked = false; this.selected = false; this.open = false; this.disabled = false;
      this.scrollTop = 0; this.scrollLeft = 0; this.selectionStart = 0; this.selectionEnd = 0; this.selectionDirection = 'none';
      this._isModal = false;
      if (this.nodeName === 'TEMPLATE') this.content = new DocumentFragment();
    }
    get attributes() { return [...this._attrs.entries()].map(([name, value]) => ({ name, value })); }
    getAttribute(k) { const n = String(k).toLowerCase(); return this._attrs.has(n) ? this._attrs.get(n) : null; }
    hasAttribute(k) { return this._attrs.has(String(k).toLowerCase()); }
    setAttribute(k, v, cnt = true) {
      if (cnt) opCounts.setAttribute++;
      const n = String(k).toLowerCase(), s = String(v ?? '');
      this._attrs.set(n, s);
      if (n === 'value' && !this._dirtyValue) this._value = s;
      if (n === 'checked') this.checked = true;
      if (n === 'selected') this.selected = true;
      if (n === 'open') this.open = true;
      if (n === 'disabled') this.disabled = true;
    }
    removeAttribute(k, cnt = true) {
      const n = String(k).toLowerCase();
      if (cnt && this._attrs.has(n)) opCounts.removeAttribute++;
      this._attrs.delete(n);
      if (n === 'checked') this.checked = false;
      if (n === 'selected') this.selected = false;
      if (n === 'open' && !this._isModal) this.open = false;
      if (n === 'disabled') this.disabled = false;
    }
    get id() { return this.getAttribute('id') || ''; }
    set id(v) { this.setAttribute('id', v); }
    get value() { return this._value; }
    set value(v) {
      this._dirtyValue = true; this._value = String(v ?? '');
      if (doc && doc.activeElement === this) { this.selectionStart = this._value.length; this.selectionEnd = this._value.length; }
    }
    setSelectionRange(s, e, d = 'none') { this.selectionStart = s; this.selectionEnd = e; this.selectionDirection = d; }
    focus() { if (doc) doc.activeElement = this; }
    blur() { if (doc && doc.activeElement === this) { opCounts.blur++; doc.activeElement = doc.body; } }
    showModal() { this._isModal = true; this.open = true; this.setAttribute('open', '', false); }
    close() { this._isModal = false; this.open = false; this.removeAttribute('open', false); }
    matches(sel) {
      if (sel === ':modal' || sel === 'dialog:modal') return this.nodeName === 'DIALOG' && !!this._isModal;
      return sel.split(',').some((p) => p.trim().toUpperCase() === this.nodeName);
    }
    get textContent() { return this.childNodes.map((c) => c.textContent || '').join(''); }
    set textContent(v) {
      this.childNodes = []; const s = String(v ?? '');
      if (s !== '') this.appendChild(new Text(s));
      if (this.nodeName === 'TEXTAREA' && !this._dirtyValue) this._value = s;
    }
    get innerHTML() { return serializeChildren(this.nodeName === 'TEMPLATE' ? this.content : this); }
    set innerHTML(h) { const t = this.nodeName === 'TEMPLATE' ? this.content : this; t.childNodes = []; parseInto(String(h ?? ''), t); }
    querySelectorAll(sel) {
      const out = [], parts = sel.split(',').map((s) => s.trim().toLowerCase());
      const m = (el) => parts.some((p) => p === 'dialog:modal' ? (el.nodeName === 'DIALOG' && !!el._isModal)
        : p.startsWith('#') ? el.id === p.slice(1) : p.startsWith('[') ? el.hasAttribute(p.slice(1, -1)) : el.nodeName.toLowerCase() === p);
      const walk = (n) => { for (const c of n.childNodes) if (c.nodeType === 1) { if (m(c)) out.push(c); walk(c); } };
      walk(this); return out;
    }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  }

  function parseInto(html, root) {
    const st = [root], re = /<!--([\s\S]*?)-->|<\/([a-zA-Z0-9:-]+)\s*>|<([a-zA-Z0-9:-]+)((?:\s+[^\s/>=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=>]+))?)*)\s*(\/?)>|([^<]+)|</g;
    let m;
    while ((m = re.exec(html)) !== null) {
      const cur = st[st.length - 1], tgt = cur.nodeName === 'TEMPLATE' ? cur.content : cur;
      if (m[1] !== undefined) { tgt.insertBefore(new Comment(m[1]), null, false); continue; }
      if (m[2] !== undefined) {
        const ct = m[2].toUpperCase();
        for (let i = st.length - 1; i > 0; i--) if (st[i].nodeName === ct) { st.length = i; break; }
        continue;
      }
      if (m[3] !== undefined) {
        const tag = m[3].toUpperCase(), el = new Element(tag), are = /([^\s/>=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=>]+)))?/g;
        let am;
        while ((am = are.exec(m[4] || '')) !== null) el.setAttribute(am[1], decEnt(am[2] ?? am[3] ?? am[4] ?? ''), false);
        tgt.insertBefore(el, null, false);
        if (tag === 'SCRIPT' || tag === 'TEXTAREA') {
          const cre = new RegExp(`</${tag}\\s*>`, 'ig'); cre.lastIndex = re.lastIndex;
          const cm = cre.exec(html), raw = cm ? html.slice(re.lastIndex, cm.index) : html.slice(re.lastIndex);
          if (raw) el.insertBefore(new Text(tag === 'TEXTAREA' ? decEnt(raw) : raw), null, false);
          if (tag === 'TEXTAREA' && !el.hasAttribute('value')) el._value = el.textContent;
          re.lastIndex = cm ? cre.lastIndex : html.length;
        } else if (!m[5] && !VOID_TAGS.has(tag)) st.push(el);
        continue;
      }
      const txt = decEnt(m[6] !== undefined ? m[6] : '<'), last = tgt.lastChild;
      if (last && last.nodeType === 3) last._val += txt; else tgt.insertBefore(new Text(txt), null, false);
    }
  }

  function serializeNode(n) {
    if (n.nodeType === 3) return encTxt(n.nodeValue);
    if (n.nodeType === 8) return `<!--${n.nodeValue}-->`;
    if (n.nodeType === 11) return serializeChildren(n);
    const tag = n.nodeName.toLowerCase();
    const a = [...n._attrs.entries()].sort((x, y) => x[0].localeCompare(y[0])).map(([k, v]) => `${k}="${encAtt(v)}"`).join(' ');
    const open = a ? `<${tag} ${a}>` : `<${tag}>`;
    if (VOID_TAGS.has(n.nodeName)) return open;
    return `${open}${n.nodeName === 'SCRIPT' ? n.textContent : serializeChildren(n.nodeName === 'TEMPLATE' ? n.content : n)}</${tag}>`;
  }
  function serializeChildren(p) { return p.childNodes.map(serializeNode).join(''); }

  doc = {
    nodeType: 9, nodeName: '#document', _listeners: new Map(),
    documentElement: new Element('HTML'), head: new Element('HEAD'), body: new Element('BODY'), activeElement: null,
    _selection: { _range: null, get rangeCount() { return this._range ? 1 : 0; }, getRangeAt() { return this._range; }, addRange(r) { this._range = r; }, removeAllRanges() { this._range = null; } },
    createElement: (t) => new Element(t), createTextNode: (t) => new Text(t), createComment: (t) => new Comment(t),
    createRange: () => ({ startContainer: null, startOffset: 0, endContainer: null, endOffset: 0, setStart(c, o) { this.startContainer = c; this.startOffset = o; }, setEnd(c, o) { this.endContainer = c; this.endOffset = o; } }),
    getElementById(id) { return this.documentElement.querySelector(`#${id}`); },
    querySelector(s) { return this.documentElement.querySelector(s); },
    querySelectorAll(s) { return this.documentElement.querySelectorAll(s); },
    addEventListener(t, fn) { if (!this._listeners.has(t)) this._listeners.set(t, []); this._listeners.get(t).push(fn); },
    dispatchEvent(ev) { for (const fn of (this._listeners.get(ev.type) || [])) fn(ev); }
  };
  doc.documentElement.insertBefore(doc.head, null, false); doc.documentElement.insertBefore(doc.body, null, false); doc.activeElement = doc.body;

  class DOMParser {
    parseFromString(html) {
      const d = { head: new Element('HEAD'), body: new Element('BODY') };
      const hm = /<head[^>]*>([\s\S]*?)<\/head>/i.exec(html), bm = /<body[^>]*>([\s\S]*?)<\/body>/i.exec(html);
      if (hm) parseInto(hm[1], d.head);
      if (bm) parseInto(bm[1], d.body); else if (!hm) parseInto(html, d.body);
      return d;
    }
  }
  const init = new DOMParser().parseFromString(initialHtml);
  doc.head.childNodes = init.head.childNodes; for (const c of doc.head.childNodes) c.parentNode = doc.head;
  doc.body.childNodes = init.body.childNodes; for (const c of doc.body.childNodes) c.parentNode = doc.body;
  resetOpCounts();
  return { document: doc, DOMParser, opCounts, resetOpCounts, serializeNode, serializeChildren };
}

module.exports = { createFakeDOM };

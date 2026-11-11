#!/usr/bin/env python3.13
"""Tiklanabilir etkilesimsiz `agent observe` girdileri (11.11). Yalniz olcum; src/ dokunulmaz.

Kullanim (arm64, PATH basinda /opt/homebrew/bin):
  python3.13 -I observe-tiklanabilir.py run [url ...]      # toplama (websockets gerekir)
  python3.13 -I observe-tiklanabilir.py rapor              # ham JSON'lardan tablo
  (token sayimi icin tiktoken venv'i alt surec olarak cagrilir)

Paylasilan tarayici 127.0.0.1:9333. Her sayfa icin kendi sekmesi (PUT /json/new) acilir,
iş bitince yalniz o sekme kapatilir. Browser.close yok.
Sinyaller (etkilesimsiz girdinin etkin elemani: metin dugumuyse ust elemani):
  b  cursor:pointer (b_self: elemanda; b_orig: elemanda pointer, ustunde degil)
  c  etiket/oznitelik: a, button, summary, label, [role=etkilesimli], [tabindex], [onclick]
     (c_self: elemanda; c_anc: ilk 3 ustte)
  a  DOMDebugger.getEventListeners click/mousedown/pointerdown/keydown
     (a_self: elemanda; a_anc: ilk 3 ustte)
  d  DOMSnapshot isClickable (Chrome'un kendi sezgisi; tek cagri)
  native: eleman ya da herhangi bir ustu yerel etkilesimli (a[href], button, input, [role=button] ...);
     bu girdi zaten bir etkilesimli girdinin icinde, gizlense de tiklanabilir kalir ("net" sayim bunu eler).
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

HOME = '/Users/nadir/01dev/_worktrees/cdpilot-098'
HAM = '/Users/nadir/01dev/cdpilot-olcum-ham/observe-tikla-2026-11-11'
VENV_PY = '/Users/nadir/01dev/_venvs/tiktoken/bin/python3.13'
PORT = 9333
PAGES = [
    ('react', 'https://react.dev/'),
    ('vue', 'https://vuejs.org/'),
    ('angular', 'https://angular.dev/'),
    ('hn', 'https://news.ycombinator.com/'),
    ('enwiki', 'https://en.wikipedia.org/wiki/Web_browser'),
    ('excalidraw', 'https://excalidraw.com/'),
]

# src/cdpilot.py 15963-15977 ile ayni
INTERACTIVE = {
    'button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'listbox',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'spinbutton',
    'slider', 'switch', 'tab', 'treeitem', 'searchbox', 'gridcell',
}
NORMALIZE = {'textField': 'textbox', 'comboBox': 'combobox', 'checkBox': 'checkbox',
             'radioButton': 'radio'}
SKIP = {'none', 'presentation', 'generic', 'LineBreak', 'InlineTextBox', 'ignored',
        'unknown', 'RootWebArea'}
EVTS = ('click', 'mousedown', 'pointerdown', 'keydown')


def snapshot_to_actions(nodes):
    """src/cdpilot.py _snapshot_to_actions (16475-16515) kopyasi; her girdiye interactive bayragi."""
    out, seen = [], {}
    for node in nodes:
        if node.get('ignored'):
            continue
        raw = node.get('role', {}).get('value', '')
        if not raw or raw in SKIP:
            continue
        role = NORMALIZE.get(raw, raw)
        name = node.get('name', {}).get('value', '') or ''
        bid = node.get('backendDOMNodeId') or node.get('backendNodeId')
        if not bid:
            continue
        inter = role in INTERACTIVE
        anchor = (not inter) and len(name) > 2 and seen.get(name, 0) == 0
        if not inter and not anchor:
            continue
        seen[name] = seen.get(name, 0) + 1
        out.append({'ref': '@%d' % (len(out) + 1), 'role': role, 'name': name, 'bid': bid,
                    'interactive': inter})
    return out


class Cdp:
    def __init__(self, ws):
        self.ws, self.n, self.fut, self.calls = ws, 0, {}, 0

    async def pump(self):
        async for raw in self.ws:
            m = json.loads(raw)
            f = self.fut.pop(m.get('id'), None)
            if f and not f.done():
                f.set_result(m)

    async def send(self, method, params=None, timeout=60):
        self.n += 1
        self.calls += 1
        i = self.n
        f = asyncio.get_running_loop().create_future()
        self.fut[i] = f
        await self.ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
        m = await asyncio.wait_for(f, timeout)
        return m


def http(method, path):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode()


PAGE_FN = r"""function(){
 const U=window.__obsU||(window.__obsU=[]), M=window.__obsM||(window.__obsM=new Map());
 const idx=e=>{let i=M.get(e); if(i===undefined){i=U.length;U.push(e);M.set(e,i);} return i;};
 const IR=['button','link','tab','menuitem','menuitemcheckbox','menuitemradio','checkbox','radio','switch','option','treeitem','combobox','textbox','searchbox','slider','spinbutton','gridcell','listbox'];
 const C=e=>{const t=e.tagName.toLowerCase(); const r=e.getAttribute('role');
  if(['a','button','summary','label'].includes(t)) return 'tag:'+t;
  if(r&&IR.includes(r)) return 'role:'+r;
  if(e.hasAttribute('tabindex')) return 'tabindex';
  if(e.hasAttribute('onclick')) return 'onclick';
  return '';};
 const NAT='a[href],button,input:not([type=hidden]),select,textarea,summary,'+IR.map(r=>'[role='+r+']').join(',');
 const n=this; const el=n.nodeType===1?n:n.parentElement;
 if(!el) return {noel:true,nodeType:n.nodeType};
 const cs=getComputedStyle(el).cursor, par=el.parentElement, pc=par?getComputedStyle(par).cursor:'';
 const chain=[idx(el)]; let a=el, cAnc='';
 for(let k=0;k<3&&a.parentElement;k++){a=a.parentElement; chain.push(idx(a)); if(!cAnc) cAnc=C(a);}
 return {tag:el.tagName.toLowerCase(), cursor:cs, pcursor:pc, c_self:C(el), c_anc:cAnc,
  native:!!el.closest(NAT), chain:chain, txt:n.nodeType!==1};
}"""


async def snapshot_cursor(cdp):
    """DOMSnapshot tek cagri: bid -> {cursor, pcursor, clickable, tag}."""
    t0 = time.time()
    r = await cdp.send('DOMSnapshot.captureSnapshot',
                       {'computedStyles': ['cursor'], 'includeDOMRects': False}, timeout=90)
    ms = (time.time() - t0) * 1000
    res = r.get('result', {})
    strings = res.get('strings', [])
    info = {}
    for doc in res.get('documents', []):
        nd = doc['nodes']
        bids, par, types = nd['backendNodeId'], nd['parentIndex'], nd['nodeType']
        names = nd['nodeName']
        click = set(nd.get('isClickable', {}).get('index', []))
        cur = {}
        lay = doc['layout']
        for ni, st in zip(lay['nodeIndex'], lay['styles']):
            cur[ni] = strings[st[0]] if st and st[0] >= 0 else ''
        for i, b in enumerate(bids):
            info[b] = {'i': i, 'p': par[i], 'type': types[i], 'tag': strings[names[i]].lower(),
                       'cursor': cur.get(i), 'click': i in click, 'doc': doc, 'cur': cur,
                       'click_set': click, 'par': par, 'types': types}
    return info, ms


def snap_signals(info, bid):
    d = info.get(bid)
    if not d:
        return None
    i, par, types = d['i'], d['par'], d['types']
    e = i if types[i] == 1 else par[i]
    if e is None or e < 0:
        return None
    pe = par[e] if par[e] is not None and par[e] >= 0 else None
    cur = d['cur']
    c = cur.get(e)
    pc = cur.get(pe) if pe is not None else None
    return {'cursor': c, 'pointer': c == 'pointer', 'orig': c == 'pointer' and pc != 'pointer',
            'click': e in d['click_set']}


async def wait_content(tid, res, limit=60):
    """Yuklu makinede go bos govdeyle donebilir: readyState complete ve govde metni > 300 bekle."""
    import websockets
    wsurl = [t for t in json.loads(http('GET', '/json/list')) if t['id'] == tid][0]['webSocketDebuggerUrl']
    t0 = time.time()
    async with websockets.connect(wsurl, max_size=None, ping_interval=None) as ws:
        cdp = Cdp(ws)
        pump = asyncio.create_task(cdp.pump())
        ok = False
        while time.time() - t0 < limit:
            r = await cdp.send('Runtime.evaluate', {
                'expression': "document.readyState+'|'+((document.body&&document.body.innerText)||'').length",
                'returnByValue': True})
            v = r.get('result', {}).get('result', {}).get('value', '')
            st, _, n = v.partition('|')
            if st == 'complete' and n.isdigit() and int(n) > 300:
                ok = True
                break
            await asyncio.sleep(2)
        pump.cancel()
    res['content_wait_ms'] = round((time.time() - t0) * 1000)
    res['content_ok'] = ok
    if ok:
        await asyncio.sleep(2)


async def measure(name, url):
    import websockets
    os.makedirs(HAM, exist_ok=True)
    res = {'name': name, 'url': url}
    tid = json.loads(http('PUT', '/json/new?about:blank'))['id']
    res['tab'] = tid
    try:
        env = dict(os.environ, CDP_PORT=str(PORT), CDPILOT_TARGET=tid, CDPILOT_PROJECT_ID='obstikla',
                   PATH='/opt/homebrew/bin:' + os.environ.get('PATH', ''))
        t0 = time.time()
        g = subprocess.run(['node', 'bin/cdpilot.js', '--timeout', '60', 'go', url], cwd=HOME, env=env,
                           capture_output=True, text=True, timeout=90)
        res['go_ms'] = round((time.time() - t0) * 1000)
        res['go_rc'] = g.returncode
        if g.returncode != 0:
            raise RuntimeError('go rc=%s %s' % (g.returncode, (g.stderr or g.stdout)[-200:]))
        await asyncio.sleep(4)  # SPA yerlesmesi
        await wait_content(tid, res)
        t0 = time.time()
        o = subprocess.run(['node', 'bin/cdpilot.js', '--timeout', '60', 'agent', 'observe'], cwd=HOME,
                           env=env, capture_output=True, text=True, timeout=90)
        res['observe_ms'] = round((time.time() - t0) * 1000)
        if o.returncode != 0:
            raise RuntimeError('observe rc=%s %s' % (o.returncode, (o.stderr or o.stdout)[-200:]))
        raw = o.stdout
        with open('%s/observe-%s.json' % (HAM, name), 'w') as f:
            f.write(raw)
        obs = json.loads(raw)
        res['observe_raw'] = raw
        res['observe_n'] = len(obs.get('actions', []))
        res['final_url'] = obs.get('url')
        wsurl = None
        for t in json.loads(http('GET', '/json/list')):
            if t['id'] == tid:
                wsurl = t['webSocketDebuggerUrl']
        async with websockets.connect(wsurl, max_size=None, ping_interval=None) as ws:
            cdp = Cdp(ws)
            pump = asyncio.create_task(cdp.pump())
            await cdp.send('Accessibility.enable')
            c0 = cdp.calls
            t0 = time.time()
            ax = await cdp.send('Accessibility.getFullAXTree', timeout=90)
            res['ax_ms'] = round((time.time() - t0) * 1000)
            entries = snapshot_to_actions(ax['result']['nodes'])
            res['entries_n'] = len(entries)
            res['entries_match_observe'] = (
                len(entries) == res['observe_n']
                and all(e['name'] == a['name'] and e['role'] == a['role']
                        for e, a in zip(entries, obs['actions'])))
            non = [e for e in entries if not e['interactive']]
            # --- yol 1: DOMSnapshot (tek cagri) ---
            snap, snap_ms = await snapshot_cursor(cdp)
            res['snapshot_ms'] = round(snap_ms)
            for e in non:
                e['snap'] = snap_signals(snap, e['bid'])
            # --- yol 2: resolveNode + callFunctionOn (+ getEventListeners) ---
            t0 = time.time()
            c1 = cdp.calls
            await cdp.send('Runtime.evaluate', {'expression': 'window.__obsU=[];window.__obsM=new Map();0'})

            async def one(e):
                try:
                    r = await cdp.send('DOM.resolveNode', {'backendNodeId': e['bid']})
                    oid = r.get('result', {}).get('object', {}).get('objectId')
                    if not oid:
                        e['page'] = {'noobj': True}
                        return
                    v = await cdp.send('Runtime.callFunctionOn',
                                       {'objectId': oid, 'functionDeclaration': PAGE_FN,
                                        'returnByValue': True})
                    e['page'] = v.get('result', {}).get('result', {}).get('value') or {
                        'err': str(v.get('error') or v.get('result'))[:120]}
                except Exception as x:  # olcum: hata kaydedilir
                    e['page'] = {'err': repr(x)[:120]}
            for k in range(0, len(non), 150):
                await asyncio.gather(*[one(e) for e in non[k:k + 150]])
            res['resolve_ms'] = round((time.time() - t0) * 1000)
            res['resolve_calls'] = cdp.calls - c1
            # benzersiz elemanlar -> objectId
            t0 = time.time()
            c2 = cdp.calls
            arr = await cdp.send('Runtime.evaluate', {'expression': 'window.__obsU'})
            aid = arr['result']['result']['objectId']
            props = await cdp.send('Runtime.getProperties', {'objectId': aid, 'ownProperties': True},
                                   timeout=90)
            oids = {}
            for p in props['result']['result']:
                if p['name'].isdigit() and 'value' in p and 'objectId' in p['value']:
                    oids[int(p['name'])] = p['value']['objectId']
            res['unique_elems'] = len(oids)
            lst = {}

            async def lis(i, oid):
                r = await cdp.send('DOMDebugger.getEventListeners', {'objectId': oid})
                ls = r.get('result', {}).get('listeners', [])
                lst[i] = sorted({l['type'] for l in ls if l['type'] in EVTS})
                lst[i] = lst[i] if lst[i] else []
            items = list(oids.items())
            for k in range(0, len(items), 150):
                await asyncio.gather(*[lis(i, o) for i, o in items[k:k + 150]])
            res['listeners_ms'] = round((time.time() - t0) * 1000)
            res['listeners_calls'] = cdp.calls - c2
            for e in non:
                ch = (e.get('page') or {}).get('chain')
                if ch:
                    e['a_self'] = lst.get(ch[0], [])
                    e['a_anc'] = sorted({t for j in ch[1:] for t in lst.get(j, [])})
            # kok kapsayici dinleyicileri (delegasyon)
            roots = {}
            for label, expr in (('document', 'document'), ('window', 'window'),
                                ('html', 'document.documentElement'), ('body', 'document.body'),
                                ('appRoot', "document.querySelector('#root,#app,#__next,[ng-version],"
                                            "#react-root,#__nuxt,#app-root')")):
                r = await cdp.send('Runtime.evaluate', {'expression': expr})
                oid = r.get('result', {}).get('result', {}).get('objectId')
                if oid:
                    q = await cdp.send('DOMDebugger.getEventListeners', {'objectId': oid})
                    roots[label] = sorted({l['type'] for l in q.get('result', {}).get('listeners', [])
                                           if l['type'] in EVTS})
            res['root_listeners'] = roots
            await cdp.send('Runtime.evaluate', {'expression': 'delete window.__obsU;delete window.__obsM;0'})
            pump.cancel()
        res['entries'] = [{k: v for k, v in e.items()} for e in entries]
        res['ok'] = True
    finally:
        try:
            http('GET', '/json/close/%s' % tid)
        except Exception as x:
            res['close_err'] = repr(x)[:100]
    return res


def tokens(strings):
    p = subprocess.run([VENV_PY, '-I', os.path.abspath(__file__), 'tok'], input=json.dumps(strings),
                       capture_output=True, text=True, timeout=120)
    return json.loads(p.stdout)


def tok_main():
    import tiktoken
    enc = tiktoken.get_encoding('o200k_base')
    data = json.loads(sys.stdin.read())
    print(json.dumps([len(enc.encode(s)) for s in data]))


def entry_str(e):
    return json.dumps({'ref': e['ref'], 'role': e['role'], 'name': e['name']}, ensure_ascii=False,
                      separators=(',', ':'))


async def run(pages):
    for name, url in pages:
        out = None
        for attempt in (1, 2):
            try:
                out = await measure(name, url)
                break
            except Exception as x:
                print('%s deneme %d basarisiz: %r' % (name, attempt, x), flush=True)
                out = {'name': name, 'url': url, 'ok': False, 'error': repr(x)[:300]}
        if out.get('ok'):
            raw = out.pop('observe_raw')
            toks = tokens([entry_str(e) for e in out['entries']] + [raw.strip()])
            out['obs_total_tok'] = toks[-1]
            for e, t in zip(out['entries'], toks[:-1]):
                e['tok'] = t
        else:
            out.pop('observe_raw', None)
        with open('%s/olcum-%s.json' % (HAM, name), 'w') as f:
            json.dump(out, f, ensure_ascii=False)
        print(name, 'ok' if out.get('ok') else 'FAIL', out.get('entries_n'), flush=True)


def classify(e):
    """Etkilesimsiz girdi icin sinyaller (resolve yolu; yoksa snapshot)."""
    pg = e.get('page') or {}
    sn = e.get('snap') or {}
    b_self = pg.get('cursor') == 'pointer' if pg.get('cursor') else bool(sn.get('pointer'))
    b_orig = (pg.get('cursor') == 'pointer' and pg.get('pcursor') != 'pointer') if pg.get('cursor') \
        else bool(sn.get('orig'))
    c_self, c_anc = pg.get('c_self') or '', pg.get('c_anc') or ''
    a_self, a_anc = e.get('a_self') or [], e.get('a_anc') or []
    return {'b': b_self, 'b_orig': b_orig, 'c_self': bool(c_self), 'c': bool(c_self or c_anc),
            'a_self': bool(a_self), 'a': bool(a_self or a_anc), 'd': bool(sn.get('click')),
            'native': bool(pg.get('native')), 'snap_b': bool(sn.get('pointer')),
            'res_b': pg.get('cursor') == 'pointer' if pg.get('cursor') else None}


def rapor():
    rows = []
    for name, _ in PAGES + [('todomvc', '')]:
        p = '%s/olcum-%s.json' % (HAM, name)
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        if not d.get('ok'):
            rows.append((name, d, None))
            continue
        rows.append((name, d, [(e, classify(e)) for e in d['entries'] if not e['interactive']]))
    sums = []
    for name, d, non in rows:
        if non is None:
            print('%s: BASARISIZ %s' % (name, d.get('error')))
            continue
        ents = d['entries']
        n_int = sum(1 for e in ents if e['interactive'])
        tot_tok = d['obs_total_tok']
        non_tok = sum(e['tok'] for e, _ in non)

        def cnt(f):
            return sum(1 for e, c in non if f(c))

        def tk(f):
            return sum(e['tok'] for e, c in non if f(c))
        rules = {
            'b': lambda c: c['b'], 'b_orig': lambda c: c['b_orig'], 'c': lambda c: c['c'],
            'a': lambda c: c['a'], 'd': lambda c: c['d'],
            'net_b': lambda c: c['b'] and not c['native'],
            'net_b_orig': lambda c: c['b_orig'] and not c['native'],
            'net_c': lambda c: c['c'] and not c['native'],
            'net_a': lambda c: c['a'] and not c['native'],
            'net_d': lambda c: c['d'] and not c['native'],
            'net_bc': lambda c: (c['b'] or c['c']) and not c['native'],
            'net_bcad': lambda c: (c['b'] or c['c'] or c['a'] or c['d']) and not c['native'],
            'net_bd': lambda c: (c['b'] or c['d']) and not c['native'],
        }
        s = {'name': name, 'total': len(ents), 'inter': n_int, 'non': len(non), 'non_tok': non_tok,
             'obs_tok': tot_tok, 'cnt': {k: cnt(f) for k, f in rules.items()},
             'tok': {k: tk(f) for k, f in rules.items()},
             'native_n': cnt(lambda c: c['native']),
             'snap_vs_res_b_diff': sum(1 for e, c in non if c['res_b'] is not None and c['res_b'] != c['snap_b']),
             'ms': {k: d.get(k) for k in ('observe_ms', 'ax_ms', 'snapshot_ms', 'resolve_ms',
                                          'listeners_ms', 'resolve_calls', 'listeners_calls',
                                          'unique_elems')},
             'match': d.get('entries_match_observe'), 'roots': d.get('root_listeners'),
             'noel': sum(1 for e, _ in non if (e.get('page') or {}).get('noel')),
             'perr': sum(1 for e, _ in non if (e.get('page') or {}).get('err') or (e.get('page') or {}).get('noobj'))}
        ex = []
        for e, c in non:
            if (c['b'] or c['c'] or c['a'] or c['d']) and not c['native']:
                pg = e.get('page') or {}
                ex.append({'role': e['role'], 'name': e['name'][:50], 'tag': pg.get('tag'),
                           'sig': [k for k in ('b', 'c', 'a', 'd') if c[k]], 'tok': e['tok']})
        s['examples'] = ex[:6]
        # rol dagilimi net_bcad
        roles = {}
        for e, c in non:
            if rules['net_bcad'](c):
                roles[e['role']] = roles.get(e['role'], 0) + 1
        s['net_roles'] = roles
        sums.append(s)
    json.dump(sums, open('%s/ozet.json' % HAM, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(sums, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if mode == 'tok':
        tok_main()
    elif mode == 'rapor':
        rapor()
    else:
        sel = sys.argv[2:]
        pages = [p for p in PAGES if p[0] in sel] if sel else PAGES
        if sel and not pages:
            pages = [(s.split('=')[0], s.split('=', 1)[1]) for s in sel if '=' in s]
        asyncio.run(run(pages))

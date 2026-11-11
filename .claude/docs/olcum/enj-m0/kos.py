"""M0 ölçüm koşucusu. /opt/homebrew/bin/python3 -I kos.py  (websockets gerekir)."""
import asyncio, glob, json, os, subprocess, time, urllib.request
import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../../../.."))
ENV = dict(os.environ, CDPILOT_HOME="/private/tmp/claude-501/m0home",
           PATH="/opt/homebrew/bin:" + os.environ["PATH"], CDPILOT_NO_AUTOLAUNCH="1")
STY = ["display", "visibility", "opacity", "font-size", "color", "background-color",
       "transform", "clip-path", "position", "overflow", "text-indent"]


def cli(args, target=None):
    env = dict(ENV)
    if target:
        env["CDPILOT_TARGET"] = target
    r = subprocess.run(["node", os.path.join(ROOT, "bin/cdpilot.js")] + args, env=env, cwd=ROOT,
                       capture_output=True, text=True, timeout=90)
    return r.stdout + (("\n[stderr] " + r.stderr) if r.returncode else "")


def where_observe(out, mk):
    try:
        j = json.loads(out)
    except Exception:
        return "ayrıştırılamadı"
    w = []
    if mk in json.dumps(j.get("actions", []), ensure_ascii=False):
        w.append("actions")
    if mk in (j.get("text") or ""):
        w.append("text")
    if mk in json.dumps(j.get("injection_suspect", []), ensure_ascii=False):
        w.append("suspect")
    if not w and mk in out:
        w.append("diğer")
    return "+".join(w) if w else "yok"


class Br:
    def __init__(self, ws):
        self.ws, self.i = ws, 0

    async def call(self, m, p=None, sid=None):
        self.i += 1
        msg = {"id": self.i, "method": m, "params": p or {}}
        if sid:
            msg["sessionId"] = sid
        await self.ws.send(json.dumps(msg))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.i:
                if "error" in r:
                    raise RuntimeError(m + " " + json.dumps(r["error"])[:200])
                return r["result"]


async def domsnap(br, target, mk):
    at = await br.call("Target.attachToTarget", {"targetId": target, "flatten": True})
    sid = at["sessionId"]
    lm = await br.call("Page.getLayoutMetrics", sid=sid)
    vw = lm["cssVisualViewport"]
    res = await br.call("DOMSnapshot.captureSnapshot",
                        {"computedStyles": STY, "includeDOMRects": True}, sid=sid)
    await br.call("Target.detachFromTarget", {"sessionId": sid})
    r = {"result": res}
    res = r["result"]
    S = res["strings"]
    sg = lambda i: S[i] if i >= 0 else ""
    hits = []
    for di, d in enumerate(res["documents"]):
        nodes = d["nodes"]
        nv = nodes.get("nodeValue", [])
        attrs = nodes.get("attributes", [])
        ntype = nodes["nodeType"]
        parent = nodes["parentIndex"]
        nname = nodes["nodeName"]
        lay = d["layout"]
        lmap = {n: k for k, n in enumerate(lay["nodeIndex"])}
        found = []
        for i in range(len(ntype)):
            if i < len(nv) and sg(nv[i]) and mk in sg(nv[i]) and (parent[i] < 0 or sg(nname[parent[i]]) not in ("SCRIPT", "STYLE")):
                found.append((i, "node" + str(ntype[i])))
            for a in (attrs[i] if i < len(attrs) else []):
                pass
            at = attrs[i] if i < len(attrs) else []
            for k in range(1, len(at), 2):
                if mk in sg(at[k]):
                    found.append((i, "attr:" + sg(at[k - 1])))
        for i, kind in found:
            el = i
            while el >= 0 and (ntype[el] != 1) and el not in lmap and ntype[el] != 3:
                el = parent[el]
            has_layout = i in lmap
            host = i if has_layout else None
            # stil: metin düğümünün ebeveyni, öğe ise kendisi
            st_node = parent[i] if ntype[i] in (3, 8) else i
            while st_node >= 0 and st_node not in lmap:
                st_node = parent[st_node]
            rec = {"doc": di, "kind": kind, "nodeName": sg(nname[i]) if i < len(nname) else "",
                   "layout": has_layout}
            if has_layout:
                b = lay["bounds"][lmap[i]]
                rec["bounds"] = [round(x, 1) for x in b]
                rec["text_in_layout"] = bool(lay.get("text") and sg(lay["text"][lmap[i]]))
            if st_node >= 0:
                st = lay["styles"][lmap[st_node]]
                rec["styles"] = {STY[k]: sg(v) for k, v in enumerate(st)}
                rec["style_bounds"] = [round(x, 1) for x in lay["bounds"][lmap[st_node]]]
                # arka plan: ata zinciri
                bg, a = "", st_node
                while a >= 0:
                    if a in lmap:
                        row_st = lay["styles"][lmap[a]]
                        v = sg(row_st[STY.index("background-color")]) if len(row_st) > STY.index("background-color") else ""
                        if v and v != "rgba(0, 0, 0, 0)":
                            bg = v
                            break
                    a = parent[a]
                rec["bg_eff"] = bg or "rgba(0,0,0,0)"
            hits.append(rec)
    return {"viewport": [vw["clientWidth"], vw["clientHeight"]], "hits": hits}


def sinyal(rec, vp):
    """Tasarım §4.1 etiketleri için ölçülebilir sinyal."""
    if not rec["hits"]:
        return "metin DOMSnapshot'ta yok"
    h = rec["hits"][0]
    if h["kind"] == "node8":
        return "yorum düğümü (yerleşimsiz)"
    if h["kind"].startswith("attr:"):
        return f"öznitelik {h['kind'][5:]} (görünür metin değil)"
    if not h["layout"]:
        return "no_layout (display:none/hidden/noscript sınıfı)"
    s = h.get("styles", {})
    b = h["bounds"]
    sb = h.get("style_bounds", b)
    out = []
    if s.get("visibility") == "hidden":
        out.append("visibility:hidden")
    try:
        if float(s.get("opacity", "1")) < 0.1:
            out.append("transparent(opacity)")
    except ValueError:
        pass
    try:
        if float(s.get("font-size", "16").replace("px", "")) < 4:
            out.append("tiny(font-size<4)")
    except ValueError:
        pass
    if b[0] + b[2] <= 0 or b[1] + b[3] <= 0 or b[0] >= vp[0] + 2000:
        out.append("offscreen(bounds)")
    if b[2] * b[3] <= 4 and not out:
        out.append("tiny(alan<=4px2)")
    if s.get("color") and s.get("color") == h.get("bg_eff"):
        out.append("camouflage(renk=zemin)")
    if "scale" in s.get("transform", "") or s.get("transform", "none") not in ("none", ""):
        out.append(f"transform={s.get('transform')} bounds={b}")
    if s.get("clip-path", "none") not in ("none", ""):
        out.append("clip-path=" + s["clip-path"])
    if sb[2] * sb[3] == 0 or (sb[3] == 0 or sb[2] == 0):
        out.append("0 boyut kutu")
    if s.get("text-indent", "0px") not in ("0px", ""):
        out.append("text-indent=" + s["text-indent"])
    return "; ".join(out) if out else "sinyal yok (görünür gibi)"


async def amain():
    names = sorted(os.path.basename(p)[:-5] for p in glob.glob(HERE + "/sayfalar/*.html")
                   if not p.endswith("-inner.html"))
    bw = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json/version"))["webSocketDebuggerUrl"]
    rows = []
    loop = asyncio.get_running_loop()
    async with websockets.connect(bw, max_size=None) as ws:
        br = Br(ws)
        for n in names:
            url = f"http://127.0.0.1:3470/{n}.html"
            ctx = (await br.call("Target.createBrowserContext"))["browserContextId"]
            t = (await br.call("Target.createTarget", {"url": url, "browserContextId": ctx}))["targetId"]
            await asyncio.sleep(2.5)
            mk = f"m0-{n}.invalid"
            try:
                snap = await domsnap(br, t, mk)
            except Exception as e:
                import traceback
                snap = {"viewport": [0, 0], "hits": [], "hata": traceback.format_exc()[-400:]}
            o = {}
            for k, a in (("observe", ["agent", "observe"]), ("observe_full", ["agent", "observe", "--full"]),
                         ("content", ["content"]), ("a11y", ["a11y"]), ("a11y_snapshot", ["a11y-snapshot"])):
                o[k] = await loop.run_in_executor(None, cli, a, t)
            await br.call("Target.closeTarget", {"targetId": t})
            await br.call("Target.disposeBrowserContext", {"browserContextId": ctx})
            row = {"teknik": n, "isaret": mk,
                   "observe": where_observe(o["observe"], mk),
                   "observe_full": where_observe(o["observe_full"], mk),
                   "content": mk in o["content"],
                   "a11y": mk in o["a11y"],
                   "a11y_snapshot": mk in o["a11y_snapshot"],
                   "injection_suspect": "suspect" in where_observe(o["observe"], mk),
                   "domsnapshot_sinyal": sinyal(snap, snap["viewport"]),
                   "domsnapshot_ham": snap}
            rows.append(row)
            with open(f"{HERE}/ham/{n}.txt", "w", encoding="utf-8") as fh:
                for k, v in o.items():
                    fh.write(f"=== {k}\n{v[:1800]}\n")
                fh.write("=== domsnapshot\n" + json.dumps(snap, ensure_ascii=False)[:1800] + "\n")
            print(n, row["observe"], row["content"], row["a11y"], row["domsnapshot_sinyal"], flush=True)
    return rows


def main():
    rows = asyncio.run(amain())
    with open(HERE + "/sonuc.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


import sys
main() if len(sys.argv) < 2 else None

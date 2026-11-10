#!/bin/zsh
# SPA settle: after `go` returns, sample document.body.innerText.length and pending requests every 100 ms for 2 s.
# Shared headless Chrome 9333 via connect; warm process. usage: olc-spa.sh <url> [<url>…]
cd "$(dirname "$0")/../../.."  # repo kökü
H=$(mktemp -d); export CDPILOT_HOME="$H" CDPILOT_LOG=0 CDPILOT_DAEMON=1 CDPILOT_DAEMON_IDLE=120
node bin/cdpilot.js connect 9333 >/dev/null 2>&1; node bin/cdpilot.js version >/dev/null; sleep 1
for url in "$@"; do
  echo "=== $url  yük: $(uptime | sed 's/.*averages: //')"
  t0=$(perl -MTime::HiRes=time -e 'printf "%d", time*1000')
  node bin/cdpilot.js go "$url" >/dev/null 2>&1; rc=$?
  t1=$(perl -MTime::HiRes=time -e 'printf "%d", time*1000'); echo "go rc=$rc $((t1-t0)) ms"
  node bin/cdpilot.js eval "window.__o=[];window.__t0=performance.now();new PerformanceObserver(l=>{}).observe({type:'resource',buffered:true});setInterval(()=>{window.__o.push([Math.round(performance.now()-window.__t0),(document.body&&document.body.innerText||'').length,performance.getEntriesByType('resource').length])},100);'ok'" >/dev/null 2>&1
  sleep 2.2
  node bin/cdpilot.js eval "JSON.stringify(window.__o)" 2>/dev/null | /usr/bin/python3 -I -c '
import json,sys
raw=sys.stdin.read().strip()
try:
    o=json.loads(json.loads(raw) if raw.startswith("\"") else raw)
except Exception as e:
    print("  örnekleme okunamadı:", raw[:120]); sys.exit(0)
prev=None; last_change=0
for t,n,r in o:
    if prev is not None and (n!=prev[0] or r!=prev[1]): last_change=t
    prev=(n,r)
print(f"  örnek {len(o)}, innerText {o[0][1] if o else 0} → {o[-1][1] if o else 0}, kaynak {o[0][2] if o else 0} → {o[-1][2] if o else 0}, son değişim +{last_change} ms (go dönüşünden sonra)")
print("  eğri:", " ".join(f"{t}:{n}/{r}" for t,n,r in o[::3]))'
done
node bin/cdpilot.js daemon stop >/dev/null
for id in $(curl -s http://127.0.0.1:9333/json | /usr/bin/python3 -I -c "import json,sys; urls=sys.argv[1:]; print(' '.join(t['id'] for t in json.load(sys.stdin) if t.get('type')=='page' and any(t.get('url','').startswith(u.rstrip('/')) for u in urls)))" "$@"); do curl -s "http://127.0.0.1:9333/json/close/$id" >/dev/null; echo "sekme kapatıldı: $id"; done

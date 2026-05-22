#!/usr/bin/env bash
# Vivaldi'yi CDP modunda başlat (port 9227).
# Default profili kullanıyor (yani @cdpilot_dev login burada).
# Vivaldi açıksa önce kapat.

set -e

PORT=9227
APP="/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"
PROFILE="$HOME/Library/Application Support/Vivaldi"

if ! command -v lsof >/dev/null 2>&1; then
  echo "lsof yok, terminal'i restart et"; exit 1
fi

# Vivaldi açıksa kapat
if pgrep -x "Vivaldi" >/dev/null 2>&1; then
  echo "→ Vivaldi açık, kapatılıyor..."
  osascript -e 'quit app "Vivaldi"' || true
  sleep 3
  # Hala duruyorsa kill
  if pgrep -x "Vivaldi" >/dev/null 2>&1; then
    pkill -x "Vivaldi" || true
    sleep 2
  fi
fi

# CDP port'unda dinleyen başka şey var mı?
if lsof -nP -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
  echo "⚠ Port $PORT dinleniyor — başka şey kapatmalı"
  lsof -nP -iTCP:$PORT -sTCP:LISTEN
  exit 1
fi

echo "→ Vivaldi CDP modunda başlatılıyor (port $PORT)..."
"$APP" \
  --remote-debugging-port=$PORT \
  --user-data-dir="$PROFILE" \
  --restore-last-session \
  > /tmp/vivaldi-cdp.log 2>&1 &

# CDP cevap verene kadar bekle
for i in {1..20}; do
  sleep 1
  if curl -sf --max-time 2 "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; then
    echo "✓ Vivaldi CDP hazır → http://127.0.0.1:$PORT/json/version"
    curl -s "http://127.0.0.1:$PORT/json/version" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  Browser: {d.get(\"Browser\")}')"
    exit 0
  fi
done

echo "✗ CDP 20 saniye içinde cevap vermedi. /tmp/vivaldi-cdp.log:"
tail -20 /tmp/vivaldi-cdp.log
exit 1

#!/usr/bin/env bash
# Chrome'u Xvfb ile başlat, port 9222 dinlemesini doğrula
set +e

pkill -f "google-chrome" 2>/dev/null
pkill -f "Xvfb" 2>/dev/null
sleep 1

echo "→ Starting Chrome under Xvfb..."
nohup xvfb-run -a --server-args="-screen 0 1280x800x24" \
  /usr/bin/google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/opt/cdpilot-twitter-bot/profile \
  --no-first-run \
  --no-default-browser-check \
  --window-size=1280,800 \
  --no-sandbox \
  > /tmp/chrome-launch.log 2>&1 &

CHROME_PID=$!
echo "Chrome PID: $CHROME_PID"
sleep 6

echo "--- Process check ---"
ps aux | grep -E "google-chrome|Xvfb" | grep -v grep | head -5

echo "--- Port 9222 check ---"
ss -ltnp 2>/dev/null | grep 9222 || echo "NOT_LISTENING"

echo "--- CDP version endpoint ---"
curl -s --max-time 3 http://127.0.0.1:9222/json/version 2>&1 | head -10

echo "--- Chrome log tail ---"
tail -20 /tmp/chrome-launch.log

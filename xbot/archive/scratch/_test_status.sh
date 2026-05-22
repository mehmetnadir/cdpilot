#!/usr/bin/env bash
# Server-side Twitter status check via cdpilot
set +e

# Eski Chrome'ları öldür
pkill -f "google-chrome" 2>/dev/null
pkill -f "Xvfb" 2>/dev/null
sleep 2

# Tek Chrome başlat
echo "→ Starting clean Chrome..."
nohup xvfb-run -a --server-args="-screen 0 1280x800x24" \
  /usr/bin/google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/opt/cdpilot-twitter-bot/profile \
  --no-first-run --no-default-browser-check \
  --no-sandbox \
  --window-size=1280,800 \
  > /tmp/chrome.log 2>&1 &
sleep 6

# Status check
echo "--- CDP version ---"
curl -s --max-time 3 http://127.0.0.1:9222/json/version | python3 -c "import sys,json;d=json.load(sys.stdin);print(f\"Browser: {d['Browser']}\")"

echo "--- Twitter status (via cdpilot) ---"
export CDP_PORT=9222
export CDPILOT_PROFILE=/opt/cdpilot-twitter-bot/profile
export DISPLAY=:99
cdpilot agent twitter status 2>&1 | tail -5

echo "--- Eval: current URL + handle ---"
cdpilot eval '(()=>{return {url: location.href, handle: document.querySelector("[data-testid=SideNav_AccountSwitcher_Button]")?.innerText?.split("\n").pop() || null}})()' 2>&1 | tail -5

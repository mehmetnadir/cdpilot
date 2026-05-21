#!/usr/bin/env bash
# Server-side: x.com'a navigate et + cookies snapshot'ı inject et.
# cdpilot-chrome.service başarıyla başlatıldıktan sonra çağrılır.

LOG=/opt/cdpilot-twitter-bot/logs/cookies.log
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1

echo "[$(date)] === inject-cookies.sh starting ==="

# 1. CDP port hazır mı?
for i in {1..20}; do
  if curl -s --max-time 2 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    echo "[$(date)] CDP ready"
    break
  fi
  sleep 1
done

# 2. x.com'a navigate (cookies'in domain'i için page gerekiyor)
cdpilot go https://x.com 2>&1 | tail -2
sleep 2

# 3. Cookies'i yükle
SNAPSHOT=/opt/cdpilot-twitter-bot/cookies-snapshot.json
if [ -f "$SNAPSHOT" ]; then
  cdpilot cookies load "$SNAPSHOT" 2>&1
else
  echo "[$(date)] WARN: cookies snapshot missing"
fi

# 4. Login state doğrula
sleep 1
cdpilot go https://x.com/home 2>&1 | tail -2
sleep 3
RESULT=$(cdpilot eval "(()=>({loggedIn:!!document.querySelector(\"[data-testid=AppTabBar_Home_Link]\")}))()" 2>&1 | tail -3)
echo "[$(date)] Verify: $RESULT"

# Login false ise exit 1 (service'i fail göster)
if ! echo "$RESULT" | grep -q '"loggedIn": true'; then
  echo "[$(date)] ERROR: login verification failed"
  exit 1
fi

echo "[$(date)] === inject-cookies.sh complete ==="

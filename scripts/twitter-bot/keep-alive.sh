#!/usr/bin/env bash
# Server-side: Chrome session'ını canlı tut.
# x.com'a periyodik navigation Twitter'a "kullanıcı aktif" sinyali verir,
# session cookie'lerini otomatik refresh ettirir.
#
# Alert tipleri:
#   - "chrome-down": Chrome service'i çalışmıyor (transient — restart bekle)
#   - "session-lost": Chrome çalışıyor AMA login state false (cookies expire)
# Mac watcher sadece session-lost'u izler; chrome-down systemd auto-handle eder.

LOG=/opt/cdpilot-twitter-bot/logs/keep-alive.log
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1

export CDP_PORT=9222
export CDPILOT_PROFILE=/opt/cdpilot-twitter-bot/profile
export DISPLAY=:99

ALERT_DIR=/opt/cdpilot-twitter-bot/alerts
mkdir -p "$ALERT_DIR"

echo "[$(date)] keep-alive run"

# 1. CDP up mu? — 3 retry × 10sn (Chrome restart tolerance)
CDP_OK=0
for attempt in 1 2 3; do
  if curl -s --max-time 3 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    CDP_OK=1
    break
  fi
  echo "[$(date)] CDP not ready, attempt $attempt/3 — waiting 10s..."
  sleep 10
done

if [ "$CDP_OK" = "0" ]; then
  # Chrome 30sn boyunca up değil — transient değil, gerçek problem
  echo "[$(date)] WARN: Chrome down for 30+ seconds"
  # Yalnızca log, alert dosyası YAZMA — systemd Chrome'u restart ediyor
  # Eğer 3 üst üste fail olursa o zaman alert (counter dosyası ile)
  COUNTER=/opt/cdpilot-twitter-bot/.chrome-down-counter
  CNT=$(cat "$COUNTER" 2>/dev/null || echo 0)
  CNT=$((CNT + 1))
  echo "$CNT" > "$COUNTER"
  if [ "$CNT" -ge 3 ]; then
    ALERT_FILE="$ALERT_DIR/chrome-down-$(date +%Y-%m-%d-%H%M).txt"
    cat > "$ALERT_FILE" <<EOF
Chrome service down 3+ ardışık keep-alive çevriminde at $(date)
systemd auto-restart başarısız olmuş olabilir.

ACTION: ssh srv21 'systemctl --user status cdpilot-chrome.service'
EOF
    echo "[$(date)] ALERT: chrome-down (counter=$CNT), wrote $ALERT_FILE"
    echo 0 > "$COUNTER"  # reset
  fi
  exit 1
fi

# Counter reset (Chrome up)
echo 0 > /opt/cdpilot-twitter-bot/.chrome-down-counter

# 2. x.com/home'a navigate — session refresh tetikler
cdpilot go https://x.com/home 2>&1 | tail -1
sleep 4

# 3. Login durumunu doğrula
RESULT=$(cdpilot eval "(()=>({loggedIn:!!document.querySelector(\"[data-testid=AppTabBar_Home_Link]\"), url: location.href}))()" 2>&1 | tail -3)
echo "[$(date)] $RESULT"

if echo "$RESULT" | grep -q '"loggedIn": true'; then
  # Login OK, session-lost counter da reset
  echo 0 > /opt/cdpilot-twitter-bot/.session-lost-counter
  echo "[$(date)] OK"
  exit 0
fi

# Session lost — 2 ardışık fail gerekli, ilk fail'de alert atma
SESSION_COUNTER=/opt/cdpilot-twitter-bot/.session-lost-counter
SCNT=$(cat "$SESSION_COUNTER" 2>/dev/null || echo 0)
SCNT=$((SCNT + 1))
echo "$SCNT" > "$SESSION_COUNTER"

if [ "$SCNT" -lt 2 ]; then
  echo "[$(date)] Session check failed (counter=$SCNT), waiting next cycle to confirm"
  exit 1
fi

# 2+ ardışık fail — gerçek session lost
ALERT_FILE="$ALERT_DIR/session-lost-$(date +%Y-%m-%d-%H%M).txt"
cat > "$ALERT_FILE" <<EOF
Session lost at $(date) — 2 ardışık keep-alive cycle'da login=false
URL: $(echo "$RESULT" | grep url)

ACTION REQUIRED:
1. Mac'te terminal aç (Cowork'e gelmen şart değil)
2. cd ~/01dev/cdpilot && python3 src/cdpilot.py launch
3. Açılan tarayıcıda x.com'a manuel login ol
4. bash ~/01dev/cdpilot/scripts/twitter-bot/refresh-cookies-mac.sh
EOF
echo "[$(date)] ALERT: session-lost confirmed (counter=$SCNT), wrote $ALERT_FILE"
echo 0 > "$SESSION_COUNTER"  # reset
exit 2

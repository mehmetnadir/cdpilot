#!/usr/bin/env bash
# Server-side: çalışan Chrome'dan canlı cookies'i snapshot olarak yaz.
# Bu, Chrome restart durumunda inject-cookies.sh için en taze fallback'i sağlar.

LOG=/opt/cdpilot-twitter-bot/logs/snapshot.log
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1

export CDP_PORT=9222
export CDPILOT_PROFILE=/opt/cdpilot-twitter-bot/profile
export DISPLAY=:99

echo "[$(date)] snapshot run"

# CDP up mu?
if ! curl -s --max-time 3 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
  echo "[$(date)] CDP not reachable, skipping"
  exit 0
fi

SNAPSHOT=/opt/cdpilot-twitter-bot/cookies-snapshot.json
BACKUP_DIR=/opt/cdpilot-twitter-bot/backups
mkdir -p "$BACKUP_DIR"

# Mevcut snapshot'ı yedekle
if [ -f "$SNAPSHOT" ]; then
  cp "$SNAPSHOT" "$BACKUP_DIR/cookies-$(date +%Y%m%d-%H%M).json"
  # 7 günden eski yedekleri temizle
  find "$BACKUP_DIR" -name 'cookies-*.json' -mtime +7 -delete
fi

# Canlı Chrome'dan cookies'i export et
cdpilot cookies save "$SNAPSHOT" x.com 2>&1 | tail -3

# Hangi domain ve kaç cookie kaydedildi
COUNT=$(python3 -c "import json; print(len(json.load(open('$SNAPSHOT'))))" 2>/dev/null)
echo "[$(date)] saved $COUNT cookies"

#!/usr/bin/env bash
# Mac-side: srv21'den alert dosyalarını kontrol et, varsa notification göster.
# launchd tarafından her 15dk çalıştırılır.

set +e

STATE_DIR="$HOME/cdpilot-twitter-data/state"
mkdir -p "$STATE_DIR"
LAST_SEEN="$STATE_DIR/last-alert-seen.txt"

# srv21'den SADECE session-lost alert'lerini al (chrome-down ignore — systemd handle ediyor)
ALERTS=$(ssh -o ConnectTimeout=5 srv21 'ls -t /opt/cdpilot-twitter-bot/alerts/session-lost-*.txt 2>/dev/null | head -5' 2>/dev/null)

if [ -z "$ALERTS" ]; then
  exit 0  # alert yok
fi

# En son alert dosyası
NEWEST=$(echo "$ALERTS" | head -1)

# Daha önce gördük mü?
SEEN=""
[ -f "$LAST_SEEN" ] && SEEN=$(cat "$LAST_SEEN")

if [ "$NEWEST" = "$SEEN" ]; then
  exit 0  # zaten görüldü
fi

# Sadece dosya adı geldi, full path için basename
NAME=$(basename "$NEWEST")
# Alert içeriği
CONTENT=$(ssh srv21 "cat $NEWEST" 2>/dev/null | head -5)

# macOS notification
osascript -e "display notification \"$NAME — Mac'te re-login + refresh-cookies-mac.sh çalıştır\" with title \"cdpilot Twitter ALERT\" subtitle \"Session lost\" sound name \"Glass\""

# Görüldü olarak işaretle
echo "$NEWEST" > "$LAST_SEEN"

# Console log
echo "$(date) ALERT: $NAME — $CONTENT"

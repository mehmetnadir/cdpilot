#!/usr/bin/env bash
# Mac-side: oturum düştüğünde manuel re-login sonrası
# fresh cookies'i Mac'ten srv21'e gönder.
#
# Akış:
#   1) Mac'te cdpilot launch (varsa atla)
#   2) Vivaldi/Chrome açıldığında x.com'a manuel login ol
#   3) Bu script'i çalıştır
#   4) Cookies srv21'e gönderilir + Chrome service restart edilir

set -e

PYTHON=/opt/homebrew/bin/python3.13
CDPILOT_DIR=/Users/nadir/01dev/cdpilot

echo "→ Exporting cookies from Mac Vivaldi..."
"$PYTHON" "$CDPILOT_DIR/src/cdpilot.py" cookies save /tmp/x-cookies-fresh.json x.com

CNT=$(python3 -c "import json; print(len(json.load(open('/tmp/x-cookies-fresh.json'))))")
echo "  → $CNT cookies"

echo "→ Uploading to srv21..."
scp /tmp/x-cookies-fresh.json srv21:/opt/cdpilot-twitter-bot/cookies-snapshot.json

echo "→ Restarting Chrome + cookies services..."
ssh srv21 'systemctl --user restart cdpilot-chrome.service && sleep 10 && systemctl --user restart cdpilot-cookies.service && sleep 5 && systemctl --user is-active cdpilot-cookies.service && tail -5 /opt/cdpilot-twitter-bot/logs/cookies.log'

echo
echo "✓ Refresh complete. Yeni session ile devam ediyor."

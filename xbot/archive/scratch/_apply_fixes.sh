#!/usr/bin/env bash
set +e

# Eski yanlış pozitif alert'leri sil
rm -f /opt/cdpilot-twitter-bot/alerts/session-lost-*.txt
rm -f /opt/cdpilot-twitter-bot/.chrome-down-counter
rm -f /opt/cdpilot-twitter-bot/.session-lost-counter

# Service reload + restart
systemctl --user daemon-reload
systemctl --user restart cdpilot-chrome.service
sleep 12
systemctl --user restart cdpilot-cookies.service
sleep 5

echo "--- chrome ---"
systemctl --user is-active cdpilot-chrome.service
echo "--- cookies ---"
systemctl --user is-active cdpilot-cookies.service

# Keep-alive'ı şimdi manuel tetikle, alert yok pozitifini test et
echo "--- keep-alive test ---"
systemctl --user start cdpilot-keep-alive.service
sleep 8
tail -10 /opt/cdpilot-twitter-bot/logs/keep-alive.log

echo "--- alerts dir ---"
ls /opt/cdpilot-twitter-bot/alerts/ 2>&1

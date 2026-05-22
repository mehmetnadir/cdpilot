#!/usr/bin/env bash
# Remote: services'i yükle, restart, doğrula
set +e

chmod +x /opt/cdpilot-twitter-bot/inject-cookies.sh
chmod +x /opt/cdpilot-twitter-bot/run-chrome.sh

systemctl --user daemon-reload
systemctl --user enable cdpilot-cookies.service 2>&1 | head -3
systemctl --user restart cdpilot-chrome.service
sleep 12
systemctl --user start cdpilot-cookies.service
sleep 4

echo "--- chrome ---"
systemctl --user is-active cdpilot-chrome.service
echo "--- cookies ---"
systemctl --user is-active cdpilot-cookies.service
echo "--- executor ---"
systemctl --user is-active cdpilot-twitter-executor.timer

echo "--- cookies log ---"
tail -15 /opt/cdpilot-twitter-bot/logs/cookies.log 2>&1

echo "--- chrome port ---"
ss -ltnp 2>/dev/null | grep 9222 | head -1

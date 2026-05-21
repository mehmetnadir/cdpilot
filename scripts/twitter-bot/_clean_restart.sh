#!/usr/bin/env bash
# Fresh start: tüm Chrome/Xvfb öldür, service'leri sırayla aç, login doğrula

set +e

echo "→ Killing all chrome/Xvfb..."
systemctl --user stop cdpilot-chrome.service cdpilot-cookies.service 2>/dev/null
pkill -9 -f google-chrome 2>/dev/null
pkill -9 -f Xvfb 2>/dev/null
sleep 3

# Eski socket / lock dosyaları temizle
rm -f /opt/cdpilot-twitter-bot/profile/SingletonLock 2>/dev/null
rm -f /opt/cdpilot-twitter-bot/profile/SingletonSocket 2>/dev/null
rm -f /opt/cdpilot-twitter-bot/profile/SingletonCookie 2>/dev/null
rm -f /tmp/.X99-lock 2>/dev/null

echo "→ Starting Chrome service..."
systemctl --user start cdpilot-chrome.service
sleep 15
systemctl --user is-active cdpilot-chrome.service

echo "--- port 9222 ---"
ss -ltnp 2>/dev/null | grep 9222 | head -2

echo "→ curl test ---"
curl -s --max-time 3 http://127.0.0.1:9222/json/version | python3 -c "import sys,json;d=json.load(sys.stdin);print('Browser:', d['Browser'])" 2>&1

echo "→ cdpilot direct test ---"
export CDP_PORT=9222
export CDPILOT_PROFILE=/opt/cdpilot-twitter-bot/profile
export DISPLAY=:99
cdpilot tabs 2>&1 | head -5

echo "→ Inject cookies..."
systemctl --user start cdpilot-cookies.service
sleep 8
tail -10 /opt/cdpilot-twitter-bot/logs/cookies.log

echo "→ Compose check..."
cdpilot go https://x.com/compose/post 2>&1 | tail -1
sleep 3
cdpilot eval "(()=>({url:location.href, hasTextarea:!!document.querySelector('[data-testid=tweetTextarea_0]'), hasPostBtn:!!document.querySelector('[data-testid=tweetButton]')}))()" 2>&1 | tail -5

echo "→ Done"

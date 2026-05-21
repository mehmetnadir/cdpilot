#!/usr/bin/env bash
# Chrome restart sonrası cookies persist ediyor mu test et
set +e

echo "→ Kill manual Chrome processes..."
pkill -f "google-chrome" 2>/dev/null
pkill -f "Xvfb" 2>/dev/null
sleep 3

echo "→ Start via systemd..."
systemctl --user daemon-reload
systemctl --user restart cdpilot-chrome.service
sleep 8

echo "--- Status ---"
systemctl --user status cdpilot-chrome.service --no-pager 2>&1 | head -10

echo "--- Port 9222 check ---"
ss -ltnp 2>/dev/null | grep 9222 | head -2

export CDP_PORT=9222
export CDPILOT_PROFILE=/opt/cdpilot-twitter-bot/profile
export DISPLAY=:99

echo "--- Post-restart compose check ---"
cdpilot go https://x.com/home 2>&1 | tail -2
sleep 3
cdpilot eval '(()=>({url: location.href, loggedIn: !!document.querySelector("[data-testid=AppTabBar_Home_Link]"), hasSignIn: document.body.innerText.includes("Sign in")}))()' 2>&1 | tail -8

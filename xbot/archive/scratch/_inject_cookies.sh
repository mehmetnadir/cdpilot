#!/usr/bin/env bash
# Server-side: x.com'a navigate et, cookies'i yükle, status doğrula
set +e

export CDP_PORT=9222
export CDPILOT_PROFILE=/opt/cdpilot-twitter-bot/profile
export DISPLAY=:99

echo "→ Navigate to x.com..."
cdpilot go https://x.com 2>&1 | tail -3
sleep 2

echo "→ Load cookies from /tmp/x-cookies.json..."
cdpilot cookies load /tmp/x-cookies.json 2>&1 | tail -5

echo "→ Reload to apply cookies..."
cdpilot go https://x.com/home 2>&1 | tail -3
sleep 3

echo "→ Twitter status check..."
cdpilot agent twitter status 2>&1 | tail -3

echo "→ DOM-level handle check..."
cdpilot eval '(()=>{return {url: location.href, handle: document.querySelector("[data-testid=SideNav_AccountSwitcher_Button]")?.innerText?.split("\n").pop() || null, loggedNav: !!document.querySelector("[data-testid=AppTabBar_Home_Link]")}})()' 2>&1 | tail -5

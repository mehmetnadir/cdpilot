#!/usr/bin/env bash
# Server'da cdpilot ile manuel test post
set +e

export CDP_PORT=9222
export CDPILOT_PROFILE=/opt/cdpilot-twitter-bot/profile
export DISPLAY=:99

cd /opt/cdpilot-src

CONTENT="webdriver was designed for cross-browser testing in 2011. cdp was designed to build devtools. one is for compliance, the other for deep surgical control of the engine. different tools, different problems"

echo "→ Attempting post via cdpilot..."
cdpilot agent twitter post "$CONTENT" 2>&1

#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CDPILOT="${CDPILOT:-node $(cd ../.. && pwd)/bin/cdpilot.js}"
export CDPILOT_PYTHON="${CDPILOT_PYTHON:-/usr/local/bin/python3}"
export CDP_PORT="${CDP_PORT:-59925}"
export CHROME_HEADLESS=1

HTTP_PORT=59924

TMP_DIR="$(mktemp -d)"
export CDPILOT_HOME="${TMP_DIR}/home"
export CDPILOT_PROFILE="${TMP_DIR}/prof"
mkdir -p "$CDPILOT_HOME" "$CDPILOT_PROFILE" "${TMP_DIR}/srv" "output"

cp index.html "${TMP_DIR}/srv/"

$CDPILOT_PYTHON -m http.server $HTTP_PORT --directory "${TMP_DIR}/srv" >/dev/null 2>&1 &
SERVER_PID=$!

trap 'kill $SERVER_PID 2>/dev/null || true; $CDPILOT stop >/dev/null 2>&1 || true' EXIT
sleep 1

RAW_LOG="${TMP_DIR}/raw_output.txt"

{
  echo "$ cdpilot browser install chrome-for-testing"
  $CDPILOT browser install chrome-for-testing 2>&1 | sed -e '/^  [0-9]\{1,3\}%/d'

  echo "$ cdpilot ext-install ../../test/fixtures/extension/unpacked"
  $CDPILOT ext-install "../../test/fixtures/extension/unpacked" 2>&1

  echo "$ cdpilot browser chrome-for-testing"
  $CDPILOT browser chrome-for-testing 2>&1

  echo "$ cdpilot go http://127.0.0.1:${HTTP_PORT}/index.html"
  $CDPILOT go "http://127.0.0.1:${HTTP_PORT}/index.html" 2>&1

  echo '$ cdpilot eval "document.documentElement.dataset.cdpilotExt"'
  $CDPILOT eval "document.documentElement.dataset.cdpilotExt" 2>&1

  echo "$ cdpilot browser status"
  $CDPILOT browser status 2>&1

  echo "$ cdpilot shot output/screenshot.png"
  $CDPILOT shot output/screenshot.png 2>&1

  echo "$ cdpilot stop"
  $CDPILOT stop 2>&1
} > "$RAW_LOG"

sed -e "s|${TMP_DIR}|<tmp>|g" -e "s|$(cd "$SCRIPT_DIR/../.." && pwd)|<repo>|g" -e "s|${HOME}|~|g" -e "s|/private/tmp/[^/]*|<tmp>|g" -e "s|/tmp/[^/]*|<tmp>|g" "$RAW_LOG" > output/transcript.txt
cat output/transcript.txt

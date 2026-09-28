#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CDPILOT="${CDPILOT:-node $(cd ../.. && pwd)/bin/cdpilot.js}"
export CDPILOT_PYTHON="${CDPILOT_PYTHON:-/usr/local/bin/python3}"
export CDP_PORT="${CDP_PORT:-59851}"
export CHROME_HEADLESS=1

PORT1=59861
PORT2=59862

TMP_DIR="$(mktemp -d)"
export CDPILOT_HOME="${TMP_DIR}/home"
export CDPILOT_PROFILE="${TMP_DIR}/prof"
mkdir -p "$CDPILOT_HOME" "$CDPILOT_PROFILE" "${TMP_DIR}/srv1" "${TMP_DIR}/srv2" "output"

cp index.html same.html "${TMP_DIR}/srv1/"
cp cross.html "${TMP_DIR}/srv2/"

sed "s|CROSS_URL|http://127.0.0.1:${PORT2}/cross.html|g" index.html > "${TMP_DIR}/srv1/index.html"

$CDPILOT_PYTHON -m http.server $PORT1 --directory "${TMP_DIR}/srv1" >/dev/null 2>&1 &
SERVER1_PID=$!

$CDPILOT_PYTHON -m http.server $PORT2 --directory "${TMP_DIR}/srv2" >/dev/null 2>&1 &
SERVER2_PID=$!

trap 'kill $SERVER1_PID $SERVER2_PID 2>/dev/null || true; $CDPILOT stop >/dev/null 2>&1 || true' EXIT
sleep 1

RAW_LOG="${TMP_DIR}/raw_output.txt"

{
  echo "$ cdpilot launch"
  $CDPILOT launch 2>&1

  echo "$ cdpilot go http://127.0.0.1:${PORT1}/index.html"
  $CDPILOT go "http://127.0.0.1:${PORT1}/index.html" 2>&1

  echo '$ cdpilot fill "iframe#same-frame >>> input#same-input" "Same Origin Text"'
  $CDPILOT fill "iframe#same-frame >>> input#same-input" "Same Origin Text" 2>&1

  echo '$ cdpilot fill "iframe#cross-frame >>> input#cross-input" "Cross Origin Text"'
  $CDPILOT fill "iframe#cross-frame >>> input#cross-input" "Cross Origin Text" 2>&1

  echo "$ cdpilot shot output/screenshot.png"
  $CDPILOT shot output/screenshot.png 2>&1

  echo "$ cdpilot stop"
  $CDPILOT stop 2>&1
} > "$RAW_LOG"

sed -e "s|${HOME}|~|g" -e "s|/private/tmp/[^/]*|<tmp>|g" -e "s|/tmp/[^/]*|<tmp>|g" "$RAW_LOG" > output/transcript.txt
cat output/transcript.txt

#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CDPILOT="${CDPILOT:-node $(cd ../.. && pwd)/bin/cdpilot.js}"
export CDPILOT_PYTHON="${CDPILOT_PYTHON:-/usr/local/bin/python3}"
export CDP_PORT="${CDP_PORT:-59853}"
export CHROME_HEADLESS=1

HTTP_PORT=59864

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
  echo "$ cdpilot launch"
  $CDPILOT launch 2>&1

  echo "$ cdpilot go http://127.0.0.1:${HTTP_PORT}/index.html"
  $CDPILOT go "http://127.0.0.1:${HTTP_PORT}/index.html" 2>&1

  echo '$ cdpilot click "#target" --entropy=on'
  set +e
  $CDPILOT click "#target" --entropy=on 2>&1
  EXIT_CODE=$?
  set -e
  echo "$ echo \$?"
  echo "$EXIT_CODE"

  echo '$ cdpilot click "#normal" --entropy=on'
  set +e
  $CDPILOT click "#normal" --entropy=on 2>&1
  EXIT_CODE=$?
  set -e
  echo "$ echo \$?"
  echo "$EXIT_CODE"

  echo "$ cdpilot shot output/screenshot.png"
  $CDPILOT shot output/screenshot.png 2>&1

  echo "$ cdpilot stop"
  $CDPILOT stop 2>&1
} > "$RAW_LOG"

sed -e "s|${TMP_DIR}|<tmp>|g" -e "s|$(cd "$SCRIPT_DIR/../.." && pwd)|<repo>|g" -e "s|${HOME}|~|g" -e "s|/private/tmp/[^/]*|<tmp>|g" -e "s|/tmp/[^/]*|<tmp>|g" "$RAW_LOG" > output/transcript.txt
cat output/transcript.txt

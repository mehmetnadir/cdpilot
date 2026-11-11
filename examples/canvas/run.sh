#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CDPILOT="${CDPILOT:-node $(cd ../.. && pwd)/bin/cdpilot.js}"
export CDPILOT_PYTHON="${CDPILOT_PYTHON:-/opt/homebrew/bin/python3.13}"
export CDP_PORT="${CDP_PORT:-59858}"
export CHROME_HEADLESS=1

TMP_DIR="$(mktemp -d)"
export CDPILOT_HOME="${TMP_DIR}/home"
export CDPILOT_PROFILE="${TMP_DIR}/prof"
mkdir -p "$CDPILOT_HOME" "$CDPILOT_PROFILE" "output"

EVENTS_OUT="${TMP_DIR}/events.jsonl"
RAW_LOG="${TMP_DIR}/raw_output.txt"

cleanup() {
  if [ -n "${EVENTS_PID:-}" ]; then
    kill -INT "$EVENTS_PID" 2>/dev/null || true
    wait "$EVENTS_PID" 2>/dev/null || true
  fi
  $CDPILOT canvas close --name demo >/dev/null 2>&1 || true
  $CDPILOT stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

emit_html_chunks() {
  printf '%s\n' '<!doctype html><main><h1> Flight Deals </h1>'
  sleep 0.06
  printf '%s\n' '<ul id="deals"><li data-key="ist-ber">IST -> BER ($140)</li><li data-key="ist-ams">IST -> AMS ($115)</li></ul>'
  sleep 0.06
  printf '%s\n' '<button id="sort-btn" data-action="sort_price">Sort by price</button></main>'
}

{
  echo "$ cdpilot launch"
  $CDPILOT launch 2>&1

  echo "$ cdpilot canvas open --name demo"
  $CDPILOT canvas open --name demo 2>&1

  echo "$ emit_html_chunks | cdpilot canvas stream --name demo"
  emit_html_chunks | $CDPILOT canvas stream --name demo 2>&1

  echo "$ cdpilot canvas events --name demo --follow   # stopped with SIGINT after click"
  $CDPILOT canvas events --name demo --follow >"$EVENTS_OUT" 2>&1 &
  EVENTS_PID=$!
  sleep 0.3

  $CDPILOT click "#sort-btn" >/dev/null 2>&1
  sleep 0.4

  kill -INT "$EVENTS_PID"
  wait "$EVENTS_PID"
  EVENTS_PID=""
  cat "$EVENTS_OUT"

  echo "$ cdpilot shot output/screenshot.png"
  $CDPILOT shot output/screenshot.png 2>&1

  echo "$ cdpilot canvas close --name demo"
  $CDPILOT canvas close --name demo 2>&1

  echo "$ cdpilot stop"
  $CDPILOT stop 2>&1
} > "$RAW_LOG"

sed \
  -e "s|${TMP_DIR}|<tmp>|g" \
  -e "s|$(cd "$SCRIPT_DIR/../.." && pwd)|<repo>|g" \
  -e "s|${HOME}|~|g" \
  -e "s|/private/tmp/[^/]*|<tmp>|g" \
  -e "s|/tmp/[^/]*|<tmp>|g" \
  "$RAW_LOG" > output/transcript.txt
cat output/transcript.txt

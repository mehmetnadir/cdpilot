#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CDPILOT="${CDPILOT:-node $(cd ../.. && pwd)/bin/cdpilot.js}"
export CDPILOT_PYTHON="${CDPILOT_PYTHON:-/opt/homebrew/bin/python3.13}"
# CDPILOT_CONNECT_PORT=<port>: drive an already running browser (connect mode).
# Unset: launch an isolated headless browser on CDP_PORT (default, used by CI).
CONNECT_PORT="${CDPILOT_CONNECT_PORT:-}"
if [ -z "$CONNECT_PORT" ]; then
  export CDP_PORT="${CDP_PORT:-59858}"
else
  unset CDP_PORT
fi
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
  if [ -n "$CONNECT_PORT" ]; then
    $CDPILOT disconnect >/dev/null 2>&1 || true
  else
    $CDPILOT stop >/dev/null 2>&1 || true
  fi
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
  if [ -n "$CONNECT_PORT" ]; then
    echo "$ cdpilot connect $CONNECT_PORT"
    $CDPILOT connect "$CONNECT_PORT" 2>&1
  else
    echo "$ cdpilot launch"
    $CDPILOT launch 2>&1
  fi

  echo "$ cdpilot canvas open --name demo"
  OPEN_OUT="$($CDPILOT canvas open --name demo 2>&1)"
  echo "$OPEN_OUT"
  # The canvas tab is addressed by its target id, so click and shot hit it in either mode.
  CANVAS_TARGET="$(printf '%s\n' "$OPEN_OUT" | awk '/^canvas: /{print $3}')"

  echo "$ emit_html_chunks | cdpilot canvas stream --name demo"
  emit_html_chunks | $CDPILOT canvas stream --name demo 2>&1

  echo "$ cdpilot canvas events --name demo --follow   # stopped with SIGINT after click"
  $CDPILOT canvas events --name demo --follow >"$EVENTS_OUT" 2>&1 &
  EVENTS_PID=$!
  sleep 0.3

  CDPILOT_TARGET="$CANVAS_TARGET" $CDPILOT click "#sort-btn" >/dev/null 2>&1
  sleep 0.4

  kill -INT "$EVENTS_PID"
  wait "$EVENTS_PID"
  EVENTS_PID=""
  cat "$EVENTS_OUT"

  echo "$ cdpilot shot output/screenshot.png"
  CDPILOT_TARGET="$CANVAS_TARGET" $CDPILOT shot output/screenshot.png 2>&1

  echo "$ cdpilot canvas close --name demo"
  $CDPILOT canvas close --name demo 2>&1

  if [ -n "$CONNECT_PORT" ]; then
    echo "$ cdpilot disconnect"
    $CDPILOT disconnect 2>&1
  else
    echo "$ cdpilot stop"
    $CDPILOT stop 2>&1
  fi
} > "$RAW_LOG"

sed \
  -e "s|/devtools/browser/[0-9a-f-]*|/devtools/browser/<id>|g" \
  -e "s|^canvas: demo [0-9A-F]*|canvas: demo <targetId>|" \
  -e 's|"t":[0-9]*|"t":<ms>|' \
  -e 's|^\(ok .*patches.*coalesced)\) [0-9.]* ms|\1 <n> ms|' \
  -e 's|^\(output/screenshot.png\) ([0-9.]*[KM]*B)|\1 (<size>)|' \
  -e 's|^  Tabs: [0-9]*|  Tabs: <n>|' \
  -e "s|${TMP_DIR}|<tmp>|g" \
  -e "s|$(cd "$SCRIPT_DIR/../.." && pwd)|<repo>|g" \
  -e "s|${HOME}|~|g" \
  -e "s|/private/tmp/[^/]*|<tmp>|g" \
  -e "s|/tmp/[^/]*|<tmp>|g" \
  "$RAW_LOG" > output/transcript.txt
cat output/transcript.txt

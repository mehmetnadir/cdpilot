#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CDPILOT="${CDPILOT:-node $(cd ../.. && pwd)/bin/cdpilot.js}"
export CDPILOT_PYTHON="${CDPILOT_PYTHON:-/usr/local/bin/python3}"
unset CDP_PORT
export CHROME_HEADLESS=1

USER_PORT=59921
HTTP_PORT=59922

TMP_DIR="$(mktemp -d)"
export CDPILOT_HOME="${TMP_DIR}/home"
export CDPILOT_PROFILE="${TMP_DIR}/prof"
mkdir -p "$CDPILOT_HOME" "$CDPILOT_PROFILE" "${TMP_DIR}/srv" "${TMP_DIR}/user_prof" "output"

cp page1.html page2.html "${TMP_DIR}/srv/"

$CDPILOT_PYTHON -m http.server $HTTP_PORT --directory "${TMP_DIR}/srv" >/dev/null 2>&1 &
SERVER_PID=$!

CHROME_BIN=""
if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif command -v google-chrome >/dev/null 2>&1; then
  CHROME_BIN="google-chrome"
elif command -v chromium >/dev/null 2>&1; then
  CHROME_BIN="chromium"
elif command -v chromium-browser >/dev/null 2>&1; then
  CHROME_BIN="chromium-browser"
fi

"$CHROME_BIN" --headless=new --remote-debugging-port=$USER_PORT --user-data-dir="${TMP_DIR}/user_prof" "http://127.0.0.1:${HTTP_PORT}/page1.html" >/dev/null 2>&1 &
USER_CHROME_PID=$!

trap 'kill $USER_CHROME_PID $SERVER_PID 2>/dev/null || true; $CDPILOT stop >/dev/null 2>&1 || true' EXIT

sleep 2

$CDPILOT_PYTHON -c '
import json, urllib.request, asyncio, websockets, time

port = '$USER_PORT'
ws_url = None
for _ in range(20):
    try:
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list")
        tabs = json.loads(req.read().decode())
        user_tab = next((t for t in tabs if t.get("type") == "page" and "page1.html" in t.get("url", "")), None)
        if user_tab and "webSocketDebuggerUrl" in user_tab:
            ws_url = user_tab["webSocketDebuggerUrl"]
            break
    except Exception:
        pass
    time.sleep(0.5)

if not ws_url:
    raise RuntimeError("Failed to find user Chrome tab WebSocket URL")

async def set_draft():
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": "document.querySelector(\"#draft\").value = \"my unsaved draft\""}
        }))
        await ws.recv()

asyncio.run(set_draft())
'

RAW_LOG="${TMP_DIR}/raw_output.txt"

{
  echo "$ cdpilot connect $USER_PORT"
  $CDPILOT connect $USER_PORT 2>&1

  echo "$ cdpilot go http://127.0.0.1:${HTTP_PORT}/page2.html"
  $CDPILOT go "http://127.0.0.1:${HTTP_PORT}/page2.html" 2>&1

  echo "$ cdpilot content"
  $CDPILOT content 2>&1

  echo "$ cdpilot tabs"
  $CDPILOT tabs 2>&1

  echo "$ cdpilot shot output/screenshot.png"
  $CDPILOT shot output/screenshot.png 2>&1

  echo "$ cdpilot stop"
  $CDPILOT stop 2>&1

  echo '$ python3 -c "read user tab over CDP /json"'
  $CDPILOT_PYTHON -c '
import json, urllib.request, asyncio, websockets
tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:'"$USER_PORT"'/json/list").read())
user_tab = next(t for t in tabs if t.get("type") == "page" and "page1.html" in t.get("url", ""))
print("User tab URL:", user_tab["url"])
async def get_draft():
    async with websockets.connect(user_tab["webSocketDebuggerUrl"]) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":"document.querySelector(\"#draft\").value"}}))
        res = json.loads(await ws.recv())
        print("User tab textarea value:", res["result"]["result"]["value"])
asyncio.run(get_draft())
' 2>&1

  echo "$ cdpilot disconnect"
  $CDPILOT disconnect 2>&1
} > "$RAW_LOG"

sed -e "s|${TMP_DIR}|<tmp>|g" -e "s|$(cd "$SCRIPT_DIR/../.." && pwd)|<repo>|g" -e "s|${HOME}|~|g" -e "s|/private/tmp/[^/]*|<tmp>|g" -e "s|/tmp/[^/]*|<tmp>|g" "$RAW_LOG" > output/transcript.txt
cat output/transcript.txt

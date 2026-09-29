# missed-click-exit-codes

This example demonstrates missed click exit codes when an element is covered on mousedown (e.g. by an opening dropdown menu).
When the release lands elsewhere, cdpilot prints `Pressed (released elsewhere, not clicked)` and exits with exit code 3 (`$?`), whereas a successful click exits with code 0.

## Commands

```bash
cdpilot launch
cdpilot go http://127.0.0.1:59864/index.html
cdpilot click "#target" --entropy=on
echo $?
cdpilot click "#normal" --entropy=on
echo $?
cdpilot shot output/screenshot.png
cdpilot stop
```

## Captured Output

```text
$ cdpilot launch

  cdpilot v0.9.4 — Pre-flight Check
  ───────────────────────────────────

  ✓ Python 3.14.7
  ✓ websockets
  ✓ Brave Browser (/Applications/Brave Browser.app/Contents/MacOS/Brave Browser)

  Ready!

Launching browser (isolated session, port 59853) [missed-click-exit-co-d4ecbb]...
  Mode: headless
  Idle close: off (launch --idle-close <min> or CDPILOT_IDLE_CLOSE=<min> turns it on)
CDP ready! (port 59853) [missed-click-exit-co-d4ecbb]
$ cdpilot go http://127.0.0.1:59864/index.html
Missed Click Exit Codes
Open Covering Menu
Normal Button
$ cdpilot click "#target" --entropy=on
note: #target was no longer under the mouse when the button was released (div#overlay was); the press and release reached the page, so no script click (it could click twice)
Pressed (released elsewhere, not clicked): BUTTON Open Covering Menu
$ echo $?
3
$ cdpilot click "#normal" --entropy=on
Clicked: BUTTON Normal Button
$ echo $?
0
$ cdpilot shot output/screenshot.png
output/screenshot.png (14.5KB)
$ cdpilot stop
  Closed via CDP Browser.close.
Browser stopped (port 59853).
```

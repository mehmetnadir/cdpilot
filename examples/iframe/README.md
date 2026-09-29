# iframe

This example demonstrates `>>>` frame hopping into both same-origin and cross-origin (OOPIF) iframes.
cdpilot seamlessly handles entering frames across different origins and filling form elements inside them.

## Commands

```bash
cdpilot launch
cdpilot go http://127.0.0.1:59861/index.html
cdpilot fill "iframe#same-frame >>> input#same-input" "Same Origin Text"
cdpilot fill "iframe#cross-frame >>> input#cross-input" "Cross Origin Text"
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

Launching browser (isolated session, port 59851) [iframe-bff5f7]...
  Mode: headless
  Idle close: off (launch --idle-close <min> or CDPILOT_IDLE_CLOSE=<min> turns it on)
CDP ready! (port 59851) [iframe-bff5f7]
$ cdpilot go http://127.0.0.1:59861/index.html
IFrame Feature Demo
 
$ cdpilot fill "iframe#same-frame >>> input#same-input" "Same Origin Text"
Filled: INPUT = Same Origin Text
$ cdpilot fill "iframe#cross-frame >>> input#cross-input" "Cross Origin Text"
Filled: INPUT = Cross Origin Text
$ cdpilot shot output/screenshot.png
output/screenshot.png (16.5KB)
$ cdpilot stop
  Closed via CDP Browser.close.
Browser stopped (port 59851).
```

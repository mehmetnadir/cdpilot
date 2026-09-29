# connect

This example demonstrates connecting `cdpilot` to an existing, external Chrome instance started by the user (`cdpilot connect <port>`), driving automation in a separate tab without closing the user browser, and proving that the user browser and unsaved tab state persist across `stop` and `disconnect`.

## Commands

```bash
cdpilot connect 59921
cdpilot go http://127.0.0.1:59922/page2.html
cdpilot content
cdpilot tabs
cdpilot shot output/screenshot.png
cdpilot stop
python3 -c "read user tab over CDP /json"
cdpilot disconnect
```

## Captured Output

```text
$ cdpilot connect 59921
⚠  This browser's cookies and sessions are accessible to cdpilot commands.
✓ Connected to Chrome/154.0.8037.58 on port 59921
  WebSocket: ws://127.0.0.1:59921/devtools/browser/60510edf-8268-4bc5-800d-c4754efb05ad
  Tabs: 1
  Commands now run in YOUR browser; cdpilot will never close it.
$ cdpilot go http://127.0.0.1:59922/page2.html
cdpilot Target Page

Opened by cdpilot in its own tab without interrupting the user browser.
$ cdpilot content
cdpilot Target Page

Opened by cdpilot in its own tab without interrupting the user browser.
$ cdpilot tabs
  🟢 [0] cdpilot Page 2
       http://127.0.0.1:59922/page2.html
  🟢 [1] User Browser Page 1
       http://127.0.0.1:59922/page1.html

2 pages, 8 targets
$ cdpilot shot output/screenshot.png
output/screenshot.png (12.4KB)
$ cdpilot stop
connected browser left running; run `cdpilot disconnect` to forget it
$ python3 -c "read user tab over CDP /json"
User tab URL: http://127.0.0.1:59922/page1.html
User tab textarea value: my unsaved draft
$ cdpilot disconnect
Disconnected from Chrome/154.0.8037.58 (port 59921); your browser keeps running.
```

# canvas

This example opens a sandboxed live canvas tab (`canvas open`), streams generated HTML chunks from a command into the tab (`canvas stream`), and reads user interaction events back as JSON lines (`canvas events --follow`) until stopped cleanly with `SIGINT` (`Ctrl+C`).

## Commands

```bash
cdpilot launch   # or: cdpilot connect <port>
cdpilot canvas open --name demo
printf '%s\n' '<main><h1>Flight Deals</h1><button id="sort-btn" data-action="sort_price">Sort by price</button></main>' | cdpilot canvas stream --name demo
cdpilot canvas events --name demo --follow
cdpilot click "#sort-btn"
cdpilot shot output/screenshot.png
cdpilot canvas close --name demo
cdpilot stop
```

## Captured Output

```text
$ cdpilot connect 9333
⚠  This browser's cookies and sessions are accessible to cdpilot commands.
✓ Connected to HeadlessChrome/152.0.7977.30 on port 9333
  WebSocket: ws://127.0.0.1:9333/devtools/browser/<id>
  Tabs: <n>
  Commands now run in YOUR browser; cdpilot will never close it.
$ cdpilot canvas open --name demo
canvas: demo <targetId>
$ emit_html_chunks | cdpilot canvas stream --name demo
ok 1 patches (0 coalesced) <n> ms 233 bytes
$ cdpilot canvas events --name demo --follow   # stopped with SIGINT after click
{"seq":1,"t":<ms>,"src":"page","type":"click","action":"sort_price","id":"sort-btn","data":{}}
$ cdpilot shot output/screenshot.png
output/screenshot.png (<size>)
$ cdpilot canvas close --name demo
closed demo
$ cdpilot disconnect
Disconnected from HeadlessChrome/152.0.7977.30 (port 9333); your browser keeps running.
```

Captured in connect mode (`CDPILOT_CONNECT_PORT=9333 sh examples/canvas/run.sh`); without that variable `run.sh` launches its own isolated headless browser.

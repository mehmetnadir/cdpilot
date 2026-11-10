# canvas

This example opens a sandboxed live canvas tab (`canvas open`), streams generated HTML chunks from a command into the tab (`canvas stream`), and reads user interaction events back as JSON lines (`canvas events --follow`) until stopped cleanly with `SIGINT` (`Ctrl+C`).

## Commands

```bash
cdpilot launch
cdpilot canvas open --name demo
printf '%s\n' '<main><h1>Flight Deals</h1><button id="sort-btn" data-action="sort_price">Sort by price</button></main>' | cdpilot canvas stream --name demo
cdpilot canvas events --name demo --follow
cdpilot click "#sort-btn"
cdpilot shot output/screenshot.png
cdpilot canvas close --name demo
cdpilot stop
```

## Expected Output

> **Note:** Lanes A (`CANVAS_RUNTIME_JS`), B (`canvas open`/host), and C (`canvas stream`) are built in parallel branches and are not merged into `lane/canvas-d` yet, so `run.sh` cannot run end-to-end here. The block below shows the **expected** output per the frozen v0 contract (`.claude/docs/canvas-sozlesme-v0.md`); after merging all four lanes, run `./examples/canvas/run.sh`, rename this heading to `## Captured Output`, and run `python3 examples/sync-readmes.py`.

```text
$ cdpilot launch
Launching browser (isolated session, port 59858)...
CDP ready! (port 59858)
$ cdpilot canvas open --name demo
canvas: demo <targetId>
$ emit_html_chunks | cdpilot canvas stream --name demo
ok ... ms
$ cdpilot canvas events --name demo --follow   # stopped with SIGINT after click
{"seq":1,"t":1762810000000,"src":"page","type":"click","action":"sort_price","id":"sort-btn","data":{}}
$ cdpilot shot output/screenshot.png
output/screenshot.png (...)
$ cdpilot canvas close --name demo
closed demo
$ cdpilot stop
Browser stopped (port 59858).
```

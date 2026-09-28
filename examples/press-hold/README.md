# press-hold

This example demonstrates `click --entropy=on` measuring the realistic press-and-hold duration (mousedown to mouseup gap).
Human-like mouse interaction holds the mouse button down for a natural duration (40-120 ms) rather than instant release.

## Commands

```bash
cdpilot launch
cdpilot go http://127.0.0.1:59863/index.html
cdpilot click "#target" --entropy=on
cdpilot content
cdpilot shot output/screenshot.png
cdpilot stop
```

## Captured Output

```text
$ cdpilot click "#target" --entropy=on
Clicked: BUTTON Click Me
$ cdpilot content
Press Hold Gap Measurement
Click Me
Mousedown -> Mouseup Gap: 58 ms
```

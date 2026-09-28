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
$ cdpilot click "#target" --entropy=on
Pressed (released elsewhere, not clicked): BUTTON Open Covering Menu
$ echo $?
3
$ cdpilot click "#normal" --entropy=on
Clicked: BUTTON Normal Button
$ echo $?
0
```

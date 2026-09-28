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
$ cdpilot fill "iframe#same-frame >>> input#same-input" "Same Origin Text"
Filled: INPUT = Same Origin Text
$ cdpilot fill "iframe#cross-frame >>> input#cross-input" "Cross Origin Text"
Filled: INPUT = Cross Origin Text
```

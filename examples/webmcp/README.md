# webmcp

This example demonstrates enabling WebMCP via `launch --webmcp`, listing tools registered on a web page via `document.modelContext`, and invoking them with `tools call`.

## Commands

```bash
cdpilot launch --webmcp
cdpilot go http://127.0.0.1:59865/shop.html
cdpilot tools list
cdpilot tools call add_to_cart '{"sku":"LAPTOP-01","qty":1}'
cdpilot shot output/screenshot.png
cdpilot stop
```

## Captured Output

```text
$ cdpilot launch --webmcp

  cdpilot v0.9.4 — Pre-flight Check
  ───────────────────────────────────

  ✓ Python 3.14.7
  ✓ websockets
  ✓ Brave Browser (/Applications/Brave Browser.app/Contents/MacOS/Brave Browser)

  Ready!

Launching browser (isolated session, port 59854) [webmcp-585cc3]...
  Mode: headless
  WebMCP: on (--enable-features=WebMCP)
  Idle close: off (launch --idle-close <min> or CDPILOT_IDLE_CLOSE=<min> turns it on)
CDP ready! (port 59854) [webmcp-585cc3]
$ cdpilot go http://127.0.0.1:59865/shop.html
WebMCP fixture shop

Cart: 0 items

Email  Subscribe

Not subscribed
$ cdpilot tools list
4 WebMCP tools on http://127.0.0.1:59865/shop.html:
  add_to_cart  "Add to cart"  [consequential]
    Add a product to the shopping cart
    input: {"type": "object", "properties": {"sku": {"type": "string", "description": "Product SKU identifier"}, "qty": {"type": "integer", "description": "Quantity to add"}}, "required": ["sku", "qty"]}
  frame_echo
    Echo a text back from the same-origin iframe
    frame: http://127.0.0.1:59865/frame.html
    input: {"type": "object", "properties": {"text": {"type": "string", "description": "Text to echo"}}, "required": ["text"]}
  subscribe_newsletter  "Subscribe"  [form, autosubmit]
    Subscribe an email address to the store newsletter
    input: {"type": "object", "properties": {"email": {"type": "string", "description": "Customer email address"}}, "required": ["email"]}
  wait_for_abort
    Never finishes on its own; rejects when the execution is aborted
$ cdpilot tools call add_to_cart "{\"sku\":\"LAPTOP-01\",\"qty\":1}"
{
  "ok": true,
  "sku": "LAPTOP-01",
  "qty": 1,
  "cart_size": 1
}
$ cdpilot shot output/screenshot.png
output/screenshot.png (14.3KB)
$ cdpilot stop
  Closed via CDP Browser.close.
Browser stopped (port 59854).
```

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
```

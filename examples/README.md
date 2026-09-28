# cdpilot Examples

Runnable examples for cdpilot features with real captured execution outputs.

| Feature | Folder | Real Result |
|---|---|---|
| IFrame Hops | [`iframe`](./iframe) | Fills input inside same-origin & cross-origin (OOPIF) iframes using `>>>` |
| Press & Hold Gap | [`press-hold`](./press-hold) | Measured realistic mouse press-and-hold gap (58 ms) with `click --entropy=on` |
| Missed Click Exit Codes | [`missed-click-exit-codes`](./missed-click-exit-codes) | Covered element returns exit code 3 (`Pressed (released elsewhere, not clicked)`) vs 0 for normal click |
| WebMCP Integration | [`webmcp`](./webmcp) | Listed 4 in-page WebMCP tools and executed `tools call add_to_cart` |
| Web Bot Auth | [`web-bot-auth`](./web-bot-auth) | Successfully authenticated with Cloudflare via RFC 9421 Ed25519 HTTP Message Signatures |
| Plugin & MCPB Build | [`plugin-install`](./plugin-install) | Built `cdpilot.mcpb` bundle (381.9 KB) via `npm run build:mcpb` |

## Running All Examples

```bash
./examples/run-all.sh
```

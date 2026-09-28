# web-bot-auth

This example demonstrates Web Bot Auth HTTP Message Signatures (RFC 9421) using the RFC 9421 Ed25519 TEST key.
`launch --bot-auth` transparently signs outgoing HTTP requests, allowing Cloudflare to verify the bot identity.

## Commands

```bash
cdpilot bot-auth status
cdpilot bot-auth directory --headers --authority example.com
cdpilot launch --bot-auth
cdpilot go https://http-message-signatures-example.research.cloudflare.com/
cdpilot content
cdpilot shot output/screenshot.png
cdpilot stop
```

## Captured Output

```text
$ cdpilot launch --bot-auth
  Bot Auth: signing every request as https://http-message-signatures-example.research.cloudflare.com (keyid poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U, Signature-Agent legacy)
$ cdpilot go https://http-message-signatures-example.research.cloudflare.com/
Identify Bots with HTTP Message Signatures
You successfully authenticated as owning the test public key
```

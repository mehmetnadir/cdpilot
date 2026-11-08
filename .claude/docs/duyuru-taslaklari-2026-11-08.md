# Duyuru taslakları — Nadir onayına (08.11.2026)

Yalnız ölçülmüş iddialar; "500x", "13x", "3-10x" gibi çarpanlar yok (06.11 iddia denetimi).

## Show HN (başlık ≤ 80 karakter)

**Başlık:** Show HN: cdpilot – browser automation CLI for agents, zero npm deps, pure CDP

**Metin:**

Hi HN. cdpilot is a command-line browser driver for LLM agents (and people): `cdpilot go <url>`, `cdpilot click "Sign in"`,
`cdpilot content`, `cdpilot shot page.png`. It talks the Chrome DevTools Protocol directly over HTTP/WebSocket: no Playwright,
no Puppeteer, zero npm dependencies (the Python core needs `websockets`). Works with Chrome, Brave, Chromium, Edge, Vivaldi and
Chrome for Testing, headless or visible, or attached to the browser you already have open (`cdpilot connect`).

Why a CLI and not a library: an agent that drives a browser through shell commands keeps its context small and its steps
inspectable. Every command appends one redacted JSON line to a local session log; `cdpilot record` / `replay` turn a session
into a flow file with secrets replaced by placeholders before anything touches disk.

0.9.5 (this week): shadow DOM traversal (`host >>> inner`), HAR 1.2 export, record/replay, an MCP server with a
`--tools core` profile (11 tools instead of 45; schema 5.8k → 1.3k tokens), Web Bot Auth (signed requests, verified against
Cloudflare), WebMCP bridge (`document.modelContext` tools, Chrome 156 frame fix). Measured this week: a browser-free command
takes ~270 ms end to end; with the new opt-in warm process (`CDPILOT_DAEMON=1`) ~110 ms, which is node's own start-up.

What it is not: not a CAPTCHA solver (it detects and hands off), not a scraping farm. MIT. Python 3.10+, Node 18+.

Repo: https://github.com/mehmetnadir/cdpilot · npm: `npx cdpilot launch` · MCP Registry: io.github.mehmetnadir/cdpilot

I'd love feedback on the daemon design (one warm Python process per project, Unix socket, fresh-process fallback) and on
what agent workflows still need a library instead of a CLI.

**Zaman önerisi:** Salı–Perşembe 15:00–17:00 TSİ (HN'de 08:00–10:00 ET). Daemon D2 (`go` ≤150 ms) bitince, "hız" iddiası
ölçümle desteklenmiş olur; D2 bitmeden yayınlanacaksa son cümledeki süre iddiaları kaldırılır.

## Reddit r/LocalLLaMA ya da r/ClaudeAI (daha kısa)

**Başlık:** cdpilot: a zero-npm-dependency browser CLI for agents (MCP server, record/replay, shadow DOM) – 0.9.5

**Metin:**

I maintain cdpilot, a CLI that drives Chrome/Brave over raw CDP so an agent can do `cdpilot go`, `click`, `content`, `shot`
from a shell. 0.9.5 adds record/replay (secrets become placeholders before they hit disk), HAR export, shadow DOM `>>>`, and
an MCP `--tools core` profile that cuts the tool schema from ~5.8k to ~1.3k tokens. There is also an opt-in warm process
(`CDPILOT_DAEMON=1`) that drops a browser-free call from ~270 ms to ~110 ms on my machine.

Not a CAPTCHA solver; it detects friction and hands off. MIT. `npx cdpilot launch`. Happy to answer questions about running it
headless on a server or next to Claude Code (there is a plugin and an .mcpb bundle).

## Karar noktaları (Nadir)

| # | Soru | Öneri |
|---|---|---|
| 1 | Show HN tarihi | D2 sonrası ilk Salı (11.11 ya da 18.11) |
| 2 | Reddit alt forumları | r/ClaudeAI + r/LocalLLaMA, HN'den 1 gün sonra |
| 3 | Kim gönderir | Nadir'in hesabı (HN yeni hesap ceza yer); metni ben hazırlarım, soruları birlikte cevaplarız |
| 4 | Süre iddiası | yalnız ölçüm belgesine bağlı cümleler; D2 bitmeden "warm process" cümlesi kalır, `go` iddiası yok |

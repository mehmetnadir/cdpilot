---
name: cdpilot
description: Browser automation over raw Chrome DevTools Protocol — navigate, click, fill forms, screenshot, extract content, handle iframes, and bypass basic bot detection. Use whenever a task needs a real browser (no Puppeteer/Playwright/Selenium available, or when those get detected) — for example "open this page and click X", "fill this form", "take a screenshot", "scrape this site", "test this login flow".
---

# cdpilot

Zero-dependency browser automation CLI. It drives a real Brave/Chrome/Chromium
browser over raw CDP (no Puppeteer/Playwright/Selenium). This plugin registers
cdpilot's MCP server (`npx cdpilot mcp`, declared in this plugin's `.mcp.json`),
so its tools appear directly in the tool list — prefer those MCP tools over
shelling out to the `cdpilot` CLI yourself when they're available.

## When to reach for it

- The task needs a real, visible-DOM browser: navigating, clicking, filling
  forms, taking screenshots/PDFs, or reading rendered page content.
- A site fights back (Cloudflare/DataDome/PerimeterX-style checks) — cdpilot's
  stealth and friction-ladder features exist for exactly this.
- An iframe is involved (payment widgets, login widgets, reCAPTCHA/Turnstile).

## Before first use

The browser needs a one-time setup on the machine running cdpilot:

```bash
npx cdpilot setup     # auto-detect browser, create an isolated profile
npx cdpilot launch    # start the browser with CDP enabled
npx cdpilot status    # confirm the connection
```

Requirements: Node.js 18+, Python 3.10+, and one of Brave/Chrome/Chromium
installed. See the [README](https://github.com/mehmetnadir/cdpilot#readme)
for the full requirements and first-run wizard.

## Core commands (CLI form; MCP tool names mirror these 1:1)

```bash
cdpilot go <url>               # navigate (alias: open <url>)
cdpilot content                # get page text
cdpilot html                   # get page HTML
cdpilot shot [file]            # screenshot (PNG)
cdpilot pdf [file]             # save page as PDF
cdpilot click <selector>       # click an element
cdpilot type <selector> <text> # type into an input
cdpilot fill <selector> <val>  # set input value (React-compatible)
cdpilot submit <form>          # submit a form
cdpilot hover <selector>       # hover an element
cdpilot status                 # check the browser connection
```

Selectors can target elements inside `<iframe>`s with the `>>>` frame-chain
syntax or `--frame`; see the README's "Element targeting inside iframes"
section before writing iframe-crossing automation by hand.

## Do not invent commands

This skill intentionally lists only commands documented in cdpilot's README.
For anything not listed here (stealth modes, CAPTCHA/press-and-hold solvers,
network interception, device emulation, parallel contexts, session logging,
WebMCP tools, etc.), read the README's `## Commands` section or run
`npx cdpilot --help` rather than guessing a flag or subcommand name.

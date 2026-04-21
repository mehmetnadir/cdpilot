# cdpilot

> Zero-dependency browser automation from your terminal. One command, full control.

[![npm version](https://img.shields.io/npm/v/cdpilot.svg)](https://www.npmjs.com/package/cdpilot)
[![npm downloads](https://img.shields.io/npm/dm/cdpilot.svg)](https://www.npmjs.com/package/cdpilot)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Node.js](https://img.shields.io/badge/Node.js-18%2B-339933)](https://nodejs.org)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.io)
[![cdpilot MCP server](https://glama.ai/mcp/servers/mehmetnadir/cdpilot/badge)](https://glama.ai/mcp/servers/mehmetnadir/cdpilot)

<div align="center">
  <img src="cdpilot-demo.gif" alt="cdpilot demo" width="600" />
</div>

## Quick Start

```bash
npx cdpilot launch    # Start browser with CDP
npx cdpilot go https://example.com
npx cdpilot shot      # Take screenshot
```

No config files. No boilerplate. Just `npx` and go.

## Why cdpilot?

AI agents and developers need browser control that **just works**:

- **Zero config** — `npx cdpilot launch` starts an isolated browser session
- **Zero dependency** — No Puppeteer, no Playwright, no Selenium. Pure CDP over HTTP
- **40+ commands** — Navigate, click, type, screenshot, network, console, accessibility, and more
- **AI-agent friendly** — Designed for Claude, GPT, Gemini, and any LLM tool-use workflow
- **Isolated sessions** — Your personal browser stays untouched. cdpilot runs in its own profile
- **Visual feedback** — Green glow overlay, cursor visualization, click ripples, and keystroke display keep you informed during automation
- **Multi-project isolation** — Each project gets its own browser instance and port automatically, no conflicts
- **AI control warning** — Red toast notification appears when you hover during active automation
- **Privacy-first** — Everything runs locally. No data leaves your machine

### Browser Selection (Workload-Aware Auto-Pick)

cdpilot picks the right browser for what you're doing. `auto` (default) is a
two-axis policy — extension workload × platform stability:

| Your workload | Auto-pick order |
|---|---|
| Has extensions registered (`ext-install`) | vivaldi → brave → edge → chromium → chrome |
| No extensions (pure automation) | chrome → vivaldi → edge → chromium → brave |

Override anytime:

```bash
cdpilot browser            # show current pick + reason
cdpilot browser vivaldi    # pin to Vivaldi
cdpilot browser auto       # restore smart default
```

**Why the split?**
- **Chrome 147+ silently drops `--load-extension`** for unpacked extensions
  (no error, no warning). Verified — `chrome://extensions` shows 0 items.
- **Vivaldi, Brave, Edge, Chromium** honor `--load-extension` (tested).
- On **macOS 26 (Tahoe)** Brave 1.89 crashes deterministically at ~7min
  uptime (SIGTRAP in ThreadPoolForegroundWorker). cdpilot detects the OS
  and demotes Brave automatically until a fixed Brave release ships.

Each browser gets its own isolated profile (`~/.cdpilot/.../profile-vivaldi`
etc.) so switching never causes prefs corruption.

## Installation

```bash
# Use directly (no install needed)
npx cdpilot <command>

# Or install globally
npm i -g cdpilot
```

**Requirements:** Node.js 18+ and one of: Brave Browser, Google Chrome, or Chromium.

### First-time setup

```bash
npx cdpilot setup     # Auto-detect browser, create isolated profile
npx cdpilot launch    # Start browser with CDP enabled
npx cdpilot status    # Check connection
```

## Commands

### Navigation & Content

```bash
cdpilot go <url>              # Navigate to URL
cdpilot content               # Get page text content
cdpilot html                  # Get page HTML
cdpilot shot [file]           # Take screenshot (PNG)
cdpilot pdf [file]            # Save page as PDF
```

### Interaction

```bash
cdpilot click <selector>      # Click element
cdpilot type <selector> <text># Type into input
cdpilot fill <selector> <val> # Set input value (React-compatible)
cdpilot submit <form>         # Submit form
cdpilot hover <selector>      # Hover element
cdpilot keys <combo>          # Keyboard shortcut (ctrl+a, enter, etc.)
cdpilot scroll-to <selector>  # Scroll element into view
cdpilot drag <from> <to>      # Drag and drop
```

### Debugging

```bash
cdpilot console [url]         # Capture console logs
cdpilot network [url]         # Monitor network requests
cdpilot debug [url]           # Full diagnostic (console+network+perf+shot)
cdpilot perf                  # Performance metrics
cdpilot eval <js>             # Execute JavaScript
```

### Tab Management

```bash
cdpilot tabs                  # List open tabs
cdpilot new-tab [url]         # Open new tab
cdpilot switch-tab <id>       # Switch to tab
cdpilot close-tab [id]        # Close tab
cdpilot close                 # Close active tab
```

### Network Control

```bash
cdpilot throttle slow3g       # Simulate slow 3G
cdpilot throttle fast3g       # Simulate fast 3G
cdpilot throttle offline      # Go offline
cdpilot throttle off          # Back to normal
cdpilot proxy <url>           # Set proxy
cdpilot proxy off             # Remove proxy
```

### Request Interception

```bash
cdpilot intercept block <pattern>                    # Block requests
cdpilot intercept mock <pattern> <json-file>         # Mock responses
cdpilot intercept headers <pattern> <header:value>   # Add headers
cdpilot intercept list                               # List active rules
cdpilot intercept clear                              # Clear all rules
```

### Device Emulation

```bash
cdpilot emulate iphone        # iPhone emulation
cdpilot emulate ipad          # iPad emulation
cdpilot emulate android       # Android emulation
cdpilot emulate reset         # Back to desktop
```

### Geolocation

```bash
cdpilot geo istanbul          # Set location to Istanbul
cdpilot geo london            # Set location to London
cdpilot geo 41.01 28.97       # Custom coordinates
cdpilot geo off               # Remove override
```

### Accessibility

```bash
cdpilot a11y                  # Full accessibility tree
cdpilot a11y summary          # Quick summary
cdpilot a11y find <role>      # Find elements by ARIA role
```

### Session Management

```bash
cdpilot session               # Current session info
cdpilot sessions              # List all sessions
cdpilot session-close [id]    # Close session
```

### Advanced

```bash
cdpilot cookies [domain]      # List cookies
cdpilot storage               # localStorage contents
cdpilot upload <sel> <file>   # Upload file to input
cdpilot multi-eval <js>       # Execute JS in all tabs
cdpilot headless [on|off]     # Toggle headless mode
cdpilot frame list            # List iframes
cdpilot dialog auto-accept    # Auto-accept dialogs
cdpilot permission grant geo  # Grant geolocation
```

### Stealth & CAPTCHA

Zero-dependency anti-fingerprint layer — patches `navigator.webdriver`,
`chrome.runtime`, plugins (proper `PluginArray` inheritance), WebGL
vendor/renderer, permissions, hardware concurrency, and the `Worker`
constructor. Injected via `Page.addScriptToEvaluateOnNewDocument` before
any page script runs. Disabled by default; opt-in.

```bash
cdpilot stealth on            # enable fingerprint patches (opt-in)
cdpilot stealth off           # disable (default)
cdpilot stealth status        # show which patches are applied

cdpilot captcha-check         # JSON detection of Turnstile/hCaptcha/reCAPTCHA/
                              # DataDome/PerimeterX/Arkose/GeeTest. Exit 0/3
cdpilot captcha-wait [sec]    # block until user solves (interactive)
                              # or poll with JSON stream (non-interactive)
```

Verified against public bot-detection panels:
- **bot.sannysoft.com:** 24/24 PASS (WebDriver, Chrome obj, Plugins as PluginArray, WebGL, PHANTOM_*, HEADCHR_*, SELENIUM_DRIVER)
- **bot.incolumitas.com** intoli: 6/6 OK — new-tests: 6/7 OK (one FAIL = pure CDP presence, cannot be JS-patched)
- **nowsecure.nl** (Cloudflare full challenge): passed
- **arh.antoinevastel.com/areyouheadless:** "You are not Chrome headless"

### Reliability

```bash
cdpilot browser [name|auto]   # workload-aware browser selection
cdpilot health                # JSON: alive, port, tabs, browser, today's crashes
```

`cdpilot health` is designed for shell watchdogs:

```bash
until cdpilot health >/dev/null; do cdpilot launch; sleep 2; done
```

Surfaces today's Brave crash count from `~/Library/Logs/DiagnosticReports/`
on macOS — spot degradation before your automation silently stalls.

## Use with AI Agents

cdpilot is designed to be called by AI agents as a tool:

### Claude Code (MCP)

```json
{
  "mcpServers": {
    "cdpilot": {
      "command": "npx",
      "args": ["cdpilot", "mcp"]
    }
  }
}
```

### Any LLM (tool-use)

```json
{
  "name": "browser",
  "description": "Control a browser via CDP",
  "parameters": {
    "command": "go https://example.com"
  }
}
```

### Python (subprocess)

```python
import subprocess
result = subprocess.run(["npx", "cdpilot", "go", url], capture_output=True, text=True)
print(result.stdout)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CDP_PORT` | `9222` | CDP debugging port |
| `CHROME_BIN` | Auto-detect | Browser binary path |
| `CDPILOT_PROFILE` | `~/.cdpilot/profile` | Isolated browser profile |
| `BROWSER_SESSION` | Auto | Session identifier |

## How It Works

```
┌─────────────┐     HTTP/WebSocket      ┌──────────────┐
│  cdpilot │ ◄──────────────────────► │ Brave/Chrome │
│   (CLI)     │    Chrome DevTools       │  (CDP mode)  │
└─────────────┘     Protocol             └──────────────┘
       │                                        │
       │  Zero dependencies                     │  Isolated profile
       │  Pure HTTP + WebSocket                 │  Separate from your
       │  ~2500 lines, single file              │  personal browser
       └────────────────────────────────────────┘
```

**No Puppeteer. No Playwright. No Selenium.** Just direct CDP communication.

## Comparison

| Feature | cdpilot | Puppeteer | Playwright | Selenium |
|---------|-----------|-----------|------------|----------|
| Install size | **~50KB** | 400MB+ | 200MB+ | 100MB+ |
| Dependencies | **0** | 50+ | 30+ | Java + drivers |
| Setup time | **instant** | minutes | minutes | painful |
| AI-agent ready | **yes** | manual | manual | manual |
| Browser download | **no** | yes (Chromium) | yes (3 browsers) | no |
| CLI-first | **yes** | no (library) | no (library) | no |
| MCP support | **yes** | no | no | no |

## Monetization / Pro (Coming Soon)

cdpilot CLI is and will always be **free and open source** (MIT).

Future paid offerings:
- **cdpilot cloud** — Remote browser instances, no local browser needed
- **Team dashboard** — Shared sessions, audit logs, usage analytics
- **Priority support** — Direct help for enterprise integrations

## Security

- **Isolated browser profile** — cdpilot runs in `~/.cdpilot/profile`, separate from your daily browser. Your cookies, passwords, and history are never exposed.
- **No arbitrary file access** — MCP screenshot filenames are sanitized and restricted to the screenshots directory. Path traversal is blocked.
- **Safe CSS selectors** — All selectors passed to `querySelector` are JSON-escaped to prevent injection.
- **No network exposure** — CDP listens on `127.0.0.1` only. Remote connections are not possible by default.
- **No dependencies** — Zero npm/Python runtime dependencies means zero supply-chain attack surface.

Found a vulnerability? Please email the maintainer directly instead of opening a public issue.

## Roadmap

The only browser MCP with built-in test assertions. Here's what we've shipped and what's next:

### Shipped

- [x] 60+ CLI commands (navigate, click, fill, screenshot, PDF, console, network...)
- [x] MCP server for AI agent integration (Claude Code, Cursor, etc.)
- [x] **10 built-in test assertions** — assert, assert-url, assert-title, assert-count, assert-value, assert-attr, assert-visible/hidden, wait-for, check (batch), screenshot-diff
- [x] **Accessibility tree snapshot** (`a11y-snapshot`) — structured data with @ref references, 500x fewer tokens than screenshots
- [x] **Token-efficient screenshots** — element-level crop (13x smaller), JPEG quality control, format selection
- [x] **Vision fallback** (`describe`) — a11y + screenshot + text in one call
- [x] **Annotated screenshots** — @N badge overlays on interactive elements
- [x] **Auto-wait** — MutationObserver-based, 5s automatic element waiting
- [x] **Batch commands** — pipe JSON arrays via stdin for multi-step automation
- [x] Visual feedback system (persistent green glow, cursor, ripples, keystroke display)
- [x] AI control warning toast (red warning when user interacts during automation)
- [x] Multi-project browser isolation (each project gets its own port + profile)
- [x] Pre-flight wizard (auto-installs dependencies on first run)
- [x] Persistent MCP glow (stays on during entire AI session, like Claude's orange glow)
- [x] DevExtension system (native JS injection without browser store)
- [x] **Smart commands** — `smart-click`, `smart-fill`, `smart-select` — interact by visible text, no CSS selectors needed, no LLM required
- [x] **Data extraction** (`extract`) — structured DOM data in text, JSON, or list format
- [x] **Page observation** (`observe`) — list all interactive elements with available actions
- [x] **Script runner** (`run`) — execute `.cdp` script files with pass/fail reporting

### Coming Soon

- [ ] **iframe & Shadow DOM** support — interact with elements inside iframes and shadow roots
- [ ] **Session recording & replay** — record browser sessions and replay them deterministically
- [ ] **Stealth mode** *(Pro)* — human-like mouse/typing, anti-fingerprint, CAPTCHA solving
- [ ] **cdpilot Cloud** — hosted browser sessions API, REST + WebSocket MCP endpoint
- [ ] **Chrome Extension** — use cdpilot from any browser without CLI
- [ ] **Performance audit** — Core Web Vitals (LCP, CLS, INP) via CDP Performance domain
- [ ] **WCAG accessibility audit** — automated a11y compliance reporting
- [ ] **Claude Code Skill mode** — run as a `.claude/skills/` skill in addition to MCP

Have an idea? [Open an issue](https://github.com/mehmetnadir/cdpilot/issues) or submit a PR!

## Contributing

```bash
git clone https://github.com/mehmetnadir/cdpilot.git
cd cdpilot
npm install
npm test
```

PRs welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

## License

MIT — do whatever you want.

---

<p align="center">
  Built with the <a href="https://github.com/mehmetnadir/cdpilot">cdpilot</a> mindset: one tool, one job, done right.
</p>

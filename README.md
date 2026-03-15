# cdpilot

> Zero-dependency browser automation from your terminal. One command, full control.

[![npm version](https://img.shields.io/npm/v/cdpilot.svg)](https://www.npmjs.com/package/cdpilot)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<div align="center">
  <a href="https://github.com/mehmetnadir/cdpilot/releases/download/v0.1.2/cdpilot-video.mp4">
    <img src="https://github.com/mehmetnadir/cdpilot/raw/main/cdpilot-poster.png" alt="cdpilot demo" width="600" />
  </a>
  <br />
  <sub>Click to watch the demo video</sub>
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
- **Privacy-first** — Everything runs locally. No data leaves your machine

### Why Brave?

cdpilot uses [Brave Browser](https://brave.com) as its engine. Here's why:

| Feature | Brave | Chrome | Why it matters |
|---------|-------|--------|---------------|
| **Built-in ad blocker** | Shields (native) | Extension needed | Pages load faster, less noise in DOM |
| **Tracker blocking** | Default on | Manual config | Cleaner network logs for debugging |
| **Fingerprint protection** | Native | None | Better privacy for automated sessions |
| **Chromium-based** | Full CDP support | Full CDP support | Same DevTools Protocol, same power |
| **Open source** | Yes (MPL 2.0) | Chromium yes, Chrome no | Transparent, auditable |
| **Resource usage** | Lower memory | Higher memory | Better for running alongside your work |

**TL;DR:** Brave = Chrome's power + built-in privacy + less bloat. Perfect for automation.

> cdpilot also works with Chrome and Chromium as fallback. Brave is recommended, not required.

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

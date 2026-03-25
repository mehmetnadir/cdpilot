---
title: "I Built a 50KB Browser Automation CLI That Replaces Playwright"
published: true
tags: webdev, javascript, ai, productivity
cover_image: https://raw.githubusercontent.com/mehmetnadir/cdpilot/main/cdpilot-demo.gif
canonical_url: https://github.com/mehmetnadir/cdpilot
---

# I Built a 50KB Browser Automation CLI That Replaces Playwright

## The Problem

Every time I set up browser automation for an AI agent, the same pain:

```bash
npm install playwright    # 200MB+ download
npx playwright install    # 3 more browser downloads
# Write boilerplate, configure launch options, handle contexts...
```

400MB of dependencies to take a screenshot. Dozens of files to click a button. A library designed for test suites when all I needed was a CLI command.

I asked myself: **What if browser automation was as simple as `curl`?**

## The Solution: cdpilot

```bash
npx cdpilot launch
npx cdpilot go https://example.com
npx cdpilot shot
```

That's it. No install step. No config files. No boilerplate.

**cdpilot** is a zero-dependency browser automation CLI that talks directly to your existing browser via Chrome DevTools Protocol. It's ~50KB total, ships with 40+ commands, and includes a built-in MCP server for AI agents.

## How It Works

Instead of downloading a separate browser binary (like Playwright and Puppeteer do), cdpilot connects to your already-installed browser:

```
┌─────────────┐     HTTP/WebSocket      ┌──────────────┐
│   cdpilot   │ ◄──────────────────────► │ Brave/Chrome │
│    (CLI)    │    Chrome DevTools       │  (CDP mode)  │
└─────────────┘     Protocol             └──────────────┘
```

The entire tool is a single Python file (~2500 lines) with a thin Node.js wrapper for `npx` distribution. No compiled binaries. No native modules. No dependency tree.

## The Numbers

| | cdpilot | Puppeteer | Playwright | Selenium |
|--|---------|-----------|------------|----------|
| **Install size** | ~50KB | 400MB+ | 200MB+ | 100MB+ |
| **Dependencies** | 0 | 50+ | 30+ | Java + drivers |
| **Setup time** | Instant | Minutes | Minutes | Painful |
| **Browser download** | No | Yes | Yes (3 browsers) | No |
| **CLI-first** | Yes | No (library) | No (library) | No |
| **MCP server** | Built-in | No | Community | No |

## What Can It Do?

### Navigation & Content
```bash
cdpilot go https://news.ycombinator.com
cdpilot content          # Get page text
cdpilot html             # Get full HTML
cdpilot shot page.png    # Screenshot
cdpilot pdf page.pdf     # Save as PDF
```

### Interaction
```bash
cdpilot click "#search-input"
cdpilot type "#search-input" "browser automation"
cdpilot submit "#search-form"
cdpilot keys "ctrl+a"
cdpilot scroll-to ".footer"
```

### Debugging
```bash
cdpilot console          # Capture console logs
cdpilot network          # Monitor network requests
cdpilot perf             # Performance metrics
cdpilot eval "document.title"
```

### Device Emulation & Geolocation
```bash
cdpilot emulate iphone
cdpilot geo istanbul
cdpilot throttle slow3g
```

### Accessibility (AI Agent Gold)
```bash
cdpilot a11y             # Full accessibility tree
cdpilot a11y summary     # Quick overview
cdpilot a11y find button # Find all buttons
```

This is particularly powerful for AI agents. Instead of parsing raw HTML, agents get a structured accessibility tree -- the same data screen readers use.

## AI Agent Integration

This is where cdpilot really shines. It was built for AI agents from day one.

### Claude Code (MCP)

Add this to your MCP config:

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

Now Claude can browse the web, take screenshots, fill forms, and interact with any website -- all through a lightweight 50KB tool.

### Any LLM via subprocess

```python
import subprocess

def browser_action(command):
    result = subprocess.run(
        ["npx", "cdpilot"] + command.split(),
        capture_output=True, text=True
    )
    return result.stdout
```

## Visual Feedback

One thing that annoyed me about headless automation: you never know what's happening. cdpilot injects visual feedback into the browser:

- **Green glow overlay** when automation is active
- **Cursor visualization** so you can see where clicks happen
- **Click ripple effects** for visual confirmation
- **Keystroke display** showing what's being typed
- **Red warning toast** when you try to interact during automation

This makes debugging automation scripts 10x easier.

## Multi-Project Isolation

Each project gets its own browser instance automatically:

```bash
# In project A (port 9222)
cd ~/project-a && npx cdpilot launch

# In project B (port 9223, auto-assigned)
cd ~/project-b && npx cdpilot launch
```

No port conflicts. No session pollution. Each project is isolated.

## The Philosophy

I believe developer tools should be:

1. **Zero-config** -- work out of the box
2. **Zero-dependency** -- no supply chain risk
3. **CLI-first** -- composable with other tools
4. **AI-native** -- designed for LLM tool-use, not just humans

cdpilot is all four.

## Try It Now

```bash
npx cdpilot launch
npx cdpilot go https://github.com/mehmetnadir/cdpilot
npx cdpilot shot
```

If you find it useful, a star on GitHub helps a lot:

**GitHub:** [github.com/mehmetnadir/cdpilot](https://github.com/mehmetnadir/cdpilot)
**npm:** [npmjs.com/package/cdpilot](https://www.npmjs.com/package/cdpilot)

---

*cdpilot is MIT licensed and free forever. PRs welcome!*

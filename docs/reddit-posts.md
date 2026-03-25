# Reddit Launch Posts for cdpilot

> Each section is a separate post for a different subreddit. Follow each subreddit's rules.

---

## r/ClaudeAI

**Title:** I built a lightweight MCP tool for browser automation -- cdpilot (50KB, zero dependencies)

**Body:**

I've been using Claude Code for development and needed a way to give it browser control without the overhead of Playwright MCP (which downloads entire browser binaries).

**cdpilot** is a zero-dependency browser automation CLI with a built-in MCP server. It connects to your existing Brave/Chrome browser via CDP -- no downloads, no bloat.

### Setup (30 seconds)

Add to your MCP config:

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

Then Claude can:
- Navigate to any URL
- Take screenshots
- Click elements, fill forms
- Read page content and accessibility trees
- Monitor console logs and network requests
- Emulate mobile devices

### Why not Playwright MCP?

| | cdpilot | Playwright MCP |
|--|---------|---------------|
| Install size | ~50KB | 200MB+ |
| Browser download | No (uses yours) | Yes |
| Dependencies | 0 | 30+ |
| Commands | 40+ | Varies |

### Key feature for AI: Accessibility tree snapshots

```bash
npx cdpilot a11y
```

Returns structured a11y data that's much more useful for AI agents than raw HTML.

**GitHub:** https://github.com/mehmetnadir/cdpilot
**npm:** `npx cdpilot launch`

Would love feedback from other Claude Code users!

---

## r/SideProject

**Title:** cdpilot -- Zero-dependency browser automation CLI (50KB vs Playwright's 200MB)

**Body:**

Hey everyone! Sharing a side project I've been working on.

**What is it?**
A CLI tool that lets you control a browser from your terminal. Navigate, click, type, screenshot, monitor network -- 40+ commands, all without installing any dependencies.

**Why I built it:**
I was building AI agents that needed browser control. Every existing solution (Playwright, Puppeteer, Selenium) required hundreds of megabytes of downloads and complex setup. I wanted something that "just works" with `npx`.

**The interesting technical bits:**
- Zero npm and Python dependencies -- uses only standard library
- Single Python file (~2500 lines) as the core
- Talks directly to your browser via Chrome DevTools Protocol
- Built-in MCP server for AI agent integration
- Visual feedback system (green glow, cursor vis, click ripples)

**The numbers:**
- ~50KB total install size (vs 200-400MB for alternatives)
- 40+ commands
- Works with Brave, Chrome, and Chromium
- Multi-project isolation (each project gets its own browser)

**Try it:**
```bash
npx cdpilot launch
npx cdpilot go https://example.com
npx cdpilot shot
```

**GitHub:** https://github.com/mehmetnadir/cdpilot

Feedback and contributions welcome! MIT licensed.

---

## r/opensource

**Title:** cdpilot: Zero-dependency, single-file browser automation CLI [MIT]

**Body:**

I'm open-sourcing **cdpilot**, a browser automation CLI built with a minimalist philosophy:

**Core principles:**
1. **Zero dependencies** -- no npm packages, no Python packages. Pure stdlib.
2. **Single file** -- the entire core is one Python file (~2500 lines). Easy to audit.
3. **CLI-first** -- every operation is a standalone command. Composable with scripts and pipes.
4. **Use what you have** -- connects to your existing browser, doesn't download its own.

**Why zero dependencies matters:**
- No supply chain attack surface
- No version conflicts
- No `npm audit` warnings
- No breaking changes from upstream packages
- Auditable in an afternoon

**What it does:**
40+ commands for browser automation: navigate, interact, screenshot, PDF, network monitoring, console capture, device emulation, accessibility tree, request interception, and more.

**Architecture:**
```
Node.js entry (npx compatible) -> spawns Python core -> CDP over HTTP/WebSocket -> Your browser
```

The Node.js layer handles browser detection and Python discovery. The Python core handles all CDP communication using only `urllib` and `asyncio`.

**AI integration:**
Includes a built-in MCP (Model Context Protocol) server, so AI agents like Claude Code can control the browser natively.

**GitHub:** https://github.com/mehmetnadir/cdpilot
**License:** MIT
**npm:** `npx cdpilot launch`

Looking for contributors, especially for:
- Windows testing and edge cases
- Additional CDP command coverage
- CI/CD pipeline improvements

---

## r/webdev

**Title:** Built a Puppeteer/Playwright alternative that's 50KB with zero dependencies

**Body:**

I know, I know -- "yet another browser automation tool." But hear me out.

**The pitch:** What if browser automation was as simple as `curl`?

```bash
npx cdpilot go https://example.com
npx cdpilot click "#login-button"
npx cdpilot type "#email" "test@example.com"
npx cdpilot shot login-page.png
```

No library imports. No async/await boilerplate. No browser downloads. Just CLI commands.

**How it compares:**

| | cdpilot | Puppeteer | Playwright | Selenium |
|--|---------|-----------|------------|----------|
| Install size | ~50KB | 400MB+ | 200MB+ | 100MB+ |
| Dependencies | 0 | 50+ | 30+ | Java + drivers |
| Setup | `npx` | `npm i` + download | `npm i` + install | JDK + drivers |
| Interface | CLI | Library | Library | Library |
| Browser | Yours | Downloads Chromium | Downloads 3 | Uses yours |

**What it's NOT:**
- Not a test framework (no assertions, no test runner)
- Not trying to replace Playwright for E2E testing suites
- Not a library you import into your code

**What it IS:**
- A CLI for quick browser automation tasks
- A tool for AI agents that need browser control
- A debugging companion (`cdpilot console`, `cdpilot network`, `cdpilot perf`)
- A lightweight alternative when you don't need a full framework

**Cool features:**
- Visual feedback (green glow overlay, cursor vis, click ripples) -- great for debugging
- Multi-project isolation (each project gets its own browser port)
- Request interception and mocking from CLI
- Device emulation presets (iPhone, iPad, Android)
- Accessibility tree snapshots
- Built-in MCP server for AI agents

**Try it:**
```bash
npx cdpilot launch
npx cdpilot go https://news.ycombinator.com
npx cdpilot content
```

**GitHub:** https://github.com/mehmetnadir/cdpilot

Happy to answer questions about the architecture. The entire core is a single Python file -- easy to read and contribute to.

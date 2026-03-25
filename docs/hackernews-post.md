# Hacker News - Show HN Post

## Title Options (pick one)

1. **Show HN: cdpilot -- 50KB zero-dependency browser automation CLI (replaces Playwright for AI agents)**
2. **Show HN: cdpilot -- Browser automation with zero dependencies, 40+ CLI commands, built-in MCP server**
3. **Show HN: I built a 50KB alternative to Playwright for AI agent browser control**

> Recommendation: Option 1 -- it's specific, has the key differentiators, and mentions the target use case.

---

## URL

https://github.com/mehmetnadir/cdpilot

---

## First Comment (post immediately after submission)

Hey HN! I built cdpilot because I was frustrated with the state of browser automation for AI agents.

**The problem:** Every time I needed an AI agent (Claude, GPT) to interact with a browser, I had to install Playwright (200MB+) or Puppeteer (400MB+), download separate browser binaries, and write boilerplate code. For what? To take a screenshot or click a button.

**The solution:** cdpilot is a CLI that talks directly to your existing browser via Chrome DevTools Protocol. The entire tool is ~50KB -- a single Python file with a thin Node.js wrapper for npx distribution.

```
npx cdpilot launch
npx cdpilot go https://example.com
npx cdpilot shot
```

**Key decisions:**

- **Zero dependencies** -- no npm packages, no Python packages. Just stdlib. This eliminates supply chain risk entirely.
- **CLI-first** -- every command is a standalone operation. Composable with pipes, scripts, and AI tool-use.
- **Uses your existing browser** -- no downloading Chromium. cdpilot finds Brave/Chrome/Chromium on your system and connects via CDP.
- **Built-in MCP server** -- AI agents (Claude Code, etc.) can control the browser out of the box.
- **Single file architecture** -- the entire core is one ~2500-line Python file. Easy to audit, easy to understand.

**What it's NOT:** It's not a test framework. It doesn't replace Playwright's test runner or assertion library. It replaces the browser automation layer with something 4000x lighter.

The visual feedback system (green glow overlay, cursor visualization, click ripples) was born from debugging AI automation -- you need to see what the agent is doing.

Tech stack: Node.js entry point + Python core, pure HTTP/WebSocket CDP communication, asyncio for WebSocket handling.

Happy to answer any questions about the architecture or design decisions!

GitHub: https://github.com/mehmetnadir/cdpilot
npm: https://www.npmjs.com/package/cdpilot

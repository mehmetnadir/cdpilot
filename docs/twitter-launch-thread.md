# Twitter/X Launch Thread for cdpilot

> Copy each tweet as a separate post in a thread. Post tweet 1 first, then reply with the rest.

---

## Tweet 1 (Hook)

I replaced Playwright with a 50KB CLI tool.

Zero dependencies. 40+ commands. Works with your existing browser.

Meet cdpilot -- browser automation that just works.

Thread:

---

## Tweet 2 (The Problem)

Every browser automation tool wants you to:

- Download 200-400MB of dependencies
- Install separate browser binaries
- Write boilerplate code
- Configure launch options

What if you could skip all of that?

---

## Tweet 3 (The Solution)

```
npx cdpilot launch
npx cdpilot go https://example.com
npx cdpilot shot
```

That's the entire setup. No install step. No config files.

cdpilot talks directly to your existing Brave/Chrome browser via Chrome DevTools Protocol.

---

## Tweet 4 (Comparison)

The difference is staggering:

| | cdpilot | Playwright | Puppeteer |
|--|---------|-----------|-----------|
| Size | 50KB | 200MB+ | 400MB+ |
| Deps | 0 | 30+ | 50+ |
| Setup | Instant | Minutes | Minutes |
| CLI | Yes | No | No |
| MCP | Built-in | Community | No |

---

## Tweet 5 (AI Agents)

Built for AI agents from day one.

Claude, GPT, Gemini -- any LLM can control a browser through cdpilot:

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

MCP server included. Zero config.

---

## Tweet 6 (Visual Feedback)

The coolest part: visual feedback during automation.

- Green glow when automation is active
- Cursor visualization for clicks
- Ripple effects on interactions
- Keystroke display
- Red warning when you hover during AI control

You always know what's happening.

---

## Tweet 7 (Commands)

40+ commands out of the box:

- Navigate, click, type, submit
- Screenshot, PDF export
- Console & network monitoring
- Device emulation (iPhone, iPad, Android)
- Geolocation override
- Accessibility tree snapshots
- Request interception & mocking
- Cookie & storage management

All from your terminal.

---

## Tweet 8 (Accessibility for AI)

The a11y command is a game-changer for AI agents:

```
npx cdpilot a11y
```

Returns a structured accessibility tree -- the same data screen readers use.

Way more useful than raw HTML for AI to understand page structure.

---

## Tweet 9 (Zero Dependency)

Zero dependencies means:

- No supply chain attacks
- No version conflicts
- No "npm audit" warnings
- No breaking changes from upstream
- Works offline after first npx cache

Just Node.js + Python stdlib + your browser.

---

## Tweet 10 (Architecture)

The entire tool is:

- 1 Python file (~2500 lines) -- the core
- 1 Node.js file -- the npx entry point
- 0 npm dependencies
- 0 Python dependencies

Pure HTTP + WebSocket communication with CDP. That's it.

---

## Tweet 11 (Multi-Project)

Each project gets its own isolated browser:

```bash
cd ~/project-a && npx cdpilot launch  # port 9222
cd ~/project-b && npx cdpilot launch  # port 9223 (auto)
```

No conflicts. No session pollution. Each project is sandboxed.

---

## Tweet 12 (CTA)

Try it now:

```bash
npx cdpilot launch
npx cdpilot go https://github.com/mehmetnadir/cdpilot
npx cdpilot shot
```

GitHub: github.com/mehmetnadir/cdpilot
npm: npmjs.com/package/cdpilot

Star if you find it useful. PRs welcome.

MIT licensed, free forever.

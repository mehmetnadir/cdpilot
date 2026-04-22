# Hacker News — Show HN Post (revised 2026-04-22)

## Title Options (pick one)

1. **Show HN: cdpilot – zero-dependency browser automation CLI (1/4000th of Playwright)**
2. **Show HN: cdpilot – 60KB browser automation for AI agents, with built-in MCP server**
3. **Show HN: cdpilot – I debugged a Brave-macOS-26 crash in prod; the fix became a browser picker**

> Recommendation: **Option 1** — pure comparison numbers beat feature lists on HN.
> Option 3 is tempting but too narrative for a title; move the story to the comment.

---

## URL

https://github.com/mehmetnadir/cdpilot

---

## Submission timing

HN traffic peaks Tuesday–Thursday, 08:00–10:00 PDT (18:00–20:00 TR time).
First 2 hours are make-or-break — respond to every comment. Stay available
for ~4 hours after posting.

---

## First Comment (post immediately after submission)

Hey HN — author here.

**The itch:** Every AI agent demo that touches a browser pulls in
Playwright (~200MB) or Puppeteer (~400MB) plus a bundled Chromium.
For what — a screenshot and three clicks? I wanted a version that
talks to my already-installed Brave over CDP and does nothing else.

cdpilot is a CLI that does exactly that. The distribution is a single
Python file (`src/cdpilot.py`) plus a thin Node wrapper
(`bin/cdpilot.js`) for `npx` support. Total unpacked size: 233KB.
Zero npm deps, zero pip deps — stdlib only. You can audit the whole
thing in an afternoon.

```
npx cdpilot launch          # start an isolated Brave/Chrome/Vivaldi
npx cdpilot go <url>         # navigate
npx cdpilot a11y-snapshot    # structured accessibility tree — LLM-ready
npx cdpilot smart-click "Sign in"   # find by visible text, no selector
npx cdpilot mcp              # expose everything as an MCP server
```

**Three decisions I'll defend:**

1. **CLI-first, not a library.** Every command is a standalone process
   that writes to stdout. Composable with pipes, shell scripts, `jq`,
   and — crucially — AI tool-use loops. An LLM calling `cdpilot click`
   doesn't care what language the tool is written in.

2. **Uses your existing browser.** No bundled Chromium download. cdpilot
   picks whichever Chromium-family browser you have (Brave, Chrome,
   Vivaldi, Edge, Chromium) and connects over `--remote-debugging-port`.
   The profile lives under `~/.cdpilot/` so it doesn't touch your real
   browsing session.

3. **Workload-aware browser pick.** Shipped this week after Brave 1.89
   started crashing on macOS 26 (Tahoe) at exactly ~7min uptime —
   SIGTRAP in ThreadPoolForegroundWorker, deterministic across 9+
   dumps. While digging into that I noticed Chrome 147 silently drops
   `--load-extension` for unpacked extensions (no error, no warning).
   So `cdpilot browser auto` now reads the dev-extension registry:
   if you're doing extension work it prefers Vivaldi/Brave/Edge (they
   honor the flag); if you're not, it prefers Chrome (most stable).
   Both tradeoffs are surfaced in `cdpilot browser status` with a
   reason string — I hate tools that make silent choices.

**What's in it that surprised people in testing:**

- `cdpilot describe` — one command combines a11y tree + OCR + screenshot
  for LLM vision fallback. A screenshot-describe round-trip goes from
  ~250k tokens (Computer Use style) to ~500 tokens.
- `cdpilot stealth on` — zero-dep fingerprint patches (opt-in). Passes
  bot.sannysoft 24/24, Cloudflare full challenge at nowsecure.nl, and
  incolumitas intoli 6/6. It does NOT beat `incolumitas overflowTest`
  because that probe detects CDP presence itself — no JS patch can hide
  the protocol.
- `cdpilot health` — JSON status with today's crash count from macOS
  DiagnosticReports. Designed for `until cdpilot health; do launch;
  done` watchdog loops.

**What it's NOT:** not a test framework. No runner, no assertion DSL
(though there are 10 assertion commands for CI pipelines). It replaces
the automation layer only.

Would love feedback on the `browser auto` policy in particular — the
two-axis (extension workload × platform stability) ended up being one
of those decisions that feels obvious in hindsight but wasn't on my
roadmap. Are there other workload signals I should be reading?

GitHub: https://github.com/mehmetnadir/cdpilot
npm: https://www.npmjs.com/package/cdpilot

---

## Rebuttal drafts (prepped for expected comments)

**"Why not just use Playwright?"**
> Fair — if you're writing a test suite, Playwright is the right tool.
> cdpilot replaces the automation layer below the test runner. If
> you're an AI agent that needs to take a screenshot of a user's
> browser, shipping 200MB + a bundled Chromium just to call
> `page.screenshot()` is wrong-sized for the job.

**"Zero dependencies is a feature until you need something"**
> Agreed — if I ever need something stdlib can't provide, the zero-dep
> promise breaks. So far (3600 LOC Python) the discipline has been
> useful: it forced me to think about what's actually essential vs.
> what's library habit. The WebSocket client is 80 lines of asyncio.
> The CDP protocol handler is 30. That's the whole "dependency."

**"Chrome already has remote-debugging"**
> Yes — cdpilot is a thin ergonomic layer over that. The value is
> `npx cdpilot go <url>` works on a fresh machine in 2 seconds vs.
> writing the WebSocket handshake + CDP message pump yourself.

**"This is just curl for browsers"**
> Basically, yeah. That's a compliment.

---

## URL

https://github.com/mehmetnadir/cdpilot

---

## Notes for the post-launch first hour

- **Don't editorialize the title.** No "My ..." or "I made ..." — HN
  downweights those.
- **No emojis in title.** Dang (moderator) kills them.
- **Respond fast, stay civil.** Even hostile comments — dry acknowledgment
  > defensive rebuttal.
- **If someone says "there's already X"** — thank them, check X,
  acknowledge differences without trashing X.
- **First 30 minutes matter most.** One upvote in the first 10 min
  = 10 in hour 3.

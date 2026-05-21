# @cdpilot_dev — X Content Strategy Master Plan

> Version 1.0 — May 2026. Living document. Update after each monthly review.

---

## 1. Mission & Positioning

Most browser automation is bloated, over-abstracted, and easily detected. `@cdpilot_dev` exists to demystify the raw Chrome DevTools Protocol (CDP) and provide the surgical alternative to Playwright/Puppeteer. We don't hide the complexity — we embrace it to gain precise control.

The positioning is "The Engineer's Tool." We focus on how the web actually works under the hood: `Network.setBlockedURLs`, rAF-throttled MutationObservers, JA4 TLS fingerprinting, and behavioral entropy. If you're tired of `waitForSelector` timeouts and want to understand what's actually happening at the WebSocket level, you're in the right place.

Zero dependencies is the north star. No Playwright. No puppeteer-cluster. No node_modules/ sprawl. Pure `urllib`, `asyncio`, and Chrome's own protocol — which means the tool can be audited in an afternoon and runs anywhere Python 3 runs.

---

## 2. The 8 Tracks

### Monday — T1: Foundations (CDP Internals)

Deep dives into the protocol layer. How `Target.createBrowserContext` enables true parallelism without spawning separate Chrome processes. Why `Runtime.evaluate` in batch mode (`eval-batch`) is faster than sequential JS injection. How the `Network` domain intercepts traffic before the renderer sees it.

This track is for the developer who switched from Selenium to Playwright and wonders "what is Playwright actually doing?" We show the raw wire. Topics include: the CDP WebSocket handshake, tab lifecycle events, `Page.frameNavigated` vs `Page.loadEventFired`, `DOM.getDocument` vs `Runtime.evaluate` for DOM reads, and the `Fetch.enable` interception model.

Difficulty ramp: beginners get "what is CDP and why does it matter," intermediates get "how `wait-for-text` uses a rAF-throttled MutationObserver instead of polling," advanced gets "session multiplexing and per-target WS connection reuse."

### Tuesday — T2: Anti-Bot Wars

The tactical front. Real-world breakdowns of how Cloudflare, Akamai, DataDome, PerimeterX, and hCaptcha detect headless environments. Not theory — actual JS decompilation results, observed network patterns, and what countermeasures actually work in 2026.

We analyze the cat-and-mouse game: TLS fingerprinting (JA3/JA4), WebDriver presence checks, `navigator.plugins` anomalies, timing side-channels, and behavioral scoring. cdpilot's adaptive escalation model (detect CAPTCHA → enable stealth per-host → re-navigate) serves as a running case study.

Occasionally include loss stories: "we tried X and DataDome still caught it. Here's why." Authenticity > bragging. The audience is scraping professionals, security researchers, and devs who've hit 403s on legitimate automation tasks.

### Wednesday — T3: AI Agents (Browser as Agent Backend)

Compare cdpilot against "heavy" agent frameworks: browser-use, Stagehand, Skyvern, ChatBrowserUse. The angle: those tools are the UI, cdpilot is the engine under the hood. High-level frameworks leak tokens on DOM noise — we show how to pipe only meaningful events to the LLM.

Topics: using `wait-for-text` to detect streaming LLM responses in browser, `eval-batch` for token-budget-aware DOM snapshots, how agent frameworks handle navigation failures (and how cdpilot's `health` probe enables watchdog patterns). Also covers the AI agent anti-patterns: screenshot-every-tick, full-page HTML to context, blocking on JS dialogs.

Cross-track with T1 (CDP internals) and T4 (stealth) frequently — autonomous agents need stealth even more than manual scrapers.

### Thursday — T4: Stealth Engineering

The art of camouflage. Canvas fingerprinting, WebGL parameter spoofing, AudioContext entropy, font enumeration, `navigator.hardwareConcurrency` normalization, and why behavioral entropy (mouse timing distributions, scroll acceleration curves) is the hardest layer to fake convincingly.

cdpilot's stealth layer serves as reference implementation. We explain the smart no-op approach: `navigator.webdriver` patch fires only when the value is `true`, avoiding the defineProperty call itself being a detection signal. We discuss what `Page.addScriptToEvaluateOnNewDocument` can and cannot do.

Honest limits section monthly: CDP detection via `incolumitas.overflowTest` and `fpscanner.WEBDRIVER` cannot be patched at the JS level — the binary tells the truth. We explain this clearly. The audience respects honesty over over-promising.

### Friday — T5: E2E Testing

Productivity and reliability angle. How cdpilot's test runner compares to Playwright's trace viewer, Vitest Browser Mode, and `@playwright/test`. Focus on synchronization: CDP events vs arbitrary `sleep` calls, why `Page.loadEventFired` is wrong for SPAs, and how `wait-for-text` with a MutationObserver eliminates 80% of flaky tests.

Practical content: migrating a 50-test Playwright suite to cdpilot, CI/CD integration patterns (the `health` probe as readiness check), zero-dependency builds making Docker images smaller. Also: common test anti-patterns that cause non-deterministic failures — and the CDP-native fix for each.

### Saturday — T6: Performance & Scale

The engine track. Context pools with `Target.createBrowserContext × N` — how to saturate a 16-core server with parallel browser contexts without running 16 Chrome instances. WS pool (per-target connection reuse) — why reconnecting per-command at scale is the bottleneck.

Efficient mode (visual feedback off by default) reduces CDP roundtrips by ~30% on interactive-heavy pages. `block` command with image/font/ad presets for resource-constrained scraping. Memory management at 100k+ pages/day. Also: profiling CDP latency with `Performance.getMetrics`, identifying which commands are the bottleneck.

### Sunday — T7: History + T8: Hot Takes (alternate)

**T7 (History):** The evolution of browser automation — Selenium's WebDriver, the headless Chrome revolution, Chrome 59 `--headless`, Puppeteer, Playwright, CDP-native tools. Why each generation broke the previous stealth model. Niche forks (Vivaldi, Brave, ungoogled-chromium) and when they matter for extension-dependent automation.

**T8 (Hot Takes):** Controversial technical opinions to drive discussion. "Playwright is the new Selenium and that's not a compliment." "If your E2E suite takes > 10 minutes, you don't have a test suite, you have a liability." "AI coding assistants write Playwright tests that are wrong 40% of the time because Playwright docs are in their training data but prod behavior isn't." Rotate T7/T8 weekly.

---

## 3. Weekly Rhythm & Interleaving Philosophy

The 7-day rotation ensures the feed never feels like a manual or documentation dump. Technical deep-dives (T2, T4) interleave with utility content (T3, T5) and context-building (T7/T8). Monday sets the conceptual stage; Tuesday immediately breaks assumptions.

Cross-track callbacks are intentional. A Wednesday AI agent thread references stealth memory from Tuesday's post. A Friday test post mentions the context pool from Saturday's post (teasing next day). A Sunday hot take calls back to a specific T1 Foundations post from 3 weeks ago. This creates a cohesive learning arc — followers feel they're building a mental model of the tool, not reading isolated tips.

Every 4 weeks, a "synthesis week" where threads explicitly connect multiple tracks. Example: "TLS fingerprinting (T4) + context pools (T6) + agent token budget (T3) = production scraper that runs 8 hours without a ban."

---

## 4. X Algorithm Rules (baked into all content)

| Signal | Impact | Implementation |
|---|---|---|
| Reply | 13× boost | 30 min/day replying to peers in automation, security, devtools space |
| Image attached | Boost | Code screenshot (carbon.now.sh) or terminal recording for every thread starter |
| Profile click | Boost | Hook tweet must make them want to know who wrote this |
| URL in main tweet | 0.5× penalty | URLs ONLY in the last reply of a thread, prefixed with "Source:" or "More:" |
| Hashtags | Negative if >2 | Max 1-2 per thread, only in last tweet |
| Identical patterns | Demote | Vary hook structure each day |

**Hook rules:** Every thread starter (1/N) must end with a question or a provocative technical claim. "Here's how X works" → bad. "X is lying to you about Y. Here's the actual implementation:" → good.

**Code snippet placement:** Never first tweet, never last tweet. Middle of thread only. First tweet = hook. Last tweet = CTA/source.

**@grok mentions:** ~1 per week, provocative technical question targeting their replies. Drives cross-platform discovery.

---

## 5. Humanizer Principles

**Length variance:**
- 40% — single-line zinger (the throwaway that gets bookmarked)
- 35% — medium (2-4 tweet thread or long single tweet)
- 20% — full thread (5-12 tweets)
- 5% — just an emoji reaction to someone else's post

**Register:** Senior dev casual. "okay this is cursed" not "I'm excited to share." "we" for the project, "I" for debugging pain. Contractions always. Abbreviations: CDP, WS, DOM, API — never spell them out.

**Personal touches (~15% of posts):** 3 AM debugging references, bad coffee, weekend coding sessions that went sideways, sleep deprivation humor. "it's 2am and I just realized our stealth patches run before the page's own JS — which is actually the correct behavior — which means I've been wrong about this for 6 months."

**Off-topic (~10-15%):** Movie/game reference, non-cdpilot dev rant, observation about the state of OSS. Keeps the feed human. Don't force it — have 5-6 real off-topic tweets drafted and drop them when engagement needs variety.

**Intentional friction (~2%):** Typo in a non-technical word, then correction reply ("*fixed, obviously can't type at this hour"). Never typo in numbers, benchmarks, or technical claims — those must be accurate. The correction reply itself generates engagement.

**Posting timing (guide for scheduling engine):**
- Active window: 13:00-23:00 İstanbul (10:00-20:00 UTC)
- Hot zones: 17:00-19:00 İst (tutorials/threads), 21:00-23:00 İst (hot takes/discussion), 13:00-15:00 İst (quick tips)
- Skip Sundays ~50% of the time
- Gaussian jitter ±30min around target time — never post at :00
- Burst patterns: sometimes 2 tweets 20 minutes apart, sometimes 6+ hour gap

---

## 6. Engagement Learning Loop

**Weekly review (every Monday):** Pull bookmark/reply/impression data for the previous week. Bookmarks and replies outweigh likes. High bookmark rate on a T4 Stealth thread = double down on sub-topic next month.

**Pivot signals:**
- T5 Testing engagement lagging → shift angle from "reliability" to "speed/cost savings"
- T2 Anti-Bot generating high reply count → schedule a follow-up Q&A thread that same week
- T3 AI Agents getting DMs → write an X Article expanding the thread

**Repurposing pipeline:**
- Top-performing thread (>500 bookmarks) → X Article draft
- X Article → documentation example or README section
- Documentation improvement → announcement tweet (cross-track T1)

**Dead content signals:** If a topic generates <50 impressions in 2 consecutive weeks, retire it from rotation. Replace with something from the "backlog bank" (ideas file).

---

## 7. X Articles Strategy

One deep-dive article per month. Premium X Articles for long-form (no external CMS needed). Articles expand the best-performing threads of the month into a complete reference piece.

**Format:** 1500-3000 words. "Whitepaper" tone — technical accuracy first, readability second. Code snippets inline. Diagrams where ASCII art works.

**Traffic flow:** Thread → Article → GitHub repo → npm install. The article is the bridge between casual follower and actual user.

**First 12 article ideas:** see `articles.md`.

---

## 8. Year 2 Philosophy

Year 1 establishes technical authority. Year 2 shifts from broadcasting to conversation.

**Audience-led content:** "Give me a URL and I'll live-tweet how to bypass its bot protection with cdpilot." Community challenges. "Build something with cdpilot this weekend" prompts.

**Collaboration:** Guest threads with other tool authors (Playwright maintainers, Browserbase team, security researchers). Not promotional — actual technical disagreements and discussions.

**AMA weeks:** Monthly "ask me anything about CDP internals." Raw, unfiltered technical Q&A. No marketing speak.

**Reduced structure:** Year 2 track rotation loosens based on what the audience actually engages with. Some tracks may merge, new ones may emerge. The 8-track system is a bootstrap, not a prison.

---

*Last updated: 2026-05-18*

# Changelog

All notable changes to cdpilot will be documented in this file.

## [Unreleased]

### Breaking
- **Visual feedback default flipped to OFF.** The glow border, fake cursor, click ripples and keystroke display were originally a trust signal that made an automation session legible to a human watching the screen. In day-to-day automation use the animations made cdpilot feel slow and amateurish — animated cursor moves take frames, the glow re-flashes between pages, every action triggers a ripple. Default OFF gives a quiet, professional experience. Bring it back any of these ways: `cdpilot show on` (persists), `CDPILOT_SHOW=1` (one-shot), or `CDPILOT_MCP_SESSION=1` (the existing MCP persistent-glow flow, still honored exactly as before). The MCP server itself sets `CDPILOT_MCP_SESSION=1` so AI sessions retain the visible glow automatically — no migration needed for that flow.

### Added
- **`cdpilot show [on|off|status]`** — toggle the visual feedback layer. Persisted in `~/.cdpilot/profile/visual.json`. Status output shows whether `CDPILOT_MCP_SESSION` is overriding it.
- **`cdpilot fast [on|off|status]`** — fast mode bundle. Currently shortens the auto-wait timeout (5000ms → 2000ms). Persisted in `~/.cdpilot/profile/fast.json`. Override the timeout independently via `CDPILOT_WAIT_MS=<ms>` (env wins over the mode default so power users can dial without touching the bundle switch).
- **`wait-for-text <text> [timeout_ms]`** — adaptive wait for a text fragment to appear anywhere in `document.body.innerText`. Uses `MutationObserver` with `childList + subtree + characterData` so it catches text-node updates from streaming sources (AI chat responses, typewriter effects, late-loaded banners). Returns the moment the text renders with 30 chars of surrounding context — eliminates fixed `sleep()` calls when the selector is unknown but the text is predictable. Throttled via `requestAnimationFrame` so high-frequency mutations (streaming AI tokens) don't trigger an `innerText` reflow on every character.
- **MCP tool `browser_wait_for_text`** — same capability exposed to AI agents (Claude Code, Cursor) via the built-in MCP server. Ideal for citation tracking, AI response synchronization, and async-content workflows.
- **`eval-batch <json_array>`** — evaluate N JS expressions in a SINGLE `Runtime.evaluate` roundtrip. Each expression runs in its own try/catch so one failure doesn't sink the batch; results return as a JSON array of `{ok, value}` or `{ok:false, error}`. Typical speedup: 5-30x vs sequential `eval` calls when reading many small DOM values. **MCP:** `browser_eval_batch`.
- **`block [on|off|preset|patterns|clear]`** — block requests by URL pattern via `Network.setBlockedURLs`. Built-in presets: `images`, `fonts`, `media`, `ads` (known analytics/ad networks). Patterns persist in `~/.cdpilot/profile/block.json` and apply on every subsequent navigation. **Opt-in only** — blocking changes the fingerprint surface (real browsers fetch images/fonts), do NOT combine with stealth-mode targets. Typical speedup on image-heavy pages: 3-10x faster load.

### Changed
- **`scrollIntoView` switched from `'smooth'` to `'instant'`** in `cmd_click` and `smart-click`. Smooth scroll animates ~300-500ms before the actual click fires; in automation it never adds value, just delay. Pure perf win, no API change.
- **`navigate_collect` post-load sleep cut from 1500ms → 300ms.** The original blind 1.5s wait after `Page.loadEventFired` was the single biggest contributor to the "amateur typing" feel cdpilot used to have on every navigation. 300ms is enough buffer for late JS without paying 1.2s of dead time per call. The outer 20s deadline still applies, so unusually slow pages aren't cut short — they just don't pay the floor on every nav.
- **Internal: TTL cache on `cdp_get('/json')`** — a typical CLI command hits the CDP HTTP discovery endpoint 3-7 times during one invocation (session lookup, tab discovery, target validation). Caching for 500ms within one process collapses those to a single fetch. Cache auto-invalidates after tab-mutating operations (`new-tab`, `close-tab`, session window creation) so stale state can never be observed. No behavior change — pure dedup.
- **Internal: WebSocket connection pool for `cdp_send`** — pooled per-target WebSocket connections eliminate the WebSocket handshake cost on repeated CDP calls within one process (MCP server, batch mode, multi-step CLI). On localhost the win is small (~2% in a 20-call bench), but the cost compounds on slower hosts (Windows, Docker, remote CDP), is essential for the future hosted-browser scenario, and reduces file-descriptor churn under high call volume. Single-shot CLI invocations are unaffected — the process opens one connection, uses it, atexit closes it (verified equal wall-clock). Pool is per-`ws_url`, with an `asyncio.Lock` for serial access to each target so concurrent calls don't interleave command frames. The hot path skips drain checks — a connection is re-pooled only after `pending` was fully consumed (recv loop exited cleanly), so by construction no stale response frames are waiting. On stale-connection failure: drop and retry ONCE with a fresh connection, but ONLY when no responses were collected yet — never replay after partial progress (would re-fire non-idempotent commands like mouse events or form submits). Opt-out via `CDPILOT_WS_POOL=0` (default ON). Zero new deps — uses the existing `websockets` library and stdlib `atexit`.

## [0.3.0] - 2026-04-07

### Added
- **Smart commands** — interact by visible text, no CSS selectors or LLM needed
  - `smart-click <text>` — fuzzy match across textContent, aria-label, title, placeholder
  - `smart-fill <label> <value>` — find input by label/placeholder, React-compatible
  - `smart-select <label> <option>` — select dropdown by label text
- **Data extraction** (`extract`) — structured DOM data in text, JSON, or list format
- **Page observation** (`observe`) — list all interactive elements with available actions (CLICK, FILL, NAVIGATE, TOGGLE, SELECT, SUBMIT, UPLOAD)
- **Script runner** (`run <script.cdp>`) — execute `.cdp` script files with pass/fail reporting
- **10 test assertions** — unique among all browser MCP servers
  - `assert`, `assert-url`, `assert-title`, `assert-count`, `assert-value`, `assert-attr`, `assert-visible`, `assert-hidden`, `wait-for`, `check` (batch), `screenshot-diff`
- **Token-efficient screenshots** — element-level crop (13x smaller), JPEG quality control, format selection
- **Pre-flight wizard** — auto-checks Python, websockets, browser on first launch; auto-installs missing deps
- **Persistent MCP glow** — `CDPILOT_MCP_SESSION=1` keeps glow active during entire AI session
- **MCP tool descriptions** enriched for Glama TDQS scoring (6 quality dimensions)
- **Glama.ai integration** — `glama.json` metadata, claimed on Glama registry
- **GitHub Actions** — PR auto-review (syntax + tests + zero-dep lint) + welcome bot for first-time contributors

### Fixed
- Python 3.8-3.11 compatibility — removed backslash in f-strings (reported by @senthazalravi)

## [0.2.0] - 2026-04-05

### Added
- **Accessibility tree snapshot** (`a11y-snapshot`) — Structured a11y data with @ref references for AI agents
- **Click by reference** (`click-ref @N`) — Click elements using a11y snapshot references
- **Annotated screenshots** (`shot-annotated`) — Screenshots with @N badge overlays on interactive elements
- **Auto-wait** — Commands automatically wait up to 5s for elements using MutationObserver
- **Batch commands** (`batch`) — Pipe JSON arrays via stdin for multi-step automation
- **Vision fallback** (`describe`) — Combined a11y snapshot + screenshot + text content in one call
- **Visual feedback system** — Persistent green glow overlay, cursor visualization, click ripples, keystroke display
- **AI control warning** — Red toast appears when user hovers during automation: "Browser is controlled by AI"
- **Multi-project isolation** — Each project directory gets its own browser port and profile automatically
- **Project management commands** — `projects`, `project-stop`, `stop-all`
- **MCP `browser_describe` tool** — Vision fallback accessible via MCP for remote AI agents

### Fixed
- Glow overlay now persists across page navigations (re-injected after navigation)
- Multi-project `CDPILOT_PROJECT_ID` env correctly passed from Node.js to Python

### Changed
- Auto-wait is now the default behavior for `click` and `fill` commands
- Persistent script cleanup deferred to 10s JS timeout instead of immediate removal

## [0.1.2] - 2026-03-20

### Added
- Initial release with 40+ CLI commands
- MCP server for Claude Code integration
- DevExtension system (native JS injection)
- Cross-platform browser detection (Brave > Chrome > Chromium)

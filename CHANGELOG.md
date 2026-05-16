# Changelog

All notable changes to cdpilot will be documented in this file.

## [Unreleased]

### Added
- **`wait-for-text <text> [timeout_ms]`** — adaptive wait for a text fragment to appear anywhere in `document.body.innerText`. Uses `MutationObserver` with `childList + subtree + characterData` so it catches text-node updates from streaming sources (AI chat responses, typewriter effects, late-loaded banners). Returns the moment the text renders with 30 chars of surrounding context — eliminates fixed `sleep()` calls when the selector is unknown but the text is predictable. Throttled via `requestAnimationFrame` so high-frequency mutations (streaming AI tokens) don't trigger an `innerText` reflow on every character.
- **MCP tool `browser_wait_for_text`** — same capability exposed to AI agents (Claude Code, Cursor) via the built-in MCP server. Ideal for citation tracking, AI response synchronization, and async-content workflows.
- **`eval-batch <json_array>`** — evaluate N JS expressions in a SINGLE `Runtime.evaluate` roundtrip. Each expression runs in its own try/catch so one failure doesn't sink the batch; results return as a JSON array of `{ok, value}` or `{ok:false, error}`. Typical speedup: 5-30x vs sequential `eval` calls when reading many small DOM values. **MCP:** `browser_eval_batch`.
- **`block [on|off|preset|patterns|clear]`** — block requests by URL pattern via `Network.setBlockedURLs`. Built-in presets: `images`, `fonts`, `media`, `ads` (known analytics/ad networks). Patterns persist in `~/.cdpilot/profile/block.json` and apply on every subsequent navigation. **Opt-in only** — blocking changes the fingerprint surface (real browsers fetch images/fonts), do NOT combine with stealth-mode targets. Typical speedup on image-heavy pages: 3-10x faster load.

### Changed
- **Internal: TTL cache on `cdp_get('/json')`** — a typical CLI command hits the CDP HTTP discovery endpoint 3-7 times during one invocation (session lookup, tab discovery, target validation). Caching for 500ms within one process collapses those to a single fetch. Cache auto-invalidates after tab-mutating operations (`new-tab`, `close-tab`, session window creation) so stale state can never be observed. No behavior change — pure dedup.

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

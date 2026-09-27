# Changelog

All notable changes to cdpilot will be documented in this file.

## [Unreleased]

### Added
- **Idle auto-close.** Since 0.9.2 page commands start the browser, and nothing ever closed it: after an agent's task it kept running (and holding memory) until someone ran `stop`. A browser a page command **auto-launched**, or that the **MCP server** launched (`browser_launch` included — agents are the leak), now closes itself after 15 minutes without a cdpilot command or a visible page change. An **explicit CLI `launch`** stays open by default (a person may browse in it by hand, which no cdpilot command reflects); it gets the same idle close only with **`launch --idle-close <min>`** or **`CDPILOT_IDLE_CLOSE=<minutes>`** (the flag wins). The env var also sets the auto-launch delay (read at launch, fractions allowed), `0` turns it off; an invalid env value falls back to the default with a one-line warning, an invalid flag exits 2. A browser the user started, or one cdpilot only attached to, is never closed. Every command stamps `CDPILOT_HOME/projects/<id>/last-activity` (read-only checks — `status`, `health`, `projects`, `version` — do not, so a `health` watchdog loop cannot pin the browser); MCP tool calls and `serve` requests count too, and so do a CDP client still attached to a page and any change in the page targets' ids/URLs between two watcher rounds (someone navigating, a tab opened or closed; title changes are ignored so a page rewriting its own title cannot pin the browser). The launch starts one detached watcher per port (own session on POSIX, `DETACHED_PROCESS` on Windows) that checks every ≤30 s, stops the browser through the same path as `cdpilot stop`, marks the registry entry stopped, logs to `projects/<id>/idle-close.log` and exits; it also exits when the browser is gone or was replaced (the browser GUID from `/json/version` is the launch marker). `serve --api` sessions keep their server-managed lifecycle.
- `cdpilot status` and `cdpilot health` (`idle_close`, `idle_close_in_s`) show `idle close in <N>m` or `idle close off`; `launch` prints whether idle close is on and how to turn it on.
- **Session log + `cdpilot log`.** After an agent or a person finished a browser task there was no record of what was done and found (`debug` covers one URL, `trace` only `cdpilot test` runs). Every CLI command now appends one JSON line to `<CDPILOT_HOME>/projects/<project-id>/log/<YYYY-MM-DD>.jsonl`: `ts` (local time), `cmd`, redacted `args`, `exit`, `duration_ms`, the page `url`/`title` the command already had (no extra CDP round-trip), a ~200-char redacted `summary` of stdout, the `error` line, and the `files` it wrote (paths it printed that exist and were written during the run). `cdpilot log` prints today's entries as a table; `--md` a Markdown report (pages visited, actions, errors, files produced) to paste into an issue or PR; `--json` the raw lines; `--days N`; `--path`.
- **Redaction before write.** Values given to `fill`, `type`, `smart-fill`, `smart-select`, `assert-value` and `dialog prompt`, values of password/token/key/secret/cookie/auth flags and headers, and token-shaped args become `«redacted:N chars»`; echoes of those values in the output are scrubbed too (also when the command cut them short). `cookies` and `storage` output is never logged. `eval` source is logged with string literals over 40 chars cut and secret-looking literals (`.value = '…'`, `setItem(k, '…')`, `password: '…'`) replaced. URLs keep everything except the userinfo password and query/fragment values whose names contain token, key, secret, password, auth, code or session; `data:` URLs keep only the media type.
- **`CDPILOT_LOG=0`** turns the log off; **`CDPILOT_LOG_DAYS`** (default 14, `0` keeps all) sets retention — day files older than that are deleted on the first write of a day. Logging is best effort: it never changes a command's output or exit code, a failed write costs one stderr line per process, and each line is one `write()` on an `O_APPEND` file so parallel invocations do not interleave. A command stopped by `--timeout` still writes its line (exit 124).
- **MCP `browser_log`** (read-only) returns the log as a table, Markdown or JSON. Each MCP tool call is logged once, by the CLI process that runs it, tagged `"via": "mcp:<tool>"`; the server writes the line itself only when it had to kill that process.
- **iframe targeting for element commands** (#1). Card forms (Stripe/iyzico-style), embedded login widgets and the reCAPTCHA checkbox live in `<iframe>`s that `click`/`fill`/`type` could not reach. Name the frame chain before the selector with `>>>` — `cdpilot click "iframe#card >>> input[name=cardnumber]"`, nested `"iframe.a >>> iframe.b >>> button"` — or pass `--frame <selector|index|url-substring>` (nestable with `>>>`). Covers `click`, `fill`, `type`, `submit`, `hover`, `dblclick`, `rightclick`, `smart-click`, `smart-fill`, `smart-select`. A hop is a CSS selector (or an element wrapping one iframe), an index, a `name`/`id`, or `url=<src substring>`; `--frame` also takes a bare src substring. `>>>` inside quotes or `[...]` stays literal.
- **Cross-origin frames work, including out-of-process iframes.** Each hop is resolved over CDP, never through `contentDocument`: `DOM.describeNode` on the `<iframe>` gives the frame id; a same-process frame runs in its main-world execution context (read from the events `Runtime.enable` replays, disabled again immediately); an out-of-process frame gets a flat session (`Target.attachToTarget` with `flatten: true`) and its messages carry that `sessionId`. `cdp_send` accepts an optional 4th tuple element (session id). Flat sessions live on one socket, so with `CDPILOT_WS_POOL=0` a frame command holds one pooled socket for its own duration; the setting is restored and that socket closed afterwards, also when the command fails or exits (`batch`/`run` keep going after a failed command).
- **Page-coordinate mouse input inside frames.** `hover`, `dblclick`, `rightclick` and `--entropy=on` clicks dispatch `Input.dispatchMouseEvent` on the page; the frame's content-box offset (summed over nested frames, re-measured after page JS runs) is added so the browser hit-tests into the right frame. Keyboard input follows focus into the frame unchanged.
- **Existing `>>>` selectors and texts are unchanged.** The chain is used only when its first hop finds an `<iframe>`/`<frame>` (or an element wrapping one) in the page and no segment is empty. Otherwise the whole string is the plain selector/text it was before, with the same exit codes: `click "Next >>>"`, `click "Home >>> Products"`, `smart-click "Page 1 of 3 >>> Next page"`. If that literal use fails, one stderr line is added: `note: 'Home' matched no iframe; used the selector as written`. `--frame` stays strict: a frame it cannot find exits 1, an empty value exits 2.
- **Automatic frame search for `smart-click` / `smart-fill` / `smart-select`, page first.** Texts and labels are compared with whitespace collapsed (`&nbsp;`, line breaks). An enabled page element whose text or label contains the whole query (exact, prefix or substring) is used without looking in frames. If the page's only such elements are disabled, the old `no enabled element matches` error and exit 1 stand, again without a frame search. Otherwise visible frames are searched breadth-first for a whole-query match (at most 20 frames; 2 s for all the search's CDP calls, each capped at the time left, and a timed-out call keeps the shared socket its frame sessions live on), reported on one stderr line: `smart-click: matched inside frame iframe#card (<src>)`. With no frame match the page's word-overlap match is used as before. A search that runs out of time says so: `smart-click: frame search stopped after 2s (<n> of <m> frames)`.
- **`smart-fill` / `smart-select` search only frames of the page's own origin.** A typed value never lands in a third-party frame (ad, chat, payment widget) by accident; a cross-origin frame is reached with `>>>` or `--frame`. `smart-click` searches all visible frames.
- **`frame eval --frame <f> <js>`** runs inside that frame's own page context (was: always the main page); without `--frame` it behaves as before. `frame list --frame <f>` lists the frames inside a frame and marks hidden ones, in `--frame <index>` order; `frame list` without `--frame` prints exactly what it did before.

### Fixed
- **Windows: non-ASCII output no longer crashes a command run through a pipe.** An agent's shell, the MCP server and `> file` all give Python the ANSI code page (cp1252), so a Turkish page title or an emoji from `eval`, `title` or `a11y` ended in `UnicodeEncodeError`. stdout/stderr are now UTF-8 on Windows unless you set `PYTHONIOENCODING`; the MCP server sets its child to UTF-8 and reads it as UTF-8.

## [0.9.2] - 2026-09-27

Why: in ~1,225 real agent sessions the top failures were "CDP connection error. Is the browser running?" (292), a command hanging with no way to bound it (171, #2) and `open <url>` typed instead of `go <url>` (14).

### Added
- **Auto-launch.** A page command that finds the CDP port unreachable now launches the browser the same way `cdpilot launch` does (same profile, same headless/visible config), waits for `/json/version` (bounded, ~10s), and continues the command once. One stderr line says so: `cdpilot: browser was not running — launched it (CDPILOT_NO_AUTOLAUNCH=1 to disable)`. If the launch fails, the old error is printed followed by `cdpilot: auto-launch failed: <reason>` and the command exits non-zero — no retry loop. Lifecycle, status/diagnostic, launch-config and server commands never launch (`AUTOLAUNCH_SKIP_CMDS`: `launch`, `stop`, `close`, `close-tab`, `session-close`, `project-stop`, `stop-all`, `status`, `health`, `setup`, `help`, `version`, `tabs`, `session`, `sessions`, `projects`, `heal`, `headless`, `proxy`, `browser`, `extensions`, `ext-install`, `ext-remove`, `mcp`, `serve`).
- **`CDPILOT_NO_AUTOLAUNCH=1`** keeps the previous behaviour: the exact "CDP connection error. Is the browser running?" error and exit code 1.
- **Universal `--timeout <seconds>`** (#2), accepted before or after the command name, plus **`CDPILOT_TIMEOUT`** as a default (the flag wins; `0` disables; a malformed value exits 2). It bounds the whole command's wall-clock; on expiry cdpilot prints `cdpilot: timed out after <N>s (<command>)`, kills the child processes it started and exits **124**. Implemented as a watchdog thread + `os._exit` so it works on Windows (no `SIGALRM`), preempts blocking sync calls, and covers direct `python src/cdpilot.py` / MCP / `run` invocations, not only the Node launcher. The value is exported to child processes, so `mcp`/`serve` (not bounded themselves) bound every tool call/request, and `run` bounds every script line.
- **`open <url>`** is an alias of `go <url>`.

### Changed
- `go`, `debug` and `context create` used to call `cdpilot launch` implicitly and print its progress lines ("Launching browser…", "CDP ready!") to **stdout**, mixed into the command's output. They now use the same quiet auto-launch path (one stderr line) and honour `CDPILOT_NO_AUTOLAUNCH`; so does the `watch` daemon's implicit launch.
- `new-tab`, `press-hold`, `profile warm` and the browser-level commands (`download`, `permission`) auto-launch too instead of failing when the browser is down.

### Fixed
- **Headless `stealth`/`undetected` announced themselves as `HeadlessChrome`.** No tier rewrote the headless user agent, which alone failed 3 of 31 sannysoft rows and incolumitas intoli. Both tiers now send `Emulation.setUserAgentOverride` (UA + client-hint metadata taken from the page's real hints) when the browser is headless; `regular` is unchanged. `undetected` also fixes `plugins.item()` index wrapping (incolumitas overflowTest) and a Worker wrapper that broke relative worker URLs. Headless after: sannysoft 31/31 and intoli 6/6 in both tiers. Limit: the override lives on the `go` connection; a later separate command in the same page can read `HeadlessChrome` again.
- **`cdpilot stop` could hang forever, and on Windows it closed the user's own browser.** On macOS/Linux it called `lsof` with no timeout; on a machine with a stale network mount `lsof` never returns. On Windows it ran `taskkill /F /IM` on brave.exe/chrome.exe/chromium.exe, which killed every Brave/Chrome window, not just cdpilot's. `stop` (and the local API's session release) now send CDP `Browser.close`, and fall back only to processes whose command line has `--remote-debugging-port=<port>` exactly (`pgrep` on POSIX, a CIM query + `taskkill /PID` on Windows). `lsof`/`pkill` are no longer used; every probe has a timeout.
- `cdpilot launch` with a browser binary that cannot be started printed a Python traceback; on Windows the error did not even name the binary. It now prints `Cannot start browser '<path>': <reason>` and exits 1 (Windows CI caught the unnamed binary in the auto-launch failure line).
- `bin/cdpilot.js` exited **0** when the Python core was killed by a signal (OOM, SIGKILL): `process.exit(code || 0)` turned `code === null` into success. It now prints the signal and exits with 128 + signal number (137 for SIGKILL).

### Corrected
- README listed bot-detection panel results from April 2026 (v0.4.x): sannysoft 24/24, incolumitas intoli 6/6, nowsecure.nl passed, areyouheadless "not headless". Re-measured 2026-09-27 on v0.9.1, headless, all three `mode` tiers: sannysoft 27/31 with 3 fails, all caused by the `HeadlessChrome` user agent that no tier rewrites; intoli 5/6; nowsecure.nl and areyouheadless could not be measured (fixed Turnstile test key / HTTP 502). README now shows the measured numbers.
- The 0.9.1 entry says the `lsof`/`pkill` calls used when stopping a browser time out after 5s. That was true only for the local API's session release; `cdpilot stop` itself still called `lsof` with no timeout.

## [0.9.1] - 2026-09-27

### Added
- Official MCP Registry metadata: root `server.json` (schema `2025-12-11`), `mcpName` field in `package.json`, and an MCP Registry publish step in `.github/workflows/publish.yml` (`mcp-publisher` v1.8.1, GitHub OIDC), running after the existing npm publish step.
- README now documents `cdpilot test` (runs `*.cdpt.js` files) and `cdpilot trace open` (time-travel trace viewer) — both have existed in the dispatch table for a while but were never mentioned in README or `--help`.

### Fixed
- **Port registry never forgot a project.** `~/.cdpilot/registry.json` only marked dead entries "stopped" and never removed them, so on a long-lived machine they filled the whole 9222–9322 range and every new project failed with "No free port". Dead entries (port free *and* recorded pid gone) are now pruned before each allocation; a port that is still bound is never pruned. The registry is written atomically, and `CDPILOT_HOME` can point it elsewhere.
- **Windows: a process-liveness probe could kill the process.** On Windows, Python turns `os.kill(pid, 0)` into `TerminateProcess`. Liveness checks (registry cleanup, `watch`) now ask the kernel via `OpenProcess`/`GetExitCodeProcess` instead of signalling.
- **Windows: the free-port probe called every port free.** It bound with `SO_REUSEADDR`, which on Windows lets a socket bind on top of a live listener, so port allocation could hand out a port another project's browser was using, and registry cleanup would prune that project. The probe now uses `SO_EXCLUSIVEADDRUSE` on Windows; POSIX behaviour is unchanged. Caught by the new registry test on `windows-latest` CI.
- `lsof`/`pkill` calls used when stopping a browser now time out after 5s instead of blocking the caller indefinitely.

### Corrected
- v0.9.0 announced a **"Multi-instance pool" (`CDPILOT_POOL_SIZE`)** feature under "Added" below — it was never implemented; no code path reads that env var. It has been removed from README (usage example, env-var table, feature checklist) and moved to the roadmap as planned/not shipped. The v0.9.0 entry itself is left unedited for historical accuracy — this note is the correction.
- README/CLAUDE.md/`.claude/docs/architecture.md` described `src/cdpilot.py` as "~2500–2600 lines" and README's Comparison table said "install size ~50KB". Measured today: 13,129 lines / ~542KB (`src/cdpilot.py`) + ~23KB (`bin/cdpilot.js`). Wording was replaced with non-decaying descriptions instead of a number that will drift again as the file grows.
- README said `a11y-snapshot` uses **"500x fewer tokens than screenshots"**. No measurement behind it was found. Measured 2026-09-27 on four real pages (Hacker News, Wikipedia, GitHub, saucedemo; `o200k_base` for text, Anthropic's 28px-patch formula for a 756×419 screenshot): a11y-snapshot is 1.4–42× smaller than the page's raw HTML, but a small screenshot is cheaper on three of the four pages (a11y wins ~7× only on the form page). README now says that.
- `bin/cdpilot.js`'s "Python not found" error said "Python 3.8+ required"; the actual requirement (PEP 604 union types) has been 3.10+ since v0.9.0. Message text corrected, no behavior change.
- `glama.json` said "40+ commands" (README/package.json already correctly say 70+) and "python >= 3.8"; both corrected.
- `.claude/docs/innovation-roadmap.md` marked "Test runner" and "Cloud-API uyumlu lokal" (`cdpilot test`/`trace`, `serve --api`) as 🔴 missing — both are implemented and dispatched, just undocumented. Status flipped, evidence cited.

### Changed
- `package.json` version → 0.9.1; removed the `multi-instance` npm keyword (it implied a shipped feature that isn't).

## [0.9.0] - 2026-08-23

### Changed
- **Python 3.10+ is now required** (the core uses PEP 604 union types). `findPython` now tries version-specific interpreters (`python3.13`…`python3.10`) and Homebrew paths before generic `python3`; the CI matrix was updated to match.

### Added
- **`cdpilot setup` detects the Python `websockets` module** and fails early with an install hint — thanks @lross2k (#12, #13). The check imports `websockets` via the same interpreter cdpilot selects, so a pip/interpreter mismatch can't fool it.
- **`cdpilot watch`** — video understanding via continuous screencast. `Page.startScreencast` streams JPEG frames into a ring buffer so an AI agent can query a time window and observe motion (animation, mouse cursor, scroll, transitions) that a single screenshot cannot capture.
  - `watch start <url|file://...>` — begin screencast and play the video
  - `watch query --at <mm:ss> --window <Ns>` — frames around a timestamp
  - `watch ask "<question>"` — ask about recently captured frames
  - `watch status` / `watch stop`
  - Works on local files (`file://`) and online video (YouTube, Vimeo, Twitter, Facebook, Instagram)
  - Zero dependency; Pillow is optional and only used for motion-detection between frames
  - Exposed to AI agents as `browser_watch_*` MCP tools
- **`--disable-blink-features=AutomationControlled`** launch flag — closes the Blink runtime flag that Cloudflare and DataDome probe to detect an automated browser.
- **`cdpilot friction`** — progressive anti-bot resilience probe. Real sites stack defenses incrementally; `friction` reports the highest active rung and the recommended response policy as JSON. Six levels (low→high): `none`, `rate_limited`, `soft_captcha`, `login_wall`, `otp_sms`, `hard_block`. Bilingual (English + Turkish) DOM heuristics. **Read-only — never bypasses anything.** Policy: `rate_limited` → automatic exponential backoff + retry (in `cmd_go`); `soft_captcha` → defer to captcha tools; `login_wall` / `otp_sms` / `hard_block` → flagged for HUMAN handoff, never autonomously solved (deliberate ethics boundary). MCP: `browser_friction`.
- **`cdpilot mode [regular|stealth|undetected]`** — three-tier stealth mode, a single switch over how much fingerprint surface is patched. `regular` (default) injects nothing — cleanest and fastest; `stealth` injects a light patch (webdriver / chrome.runtime / permissions, deliberately omitting plugin spoofing which leaks); `undetected` injects the full patch (+ plugin array + WebGL + Worker). Default is `regular` because Stealth Bench V1 found the full patch set *alone* lowered scores. The adaptive layer learns the right tier per host and escalates on CAPTCHA. Effect applies on the next navigation; env override `CDPILOT_MODE`. Legacy `stealth on/off` stays coherent with the tier. MCP: `browser_mode`.
- **`cdpilot press-hold [<selector>]`** — PerimeterX/HUMAN "Press & Hold" behavioral challenge solver. It is not token-based, so there is no provider to call; the only solution is a real press → hold → release gesture, emitted via CDP Input events: a Gaussian-randomized ~3–7s hold with ±1–2px micro-jitter while held. Auto-locates the `#px-captcha` widget or takes an explicit selector. `captcha-solve` auto-routes here when it detects a `perimeterx` challenge. MCP: `browser_press_hold`.
- **`cdpilot captcha-solve [--provider amazon-local|capsolver|2captcha]`** — image-based CAPTCHA solver, complementing the token solvers. Amazon classic image CAPTCHA ("Type the characters you see" rate-limit page) is OCR'd offline via the **optional** `amazoncaptcha` library (pure-Python + Pillow, MIT) — not installed = clean report, no hard dependency. BYOK providers `capsolver` / `2captcha` use image-to-text APIs via `CAPSOLVER_API_KEY` / `TWOCAPTCHA_API_KEY`. Auto-detects and routes (including to `press-hold` for PerimeterX). MCP: `browser_captcha_solve`.
- **`cdpilot profile warm`** — ages the browser profile by browsing low-risk sites to build cookie/history age, which nudges reCAPTCHA v3's behavioral score upward over time. Slow by design — run ahead of a session, not inline.
- **Multi-instance pool** (`CDPILOT_POOL_SIZE=N`) — launches N independent browser processes and dispatches work to the least-loaded one, for `N × per-instance` parallelism. Default `1` (single instance, no change for existing users).
- **Off-screen mode** (`CDPILOT_OFFSCREEN=1`) — keeps the browser headed (real rendering, no headless fingerprint) but positions the window where it can't steal focus. For automating on a workstation in active use.
- **Docker + Xvfb harness** (`cdpilot-bench/docker/`) — headed-in-Xvfb so bench/automation runs never pop a window on the host display; CI-ready. Software rendering (no GPU) lowers anti-bot scores versus native — an isolated reproducibility environment, not the headline configuration.

### Changed
- **smart-click / smart-fill / smart-select** hardening:
  - Disabled-element guard — no longer reports a successful "click" on a disabled button (real bug fix).
  - Shadow DOM traversal — finds elements inside Lightning, Polymer, and lit-element web components.
  - Locale-aware text matching — correct case folding for Turkish (İ/i) and German (ß).
  - `smart-fill` floating-label support — resolves Material / Ant / Chakra labels via `aria-labelledby` and `closest` label lookup.

### Bench (in progress)
- Native (Apple M1, GPU): **45 / 80 (≈56%)** at $0.00 (driven by free Gemini). This is a **single run** and verification was interrupted — treat as provisional, not a confirmed rate. Journey across sprints: 12 → 19 → 35 → 45 (Sprint 2 adapter fix +20, Sprint 3 captcha + regular-as-default +10).
- Docker (Xvfb, software render): 30 / 80 — a separate, GPU-less isolated CI environment, not comparable to the native run and not a headline number.
- For context (not apples-to-apples): commercial hosted services score higher (browserbase 73, anchor 65) but run premium LLM controllers at roughly $150–300/mo; cdpilot's bench runs at $0.

### Known limitation
- `watch` cannot capture DRM-protected players (Netflix and similar) — they render as black frames at the CDP layer.

## [0.8.0] - 2026-05-20

### Bench
- **Full variant: 29 / 80 (36.25%)** — v0.6.0 cookies-auto regression confirmed fixed (was 15/80 = 18.75%). vs v0.5.3 baseline (30/80, 37.5%): -1 task net, well within run-to-run noise.
- Category lifts: Datadome 7/13 (was 5), Akamai 2/6 (was 1), GeeTest 1/4 (was 0), Shape 1/1 (was 0), reCaptcha 3/6 (was 2)
- Category drops: Cloudflare 10/22 (was 12), Custom Antibot 3/5 (was 5), hCaptcha 1/3 (was 2)
- v0.6.2 `wipe` produced no measurable lift in single run — cross-task contamination was either smaller than estimated or `wipe` does not capture the failure mode. Will revisit with multi-run statistics.
- v0.7.0 / v0.8.0 are no-ops without user-installed residential proxy or TLS-corrected browser (as documented). Score above is BoringSSL-default, datacenter-IP.

### Added
- **`cdpilot tls-check`** — probes the running browser's TLS / HTTP-2 fingerprint via a public echo service (`tls.peet.ws` default, `browserleaks` alternate). Extracts JA3, JA3 hash, JA4, and Akamai HTTP-2 fingerprint, then verdicts the result against a small `KNOWN_CHROME_TLS` set. Useful before/after switching browsers to confirm what anti-bot services actually see at the TLS layer (the layer Akamai/Kasada inspect before JS stealth even runs).
### Known limitation (corrected 2026-05-20)
- The initial v0.8.0 plan referenced `cdpilot browser camoufox` and `cdpilot browser undetected-chrome` as TLS-correction integrations. **This was incorrect.** Camoufox is Firefox+Juggler (no CDP); Patchright / undetected-chromedriver / nodriver are Python/Playwright libraries, not standalone browsers with `--remote-debugging-port`. cdpilot's CDP-only architecture is incompatible with all of them without a protocol adapter. Those `BROWSER_BINARIES` entries have been removed; the related CLI helpers stayed only as documentation pointing at the v0.9 roadmap.

### Why
- Stealth Bench v0.5.0–v0.7.0 plateau at ~37–40% had a TLS-layer ceiling: BoringSSL inside Brave/Chromium produces a fixed JA3/JA4. Anti-bot services that gate on TLS (Akamai, Kasada, deeper Cloudflare modes) will block the connection before any JS stealth gets a chance to load.
- Patching BoringSSL in a Chromium fork is a 2–3 week sprint with rebuild and distribution overhead. Out of scope for v0.8.0.
- v0.8.0 ships the **awareness + integration** layer instead: cdpilot can measure the current TLS surface, and users who need TLS correction can install a TLS-modified browser (Camoufox or undetected-chrome) and select it via `cdpilot browser`. Zero new dependencies on our side, no rebuild burden.

### Roadmap
- v0.9: evaluate shipping a thin `cdpilot tls-proxy` (local TLS-terminating MITM) using `curl-impersonate` semantics, behind an explicit opt-in (`cdpilot stealth tls-proxy on`). Maintains zero-dep core; proxy ships as optional plugin.

## [0.7.0] - 2026-05-20

### Added
- **Named proxy pools** — provider-agnostic residential/datacenter proxy management. cdpilot is now a thin wrapper around Chromium's `--proxy-server` with multi-pool config, credential redaction, and per-pool metadata.
  - `cdpilot proxy add <name> <url> [--geo X] [--sticky]` — register a pool (auth in URL: `http://USER:PASS@host:port`)
  - `cdpilot proxy remove <name>` / `cdpilot proxy use <name>|none` / `cdpilot proxy list` / `cdpilot proxy show [<name>]`
  - Legacy single-URL form (`cdpilot proxy http://...`) still works and is preserved as a fallback when no pool is active
  - All proxy display redacts credentials (`***:***@host:port`)
- Resolution order: `CHROME_PROXY` env > active pool > legacy single URL
- Tested with BrightData, IPRoyal, and Anchor URL formats (sticky session and rotating endpoints)

### Why
- v0.5–v0.6 stealth work plateaued at ~40% on the bench. Commercial providers (browserbase/anchor/onkernel at 46–73%) are partly winning on **IP reputation**, not stealth — datacenter IPs that cdpilot launches from are flagged by Akamai/PerimeterX before stealth even matters.
- Shipping the framework first (free, zero-dep on our side) lets users plug in any residential provider without waiting for cdpilot-specific integrations.

### Notes
- Browser restart required after any change (Chromium reads `--proxy-server` at launch).
- Per-host proxy routing is **not** in v0.7.0 — Chromium's process-wide proxy plus browser-use's target-tracking constraints make per-host switching fragile. Planned for v0.7.x via CDP `Fetch.continueRequest` rewriting, off by default.

## [0.6.2] - 2026-05-20

### Added
- **`cdpilot wipe`** — per-task state hygiene command. Clears cookies and origin storage for non-safe-listed hosts. Designed for parallel/agent workloads that share one browser across many tasks.
  - `--all` — wipe everything including safe-list hosts
  - `--keep host1,host2` — explicit per-call keep-list (overrides safe-list)
  - `--cookies` / `--storage` / `--tabs` — scope to one channel
  - Default: cookies + localStorage + sessionStorage + indexeddb + cache for non-safe hosts
- Bench adapter (`cdpilot-bench/browsers/cdpilot.py`) now calls `cdpilot wipe --cookies --storage` between tasks via `disconnect()`. Disabled with `CDPILOT_NO_WIPE=1`.

### Why
- v0.5.0 full variant exhibited cross-task contamination: 11 tasks landed on the wrong domain (e.g. anthropologie.com task got a fiverr.com captcha) because cookies from prior tasks bled into later ones in the shared browser.
- v0.5.1 attempted to fix this with `Target.createBrowserContext` per task, but browser-use's target tracker couldn't see the new context → "Target not found" / "Session corrupted". That fix is opt-in via `CDPILOT_ADAPTIVE_FRESH_CONTEXT=1` only.
- v0.6.2's approach: don't change target topology, just scrub state between tasks. browser-use sees the same shared browser, but each task starts with a clean cookie jar (except hosts the user explicitly opted-in via `cookies auto add`).

## [0.6.1] - 2026-05-20

### Fixed
- `cookies auto` is now gated by an opt-in per-host **safe-list** (default empty). Enabling the global toggle alone is now a **no-op** until hosts are explicitly added via `cookies auto add <host>`. This fixes the v0.6.0 bench regression (15/80 vs ~30/80 baseline) caused by indiscriminate cookie save/load across all visited hosts in parallel workloads.

### Added
- `cookies auto add <host>` — opt-in a host for automatic clearance cookie save/replay (suffix match: adding `cloudflare.com` covers `*.cloudflare.com`).
- `cookies auto remove <host>` — remove a host from the safe-list.
- `cookies auto list` — display enable flag + current safe-list.
- `_cookies_auto_should_apply(host)` — internal gate consulted by the navigate hooks.

### Changed
- Pre/post-navigate cookie hooks (`_cookies_auto_enabled() && expected_host` → `_cookies_auto_should_apply(expected_host)`).
- `cookies` command no longer requires browser for `auto add/remove/list/on/off/status` sub-commands.
- `_cookies_auto_enabled()` now reads via `_cookies_auto_config()` (preserves `safe_hosts` on toggle).

### Why
- v0.6.0 dropped to 15/80 with `cookies auto on` because browser-use runs 5 parallel tasks against different hosts, and the auto-replay was injecting stale cookies from prior tasks into unrelated targets. Cookies are valuable for known anti-bot walls (CF, DataDome) but harmful when applied indiscriminately across a bench workload.

## [0.5.3] - 2026-05-20

### Changed
- `CAPTCHA_ENTROPY_REQUIRED` scope narrowed based on v0.5.2 bench data: entropy auto-enable now only on PerimeterX, hCaptcha, reCaptcha, Arkose, GeeTest, Temu Slider. Datadome/Akamai/Cloudflare/Custom Antibot/Kasada/Shape get OFF (entropy added latency without bypass benefit on those detectors).

### Bench
- v0.5.3 full: 30/80 (37.5%) — matches v0.5.0 baseline
- Adaptive layer is now neutral vs baseline; stealth-only (v0.5.0: 32/80 = 40%) remains the best-performing variant
- Recommended: use `cdpilot stealth on` standalone unless captcha-heavy site requires adaptive escalation

### Internal
- Removed `datadome`, `custom_antibot` from entropy_required dict
- Added `kasada`, `shape` with False (explicit, TLS-based)

## [0.5.2] - 2026-05-19

### Added
- Adaptive layer now auto-enables behavioral entropy per-host when CAPTCHA categories sensitive to mouse/keyboard patterns are detected (PerimeterX, DataDome, hCaptcha, reCaptcha, Arkose, GeeTest).

### Changed
- Per-command `--entropy=on` flag still works as override. Global `cdpilot entropy on` unchanged.
- Akamai and Cloudflare are explicitly excluded from entropy auto-activation (JS challenge-based; mouse entropy provides no bypass benefit there).

### Bench impact
- Stealth Bench V1 (80 tasks): pending v0.5.2 rerun.
- PerimeterX: 2/18 (v0.5.1) → expected 6+/18 (v0.5.2).
- DataDome: 5/13 → expected 7+/13.

### Internal
- `_adaptive_state[host].entropy_required` flag added.
- `_entropy_enabled(project_id, host=None)` honors host-gated override.

## [0.5.1] - 2026-05-19

### Fixed
- **Adaptive regression**: per-task wrong-site landings (11/80 in v0.5.0 full) due to context reuse + cookie replay timing. Now idempotent (skip re-nav if already on origin) + host-assert after every navigate.
- `posixpath.join() argument must be str... None` TypeError on `cdpilot type/click` when `CDP_PORT` + `CDPILOT_PROFILE` env both set.
- Twitter wrapper `_tw_type` rewritten to use `document.execCommand('insertText')` for Draft.js compatibility (was broken on contenteditable).

### Added
- `CDPILOT_ADAPTIVE_FRESH_CONTEXT=1` opt-in env: per-task `Target.createBrowserContext`. Default OFF (incompatible with browser-use's target_id model).
- `NavigationDrift` exception (raise mode via `CDPILOT_ADAPTIVE_STRICT=1`).

### Bench
- v0.5.0 full: 26/80 (32.5%) — regression from baseline (37.5%).
- v0.5.1 full: 29/80 (36.25%) — regression closed.
- Category breakdown (v0.5.1): Cloudflare 12/22, reCaptcha 2/6, PerimeterX 2/18, DataDome 5/13, GeeTest 1/4, Akamai 4/6, Kasada 1/1, Custom Antibot 2/5. hCaptcha 0/3, Shape 0/1, Temu Slider 0/1.

## [0.5.0] - 2026-05-17

> "Run fast in the open lane, climb walls when you see them, then keep running."
> A release organised around three themes: **quiet professional output**,
> **wall-aware navigation**, and **true parallelism**.

### Added
- **`cdpilot dismiss [N|aggressive]`** — heuristic auto-click for "Stay signed out / No thanks / Continue without account" buttons. Designed for unauthenticated queries against LLM chat sites (ChatGPT, Perplexity, Claude.ai, Gemini) that gate access behind a sign-up modal but offer an escape hatch. Built-in pattern library covers English + Turkish dismissive phrases with weighted scoring (exact-match bonus). **Safety guards** are load-bearing: an explicit negative-pattern list ("delete account", "sign out", "subscribe", Turkish equivalents) disqualifies dangerous lookalikes — one negative hit on any of the element's text/aria/title/value attributes and it's out, regardless of how many positive patterns also match. Visibility gate (0-size, display:none, visibility:hidden, opacity<0.1) and a minimum score threshold of 40 prevent weak-match misfires. Pass an integer N (1-10) or `aggressive` (up to 5) to handle chained modals — common on cookie-banner-then-signup pages. MCP: `browser_dismiss`.
- **`cdpilot adaptive [on|off|status|clear|forget <host>]`** — auto-escalate to stealth mode for hosts that show a CAPTCHA. Persists a per-host memory in `~/.cdpilot/profile/adaptive.json`. Flow: `cmd_go` checks the URL hostname against the learned list and enables `CDPILOT_STEALTH=1` for that one navigation if matched. After every navigation, `_detect_captcha` runs (already part of cmd_go); when CAPTCHA is detected AND adaptive is on, the host is added to the list AND if stealth was off this round, the navigation is retried ONCE with stealth enabled. Never auto-demotes — once a host is in the list it stays until you run `adaptive forget <host>` or `adaptive clear`. This conservative rule prevents flapping when CAPTCHA detection has a false negative. Matches the "run fast, climb walls when seen" philosophy: the default fast lane stays fast, but cdpilot learns where the walls are.
- **`cdpilot cookies save <file> [<domain>]` / `cdpilot cookies load <file>`** — export/import cookies as JSON. Designed for replaying CF/DataDome clearance cookies across cdpilot runs: beat the wall once, capture, replay in a separate process or after a `cdpilot stop` cycle. Save accepts an optional domain filter (subdomain-aware via endswith). Load round-trips via `Network.setCookies` and verifies the accepted count by re-fetching — anything CDP rejected (expiry, malformed domain) is reported.
- **`cdpilot context [create|list|close]` + `CDPILOT_TARGET` env pin** — browser context pool for true parallelism inside a single browser. Each context is an isolated cookie/storage namespace (Playwright's parallel-tabs model). Create N contexts, run actions against them concurrently from separate CLI invocations by setting `CDPILOT_TARGET=<target_id>` on each. The env pin bypasses cdpilot's CWD-keyed session resolution entirely — necessary for parallel workflows where two concurrent processes would otherwise race on the same `sessions.json` entry. Missing pin = fail loud (no silent fallback to a different tab — would be a heisenbug). `context create` rolls back the empty context if `createTarget` fails afterwards, so orphan-context leaks can't happen. `context close` refuses to destroy the default context. Use case: run 50 Perplexity queries in parallel without each query stomping on the previous one's chat history; A/B test logged-in vs logged-out flows without spinning up multiple browsers.

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

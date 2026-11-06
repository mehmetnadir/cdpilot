import json, pathlib
W = "/Users/nadir/01dev/_worktrees/cdpilot-"
RULES = """
RULES (apply to everything you do)
- MACHINE: arm64 Mac. Python runs as /usr/bin/python3 and must stay 3.9-compatible (no `match`, no runtime `X | Y` unions). Node 18+.
- Zero dependencies: Python stdlib only, no npm packages. Single-file architecture: all Python lives in src/cdpilot.py (20k lines; read the parts you need with sed/grep, not the whole file). Tests live in test/test.js: node:assert, `test('name', () => {...})`; copy the pattern of a nearby test. Pure Python helpers are tested through `pyFuncs([...])` + `pyCases(src, cases)`; CLI behaviour through `spawnSync(process.execPath, [CLI, ...])` with an isolated env (CDPILOT_HOME, CDPILOT_PROFILE, CDPILOT_LOG=0, CDPILOT_NO_AUTOLAUNCH=1) like the other tests. Real-browser tests are gated by CDPILOT_E2E=1 like the existing e2e tests.
- Do not touch: xbot/, examples/, bin/, .claude/, package.json, any existing test or behaviour (adding is fine, removing is not).
- Docs are part of the job: CHANGELOG.md `[Unreleased]` -> `### Added` bullet (bold lead sentence naming the command, then the behaviour, 3-8 lines, measured wording only) and the README.md section where the command belongs, plus the CLI help text.
- Run only your NEW tests in the foreground while developing. The whole suite takes ~4 minutes: run it ONCE at the end: `node test/test.js > .lane-test.out 2>&1` (from the repo root). Report the last summary line (`N passed, M failed`) and the names of failed tests. The pre-existing failure `bot-auth: idle close counts CDP clients...` is known and not yours.
- No `--no-sandbox`, no silent `except: pass`, no `catch {}`, no deleting tests.
- Commit nothing. FINAL REPORT (your last message): files changed with line ranges; each new test and what it proves; the test summary line; what you could not do and why.
"""
isler = {}
isler["shadow"] = """TASK: GitHub issue #3 "Add Shadow DOM support" for cdpilot (zero-dependency browser automation CLI, pure CDP). Elements inside open shadow roots are not reachable by the CSS-selector commands (click, fill, type, hover, get-text, attr, exists, wait-for, select, screenshot --selector and every other command that resolves a CSS selector through querySelector).

DESIGN (decided; implement exactly this)
1. `>>>` already means "step into an iframe" (v0.9.3). Code: `_split_frame_chain`, `_frame_selector_hops`, `_frame_selector_plan`, `_frame_hop_is_selector`, `_frame_chain_candidate`, `_parse_frame_hop` (src/cdpilot.py ~3900-3995) and the probe that computes `first_hop_is_frame` before an element command runs. Extend the meaning: when a `>>>` hop matches an element that is NOT an iframe but HAS an open `shadowRoot`, the next segment is resolved inside that shadow root (`host.shadowRoot.querySelector(next)`). Chains mix freely: `iframe#pay >>> my-card >>> button.inner`, `my-app >>> my-panel >>> input`. A hop that is neither an iframe nor a shadow host keeps today's literal fallback; reword its stderr note to: "note: 'X' matched no iframe or shadow host; used the selector as written" (update the existing test expectation for that note text). A closed shadow root is unreachable by design: fail with "'X' has a closed shadow root; cdpilot cannot reach inside it".
2. Automatic deep fallback: when a plain CSS selector (no `>>>`) matches nothing at document level, retry with a shadow-piercing search (same walk as `deepQuerySelectorAll` in the smart-click JS at ~13698: every open shadow root, depth-first, document order). If it finds something, use the first match and print ONE stderr note: "note: '<sel>' found inside the shadow root of <host tag#id>". Zero matches -> today's error unchanged. Applies to element commands and to `wait-for`/`exists` polling. It must NOT apply to `>>>` hops (those are explicit).
3. One shared JS helper string (e.g. `_SHADOW_QUERY_JS`) used by every resolver you touch: no copy-pasted walkers. Keep the pure Python side (hop classification, note wording) in small pure functions next to `_frame_selector_plan` so `pyFuncs` can test them.

STEPS
0. Inventory first: list every place that resolves a CSS selector into a DOM node or box (querySelector inside Python-built JS strings, `DOM.querySelector`, the frame-chain resolver). Put the list in your report. Pick the shared choke point(s). If more than 3 distinct resolvers exist, change the shared ones and list the rest under "not covered" instead of patching twenty places.
1. Implement design 1-3.
2. Tests in test/test.js next to the `frames:` tests (~3715): (a) pure hop-classification cases through pyFuncs/pyCases; (b) a page fixture with an open shadow host, a nested host, a host inside an iframe and a closed root (the suite already spawns small node http servers and has `test/frames_fake_cdp.py`; reuse whichever fits), gated by CDPILOT_E2E=1 when a real browser is needed: `click "my-card >>> button"` clicks the inner button; plain `click ".inner"` finds it and prints the note; the closed root gives the closed error; an existing iframe chain still works. The pure parts must be covered without a browser.
3. Docs: README section where `>>>`/iframes are explained (add shadow DOM, 5-10 lines with the two examples), CHANGELOG [Unreleased], help text where `>>>` is described (~16201 and the main help).
ACCEPTANCE: new tests green; full-suite summary with no new failures; report lists resolvers covered and not covered.
""" + RULES

isler["flow"] = """TASK: GitHub issue #5 "Add session recording & replay" for cdpilot (zero-dependency browser automation CLI). Target CLI (exactly):
  cdpilot record start [--name <n>]        cdpilot record status        cdpilot record cancel
  cdpilot go https://example.com ; cdpilot click "#login" ; cdpilot fill "#email" test@test.com
  cdpilot record stop [--save login-flow.json]   (no --save: print the flow JSON to stdout)
  cdpilot replay login-flow.json [--var k=v ...] [--delay real|none|<ms>] [--dry-run] [--continue]

DESIGN (decided; implement exactly this)
- State: `$CDPILOT_HOME/record/active.json` = {"name","started_at","steps":[...]}; one recording per CDPILOT_HOME. `record start` while active -> exit 1 naming the active recording.
- Hook: every CLI command that ran while a recording is active is appended as a step AFTER it ran: {"cmd","args":[...],"t_ms": ms since start,"exit": code}. Hook it at the single dispatcher point where the session log records a command (the `_slog_*` writer and `_slog_record_external` ~19756; the session log section starts ~19068 and lists which commands it skips in SLOG_SKIP_CMDS/SLOG_CMD_ALIASES: reuse those tables). Never recorded: record, replay, log, help, version, status, health, mcp, serve, bot-auth. Steps whose exit != 0 are dropped at `record stop` (report "dropped N failed steps").
- Secrets: a value becomes a placeholder `{{name}}` listed under "vars" iff (a) the command is fill/type/smart-fill/select-like and the selector/label is secret-shaped by the session log's `_SLOG_SECRET_NAME_RE` (e.g. `#password`, `input[type=password]`, "API key"), or (b) the value itself matches the session log's secret patterns (`_SLOG_TOKEN_PREFIX_RE`, `_SLOG_BEARER_RE`, secret URL params via `_slog_mask_url`). Reuse those regexes; write no new heuristics. Other typed values (an email in `#email`, a search term) are kept verbatim: the user asked for a recording. Placeholder names: the selector's id/name/label slug (`password`, `api_key`), else `v<n>`; "vars": {"password": {"step": 3, "hint": "fill #password"}}.
- Flow file: {"cdpilot_flow": 1, "name", "recorded_at" (ISO UTC), "cdpilot_version", "steps": [{"cmd","args","t_ms"}], "vars": {...}}.
- Replay: validate the file (exit 2 with a reason on bad shape or unknown version); collect `--var k=v` and env `CDPILOT_VAR_<NAME>`; a missing var -> exit 2 listing the missing names before running anything. Run each step as a child process of this same CLI (`sys.executable`, the script path, cmd, args) with the current env (the MCP server already runs tool calls as child CLI processes: reuse that helper if one exists). `--delay real` (default) sleeps the recorded gap, capped at 10 s; `none` = no sleep; `<ms>` = fixed gap. One line per step: `[3/7] fill #email ... ok 0.8s`. First failing step: print its stderr, exit 1 (unless `--continue`, then keep going and exit 1 at the end if any failed). `--dry-run` prints the steps with substitutions (placeholders shown as `{{name}}`, never the value) and exits 0.
- Help: add `record` and `replay` to the main help, the dispatch table (~20255) and `__doc__`.

TESTS (test/test.js): CLI-level with spawnSync and an isolated CDPILOT_HOME; use browser-free commands for the recorded steps (config-type commands such as `block add <pattern>`, `entropy on|off`: check which commands run without a browser and pick two). Prove: start/status/stop/cancel; a second start is refused; failed steps are dropped; `--save` writes the file shape above; placeholders: `fill "#password" hunter2` -> `{{password}}` + vars entry, `fill "#email" a@b.c` kept verbatim (pure test via pyFuncs of the placeholder function, no browser); replay `--dry-run` prints substitutions and never prints a secret value; replay with a missing var exits 2 before any step; replay runs the browser-free steps and reports per-step status; `--delay none` runs without sleeping. One real round trip (go -> fill -> record stop -> replay) gated by CDPILOT_E2E=1 against a local node http server, like the other e2e tests.
DOCS: README section "Record & replay" (8-15 lines with the exact commands above and the secrets rule), CHANGELOG [Unreleased].
""" + RULES

isler["har"] = """TASK: GitHub issue #4 "Add HAR export for network monitoring": `cdpilot network <url> --har <file>` exports the requests of that navigation as HAR 1.2 JSON (`--har -` = stdout).
Code today: `cmd_network` (src/cdpilot.py ~8149) prints the list collected by `navigate_collect(ws_url, url, network=True, ...)` (~5227), which keeps only {url[:150], status, type, mime} from `Network.responseReceived`.

DESIGN (decided; implement exactly this)
- With `--har`, navigate_collect keeps a richer record per requestId: `Network.requestWillBeSent` (untruncated url, method, headers, has postData + its length, wallTime/timestamp, initiator.type, type), `Network.responseReceived` (status, statusText, headers, mimeType, timing, remoteIPAddress, remotePort, protocol, fromDiskCache, fromServiceWorker), `Network.loadingFinished` (encodedDataLength, timestamp), `Network.loadingFailed` (errorText, canceled), plus `Page.domContentEventFired` / `Page.loadEventFired` timestamps. Without `--har` the existing output stays byte-for-byte unchanged (existing tests prove it).
- Response bodies are NOT fetched; comment why (size + one extra round-trip per request). `content.size` = encodedDataLength, `content.mimeType` set, no `content.text`.
- A pure builder `_har_from_events(events, page, creator_version)` returns the HAR dict: log.version "1.2", creator {name:"cdpilot", version}, pages[0] {startedDateTime, id:"page_1", title, pageTimings {onContentLoad, onLoad} (ms from page start; -1 when the event was not seen)}, entries[] sorted by start: startedDateTime (ISO 8601 with ms, UTC, from wallTime), time (ms, loadingFinished - requestWillBeSent, -1 if unfinished), request {method,url,httpVersion,headers[{name,value}],queryString[{name,value}] parsed from the url,cookies:[],headersSize:-1,bodySize (postData length or 0)}, response {status,statusText,httpVersion (from protocol: h2 -> "HTTP/2", http/1.1 -> "HTTP/1.1", h3 -> "HTTP/3"),headers[],cookies:[],content{size,mimeType},redirectURL (Location header or ""),headersSize:-1,bodySize}, cache {}, timings {blocked:-1, dns, connect, ssl, send, wait, receive} derived from CDP `timing` (dnsEnd-dnsStart etc.; -1 when the pair is missing or -1), serverIPAddress, _resourceType, _fromCache ("disk"|"serviceworker"|absent), _error (errorText when failed). Header VALUES whose name matches the session log's secret-name rule (`_SLOG_SECRET_NAME_RE`: cookie, set-cookie, authorization, x-api-key, ...) are replaced by "«masked»" (document this; no flag to disable).
- Write the file atomically (tmp + os.replace). `--har` without a value -> usage line, exit 2. Print one stderr line: "har: N entries -> <file>".

TESTS (test/test.js): pure builder through pyFuncs with a hand-written event fixture derived from the CDP spec: a document (h2, 200), an XHR that failed (loadingFailed), a cached image (fromDiskCache) and a 302 with Location; assert the key set above, timings arithmetic, the -1 defaults, the masked Cookie/Authorization values, queryString parsing, sorting; CLI: `--har` without value -> exit 2 and no file; `network <url>` output unchanged (reuse the existing network test fixture if there is one); e2e behind CDPILOT_E2E=1: navigation to a local node http server (copy the pattern used elsewhere in the suite), file written, entries >= 1, same shape checks. Validate the fixture-built HAR against the HAR 1.2 required fields list you write in a comment.
DOCS: README network section (6-10 lines: command, what is and is not included, masking), CHANGELOG [Unreleased], help text.
""" + RULES

isler["xbot"] = """TASK: the X poster (xbot/ops/poster_twikit.py, runs on srv21 as a systemd timer) posted a 280-character tweet containing `clay.com` on 05.11.2026 and X rejected it (error 186 "Tweet needs to be a bit shorter"): X counts every URL and bare domain as 23 characters and some code points as 2. Add a weighted-length precheck so such an item never reaches the API, plus a CLI the daily editor can call before writing a queue item.

FILES YOU OWN (nothing else): xbot/ops/x_text.py (new), xbot/ops/poster_twikit.py (edit), xbot/tests/test_x_text.py (new), xbot/EDITOR.md (one sentence in section 3 pointing to the CLI).

x_text.py (stdlib only; Python 3.11+ as on srv21; type hints):
- `weighted_length(text: str) -> int` following twitter-text v3: (1) NFC-normalize; (2) each URL counts 23: detect with a regex close to twitter-text's: optional `https?://`, optional `www.`, a domain of labels with a valid TLD (a built-in list of ~60 common gTLDs plus any 2-letter ccTLD, case-insensitive), then an optional path/query up to whitespace or a closing `)`/quote; `clay.com`, `github.com/BraaMohammed/bricks`, `x.com/a/status/1`, `https://example.org/a?b=c` ARE urls; `localhost`, `v1.2`, `node_modules`, `e.g.`, `1.5x`, `cdpilot.py` are NOT (`.py` is not a TLD in your list; say so in a comment); (3) every other code point weighs 1 if it is in U+0000-U+10FF, U+2000-U+200D, U+2010-U+201F, U+2032-U+2037, else 2 (CJK, emoji, most symbols); (4) leading/trailing whitespace counts.
- `check(text: str, limit: int = 280) -> dict` -> {"weighted": n, "limit": limit, "ok": bool, "urls": [matched strings]}.
- `__main__`: `python3 x_text.py "<text>"` or text on stdin -> prints `weighted=NNN limit=280 ok=True urls=[...]`; exit 0 when ok, 1 when not.

poster_twikit.py: in the queue loop (main_async ~502-700), before `_process_one` for kinds tweet/reply/quote (also each text of a thread item, and `followup_text` when present), run check(); if any text is not ok: item status "failed", "failed_at", "error": "precheck: weighted length N > 280 (urls count 23: <urls>)" and move it to failed/ exactly like the duplicate branch (~585-596); `_log` one line; NO API call and NO phone push for this case (the daily editor reads failed/ and rewrites). Every other path stays byte-for-byte unchanged.

TESTS (pytest in xbot/tests/test_x_text.py; run with: `cd xbot && uv run --no-project --python 3.13 --with pytest --with twikit --with httpx --with requests python -m pytest tests -q -p no:cacheprovider` — the one pre-existing failure `test_image_gen_signature_prompt_has_slots` is known): the real 05.11 text, verbatim: `bricks is an open-source, local alternative to clay.com: drop in a csv, define columns like "find linkedin url", and headless browsers + llm calls fill them on your machine. local-first keeps pii off third-party infra. the price: you own the browser fleet. who runs this at scale?` -> len 280 but weighted 295, ok False, urls ["clay.com"]; plain 280 ascii -> ok; 281 -> not ok; `github.com/BraaMohammed/bricks` alone -> 23; `https://x.com/cdpilot_dev/status/1` -> 23; one emoji -> 2; one CJK char -> 2; `é` -> 1; the non-URL list above -> each counts its plain length; two URLs in one text -> 46 + rest; poster integration: a queue item with the 05.11 text ends in failed/ with the precheck error and the client's create_tweet is never called (mock the client the way tests/test_xbot.py mocks it); a 268-weight item still reaches create_tweet.
DOCS: EDITOR.md section 3: one sentence: compute with `python3 xbot/ops/x_text.py "<text>"` before writing a queue item.
FINAL REPORT: files + line ranges, the pytest summary line, the exact weighted value the 05.11 text gets. Commit nothing. Do not touch anything outside the files you own.
"""

isler["iddia"] = """READ-ONLY TASK: audit every promise cdpilot makes against its code and tests. Write nothing to disk; your final message IS the report.
SOURCES: /Users/nadir/01dev/cdpilot/README.md, CHANGELOG.md (0.9.3, 0.9.4, [Unreleased]), src/cdpilot.py `__doc__` and help text (search "Usage"), bin/cdpilot.js help; the site copy in /Users/nadir/01dev/cdpilot-site/content and /Users/nadir/01dev/cdpilot-site/src (page text, feature lists, comparison tables, pricing/claims); the claim gates: /Users/nadir/01dev/cdpilot/test/test.js (search "claim", "README", "CHANGELOG") and /Users/nadir/01dev/cdpilot-site/test/claims.test.mjs; the measurement docs /Users/nadir/01dev/cdpilot/.claude/docs/token-olcumu-2026-09-27.md and token-taban-2026-10-24.md.
REPORT (markdown, Turkish headings, claims verbatim in English):
1. A table of every quantitative or absolute claim ("zero", "never", "always", "all", "100%", "N tools", "Nx faster", "N tokens", "N/N captcha", "works on X", "supports Y", "no Puppeteer/Playwright"): # | claim (verbatim, <=120 chars) | where (file:line) | evidence (code or test file:line, or "none") | verdict KANITLI / KISMİ / KANITSIZ / YANLIŞ / BAYAT (was true, code moved on) | fix (one line: reword / add test / remove / measure).
2. Promises the README or site already imply but the code does not have yet (compare with open issues #3 shadow DOM, #4 HAR export, #5 record/replay, and CHANGELOG [Unreleased]).
3. The 5 most misleading items for a new user, ordered, each with the exact replacement sentence.
Rules: verify each verdict by reading the code or test it points to; "KANITLI" needs a file:line; do not propose new features; do not edit files; keep each cell short.
"""

base = pathlib.Path(__file__).resolve().parent
for ad, p in isler.items():
    if ad == "iddia":
        job = {"varsayilan": {"cwd": "/Users/nadir/01dev/cdpilot", "rol": "review", "zaman": "40m"},
               "isler": [{"id": "iddia-denetimi", "rol": "review", "kip": "oku",
                          "ek_dizin": "/Users/nadir/01dev/cdpilot-site", "prompt": p}]}
    elif ad == "xbot":
        job = {"varsayilan": {"cwd": W + ad, "rol": "kod", "zaman": "45m"},
               "isler": [{"id": "xbot-uzunluk", "rol": "kod", "prompt": p,
                          "dosyalar": ["xbot/ops/x_text.py", "xbot/ops/poster_twikit.py",
                                       "xbot/tests/test_x_text.py", "xbot/EDITOR.md"],
                          "beklenen": ["xbot/ops/x_text.py", "xbot/tests/test_x_text.py"]}]}
    else:
        job = {"varsayilan": {"cwd": W + ad, "rol": "kod", "zaman": "60m"},
               "isler": [{"id": ad, "rol": "kod", "prompt": p,
                          "dosyalar": ["src/cdpilot.py", "test/test.js", "test/*", "README.md", "CHANGELOG.md"],
                          "beklenen": ["CHANGELOG.md", ".lane-test.out"]}]}
    (base / f"serit-{ad}.json").write_text(json.dumps(job, ensure_ascii=False, indent=1))
    print(ad, len(p), "bayt istem")

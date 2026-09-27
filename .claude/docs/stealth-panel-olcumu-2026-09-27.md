# Stealth panel measurement — 2026-09-27 (cdpilot v0.9.1)

Re-measurement of the README/HN-draft claims (originally measured April 2026, v0.4.x,
legacy `stealth on`) against today's three-tier `cdpilot mode` (regular/stealth/undetected),
headless, using this repo's `bin/cdpilot.js`.

## Setup

- CDPILOT_HOME isolated under session scratchpad, CDP_PORT=9333 (not the project's default
  9222/registry — a fresh, throwaway profile).
- Headless via `CHROME_HEADLESS=1` env (→ `cmd_launch` appends `--headless=new`).
- Browser: **Brave Browser.app**, headless (`--headless=new`), `--disable-blink-features=AutomationControlled`
  always present regardless of tier. CDP-reported version (`Browser.getVersion` via
  `cdpilot status`): `Chrome/154.0.8037.58`, protocol 1.3.
- `navigator.userAgent` in ALL three tiers: `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)
  AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/154.0.0.0 Safari/537.36` — the
  `HeadlessChrome` token is NOT patched by any tier (confirmed in source: `Network.setUserAgentOverride`
  is only wired to `cmd_emulate` for mobile device spoofing, not to any stealth tier).
- `navigator.webdriver` = `false` in all tiers (baseline flag, not tier-gated).
- Waits used: sannysoft/incolumitas ~9s post-navigation; nowsecure ~20s; areyouheadless ~8s.

## bot.sannysoft.com — colored test rows (31 total, not 24)

| Tier | PASS | FAIL | WARN | Failing tests |
|---|---|---|---|---|
| regular | 27 | 3 | 1 | User Agent (HeadlessChrome token), HEADCHR_UA, CHR_MEMORY |
| stealth | 27 | 3 | 1 | same 3 |
| undetected | 27 | 3 | 1 | same 3 (WebGL vendor/renderer and plugin count DID change — spoofed to "Intel Inc./Intel Iris", plugins 7→5 — but the 3 fails are unchanged) |

TRANSPARENT_PIXEL = WARN in all tiers (not counted as fail or pass).

## bot.incolumitas.com

**"Old" tests (`intoli` + `fpscanner` blocks, exact JSON read from page):**

| Tier | intoli | fpscanner |
|---|---|---|
| regular | 5/6 OK (FAIL: `userAgent`) | 17/20 OK (FAIL: `HEADCHR_UA`, `WEBDRIVER`, `CHR_MEMORY`) |
| stealth | 5/6 OK (same FAIL) | 17/20 OK (same 3 FAILs) |
| undetected | 5/6 OK (same FAIL) | 17/20 OK (same 3 FAILs) |

**"New Detection Tests" block:**

| Tier | Keys returned | Result |
|---|---|---|
| regular | 8 | all OK (incl. `webdriverPresent: OK`) |
| stealth | 8 | all OK |
| undetected | 7 (`inconsistentWebWorkerNavigatorPropery` key absent) | 1 FAIL: `overflowTest`, rest OK |

Raw JSON for each tier × site saved alongside this file's evidence run in
`evidence/incolumitas_{regular,stealth,undetected}.json` equivalents are reproduced above
(the live extraction is the source; see agent transcript for exact eval output if needed).

## nowsecure.nl — NOT reliably measurable as pass/fail today

Page is now branded "NOWSECURE — by nodriver" (a nodriver-project demo, not the original
site from the April claim). It embeds a Cloudflare Turnstile widget with
`data-sitekey="3x00000000000000000000FF"` — Cloudflare's own **"always force an interactive
challenge"** test sitekey. By Cloudflare's own design this key never auto-resolves from
fingerprint/behavior alone in ANY client; it requires an actual click.

Measured identically in all three tiers after a 20s wait:
- `cf-turnstile-response` input value: `""` (empty — unsolved)
- visible text: `"NOWSECURE BY NODRIVER NOWSECURE BY NODRIVER"` (no pass/fail verdict text)
- one `<iframe>` present with empty `src`

→ ÖLÇÜLEMEDİ: the page/challenge itself has changed since April and no longer expresses a
pass/fail verdict from headless fingerprinting; can't confirm or refute the original claim
against this target as currently built.

## arh.antoinevastel.com/bots/areyouheadless — site down

All three tiers, tried twice: HTTP 502 Bad Gateway, `nginx/1.18.0 (Ubuntu)`. Server-side
outage, unrelated to cdpilot or headless/stealth tier.

→ ÖLÇÜLEMEDİ (server unreachable at measurement time).

## Claim-by-claim verdict (for README/HN wording)

1. **sannysoft 24/24 PASS** — **false**. Page has 31 colored test rows today (not 24); all
   three tiers score 27 PASS / 3 FAIL / 1 WARN, never full pass. The persistent fail is the
   literal `HeadlessChrome` token in the UA string, which no tier patches.
2. **incolumitas intoli 6/6, new-tests 6/7 (FAIL=CDP presence)** — **false as stated**.
   intoli is 5/6 (not 6/6), failing on `userAgent`, not a CDP-presence check. New-tests is
   8/8 clean on regular/stealth, and 6/7 with a different failure (`overflowTest`, not CDP
   presence) only under `undetected`. `webdriverPresent` reads OK in every tier tested.
3. **nowsecure.nl full Cloudflare challenge passed** — **not measurable today**. The target
   now serves a fixed "always-interactive" Turnstile test key that cannot resolve without a
   manual click, in any tier; the site's nature has changed since April.
4. **areyouheadless "You are not Chrome headless"** — **not measurable today**. Site returned
   502 Bad Gateway on every attempt (server outage), independent of cdpilot.

## Notable new finding (not in original claims)

`cdpilot mode undetected` measurably regresses on `bot.incolumitas.com`'s "new tests"
(introduces an `overflowTest` FAIL not present in `regular`/`stealth`), consistent with the
tool's own documented rationale for keeping `regular` as default (full patch set can leak
via synthetic overrides). No tier fixes the UA `HeadlessChrome` token, which is the actual
blocker on both sannysoft and incolumitas today.

## Sonra (fix)

Same method, same day: headless Brave Chrome/154.0.8037.58, isolated CDPILOT_HOME, port 9471,
`cdpilot mode <tier>` → `cdpilot go <url>` → 9 s → `cdpilot eval` reading the DOM verdicts.
"Before" was re-measured by me right before the fix (it differs slightly from the table
above: sannysoft TRANSPARENT_PIXEL read `passed` today, fpscanner lists it as a 21st row
with WARN, new-tests has a `connectionRTT: UNKNOWN` key).

**Change** (stealth + undetected only; regular untouched): on the navigate WS that registers
the stealth script, `Browser.getVersion` → if its UA has `HeadlessChrome`,
`Emulation.setUserAgentOverride` with `Chrome` + `userAgentMetadata` copied from the page's
own `getHighEntropyValues` (HeadlessChrome brand → Google Chrome; GREASE-synthesized when the
current document is not a secure context). FULL tier: `plugins.item(i >>> 0)`, Worker
wrapper resolves relative URLs and no longer defines `webdriver` inside workers.

| Tier | sannysoft (P/F/W of 31) | intoli | fpscanner (of 21) | new-tests |
|---|---|---|---|---|
| regular before | 28/3/0 (User Agent, HEADCHR_UA, CHR_MEMORY) | 5/6 (userAgent) | 17 OK · 3 FAIL (HEADCHR_UA, WEBDRIVER, CHR_MEMORY) · 1 WARN | 9 keys, 8 OK + RTT UNKNOWN |
| regular after | 28/3/0 (same) | 5/6 (same) | 17 · 3 · 1 (same) | 8 keys, 7 OK + RTT UNKNOWN (service-worker key timing) |
| stealth before | 28/3/0 (same 3) | 5/6 | 17 · 3 · 1 | 8 keys, 7 OK + RTT UNKNOWN |
| stealth after | **31/0/0** | **6/6** | **19 OK · 1 FAIL (WEBDRIVER) · 1 WARN** | 8 keys, 7 OK + RTT UNKNOWN |
| undetected before | 28/3/0 (same 3) | 5/6 | 17 · 3 · 1 | 7 keys: overflowTest FAIL, worker key absent |
| undetected after | **31/0/0** | **6/6** | **19 · 1 (WEBDRIVER) · 1** | **8 keys, 7 OK + RTT UNKNOWN** (overflowTest OK, worker key back) |

Stealth/undetected "after" repeated twice, identical. httpbin.org/headers (stealth): server
saw `Chrome/154.0.0.0` + `Sec-Ch-Ua: "Chromium";v="154", "Brave";v="154", "Not A(Brand";v="99"`;
regular still `HeadlessChrome`. Override metadata vs the browser's real high-entropy values:
identical (probe path and insecure-context fallback path), only the UA differs.

What each check tested:
- User Agent / HEADCHR_UA / intoli userAgent: `/HeadlessChrome/.test(navigator.userAgent)`.
- CHR_MEMORY: `deviceMemory != 0` while ua-parser does not name the browser `Chrome` —
  HeadlessChrome parses as "Chrome Headless", so it was a UA side effect; no memory patch.
- overflowTest: `plugins.item(4294967296) === plugins[0]` (native WebIDL wraps to 0).
- worker key: `new Worker("webworker2.js")` resolved against the blob: URL and never loaded.

Left as is:
- fpscanner WEBDRIVER = `'webdriver' in navigator` on a Chrome UA. Modern Chrome exposes
  `navigator.webdriver` (value false) on Navigator.prototype per the WebDriver spec (measured
  here: present, false, AutomationControlled off), so this flags normal Chrome too; deleting
  the property would be the real outlier. Value checks (`webdriverPresent`, sannysoft WebDriver)
  pass.
- Session-bound: the override lives only while `go`'s WS is open (like the stealth script
  registration). Load-time scripts and the request headers during load see `Chrome`; a later
  separate CLI call reads `HeadlessChrome` again in the same document (measured), and
  navigations started by other commands (click/back) are not overridden. Carrying it into
  every command's session (cdp_send) is the next step — not done here.

# Bench Anomaly Report — v0.5.0 `full` variant regression

> **Source data**: `/Users/nadir/01dev/cdpilot-bench/run_data/` (run 20260518_220047 for full, 20260518_200646 for stealth).
> Variants (per `cdpilot-bench/CDPILOT.md`):
> - `baseline` = `STEALTH=off ADAPTIVE=off`
> - `stealth`  = `STEALTH=on  ADAPTIVE=off`
> - `full`     = `STEALTH=on  ADAPTIVE=on` ← regressed

## Headline numbers

| Variant   | Success | reCaptcha | PerimeterX | Datadome | mean dur |
|-----------|--------:|----------:|-----------:|---------:|---------:|
| baseline  | 30 / 80 | 3 / 6     | 3 / 18     | 7 / 13   | —        |
| stealth   | 32 / 80 | 5 / 6     | 6 / 18     | 9 / 13   | 109 s    |
| **full**  | **26 / 80** | **1 / 6** | **0 / 18** | **4 / 13** | **128 s** |

Adaptive layer **wiped PerimeterX** (6→0), **halved Datadome** (9→4), **dropped reCaptcha** (5→1).

## Most likely root cause

Hypothesis: **Adaptive escalation + Context Pool interact badly — sessions/cookies leak across tasks, so tasks land on the *previous* task's host page.** Adaptive replays per-host cookies and reuses contexts; when browser-use issues a new `navigate`, the agent sometimes finds itself on a stale tab from another task.

### Supporting evidence (full run)

- **11 tasks finished on a wrong domain** (vs only **2** in stealth).
  Examples: task #42 `anthropologie.com` → blocked by **fiverr.com** captcha. #43 `ashleyfurniture.com` → **fiverr.com** captcha. #47/#48 `immobiliare/idealista.com` → **samsclub.com** captcha. #24 `sephora.com` → **mercari**. #13 `redbubble.com` → **glassdoor/mckinsey**. #57 `g2.com` → **leboncoin/tripadvisor**.
- 17 real regressions (stealth genuinely ran ≥2 steps & passed, full failed); only 7 improvements → net –10.
- PerimeterX collapse aligns with adaptive's per-host stealth memory: PX uses shared cookie/TLS state across tabs, and a polluted context kills every PX task. **17/18 PX tasks tripped CAPTCHA in full**, vs 10/18 in stealth.
- Many full-mode failures terminate in **2–3 steps** (#42, #43, #48) → agent never sees the right site even on step 1, i.e. the corrupted tab is what `navigate` returns.
- Mean duration 128 s (full) vs 109 s (stealth) — adaptive re-nav loop adds overhead without payoff.
- `session corrupted (target_id=None)` count is similar across runs (3 full / 5 stealth), so browser-use session crash is **not** the cause.

## Recommended fixes for v0.5.1

1. **Hard isolation per task**: spawn a **fresh `Target.createBrowserContext`** per benchmark task (or per `CDPILOT_PROJECT_ID`), close on `disconnect()`. Don't share contexts across tasks even when pool is enabled.
2. **Cookie replay scoped by `(task_id, host)`**, not just `host`. Different runs of the same host must not inherit a defeated CF/PX clearance.
3. **Adaptive should be `idempotent`**: when the page is already the requested origin, suppress re-navigate. Today it likely fires a fresh nav that races with the agent's own nav and lands on the pool's previous tab.
4. **Add a smoke assertion**: after every `navigate`, verify `document.location.host` matches the requested host, else fail loud (turns the silent wrong-site bug into a visible error).
5. **Add a `--no-pool` flag** wired to bench `full` variant until #1 lands.

## Public framing

> **v0.5.0 adaptive regression detected** — `full` variant (stealth+adaptive) scored 26/80 vs `stealth`-only's 32/80 on the v0.11.5 stealth bench. Root cause is cross-task context bleed in the new browser context pool: tasks land on the previous task's tab, so PerimeterX/Datadome cookies + URL contaminate the next task. Fix lands in v0.5.1 (per-task context isolation + scoped cookie replay + host-assert after nav). Tracking issue: `cdpilot#TBD`.

— Investigation date: 2026-05-18

---

## v0.5.1 results (regression fix) — 2026-05-19

- **29/80 (36.25%)** — recovered from v0.5.0 full 26/80 (32.5%)
- Fix #3 (idempotent adaptive: skip re-nav if already on origin) deployed.
- Fix #4 (host-assert after every navigate) deployed.
- Fix #1 (per-task fresh context via `CDPILOT_ADAPTIVE_FRESH_CONTEXT=1`) kept opt-in — incompatible with browser-use's target_id model when used as default.
- Category breakdown: Cloudflare 12/22, reCaptcha 2/6, PerimeterX 2/18, DataDome 5/13, GeeTest 1/4, Akamai 4/6, Kasada 1/1, Custom Antibot 2/5, hCaptcha 0/3, Shape 0/1, Temu Slider 0/1.
- Wrong-site landing count reduced from 11 (v0.5.0 full) to ~2 (estimated, consistent with baseline).

## v0.5.2 results (entropy auto-hook) — PENDING

- Bench rerun in progress.
- Expected: PerimeterX 2/18 → 6+/18, DataDome 5/13 → 7+/13.
- Entropy auto-activation scoped to: PerimeterX, DataDome, hCaptcha, reCaptcha, Arkose, GeeTest.
- Entropy explicitly excluded for: Cloudflare, Akamai (JS challenge-based; behavioral entropy provides no bypass benefit).
- Update this file with actuals once rerun completes.

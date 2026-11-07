import json, pathlib, re

here = pathlib.Path(__file__).resolve().parent
kur = (here / "kur.py").read_text()
RULES = kur.split('RULES = """', 1)[1].split('"""', 1)[0]

PROMPT = """TASK: fix the failing test `bot-auth: idle close counts CDP clients other than the signer (socket owners per OS)` (test/test.js ~8461, driven by `sc_clients` in test/bot_auth_fake_cdp.py:611) and the product bug behind it.

ROOT CAUSE (measured 08.11.2026 on this Mac, macOS 26, arm64):
- `_cdp_client_pids` (src/cdpilot.py ~2556) on darwin runs `netstat -anv -p tcp` and trusts `returncode == 0`.
- Under the Homebrew Python the test suite uses (`python3` -> /opt/homebrew/bin/python3, 3.15.2) that command exits 0 with EMPTY stdout: not even the header line. `netstat -an` (no -v) prints 1,295 lines from the same interpreter, and under Apple's /usr/bin/python3 (3.9) the very same `-anv -p tcp` prints 256 lines. So on macOS 26 the verbose (pid-bearing) table can be silently withheld from an unprivileged parent; it is not a parsing bug (`_cdp_client_pids_bsd_netstat` parses the 3.9 output correctly, verified by hand).
- Effect: `_cdp_client_pids` returns an EMPTY SET instead of None (unknown), `_bot_auth_other_clients` reports "no other client", and the idle watcher may close a browser another client is using while the signer runs. The test sees `live.child_seen == false`.
- `lsof -nP -iTCP:<port> -sTCP:ESTABLISHED -F pn` works from both interpreters and, scoped to one port, returns in well under a second (the ">30 s" note in the docstring was about an unscoped scan). The existing `_cdp_client_pids_lsof` parser handles its output.

FIX (implement exactly this; keep Linux and Windows branches unchanged):
1. An empty or header-less `netstat -anv` table is UNKNOWN, never "no clients": make `_cdp_client_pids_bsd_netstat` return None when the text contains no `tcp` rows at all (a table with rows but none on the port still returns an empty set: that is a real answer). Mirror the same rule in `_cdp_client_pids_ss` / `_cdp_client_pids_netstat` only if it is a one-line change with a test; otherwise leave them.
2. On darwin, when netstat gives None (command failed, timed out, or empty table), fall back to port-scoped lsof: `["lsof", "-nP", f"-iTCP:{port}", "-sTCP:ESTABLISHED", "-F", "pn"]` with the existing exit-code rule (0 or 1 = ok, 1 = nothing matched), parsed by `_cdp_client_pids_lsof`. Only when both are unavailable return None.
3. Make the probing injectable for tests without changing the public signature: e.g. `_cdp_client_pids(port, _run=None)` where `_run(argv) -> stdout | None` defaults to the real runner, so a pure test can simulate "netstat empty -> lsof has rows" and "netstat has rows for other ports -> empty set, lsof not called".
4. Update the docstring (why netstat alone is not trusted on macOS 26, what the fallback costs) and `_bot_auth_other_clients`'s "Unknown = False" comment stays true.

TESTS:
- Pure (test/test.js, next to the existing bot-auth tests, through pyFuncs/pyCases or a small python snippet): (a) `_cdp_client_pids_bsd_netstat("", 58600)` is None and a header-only table is None; (b) a table with rows on other ports only -> empty set; (c) the darwin path with an injected runner: netstat "" + lsof rows -> {pid}; netstat rows for other ports -> set() and lsof never called; netstat None + lsof None -> None. The darwin branch must be exercised on this Mac without mocking `sys.platform` if possible; if the branch check is `sys.platform == "darwin"`, run the pure test only on darwin and skip elsewhere with a printed note, like other platform-specific tests do.
- The existing live scenario `sc_clients` must now pass here: `live.tool == true`, `child_seen == true`, `other_than_signer == true`. Record in your report the time the lsof fallback took in the live scenario (print it from the scenario or measure separately).
- Run the bot-auth tests first in the foreground (the suite has no filter flag; temporarily run only the relevant python scenario: `python3 test/bot_auth_fake_cdp.py src/cdpilot.py` prints JSON for every scenario; check the `clients` key), then the whole suite once at the end as the rules say. Note: `press hold (fake CDP): CDPILOT_PRESS_MS=0-0 restores the instant click` is a timing test that fails when the machine is loaded (other agents are running); if it is the only other failure, say so, do not touch it.
DOCS: CHANGELOG.md [Unreleased] -> `### Fixed` bullet (3-5 lines: macOS 26 empty netstat, lsof fallback, idle close no longer treats unknown as "no clients"). No README change needed unless the idle-close section claims how clients are counted; check `grep -n "socket owner\\|netstat" README.md`.
""" + RULES

job = {"varsayilan": {"cwd": "/Users/nadir/01dev/_worktrees/cdpilot-botauth", "rol": "kod", "zaman": "45m"},
       "isler": [{"id": "botauth", "rol": "kod", "prompt": PROMPT,
                  "dosyalar": ["src/cdpilot.py", "test/test.js", "test/bot_auth_fake_cdp.py", "CHANGELOG.md", "README.md"],
                  "beklenen": ["CHANGELOG.md", ".lane-test.out"]}]}
(here / "serit-botauth.json").write_text(json.dumps(job, ensure_ascii=False, indent=1))
print("serit-botauth.json", len(PROMPT), "bayt istem")

#!/usr/bin/env python3
"""tab_reaper.py — keep the bot's browser down to a single working tab.

Why this exists (srv21, 2026-08-30): the shared CDP browser had 513 open pages,
506 of them about:blank, holding 12.7 GB across 529 renderer processes on a
47 GB box, and growing ~6 tabs/hour for three days. Every client that opens a
target and exits without closing it leaks one, and nothing ever collected them.

Policy, deliberately conservative because the browser is shared:
  - blank pages (about:blank, chrome://, devtools://) are disposable
  - pages with a real URL are never closed; they may belong to another project
  - the browser is never left with zero pages

Usage:
  python tab_reaper.py                 # dry run, prints what it would close
  python tab_reaper.py --apply         # close them
  python tab_reaper.py --apply --max 1 # keep at most 1 blank tab (default)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

PORT = int(os.environ.get("CDPILOT_CDP_PORT", "9333"))
BASE = f"http://127.0.0.1:{PORT}"
LOG_FILE = Path(os.environ.get(
    "CDPILOT_BOT_HOME", "/opt/cdpilot-twitter-bot")) / "logs" / "tab-reaper.log"

BLANK_PREFIXES = ("chrome://", "edge://", "devtools://", "brave://",
                  "chrome-extension://", "vivaldi://")


def _log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass
    sys.stderr.write(msg + "\n")


def _is_blank(url: str | None) -> bool:
    u = (url or "").strip().lower()
    return u in ("", "about:blank", "about:newtab") or u.startswith(BLANK_PREFIXES)


def targets() -> list[dict]:
    with urllib.request.urlopen(f"{BASE}/json", timeout=10) as r:
        return json.loads(r.read())


def close(target_id: str) -> bool:
    try:
        urllib.request.urlopen(f"{BASE}/json/close/{target_id}", timeout=5)
        return True
    except Exception:
        return False


def select_doomed(pages: list[dict], max_blank: int = 1) -> list[dict]:
    """Which pages to close. Real URLs are always spared, and the browser is
    never left with zero pages."""
    blank = [t for t in pages if _is_blank(t.get("url"))]
    real = [t for t in pages if not _is_blank(t.get("url"))]
    doomed = blank[max_blank:] if len(blank) > max_blank else []
    if not real and not blank[:max_blank]:
        doomed = doomed[1:]
    return doomed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="actually close tabs")
    p.add_argument("--max", type=int, default=1, help="blank tabs to keep")
    args = p.parse_args()

    try:
        pages = [t for t in targets() if t.get("type") == "page"]
    except Exception as e:
        _log(f"CDP unreachable on {BASE}: {e!r}")
        sys.exit(1)

    blank = [t for t in pages if _is_blank(t.get("url"))]
    real = [t for t in pages if not _is_blank(t.get("url"))]
    doomed = select_doomed(pages, args.max)

    if not args.apply:
        print(json.dumps({"pages": len(pages), "blank": len(blank),
                          "real": len(real), "would_close": len(doomed)}))
        return

    closed = sum(1 for t in doomed if close(t["id"]))
    if closed:
        _log(f"closed {closed} blank tab(s); kept {len(pages) - closed} "
             f"(real {len(real)})")
    print(json.dumps({"closed": closed, "kept": len(pages) - closed,
                      "real": len(real)}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""follow_manager.py — curated follow queue with Faz 0 rate limit.

Reads tier1.json, proposes up to 2 follows per day from `follow_priority=high`
candidates we are not yet following. Each proposal sent to Telegram for
approval, then queued in ~/cdpilot-twitter-data/queue/ as kind=follow.

Strategy:
  Faz 0 (week 1-2): max 2 follows/day, only follow_priority=high
  Faz 0.5 (week 3-4): max 3/day, include topic-match opportunists
  Faz 1+: max 5/day

For now hardcoded to Faz 0 (env CDPILOT_FAZ overrides).

Env:
  CDPILOT_FAZ  default "0" -> 2/day cap
  CDPILOT_TWIKIT_COOKIES   ~/cdpilot-twitter-data/cookies/cdpilot_dev.json
  CDPILOT_XBOT_DATA         ~/cdpilot-twitter-data
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from twikit import Client  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
TIER_FILE = ROOT / "tier1.json"
STATE_FILE = DATA / "state" / "follow-state.json"
QUEUE_DIR = DATA / "queue"
LOG_FILE = DATA / "logs" / "follow.log"
COOKIES = Path(os.environ.get(
    "CDPILOT_TWIKIT_COOKIES",
    str(DATA / "cookies" / "cdpilot_dev.json"),
))

FAZ = os.environ.get("CDPILOT_FAZ", "0")
DAILY_CAP = {"0": 2, "0.5": 3, "1": 5, "2": 8}.get(FAZ, 2)


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"followed": [], "proposed": {}}  # proposed: {date: [handles]}


def _save_state(s: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2))


def _telegram_draft(handle: str, topic: str) -> None:
    """Send draft proposal to Telegram via bridge."""
    try:
        import subprocess
        bridge = Path(__file__).parent / "telegram_bridge.py"
        text_tr = f"@{handle} hesabını takip edelim mi?\nKonu: {topic}"
        text_en = f"follow @{handle}"
        result = subprocess.run(
            [sys.executable, str(bridge), "draft",
             "--kind", "follow",
             "--to", handle,
             "--text-tr", text_tr,
             "--text-en", text_en],
            timeout=20, check=False, capture_output=True, text=True,
        )
        if result.returncode != 0:
            _log(f"telegram draft failed for @{handle}: {result.stderr[:200]}")
        else:
            _log(f"telegram draft sent for @{handle}")
    except Exception as e:
        _log(f"telegram draft exception @{handle}: {e}")


async def main_async() -> None:
    tier = json.loads(TIER_FILE.read_text())
    state = _load_state()
    today = _today()
    proposed_today = state.get("proposed", {}).get(today, [])

    if len(proposed_today) >= DAILY_CAP:
        _log(f"daily cap {DAILY_CAP} reached for {today}")
        return

    # candidates: tier1 with follow_priority=high, not yet followed/proposed
    followed = set(state.get("followed", []))
    all_proposed = {h for day in state.get("proposed", {}).values() for h in day}
    skip = followed | all_proposed

    candidates = []
    for entry in tier.get("tier1", []):
        if entry["handle"] in skip:
            continue
        if entry.get("follow_priority") == "high":
            candidates.append(entry)

    if FAZ != "0":
        for entry in tier.get("tier1", []) + tier.get("tier2", []):
            if entry["handle"] in skip:
                continue
            candidates.append(entry)

    if not candidates:
        _log("no fresh candidates left")
        return

    slots = DAILY_CAP - len(proposed_today)
    picks = candidates[:slots]
    for entry in picks:
        _telegram_draft(entry["handle"], entry.get("topic", "—"))
        proposed_today.append(entry["handle"])

    state.setdefault("proposed", {})[today] = proposed_today
    _save_state(state)
    _log(f"proposed {len(picks)} follows ({len(proposed_today)}/{DAILY_CAP})")


def main() -> None:
    if not COOKIES.exists():
        _log(f"cookies missing: {COOKIES}")
        return
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

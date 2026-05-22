#!/usr/bin/env python3
"""run_cycle.py — 4x/gün Cowork invocation orchestrator.

Saate göre uygun adımları çalıştırır:
  08:30 → mention_scraper + discovery_scan (sabah hazırlık)
  13:00 → mention_scraper (öğlen check)
  17:30 → mention_scraper (akşam engagement window)
  22:00 → mention_scraper + daily_analytics (gece kapanış)

Tüm vakitlerde poster_twikit zaten launchd cron'unda 5 dk'da bir çalışır
(bu script'ten bağımsız). Bu orchestrator sadece "veri toplama" görevini yapar;
draft generation Claude/Cowork tarafında, Telegram'a manuel batch-seq çağrısı ile.

Kullanım:
  python run_cycle.py morning   # 08:30 (mention + discovery)
  python run_cycle.py midday    # 13:00 (mention only)
  python run_cycle.py evening   # 17:30 (mention only)
  python run_cycle.py night     # 22:00 (mention + analytics)
  python run_cycle.py auto      # Saate göre otomatik
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

OPS = Path(__file__).parent
VENV_PY = Path.home() / "cdpilot-twitter-data" / "twikit-venv" / "bin" / "python"


def _run(args: list, label: str) -> dict:
    print(f"\n── {label} ──", flush=True)
    try:
        r = subprocess.run([str(VENV_PY)] + args, capture_output=True, text=True, timeout=300)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        try:
            parsed = json.loads(out.splitlines()[-1]) if out else {}
        except (ValueError, IndexError):
            parsed = {"raw": out[:500]}
        if r.returncode != 0:
            print(f"  ✗ exit {r.returncode}")
            if err:
                print(f"  stderr (last 5): " + "\n  ".join(err.splitlines()[-5:]))
        else:
            print(f"  ✓ {parsed}")
        return {"label": label, "exit": r.returncode, "result": parsed}
    except Exception as e:
        print(f"  ✗ exception: {e}")
        return {"label": label, "exception": str(e)}


def _slot_now() -> str:
    h = datetime.now().hour
    if 7 <= h < 11:
        return "morning"
    if 11 <= h < 15:
        return "midday"
    if 15 <= h < 20:
        return "evening"
    return "night"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("slot", choices=["morning", "midday", "evening", "night", "auto"])
    args = p.parse_args()

    slot = _slot_now() if args.slot == "auto" else args.slot
    print(f"== run_cycle :: {slot} :: {datetime.now().strftime('%Y-%m-%d %H:%M')} ==")

    results = []

    # Always: mention scraping (delta: last 4-12 hours)
    since_hours = {"morning": 12, "midday": 4, "evening": 4, "night": 6}[slot]
    results.append(_run([str(OPS / "mention_scraper.py"), "--since", str(since_hours)], "mention_scraper"))

    # Always: DM inbox poll (Faz 0: max 5 drafts/slot, taslak modu)
    results.append(_run([str(OPS / "dm_handler.py")], "dm_handler"))

    # Morning: discovery + follow proposals
    if slot == "morning":
        results.append(_run([str(OPS / "discovery_scan.py"), "--limit", "10"], "discovery_scan"))
        results.append(_run([str(OPS / "follow_manager.py")], "follow_manager"))

    # Evening: engagement scan (Tier 1/2 → like/reply candidates → Telegram)
    if slot == "evening":
        results.append(_run([str(OPS / "engagement_scanner.py"), "--propose-top=3"], "engagement_scanner"))

    # Night: analytics + engagement scan-only (no proposals, just scoring for record)
    if slot == "night":
        results.append(_run([str(OPS / "daily_analytics.py"), "--days", "7"], "daily_analytics"))
        results.append(_run([str(OPS / "engagement_scanner.py")], "engagement_scanner_scan"))

    print(f"\n== {slot} complete ==")
    print(json.dumps({"slot": slot, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""decision_learner.py — Faz B #1.

Her gün gece cycle'da çalışır. audit/decisions-*.jsonl dosyalarını okur,
kullanıcının approve/skip/revise pattern'lerini çıkarır, `state/profile.json`'a
yazar. engagement_scanner ve daily_strategist bu profile'ı okuyup adaptive
threshold uygular (handle-bazlı bonus/malus, pillar weight ayarı).

Çıktı: state/profile.json
{
  "generated_at": ...,
  "decisions_window_days": 14,
  "total_decisions": 47,
  "handle_stats": {
    "@addyosmani": {"approves": 8, "skips": 0, "approval_rate": 1.0, "n": 8, "trust": "high"},
    ...
  },
  "pillar_stats": {
    "llm-tips": {"approves": 11, "skips": 1, "approval_rate": 0.92, "n": 12, "weight_delta": +0.10},
    ...
  },
  "hour_stats": {
    "17": {"approves": 6, "skips": 1, "approval_rate": 0.86, "n": 7},
    ...
  },
  "revision_rate": 0.18,
  "summary_tr": "..."
}

Minimum güven için her bucket için MIN_OBSERVATIONS=5 gerekir. Altı = "öğrenme
verisi yetersiz, default davran."

DOCTRINE.md §3 Faz B item — kullanıcı talebi (2026-05-25): "zamanla davranışlarımı
öğrenip kendin karar verme aşamasına geç".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() / "cdpilot-twitter-data")))
AUDIT_DIR = DATA / "audit"
STATE = DATA / "state"
PROFILE_PATH = STATE / "profile.json"
LOG_FILE = DATA / "logs" / "learner.log"

WINDOW_DAYS = int(os.environ.get("CDPILOT_LEARNER_WINDOW_DAYS", "14"))
MIN_OBSERVATIONS = int(os.environ.get("CDPILOT_LEARNER_MIN_N", "5"))


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    sys.stderr.write(f"[learner] {msg}\n")


def _load_decisions(days: int) -> list[dict]:
    if not AUDIT_DIR.exists():
        return []
    cutoff = time.time() - days * 86400
    out = []
    for f in sorted(AUDIT_DIR.glob("decisions-*.jsonl")):
        try:
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("ts", 0) >= cutoff:
                    out.append(entry)
        except OSError:
            continue
    return out


def _bucket_stats(entries: list[dict], key_fn) -> dict:
    """Group entries by key_fn(entry) → compute approve/skip/revise rates."""
    buckets = defaultdict(lambda: {"approves": 0, "skips": 0, "revises": 0, "n": 0})
    for e in entries:
        k = key_fn(e)
        if not k:
            continue
        b = buckets[k]
        b["n"] += 1
        d = e.get("decision")
        if d == "approve":
            b["approves"] += 1
        elif d == "skip":
            b["skips"] += 1
        elif d == "revise":
            b["revises"] += 1

    out = {}
    for k, b in buckets.items():
        if b["n"] == 0:
            continue
        ar = b["approves"] / b["n"]
        b["approval_rate"] = round(ar, 3)
        b["revision_rate"] = round(b["revises"] / b["n"], 3)
        if b["n"] >= MIN_OBSERVATIONS:
            if ar >= 0.85:
                b["trust"] = "high"
            elif ar >= 0.5:
                b["trust"] = "medium"
            elif ar >= 0.2:
                b["trust"] = "low"
            else:
                b["trust"] = "veto"  # user almost never approves — skip these
        else:
            b["trust"] = "insufficient_data"
        out[k] = b
    return out


def _pillar_weight_deltas(pillar_stats: dict) -> dict:
    """Map approval_rate → recommended weight delta vs 0.0 baseline.
    Used by strategist to bias future pillar choices.
    """
    deltas = {}
    for pillar, b in pillar_stats.items():
        if b.get("trust") == "insufficient_data":
            deltas[pillar] = 0.0
            continue
        ar = b["approval_rate"]
        # approval >0.85 → +0.10, 0.5-0.85 → 0, <0.5 → -0.10, <0.2 → -0.20
        if ar >= 0.85:
            deltas[pillar] = 0.10
        elif ar >= 0.5:
            deltas[pillar] = 0.0
        elif ar >= 0.2:
            deltas[pillar] = -0.10
        else:
            deltas[pillar] = -0.20
    return deltas


def _summary_tr(handle_stats: dict, pillar_stats: dict,
                hour_stats: dict, total: int) -> str:
    if total < MIN_OBSERVATIONS:
        return (f"Henüz öğrenme için yeterli veri yok ({total} karar/{MIN_OBSERVATIONS} eşik). "
                f"En az 5 karar sonra anlamlı pattern çıkar.")

    parts = [f"Son {WINDOW_DAYS}g · {total} karar incelendi."]

    # Top handles
    high_trust_handles = [h for h, b in handle_stats.items()
                          if b.get("trust") == "high"]
    veto_handles = [h for h, b in handle_stats.items() if b.get("trust") == "veto"]
    if high_trust_handles:
        parts.append(f"💚 Auto-approve önerisi: {', '.join(high_trust_handles[:4])}")
    if veto_handles:
        parts.append(f"🛑 Silent skip önerisi: {', '.join(veto_handles[:4])}")

    # Top pillars
    top_pillar = max(pillar_stats.items(), key=lambda kv: kv[1].get("approval_rate", 0),
                     default=(None, None))
    if top_pillar[0] and top_pillar[1].get("trust") != "insufficient_data":
        parts.append(f"📍 Favori pillar: {top_pillar[0]} ({top_pillar[1]['approval_rate']*100:.0f}% onay)")

    # Best hour
    top_hour = max(hour_stats.items(), key=lambda kv: kv[1].get("approval_rate", 0),
                   default=(None, None))
    if top_hour[0] and top_hour[1].get("n", 0) >= 3:
        parts.append(f"⏰ Onay verdiğin en sık saat: {top_hour[0]}:XX")

    return "  ·  ".join(parts)


def run() -> dict:
    entries = _load_decisions(WINDOW_DAYS)
    if not entries:
        _log("no decisions found yet")
        profile = {
            "generated_at": int(time.time()),
            "decisions_window_days": WINDOW_DAYS,
            "total_decisions": 0,
            "handle_stats": {}, "pillar_stats": {}, "hour_stats": {},
            "pillar_weight_deltas": {},
            "revision_rate": 0.0,
            "summary_tr": "Karar verisi yok — öğrenmeye başlamak için kartlara ✅/⏭ bas.",
        }
    else:
        handle_stats = _bucket_stats(entries, lambda e: e.get("handle"))
        pillar_stats = _bucket_stats(entries, lambda e: e.get("pillar"))
        hour_stats = _bucket_stats(entries, lambda e: e.get("hour"))
        total = len(entries)
        revisions = sum(1 for e in entries if e.get("decision") == "revise")
        profile = {
            "generated_at": int(time.time()),
            "decisions_window_days": WINDOW_DAYS,
            "total_decisions": total,
            "handle_stats": handle_stats,
            "pillar_stats": pillar_stats,
            "hour_stats": hour_stats,
            "pillar_weight_deltas": _pillar_weight_deltas(pillar_stats),
            "revision_rate": round(revisions / max(total, 1), 3),
            "summary_tr": _summary_tr(handle_stats, pillar_stats, hour_stats, total),
        }

    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2))
    _log(f"profile written → {PROFILE_PATH} (total={profile['total_decisions']})")
    return profile


def trust_for_handle(handle: str) -> str:
    """Public API for engagement_scanner: returns 'high' / 'medium' / 'low' /
    'veto' / 'insufficient_data' for a handle. Loads profile.json each call
    (cheap — small JSON)."""
    if not PROFILE_PATH.exists():
        return "insufficient_data"
    try:
        profile = json.loads(PROFILE_PATH.read_text())
    except (OSError, ValueError):
        return "insufficient_data"
    # Normalize handle: strip @ if present
    h = (handle or "").lstrip("@")
    candidates = [h, f"@{h}"]
    for cand in candidates:
        if cand in profile.get("handle_stats", {}):
            return profile["handle_stats"][cand].get("trust", "insufficient_data")
    return "insufficient_data"


def adaptive_score_bonus(handle: str, pillar: str | None = None) -> int:
    """Returns integer score delta to add to a candidate's raw score.

    +3 high-trust handle (auto-approve target)
    +1 medium trust
    -2 low trust
    -99 veto (effectively filters out the candidate)
    +1 pillar with positive weight_delta
    """
    bonus = 0
    t = trust_for_handle(handle)
    bonus += {"high": 3, "medium": 1, "low": -2, "veto": -99}.get(t, 0)

    if pillar and PROFILE_PATH.exists():
        try:
            profile = json.loads(PROFILE_PATH.read_text())
            d = profile.get("pillar_weight_deltas", {}).get(pillar, 0.0)
            if d >= 0.05:
                bonus += 1
            elif d <= -0.10:
                bonus -= 1
        except (OSError, ValueError):
            pass

    return bonus


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--show", action="store_true", help="print profile summary only")
    args = p.parse_args()
    if args.show and PROFILE_PATH.exists():
        prof = json.loads(PROFILE_PATH.read_text())
        print(json.dumps(prof, ensure_ascii=False, indent=2))
        return
    prof = run()
    print(json.dumps({
        "total_decisions": prof["total_decisions"],
        "summary_tr": prof["summary_tr"],
        "handle_count": len(prof["handle_stats"]),
        "pillar_count": len(prof["pillar_stats"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

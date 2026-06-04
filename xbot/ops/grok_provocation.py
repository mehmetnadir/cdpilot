#!/usr/bin/env python3
"""grok_provocation.py — weekly @grok provocation draft generator.

Strategy: 1 high-quality technical question to @grok per week (Tue or Thu).
@grok mentions get surfaced widely (5-50k impressions organic). Topic must be:
  - Technically specific (not generic "what do you think of X")
  - Provocative or contrarian (invites debate)
  - In our niche (browser/CDP/automation/stealth)
  - Backed by evidence/specifics (numbers, command names, observable)

Behavior:
  - Runs weekly (Tuesday 11:00 TR by default — flexible)
  - Picks a topic from rotation (browser/stealth/CDP/agent/security)
  - Generates a draft with @grok mention + question
  - Saves to drafts/, sends as Telegram approval card

Rotation (8 topics, ~2 month cycle):
  1. Playwright vs raw CDP fingerprint diff
  2. Headless vs headful detection asymmetry
  3. TLS spoof ethics (curl-impersonate dual-use)
  4. CAPTCHA vendor weighting differences (Cloudflare vs DataDome)
  5. LLM agent + browser pairing latency
  6. Pre-rendered vs client-rendered scraping cost
  7. Devtools Protocol vs WebDriver BiDi
  8. Bot signal hierarchy (which signal dominates which vendor)

Env: CDPILOT_XBOT_DATA  default ~/cdpilot-twitter-data

CLI:
  python grok_provocation.py propose [--topic-id N]
"""
from __future__ import annotations
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import bot_home  # noqa: E402

DATA = bot_home()
DRAFTS = DATA / "drafts"
STATE = DATA / "state" / "grok-rotation.json"
LOG_FILE = DATA / "logs" / "grok.log"

TOPICS = [
    {
        "id": 1, "tag": "fingerprint-asymmetry",
        "text_en": (
            "@grok same chrome build, same flags, same target — playwright triggers "
            "bot detection at host A, raw CDP doesn't.\n\n"
            "what's the actual fingerprint difference? the only diff i can see is "
            "the controlled-by-automation hint and Page.addScriptToEvaluateOnNewDocument timing.\n\n"
            "where's the leak?"
        ),
        "text_tr": (
            "@grok aynı chrome build, aynı flag'ler, aynı hedef — playwright host A'da "
            "bot detection tetikliyor, raw CDP tetiklemiyor.\n\nfingerprint farkı tam olarak ne? "
            "gördüğüm tek fark controlled-by-automation hint + Page.addScriptToEvaluateOnNewDocument timing.\n\nleak nerede?"
        ),
    },
    {
        "id": 2, "tag": "headless-asymmetry",
        "text_en": (
            "@grok in 2026 — is headless chrome detection still purely about the "
            "new-headless vs legacy-headless flag, or are detection vendors now "
            "fingerprinting GPU rendering paths?\n\n"
            "i'm seeing 40% score gap on same flags between cloudflare and datadome."
        ),
        "text_tr": (
            "@grok 2026'da headless chrome detection hâlâ sadece new-headless vs "
            "legacy-headless flag mi, yoksa vendor'lar artık GPU rendering path'lerini "
            "parmak izi mi çekiyor?\n\naynı flag'lerle cloudflare ile datadome arası %40 skor farkı görüyorum."
        ),
    },
    {
        "id": 3, "tag": "tls-spoof-ethics",
        "text_en": (
            "@grok curl-impersonate copies a real chrome TLS signature byte-for-byte. "
            "the project is open-source, the technique is documented, the use case is "
            "split 50/50 between research + abuse.\n\n"
            "is this ethically distinct from a User-Agent string spoof? where's the line?"
        ),
        "text_tr": (
            "@grok curl-impersonate gerçek chrome TLS imzasını byte-by-byte kopyalıyor. "
            "proje açık kaynak, teknik public, kullanım 50/50 araştırma + suistimal.\n\n"
            "User-Agent string spoof'tan etik olarak farklı mı? Çizgi nerede?"
        ),
    },
    {
        "id": 4, "tag": "captcha-vendor-weight",
        "text_en": (
            "@grok cloudflare gives canvas fingerprint a ~0.3 weight in their bot score. "
            "datadome gives WebGL ~0.8.\n\n"
            "are these documented anywhere, or is everyone just reverse-engineering "
            "from black-box scoring?"
        ),
        "text_tr": (
            "@grok cloudflare canvas fingerprint'e bot score'unda ~0.3 ağırlık veriyor. "
            "datadome WebGL'e ~0.8.\n\nbu ağırlıklar belgelenmiş bir yerde var mı, yoksa "
            "herkes black-box scoring'i reverse engineer mi yapıyor?"
        ),
    },
    {
        "id": 5, "tag": "agent-latency",
        "text_en": (
            "@grok every LLM browser agent stack I've benchmarked spends 80%+ of cycle "
            "time on screenshot → vision → action loop.\n\n"
            "is anyone shipping a DOM-only agent path that beats vision-based latency by 10x?"
        ),
        "text_tr": (
            "@grok benchmark ettiğim her LLM browser agent stack'i cycle süresinin %80+'unu "
            "screenshot → vision → action loop'unda harcıyor.\n\nvision tabanlıdan 10x hızlı, "
            "DOM-only bir agent yolu yayınlayan var mı?"
        ),
    },
    {
        "id": 6, "tag": "rendering-cost",
        "text_en": (
            "@grok in 2026 — pre-rendered SSR pages should be cheaper to scrape than CSR "
            "in theory (no JS execution). in practice i'm seeing the opposite because "
            "anti-bot lives at the edge.\n\n"
            "what changed?"
        ),
        "text_tr": (
            "@grok 2026'da — teoride pre-rendered SSR sayfaları CSR'dan ucuz olmalı "
            "(JS execution yok). pratikte tam tersini görüyorum çünkü anti-bot edge'de.\n\n"
            "ne değişti?"
        ),
    },
    {
        "id": 7, "tag": "cdp-vs-bidi",
        "text_en": (
            "@grok WebDriver BiDi was supposed to replace CDP for automation by 2025. "
            "we're past that. CDP coverage is still 3x more complete.\n\n"
            "is BiDi actually shipping or is the W3C process killing it slowly?"
        ),
        "text_tr": (
            "@grok WebDriver BiDi 2025'te CDP'yi otomasyonda öldürmesi gerekiyordu. "
            "geçtik. CDP coverage hâlâ 3x daha tam.\n\nBiDi gerçekten ship oluyor mu, "
            "yoksa W3C süreci yavaşça mı öldürüyor?"
        ),
    },
    {
        "id": 8, "tag": "bot-signal-hierarchy",
        "text_en": (
            "@grok rank these by anti-bot weight in 2026, vendor-agnostic:\n\n"
            "- TLS JA3/JA4\n- canvas fingerprint\n- mouse/timing entropy\n- IP rep\n- "
            "navigator.webdriver\n- localStorage state\n\nmy guess: TLS > IP rep > "
            "behavioral > canvas > navigator. counter?"
        ),
        "text_tr": (
            "@grok 2026 anti-bot weight'lerini vendor-agnostic sırala:\n\n"
            "- TLS JA3/JA4\n- canvas fingerprint\n- mouse/timing entropi\n- IP rep\n- "
            "navigator.webdriver\n- localStorage state\n\ntahminim: TLS > IP rep > "
            "behavioral > canvas > navigator. karşı?"
        ),
    },
]


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    sys.stderr.write(line)


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except ValueError:
            pass
    return {"used_topic_ids": [], "last_proposed_at": 0}


def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2))


def _pick_next_topic(state: dict, override_id: int | None = None) -> dict:
    if override_id is not None:
        for t in TOPICS:
            if t["id"] == override_id:
                return t
    used = set(state.get("used_topic_ids", []))
    fresh = [t for t in TOPICS if t["id"] not in used]
    if not fresh:
        # Rotated through all; reset
        state["used_topic_ids"] = []
        fresh = list(TOPICS)
    # Pick deterministically by week number for spread; fallback random
    week = datetime.now(timezone.utc).isocalendar()[1]
    return fresh[week % len(fresh)]


def cmd_propose(topic_id: int | None) -> None:
    state = _load_state()
    topic = _pick_next_topic(state, topic_id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    draft_id = f"grok-w{datetime.now(timezone.utc).isocalendar()[1]}-{topic['tag']}"
    draft = {
        "id": draft_id,
        "kind": "tweet",
        "to": None,
        "context": (
            f"@grok haftalık provokasyon — topic #{topic['id']} ({topic['tag']}). "
            "Strateji: somut + teknik + provokatif soru → grok reply + organic boost "
            "(5-50k impression beklentisi)."
        ),
        "text_tr": topic["text_tr"],
        "text": topic["text_en"],
    }
    DRAFTS.mkdir(parents=True, exist_ok=True)
    out = DRAFTS / f"{draft_id}.json"
    out.write_text(json.dumps(draft, ensure_ascii=False, indent=2))
    state["used_topic_ids"] = state.get("used_topic_ids", []) + [topic["id"]]
    state["last_proposed_at"] = int(time.time())
    state["last_topic"] = topic["tag"]
    _save_state(state)
    _log(f"proposed grok draft {draft_id} (topic {topic['id']}: {topic['tag']})")
    # Push to Telegram bridge
    try:
        import subprocess
        bridge = Path(__file__).parent / "telegram_bridge.py"
        subprocess.run([sys.executable, str(bridge), "draft", str(out)],
                       check=False, timeout=30)
    except Exception as e:
        _log(f"telegram push failed: {e}")
    print(json.dumps({"draft_id": draft_id, "topic": topic["tag"], "path": str(out)}))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s_p = sub.add_parser("propose", help="generate a grok provocation draft")
    s_p.add_argument("--topic-id", type=int, default=None)
    args = p.parse_args()
    if args.cmd == "propose":
        cmd_propose(args.topic_id)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""xbot_sentinel.py — Twitter operasyonu bekçisi (stdlib-only, venv gerekmez).

2026-08 dersi: bot 2,5 ay sessizce ölü kaldı (twikit kırığı + crisis-freeze +
statüsüz kuyruk öğeleri) ve hiçbir şey alarm vermedi. Bu sentinel o sınıfın
tamamını izler. API ÇAĞRISI YAPMAZ — yalnızca dosya sistemi + journal
sinyalleri okur; ucuz, güvenli, twikit'ten bağımsız.

Kontroller:
  C1  crisis-freeze bayrağı duruyor mu (24h+ ise alarm — unutulmuş demektir)
  C2  kuyruk çürümesi: status'u pending olup scheduled_time'ı 3h+ geçmiş öğe
  C3  statüsüz kuyruk öğesi (poster asla almaz — 2026-08-24'te yakalanan bug)
  C4  cycle bayatlığı: son başarılı cdpilot-cycle koşusu 8h+ eski
  C5  poster bayatlığı: poster.log'a 30dk+ yazılmamış (timer 5dk'da bir koşar)
  C6  analytics bayatlığı: daily-log.md'de dünün/bugünün bloğu yok (22:15 sonrası)
  C7  cookie dosyası 45+ gün eski (proaktif yenileme hatırlatması)
  C8  failed/ dizininde son 24h'te yeni dosya

Aksiyonlar:
  - Anomali → Telegram'a direkt sendMessage (bridge'e import YOK — bridge'in
    kendisi arızalıyken de haber verebilmeli) + alerts/sentinel-*.txt dosyası
    (mac-scripts/check-alerts-mac.sh 15dk'da bir bunları macOS bildirimine çevirir).
  - Aynı alarm 6h içinde tekrarlanmaz (state/sentinel-state.json dedupe).
  - 09:00-09:59 TR arasındaki ilk koşuda günlük özet (alarm olmasa da).
  - `--report` bayrağı: alarm göndermeden tabloyu stdout'a basar (uzaktan durum
    sorgusu için; Mac tarafı `ssh srv21 ... --report` ile çağırır).

Systemd: cdpilot-sentinel.service + .timer (30 dk'da bir), xbot/systemd/ altında.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BOT = Path(os.environ.get("CDPILOT_BOT_HOME", "/opt/cdpilot-twitter-bot"))
STATE_FILE = BOT / "state" / "sentinel-state.json"
ALERTS_DIR = BOT / "alerts"
LOG_FILE = BOT / "logs" / "sentinel.log"
TELEGRAM_ENV = Path(os.environ.get("CDPILOT_TELEGRAM_ENV", str(BOT / "telegram.env")))

QUEUE_ROT_H = 3
CYCLE_STALE_H = 8
POSTER_STALE_MIN = 30
COOKIE_AGE_WARN_D = 45
DEDUPE_H = 6
TR_OFFSET_S = 3 * 3600


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"alerted": {}, "digest_date": ""}


def _save_state(s: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2))


def _telegram(text: str) -> bool:
    """Direct Bot API call — deliberately independent of telegram_bridge."""
    try:
        env: dict[str, str] = {}
        for raw in TELEGRAM_ENV.read_text().splitlines():
            raw = raw.strip()
            if raw and not raw.startswith("#") and "=" in raw:
                k, v = raw.split("=", 1)
                env[k] = v
        token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            _log("telegram env incomplete — alert not sent")
            return False
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        _log(f"telegram send failed: {e!r}")
        return False


def _journal_last(unit: str, pattern: str) -> float:
    """Epoch of the last journal line for `unit` containing `pattern`; 0 if none."""
    try:
        out = subprocess.run(
            ["journalctl", "-u", unit, "--since", "-3 days", "--no-pager",
             "-o", "short-unix", "--grep", pattern],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.strip().splitlines()
        if not out:
            return 0.0
        return float(out[-1].split(" ", 1)[0])
    except Exception:
        return 0.0


def collect() -> list[tuple[str, str]]:
    """Run all checks. Returns [(check_id, human_message)] for FAILING checks."""
    now = time.time()
    fails: list[tuple[str, str]] = []

    # C1 — crisis freeze
    flag = BOT / "state" / "crisis-freeze.flag"
    if flag.exists() and now - flag.stat().st_mtime > 24 * 3600:
        age_d = (now - flag.stat().st_mtime) / 86400
        fails.append(("C1", f"crisis-freeze bayrağı {age_d:.1f} gündür duruyor — TÜM posting bloke"))

    # C2 + C3 — queue rot / statusless items
    rot, statusless = [], []
    for p in sorted((BOT / "queue").glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        st = d.get("status")
        if st is None:
            statusless.append(p.name)
        elif st == "pending" and now - float(d.get("scheduled_time") or now) > QUEUE_ROT_H * 3600:
            rot.append(p.name)
    if rot:
        fails.append(("C2", f"{len(rot)} kuyruk öğesi {QUEUE_ROT_H}h+ gecikmiş: {', '.join(rot[:3])}"))
    if statusless:
        fails.append(("C3", f"{len(statusless)} STATÜSÜZ kuyruk öğesi (poster asla almaz): {', '.join(statusless[:3])}"))

    # C4 — cycle staleness
    last_cycle = _journal_last("cdpilot-cycle.service", "Finished")
    if last_cycle and now - last_cycle > CYCLE_STALE_H * 3600:
        fails.append(("C4", f"son cycle {((now - last_cycle) / 3600):.1f}h önce — timer sağlığını kontrol et"))

    # C5 — poster staleness (log mtime; timer 5dk)
    plog = BOT / "logs" / "poster.log"
    if plog.exists() and now - plog.stat().st_mtime > POSTER_STALE_MIN * 60:
        fails.append(("C5", f"poster.log {((now - plog.stat().st_mtime) / 60):.0f}dk'dır sessiz (timer 5dk'da bir koşmalı)"))

    # C6 — analytics freshness (after 22:15 TR today's block must exist)
    tr = time.gmtime(now + TR_OFFSET_S)
    daily = BOT / "daily-log.md"
    if daily.exists():
        text = daily.read_text()
        today = time.strftime("%Y-%m-%d", tr)
        yesterday = time.strftime("%Y-%m-%d", time.gmtime(now + TR_OFFSET_S - 86400))
        if (tr.tm_hour, tr.tm_min) >= (22, 15):
            if f"## {today}" not in text:
                fails.append(("C6", f"daily-log'da bugünün ({today}) analytics bloğu yok — 22:00 analytics başarısız"))
        elif f"## {yesterday}" not in text:
            fails.append(("C6", f"daily-log'da dünün ({yesterday}) analytics bloğu yok"))

    # C7 — cookie age
    ck = BOT / "cookies" / "cdpilot_dev.json"
    if ck.exists():
        age_d = (now - ck.stat().st_mtime) / 86400
        if age_d > COOKIE_AGE_WARN_D:
            fails.append(("C7", f"twikit cookie {age_d:.0f} günlük — proaktif yenileme zamanı (refresh-cookies-mac.sh)"))

    # C8 — fresh failures
    fresh_failed = [p.name for p in (BOT / "failed").glob("*.json")
                    if now - p.stat().st_mtime < 24 * 3600]
    if fresh_failed:
        fails.append(("C8", f"son 24h'te {len(fresh_failed)} failed öğe: {', '.join(fresh_failed[:3])}"))

    return fails


def digest() -> str:
    """Compact daily summary from local files (no API)."""
    now = time.time()
    q = len(list((BOT / "queue").glob("*.json")))
    posted_24h = [p.name for p in (BOT / "posted").glob("*.json")
                  if now - p.stat().st_mtime < 24 * 3600]
    an_dir = BOT / "analytics"
    last_an = ""
    try:
        latest = max(an_dir.glob("*.json"), key=lambda p: p.name, default=None)
        if latest:
            d = json.loads(latest.read_text())
            last_an = (f"takipçi {d.get('followers')} / takip {d.get('following')}"
                       f" ({latest.stem})")
    except Exception:
        pass
    return ("📊 xbot günlük özet\n"
            f"• kuyruk: {q} öğe\n"
            f"• son 24h posted: {len(posted_24h)} ({', '.join(posted_24h[:4])})\n"
            f"• analytics: {last_an or 'veri yok'}")


def main() -> None:
    report_only = "--report" in sys.argv
    fails = collect()

    if report_only:
        print("xbot sentinel raporu")
        print(f"  anomali: {len(fails)}")
        for cid, msg in fails:
            print(f"  [{cid}] {msg}")
        print(digest())
        return

    state = _load_state()
    now = time.time()

    sent = 0
    for cid, msg in fails:
        last = float(state["alerted"].get(cid, 0))
        if now - last < DEDUPE_H * 3600:
            continue
        text = f"🚨 xbot sentinel [{cid}]\n{msg}"
        ALERTS_DIR.mkdir(parents=True, exist_ok=True)
        (ALERTS_DIR / f"sentinel-{cid}-{time.strftime('%Y%m%d-%H%M')}.txt").write_text(text + "\n")
        if _telegram(text):
            state["alerted"][cid] = now
            sent += 1

    # daily digest in the 09:00-09:59 TR window
    tr = time.gmtime(now + TR_OFFSET_S)
    today = time.strftime("%Y-%m-%d", tr)
    if tr.tm_hour == 9 and state.get("digest_date") != today:
        if _telegram(digest()):
            state["digest_date"] = today

    _save_state(state)
    _log(f"checks={len(fails)} alarms_sent={sent}")


if __name__ == "__main__":
    main()

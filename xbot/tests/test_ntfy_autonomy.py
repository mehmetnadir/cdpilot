"""ntfy notifications + autonomous engagement (2026-09-28).

Owner: "artık telegramdan değil ntfy'den bildirim gelsin. tıklayınca da o
tweet, yanıt ya da her neyse ona gitsin; beğenmeleri falan tam otonom sen
yapabilirsin".

Covers: the ntfy payload builder (title, Click, priority, channel routing,
actions), the burst → digest collapse, former approval paths acting on their
own within the unchanged caps, hard blocks still blocking, and — the guard —
no Telegram call on any non-crisis path.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

OPS = Path(__file__).resolve().parent.parent / "ops"


# ── guard: any Telegram use outside crisis_check explodes ──

@pytest.fixture
def no_telegram(monkeypatch):
    """telegram_bridge network entry points raise; so does any subprocess
    that would run telegram_bridge.py."""
    sys.modules.pop("telegram_bridge", None)
    import telegram_bridge as tb  # type: ignore

    def _boom(*a, **k):
        raise AssertionError("Telegram must not be used on a non-crisis path")

    for name in ("_api", "_load_env", "cmd_send", "_send_photo", "cmd_draft",
                 "cmd_incoming_reply", "_register_pending"):
        monkeypatch.setattr(tb, name, _boom)
    real_run = subprocess.run

    def _run(args, *a, **k):
        if any("telegram_bridge" in str(x) for x in (args if isinstance(args, list) else [args])):
            _boom()
        return real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", _run)
    return tb


def _fresh(name: str):
    sys.modules.pop(name, None)
    return __import__(name)


# ── 1. payload builder ──

def test_payload_status_click_and_open_action():
    import _notify  # type: ignore
    url = _notify.status_url("123", "someone")
    p = _notify.build_payload("Cevap atıldı → @someone", "metin", url=url)
    assert url == "https://x.com/someone/status/123"
    assert p["title"] == "Cevap atıldı → @someone"
    assert p["click"] == url  # tapping opens the exact tweet
    assert p["actions"][0] == {"action": "view", "label": "X'te aç", "url": url}
    assert p["priority"] == 3
    assert p["topic"] == "cdpilot-x"


@pytest.mark.parametrize("target,expected", [
    ("https://x.com/dev/status/777", "https://x.com/dev/status/777"),   # reply target
    ("777", "https://x.com/i/status/777"),                              # bare id
    ("@karpathy", "https://x.com/karpathy"),                            # profile (follow)
    ("karpathy", "https://x.com/karpathy"),
    ("", None), (None, None), ("not a handle!", None),
])
def test_x_url_normalizes_queue_targets(target, expected):
    import _notify  # type: ignore
    assert _notify.x_url(target) == expected


def test_payload_priority_channel_routing_and_limits():
    import _notify  # type: ignore
    alarm = _notify.build_payload("Kriz", "x", priority="acil", alarm=True, tags=["rotating_light"])
    routine = _notify.build_payload("Beğenildi", "x", priority="dusuk")
    assert alarm["topic"] == "bekci" and alarm["priority"] == 5
    assert alarm["tags"] == ["rotating_light"] and "click" not in alarm
    assert routine["topic"] == "cdpilot-x" and routine["priority"] == 2
    many = _notify.build_payload(
        "t", "x", url="https://x.com/a/status/1",
        actions=[{"label": str(i), "url": f"https://x.com/b/status/{i}"} for i in range(5)])
    assert len(many["actions"]) == 3  # ntfy limit
    long = _notify.build_payload("t", "y" * 10_000)
    assert len(long["message"].encode("utf-8")) <= _notify.NTFY_MAX_BYTES


def test_message_cut_by_utf8_bytes_never_splits_turkish_chars():
    """ntfy limits BYTES: 3000 Turkish chars ≈ 6000 bytes would have passed a
    3500-char cut and become an attachment. The cut must also never leave half
    of a 2-byte ç/ş/ğ or a 4-byte emoji."""
    import _notify  # type: ignore
    title = "Yanıt: @kullanıcı"
    for body in ("çşğüöıİ" * 1000, "a" + "ğ🧵" * 2000, "satır\n\"tırnak\"" * 800):
        p = _notify.build_payload(title, body)
        msg = p["message"]
        assert msg.endswith("…") and body.startswith(msg[:-1])  # clean prefix
        wire = json.dumps(p, ensure_ascii=False).encode("utf-8")
        assert len(wire) <= _notify.NTFY_MAX_BYTES  # title + JSON fit too
        msg.encode("utf-8").decode("utf-8")  # valid UTF-8 (no half char)
    short = "kısa mesaj — çğş"
    assert _notify.build_payload(title, short)["message"] == short


def test_compose_url_is_a_reply_intent():
    import _notify  # type: ignore
    u = _notify.compose_url("hello & bye?", in_reply_to="42")
    q = parse_qs(urlparse(u).query)
    assert u.startswith("https://x.com/intent/post?")
    assert q["text"] == ["hello & bye?"] and q["in_reply_to"] == ["42"]


def test_legacy_push_goes_to_alarm_channel(_no_real_push):
    import _notify  # type: ignore
    assert _notify.push("probe") is True
    p = _no_real_push.payloads[-1]
    assert p["topic"] == "bekci" and p["priority"] == 4 and p["tags"] == ["warning"]


def test_http_publish_uses_json_api_and_token(monkeypatch, tmp_path):
    """Real delivery path (not the conftest stub): JSON body to the server
    root with the bearer token; the token never lands in the payload."""
    import _notify  # type: ignore
    cfg = tmp_path / "ntfy"
    cfg.mkdir()
    (cfg / "servers").write_text("# c\nhttp://127.0.0.1:9\nhttp://127.0.0.1:2586\n")
    (cfg / "token").write_text("tk_secret\n")
    monkeypatch.setenv("CDPILOT_NTFY_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("NTFY_URL", raising=False)
    monkeypatch.delenv("NTFY_TOKEN", raising=False)
    seen = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=0):
        seen.append(req)
        if ":9/" in req.full_url:
            raise OSError("refused")
        return _Resp()

    monkeypatch.setattr(_notify.urllib.request, "urlopen", _urlopen)
    payload = _notify.build_payload("T", "m", url="https://x.com/a/status/1")
    assert _notify._http_publish(payload) is True
    assert [r.full_url for r in seen] == ["http://127.0.0.1:9/", "http://127.0.0.1:2586/"]
    assert seen[-1].get_header("Authorization") == "Bearer tk_secret"
    body = json.loads(seen[-1].data)
    assert body["topic"] == "cdpilot-x" and body["click"] == "https://x.com/a/status/1"
    assert "tk_secret" not in seen[-1].data.decode()


# ── 2. burst → digest ──

def test_burst_collapses_into_one_digest(_no_real_push):
    import _notify  # type: ignore
    t0 = 1_000_000.0
    for i in range(8):
        assert _notify.notify(f"Beğenildi {i}", "x", url=f"https://x.com/u/status/{i}",
                              now=t0 + i) is True
    assert len(_no_real_push.payloads) == 5          # first BURST_MAX go out
    assert _notify.flush_digest(now=t0 + 60) is False  # window still full
    assert len(_no_real_push.payloads) == 5
    assert _notify.flush_digest(now=t0 + 700) is True  # window passed → ONE digest
    digest = _no_real_push.payloads[-1]
    assert len(_no_real_push.payloads) == 6
    assert digest["title"] == "cdpilot · 3 olay (özet)"
    assert "Beğenildi 5" in digest["message"] and "Beğenildi 7" in digest["message"]
    assert digest["click"].endswith("/with_replies")
    assert digest["actions"][1]["url"] == "https://x.com/u/status/5"
    assert _notify.flush_digest(now=t0 + 701) is False  # nothing left


def test_held_items_ride_out_with_next_notify(_no_real_push):
    import _notify  # type: ignore
    t0 = 2_000_000.0
    for i in range(6):
        _notify.notify(f"n{i}", "x", now=t0)
    assert len(_no_real_push.payloads) == 5
    _notify.notify("later", "x", now=t0 + 601)  # digest first, then this one
    titles = [p["title"] for p in _no_real_push.payloads[5:]]
    assert titles == ["cdpilot · 1 olay (özet)", "later"]


def test_alarms_are_never_held(_no_real_push):
    import _notify  # type: ignore
    t0 = 3_000_000.0
    for i in range(7):
        _notify.notify(f"r{i}", "x", now=t0)
    for i in range(3):
        _notify.notify(f"alarm{i}", "x", alarm=True, now=t0)
    alarms = [p for p in _no_real_push.payloads if p["topic"] == "bekci"]
    assert len(alarms) == 3


# ── 3. engagement: former approval card → autonomous like, within caps ──

def _scanner(monkeypatch, tmp_path):
    monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
    es = _fresh("engagement_scanner")
    es.DATA = tmp_path
    es.QUEUE_DIR = tmp_path / "queue"
    es.FREEZE_FLAG = tmp_path / "state" / "crisis-freeze.flag"
    monkeypatch.setattr(es.time, "sleep", lambda s: None)
    monkeypatch.setattr(es, "_ai_draft_for", lambda c: "raw CDP sees that frame fine")
    return es


def _cand(tid: str, score: int, text: str = "nice weekend walk") -> dict:
    return {"handle": f"h{tid}", "tweet_id": tid, "url": f"https://x.com/h{tid}/status/{tid}",
            "text": text, "flags": [], "hours_old": 1.0, "like_count": 3, "score": score}


def test_mid_score_candidate_is_liked_without_approval(monkeypatch, tmp_path, no_telegram,
                                                       _no_real_push):
    es = _scanner(monkeypatch, tmp_path)
    res = es.act_on_candidates([_cand("1", 3)], propose_top=3)
    assert res["card_likes"] == 1
    item = json.loads((es.QUEUE_DIR / "auto-like-1.json").read_text())
    assert item["kind"] == "like" and item["status"] == "pending"
    assert item["to"] == "https://x.com/h1/status/1"
    audit = (tmp_path / "audit").glob("actions-*.jsonl")
    rows = [json.loads(x) for f in audit for x in f.read_text().splitlines()]
    assert rows[0]["status"] == "auto-queued-card"
    assert _no_real_push.payloads == []  # the poster pushes when it's done


def test_mid_score_likes_bounded_by_propose_top(monkeypatch, tmp_path, no_telegram):
    es = _scanner(monkeypatch, tmp_path)
    res = es.act_on_candidates([_cand(str(i), 3) for i in range(5)], propose_top=2)
    assert res["card_likes"] == 2
    assert len(list(es.QUEUE_DIR.glob("auto-like-*.json"))) == 2


def test_reply_needs_threshold_and_topic_still(monkeypatch, tmp_path, no_telegram):
    es = _scanner(monkeypatch, tmp_path)
    es.act_on_candidates([_cand("7", 7, "playwright stealth keeps failing on cloudflare"),
                          _cand("8", 5, "playwright stealth keeps failing on cloudflare")],
                         propose_top=3)
    assert (es.QUEUE_DIR / "auto-reply-7.json").exists()      # ≥7 + topic → reply
    assert not (es.QUEUE_DIR / "auto-reply-8.json").exists()  # 5: never a reply
    assert (es.QUEUE_DIR / "auto-like-8.json").exists()        # … a like instead


def test_like_cap_reached_no_action_one_info(monkeypatch, tmp_path, no_telegram,
                                              _no_real_push):
    es = _scanner(monkeypatch, tmp_path)
    audit = tmp_path / "audit" / f"actions-{es._today_iso()}.jsonl"
    audit.parent.mkdir(parents=True)
    audit.write_text("".join(json.dumps({"kind": "like", "status": "auto-queued"}) + "\n"
                             for _ in range(es.LIKE_PER_DAY)))
    res = es.act_on_candidates([_cand("1", 6), _cand("2", 3), _cand("3", 2)], propose_top=3)
    assert not es.QUEUE_DIR.exists() or not list(es.QUEUE_DIR.glob("*.json"))
    assert res["held"] == 3
    assert len(_no_real_push.payloads) == 1  # exactly one info
    info = _no_real_push.payloads[0]
    assert "işlemsiz" in info["title"] and "sınırı" in info["message"]
    assert info["click"] == "https://x.com/h1/status/1"


def test_crisis_freeze_blocks_every_action(monkeypatch, tmp_path, no_telegram, _no_real_push):
    es = _scanner(monkeypatch, tmp_path)
    es.FREEZE_FLAG.parent.mkdir(parents=True)
    es.FREEZE_FLAG.write_text("{}")
    res = es.act_on_candidates(
        [_cand("1", 9, "playwright stealth on cloudflare"), _cand("2", 3)], propose_top=3)
    assert res["crisis"] is True and res["auto_like"] == res["auto_reply"] == 0
    assert not list(es.QUEUE_DIR.glob("*.json"))
    assert len(_no_real_push.payloads) == 1
    assert "Kriz" in _no_real_push.payloads[0]["message"]


def test_off_limits_candidate_gets_nothing(monkeypatch, tmp_path, no_telegram):
    es = _scanner(monkeypatch, tmp_path)
    monkeypatch.setattr(es, "_off_limits", lambda text: "politics")
    es.act_on_candidates([_cand("1", 9), _cand("2", 3)], propose_top=3)
    assert not list(es.QUEUE_DIR.glob("*.json"))


# ── 4. poster: acts, then pushes the link; hard blocks still block ──

class _Tw:
    def __init__(self, tid="555"):
        self.id = tid

    async def favorite(self):
        return None


class _Client:
    def __init__(self):
        self.created = []

    def load_cookies(self, p):
        pass

    async def get_tweet_by_id(self, tid):
        return _Tw(tid)

    async def create_tweet(self, text=None, reply_to=None, media_ids=None):
        self.created.append(text)
        return _Tw("9001")


def _poster(monkeypatch, tmp_path):
    monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
    monkeypatch.setenv("CDPILOT_AUTO_POST", "on")
    pt = _fresh("poster_twikit")
    pt.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    pt.COOKIES_PATH = tmp_path / "cookies.json"
    pt.COOKIES_PATH.write_text("{}")
    client = _Client()
    monkeypatch.setattr(pt, "Client", lambda lang: client)
    monkeypatch.setattr(pt, "_tr_summary", lambda t: "özet")
    monkeypatch.setattr(pt, "_in_quiet_hours", lambda ts: False)
    return pt, client


def _q(pt, **item):
    item.setdefault("status", "pending")
    item.setdefault("scheduled_time", 1)
    (pt.QUEUE_DIR / f"{item['id']}.json").write_text(json.dumps(item))


def test_autonomous_like_executes_and_pushes_link(monkeypatch, tmp_path, no_telegram,
                                                  _no_real_push):
    pt, _ = _poster(monkeypatch, tmp_path)
    _q(pt, id="auto-like-555", kind="like", to="https://x.com/dev/status/555",
       context="auto-like (score 3, @dev)")
    asyncio.run(pt.main_async())
    assert (pt.POSTED_DIR / "auto-like-555.json").exists()
    p = _no_real_push.payloads[-1]
    assert p["title"] == "Beğenildi" and p["topic"] == "cdpilot-x"
    assert p["click"] == "https://x.com/dev/status/555" and p["priority"] == 2


def test_reply_push_opens_our_reply_and_offers_target(monkeypatch, tmp_path, no_telegram,
                                                      _no_real_push):
    pt, client = _poster(monkeypatch, tmp_path)
    _q(pt, id="pain-reply-77", kind="reply", to="https://x.com/dev/status/77",
       text="cookies expiring is usually the profile dir, not the site",
       approved_at=int(time.time()))
    asyncio.run(pt.main_async())
    p = _no_real_push.payloads[-1]
    assert p["title"] == "Cevap atıldı → @dev"
    assert p["click"] == "https://x.com/cdpilot_dev/status/9001"
    assert {"action": "view", "label": "Hedef tweet",
            "url": "https://x.com/dev/status/77"} in p["actions"]


def test_follow_push_opens_profile(monkeypatch, tmp_path, no_telegram, _no_real_push):
    pt, client = _poster(monkeypatch, tmp_path)

    class _U:
        id = "11"

    async def _gu(h):
        return _U()

    async def _fu(uid):
        return None

    client.get_user_by_screen_name = _gu
    client.follow_user = _fu
    _q(pt, id="follow-karpathy", kind="follow", to="karpathy")
    asyncio.run(pt.main_async())
    p = _no_real_push.payloads[-1]
    assert p["title"] == "Takip edildi" and p["click"] == "https://x.com/karpathy"


def test_duplicate_text_is_blocked_and_alarms(monkeypatch, tmp_path, no_telegram,
                                              _no_real_push):
    pt, client = _poster(monkeypatch, tmp_path)
    pt.POSTED_DIR.mkdir(parents=True, exist_ok=True)
    (pt.POSTED_DIR / "old.json").write_text(json.dumps(
        {"id": "old", "text": "same words", "posted_at": int(time.time())}))
    _q(pt, id="r-dup", kind="reply", to="https://x.com/d/status/1", text="same words")
    asyncio.run(pt.main_async())
    assert client.created == []  # hard block holds
    assert (pt.FAILED_DIR / "r-dup.json").exists()
    p = _no_real_push.payloads[-1]
    assert p["topic"] == "bekci" and "Tekrar" in p["title"]


def test_failure_alarm_not_held_after_routine_burst(monkeypatch, tmp_path, no_telegram,
                                                   _no_real_push):
    """5 routine pushes fill the window; a posting failure right after must
    still go out immediately, on bekci — never parked in the digest."""
    import _notify  # type: ignore
    for i in range(5):
        _notify.notify(f"Beğenildi {i}", "x")
    assert len(_no_real_push.payloads) == 5
    pt, client = _poster(monkeypatch, tmp_path)

    async def _fail(*a, **k):
        raise RuntimeError("403 forbidden")
    client.create_tweet = _fail
    _q(pt, id="r-fail", kind="reply", to="https://x.com/d/status/3", text="unique words here",
       approved_at=int(time.time()))
    asyncio.run(pt.main_async())
    assert (pt.FAILED_DIR / "r-fail.json").exists()
    p = _no_real_push.payloads[-1]
    assert len(_no_real_push.payloads) == 6  # delivered, not held
    assert p["topic"] == "bekci" and p["title"] == "Atım hatası"
    assert p["click"] == "https://x.com/d/status/3"
    # the other failure branch: X/twikit returns ok=False (no exception)
    _q(pt, id="r-bad", kind="reply", to="not-a-status", text="other unique words",
       approved_at=int(time.time()))
    asyncio.run(pt.main_async())
    assert (pt.FAILED_DIR / "r-bad.json").exists()
    assert len(_no_real_push.payloads) == 7
    assert _no_real_push.payloads[-1]["topic"] == "bekci"


def test_crisis_dm_is_an_alarm(no_telegram, _no_real_push):
    dm = _fresh("dm_handler")
    dm.notify_dm("x", "X", "threat", ["crisis_topic"], None)
    assert _no_real_push.payloads[-1]["topic"] == "bekci"
    dm.notify_dm("y", "Y", "hi", [], None)
    assert _no_real_push.payloads[-1]["topic"] == "cdpilot-x"


def test_auto_reply_never_twice_across_runs(monkeypatch, tmp_path, no_telegram):
    """Run 1 replies; the poster posts it and dequeues it. Run 2 (next day,
    different draft) must not reply to the same tweet again."""
    es = _scanner(monkeypatch, tmp_path)
    topic = "playwright stealth keeps failing on cloudflare"
    es.act_on_candidates([_cand("7", 8, topic)], propose_top=3)
    qf = es.QUEUE_DIR / "auto-reply-7.json"
    assert qf.exists()
    # poster posted it → queue file gone, posted/ has it
    (tmp_path / "posted").mkdir()
    (tmp_path / "posted" / qf.name).write_text(qf.read_text())
    qf.unlink()
    monkeypatch.setattr(es, "_ai_draft_for", lambda c: "a different second draft")
    monkeypatch.setattr(es, "_today_iso", lambda: "2099-01-01")  # new day, fresh caps
    res = es.act_on_candidates([_cand("7", 8, topic)], propose_top=3)
    assert res["auto_reply"] == 0 and not qf.exists()
    # even with posted/ wiped (archived elsewhere), the state file remembers
    (tmp_path / "posted" / qf.name).unlink()
    sys.modules.pop("engagement_scanner", None)
    es2 = _scanner(monkeypatch, tmp_path)
    assert es2.act_on_candidates([_cand("7", 8, topic)], propose_top=3)["auto_reply"] == 0
    assert "7" in json.loads(es2.REPLIED_STATE.read_text())


def test_auto_reply_skips_tweet_answered_by_other_path(monkeypatch, tmp_path, no_telegram):
    es = _scanner(monkeypatch, tmp_path)
    es.QUEUE_DIR.mkdir(parents=True)
    (es.QUEUE_DIR / "pain-reply-9.json").write_text(json.dumps(
        {"id": "pain-reply-9", "kind": "reply", "to": "https://x.com/h9/status/9"}))
    res = es.act_on_candidates([_cand("9", 8, "playwright stealth on cloudflare")], 3)
    assert res["auto_reply"] == 0
    assert not (es.QUEUE_DIR / "auto-reply-9.json").exists()


def test_poster_flushes_held_digest_each_run(monkeypatch, tmp_path, no_telegram,
                                             _no_real_push):
    import _notify  # type: ignore
    t0 = time.time() - 3600  # an hour ago: window long passed
    for i in range(6):
        _notify.notify(f"x{i}", "y", now=t0)
    assert len(_no_real_push.payloads) == 5
    pt, _ = _poster(monkeypatch, tmp_path)
    asyncio.run(pt.main_async())  # empty queue — still flushes
    assert _no_real_push.payloads[-1]["title"] == "cdpilot · 1 olay (özet)"


# ── 5. other former-Telegram paths: ntfy only, correct links ──

def test_mention_push_links_their_tweet(no_telegram, _no_real_push):
    ms = _fresh("mention_scraper")
    ms.notify_mention({"author": "@dev", "text": "how?", "is_reply_to_us": True,
                       "tweet_url": "https://x.com/dev/status/5"})
    p = _no_real_push.payloads[-1]
    assert p["title"] == "Yanıt: @dev" and p["click"] == "https://x.com/dev/status/5"


def test_dm_push_opens_conversation(no_telegram, _no_real_push):
    dm = _fresh("dm_handler")
    dm.notify_dm("stranger", "S", "hi", [], "123-456")
    p = _no_real_push.payloads[-1]
    assert p["click"] == "https://x.com/messages/123-456"
    assert p["actions"][1]["url"] == "https://x.com/stranger"


def test_grok_draft_waits_with_compose_link(monkeypatch, tmp_path, no_telegram,
                                            _no_real_push):
    monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
    gp = _fresh("grok_provocation")
    gp.cmd_propose(1)
    p = _no_real_push.payloads[-1]
    assert p["title"] == "Onay bekliyor: @grok sorusu"
    assert p["click"].startswith("https://x.com/intent/post?text=%40grok")
    assert not (tmp_path / "queue").exists()  # NOT posted unattended


def test_weekly_plan_waits(monkeypatch, tmp_path, no_telegram, _no_real_push):
    monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
    wr = _fresh("weekly_review")
    wr._send_waiting_notice("plan metni", "2026-W40")
    p = _no_real_push.payloads[-1]
    assert p["title"] == "Onay bekliyor: haftalık plan 2026-W40"
    assert "plan metni" in p["message"]


def test_follow_suggestion_and_pain_hits(monkeypatch, tmp_path, no_telegram, _no_real_push):
    monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
    fm = _fresh("follow_manager")
    fm._suggest_follow("karpathy", "ai")
    assert _no_real_push.payloads[-1]["click"] == "https://x.com/karpathy"
    ph = _fresh("pain_hunter")
    ph.notify_hits([{"author": "a", "text": "cookies keep expiring", "url": "https://x.com/a/status/1"},
                    {"author": "b", "text": "cdp hangs", "url": "https://x.com/b/status/2"}],
                   {"queued": 1, "rejected": 0})
    p = _no_real_push.payloads[-1]
    assert p["title"] == "Pain hunter: 2 sorun"
    assert p["click"] == "https://x.com/a/status/1"


# ── 6. static guard: Telegram lives only in the bridge + crisis fallback ──

_TELEGRAM_USE = re.compile(
    r"api\.telegram\.org|TELEGRAM_BRIDGE|telegram_bridge\.py|\btb\._api\(|\btb\._load_env\(|"
    r"_register_pending\(|TELEGRAM_CHAT_ID")


@pytest.mark.parametrize("path", sorted(p.name for p in OPS.glob("*.py")))
def test_no_telegram_outside_bridge_and_crisis(path):
    if path in ("telegram_bridge.py", "crisis_check.py"):
        pytest.skip("the bridge itself / crisis fallback (kept on purpose)")
    src = (OPS / path).read_text()
    hits = [m.group(0) for m in _TELEGRAM_USE.finditer(src)]
    assert hits == [], f"{path} still talks to Telegram: {hits}"


def test_crisis_keeps_telegram_as_last_resort(monkeypatch):
    """ntfy first; the bridge only when ntfy could not deliver (unchanged)."""
    import _notify  # type: ignore
    cc = _fresh("crisis_check")
    calls = []
    monkeypatch.setattr(_notify, "_deliver", lambda p: False)
    monkeypatch.setattr(cc.subprocess if hasattr(cc, "subprocess") else subprocess,
                        "run", lambda args, **k: calls.append(args))
    cc._telegram_send("kriz")
    assert calls and "telegram_bridge.py" in str(calls[0][1])

"""xbot tests — Feature A (thread poster, kind=thread) + Feature B (AUTO_POST
reply coverage: daily cap, staleness archive, quiet hours, post-notify).

Twikit is always mocked — no network. Run: pytest xbot/tests/ -v
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parent.parent / "ops"
sys.path.insert(0, str(OPS))


# ── helpers ──
class _FakeTweet:
  def __init__(self, tid: str) -> None:
    self.id = tid


class _FakeClient:
  """Records create_tweet calls; can fail at chosen call numbers (1-based)."""

  def __init__(self, base: int = 1000, fail_at: set[int] | None = None) -> None:
    self.base = base
    self.fail_at = fail_at or set()
    self.calls: list[dict] = []
    self._n = 0

  def load_cookies(self, path: str) -> None:
    pass

  async def create_tweet(self, text: str = "", reply_to: str | None = None,
                         media_ids: list | None = None) -> _FakeTweet:
    self._n += 1
    if self._n in self.fail_at:
      raise RuntimeError(f"boom at call {self._n}")
    self.calls.append({"text": text, "reply_to": reply_to})
    return _FakeTweet(str(self.base + self._n))


def _setup_poster(monkeypatch, tmp_path, auto_post: str = "on"):
  """Fresh poster_twikit module rooted at tmp_path with telegram/claude mocked."""
  monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
  monkeypatch.setenv("CDPILOT_AUTO_POST", auto_post)
  sys.modules.pop("poster_twikit", None)
  import poster_twikit as pt  # type: ignore
  pt.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
  pt.COOKIES_PATH = tmp_path / "cookies" / "c.json"
  pt.COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
  pt.COOKIES_PATH.write_text("{}")
  notes: list[str] = []
  monkeypatch.setattr(pt, "_telegram_notify", lambda t: notes.append(t))
  monkeypatch.setattr(pt, "_tr_summary", lambda t: "TR özet")
  monkeypatch.setattr(pt, "_humanized_gap", lambda *a, **k: 0.0)
  monkeypatch.setattr(pt, "_in_quiet_hours", lambda ts: False)
  return pt, notes


def _queue_item(pt, item: dict) -> Path:
  p = pt.QUEUE_DIR / f"{item['id']}.json"
  p.write_text(json.dumps(item, ensure_ascii=False))
  return p


THREAD_TEXTS = ["root tweet of the chain", "second tweet", "third tweet"]


def _thread_item(**over) -> dict:
  item = {"id": "th-1", "kind": "thread", "texts": list(THREAD_TEXTS),
          "status": "pending", "scheduled_time": 1}
  item.update(over)
  return item


def _reply_item(**over) -> dict:
  item = {"id": "r-1", "kind": "reply", "to": "https://x.com/u/status/555",
          "text": "cool reply", "status": "pending", "scheduled_time": 1}
  item.update(over)
  return item


# ── Feature A: _humanized_gap ──
def test_humanized_gap_within_range():
  sys.modules.pop("poster_twikit", None)
  import poster_twikit as pt  # type: ignore
  samples = [pt._humanized_gap() for _ in range(300)]
  assert all(20.0 <= s <= 90.0 for s in samples)
  # Gaussian-ish: mass concentrates mid-range, not at the clamp edges
  mean = sum(samples) / len(samples)
  assert 45.0 <= mean <= 65.0


# ── Feature A: thread chain posting ──
def test_thread_posts_full_chain_in_reply_order(monkeypatch, tmp_path):
  import asyncio
  pt, notes = _setup_poster(monkeypatch, tmp_path)
  fake = _FakeClient()
  monkeypatch.setattr(pt, "Client", lambda lang: fake)
  qp = _queue_item(pt, _thread_item())

  asyncio.run(pt.main_async())

  # 3 tweets, chained: root has no reply_to, each next replies to previous id
  assert [c["text"] for c in fake.calls] == THREAD_TEXTS
  assert [c["reply_to"] for c in fake.calls] == [None, "1001", "1002"]
  assert not qp.exists()  # moved out of queue
  posted = json.loads((pt.POSTED_DIR / "th-1.json").read_text())
  assert posted["status"] == "posted"
  assert posted["tweet_url"].endswith("/1001")  # root tweet url
  assert posted["posted_ids"] == ["1001", "1002", "1003"]
  assert posted["tweet_ids"] == ["1001", "1002", "1003"]
  assert posted["last_posted_index"] == 2
  assert posted["thread_count"] == 3
  # Post-notify reuses the ✅ + link + TR özet path
  assert any("Thread atıldı (3 tweet)" in n and "/1001" in n and "TR özet" in n
             for n in notes)


def test_thread_humanized_gap_between_tweets_only(monkeypatch, tmp_path):
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path)
  calls = {"n": 0}

  def _gap(*a, **k):
    calls["n"] += 1
    return 0.0
  monkeypatch.setattr(pt, "_humanized_gap", _gap)
  monkeypatch.setattr(pt, "Client", lambda lang: _FakeClient())
  _queue_item(pt, _thread_item())

  asyncio.run(pt.main_async())
  assert calls["n"] == 2  # 3 tweets → 2 gaps, none before the root


def test_thread_midchain_failure_persists_partial_then_resumes(monkeypatch, tmp_path):
  import asyncio
  pt, notes = _setup_poster(monkeypatch, tmp_path)
  fake1 = _FakeClient(base=1000, fail_at={2})  # 2nd create_tweet blows up
  monkeypatch.setattr(pt, "Client", lambda lang: fake1)
  qp = _queue_item(pt, _thread_item())

  asyncio.run(pt.main_async())

  # Progress persisted in the QUEUE file — not moved to failed/
  assert qp.exists()
  part = json.loads(qp.read_text())
  assert part["status"] == "partial"
  assert part["posted_ids"] == ["1001"]
  assert part["last_posted_index"] == 0
  assert "boom" in part["error"]
  assert not (pt.FAILED_DIR / "th-1.json").exists()
  assert any("kısmi" in n for n in notes)

  # Second run RESUMES: no re-post of the root, chain continues off 1001
  fake2 = _FakeClient(base=2000)
  monkeypatch.setattr(pt, "Client", lambda lang: fake2)
  asyncio.run(pt.main_async())

  assert [c["text"] for c in fake2.calls] == THREAD_TEXTS[1:]
  assert [c["reply_to"] for c in fake2.calls] == ["1001", "2001"]
  assert not qp.exists()
  posted = json.loads((pt.POSTED_DIR / "th-1.json").read_text())
  assert posted["status"] == "posted"
  assert posted["posted_ids"] == ["1001", "2001", "2002"]
  assert posted["tweet_url"].endswith("/1001")  # root url survives the resume


def test_thread_rejects_single_text(monkeypatch, tmp_path):
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path)
  monkeypatch.setattr(pt, "Client", lambda lang: _FakeClient())
  _queue_item(pt, _thread_item(texts=["only one"]))

  asyncio.run(pt.main_async())
  failed = json.loads((pt.FAILED_DIR / "th-1.json").read_text())
  assert failed["status"] == "failed"
  assert "thread needs >=2" in failed["error"]


def test_thread_deferred_in_quiet_hours(monkeypatch, tmp_path):
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path)
  monkeypatch.setattr(pt, "_in_quiet_hours", lambda ts: True)

  def _no_client(lang):
    raise AssertionError("client must not be built — nothing due")
  monkeypatch.setattr(pt, "Client", _no_client)
  qp = _queue_item(pt, _thread_item())

  asyncio.run(pt.main_async())
  assert qp.exists()
  assert json.loads(qp.read_text())["status"] == "pending"


def test_queue_draft_carries_thread_texts(monkeypatch, tmp_path):
  monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
  monkeypatch.setenv("CDPILOT_QUEUE_RSYNC", "")
  sys.modules.pop("telegram_bridge", None)
  import telegram_bridge as tb  # type: ignore
  draft = {"id": "th-q", "kind": "thread", "texts": list(THREAD_TEXTS),
           "context": "t", "source": "faz5-bench-journey"}
  qp = tb.auto_queue_draft(draft)
  item = json.loads(qp.read_text())
  assert item["kind"] == "thread"
  assert item["texts"] == THREAD_TEXTS
  assert item["status"] == "pending"
  assert item["source"] == "faz5-bench-journey"
  # Hot-zone scheduler applied (thread treated like a tweet: peak window,
  # never inside the 23:00-08:00 TR quiet window)
  import datetime as _dt
  tr = _dt.datetime.utcfromtimestamp(item["scheduled_time"] + 3 * 3600)
  assert not (tr.hour >= 23 or tr.hour < 8)


# ── Feature B: staleness gate ──
def test_stale_reply_archived_not_posted(monkeypatch, tmp_path):
  import asyncio
  pt, notes = _setup_poster(monkeypatch, tmp_path)
  fake = _FakeClient()
  monkeypatch.setattr(pt, "Client", lambda lang: fake)
  old = int(time.time()) - 72 * 3600  # 72h > 48h gate
  qp = _queue_item(pt, _reply_item(target_created_ts=old))

  asyncio.run(pt.main_async())

  assert fake.calls == []  # never posted
  assert not qp.exists()
  arch = json.loads((pt.ARCHIVE_DIR / "r-1.json").read_text())
  assert arch["status"] == "stale"
  assert arch["archived_at"] > 0
  assert any("bayat" in n and "arşivlendi" in n for n in notes)
  assert not pt.AUTO_REPLY_COUNT_FILE.exists()  # archive ≠ auto-post


def test_fresh_reply_autoposted_counted_and_notified(monkeypatch, tmp_path):
  import asyncio
  pt, notes = _setup_poster(monkeypatch, tmp_path)
  fake = _FakeClient()
  monkeypatch.setattr(pt, "Client", lambda lang: fake)
  fresh = int(time.time()) - 3600
  _queue_item(pt, _reply_item(target_created_ts=fresh))

  asyncio.run(pt.main_async())

  assert len(fake.calls) == 1
  posted = json.loads((pt.POSTED_DIR / "r-1.json").read_text())
  assert posted["status"] == "posted"
  # Daily counter persisted in state/
  rec = json.loads(pt.AUTO_REPLY_COUNT_FILE.read_text())
  assert rec == {"date": time.strftime("%Y-%m-%d"), "count": 1}
  # Existing post-notify path reused: ✅ + link + TR özet
  assert any("Cevap atıldı" in n and posted["tweet_url"] in n and "TR özet" in n
             for n in notes)


def test_reply_without_timestamps_treated_fresh(monkeypatch, tmp_path):
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path)
  fake = _FakeClient()
  monkeypatch.setattr(pt, "Client", lambda lang: fake)
  _queue_item(pt, _reply_item())  # no target_created_ts/created_at/approved_at

  asyncio.run(pt.main_async())
  assert len(fake.calls) == 1  # unknown age → posted, not archived


# ── Feature B: daily cap ──
def test_auto_reply_daily_cap_defers(monkeypatch, tmp_path):
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path)
  fake = _FakeClient()
  monkeypatch.setattr(pt, "Client", lambda lang: fake)
  pt.AUTO_REPLY_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
  pt.AUTO_REPLY_COUNT_FILE.write_text(
    json.dumps({"date": time.strftime("%Y-%m-%d"), "count": 6}))
  fresh = int(time.time()) - 600
  qp = _queue_item(pt, _reply_item(target_created_ts=fresh))

  asyncio.run(pt.main_async())

  assert fake.calls == []  # cap reached → deferred, not posted
  assert qp.exists()
  assert json.loads(qp.read_text())["status"] == "pending"  # stays for later


def test_auto_reply_cap_allows_only_remaining_budget(monkeypatch, tmp_path):
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path)
  fake = _FakeClient()
  monkeypatch.setattr(pt, "Client", lambda lang: fake)
  pt.AUTO_REPLY_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
  pt.AUTO_REPLY_COUNT_FILE.write_text(
    json.dumps({"date": time.strftime("%Y-%m-%d"), "count": 5}))
  fresh = int(time.time()) - 600
  _queue_item(pt, _reply_item(id="r-a", target_created_ts=fresh))
  _queue_item(pt, _reply_item(id="r-b", to="https://x.com/u/status/556",
                              target_created_ts=fresh))

  asyncio.run(pt.main_async())

  assert len(fake.calls) == 1  # only 1 slot left under the 6/day cap
  rec = json.loads(pt.AUTO_REPLY_COUNT_FILE.read_text())
  assert rec["count"] == 6
  remaining = sorted(p.name for p in pt.QUEUE_DIR.glob("*.json"))
  assert len(remaining) == 1  # the other one deferred in place


def test_auto_reply_counter_resets_on_new_day(monkeypatch, tmp_path):
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path)
  fake = _FakeClient()
  monkeypatch.setattr(pt, "Client", lambda lang: fake)
  pt.AUTO_REPLY_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
  pt.AUTO_REPLY_COUNT_FILE.write_text(
    json.dumps({"date": "2000-01-01", "count": 6}))  # yesterday's cap
  _queue_item(pt, _reply_item(target_created_ts=int(time.time()) - 600))

  asyncio.run(pt.main_async())
  assert len(fake.calls) == 1
  rec = json.loads(pt.AUTO_REPLY_COUNT_FILE.read_text())
  assert rec == {"date": time.strftime("%Y-%m-%d"), "count": 1}


# ── Feature B: quiet hours + AUTO_POST=off ──
def test_quiet_hours_defers_auto_reply(monkeypatch, tmp_path):
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path)
  monkeypatch.setattr(pt, "_in_quiet_hours", lambda ts: True)

  def _no_client(lang):
    raise AssertionError("client must not be built — nothing due")
  monkeypatch.setattr(pt, "Client", _no_client)
  qp = _queue_item(pt, _reply_item(target_created_ts=int(time.time()) - 600))

  asyncio.run(pt.main_async())
  assert qp.exists()  # deferred in place, untouched


def test_auto_post_off_keeps_legacy_reply_behavior(monkeypatch, tmp_path):
  """AUTO_POST=off → guardrails inactive: even a stale approved reply posts
  exactly like before (no archive, no counter)."""
  import asyncio
  pt, _ = _setup_poster(monkeypatch, tmp_path, auto_post="off")
  fake = _FakeClient()
  monkeypatch.setattr(pt, "Client", lambda lang: fake)
  old = int(time.time()) - 72 * 3600
  _queue_item(pt, _reply_item(target_created_ts=old))

  asyncio.run(pt.main_async())

  assert len(fake.calls) == 1  # posted — legacy path unchanged
  assert not pt.ARCHIVE_DIR.exists() or not list(pt.ARCHIVE_DIR.glob("*.json"))
  assert not pt.AUTO_REPLY_COUNT_FILE.exists()
  assert (pt.POSTED_DIR / "r-1.json").exists()


def test_in_quiet_hours_tr_window():
  sys.modules.pop("poster_twikit", None)
  import poster_twikit as pt  # type: ignore
  import calendar

  def _ts(hour: int) -> float:
    # Build a UTC ts whose TR (+3) local hour == hour
    return calendar.timegm((2026, 8, 20, (hour - 3) % 24, 30, 0, 0, 0, 0))
  assert pt._in_quiet_hours(_ts(23)) is True
  assert pt._in_quiet_hours(_ts(3)) is True
  assert pt._in_quiet_hours(_ts(7)) is True
  assert pt._in_quiet_hours(_ts(8)) is False
  assert pt._in_quiet_hours(_ts(14)) is False
  assert pt._in_quiet_hours(_ts(22)) is False


# ── Feature B: mention card (aireply) auto-queue — no approval card ──
def _fake_reply_drafter(monkeypatch, draft_text: str, fallback: bool = False):
  import types
  mod = types.ModuleType("reply_drafter")

  def draft(text, parent=None, author=None, lang="en"):
    return {"draft": draft_text, "fallback": fallback}
  mod.draft = draft  # type: ignore[attr-defined]
  monkeypatch.setitem(sys.modules, "reply_drafter", mod)


def test_mention_card_auto_post_queues_aireply_without_card(monkeypatch, tmp_path):
  monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
  monkeypatch.setenv("CDPILOT_AUTO_POST", "on")
  monkeypatch.setenv("CDPILOT_QUEUE_RSYNC", "")
  sys.modules.pop("telegram_bridge", None)
  import telegram_bridge as tb  # type: ignore
  _fake_reply_drafter(monkeypatch, "raw CDP handles the iframe case natively")

  def _no_card(*a, **k):
    raise AssertionError("Telegram API must NOT be called in AUTO_POST mode")
  monkeypatch.setattr(tb, "_api", _no_card)
  monkeypatch.setattr(tb, "_load_env", _no_card)

  created = int(time.time()) - 3600
  mention = {"tweet_id": "777", "author": "@dev", "text": "does it handle iframes?",
             "tweet_url": "https://x.com/dev/status/777", "created_at": created,
             "is_reply_to_us": True}
  mp = tmp_path / "mention.json"
  mp.write_text(json.dumps(mention))

  tb.cmd_incoming_reply(str(mp))

  qf = tmp_path / "queue" / "aireply-to-777.json"
  assert qf.exists()
  item = json.loads(qf.read_text())
  assert item["kind"] == "reply"
  assert item["to"] == "https://x.com/dev/status/777"
  assert item["text"] == "raw CDP handles the iframe case natively"
  assert item["target_created_ts"] == created  # staleness gate input
  assert item["source"] == "mention_auto"
  assert item["status"] == "pending"


def test_mention_card_auto_post_skips_when_no_draft(monkeypatch, tmp_path, capsys):
  monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
  monkeypatch.setenv("CDPILOT_AUTO_POST", "on")
  sys.modules.pop("telegram_bridge", None)
  import telegram_bridge as tb  # type: ignore
  _fake_reply_drafter(monkeypatch, "", fallback=True)  # drafter fell back → no draft

  def _no_card(*a, **k):
    raise AssertionError("no Telegram call expected")
  monkeypatch.setattr(tb, "_api", _no_card)
  monkeypatch.setattr(tb, "_load_env", _no_card)

  mp = tmp_path / "mention.json"
  mp.write_text(json.dumps({"tweet_id": "888", "author": "@dev", "text": "gm",
                            "tweet_url": "https://x.com/dev/status/888",
                            "created_at": int(time.time())}))
  tb.cmd_incoming_reply(str(mp))

  assert not (tmp_path / "queue" / "aireply-to-888.json").exists()
  out = json.loads(capsys.readouterr().out.strip())
  assert out["auto_post"] == "skip_no_draft"


def test_mention_card_off_still_sends_card(monkeypatch, tmp_path):
  """AUTO_POST=off → legacy approval card flow untouched."""
  monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
  monkeypatch.setenv("CDPILOT_AUTO_POST", "off")
  sys.modules.pop("telegram_bridge", None)
  import telegram_bridge as tb  # type: ignore
  _fake_reply_drafter(monkeypatch, "some ai draft")
  monkeypatch.setattr(tb, "_load_env", lambda: {"TELEGRAM_BOT_TOKEN": "t",
                                                "TELEGRAM_CHAT_ID": "1"})
  sent = {}

  def _fake_api(env, method, params=None, timeout=30):
    sent["method"] = method
    return {"message_id": 42}
  monkeypatch.setattr(tb, "_api", _fake_api)

  mp = tmp_path / "mention.json"
  mp.write_text(json.dumps({"tweet_id": "999", "author": "@dev", "text": "nice, how?",
                            "tweet_url": "https://x.com/dev/status/999",
                            "created_at": int(time.time())}))
  tb.cmd_incoming_reply(str(mp))

  assert sent["method"] == "sendMessage"  # card WAS sent
  assert not (tmp_path / "queue").exists() or \
      not list((tmp_path / "queue").glob("aireply-*.json"))


# ── Feature B: search_respond drafts carry the target timestamp ──
def test_search_reply_draft_carries_target_created_ts(monkeypatch, tmp_path):
  monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
  monkeypatch.setenv("CDPILOT_AUTO_POST", "on")
  monkeypatch.setenv("CDPILOT_QUEUE_RSYNC", "")
  sys.modules.pop("telegram_bridge", None)
  sys.modules.pop("search_respond", None)
  import search_respond as sr  # type: ignore
  created = time.time() - 7200
  c = {"tweet_id": "4242", "url": "https://x.com/q/status/4242",
       "author": "quester", "created_ts": created}
  res = sr._auto_queue_reply(c, "direct CDP sidesteps that entirely", 0)
  assert res["queued"] is True
  item = json.loads(Path(res["queue_path"]).read_text())
  assert item["kind"] == "reply"
  assert item["target_created_ts"] == int(created)
  assert item["source"] == "search_respond"


if __name__ == "__main__":
  sys.exit(pytest.main([__file__, "-v"]))

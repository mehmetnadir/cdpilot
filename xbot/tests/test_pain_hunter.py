"""tests/test_pain_hunter.py — ops/pain_hunter.py, no network.

Every test injects a fake reply_drafter.generate / _novelty.check rather than
calling a model or hitting X — the twikit search path (_get_client/_search_one/
main_async) is exercised only by manual/staging runs, per the task's "ağ yok
testlerde" rule. twikit itself is never imported at module import time (see
pain_hunter._get_client), so this file runs on a Mac with no twikit installed.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))


def _ph(tmp_path, monkeypatch):
    monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
    sys.modules.pop("pain_hunter", None)
    ph = importlib.import_module("pain_hunter")
    ph.DATA = tmp_path
    ph.STATE = tmp_path / "state"
    ph.PAINS_DIR = tmp_path / "pains"
    ph.DRAFTS_DIR = tmp_path / "drafts"
    ph.CURSOR_PATH = ph.STATE / "pain-cursor.json"
    ph.SEEN_PATH = ph.PAINS_DIR / "seen.json"
    return ph


# ── cursor rotation ──

def test_cursor_rotates_and_wraps(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)
    queries = [{"q": f"q{i}"} for i in range(8)]
    cursor = tmp_path / "state" / "pain-cursor.json"

    first = ph.next_queries(queries, cursor, n=6)
    assert [q["q"] for q in first] == ["q0", "q1", "q2", "q3", "q4", "q5"]

    second = ph.next_queries(queries, cursor, n=6)
    assert [q["q"] for q in second] == ["q6", "q7", "q0", "q1", "q2", "q3"]


def test_cursor_dry_run_does_not_advance(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)
    queries = [{"q": f"q{i}"} for i in range(8)]
    cursor = tmp_path / "state" / "pain-cursor.json"

    a = ph.next_queries(queries, cursor, n=6, persist=False)
    b = ph.next_queries(queries, cursor, n=6, persist=False)
    assert [q["q"] for q in a] == [q["q"] for q in b]
    assert not cursor.exists()


# ── filters ──

def _cand(**kw):
    base = {"tweet_id": "1", "url": "https://x.com/someone/status/1", "author": "someone",
            "text": "this is a real complaint about my current setup breaking during automation runs",
            "hours_old": 1.0, "created_ts": time.time()}
    base.update(kw)
    return base


def test_filter_rejects_self():
    from pain_hunter import passes_filters, HANDLE
    ok, reason = passes_filters(_cand(author=HANDLE), {}, [], set(), time.time())
    assert not ok and reason == "self"


def test_filter_rejects_retweet():
    from pain_hunter import passes_filters
    ok, reason = passes_filters(_cand(text="RT @someone: check this out this is a long body"),
                                 {}, [], set(), time.time())
    assert not ok and reason == "retweet"


def test_filter_rejects_stale():
    from pain_hunter import passes_filters
    ok, reason = passes_filters(_cand(hours_old=40.0), {}, [], set(), time.time())
    assert not ok and reason == "stale"


def test_filter_rejects_link_only_body():
    from pain_hunter import passes_filters
    ok, reason = passes_filters(_cand(text="https://t.co/abc123"), {}, [], set(), time.time())
    assert not ok and reason == "link-only"


def test_filter_rejects_negative_term():
    from pain_hunter import passes_filters
    ok, reason = passes_filters(
        _cand(text="I switched from CloakBrowser and never looked back honestly"),
        {}, ["cloakbrowser"], set(), time.time())
    assert not ok and reason == "competitor-noise"


def test_filter_rejects_negative_author():
    from pain_hunter import passes_filters
    ok, reason = passes_filters(_cand(author="browser_use"), {}, [], {"browser_use"}, time.time())
    assert not ok and reason == "competitor-noise"


def test_filter_rejects_off_limits():
    from pain_hunter import passes_filters
    ok, reason = passes_filters(
        _cand(text="sure, but the election proves the working class was duped again"),
        {}, [], set(), time.time())
    assert not ok and reason.startswith("off-limits")


def test_filter_rejects_seen():
    from pain_hunter import passes_filters
    now = time.time()
    ok, reason = passes_filters(_cand(tweet_id="42"), {"42": now}, [], set(), now)
    assert not ok and reason == "seen"


def test_filter_no_follower_floor():
    """MIN_FOLLOWERS (search_respond.py) filters out exactly the small accounts
    that write real complaints — pain_hunter has no such field at all."""
    from pain_hunter import passes_filters
    tiny = _cand(text="day 3 building this in public, sessions keep expiring and cookies get lost")
    tiny["author_followers"] = 32
    ok, reason = passes_filters(tiny, {}, [], set(), time.time())
    assert ok, reason


# ── classification validator ──

def _classes():
    return {
        "session_cookie_persistence": {
            "cdpilot_answer": "cdpilot cookies save/load, cdpilot cookies auto on",
            "missing": None,
        },
        "iframe_support": {"cdpilot_answer": None, "missing": "iframe interaction"},
    }


def _valid_obj(**over):
    obj = {"first_person_pain": True, "class": "session_cookie_persistence",
           "pain": "cookies keep expiring", "solvable_now": True,
           "command": "cdpilot cookies save --host x.com", "missing_capability": None}
    obj.update(over)
    return obj


def test_validator_accepts_real_command():
    from pain_hunter import make_classification_validator
    validate = make_classification_validator(_classes())
    _, issues = validate(json.dumps(_valid_obj()))
    assert issues == []


def test_validator_rejects_fabricated_command():
    from pain_hunter import make_classification_validator
    validate = make_classification_validator(_classes())
    _, issues = validate(json.dumps(_valid_obj(command="cdpilot vision-solve")))
    assert issues and any("unknown command" in i for i in issues)


def test_validator_rejects_unknown_class():
    from pain_hunter import make_classification_validator
    validate = make_classification_validator(_classes())
    _, issues = validate(json.dumps(_valid_obj(**{"class": "made-up-class"})))
    assert issues and any("unknown class" in i for i in issues)


def test_validator_rejects_missing_keys():
    from pain_hunter import make_classification_validator
    validate = make_classification_validator(_classes())
    _, issues = validate(json.dumps({"first_person_pain": True}))
    assert issues and any("missing key" in i for i in issues)


def test_validator_rejects_invalid_json():
    from pain_hunter import make_classification_validator
    validate = make_classification_validator(_classes())
    _, issues = validate("not json at all")
    assert issues == ["invalid json"]


def test_validator_allows_null_command_for_missing_capability():
    from pain_hunter import make_classification_validator
    validate = make_classification_validator(_classes())
    obj = _valid_obj(**{"class": "iframe_support", "solvable_now": False,
                         "command": None, "missing_capability": "iframe interaction"})
    _, issues = validate(json.dumps(obj))
    assert issues == []


# ── classify_candidates: dry-run writes nothing ──

def test_classify_candidates_dry_run_writes_no_ledger(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)

    def fake_generate(system_prompt, user_prompt, timeout=60, validate=None, max_tokens=250):
        obj = _valid_obj()
        text = json.dumps(obj)
        if validate:
            _, issues = validate(text)
            assert not issues
        return {"text": text, "engine": "fake", "model": "fake"}

    monkeypatch.setattr(ph.reply_drafter, "generate", fake_generate)
    survivors = [_cand(tweet_id="7", url="https://x.com/u/status/7")]
    classified, unclassified = ph.classify_candidates(survivors, _classes(), time.time(), dry_run=True)
    assert len(classified) == 1 and unclassified == 0
    assert not ph.PAINS_DIR.exists() or not list(ph.PAINS_DIR.glob("*.jsonl"))


def test_classify_candidates_writes_ledger_when_not_dry_run(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)

    def fake_generate(system_prompt, user_prompt, timeout=60, validate=None, max_tokens=250):
        return {"text": json.dumps(_valid_obj()), "engine": "fake"}

    monkeypatch.setattr(ph.reply_drafter, "generate", fake_generate)
    survivors = [_cand(tweet_id="9", url="https://x.com/u/status/9")]
    ph.classify_candidates(survivors, _classes(), time.time(), dry_run=False)
    rows = ph.iter_ledger(days=7)
    assert len(rows) == 1 and rows[0]["tweet_id"] == "9"


def test_classify_candidates_unclassified_on_all_engines_down(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)

    def fake_generate(system_prompt, user_prompt, timeout=60, validate=None, max_tokens=250):
        return {"text": None, "engine": None, "fallback": True, "errors": ["claude-timeout", "nim-no-key"]}

    monkeypatch.setattr(ph.reply_drafter, "generate", fake_generate)
    survivors = [_cand(tweet_id="11")]
    classified, unclassified = ph.classify_candidates(survivors, _classes(), time.time(), dry_run=False)
    assert classified == [] and unclassified == 1
    rows = ph.iter_ledger(days=7)
    assert rows[0]["classification"] is None


# ── reply pipeline: daily cap + mention budget ──

def _pain_cand(idx, mentions_used_in_draft=False):
    return {
        "tweet_id": f"p{idx}", "url": f"https://x.com/u/status/p{idx}",
        "author": f"user{idx}", "created_ts": time.time() - idx,
        "classification": {"first_person_pain": True, "class": "session_cookie_persistence",
                            "pain": "x", "solvable_now": True,
                            "command": "cdpilot cookies save --host x.com",
                            "missing_capability": None},
    }


def test_daily_cap_stops_at_three(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)
    ph.DAILY_REPLY_CAP = 3

    def fake_generate(system_prompt, user_prompt, timeout=90, validate=None, max_tokens=220):
        text = "yeah, the retry backoff usually clears that up.. did the failures cluster around one endpoint?"
        if validate:
            text, issues = validate(text)
            assert not issues
        return {"text": text, "engine": "fake"}

    monkeypatch.setattr(ph.reply_drafter, "generate", fake_generate)

    import telegram_bridge as tb  # type: ignore
    monkeypatch.setattr(tb, "auto_post_enabled", lambda: False)

    candidates = [_pain_cand(i) for i in range(5)]
    stats = ph.run_replies(candidates, dry_run=False)
    assert stats["drafts_written"] == 3
    assert len(list(ph.DRAFTS_DIR.glob("*.json"))) == 3


def test_mention_budget_allows_only_one_per_day(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)
    ph.DAILY_REPLY_CAP = 3
    ph.CDPILOT_MENTION_BUDGET = 1

    calls = {"n": 0}

    def fake_generate(system_prompt, user_prompt, timeout=90, validate=None, max_tokens=220):
        calls["n"] += 1
        # every draft mentions cdpilot — the budget must reject all but one
        text = "cdpilot cookies auto on fixes exactly this.. what's your retry count today?"
        if validate:
            text, issues = validate(text)
            assert not issues
        return {"text": text, "engine": "fake"}

    monkeypatch.setattr(ph.reply_drafter, "generate", fake_generate)

    import telegram_bridge as tb  # type: ignore
    monkeypatch.setattr(tb, "auto_post_enabled", lambda: False)

    candidates = [_pain_cand(i) for i in range(3)]
    stats = ph.run_replies(candidates, dry_run=False)
    assert stats["drafts_written"] == 1
    assert stats["rejected"] == 2
    rows = ph.iter_ledger(days=7)
    reasons = [r.get("reason") for r in rows if r.get("event") == "draft_rejected"]
    assert any("mention budget" in r for r in reasons)


# ── lint-rejected draft never queued, always logged ──

def test_lint_rejected_draft_not_queued_but_logged(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)

    def fake_generate(system_prompt, user_prompt, timeout=90, validate=None, max_tokens=220):
        # Simulate every engine failing voice-lint (leaked prompt text) —
        # reply_drafter.generate() itself would return this shape once no
        # engine's draft survives `validate`.
        return {"text": None, "engine": None, "fallback": True,
                "errors": ["claude-lint:leaked prompt text"]}

    monkeypatch.setattr(ph.reply_drafter, "generate", fake_generate)

    import telegram_bridge as tb  # type: ignore
    monkeypatch.setattr(tb, "auto_post_enabled", lambda: False)

    candidates = [_pain_cand(0)]
    stats = ph.run_replies(candidates, dry_run=False)
    assert stats["rejected"] == 1
    assert stats["drafts_written"] == 0
    assert not list(ph.DRAFTS_DIR.glob("*.json")) if ph.DRAFTS_DIR.exists() else True
    rows = ph.iter_ledger(days=7)
    assert rows and rows[0]["event"] == "draft_rejected"
    assert "leaked prompt text" in rows[0]["reason"]


def test_model_skip_rejected_and_logged(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)

    def fake_generate(system_prompt, user_prompt, timeout=90, validate=None, max_tokens=220):
        return {"text": None, "engine": "claude", "skip": True, "fallback": False}

    monkeypatch.setattr(ph.reply_drafter, "generate", fake_generate)
    import telegram_bridge as tb  # type: ignore
    monkeypatch.setattr(tb, "auto_post_enabled", lambda: False)

    stats = ph.run_replies([_pain_cand(0)], dry_run=False)
    assert stats["rejected"] == 1
    rows = ph.iter_ledger(days=7)
    assert rows[0]["reason"] == "model skip"


# ── dry-run writes nothing at all ──

def test_run_replies_dry_run_writes_no_files(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)

    def fake_generate(system_prompt, user_prompt, timeout=90, validate=None, max_tokens=220):
        text = "fair — what's the actual failure mode, timeout or a hard 403?"
        if validate:
            text, issues = validate(text)
            assert not issues
        return {"text": text, "engine": "fake"}

    monkeypatch.setattr(ph.reply_drafter, "generate", fake_generate)
    import telegram_bridge as tb  # type: ignore
    monkeypatch.setattr(tb, "auto_post_enabled", lambda: True)
    queued = []
    monkeypatch.setattr(tb, "auto_queue_draft", lambda draft, idx=0: queued.append(draft))

    stats = ph.run_replies([_pain_cand(0), _pain_cand(1)], dry_run=True)
    assert stats["queued"] == 2
    assert queued == []  # dry-run must never actually call auto_queue_draft
    assert not ph.PAINS_DIR.exists() or not list(ph.PAINS_DIR.glob("daily-*.json"))
    assert not ph.PAINS_DIR.exists() or not list(ph.PAINS_DIR.glob("*.jsonl"))


# ── digest ──

def test_digest_aggregates_classes_and_first_person_ratio(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)
    now = time.time()
    rows = [
        {"ts": now, "url": "https://x.com/a/status/1", "query": "my cookies keep expiring every run",
         "classification": {"class": "session_cookie_persistence", "first_person_pain": True,
                             "missing_capability": None}},
        {"ts": now, "url": "https://x.com/b/status/2", "query": "cloudflare keeps blocking my bot",
         "classification": {"class": "headless_detection_anti_bot", "first_person_pain": True,
                             "missing_capability": None}},
        {"ts": now, "url": "https://x.com/c/status/3", "query": "iframe automation is a nightmare",
         "classification": {"class": "iframe_support", "first_person_pain": False,
                             "missing_capability": "iframe element interaction"}},
        {"ts": now, "url": "https://x.com/d/status/4", "query": "iframe automation is a nightmare",
         "classification": {"class": "iframe_support", "first_person_pain": False,
                             "missing_capability": "iframe element interaction"}},
    ]
    for r in rows:
        ph.append_ledger(r)

    digest = ph.build_digest(days=7)
    assert digest["total"] == 4
    assert digest["class_counts"]["iframe_support"] == 2
    assert digest["first_person"] == 2
    assert digest["first_person_ratio"] == 0.5
    assert digest["missing_capabilities"]["iframe element interaction"]["count"] == 2
    assert len(digest["missing_capabilities"]["iframe element interaction"]["example_urls"]) == 2
    top_q = dict(digest["top_queries"])
    assert top_q.get("iframe automation is a nightmare") == 2


def test_digest_excludes_reply_pipeline_events(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)
    now = time.time()
    ph.append_ledger({"ts": now, "event": "draft_rejected", "reason": "x"})
    ph.append_ledger({"ts": now, "event": "draft_accepted", "text": "y"})
    ph.append_ledger({"ts": now, "url": "https://x.com/a/status/1", "query": "q",
                       "classification": {"class": "shadow_dom", "first_person_pain": True}})
    digest = ph.build_digest(days=7)
    assert digest["total"] == 1
    assert digest["class_counts"] == {"shadow_dom": 1}


def test_digest_flags_zero_signal_queries(tmp_path, monkeypatch):
    ph = _ph(tmp_path, monkeypatch)
    cfg_path = tmp_path / "pain-queries.json"
    cfg_path.write_text(json.dumps({
        "queries": [{"q": "used query", "class": "a", "lang": "en"},
                    {"q": "never matched", "class": "a", "lang": "en"}],
        "classes": {"a": {"cdpilot_answer": "cdpilot cookies", "missing": None}},
        "negative_terms": [], "negative_authors": [],
    }))
    monkeypatch.setenv("CDPILOT_PAIN_QUERIES", str(cfg_path))
    ph.PAIN_CONFIG_PATH = cfg_path
    ph.append_ledger({"ts": time.time(), "url": "https://x.com/a/status/1", "query": "used query",
                       "classification": {"class": "a", "first_person_pain": True}})
    digest = ph.build_digest(days=7)
    assert digest["zero_signal_queries"] == ["never matched"]


# ── chef review fixes (2026-09-27) ──
def test_queries_are_sent_verbatim():
    """Measured 2026-09-27: forced quoting returned 0 results where the bare
    words found the real complaint. The data file decides; the code must not
    rewrite queries."""
    import asyncio
    import pain_hunter as ph  # type: ignore
    seen: list[str] = []

    class _Client:
        async def search_tweet(self, q, mode, count=20):
            seen.append(q)
            return []

    asyncio.run(ph._search_one(_Client(), {"q": "cookies keep expiring", "class": "x"}))
    assert seen == ["cookies keep expiring"]


def test_answer_hints_carry_no_numbers_we_corrected():
    """The hints feed the drafting model verbatim; a wrong number there is
    repeated in public replies. "~50KB" was corrected out of the README the
    same day; "500x" was never measured."""
    import json as _json
    from pathlib import Path as _P
    raw = (_P(__file__).resolve().parent.parent / "pain-queries.json").read_text()
    for bad in ("50KB", "50 KB", "2500 lines", "500x"):
        assert bad not in raw, bad
    data = _json.loads(raw)
    assert all(q["q"].strip() for q in data["queries"]), "empty query in pain-queries.json"


def test_pain_mode_prompt_labels_count_as_a_leak():
    from reply_drafter import _looks_like_leaked_prompt  # type: ignore
    assert _looks_like_leaked_prompt('THEIR PAIN (from @x): "cookies expire"')
    assert _looks_like_leaked_prompt("--- SORUN MODU (pain_hunter) --- lead with a fix")


def test_validator_takes_the_object_out_of_a_preamble():
    """nemotron-3-ultra prefixed its classification with analysis prose."""
    import pain_hunter as ph  # type: ignore
    classes = {"session_cookie_persistence": {"cdpilot_answer": "cdpilot cookies save/load"}}
    v = ph.make_classification_validator(classes)
    raw = ('The user is describing cookie loss between runs.\n'
           '{"first_person_pain": true, "class": "session_cookie_persistence", '
           '"pain": "cookies expire every run", "solvable_now": true, '
           '"command": "cdpilot cookies save", "missing_capability": null}\nDone.')
    _, issues = v(raw)
    assert issues == []
    _, issues = v("The user is describing cookie loss between runs.")
    assert issues == ["invalid json"]


def test_token_cost_hint_does_not_sell_the_snapshot_as_smaller():
    """2026-09-27 dry-run: a post about huge accessibility snapshots eating
    tokens was classified solvable with `cdpilot a11y-snapshot`. Measured, that
    snapshot is 8k tokens on Hacker News and GitHub, larger than a small
    screenshot. The hint leads with acting by visible text and carries the
    caveat, so the drafter cannot pitch the snapshot as a token saver."""
    import json as _json
    from pathlib import Path as _P
    data = _json.loads((_P(__file__).resolve().parent.parent / "pain-queries.json").read_text())
    hint = data["classes"]["mcp_vision_token_cost"]["cdpilot_answer"]
    assert hint.index("smart-click") < hint.index("a11y-snapshot")
    assert "larger than a small screenshot" in hint

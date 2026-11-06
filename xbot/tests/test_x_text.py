"""Tests for X weighted text length counter and poster precheck."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from x_text import check, weighted_length

REAL_0511_TEXT = (
    'bricks is an open-source, local alternative to clay.com: drop in a csv, '
    'define columns like "find linkedin url", and headless browsers + llm calls '
    'fill them on your machine. local-first keeps pii off third-party infra. '
    'the price: you own the browser fleet. who runs this at scale?'
)


def test_0511_real_text():
    """The real 05.11 text rejected by X error 186.

    len is 280, but clay.com counts 23 instead of 8, so weighted length is 295.
    """
    assert len(REAL_0511_TEXT) == 280
    res = check(REAL_0511_TEXT)
    assert res["weighted"] == 295
    assert res["limit"] == 280
    assert res["ok"] is False
    assert res["urls"] == ["clay.com"]


def test_plain_280_ascii():
    plain = "a" * 280
    res = check(plain)
    assert res["weighted"] == 280
    assert res["ok"] is True
    assert res["urls"] == []


def test_plain_281_ascii():
    plain = "a" * 281
    res = check(plain)
    assert res["weighted"] == 281
    assert res["ok"] is False
    assert res["urls"] == []


def test_github_url_alone():
    assert weighted_length("github.com/BraaMohammed/bricks") == 23


def test_x_url_alone():
    assert weighted_length("https://x.com/cdpilot_dev/status/1") == 23


def test_one_emoji():
    assert weighted_length("🚀") == 2


def test_one_cjk():
    assert weighted_length("中") == 2


def test_accented_e():
    assert weighted_length("é") == 1


def test_non_urls_count_plain_length():
    non_urls = [
        "localhost",
        "v1.2",
        "node_modules",
        "e.g.",
        "1.5x",
        "cdpilot.py",
    ]
    for item in non_urls:
        assert weighted_length(item) == len(item), f"{item} should weigh {len(item)}"
        assert check(item)["urls"] == [], f"{item} should not match any url"


def test_two_urls_in_one_text():
    text = "clay.com and x.com/a/status/1"
    # clay.com (23) + " and " (5) + x.com/a/status/1 (23) = 51
    assert weighted_length(text) == 51
    res = check(text)
    assert res["urls"] == ["clay.com", "x.com/a/status/1"]


def test_cli_argument():
    cli_path = Path(__file__).resolve().parent.parent / "ops" / "x_text.py"
    proc = subprocess.run(
        [sys.executable, str(cli_path), REAL_0511_TEXT],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "weighted=295 limit=280 ok=False urls=['clay.com']" in proc.stdout

    proc_ok = subprocess.run(
        [sys.executable, str(cli_path), "hello world"],
        capture_output=True,
        text=True,
    )
    assert proc_ok.returncode == 0
    assert "weighted=11 limit=280 ok=True urls=[]" in proc_ok.stdout


def test_cli_stdin():
    cli_path = Path(__file__).resolve().parent.parent / "ops" / "x_text.py"
    proc = subprocess.run(
        [sys.executable, str(cli_path)],
        input="hello world",
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "weighted=11 limit=280 ok=True urls=[]" in proc.stdout


class _FakeTweet:
    def __init__(self, id_val: int = 123456789) -> None:
        self.id = id_val


class _MockClient:
    def __init__(self, lang: str = "en-US") -> None:
        self.created: list[dict] = []

    def load_cookies(self, path: str) -> None:
        pass

    async def create_tweet(self, **kwargs) -> _FakeTweet:
        self.created.append(kwargs)
        return _FakeTweet(id_val=987654321)


def _setup_poster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CDPILOT_XBOT_DATA", str(tmp_path))
    monkeypatch.delenv("CDPILOT_AUTO_POST", raising=False)
    fake = types.ModuleType("twikit")
    fake.Client = _MockClient
    monkeypatch.setitem(sys.modules, "twikit", fake)
    monkeypatch.setitem(sys.modules, "_twikit_patch", types.ModuleType("_twikit_patch"))
    sys.modules.pop("poster_twikit", None)
    import poster_twikit as pt

    pt.QUEUE_DIR = tmp_path / "queue"
    pt.POSTED_DIR = tmp_path / "posted"
    pt.FAILED_DIR = tmp_path / "failed"
    pt.ARCHIVE_DIR = tmp_path / "queue-archive"
    pt.FREEZE_FLAG = tmp_path / "state" / "crisis-freeze.flag"
    pt.COOKIES_PATH = tmp_path / "cookies" / "cdpilot_dev.json"

    pt.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    pt.POSTED_DIR.mkdir(parents=True, exist_ok=True)
    pt.FAILED_DIR.mkdir(parents=True, exist_ok=True)
    pt.COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    pt.COOKIES_PATH.write_text("{}")

    # Capture any phone notifications
    sent_notifies = []
    monkeypatch.setattr(pt, "_phone_notify", lambda *a, **k: sent_notifies.append((a, k)))
    monkeypatch.setattr(pt, "_notify_done", lambda *a, **k: None)

    client_instance = _MockClient()
    monkeypatch.setattr(pt, "Client", lambda *a, **k: client_instance)

    return pt, client_instance, sent_notifies


def test_poster_integration_0511_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """05.11 text item fails precheck, moves to failed/, create_tweet never called, no phone push."""
    pt, client, notifies = _setup_poster(tmp_path, monkeypatch)

    item = {
        "id": "tweet-0511",
        "kind": "tweet",
        "text": REAL_0511_TEXT,
        "status": "pending",
        "scheduled_time": 1,
    }
    q_file = pt.QUEUE_DIR / "tweet-0511.json"
    q_file.write_text(json.dumps(item))

    asyncio.run(pt.main_async())

    # Queue file removed
    assert not q_file.exists()

    # Client was never called
    assert len(client.created) == 0

    # No phone push sent
    assert len(notifies) == 0

    # Item moved to failed/ with exact error format
    failed_file = pt.FAILED_DIR / "tweet-0511.json"
    assert failed_file.exists()
    data = json.loads(failed_file.read_text())
    assert data["status"] == "failed"
    assert "failed_at" in data
    assert data["error"] == "precheck: weighted length 295 > 280 (urls count 23: clay.com)"


def test_poster_integration_268_weight_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A 268-weight item passes precheck and reaches create_tweet."""
    pt, client, notifies = _setup_poster(tmp_path, monkeypatch)

    text_268 = "a" * 268
    assert check(text_268)["weighted"] == 268

    item = {
        "id": "tweet-268",
        "kind": "tweet",
        "text": text_268,
        "status": "pending",
        "scheduled_time": 1,
    }
    q_file = pt.QUEUE_DIR / "tweet-268.json"
    q_file.write_text(json.dumps(item))

    asyncio.run(pt.main_async())

    # Queue file removed, posted file exists
    assert not q_file.exists()
    posted_file = pt.POSTED_DIR / "tweet-268.json"
    assert posted_file.exists()

    # create_tweet was called with the text
    assert len(client.created) == 1
    assert client.created[0]["text"] == text_268


def test_poster_thread_item_precheck_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Thread with an oversized tweet fails precheck before create_tweet is called."""
    pt, client, notifies = _setup_poster(tmp_path, monkeypatch)

    item = {
        "id": "thread-oversized",
        "kind": "thread",
        "texts": [
            "valid first tweet",
            REAL_0511_TEXT,
        ],
        "status": "pending",
        "scheduled_time": 1,
    }
    q_file = pt.QUEUE_DIR / "thread-oversized.json"
    q_file.write_text(json.dumps(item))

    asyncio.run(pt.main_async())

    assert not q_file.exists()
    assert len(client.created) == 0
    assert len(notifies) == 0

    failed_file = pt.FAILED_DIR / "thread-oversized.json"
    assert failed_file.exists()
    data = json.loads(failed_file.read_text())
    assert data["status"] == "failed"
    assert data["error"] == "precheck: weighted length 295 > 280 (urls count 23: clay.com)"


def test_poster_followup_text_precheck_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Main tweet ok but followup_text oversized fails precheck before create_tweet."""
    pt, client, notifies = _setup_poster(tmp_path, monkeypatch)

    item = {
        "id": "tweet-bad-followup",
        "kind": "tweet",
        "text": "short main tweet",
        "followup_text": REAL_0511_TEXT,
        "status": "pending",
        "scheduled_time": 1,
    }
    q_file = pt.QUEUE_DIR / "tweet-bad-followup.json"
    q_file.write_text(json.dumps(item))

    asyncio.run(pt.main_async())

    assert not q_file.exists()
    assert len(client.created) == 0
    assert len(notifies) == 0

    failed_file = pt.FAILED_DIR / "tweet-bad-followup.json"
    assert failed_file.exists()
    data = json.loads(failed_file.read_text())
    assert data["status"] == "failed"
    assert data["error"] == "precheck: weighted length 295 > 280 (urls count 23: clay.com)"

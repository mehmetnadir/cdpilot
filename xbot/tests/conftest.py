"""Test-wide guards.

1. No test may send a real phone push. `bildir` and the ntfy token exist on
   the dev Mac as well as srv21, so any code path that notifies (poster,
   crisis_check, the sentinel, engagement_scanner…) would otherwise page
   Nadir's phone from a test run. `_notify._deliver` is the single network
   exit — it is replaced here and every payload is recorded.
2. The routine burst limiter keeps state on disk; each test gets its own file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))


class _Sent(list):
    """Messages pushed during the test (list of str) + the full payloads."""

    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[dict] = []


@pytest.fixture(autouse=True)
def _no_real_push(monkeypatch, tmp_path):
    import _notify  # type: ignore
    sent = _Sent()

    def _fake(payload: dict) -> bool:
        sent.append(payload.get("message", ""))
        sent.payloads.append(payload)
        return True

    monkeypatch.setattr(_notify, "_deliver", _fake)
    monkeypatch.setenv("CDPILOT_NTFY_STATE", str(tmp_path / "ntfy-state" / "routine.json"))
    return sent

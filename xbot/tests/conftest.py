"""Test-wide guard: no test may send a real phone push.

`bildir` exists on the dev Mac as well as srv21, so any code path that raises
an alarm (crisis_check.clear, the sentinel) would otherwise page Nadir's phone
from a test run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))


@pytest.fixture(autouse=True)
def _no_real_push(monkeypatch):
    import _notify  # type: ignore
    sent: list[str] = []

    def _fake(text: str, *a, **k) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(_notify, "push", _fake)
    return sent

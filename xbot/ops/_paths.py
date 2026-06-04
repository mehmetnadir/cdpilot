#!/usr/bin/env python3
"""_paths.py — shared, env-aware path resolver for all xbot ops modules.

Single source of truth for the bot's data/home directory. Replaces the
scattered ``Path(os.environ.get("CDPILOT_XBOT_DATA", str(Path.home() /
"cdpilot-twitter-data")))`` literals that broke when the bot code moved from
``~/cdpilot-twitter-data`` (Mac dev) to ``/opt/cdpilot-twitter-bot`` (srv21).

Resolution order (first match wins):
  1. ``CDPILOT_BOT_HOME`` env  — explicit override (new canonical var)
  2. ``CDPILOT_XBOT_DATA`` env — backward-compat (existing deploys + tests)
  3. Script-location derivation — ``ops/<mod>.py`` → parent is the bot root
     when it carries a recognizable data marker (queue/state/posted/cookies/
     twikit-venv). Works for ``/opt/cdpilot-twitter-bot`` and ``/root/...``
     alike without hardcoding either.
  4. Legacy fallback — ``~/cdpilot-twitter-data`` (original Mac dev layout)

Behavior is unchanged when an env var is set or when running from the legacy
Mac layout: the legacy fallback (#4) reproduces the old default exactly.
"""
from __future__ import annotations

import os
from pathlib import Path

# Markers that identify a directory as the bot's data/home root.
_HOME_MARKERS = ("queue", "state", "posted", "cookies", "twikit-venv")

# Legacy default — preserves prior behavior when nothing else resolves.
LEGACY_HOME = Path.home() / "cdpilot-twitter-data"


def _looks_like_home(path: Path) -> bool:
    """True if ``path`` carries any recognizable bot data marker."""
    try:
        return any((path / marker).exists() for marker in _HOME_MARKERS)
    except OSError:
        return False


def bot_home() -> Path:
    """Resolve the bot's data/home directory (see module docstring for order)."""
    env = os.environ.get("CDPILOT_BOT_HOME") or os.environ.get("CDPILOT_XBOT_DATA")
    if env:
        return Path(env)

    # ops/<module>.py → parent.parent is the bot root (e.g. /opt/cdpilot-twitter-bot)
    here = Path(__file__).resolve().parent.parent
    if _looks_like_home(here):
        return here

    return LEGACY_HOME

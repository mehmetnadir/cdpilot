"""_notify.py — one alarm path for every xbot watchdog.

Alarms went to Telegram. Between 2026-09-15 and 09-21 the sends failed with
"Network is unreachable", and the ones that did land sat in a chat nobody
reads — so a false crisis freeze kept the account silent for 11 days while
the sentinel reported the alarm as delivered. An alarm is only as good as
the channel someone actually looks at.

Order: ntfy via `bildir` (the phone push Nadir is subscribed to), then the
caller's own fallback. Never raises: a broken alarm path must not take the
watchdog down with it.
"""
from __future__ import annotations

import os
import shutil
import subprocess

BILDIR = os.environ.get("CDPILOT_BILDIR", "bildir")
CHANNEL = os.environ.get("CDPILOT_NTFY_CHANNEL", "bekci")
TITLE = "cdpilot xbot"


def push(text: str, priority: str = "yuksek", tag: str = "warning") -> bool:
    """Send `text` to the ntfy channel. True only when bildir confirmed delivery."""
    exe = shutil.which(BILDIR)
    if not exe:
        return False
    try:
        r = subprocess.run(
            [exe, CHANNEL, text, "-b", TITLE, "-p", priority, "-e", tag],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

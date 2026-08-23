"""_twikit_patch.py — monkey-patch for twikit X.com migration helper.

Problem (2026-05-25):
  Logged-in X cookies cause x.com to return 401 + empty body when fetching the
  marketing/landing HTML. twikit's ClientTransaction needs that HTML to find
  the `ondemand.s.<hash>.a.js` bundle, which provides KEY_BYTE indices for
  x-client-transaction-id signing. Without it, every authed call (search, get_user)
  fails with "Couldn't get KEY_BYTE indices" or "ClientTransaction has no key".

Fix:
  Replace `handle_x_migration` so it fetches https://x.com with a FRESH
  cookieless httpx client (the response is public; no auth needed for the
  marketing landing). The rest of twikit (which uses the authenticated session
  for actual API calls) is untouched.

Import this module ONCE at startup, before any `Client()` calls:
    from . import _twikit_patch  # noqa: F401

Idempotent — patches only once even if imported multiple times.
"""
from __future__ import annotations

import re
import bs4
import httpx

_MIGRATION_RE = re.compile(
    r"""(http(?:s)?://(?:www\.)?(twitter|x){1}\.com(/x)?/migrate([/?])?tok=[a-zA-Z0-9%\-_]+)+""",
    re.VERBOSE,
)

_DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

_PATCHED = False


async def _cookieless_handle_x_migration(session, headers):  # noqa: ARG001
    """Drop-in replacement: ignores `session` and `headers`, uses a fresh
    httpx client without any cookies. Returns BeautifulSoup of the landing page."""
    # NOTE: we deliberately ignore `headers` because cookie-laden Authorization /
    # csrf tokens break the marketing-landing response (X returns 401).
    fresh_headers = {
        "User-Agent": _DESKTOP_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(
        headers=fresh_headers,
        follow_redirects=True,
        timeout=30,
    ) as client:
        response = await client.request(method="GET", url="https://x.com")
        home_page = bs4.BeautifulSoup(response.content, "lxml")
        # Some regions still get a migration redirect — follow it the same way
        # the original code did.
        migration_url = home_page.select_one("meta[http-equiv='refresh']")
        migration_redirection_url = (
            _MIGRATION_RE.search(str(migration_url)) if migration_url else None
        ) or _MIGRATION_RE.search(str(response.content))
        if migration_redirection_url:
            response = await client.request(
                method="GET", url=migration_redirection_url.group(0))
            home_page = bs4.BeautifulSoup(response.content, "lxml")
        migration_form = home_page.select_one("form[name='f']") or home_page.select_one(
            "form[action='https://x.com/x/migrate']")
        if migration_form:
            url = migration_form.attrs.get("action", "https://x.com/x/migrate") + "/?mx=2"
            method = migration_form.attrs.get("method", "POST")
            payload = {i.get("name"): i.get("value") for i in migration_form.select("input")}
            response = await client.request(method=method, url=url, data=payload)
            home_page = bs4.BeautifulSoup(response.content, "lxml")
        return home_page


def _patch_user_class():
    """Patch twikit's User to tolerate missing fields X added/removed in 2026-05.

    Known absent fields in current X responses: withheld_in_countries.
    Without the patch, every get_user_by_screen_name raises KeyError.
    """
    from twikit import user as _user_mod
    orig_init = _user_mod.User.__init__

    _OPTIONAL_LEGACY_FIELDS = {
        "withheld_in_countries": [],
        "translator_type": "none",
        "is_translator": False,
        "listed_count": 0,
        "media_count": 0,
        "statuses_count": 0,
        "favourites_count": 0,
        "friends_count": 0,
    }

    def safe_init(self, client, data):
        # Pre-fill missing legacy fields so the original __init__ doesn't KeyError
        try:
            legacy = data.get("legacy", {}) if isinstance(data, dict) else {}
            for k, default in _OPTIONAL_LEGACY_FIELDS.items():
                legacy.setdefault(k, default)
            # 2026-08: v1.1 endpoints (follow_user et al.) return location as a
            # plain string; User.__init__ expects {"location": {"location": ...}}.
            if isinstance(data.get("location"), str):
                data["location"] = {"location": data["location"]}
            if isinstance(legacy.get("location"), dict):
                legacy["location"] = legacy["location"].get("location", "")
        except Exception:
            pass
        return orig_init(self, client, data)

    _user_mod.User.__init__ = safe_init

    # Same for guest user (used by guest client)
    try:
        from twikit.guest import user as _guser_mod
        g_orig = _guser_mod.User.__init__

        def g_safe_init(self, client, data):
            try:
                legacy = data.get("legacy", {}) if isinstance(data, dict) else {}
                for k, default in _OPTIONAL_LEGACY_FIELDS.items():
                    legacy.setdefault(k, default)
            except Exception:
                pass
            return g_orig(self, client, data)
        _guser_mod.User.__init__ = g_safe_init
    except Exception:
        pass


def apply() -> None:
    """Idempotent patch installer."""
    global _PATCHED
    if _PATCHED:
        return
    try:
        import twikit as _twikit
        # 2026-08-23: the migration override is ONLY for the legacy 2.3.3 fork.
        # On twifork (2.3.5+) it feeds ClientTransaction a landing page whose
        # ondemand bundle no longer matches -> "Couldn't get KEY_BYTE indices".
        # twifork handles migration itself; overriding it re-breaks auth.
        if str(getattr(_twikit, "__version__", "")).startswith("2.3.3"):
            from twikit.x_client_transaction import utils as _utils
            _utils.handle_x_migration = _cookieless_handle_x_migration
            # Some callers import the name directly:
            from twikit.x_client_transaction import transaction as _tx
            _tx.handle_x_migration = _cookieless_handle_x_migration
        _patch_user_class()
        _PATCHED = True
    except Exception:
        # If twikit's layout changes, fail open (twikit will error itself)
        pass


# Auto-apply on import — convenience so callers just `import _twikit_patch`
apply()

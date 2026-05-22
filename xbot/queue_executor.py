#!/usr/bin/env python3
"""
cdpilot Twitter Bot — Queue Executor
=====================================
Server-side dumb executor. Mac'te üretilen YYYY-MM-DD.json queue dosyasını
okur, schedule'a göre tweet/thread/reply gönderir.

Çalıştırma:
  python queue_executor.py [--queue-dir /opt/cdpilot-twitter-bot/queue]
  python queue_executor.py --dry-run
  python queue_executor.py --no-delay --dry-run

Exit codes:
  0 — başarılı (işlenecek item yoksa da 0)
  1 — fatal error (queue okunamadı, yazılamadı)
  2 — kısmi başarısızlık (bazı postlar failed)

Queue schema: scripts/twitter-bot/queue-schema.md
"""

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Log dir env var ile override edilebilir (Mac local vs Linux server)
LOG_DIR = os.environ.get("CDPILOT_TWITTER_LOG_DIR", "/var/log/cdpilot-twitter")
ERROR_LOG_FILENAME = "error.log"
QUEUE_LOG_FILENAME = "queue.log"

# cdpilot CLI komutu — Mac'te `python3 src/cdpilot.py` olarak çağrılır
# Env ile override edilebilir, default `cdpilot` PATH'te.
CDPILOT_CMD = os.environ.get("CDPILOT_CMD", "cdpilot").split()

# CDP port — health check için
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))


def _cdp_health_check() -> tuple[bool, str]:
    """
    Chrome CDP endpoint up mı? Post atmadan önce verify.
    Returns (healthy, error_msg).
    """
    import urllib.request
    import urllib.error
    try:
        url = f"http://127.0.0.1:{CDP_PORT}/json/version"
        with urllib.request.urlopen(url, timeout=3) as resp:
            if resp.status == 200:
                return True, ""
            return False, f"CDP returned status {resp.status}"
    except urllib.error.URLError as e:
        return False, f"CDP unreachable: {e.reason}"
    except Exception as e:
        return False, f"CDP check error: {e}"

DELAY_MIN_SECONDS = 30
DELAY_MAX_SECONDS = 120


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_dir: str) -> logging.Logger:
    """
    Logging'i hem stdout'a hem de dosyaya yönlendir.

    Args:
        log_dir: Log dosyalarının tutulacağı dizin.

    Returns:
        Yapılandırılmış Logger.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, QUEUE_LOG_FILENAME)

    logger = logging.getLogger("queue_executor")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger


def _log_error_file(log_dir: str, item_id: str, message: str) -> None:
    """Hata log dosyasına ek satır yaz (ana logger'dan bağımsız)."""
    error_log = os.path.join(log_dir, ERROR_LOG_FILENAME)
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(error_log, "a", encoding="utf-8") as f:
            ts = datetime.now().isoformat(timespec="seconds")
            f.write(f"[{ts}] item={item_id}\n{message}\n{'─' * 60}\n")
    except OSError:
        pass  # log dizinine yazılamazsa sessiz geç


# ---------------------------------------------------------------------------
# Queue I/O
# ---------------------------------------------------------------------------

def load_queue(queue_path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Queue JSON dosyasını oku.

    Top-level yapı:
      {"date": "...", "day_n": N, ..., "posts": [...]}
    Geriye uyumluluk: dosya doğrudan list ise wrapper oluşturulur.

    Args:
        queue_path: JSON queue dosyasının tam yolu.

    Returns:
        (meta_dict, posts_list) tuple'ı.

    Raises:
        json.JSONDecodeError: Geçersiz JSON.
        OSError: Dosya okuma hatası.
    """
    with open(queue_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        # Geriye uyumluluk: bare list formatı
        return {}, raw

    meta = {k: v for k, v in raw.items() if k != "posts"}
    posts = raw.get("posts", [])
    return meta, posts


def save_queue(
    queue_path: str,
    meta: dict[str, Any],
    posts: list[dict[str, Any]],
) -> None:
    """
    Queue'yu atomik olarak geri yaz (tmp → rename).

    Args:
        queue_path: Hedef JSON dosyası.
        meta: Top-level meta alanlar (date, day_n, track vs.)
        posts: Güncellenmiş post listesi.

    Raises:
        OSError: Yazma / rename hatası.
    """
    queue_dir = os.path.dirname(queue_path) or "."
    os.makedirs(queue_dir, exist_ok=True)

    payload = {**meta, "posts": posts}

    fd, tmp_path = tempfile.mkstemp(dir=queue_dir, prefix=".queue_tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, queue_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Tweet posting
# ---------------------------------------------------------------------------

def _humanizer_delay(item: dict[str, Any], no_delay: bool) -> None:
    """Item'ın humanizer_seed'ini kullanarak rastgele gecikme uygula."""
    if no_delay:
        return
    seed = item.get("humanizer_seed", random.randint(0, 99999))
    rng = random.Random(seed ^ int(time.time() // 60))  # dakika granülaritesi
    delay = rng.randint(DELAY_MIN_SECONDS, DELAY_MAX_SECONDS)
    logger = logging.getLogger("queue_executor")
    logger.info(f"Humanizer delay: {delay}s (seed={seed}) — item {item.get('id')}")
    time.sleep(delay)


def _build_post_cmd(item: dict[str, Any]) -> tuple[list[str] | None, str]:
    """
    type=post için cmd üret — modifier'ları (quote, poll, media, long) flag olarak ekle.

    Returns: (cmd_list veya None, error_message)
    """
    content = item.get("content", "")
    if not content:
        return None, "type=post but content is empty"

    cmd = ["cdpilot", "agent", "twitter", "post"]

    # Long-form (Premium) — 280+ karakter
    if item.get("long_form"):
        cmd.append("--long")

    # Quote tweet
    quote_url = item.get("quote_url")
    if quote_url:
        cmd += ["--quote", str(quote_url)]

    # Poll (anket)
    poll = item.get("poll")
    if poll and isinstance(poll, dict):
        for opt in poll.get("options", []):
            cmd += ["--poll", str(opt)]
        dur = poll.get("duration_hours", 24)
        cmd += ["--poll-duration", str(dur)]

    # Media (image/video)
    media = item.get("media") or []
    for m in media:
        if isinstance(m, dict) and m.get("path"):
            cmd += ["--media", str(m["path"])]
            if m.get("alt_text"):
                cmd += ["--alt", str(m["alt_text"])]

    cmd.append(content)
    return cmd, ""


def post_tweet(
    item: dict[str, Any],
    dry_run: bool,
    no_delay: bool,
) -> tuple[bool, str, str]:
    """
    cdpilot CLI üzerinden uygun aksiyonu yürüt.

    Desteklenen type'lar:
      Content: post, thread, reply
      Pin: pin, unpin
      Engagement: like, unlike, retweet, unretweet, bookmark, follow, unfollow

    Args:
        item: Queue item dict'i.
        dry_run: True ise gerçek gönderi yapılmaz.
        no_delay: True ise humanizer delay atlanır.

    Returns:
        (success, result_url, error_message) tuple'ı.
    """
    logger = logging.getLogger("queue_executor")
    item_id = item.get("id", "?")
    item_type = item.get("type", "")

    # Engagement aksiyonlarına content delay'i uygulanmaz, ama yine de küçük jitter ekleyebilir
    _humanizer_delay(item, dry_run or no_delay)

    cmd: list[str] | None = None
    err: str = ""

    # ─── Content actions ───────────────────────────────────────────────
    if item_type == "post":
        cmd, err = _build_post_cmd(item)
        if cmd is None:
            return False, "", err

    elif item_type == "thread":
        tweets = item.get("thread") or []
        if len(tweets) < 2:
            return False, "", f"type=thread but thread has {len(tweets)} items (min 2)"
        cmd = ["cdpilot", "agent", "twitter", "thread"] + tweets
        # Thread için media: her tweet'in media'sı thread'ten farklı çekilir;
        # cdpilot CLI gelecekte --media-per-tweet 0:path desteklerse buraya ekle.

    elif item_type == "reply":
        content = item.get("content", "")
        reply_to = item.get("reply_to", "")
        if not content:
            return False, "", "type=reply but content is empty"
        if not reply_to:
            return False, "", "type=reply but reply_to is missing"
        cmd = ["cdpilot", "agent", "twitter", "reply", "--to", str(reply_to), content]

    # ─── Pin actions ───────────────────────────────────────────────────
    elif item_type in ("pin", "unpin"):
        tgt = item.get("pin_target", "")
        if not tgt:
            return False, "", f"type={item_type} but pin_target is missing"
        cmd = ["cdpilot", "agent", "twitter", item_type, str(tgt)]

    # ─── Engagement on others' tweets ─────────────────────────────────
    elif item_type in ("like", "unlike", "retweet", "unretweet", "bookmark"):
        tgt = item.get("target_tweet_id", "")
        if not tgt:
            return False, "", f"type={item_type} but target_tweet_id is missing"
        cmd = ["cdpilot", "agent", "twitter", item_type, str(tgt)]

    # ─── Follow / Unfollow ─────────────────────────────────────────────
    elif item_type in ("follow", "unfollow"):
        handle = item.get("target_handle", "")
        if not handle:
            return False, "", f"type={item_type} but target_handle is missing"
        # Handle'dan @ varsa temizle
        handle = handle.lstrip("@")
        cmd = ["cdpilot", "agent", "twitter", item_type, handle]

    else:
        return False, "", f"Unknown type: {item_type!r}"

    if dry_run:
        logger.info(f"[DRY-RUN] Would run: {' '.join(cmd)}")
        return True, "https://x.com/dry_run/status/0", ""

    # Gerçek çalıştırma
    logger.info(f"Executing item {item_id} ({item_type}): {' '.join(cmd[:6])}…")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            err = f"exit={result.returncode} stderr={result.stderr.strip()[:500]}"
            return False, "", err
        result_url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        return True, result_url, ""

    except subprocess.TimeoutExpired:
        return False, "", "cdpilot command timed out after 120s"
    except FileNotFoundError:
        return False, "", "cdpilot not found in PATH"
    except Exception as exc:
        return False, "", str(exc)


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

def run_executor(queue_dir: str, dry_run: bool, no_delay: bool) -> int:
    """
    Bugünün queue dosyasını bul ve işlenecek itemları çalıştır.

    Args:
        queue_dir: Queue JSON dosyalarının dizini.
        dry_run: Gerçek post yapılmasın.
        no_delay: Humanizer delay'i atla.

    Returns:
        Exit code (0 / 1 / 2).
    """
    logger = logging.getLogger("queue_executor")
    today_str = datetime.now().strftime("%Y-%m-%d")
    queue_path = os.path.join(queue_dir, f"{today_str}.json")

    logger.info(f"Queue executor starting. File: {queue_path}")

    if not os.path.exists(queue_path):
        logger.info("Queue file does not exist — nothing to do.")
        return 0

    # Yükleme
    try:
        meta, posts = load_queue(queue_path)
    except Exception as exc:
        logger.error(f"Fatal: Cannot load queue: {exc}")
        return 1

    if not posts:
        logger.info("Queue is empty.")
        return 0

    now = datetime.now(timezone.utc)
    partial_failure = False
    processed = 0

    for item in posts:
        status = item.get("status", "")
        item_id = item.get("id", "?")

        # Idempotency: done/failed/skipped itemları geç
        if status in ("done", "failed", "skipped"):
            continue

        if status != "pending":
            logger.warning(f"Item {item_id} has unknown status {status!r} — skipping.")
            continue

        # Schedule kontrolü
        raw_time = item.get("scheduled_time", "")
        if not raw_time:
            logger.warning(f"Item {item_id} has no scheduled_time — skipping.")
            continue

        try:
            sched = datetime.fromisoformat(raw_time)
            if sched.tzinfo is None:
                sched = sched.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            logger.error(f"Item {item_id}: invalid scheduled_time {raw_time!r}: {exc}")
            item["status"] = "failed"
            item["error"] = f"Invalid time format: {exc}"
            partial_failure = True
            _safe_save(queue_path, meta, posts, logger)
            continue

        if sched > now:
            logger.debug(f"Item {item_id}: not yet due ({raw_time}).")
            continue

        # Pre-flight: Chrome CDP up mu? Down ise item'ı pending bırak, fail olarak işaretleme
        if not dry_run:
            healthy, health_err = _cdp_health_check()
            if not healthy:
                logger.warning(f"Item {item_id}: SKIP (Chrome health fail: {health_err}) — pending kalır, sonraki cycle yeniden dener")
                # Hiçbir status değiştirme — pending kalır, sonraki cycle aynı item'ı seçer
                continue

        # Gönder
        success, result_url, error = post_tweet(item, dry_run, no_delay)
        processed += 1

        if success:
            item["status"] = "done"
            item["result_url"] = result_url
            item["error"] = None
            logger.info(f"Item {item_id}: done. url={result_url or '(none)'}")
        else:
            item["status"] = "failed"
            item["result_url"] = None
            item["error"] = error
            partial_failure = True
            logger.error(f"Item {item_id}: FAILED — {error}")
            _log_error_file(LOG_DIR, item_id, error)

        # Her item sonrası kaydet (crash güvenliği)
        if not _safe_save(queue_path, meta, posts, logger):
            return 1

    summary = f"Done. Processed={processed}"
    if partial_failure:
        summary += " (some failures)"
    logger.info(summary)
    return 2 if partial_failure else 0


def _safe_save(
    queue_path: str,
    meta: dict[str, Any],
    posts: list[dict[str, Any]],
    logger: logging.Logger,
) -> bool:
    """Queue'yu kaydet, başarı/başarısızlık bool döndür."""
    try:
        save_queue(queue_path, meta, posts)
        return True
    except Exception as exc:
        logger.error(f"Fatal: Cannot save queue: {exc}")
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI argümanlarını ayrıştır ve executor'ı çalıştır."""
    parser = argparse.ArgumentParser(
        description="cdpilot Twitter Bot — Queue Executor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--queue-dir",
        default="/opt/cdpilot-twitter-bot/queue",
        metavar="DIR",
        help="Queue JSON dosyalarının dizini",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Gerçek post yapmadan sadece logla",
    )
    parser.add_argument(
        "--no-delay",
        action="store_true",
        help="Humanizer delay'i atla (test için)",
    )

    args = parser.parse_args()
    setup_logging(LOG_DIR)

    exit_code = run_executor(
        queue_dir=args.queue_dir,
        dry_run=args.dry_run,
        no_delay=args.no_delay,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

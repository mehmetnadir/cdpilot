#!/usr/bin/env python3
"""Fake AF_UNIX canvas host speaking v0 contract §4/§5 for Lane D tests."""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
import socket
import sys
import threading
import time
from typing import Any

ALLOWED_OPS: frozenset[str] = frozenset({"set", "patch", "events", "close", "ping"})
HTML_MAX: int = 1 << 20
LINE_MAX: int = HTML_MAX + (64 << 10)


def _cut_data(data: Any, item_max: int) -> Any:
    """Bound event `data` to `item_max` UTF-8 bytes per contract §5."""
    if data is None:
        return None
    if isinstance(data, str):
        raw = data.encode("utf-8")
        if len(raw) <= item_max:
            return data
        return raw[:item_max].decode("utf-8", errors="ignore")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= item_max:
        return data
    return encoded[:item_max].decode("utf-8", errors="ignore")


class FakeCanvasHost:
    """In-memory event ring + AF_UNIX line-JSON server implementing contract §4."""

    def __init__(
        self,
        sock_path: str,
        name: str = "main",
        ring_max: int = 1000,
        ring_bytes: int = 64 << 10,
        item_max: int = 1024,
        record_file: str | None = None,
    ) -> None:
        self.sock_path = sock_path
        self.name = name
        self.ring_max = ring_max
        self.ring_bytes = ring_bytes
        self.item_max = item_max
        self.record_file = record_file

        self._cond = threading.Condition()
        self._ring: deque[tuple[dict[str, Any], int]] = deque()
        self._total_bytes = 0
        self._seq = 0
        self._dropped = 0
        self._polls = 0
        self._closed = False
        self._started = time.monotonic()
        self._srv: socket.socket | None = None
        self._threads: list[threading.Thread] = []

    def push_event(self, raw_ev: dict[str, Any]) -> dict[str, Any]:
        """Append one event to the ring, truncating `data` and evicting oldest on overflow."""
        with self._cond:
            self._seq += 1
            ev: dict[str, Any] = {
                "seq": self._seq,
                "t": int(raw_ev.get("t") or int(time.time() * 1000)),
                "src": str(raw_ev.get("src") or "page"),
                "type": str(raw_ev.get("type") or "click"),
                "action": raw_ev.get("action"),
                "id": raw_ev.get("id"),
                "data": _cut_data(raw_ev.get("data"), self.item_max),
            }
            size = len(json.dumps(ev, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            self._ring.append((ev, size))
            self._total_bytes += size
            while len(self._ring) > self.ring_max or (
                len(self._ring) > 1 and self._total_bytes > self.ring_bytes
            ):
                _, old_sz = self._ring.popleft()
                self._total_bytes -= old_sz
                self._dropped += 1
            self._cond.notify_all()
            return ev

    def _record(self, msg: dict[str, Any]) -> None:
        if not self.record_file:
            return
        logged = dict(msg)
        if isinstance(logged.get("html"), str):
            logged["html_len"] = len(logged["html"])
            logged["html_head"] = logged["html"][:64]
            del logged["html"]
        with open(self.record_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(logged, ensure_ascii=False) + "\n")

    def handle_message(self, msg: Any) -> tuple[dict[str, Any], bool]:
        """Process one request dict; returns (reply_dict, should_close)."""
        if not isinstance(msg, dict):
            return {"ok": False, "error": "request must be an object", "code": 2}, False
        op = msg.get("op")
        if op not in ALLOWED_OPS:
            return {"ok": False, "error": f"unknown op: {op!r}", "code": 2}, False
        self._record(msg)

        if op == "ping":
            return {
                "ok": True,
                "name": self.name,
                "targetId": "FAKE_TARGET_ID_0001",
                "v": 1,
                "pid": os.getpid(),
                "uptime_s": round(time.monotonic() - self._started, 3),
            }, False

        if op == "close":
            return {"ok": True}, True

        if op in ("set", "patch"):
            html = msg.get("html")
            if not isinstance(html, str) or len(html.encode("utf-8")) > HTML_MAX:
                return {"ok": False, "error": "invalid or oversized html", "code": 2}, False
            now_ms = int(time.time() * 1000)
            if op == "set":
                return {"ok": True, "ms": 4, "t_paint": now_ms}, False
            if not isinstance(msg.get("final"), bool):
                return {"ok": False, "error": "patch requires boolean final", "code": 2}, False
            return {
                "ok": True,
                "ops": {"add": 2, "del": 1, "move": 0, "upd": 3},
                "ms": 5,
                "t_paint": now_ms,
            }, False

        after = msg.get("after", 0)
        max_n = msg.get("max", 100)
        wait_ms = msg.get("wait_ms", 0)
        if (
            isinstance(after, bool)
            or not isinstance(after, int)
            or after < 0
            or isinstance(max_n, bool)
            or not isinstance(max_n, int)
            or not (1 <= max_n <= 100)
            or isinstance(wait_ms, bool)
            or not isinstance(wait_ms, int)
            or not (0 <= wait_ms <= 25000)
        ):
            return {"ok": False, "error": "invalid events arguments", "code": 2}, False

        deadline = time.monotonic() + (wait_ms / 1000.0)
        with self._cond:
            self._polls += 1
            self._cond.notify_all()
            while not self._closed:
                matching = [ev for ev, _ in self._ring if ev["seq"] > after]
                if matching or wait_ms == 0:
                    break
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                self._cond.wait(timeout=rem)
            matching = [ev for ev, _ in self._ring if ev["seq"] > after]
            batch = matching[:max_n]
            nxt = batch[-1]["seq"] if batch else max(after, self._seq)
            return {
                "ok": True,
                "events": batch,
                "next": nxt,
                "dropped": self._dropped,
            }, False

    def start(self) -> None:
        """Bind AF_UNIX socket with 0700 dir and 0600 socket permissions."""
        sock_dir = os.path.dirname(self.sock_path)
        os.makedirs(sock_dir, mode=0o700, exist_ok=True)
        os.chmod(sock_dir, 0o700)
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        os.chmod(self.sock_path, 0o600)
        srv.listen(16)
        srv.settimeout(0.2)
        self._srv = srv
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()
        self._threads.append(t)

    def _accept_loop(self) -> None:
        assert self._srv is not None
        while not self._closed:
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._client_worker, args=(conn,), daemon=True)
            t.start()

    def _client_worker(self, conn: socket.socket) -> None:
        should_close = False
        try:
            with conn:
                conn.settimeout(30.0)
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if len(buf) > LINE_MAX:
                        reply = {"ok": False, "error": "request line too large", "code": 2}
                        conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                        return
                if not buf.strip():
                    return
                try:
                    msg = json.loads(buf.decode("utf-8"))
                except ValueError:
                    reply = {"ok": False, "error": "invalid json", "code": 2}
                else:
                    reply, should_close = self.handle_message(msg)
                conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError:
            pass
        if should_close:
            self.stop()

    def run_script(self, steps: list[dict[str, Any]]) -> None:
        """Load immediate steps now and run delayed / poll-gated steps on a helper thread."""
        deferred: list[dict[str, Any]] = []
        for step in steps:
            if not step.get("after_polls") and not step.get("delay_ms"):
                self.push_event(step["event"])
            else:
                deferred.append(step)
        if not deferred:
            return

        def _worker() -> None:
            for step in deferred:
                target_polls = int(step.get("after_polls") or 0)
                if target_polls > 0:
                    with self._cond:
                        while not self._closed and self._polls < target_polls:
                            self._cond.wait(timeout=0.1)
                delay_s = float(step.get("delay_ms") or 0) / 1000.0
                if delay_s > 0:
                    time.sleep(delay_s)
                if self._closed:
                    return
                self.push_event(step["event"])

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        self._threads.append(t)

    def wait_until_closed(self, max_seconds: float = 30.0) -> None:
        deadline = time.monotonic() + max_seconds
        with self._cond:
            while not self._closed and time.monotonic() < deadline:
                self._cond.wait(timeout=0.2)

    def stop(self) -> None:
        with self._cond:
            if self._closed:
                return
            self._closed = True
            self._cond.notify_all()
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
        try:
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fake canvas AF_UNIX host for tests")
    parser.add_argument("--profile", required=True, help="CDPILOT_PROFILE directory")
    parser.add_argument("--name", default="main", help="Canvas name")
    parser.add_argument("--ring-max", type=int, default=1000)
    parser.add_argument("--ring-bytes", type=int, default=64 << 10)
    parser.add_argument("--item-max", type=int, default=1024)
    parser.add_argument("--script-file", default=None, help="JSON file of scripted events")
    parser.add_argument("--ready-file", default=None, help="File written once socket listens")
    parser.add_argument("--record-file", default=None, help="JSONL file logging incoming ops")
    parser.add_argument("--max-seconds", type=float, default=25.0)
    ns = parser.parse_args(argv)

    sock_path = os.path.join(ns.profile, "canvas", f"{ns.name}.sock")
    host = FakeCanvasHost(
        sock_path=sock_path,
        name=ns.name,
        ring_max=ns.ring_max,
        ring_bytes=ns.ring_bytes,
        item_max=ns.item_max,
        record_file=ns.record_file,
    )
    steps: list[dict[str, Any]] = []
    if ns.script_file:
        with open(ns.script_file, encoding="utf-8") as f:
            steps = json.load(f)
    host.start()
    host.run_script(steps)
    if ns.ready_file:
        with open(ns.ready_file, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}\n")
    try:
        host.wait_until_closed(ns.max_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        host.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

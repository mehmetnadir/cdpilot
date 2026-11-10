#!/usr/bin/env python3.13
"""Paint-latency benchmark for `cdpilot canvas stream` (plan §4, contract §4).

Streams a synthetic ~20 KB HTML document token by token into `cmd_canvas_stream`
against a running canvas host, a standalone CDP harness (`--cdp 127.0.0.1:9333`),
or an in-process fake host (`--fake`). Records per patch:
  - t_cli (last byte read timestamp from CLI, ns / epoch ms)
  - host_reply_ms (host reply time minus t_cli)
  - t_paint (double-rAF epoch ms from page / host)
  - paint_minus_cli_ms (t_paint - t_cli)
Writes JSON to `.claude/docs/olcum/canvas-bench-<date>.json`.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".claude", "docs", "olcum")

FORBIDDEN_PORTS = {3000, 9222}
CANVAS_CSP = (
  "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; "
  "style-src 'unsafe-inline'; img-src data: blob:; form-action 'none'; "
  "base-uri 'none'; frame-src 'none'; sandbox allow-scripts"
)
SKELETON_HTML = (
  b"<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>"
)


def percentile(vals: list[float], pct: float) -> float:
  """Nearest-rank / linear interpolated percentile on non-empty float list."""
  if not vals:
    return 0.0
  s = sorted(vals)
  if len(s) == 1:
    return round(s[0], 3)
  pos = (pct / 100.0) * (len(s) - 1)
  lo = int(math.floor(pos))
  hi = int(math.ceil(pos))
  if lo == hi:
    return round(s[lo], 3)
  frac = pos - lo
  return round(s[lo] + (s[hi] - s[lo]) * frac, 3)


def summarize_series(vals: list[float]) -> dict[str, float]:
  if not vals:
    return {"p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
  return {
    "p50": percentile(vals, 50.0),
    "p95": percentile(vals, 95.0),
    "min": round(min(vals), 3),
    "max": round(max(vals), 3),
    "mean": round(sum(vals) / len(vals), 3),
  }


def read_uptime() -> str:
  try:
    r = subprocess.run(
      ["uptime"], capture_output=True, text=True, timeout=5.0, check=False
    )
    return (r.stdout or "").strip()
  except OSError:
    return ""


def build_synthetic_tokens(blocks: int) -> list[tuple[bytes, float]]:
  """Build (token_bytes, delay_after_s) pairs totaling ~20 KB for 50 blocks."""
  out: list[tuple[bytes, float]] = []
  head_parts = [
    "<!doctype html><html><head><meta charset=\"utf-8\">",
    "<style>",
    "body{font-family:system-ui,sans-serif;margin:16px;background:#0f172a;color:#e2e8f0}",
    ".grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}",
    ".card{padding:10px 12px;border:1px solid #334155;border-radius:8px;background:#1e293b}",
    ".card h3{margin:0 0 4px;font-size:14px;color:#38bdf8}",
    ".meta{font-size:12px;color:#94a3b8}",
    "</style></head><body><main class=\"grid\" id=\"app\">",
  ]
  for part in head_parts[:-1]:
    out.append((part.encode("utf-8"), 0.002))
  out.append((head_parts[-1].encode("utf-8"), 0.025))

  for idx in range(1, blocks + 1):
    t1 = f'<section class="card" id="card-{idx}" data-key="k-{idx}">'
    t2 = f"<h3>Result #{idx}: Live Canvas Item {idx * 17}</h3>"
    t3 = (
      f'<p class="meta">Latency probe row {idx} with deterministic filler '
      f"metrics score={(idx * 31) % 100} status=active region=eu-central.</p>"
    )
    t4 = (
      f'<div class="bar" data-action="select" data-id="{idx}">'
      f"<span>Token batch {idx}</span> · <strong>{(idx * 13) % 97} ms</strong></div>"
    )
    t5 = "</section>"
    out.append((t1.encode("utf-8"), 0.002))
    out.append((t2.encode("utf-8"), 0.002))
    out.append((t3.encode("utf-8"), 0.002))
    out.append((t4.encode("utf-8"), 0.002))
    # Pause set by caller on closing </section> tokens (sentinel -1.0).
    out.append((t5.encode("utf-8"), -1.0))

  tail_parts = [
    "</main>",
    "<script>window.__canvasBenchCards=document.querySelectorAll('section.card').length;</script>",
    "</body></html>",
  ]
  for part in tail_parts:
    out.append((part.encode("utf-8"), 0.002))
  return out


class CDPBenchBackend:
  """Isolated browserContext CDP backend for pre-merge / standalone e2e measurement."""

  def __init__(self, host_port: str, canvas_name: str) -> None:
    host, _, port_s = host_port.rpartition(":")
    if not host or not port_s.isdigit():
      raise ValueError(f"bad --cdp address: {host_port!r} (expected host:port)")
    port = int(port_s)
    if port in FORBIDDEN_PORTS:
      raise ValueError(f"port {port} is forbidden by project rules")
    self.host_port = host_port
    self.canvas_url = f"http://cdpilot-canvas.invalid/{canvas_name}/"
    self.browser_version = ""
    self._loop: asyncio.AbstractEventLoop | None = None
    self._thread: threading.Thread | None = None
    self._ready = threading.Event()
    self._start_err: BaseException | None = None
    self._ws: Any = None
    self._msg_id = 0
    self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
    self._session_id: str | None = None
    self._ctx_id: str | None = None
    self._target_id: str | None = None

  def _http_json(self, path: str) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(f"http://{self.host_port}{path}", method="GET")
    with opener.open(req, timeout=10.0) as resp:
      return json.loads(resp.read().decode("utf-8", errors="replace"))

  def start(self) -> None:
    ver = self._http_json("/json/version")
    self.browser_version = str(ver.get("Browser") or "unknown")
    ws_url = str(ver["webSocketDebuggerUrl"])

    def _run() -> None:
      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)
      self._loop = loop
      try:
        loop.run_until_complete(self._async_setup(ws_url))
      except BaseException as exc:
        self._start_err = exc
        self._ready.set()
        return
      self._ready.set()
      loop.run_forever()
      loop.run_until_complete(self._async_teardown())
      loop.close()

    self._thread = threading.Thread(target=_run, name="cdp-bench-loop", daemon=True)
    self._thread.start()
    self._ready.wait(timeout=20.0)
    if self._start_err is not None:
      raise RuntimeError(f"CDP setup failed: {self._start_err}") from self._start_err

  async def _cdp_send(
    self,
    method: str,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
    timeout: float = 15.0,
  ) -> dict[str, Any]:
    assert self._loop is not None
    self._msg_id += 1
    mid = self._msg_id
    payload: dict[str, Any] = {"id": mid, "method": method, "params": params or {}}
    if session_id:
      payload["sessionId"] = session_id
    fut: asyncio.Future[dict[str, Any]] = self._loop.create_future()
    self._pending[mid] = fut
    await self._ws.send(json.dumps(payload))
    msg = await asyncio.wait_for(fut, timeout=timeout)
    if "error" in msg:
      raise RuntimeError(f"{method}: {msg['error']}")
    res = msg.get("result")
    return res if isinstance(res, dict) else {}

  async def _rx_loop(self) -> None:
    try:
      async for raw in self._ws:
        data = json.loads(raw)
        if "id" in data:
          fut = self._pending.pop(data["id"], None)
          if fut is not None and not fut.done():
            fut.set_result(data)
        elif data.get("method") == "Fetch.requestPaused":
          if data.get("sessionId") == self._session_id:
            asyncio.create_task(self._on_fetch_paused(data.get("params") or {}))
    except Exception:
      for fut in list(self._pending.values()):
        if not fut.done():
          fut.set_exception(RuntimeError("CDP websocket closed"))

  async def _on_fetch_paused(self, params: dict[str, Any]) -> None:
    rid = params.get("requestId")
    url = (params.get("request") or {}).get("url", "")
    rtype = params.get("resourceType", "")
    sid = self._session_id
    try:
      if url == self.canvas_url and rtype == "Document":
        headers = [
          {"name": "Content-Type", "value": "text/html; charset=utf-8"},
          {"name": "Content-Security-Policy", "value": CANVAS_CSP},
        ]
        await self._cdp_send(
          "Fetch.fulfillRequest",
          {
            "requestId": rid,
            "responseCode": 200,
            "responseHeaders": headers,
            "body": base64.b64encode(SKELETON_HTML).decode("ascii"),
          },
          session_id=sid,
        )
      elif rtype == "Document":
        await self._cdp_send(
          "Fetch.fulfillRequest",
          {"requestId": rid, "responseCode": 204, "responseHeaders": []},
          session_id=sid,
        )
      else:
        await self._cdp_send(
          "Fetch.failRequest",
          {"requestId": rid, "errorReason": "BlockedByClient"},
          session_id=sid,
        )
    except Exception:
      pass

  async def _async_setup(self, ws_url: str) -> None:
    import websockets.asyncio.client as wsc

    self._ws = await wsc.connect(
      ws_url, max_size=None, ping_interval=None, open_timeout=15.0, proxy=None
    )
    asyncio.create_task(self._rx_loop())
    ctx_res = await self._cdp_send(
      "Target.createBrowserContext", {"disposeOnDetach": True}
    )
    self._ctx_id = str(ctx_res["browserContextId"])
    tgt_res = await self._cdp_send(
      "Target.createTarget",
      {"url": "about:blank", "browserContextId": self._ctx_id},
    )
    self._target_id = str(tgt_res["targetId"])
    att_res = await self._cdp_send(
      "Target.attachToTarget", {"targetId": self._target_id, "flatten": True}
    )
    self._session_id = str(att_res["sessionId"])
    sid = self._session_id
    await self._cdp_send("Page.enable", {}, session_id=sid)
    await self._cdp_send("Runtime.enable", {}, session_id=sid)
    await self._cdp_send(
      "Fetch.enable",
      {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]},
      session_id=sid,
    )
    await self._cdp_send("Page.navigate", {"url": self.canvas_url}, session_id=sid)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
      ev = await self._cdp_send(
        "Runtime.evaluate",
        {"expression": "location.href + '|' + document.readyState", "returnByValue": True},
        session_id=sid,
      )
      val = (ev.get("result") or {}).get("value")
      if val == f"{self.canvas_url}|complete":
        try:
          await self._cdp_send("Page.bringToFront", {}, session_id=sid)
          await self._cdp_send(
            "Emulation.setFocusEmulationEnabled", {"enabled": True}, session_id=sid
          )
        except Exception:
          pass
        return
      await asyncio.sleep(0.03)
    raise RuntimeError("canvas page did not reach readyState=complete")

  async def _async_patch(self, html: str, is_final: bool) -> dict[str, Any]:
    t0 = time.monotonic()
    html_json = json.dumps(html)
    final_json = "true" if is_final else "false"
    expr = f"""(() => {{
      const html = {html_json};
      const final = {final_json};
      if (window.__cdpilotCanvas && typeof window.__cdpilotCanvas.patch === 'function') {{
        return window.__cdpilotCanvas.patch(html, {{ final }});
      }}
      const t0 = performance.now();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      for (const bad of doc.querySelectorAll('base,meta[http-equiv]')) bad.remove();
      if (!final) {{
        for (const s of doc.querySelectorAll('script')) s.remove();
      }}
      document.head.innerHTML = doc.head ? doc.head.innerHTML : '';
      document.body.innerHTML = doc.body ? doc.body.innerHTML : '';
      if (final) {{
        for (const old of Array.from(document.body.querySelectorAll('script'))) {{
          const s = document.createElement('script');
          s.textContent = old.textContent;
          old.replaceWith(s);
        }}
      }}
      const ms = Math.round((performance.now() - t0) * 10) / 10;
      return new Promise((resolve) => {{
        requestAnimationFrame(() => requestAnimationFrame(() => {{
          resolve({{ ok: true, ops: {{ add: 0, del: 0, move: 0, upd: 1 }}, ms, t_paint: Date.now() }});
        }}));
      }});
    }})()"""
    ev = await self._cdp_send(
      "Runtime.evaluate",
      {"expression": expr, "awaitPromise": True, "returnByValue": True},
      session_id=self._session_id,
      timeout=15.0,
    )
    if "exceptionDetails" in ev:
      return {"ok": False, "error": str(ev["exceptionDetails"])[:120], "code": 1}
    val = (ev.get("result") or {}).get("value")
    if isinstance(val, dict) and val.get("ok"):
      return val
    return {
      "ok": True,
      "ops": {"add": 0, "del": 0, "move": 0, "upd": 1},
      "ms": round((time.monotonic() - t0) * 1000.0, 2),
      "t_paint": round(time.time() * 1000),
    }

  def patch(self, html: str, is_final: bool) -> dict[str, Any]:
    assert self._loop is not None
    fut = asyncio.run_coroutine_threadsafe(
      self._async_patch(html, is_final), self._loop
    )
    return fut.result(timeout=20.0)

  async def _async_teardown(self) -> None:
    if self._target_id:
      try:
        await self._cdp_send(
          "Target.closeTarget", {"targetId": self._target_id}, timeout=5.0
        )
      except Exception:
        pass
      self._target_id = None
    if self._ctx_id:
      try:
        await self._cdp_send(
          "Target.disposeBrowserContext",
          {"browserContextId": self._ctx_id},
          timeout=5.0,
        )
      except Exception:
        pass
      self._ctx_id = None
    if self._ws is not None:
      try:
        await self._ws.close()
      except Exception:
        pass

  def close(self) -> None:
    if self._loop is not None:
      self._loop.call_soon_threadsafe(self._loop.stop)
    if self._thread is not None:
      self._thread.join(timeout=10.0)


class RecordingCanvasTap:
  """AF_UNIX server speaking contract §4 and recording per-patch timestamps."""

  def __init__(
    self,
    sock_path: str,
    mode: str,
    fake_ms: float = 2.0,
    upstream_sock: str | None = None,
    cdp_backend: CDPBenchBackend | None = None,
  ) -> None:
    self.sock_path = sock_path
    self.mode = mode
    self.fake_ms = fake_ms
    self.upstream_sock = upstream_sock
    self.cdp_backend = cdp_backend
    self.records: list[dict[str, Any]] = []
    self._stop = threading.Event()
    self._srv: socket.socket | None = None
    self._thread: threading.Thread | None = None
    self._lock = threading.Lock()

  def start(self) -> None:
    os.makedirs(os.path.dirname(self.sock_path), mode=0o700, exist_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(self.sock_path)
    os.chmod(self.sock_path, 0o600)
    srv.listen(16)
    srv.settimeout(0.1)
    self._srv = srv
    self._thread = threading.Thread(target=self._serve, name="canvas-tap", daemon=True)
    self._thread.start()

  def _forward_upstream(self, raw_line: bytes) -> dict[str, Any]:
    assert self.upstream_sock is not None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as us:
      us.settimeout(15.0)
      us.connect(self.upstream_sock)
      us.sendall(raw_line)
      buf = b""
      while not buf.endswith(b"\n"):
        chunk = us.recv(65536)
        if not chunk:
          break
        buf += chunk
    return json.loads(buf.decode("utf-8"))

  def _handle_conn(self, conn: socket.socket) -> None:
    with conn:
      conn.settimeout(15.0)
      buf = b""
      while not buf.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
          break
        buf += chunk
      if not buf:
        return
      t_recv_ns = time.time_ns()
      msg = json.loads(buf.decode("utf-8"))
      op = msg.get("op")
      if self.mode == "live":
        reply = self._forward_upstream(buf)
      elif op == "ping":
        reply = {
          "ok": True,
          "name": "bench",
          "targetId": "FAKE",
          "v": 1,
          "pid": os.getpid(),
          "uptime_s": 1,
        }
      elif op == "patch":
        if self.mode == "cdp":
          assert self.cdp_backend is not None
          reply = self.cdp_backend.patch(
            str(msg.get("html") or ""), bool(msg.get("final"))
          )
        else:
          if self.fake_ms > 0:
            time.sleep(self.fake_ms / 1000.0)
          reply = {
            "ok": True,
            "ops": {"add": 1, "del": 0, "move": 0, "upd": 0},
            "ms": round(self.fake_ms, 2),
            "t_paint": round(time.time() * 1000),
          }
      else:
        reply = {"ok": False, "error": f"unsupported bench op: {op}", "code": 2}
      t_reply_ns = time.time_ns()
      conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))

      if op == "patch" and reply.get("ok"):
        t_cli_ns = int(msg.get("t_cli") or t_recv_ns)
        t_paint_raw = reply.get("t_paint")
        t_paint_ms = (
          float(t_paint_raw)
          if isinstance(t_paint_raw, (int, float))
          else round(t_reply_ns / 1e6, 3)
        )
        html_bytes = len(str(msg.get("html") or "").encode("utf-8"))
        with self._lock:
          seq = len(self.records) + 1
          self.records.append({
            "seq": seq,
            "bytes": html_bytes,
            "final": bool(msg.get("final")),
            "t_cli_ns": t_cli_ns,
            "t_cli_ms": round(t_cli_ns / 1e6, 3),
            "t_host_recv_ms": round(t_recv_ns / 1e6, 3),
            "t_host_reply_ms": round(t_reply_ns / 1e6, 3),
            "host_reply_ms": round((t_reply_ns - t_cli_ns) / 1e6, 3),
            "host_ms": reply.get("ms"),
            "t_paint_ms": t_paint_ms,
            "paint_minus_cli_ms": round(t_paint_ms - (t_cli_ns / 1e6), 3),
          })

  def _serve(self) -> None:
    assert self._srv is not None
    while not self._stop.is_set():
      try:
        conn, _ = self._srv.accept()
      except TimeoutError:
        continue
      except OSError:
        break
      self._handle_conn(conn)

  def stop(self) -> None:
    self._stop.set()
    if self._srv is not None:
      try:
        self._srv.close()
      except OSError:
        pass
    if self._thread is not None:
      self._thread.join(timeout=5.0)


def resolve_live_upstream(canvas_name: str) -> tuple[str, dict[str, Any]]:
  """Locate and ping an already-running canvas host socket."""
  sys.path.insert(0, SRC_DIR)
  import cdpilot  # type: ignore[import-not-found]

  sock_path = str(cdpilot._canvas_paths(canvas_name)["sock"])
  ping = cdpilot._canvas_request(canvas_name, {"op": "ping"}, timeout=5.0)
  if not ping.get("ok"):
    raise RuntimeError(f"canvas {canvas_name!r} ping failed: {ping}")
  return sock_path, ping


def run_single_stream(
  canvas_name: str,
  tap_home: str,
  tap_profile: str,
  tokens: list[tuple[bytes, float]],
  pause_s: float,
) -> tuple[int, str, str, int]:
  """Spawn fresh Python running `cmd_canvas_stream(name)` and feed tokens live."""
  ready_r, ready_w = os.pipe()
  env = dict(os.environ)
  env["CDPILOT_HOME"] = tap_home
  env["CDPILOT_PROFILE"] = tap_profile
  env["CDP_PORT"] = "19333"
  env["CDPILOT_LOG"] = "0"
  runner_code = (
    "import os, sys; "
    "sys.path.insert(0, sys.argv[1]); "
    "import cdpilot; "
    "wfd = int(sys.argv[3]); "
    "os.write(wfd, b'R'); "
    "os.close(wfd); "
    "cdpilot.cmd_canvas_stream(sys.argv[2])"
  )
  proc = subprocess.Popen(
    [sys.executable, "-I", "-c", runner_code, SRC_DIR, canvas_name, str(ready_w)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    pass_fds=(ready_w,),
  )
  os.close(ready_w)
  try:
    ack = os.read(ready_r, 1)
    if ack != b"R":
      raise RuntimeError("stream subprocess failed before ready handshake")
  finally:
    os.close(ready_r)

  time.sleep(0.010)
  total_bytes = 0
  assert proc.stdin is not None
  for chunk, delay_s in tokens:
    proc.stdin.write(chunk)
    proc.stdin.flush()
    total_bytes += len(chunk)
    wait = pause_s if delay_s < 0 else delay_s
    if wait > 0:
      time.sleep(wait)
  proc.stdin.close()
  proc.stdin = None
  out_b, err_b = proc.communicate(timeout=30.0)
  return (
    proc.returncode,
    out_b.decode("utf-8", errors="replace").strip(),
    err_b.decode("utf-8", errors="replace").strip(),
    total_bytes,
  )


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Benchmark cdpilot canvas stream paint latency.")
  parser.add_argument("--name", default="main", help="Canvas name (default: main)")
  parser.add_argument("--fake", action="store_true", help="Run against an in-process fake host")
  parser.add_argument("--fake-ms", type=float, default=2.0, help="Fake host patch delay in ms")
  parser.add_argument(
    "--cdp",
    default="",
    help="Run against shared headless Chrome host:port (e.g. 127.0.0.1:9333)",
  )
  parser.add_argument("--blocks", type=int, default=62, help="Synthetic HTML card blocks (62 ~= 20.5 KB)")
  parser.add_argument("--pause-ms", type=float, default=55.0, help="Pause after each </section> in ms")
  parser.add_argument("--out", default="", help="Output JSON path")
  parser.add_argument("--gate", action="store_true", help="Enforce CI latency & load gates")
  args = parser.parse_args(argv)

  if args.fake and args.cdp:
    print("canvas_bench: choose at most one of --fake or --cdp", file=sys.stderr)
    return 2

  mode = "fake" if args.fake else ("cdp" if args.cdp else "live")
  tokens = build_synthetic_tokens(args.blocks)
  pause_s = max(0.0, args.pause_ms / 1000.0)
  cores = os.cpu_count() or 1
  max_attempts = 3 if (args.gate and mode != "fake") else 1

  upstream_sock: str | None = None
  browser_ver = "fake"
  if mode == "live":
    try:
      upstream_sock, ping_info = resolve_live_upstream(args.name)
      browser_ver = f"canvas-host-v{ping_info.get('v', '?')}"
    except Exception as exc:
      print(f"canvas_bench: {exc}", file=sys.stderr)
      return 1

  cdp_backend: CDPBenchBackend | None = None
  if mode == "cdp":
    cdp_backend = CDPBenchBackend(args.cdp, args.name)
    cdp_backend.start()
    browser_ver = cdp_backend.browser_version

  result_doc: dict[str, Any] = {}
  try:
    for attempt in range(1, max_attempts + 1):
      load_before = os.getloadavg()
      uptime_before = read_uptime()
      with tempfile.TemporaryDirectory(prefix="cb-", dir="/tmp") as tmp_dir:
        tap_profile = os.path.join(tmp_dir, "p")
        sock_path = os.path.join(tap_profile, "canvas", f"{args.name}.sock")
        tap = RecordingCanvasTap(
          sock_path=sock_path,
          mode=mode,
          fake_ms=args.fake_ms,
          upstream_sock=upstream_sock,
          cdp_backend=cdp_backend,
        )
        tap.start()
        try:
          rc, stdout_s, stderr_s, sent_bytes = run_single_stream(
            args.name, tmp_dir, tap_profile, tokens, pause_s
          )
        finally:
          tap.stop()

      if rc != 0:
        print(f"canvas_bench: stream exited {rc}: {stderr_s}", file=sys.stderr)
        return rc or 1

      load_after = os.getloadavg()
      uptime_after = read_uptime()
      peak_1m = max(load_before[0], load_after[0])
      load_valid = peak_1m <= (4.0 * cores)

      paint_deltas = [float(r["paint_minus_cli_ms"]) for r in tap.records]
      reply_deltas = [float(r["host_reply_ms"]) for r in tap.records]
      paint_stats = summarize_series(paint_deltas)
      reply_stats = summarize_series(reply_deltas)

      gate_pass = (
        paint_stats["p50"] <= 100.0
        and paint_stats["p95"] <= 200.0
        and (load_valid or mode == "fake")
      )
      if mode == "fake":
        gate_status = "fake (report-only)"
      elif not load_valid:
        gate_status = "load-invalid" if args.gate else "load-invalid (report-only)"
      elif gate_pass:
        gate_status = "pass"
      else:
        gate_status = "fail" if args.gate else "over-threshold (report-only)"

      today = dt.date.today().isoformat()
      result_doc = {
        "date": today,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": mode,
        "browser": browser_ver,
        "canvas_name": args.name,
        "attempt": attempt,
        "doc_bytes": sent_bytes,
        "stream_summary": stdout_s,
        "uptime": {
          "before": uptime_before,
          "after": uptime_after,
          "load_before": [round(x, 2) for x in load_before],
          "load_after": [round(x, 2) for x in load_after],
          "cpu_cores": cores,
          "load_threshold_1m": 4 * cores,
          "load_valid": load_valid,
        },
        "gate": {
          "target_p50_ms": 100.0,
          "target_p95_ms": 200.0,
          "enforced": bool(args.gate),
          "status": gate_status,
        },
        "summary": {
          "patches": len(tap.records),
          "paint_minus_cli_ms": paint_stats,
          "host_reply_ms": reply_stats,
        },
        "patches": tap.records,
      }
      if load_valid or attempt == max_attempts:
        break
  finally:
    if cdp_backend is not None:
      cdp_backend.close()

  today = dt.date.today().isoformat()
  out_path = args.out or os.path.join(DEFAULT_OUT_DIR, f"canvas-bench-{today}.json")
  os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
  with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result_doc, f, indent=2, ensure_ascii=False)
    f.write("\n")

  s_paint = result_doc["summary"]["paint_minus_cli_ms"]
  s_reply = result_doc["summary"]["host_reply_ms"]
  up = result_doc["uptime"]
  print(
    f"canvas-bench ({mode}, {result_doc['browser']}): "
    f"patches={result_doc['summary']['patches']} bytes={result_doc['doc_bytes']} "
    f"t_paint-t_cli p50={s_paint['p50']}ms p95={s_paint['p95']}ms "
    f"reply p50={s_reply['p50']}ms "
    f"load1m={up['load_before'][0]}->{up['load_after'][0]} "
    f"(valid={up['load_valid']}) gate={result_doc['gate']['status']} "
    f"out={out_path}"
  )

  if args.gate and result_doc["gate"]["status"] != "pass":
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())

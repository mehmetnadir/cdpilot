#!/usr/bin/env python3.13
"""Session-log error-class report for warm-process gate 3.

Run:
  python3.13 -I .claude/docs/olcum/gunluk-hata-sinifi.py [--since YYYY-MM-DD] [--top N] [--json]

Reads $CDPILOT_HOME/projects/*/log/YYYY-MM-DD.jsonl (default ~/.cdpilot) and
groups calls and non-zero exits across cli-fresh, cli-warm, mcp-fresh, mcp-warm.
Never prints args, urls, titles, summaries, file paths or project names.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import TypedDict

PATHS: tuple[str, ...] = ("cli-fresh", "cli-warm", "mcp-fresh", "mcp-warm")
FRESH_PATHS: frozenset[str] = frozenset({"cli-fresh", "mcp-fresh"})
WARM_PATHS: frozenset[str] = frozenset({"cli-warm", "mcp-warm"})
SESSION_DEF = "distinct (project, YYYY-MM-DD) pairs with >=1 call on that path"

DAY_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SAFE_TS_RE = re.compile(r"^[0-9T:.\-+Z ]{1,40}$")
URL_RE = re.compile(
    r"(?:https?|wss?|file|ftp|chrome(?:-extension)?)://[^\s\"'<>)\]]+"
    r"|(?:data|blob):[^\s\"'<>)\]]+",
    re.I,
)
WIN_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s\"'<>()\[\]:,;|]+")
UNIX_PATH_RE = re.compile(
    r"(?:~|\.\.?)(?:/[^\s\"'<>()\[\]:,;|]+)+"
    r"|(?<![A-Za-z0-9_<])/(?:[^\s\"'<>()\[\]:,;|/]+/)*[^\s\"'<>()\[\]:,;|/]+"
)
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"
)
HEX0X_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
HEX_TOKEN_RE = re.compile(
    r"\b(?:(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{8,}"
    r"|(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{6,})\b"
)
DIGIT_RE = re.compile(r"\d+")

SUBCMDS: frozenset[str] = frozenset({
    "observe", "act", "flow", "save", "run", "list", "show", "delete",
    "reset", "stats", "start", "stop", "status", "query", "config", "set",
    "clear", "load", "add", "remove", "call", "headers", "block", "mock",
    "full", "summary", "json", "md", "table",
})


class TopClassItem(TypedDict):
    class_id: str
    exit: int | str
    error: str
    count: int
    cmd: str


class PathSummary(TypedDict):
    calls: int
    sessions: int
    errors: int
    error_rate: float
    top_classes: list[dict[str, object]]


def _sub_keep_punct(pat: re.Pattern[str], repl: str, text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        tok = match.group(0)
        core = tok.rstrip(".,;:!?")
        if not core or core in ("/", "~", ".", ".."):
            return tok
        return repl + tok[len(core):]

    return pat.sub(_replace, text)


def _normalise_spans(text: str) -> str:
    text = _sub_keep_punct(URL_RE, "<url>", text)
    text = _sub_keep_punct(WIN_PATH_RE, "<path>", text)
    text = _sub_keep_punct(UNIX_PATH_RE, "<path>", text)
    text = UUID_RE.sub("<hex>", text)
    text = HEX0X_RE.sub("<hex>", text)
    text = HEX_TOKEN_RE.sub("<hex>", text)
    text = DIGIT_RE.sub("<n>", text)
    return text


def _arg_candidates(raw_args: object) -> list[str]:
    if not isinstance(raw_args, list):
        return []
    vals: list[str] = []
    for idx, item in enumerate(raw_args):
        if not isinstance(item, str) or not item:
            continue
        if item.startswith("-"):
            if "=" in item:
                _, rhs = item.split("=", 1)
                if rhs:
                    vals.append(rhs)
            continue
        if idx < 2 and item in SUBCMDS:
            continue
        vals.append(item)
        if item[:1] in "#." and len(item) >= 5:
            vals.append(item.lstrip("#."))
        if ">>>" in item:
            for part in (p.strip() for p in item.split(">>>") if p.strip()):
                vals.append(part)
                if part[:1] in "#." and len(part) >= 5:
                    vals.append(part.lstrip("#."))
    return sorted(set(vals), key=len, reverse=True)


def normalise_error(raw_error: object, entry: dict[str, object]) -> str:
    text = " ".join(str(raw_error or "").split())
    if not text:
        return "(no error)"
    text = _sub_keep_punct(URL_RE, "<url>", text)
    raw_url = entry.get("url")
    if isinstance(raw_url, str) and len(raw_url) >= 4:
        text = text.replace(raw_url, "<url>")
    for val in _arg_candidates(entry.get("args")):
        text = text.replace(f"'{val}'", "'<arg>'").replace(f'"{val}"', '"<arg>"')
        for sub in re.split(r"[#.>\[\]=:\s]+", val):
            if len(sub) >= 3 and sub not in SUBCMDS:
                text = text.replace(f"'{sub}'", "'<arg>'").replace(f'"{sub}"', '"<arg>"')
        has_punct = any(ch in val for ch in "#./:=_-@[]")
        if has_punct or (len(val) >= 6 and not val.islower()):
            pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(val) + r"(?![A-Za-z0-9_])")
            text = pat.sub("<arg>", text)
    text = _normalise_spans(text)
    return text[:60].rstrip() or "(no error)"


def safe_cmd(raw_cmd: object) -> str:
    cmd = " ".join(str(raw_cmd or "").split())
    if not cmd:
        return "(unknown)"
    return _normalise_spans(cmd)[:40].rstrip() or "(unknown)"


def safe_ts(raw_ts: object, fallback_day: str) -> str:
    ts = str(raw_ts or "").strip()
    if SAFE_TS_RE.fullmatch(ts):
        return ts
    return fallback_day


def valid_day(value: str) -> bool:
    if not DATE_RE.fullmatch(value):
        return False
    try:
        datetime.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def parse_cli(argv: list[str]) -> tuple[Path, str | None, int, bool]:
    home_str = os.environ.get("CDPILOT_HOME") or os.path.expanduser("~/.cdpilot")
    since: str | None = None
    top_n = 5
    as_json = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--json":
            as_json = True
        elif arg == "--since" or arg.startswith("--since="):
            if arg == "--since":
                i += 1
                raw = argv[i] if i < len(argv) else ""
            else:
                raw = arg.split("=", 1)[1]
            if not valid_day(raw):
                print(f"gunluk-hata-sinifi: invalid --since {raw!r} (expected YYYY-MM-DD)",
                      file=sys.stderr)
                sys.exit(2)
            since = raw
        elif arg == "--top" or arg.startswith("--top="):
            if arg == "--top":
                i += 1
                raw = argv[i] if i < len(argv) else ""
            else:
                raw = arg.split("=", 1)[1]
            if not raw.isdigit() or int(raw) < 1:
                print(f"gunluk-hata-sinifi: invalid --top {raw!r}", file=sys.stderr)
                sys.exit(2)
            top_n = int(raw)
        elif arg == "--home" or arg.startswith("--home="):
            if arg == "--home":
                i += 1
                home_str = argv[i] if i < len(argv) else ""
            else:
                home_str = arg.split("=", 1)[1]
            if not home_str:
                print("gunluk-hata-sinifi: --home requires a path", file=sys.stderr)
                sys.exit(2)
        elif arg in ("-h", "--help"):
            print(__doc__ or "")
            sys.exit(0)
        else:
            print(f"gunluk-hata-sinifi: unknown option {arg!r}", file=sys.stderr)
            sys.exit(2)
        i += 1
    return Path(home_str), since, top_n, as_json


def collect(home: Path, since: str | None, top_n: int) -> dict[str, object]:
    calls: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    sessions: dict[str, set[tuple[str, str]]] = {p: set() for p in PATHS}
    all_sessions: set[tuple[str, str]] = set()
    warm_sessions: set[tuple[str, str]] = set()
    path_classes: dict[str, Counter[str]] = {p: Counter() for p in PATHS}
    class_meta: dict[str, tuple[int | str, str]] = {}
    class_cmd: dict[str, str] = {}
    class_warm_ts: dict[str, str] = {}

    projects_dir = home / "projects"
    if projects_dir.is_dir():
        for proj_dir in sorted(projects_dir.iterdir(), key=lambda p: p.name):
            log_dir = proj_dir / "log"
            if not log_dir.is_dir():
                continue
            proj_key = proj_dir.name
            for log_file in sorted(log_dir.iterdir(), key=lambda p: p.name):
                m = DAY_FILE_RE.fullmatch(log_file.name)
                if not m or not log_file.is_file():
                    continue
                file_day = m.group(1)
                try:
                    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    ts_head = str(entry.get("ts") or "")[:10]
                    day = ts_head if valid_day(ts_head) else file_day
                    if since is not None and day < since:
                        continue
                    is_mcp = str(entry.get("via") or "").startswith("mcp")
                    is_warm = bool(entry.get("warm"))
                    bucket = ("mcp" if is_mcp else "cli") + "-" + ("warm" if is_warm else "fresh")
                    calls[bucket] += 1
                    sess_key = (proj_key, day)
                    sessions[bucket].add(sess_key)
                    all_sessions.add(sess_key)
                    if is_warm:
                        warm_sessions.add(sess_key)
                    code = entry.get("exit")
                    if code not in (0, None):
                        code_val: int | str = code if isinstance(code, int) else str(code)
                        norm_err = normalise_error(entry.get("error"), entry)
                        cls_key = f"exit={code_val}: {norm_err}"
                        errors[bucket] += 1
                        path_classes[bucket][cls_key] += 1
                        if cls_key not in class_meta:
                            class_meta[cls_key] = (code_val, norm_err)
                            class_cmd[cls_key] = safe_cmd(entry.get("cmd"))
                        if is_warm and cls_key not in class_warm_ts:
                            class_warm_ts[cls_key] = safe_ts(entry.get("ts"), day)

    fresh_seen = {c for p in FRESH_PATHS for c, n in path_classes[p].items() if n > 0}
    warm_seen = {c for p in WARM_PATHS for c, n in path_classes[p].items() if n > 0}
    warm_only_keys = sorted(
        warm_seen - fresh_seen,
        key=lambda c: (-sum(path_classes[p][c] for p in WARM_PATHS), c),
    )

    paths_out: dict[str, PathSummary] = {}
    for p in PATHS:
        c_cnt = calls[p]
        e_cnt = errors[p]
        rate = round(e_cnt / c_cnt, 6) if c_cnt else 0.0
        ranked = sorted(path_classes[p].items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        top_list: list[dict[str, object]] = []
        for cls_key, cnt in ranked:
            code_val, norm_err = class_meta[cls_key]
            top_list.append({
                "class": cls_key,
                "exit": code_val,
                "error": norm_err,
                "count": cnt,
                "cmd": class_cmd[cls_key],
            })
        paths_out[p] = {
            "calls": c_cnt,
            "sessions": len(sessions[p]),
            "errors": e_cnt,
            "error_rate": rate,
            "top_classes": top_list,
        }

    warm_only_out: list[dict[str, object]] = []
    for cls_key in warm_only_keys:
        code_val, norm_err = class_meta[cls_key]
        per_warm = {p: path_classes[p][cls_key] for p in WARM_PATHS if path_classes[p][cls_key] > 0}
        warm_only_out.append({
            "class": cls_key,
            "exit": code_val,
            "error": norm_err,
            "count": sum(per_warm.values()),
            "paths": per_warm,
            "cmd": class_cmd[cls_key],
            "example_ts": class_warm_ts.get(cls_key, ""),
        })

    total_calls = sum(calls.values())
    total_errors = sum(errors.values())
    return {
        "since": since,
        "session_definition": SESSION_DEF,
        "totals": {
            "calls": total_calls,
            "sessions": len(all_sessions),
            "warm_sessions": len(warm_sessions),
            "errors": total_errors,
            "error_rate": round(total_errors / total_calls, 6) if total_calls else 0.0,
        },
        "paths": paths_out,
        "gate3_warm_only_count": len(warm_only_out),
        "warm_only_classes": warm_only_out,
    }


def format_report(data: dict[str, object]) -> str:
    since = data["since"] or "all"
    totals = data["totals"]
    assert isinstance(totals, dict)
    paths = data["paths"]
    assert isinstance(paths, dict)
    warm_only = data["warm_only_classes"]
    assert isinstance(warm_only, list)

    t_calls = int(totals["calls"])
    t_sess = int(totals["sessions"])
    t_warm_sess = int(totals["warm_sessions"])
    t_errs = int(totals["errors"])
    t_rate = float(totals["error_rate"]) * 100.0

    out = [
        f"cdpilot session-log error classes (since: {since})",
        f"sessions: {SESSION_DEF}",
        f"totals: {t_calls} calls, {t_sess} sessions ({t_warm_sess} warm), "
        f"{t_errs} errors ({t_rate:.2f}%)",
        "",
        f"{'PATH':<10}  {'CALLS':>8}  {'SESSIONS':>8}  {'ERRORS':>8}  {'ERR_RATE':>8}",
    ]
    for p in PATHS:
        row = paths[p]
        assert isinstance(row, dict)
        pct = float(row["error_rate"]) * 100.0
        out.append(
            f"{p:<10}  {int(row['calls']):>8}  {int(row['sessions']):>8}  "
            f"{int(row['errors']):>8}  {pct:>7.2f}%"
        )

    out.append("")
    out.append("top error classes per path:")
    for p in PATHS:
        row = paths[p]
        assert isinstance(row, dict)
        tops = row["top_classes"]
        assert isinstance(tops, list)
        out.append(f"  [{p}]")
        if not tops:
            out.append("    (none)")
            continue
        for item in tops:
            assert isinstance(item, dict)
            out.append(
                f"    {int(item['count']):>5}  exit={item['exit']}  "
                f"{item['error']}  (cmd: {item['cmd']})"
            )

    out.append("")
    out.append(
        f"warm-only error classes (gate 3): {data['gate3_warm_only_count']} "
        f"(warm sessions: {t_warm_sess})"
    )
    if not warm_only:
        out.append("  (none)")
    else:
        for item in warm_only:
            assert isinstance(item, dict)
            per_p = item["paths"]
            assert isinstance(per_p, dict)
            where = ", ".join(f"{k}={v}" for k, v in per_p.items())
            out.append(
                f"  {int(item['count']):>5}  exit={item['exit']}  {item['error']}  "
                f"({where}; cmd: {item['cmd']}; example_ts: {item['example_ts']})"
            )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    home, since, top_n, as_json = parse_cli(sys.argv[1:] if argv is None else argv)
    report = collect(home, since, top_n)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

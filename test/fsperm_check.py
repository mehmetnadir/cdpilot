"""File-permission checks for cdpilot (no browser). Usage: fsperm_check.py <path to cdpilot.py>.
Prints one JSON object {scenario: "ok" | "FAIL: ..."}; a crash is reported as FAIL too."""
import asyncio, contextlib, importlib.util, inspect, io, json, os, re, shutil, stat, subprocess, sys
import tempfile, traceback

PY = sys.argv[1]
ROOT = tempfile.mkdtemp(prefix="cdpilot-fsperm-")
os.umask(0o022)
os.environ["CDPILOT_HOME"] = os.path.join(ROOT, "newhome", "deeper")
os.environ["CDPILOT_LOG"] = "0"
spec = importlib.util.spec_from_file_location("cdpilot_under_test", PY)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def home_mode():
    with mod._registry_lock():
        pass
    check(mode(mod.CDPILOT_HOME) == 0o700, f"fresh CDPILOT_HOME is {oct(mode(mod.CDPILOT_HOME))}")
    # an existing user-chosen directory keeps its mode
    keep = os.path.join(ROOT, "keep")
    os.mkdir(keep, 0o755)
    os.chmod(keep, 0o755)
    mod.REGISTRY_FILE = os.path.join(keep, "registry.json")
    with mod._registry_lock():
        pass
    check(mode(keep) == 0o755, f"existing directory changed to {oct(mode(keep))}")


def watch_frame():
    d = os.path.join(ROOT, "watchproj", "watch", "frames")
    mod._makedirs_private(d)
    check(mode(d) == 0o700, f"frames dir {oct(mode(d))}")
    check(mode(os.path.dirname(d)) == 0o700, f"watch dir {oct(mode(os.path.dirname(d)))}")
    f = os.path.join(d, "1.jpg")
    with mod._open_output_fd(f) as fh:
        fh.write(b"jpeg")
    check(mode(f) == 0o600, f"frame file {oct(mode(f))}")
    idx = os.path.join(d, "index.jsonl")
    with mod._open_output_fd(idx, append=True) as fh:
        fh.write(b"a\n")
    with mod._open_output_fd(idx, append=True) as fh:
        fh.write(b"b\n")
    check(open(idx, "rb").read() == b"a\nb\n" and mode(idx) == 0o600, "index append")
    src = open(PY).read()
    check("with _open_output_fd(fpath) as f:" in src, "the watch daemon writes frames with the private helper")


def cookies_export():
    out = os.path.join(ROOT, "cookies-out.json")

    async def fake_send(ws, cmds, *a, **k):
        return {1: {"cookies": [{"name": "sid", "value": "secret", "domain": "example.com"}]}}

    mod.get_page_ws = lambda *a, **k: ("ws://fake", None)
    mod.cdp_send = fake_send
    with contextlib.redirect_stdout(io.StringIO()):
        asyncio.run(mod.cmd_cookies("save", out))
    check(json.load(open(out))[0]["name"] == "sid", "export content")
    check(mode(out) == 0o600, f"cookie export {oct(mode(out))}")


def cookies_export_existing():
    # an export file that already exists (0644, e.g. from an earlier version) becomes 0600
    out = os.path.join(ROOT, "cookies-existing.json")
    with open(out, "w") as fh:
        fh.write("old content")
    os.chmod(out, 0o644)

    async def fake_send(ws, cmds, *a, **k):
        return {1: {"cookies": [{"name": "sid", "value": "secret", "domain": "example.com"}]}}

    mod.get_page_ws = lambda *a, **k: ("ws://fake", None)
    mod.cdp_send = fake_send
    with contextlib.redirect_stdout(io.StringIO()):
        asyncio.run(mod.cmd_cookies("save", out))
    check(json.load(open(out))[0]["name"] == "sid", "export content")
    check(mode(out) == 0o600, f"existing cookie export file stays {oct(mode(out))}")


def cli_home():
    # Real commands in an empty CDPILOT_HOME (CDPILOT_LOG left on): the home, projects/,
    # projects/<id>/ and every directory created under the home must be 0700.
    node = os.environ.get("CDPILOT_TEST_NODE") or shutil.which("node")
    launcher = os.path.join(os.path.dirname(os.path.abspath(PY)), "..", "bin", "cdpilot.js")
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "fsperm", "version": "0"}}}) + "\n"
    runs = [([sys.executable, PY, "proxy", "list"], None),
            ([sys.executable, PY, "status"], None),
            ([sys.executable, PY, "tabs"], None),
            ([sys.executable, PY, "mcp"], init)]
    if node and os.path.isfile(launcher):
        runs += [([node, launcher, "proxy", "list"], None),
                 ([node, launcher, "tabs"], None)]
    for argv, stdin in runs:
        home = os.path.join(tempfile.mkdtemp(prefix="cdpilot-fsperm-cli-"), "home")
        env = {k: v for k, v in os.environ.items()
               if k not in ("CDPILOT_LOG", "CDPILOT_PROFILE", "CDPILOT_MCP_SESSION")}
        env.update(CDPILOT_HOME=home, CDP_PORT="19572", CDPILOT_NO_AUTOLAUNCH="1",
                   CDPILOT_PROJECT_ID="fsperm-cli", CDPILOT_DAEMON="0",
                   CDPILOT_PYTHON=sys.executable)
        r = subprocess.run(argv, input=stdin or "", env=env, capture_output=True, text=True,
                           timeout=60)
        label = os.path.basename(argv[0]) + " " + " ".join(argv[2:])
        projects = os.path.join(home, "projects")
        ids = os.listdir(projects) if os.path.isdir(projects) else []
        check(os.path.isdir(home), f"{label}: home not created (exit {r.returncode})")
        # Python: projects/<id>/ (last-activity, session log). The Node launcher derives
        # the id from the cwd: there every directory found is checked.
        check(argv[0] == node or "fsperm-cli" in ids,
              f"{label}: no projects/fsperm-cli (exit {r.returncode}: {r.stderr[-200:]!r})")
        for top, dirs, _files in os.walk(home):
            for d in [top] + [os.path.join(top, x) for x in dirs]:
                if not os.path.islink(d):
                    rel = os.path.relpath(d, os.path.dirname(home))
                    check(mode(d) == 0o700, f"{label}: {rel} is {oct(mode(d))}")


def hardlink_output():
    # A hard link to one of your own files planted at the output path (another local user can
    # `ln ~you/.zshrc /tmp/shot.png` on one volume) is refused; the linked file stays unchanged.
    d = os.path.join(ROOT, "hardlink")
    os.mkdir(d)
    victim = os.path.join(d, "victim-rc")
    with open(victim, "w") as fh:
        fh.write("keep me")
    link = os.path.join(d, "shot.png")
    os.link(victim, link)
    for append in (False, True):
        try:
            fh = mod._open_output_fd(link, append=append)
            fh.close()
            raise AssertionError(f"hard link accepted (append={append})")
        except OSError:
            pass
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            mod._open_output(link)
        raise AssertionError("hard link accepted by _open_output")
    except SystemExit as e:
        check(e.code == 1 and "Cannot write" in err.getvalue() and "hard link" in err.getvalue(),
              f"exit {e.code} / {err.getvalue()!r}")
    check(open(victim).read() == "keep me", "hard-linked file was written")


def output_call_sites():
    # Each output writer goes through the helper (and none opens its file with a plain open()).
    sites = {"cmd_shot": "_open_output(", "cmd_shot_annotated": "_open_output(",
             "cmd_pdf": "_open_output(", "cmd_cookies": "_open_output(",
             "cmd_debug": "_open_output(", "cmd_describe": "_open_output(",
             "_watch_save_state": "_open_output_fd(", "_watch_daemon_run": "_open_output_fd("}
    plain_write = re.compile(r"(?<![\w.])open\([^)\n]*['\"][wax]b?\+?['\"]")
    for fn, helper in sites.items():
        src = inspect.getsource(getattr(mod, fn))
        check(helper in src, f"{fn} does not write through {helper.rstrip('(')}")
        m = plain_write.search(src)
        check(not m, f"{fn} opens a file for writing without the helper: {m and m.group(0)!r}")


def output_helper():
    d = os.path.join(ROOT, "shared")
    os.mkdir(d)
    mine = os.path.join(d, "shot.png")
    for data in (b"first-long-content", b"2nd"):
        with mod._open_output(mine) as fh:
            fh.write(data)
    check(open(mine, "rb").read() == b"2nd", "overwrite of our own file (truncates)")
    check(mode(mine) == 0o600, f"new output {oct(mode(mine))}")
    # symlink is refused, the target stays untouched
    target = os.path.join(d, "victim.txt")
    open(target, "w").write("keep")
    link = os.path.join(d, "link.png")
    os.symlink(target, link)
    try:
        mod._open_output_fd(link)
        raise AssertionError("symlink accepted")
    except OSError:
        pass
    check(open(target).read() == "keep", "symlink target was written")
    # a file that belongs to someone else is refused (simulated with getuid)
    other = os.path.join(d, "other.png")
    open(other, "w").write("theirs")
    real = os.getuid
    os.getuid = lambda: real() + 1
    try:
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                mod._open_output(other)
            raise AssertionError("foreign file accepted")
        except SystemExit as e:
            check(e.code == 1 and "Cannot write" in err.getvalue(), f"exit {e.code} / {err.getvalue()!r}")
    finally:
        os.getuid = real
    check(open(other).read() == "theirs", "foreign file was truncated")
    # a FIFO or other non-regular file is refused too
    fifo = os.path.join(d, "fifo.png")
    os.mkfifo(fifo)
    try:
        fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        try:
            mod._open_output_fd(fifo)
            raise AssertionError("fifo accepted")
        except OSError:
            pass
        finally:
            os.close(fd)
    except AttributeError:
        pass


res = {}
for name, fn in [("home_mode", home_mode), ("watch_frame", watch_frame),
                 ("cookies_export", cookies_export),
                 ("cookies_export_existing", cookies_export_existing),
                 ("cli_home", cli_home), ("hardlink_output", hardlink_output),
                 ("output_call_sites", output_call_sites), ("output_helper", output_helper)]:
    try:
        fn()
        res[name] = "ok"
    except BaseException:
        res[name] = "FAIL: " + traceback.format_exc().strip().splitlines()[-1]
print(json.dumps(res))

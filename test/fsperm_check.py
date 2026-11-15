"""File-permission checks for cdpilot (no browser). Usage: fsperm_check.py <path to cdpilot.py>.
Prints one JSON object {scenario: "ok" | "FAIL: ..."}; a crash is reported as FAIL too."""
import asyncio, contextlib, importlib.util, io, json, os, stat, sys, tempfile, traceback

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
    src = open(PY).read()
    check(src.count("_open_output(") >= 6, "shot, shot annotated, pdf, cookies, debug, describe use the helper")


res = {}
for name, fn in [("home_mode", home_mode), ("watch_frame", watch_frame),
                 ("cookies_export", cookies_export), ("output_helper", output_helper)]:
    try:
        fn()
        res[name] = "ok"
    except BaseException:
        res[name] = "FAIL: " + traceback.format_exc().strip().splitlines()[-1]
print(json.dumps(res))

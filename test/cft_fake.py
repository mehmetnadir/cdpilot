"""Chrome for Testing harness for test.js (no network, no browser).

    python cft_fake.py <path/to/cdpilot.py> <scenario>

A fake of the CfT JSON endpoints and download bucket runs in a thread on
127.0.0.1 (a port in 59570-59599) and logs every request it gets.

  install    `browser install chrome-for-testing` (the real CLI, as a child
             process) for mac-arm64 / linux64 / win64 zips, channel, version,
             milestone and bad-argument cases, then `browser status` and
             `browser chrome-for-testing`.
  integrity  downloads that must be refused: md5 mismatch, truncated body,
             no Content-Length, a zip entry or symlink escaping the target.
  select     browser choice in-process (cdpilot.py imported): branded Chrome
             -> Chrome for Testing only with dev extensions registered and CfT
             installed; the ext-install hint; bin/cdpilot.js's CHROME_BIN guess;
             and that none of it made a single request (never auto-downloads).

Prints one JSON object; a scenario that raises reports {"error": traceback}.
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import traceback
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CDPILOT = os.path.abspath(sys.argv[1])
SCENARIO = sys.argv[2] if len(sys.argv) > 2 else 'install'
PLATS = ('mac-arm64', 'linux64', 'win64')
FAKE_BIN = b'#!/bin/sh\necho "Google Chrome for Testing (fake)"\n'


def _entry(zf, name, data=b'', mode=0o100644):
    info = zipfile.ZipInfo(name, date_time=(2026, 9, 28, 0, 0, 0))
    info.create_system = 3  # Unix: external_attr carries the mode
    info.external_attr = (mode & 0xFFFF) << 16
    zf.writestr(info, data)


def make_zip(plat, evil=None):
    buf = io.BytesIO()
    top = f'chrome-{plat}'
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        _entry(zf, f'{top}/', mode=0o040755)
        if plat.startswith('mac'):
            app = f'{top}/Google Chrome for Testing.app/Contents'
            _entry(zf, f'{app}/MacOS/Google Chrome for Testing', FAKE_BIN, 0o100755)
            fw = f'{app}/Frameworks/Fake.framework'
            _entry(zf, f'{fw}/Versions/A/Fake', b'framework', 0o100755)
            _entry(zf, f'{fw}/Versions/Current', b'A', 0o120777)
            _entry(zf, f'{fw}/Fake', b'Versions/Current/Fake', 0o120777)
        elif plat.startswith('win'):
            _entry(zf, f'{top}/chrome.exe', b'MZ fake', 0o100755)
        else:
            _entry(zf, f'{top}/chrome', FAKE_BIN, 0o100755)
            _entry(zf, f'{top}/locales/en-US.pak', b'pak')
        if evil == 'slip':
            _entry(zf, '../escaped.txt', b'x')
        elif evil == 'symlink':
            _entry(zf, f'{top}/evil-link', b'../../../../outside', 0o120777)
    return buf.getvalue()


class Fake:
    """Routes: path -> (status, headers list, body, send_length)."""

    def __init__(self):
        self.routes, self.log = {}, []
        handler = self._handler()
        self.server = None
        for port in range(59570, 59600):
            try:
                self.server = ThreadingHTTPServer(('127.0.0.1', port), handler)
                break
            except OSError:
                continue
        if not self.server:
            raise RuntimeError('no free port in 59570-59599')
        self.port = self.server.server_address[1]
        self.base = f'http://127.0.0.1:{self.port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake.log.append(self.path)
                route = fake.routes.get(self.path)
                if not route:
                    self.send_response(404)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                status, headers, body, length = route
                self.send_response(status)
                for k, v in headers:
                    self.send_header(k, v)
                if length is not None:
                    self.send_header('Content-Length', str(length))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        return H

    def json(self, path, obj):
        body = json.dumps(obj).encode()
        self.routes[path] = (200, [('Content-Type', 'application/json')], body, len(body))

    def zip(self, ver, plat, body, md5=None, length='ok'):
        path = f'/dl/{ver}/{plat}/chrome-{plat}.zip'
        md5 = md5 or base64.b64encode(hashlib.md5(body).digest()).decode()
        headers = [('Content-Type', 'application/zip'), ('x-goog-hash', 'crc32c=AAAAAA=='),
                   ('x-goog-hash', f'md5={md5}')]
        n = {'ok': len(body), 'none': None, 'short': len(body) + 100}[length]
        self.routes[path] = (200, headers, body, n)
        return self.base + path

    def entry(self, ver, plats=PLATS, evil=None, body=None, md5=None, length='ok'):
        downloads = [{'platform': p,
                      'url': self.zip(ver, p, make_zip(p, evil) if body is None else body,
                                      md5=md5, length=length)}
                     for p in plats]
        return {'version': ver, 'revision': '1700000',
                'downloads': {'chrome': downloads, 'chromedriver': []}}

    def standard(self):
        stable, beta = self.entry('150.0.7000.1'), self.entry('151.0.7100.2')
        self.json('/last-known-good-versions-with-downloads.json', {
            'timestamp': '2026-09-28T00:00:00Z',
            'channels': {'Stable': dict(stable, channel='Stable'), 'Beta': dict(beta, channel='Beta')}})
        self.json('/149.0.6900.5.json', self.entry('149.0.6900.5'))
        self.json('/latest-versions-per-milestone-with-downloads.json', {
            'milestones': {'148': dict(self.entry('148.0.6800.3'), milestone='148')}})


def cli_env(home, fake, plat=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ('CHROME_BIN', 'CDPILOT_CHROME_BIN_AUTO', 'CDPILOT_TIMEOUT',
                        'CDPILOT_PROJECT_ID', 'CDPILOT_CFT_PLATFORM')}
    env.update(CDPILOT_HOME=home, CDPILOT_PROFILE=os.path.join(home, 'profile'),
               CDPILOT_LOG='0', CDP_PORT='59571', CDPILOT_NO_AUTOLAUNCH='1',
               CDPILOT_CFT_BASE_URL=fake.base, PYTHONIOENCODING='utf-8')
    if plat:
        env['CDPILOT_CFT_PLATFORM'] = plat
    return env


def cli(home, fake, *args, plat=None):
    r = subprocess.run([sys.executable, CDPILOT, *args], capture_output=True, text=True,
                       encoding='utf-8', timeout=120, env=cli_env(home, fake, plat))
    return {'rc': r.returncode, 'out': r.stdout, 'err': r.stderr}


def leftovers(home):
    root = os.path.join(home, 'browsers', 'chrome-for-testing')
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root) if n.startswith('.'))


def state(home):
    try:
        with open(os.path.join(home, 'browsers', 'chrome-for-testing', 'installed.json')) as f:
            return json.load(f)
    except OSError:
        return None


def scenario_install(fake):
    fake.standard()
    res = {'platforms': {}}
    for plat in PLATS:
        home = tempfile.mkdtemp(prefix=f'cdpilot-cft-{plat}-')
        fake.log.clear()
        r = cli(home, fake, 'browser', 'install', 'chrome-for-testing', plat=plat)
        st = state(home) or {}
        rec = (st.get('installs') or {}).get(st.get('current') or '') or {}
        binary = rec.get('path') or ''
        out = {'rc': r['rc'], 'err': r['err'][-600:], 'out': r['out'][-900:],
               'current': st.get('current'), 'rec_keys': sorted(rec),
               'platform': rec.get('platform'), 'channel': rec.get('channel'),
               'binary_rel': os.path.relpath(binary, home).replace(os.sep, '/') if binary else None,
               'binary_exists': os.path.isfile(binary),
               'exec': bool(binary) and os.name != 'nt' and os.access(binary, os.X_OK),
               'bytes_ok': rec.get('bytes') == len(make_zip(plat)),
               'leftovers': leftovers(home), 'requests': list(fake.log)}
        if plat.startswith('mac') and os.name != 'nt':
            fw = os.path.join(os.path.dirname(os.path.dirname(binary)), 'Frameworks', 'Fake.framework')
            out['symlinks'] = [os.path.islink(os.path.join(fw, 'Versions', 'Current')),
                               os.readlink(os.path.join(fw, 'Fake')) if os.path.islink(
                                   os.path.join(fw, 'Fake')) else None,
                               os.path.isfile(os.path.join(fw, 'Fake'))]
        res['platforms'][plat] = out
        if plat == 'linux64':
            res['home_linux'] = home
    home = res.pop('home_linux')
    # Installed already: no second download.
    fake.log.clear()
    again = cli(home, fake, 'browser', 'install', 'chrome-for-testing', plat='linux64')
    res['again'] = {'rc': again['rc'], 'out': again['out'], 'requests': list(fake.log)}
    # Status and selection.
    res['status'] = cli(home, fake, 'browser', 'status', plat='linux64')
    res['select'] = cli(home, fake, 'browser', 'chrome-for-testing', plat='linux64')
    with open(os.path.join(home, 'browser.json')) as f:
        res['pref'] = json.load(f)
    res['status_after'] = cli(home, fake, 'browser', plat='linux64')
    # Channel / version / milestone resolution (each in a fresh home).
    for key, args in (('beta', ['--channel', 'beta']), ('beta_eq', ['--channel=beta']),
                      ('version', ['--version', '149.0.6900.5']),
                      ('milestone', ['--version', '148'])):
        h = tempfile.mkdtemp(prefix='cdpilot-cft-v-')
        r = cli(h, fake, 'browser', 'install', 'chrome-for-testing', *args, plat='linux64')
        st = state(h) or {}
        res[key] = {'rc': r['rc'], 'err': r['err'][-400:], 'current': st.get('current'),
                    'channel': ((st.get('installs') or {}).get(st.get('current') or '') or {})
                    .get('channel', 'MISSING')}
    bad = {}
    for key, args in (('unknown_version', ['chrome-for-testing', '--version', '147.0.1.1']),
                      ('bad_version', ['chrome-for-testing', '--version', '../x']),
                      ('bad_channel', ['chrome-for-testing', '--channel', 'nightly']),
                      ('both', ['chrome-for-testing', '--channel', 'beta', '--version', '148']),
                      ('other_browser', ['firefox']),
                      ('no_platform_build', ['cft'])):
        h = tempfile.mkdtemp(prefix='cdpilot-cft-bad-')
        plat = 'linux-arm64' if key == 'no_platform_build' else 'linux64'
        r = cli(h, fake, 'browser', 'install', *args, plat=plat)
        bad[key] = {'rc': r['rc'], 'err': r['err'][-300:], 'installed': state(h) is not None,
                    'leftovers': leftovers(h)}
    res['bad'] = bad
    return res


def scenario_integrity(fake):
    body = make_zip('linux64')
    fake.json('/150.0.7000.66.json', fake.entry('150.0.7000.66', plats=('linux64',), md5='AAAAAAAAAAAAAAAAAAAAAA=='))
    fake.json('/150.0.7000.77.json', fake.entry('150.0.7000.77', plats=('linux64',), length='short'))
    fake.json('/150.0.7000.88.json', fake.entry('150.0.7000.88', plats=('linux64',), evil='slip'))
    fake.json('/150.0.7000.89.json', fake.entry('150.0.7000.89', plats=('linux64',), evil='symlink'))
    fake.json('/150.0.7000.99.json', fake.entry('150.0.7000.99', plats=('linux64',), length='none'))
    fake.json('/150.0.7000.55.json', fake.entry('150.0.7000.55', plats=('linux64',), body=b'not a zip at all'))
    assert body
    res = {}
    for key, ver in (('bad_md5', '150.0.7000.66'), ('truncated', '150.0.7000.77'),
                     ('zip_slip', '150.0.7000.88'), ('symlink_escape', '150.0.7000.89'),
                     ('no_length', '150.0.7000.99'), ('not_zip', '150.0.7000.55')):
        h = tempfile.mkdtemp(prefix='cdpilot-cft-int-')
        r = cli(h, fake, 'browser', 'install', 'chrome-for-testing', '--version', ver, plat='linux64')
        root = os.path.join(h, 'browsers', 'chrome-for-testing')
        res[key] = {'rc': r['rc'], 'err': r['err'][-400:], 'installed': state(h) is not None,
                    'version_dir': os.path.exists(os.path.join(root, ver)),
                    'leftovers': leftovers(h),
                    'escaped': os.path.exists(os.path.join(root, 'escaped.txt'))
                    or os.path.exists(os.path.join(h, 'browsers', 'escaped.txt'))}
    return res


def load_cdpilot(home):
    for k in ('CHROME_BIN', 'CDPILOT_CHROME_BIN_AUTO', 'CDPILOT_PROJECT_ID', 'CDPILOT_CFT_PLATFORM'):
        os.environ.pop(k, None)
    os.environ.update(CDPILOT_HOME=home, CDPILOT_PROFILE=os.path.join(home, 'profile'),
                      CDPILOT_LOG='0', CDP_PORT='59572')
    spec = importlib.util.spec_from_file_location('cdpilot_cft_under_test', CDPILOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scenario_select(fake):
    home = tempfile.mkdtemp(prefix='cdpilot-cft-select-')
    os.environ['CDPILOT_CFT_BASE_URL'] = fake.base
    mod = load_cdpilot(home)
    system = platform.system()
    bindir = os.path.join(home, 'apps', 'Google', 'bin')
    os.makedirs(bindir)
    chrome = os.path.join(bindir, 'chrome.exe' if os.name == 'nt' else 'Google Chrome')
    vivaldi = os.path.join(home, 'apps', 'vivaldi.exe' if os.name == 'nt' else 'Vivaldi')
    for p in (chrome, vivaldi):
        with open(p, 'w') as f:
            f.write('fake')
    have = {'chrome': True, 'vivaldi': False}

    def binaries():
        return {n: {system: ([chrome] if n == 'chrome' and have['chrome'] else
                             [vivaldi] if n == 'vivaldi' and have['vivaldi'] else [])}
                for n in ('brave', 'chrome', 'vivaldi', 'edge', 'chromium')}

    mod.shutil.which = lambda *a, **k: None  # no PATH browsers on the test machine
    plat = mod._cft_platform() or 'linux64'
    cft_dir = os.path.join(mod.CFT_ROOT, '150.0.7000.1')
    cft = os.path.join(cft_dir, mod._cft_binary_relpath(plat))
    os.makedirs(os.path.dirname(cft))
    with open(cft, 'w') as f:
        f.write('fake cft')
    record = {'current': '150.0.7000.1', 'installs': {'150.0.7000.1': {
        'version': '150.0.7000.1', 'platform': plat, 'path': cft, 'dir': cft_dir}}}
    ext = os.path.join(home, 'ext')
    os.makedirs(ext)
    with open(os.path.join(ext, 'manifest.json'), 'w') as f:
        json.dump({'manifest_version': 3, 'name': 'Fixture', 'version': '1.0'}, f)

    def setup(pref='auto', exts=False, cft_installed=True, chrome_installed=True, viv=False):
        have['chrome'], have['vivaldi'] = chrome_installed, viv
        mod.BROWSER_BINARIES = binaries()
        mod._CFT_SWAP_NOTED[0] = False
        mod.save_dev_extensions([ext] if exts else [])
        mod._atomic_write_json(mod.BROWSER_CONFIG_FILE, {'browser': pref})
        if cft_installed:
            mod._atomic_write_json(mod.CFT_STATE_FILE, record)
        elif os.path.exists(mod.CFT_STATE_FILE):
            os.remove(mod.CFT_STATE_FILE)

    def pick(**kw):
        setup(**kw)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            first = mod._find_browser()
            second = mod._find_browser()
        name = {chrome: 'chrome', vivaldi: 'vivaldi', cft: 'cft'}.get(first, first)
        return {'pick': name, 'same_twice': first == second,
                'info_lines': err.getvalue().count('using Chrome for Testing'), 'err': err.getvalue()}

    res = {
        'no_ext_pref_chrome': pick(pref='chrome'),
        'ext_pref_chrome': pick(pref='chrome', exts=True),
        'ext_pref_chrome_no_cft': pick(pref='chrome', exts=True, cft_installed=False),
        'ext_auto_only_chrome': pick(exts=True),
        'ext_auto_vivaldi': pick(exts=True, viv=True),
        'no_ext_auto': pick(),
        'pref_cft_no_ext': pick(pref='chrome-for-testing'),
        'pref_cft_missing': pick(pref='chrome-for-testing', cft_installed=False),
    }

    # bin/cdpilot.js's CHROME_BIN guess (CDPILOT_CHROME_BIN_AUTO=1) vs a user's CHROME_BIN.
    def refine(auto, **kw):
        setup(**kw)
        os.environ['CDPILOT_CHROME_BIN_AUTO'] = '1' if auto else ''
        with contextlib.redirect_stderr(io.StringIO()):
            got = mod._refine_wrapper_browser(chrome)
        os.environ.pop('CDPILOT_CHROME_BIN_AUTO', None)
        return {chrome: 'chrome', vivaldi: 'vivaldi', cft: 'cft'}.get(got, got)

    res['refine'] = {
        'guess_ext': refine(True, exts=True),
        'user_ext': refine(False, exts=True),
        'guess_no_ext': refine(True),
        'guess_pref_vivaldi': refine(True, pref='vivaldi', viv=True),
        'guess_ext_no_cft': refine(True, exts=True, cft_installed=False),
    }

    # ext-install: the hint without CfT, the info line with it. Stop/launch stubbed.
    mod.cmd_stop = lambda *a, **k: None
    mod.cmd_launch = lambda *a, **k: None
    mod.time.sleep = lambda *_: None

    def ext_install(**kw):
        setup(**kw)
        mod.save_dev_extensions([])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            mod.cmd_ext_install(ext)
        return {'err': err.getvalue(), 'registered': mod.get_dev_extensions() == [os.path.abspath(ext)]}

    res['ext_install_no_cft'] = ext_install(pref='chrome', cft_installed=False)
    res['ext_install_cft'] = ext_install(pref='chrome')
    res['ext_install_vivaldi'] = ext_install(pref='vivaldi', viv=True, cft_installed=False)

    # `browser chrome-for-testing` without an install; `browser cft` alias.
    setup(cft_installed=False)
    err = io.StringIO()
    code = None
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        try:
            mod.cmd_browser('chrome-for-testing')
        except SystemExit as e:
            code = e.code
    res['select_missing'] = {'code': code, 'err': err.getvalue(),
                             'pref': mod.get_browser_preference()}
    setup()
    with contextlib.redirect_stdout(io.StringIO()):
        mod.cmd_browser('cft')
    res['alias_pref'] = mod.get_browser_preference()

    # Path classification.
    res['paths'] = {
        'ours': mod._is_cft_path(cft),
        'mac_app': mod._is_cft_path('/x/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'),
        'puppeteer': mod._is_cft_path(os.path.join(home, '.cache', 'puppeteer', 'chrome',
                                                   'linux-150', 'chrome-linux64', 'chrome')),
        'chrome_is_cft': mod._is_cft_path(chrome),
        'branded_chrome': mod._is_branded_chrome(chrome),
        'branded_cft': mod._is_branded_chrome(cft),
        'branded_linux': mod._is_branded_chrome('/usr/bin/google-chrome-stable'),
        'branded_chromium': mod._is_branded_chrome('/usr/bin/chromium'),
        'platform_key': mod._cft_platform(),
    }
    res['requests'] = list(fake.log)  # must stay empty: nothing downloads by itself
    return res


def main():
    fake = Fake()
    try:
        fn = {'install': scenario_install, 'integrity': scenario_integrity,
              'select': scenario_select}[SCENARIO]
        out = fn(fake)
    except Exception:
        out = {'error': traceback.format_exc()}
    finally:
        fake.server.shutdown()
    sys.stdout.write(json.dumps(out) + '\n')


if __name__ == '__main__':
    main()

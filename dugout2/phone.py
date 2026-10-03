"""Dugout on the phone: the same app, as an app on the phone that keeps working on its own.

The PC stays the main app: it reads the save and the running game. The phone gets the pages and the
data through an encrypted Cloudflare tunnel (cloudflared, "quick tunnel": no account, the PC only
connects out, so no firewall or router settings; it works on Wi-Fi and on 4G). On the phone the
page installs as an app that keeps the last data it received (sw.js): with the PC off it still
opens and shows that data; as soon as Dugout runs again it syncs by itself.

A quick tunnel gets a new address each time it starts. Dugout posts the current address to a
private ntfy.sh topic (its name comes from the pairing key, so only a paired phone knows it); the
phone app looks there when its address stops answering. Every request must carry the pairing key.

The home-network mode (the phone server on every network address of the PC) is still there as an
option; it needs the Windows firewall to let port+1 in.
"""
import ctypes
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.request

from . import config, store

FIREWALL_RULE = 'FL26 Dugout phone'
COOKIE = 'dugout_key'
NTFY = 'https://ntfy.sh/'
REPUBLISH_SECONDS = 4 * 3600           # ntfy.sh keeps a message 12 hours
STARTUP_LNK = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs',
                           'Startup', 'Dugout (chạy nền).lnk')
_NO_WINDOW = 0x08000000


def _settings_set(**kw):
    s = config.settings()
    s.update(kw)
    store.write_json(config.SETTINGS, s)


def key():
    k = config.settings().get('phone_key')
    if not k:
        k = secrets.token_urlsafe(12)
        _settings_set(phone_key=k)
    return k


def topic(k=None):
    """The private ntfy.sh topic where the current tunnel address is posted (same rule in sw.js)."""
    return 'dugout-' + hashlib.sha256(('dugout:' + (k or key())).encode()).hexdigest()[:24]


def addresses():
    """[(ip, kind)] this PC can be reached at on the home network (and Tailscale 100.64.0.0/10)."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:                                    # the address used for the default route
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    out = []
    for ip in found:
        a = ipaddress.ip_address(ip)
        if a in ipaddress.ip_network('100.64.0.0/10'):
            out.append((ip, 'tailscale'))
        elif a.is_private and not a.is_loopback and not a.is_link_local:
            out.append((ip, 'lan'))
    return sorted(out, key=lambda x: (x[1] != 'lan', not x[0].startswith('192.168.'), x[0]))


def qr_svg(text):
    try:
        import segno
    except ImportError:
        return ''
    return segno.make(text, error='m').svg_inline(scale=5, border=2, dark='#0b0f14', light='#ffffff')


def firewall_ok():
    try:
        r = subprocess.run(['netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={FIREWALL_RULE}'],
                           capture_output=True, creationflags=_NO_WINDOW, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def open_firewall(port):
    """Ask Windows (UAC prompt on the PC) to let phones on the home network reach Dugout."""
    args = (f'advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow protocol=TCP '
            f'localport={port} remoteip=localsubnet,100.64.0.0/10 profile=any')
    r = ctypes.windll.shell32.ShellExecuteW(None, 'runas', 'netsh', args, None, 0)
    return r > 32


def startup_on():
    return os.path.exists(STARTUP_LNK)


def set_startup(on):
    """Start Dugout in the background when Windows starts (so the phone can sync any time)."""
    if not on:
        if os.path.exists(STARTUP_LNK):
            os.remove(STARTUP_LNK)
        return
    exe = os.path.join(config.APP_DIR, 'Dugout.exe')
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);$s.TargetPath=$env:EXE;"
          "$s.Arguments='--no-window';$s.WorkingDirectory=$env:DIR;$s.IconLocation=$env:EXE+',0';"
          "$s.Description='FL26 Dugout chạy nền (xem trên điện thoại)';$s.Save()")
    env = dict(os.environ, LNK=STARTUP_LNK, EXE=exe, DIR=config.APP_DIR)
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], env=env, check=True,
                   capture_output=True, creationflags=_NO_WINDOW, timeout=30)


# ------------------------------------------------------------------ Cloudflare quick tunnel
def find_cloudflared():
    for p in (shutil.which('cloudflared'), os.path.join(config.DATA_DIR, 'cloudflared.exe'),
              r'C:\Program Files (x86)\cloudflared\cloudflared.exe', r'C:\Program Files\cloudflared\cloudflared.exe'):
        if p and os.path.exists(p):
            return p
    return None


class _Job:
    """A Windows job object: cloudflared dies with Dugout, even when Dugout is killed."""

    def __init__(self):
        k32 = ctypes.windll.kernel32
        self.handle = k32.CreateJobObjectW(None, None)

        class LIMIT(ctypes.Structure):
            _fields_ = [('a', ctypes.c_int64), ('b', ctypes.c_int64), ('flags', ctypes.c_uint32), ('c', ctypes.c_size_t),
                        ('d', ctypes.c_size_t), ('e', ctypes.c_uint32), ('f', ctypes.c_size_t), ('g', ctypes.c_uint32),
                        ('h', ctypes.c_uint32), ('io', ctypes.c_uint64 * 6), ('pm', ctypes.c_size_t), ('jm', ctypes.c_size_t),
                        ('ppm', ctypes.c_size_t), ('pjm', ctypes.c_size_t)]
        info = LIMIT()
        info.flags = 0x2000                  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))

    def add(self, proc):
        ctypes.windll.kernel32.AssignProcessToJobObject(self.handle, ctypes.c_void_p(int(proc._handle)))


class Tunnel:
    URL = re.compile(r'https://[-a-z0-9]+\.trycloudflare\.com')

    def __init__(self, port, log=print):
        self.port = port
        self.log = log
        self.proc = None
        self.url = ''
        self.error = ''
        self.want = False
        self.published = 0.0
        self.lock = threading.Lock()
        self._job = None

    @property
    def on(self):
        return self.want

    def start(self):
        exe = find_cloudflared()
        if not exe:
            self.error = 'Chưa có cloudflared trên máy (cài: winget install Cloudflare.cloudflared).'
            return False
        with self.lock:
            if self.want:
                return True
            self.want = True
            self.error = ''
        threading.Thread(target=self._run, args=(exe,), daemon=True, name='tunnel').start()
        return True

    def stop(self):
        with self.lock:
            self.want = False
            p, self.proc, self.url = self.proc, None, ''
        if p is not None and p.poll() is None:
            p.terminate()

    def _run(self, exe):
        delay = 5
        while self.want:
            started = time.time()
            try:
                p = subprocess.Popen([exe, 'tunnel', '--no-autoupdate', '--url', f'http://127.0.0.1:{self.port}'],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=_NO_WINDOW, text=True, encoding='utf-8', errors='replace')
            except OSError as exc:
                self.error = f'Không chạy được cloudflared: {exc}'
                return
            try:
                if self._job is None:
                    self._job = _Job()
                self._job.add(p)
            except Exception:
                pass
            with self.lock:
                self.proc = p
            for line in p.stdout:
                m = self.URL.search(line)
                if m and m.group(0) != self.url:
                    self.url = m.group(0)
                    self.error = ''
                    self.log(f'Kết nối điện thoại qua Internet: {self.url}')
                    threading.Thread(target=self.publish, daemon=True).start()
                if 'failed to request quick Tunnel' in line or 'failed to unmarshal' in line:
                    self.error = 'Cloudflare chưa cấp được đường kết nối (thử lại sau ít phút).'
            p.wait()
            self.url = ''
            if not self.want:
                return
            delay = 5 if time.time() - started > 120 else min(300, delay * 2)
            self.log(f'Đường kết nối điện thoại bị ngắt, tạo lại sau {delay} giây.')
            time.sleep(delay)

    def publish(self):
        """Post the current address to the pairing key's private ntfy.sh topic."""
        url = self.url
        if not url:
            return False
        body = json.dumps({'url': url, 'at': int(time.time())}).encode()
        req = urllib.request.Request(NTFY + topic(), data=body, method='POST',
                                     headers={'Title': 'Dugout', 'Cache': 'yes', 'Tags': 'soccer'})
        for _ in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15):
                    self.published = time.time()
                    return True
            except OSError:
                time.sleep(10)
        return False

    def keep_published(self):
        if self.url and time.time() - self.published > REPUBLISH_SECONDS:
            self.publish()


# ------------------------------------------------------------------ the phone server
class PhoneServer:
    """Serves the app to phones: to the tunnel (127.0.0.1 only) and, when the manager chooses the
    home-network mode, to every network address of the PC."""
    host = None                         # tests pin it; else chosen by the mode

    def __init__(self, handler_cls, port, log=print):
        self.handler_cls = handler_cls
        self.port = port
        self.httpd = None
        self.bound = None
        self.error = ''
        self.lock = threading.Lock()
        self.tunnel = Tunnel(port, log)
        threading.Thread(target=self._keep, daemon=True, name='phone-keep').start()

    @property
    def on(self):
        return self.httpd is not None

    @property
    def lan(self):
        return bool(config.settings().get('phone_lan'))

    def _bind(self):
        from http.server import ThreadingHTTPServer
        host = self.host or ('0.0.0.0' if self.lan else '127.0.0.1')
        if self.httpd is not None and self.bound == host:
            return True
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        try:
            self.httpd = ThreadingHTTPServer((host, self.port), self.handler_cls)
        except OSError as exc:
            self.error = f'Không mở được cổng {self.port}: {exc}'
            return False
        self.httpd.daemon_threads = True
        self.bound = host
        self.error = ''
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name='phone-server').start()
        return True

    def start(self, lan=None):
        if lan is not None:
            _settings_set(phone_lan=bool(lan))
        with self.lock:
            if not self._bind():
                return False
        _settings_set(phone=True)
        self.tunnel.start()
        return True

    def stop(self):
        self.tunnel.stop()
        with self.lock:
            if self.httpd is not None:
                self.httpd.shutdown()
                self.httpd.server_close()
                self.httpd = None
        _settings_set(phone=False)

    def _keep(self):
        while True:
            time.sleep(600)
            try:
                self.tunnel.keep_published()
            except Exception:
                pass

    def info(self):
        k = key()
        t = self.tunnel
        lan = [{'ip': ip, 'kind': kind, 'url': f'http://{ip}:{self.port}/'} for ip, kind in addresses()] if self.lan else []
        pair = f'{t.url}/?key={k}' if t.url else ''
        lan_pair = f'{lan[0]["url"]}?key={k}' if lan else ''
        return {'on': self.on, 'port': self.port, 'error': self.error or t.error, 'lan': self.lan,
                'tunnel': {'url': t.url, 'on': t.on, 'cloudflared': bool(find_cloudflared()), 'error': t.error},
                'pair_url': pair, 'qr': qr_svg(pair) if pair and self.on else '',
                'lan_urls': lan, 'lan_pair_url': lan_pair, 'lan_qr': qr_svg(lan_pair) if lan_pair and self.on else '',
                'firewall': firewall_ok() if self.lan else None, 'startup': startup_on()}

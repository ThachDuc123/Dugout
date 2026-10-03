"""Keep FL26 on screen while the manager uses Dugout's window on another monitor.

Full Screen (the game's setting): DirectX minimises the game as soon as any other window becomes
active, and nothing outside the game can stop that. When that happens because the manager clicked
Dugout, Dugout shows the game again at once on its own monitor, without giving it the focus (the same
window the game had, covering its monitor, kept above the taskbar). Clicking the game gives it the
focus back and DirectX makes it full screen again; clicking any other application hides it as usual.
If the game keeps minimising itself, Dugout stops trying until the game has the focus again.

Window Mode: the game does not minimise, so Dugout turns its window into a borderless window that
covers its monitor (it looks like full screen), kept on top of its monitor while the manager works in
Dugout's window. Only the game window's style, position, z-order and minimised state are changed;
nothing is sent to the game and nothing in its files changes.
"""
import ctypes
import threading
import time
from ctypes import wintypes

from . import config, gamemem

TITLE = 'FL26 Dugout'
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00020000, 0x00010000
FRAME = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
WS_EX_FRAME = 0x00000001 | 0x00000100 | 0x00000200 | 0x00020000   # dlgmodalframe, windowedge, clientedge, staticedge
WS_EX_TOPMOST = 0x00000008
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_NOOWNERZORDER = 1, 2, 4, 0x10, 0x20, 0x200
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SW_SHOWNOACTIVATE, SW_SHOWMINNOACTIVE = 4, 7
INTERVAL = 0.3
HOLD_TRIES, HOLD_WINDOW = 3, 30.0    # the game minimised itself again this often (seconds): stop

user32 = ctypes.WinDLL('user32', use_last_error=True)
_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT),
                ('dwFlags', wintypes.DWORD)]


def _top_windows():
    """(hwnd, process id, title, class) of every visible top-level window."""
    out = []

    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            out.append((hwnd, pid.value, buf.value, cls.value))
        return True

    user32.EnumWindows(_ENUM(cb), 0)
    return out


def _rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def monitor_rect(hwnd):
    """The monitor the window is (mostly) on."""
    mon = user32.MonitorFromWindow(hwnd, 2)
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(mi)
    if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return None
    m = mi.rcMonitor
    return m.left, m.top, m.right, m.bottom


def _area(hwnd):
    left, top, right, bottom = _rect(hwnd)
    return max(0, right - left) * max(0, bottom - top)


def game_window(pid, windows):
    own = [w[0] for w in windows if w[1] == pid and w[2] != TITLE]
    return max(own, key=_area) if own else None


def dugout_windows(windows):
    """Dugout's app window: Edge/Chromium, titled exactly like the page (a browser tab would carry
    the browser's name in the title, so a normal browser window is never matched)."""
    return [w[0] for w in windows if w[2] == TITLE and w[3].startswith('Chrome_WidgetWin')]


class Keeper:
    def __init__(self):
        self.lock = threading.Lock()
        self.made = {}                   # game hwnd -> (style, exstyle, rect) before Dugout changed it
        self.top = {}                    # game hwnd -> topmost set by Dugout
        self.hold = False                # Full Screen: the game was on screen when the manager went to Dugout
        self.shown = {}                  # game hwnd -> when Dugout showed it again (Full Screen)
        self.mon = {}                    # game hwnd -> its monitor, seen while it was on screen
        self.retries = []                # times the game minimised itself again after being shown
        self.gave_up = False
        self.state = {'game': False, 'mode': None, 'enabled': self.enabled, 'windows': 0, 'setting': None,
                      'held_failed': False}
        self._game = (0.0, None)
        self._setting = (0.0, None)

    @property
    def enabled(self):
        return config.settings().get('borderless_game', True)

    def set_enabled(self, on):
        s = config.settings()
        s['borderless_game'] = bool(on)
        from . import store
        store.write_json(config.SETTINGS, s)
        if not on:
            self.release()
        self.step()

    def start(self):
        threading.Thread(target=self._run, daemon=True, name='window-keeper').start()
        return self

    def _run(self):
        try:                             # real pixels, whatever the display scaling
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        while True:
            try:
                self.step()
            except Exception:
                import traceback
                traceback.print_exc()
                time.sleep(5)
            time.sleep(INTERVAL)

    def _game_pid(self):
        at, pid = self._game
        if time.time() - at > 3:         # the process list is not read on every step
            g = gamemem.find_game()
            pid = g[0] if g else None
            self._game = (time.time(), pid)
        return pid

    def step(self):
        with self.lock:
            windows = _top_windows()
            pid = self._game_pid()
            gw = game_window(pid, windows) if pid else None
            mine = dugout_windows(windows)
            for d in (self.made, self.top, self.shown, self.mon):
                for h in list(d):
                    if h != gw:
                        d.pop(h, None)               # the game closed or made a new window
            at, setting = self._setting
            if time.time() - at > 5:
                setting = screen_setting()
                self._setting = (time.time(), setting)
            full = bool(setting and setting['mode'] == 'fullscreen')
            fg = user32.GetForegroundWindow()
            kind = 'game' if gw and fg == gw else 'dugout' if fg in mine else 'other'
            mode = None
            if gw:
                style = user32.GetWindowLongPtrW(gw, GWL_STYLE)
                mon = monitor_rect(gw)
                iconic = bool(user32.IsIconic(gw))
                if not iconic and mon:
                    self.mon[gw] = mon
                if full:
                    mode = self._full_screen(gw, kind, iconic)
                elif iconic:
                    mode = 'minimized'
                elif gw in self.made:
                    mode = 'borderless'
                    if style & FRAME or _rect(gw) != mon:      # the game put its frame back
                        self._borderless(gw, mon)
                elif style & WS_CAPTION:
                    mode = 'window'
                    if self.enabled and mon:
                        self._borderless(gw, mon)
                        mode = 'borderless'
                else:
                    mode = 'fullscreen' if mon and _rect(gw) == mon else 'other'
                if mode == 'borderless':
                    self._topmost(gw, kind != 'other')
            else:
                self.hold = False
            self.state = {'game': bool(pid), 'mode': mode, 'enabled': self.enabled, 'windows': len(mine),
                          'setting': setting['mode'] if setting else None, 'held_failed': self.gave_up}

    def _full_screen(self, gw, kind, iconic):
        """Full Screen: show the game again when it minimised itself because the manager clicked Dugout."""
        now = time.time()
        if kind == 'game' and not iconic:            # the game has the focus: it is full screen again
            self.hold, self.gave_up = True, False
            self.retries.clear()
            self.shown.pop(gw, None)
            return 'fullscreen'
        if kind == 'other':                          # another application: the game hides as usual
            self.hold = False
            if gw in self.shown:
                self.shown.pop(gw)
                if not iconic:
                    self._topmost(gw, False)
                    user32.ShowWindow(gw, SW_SHOWMINNOACTIVE)
                    return 'minimized'
            return 'minimized' if iconic else 'fullscreen'
        if not iconic:                               # Dugout is active and the game is on screen
            if gw in self.shown:
                self._topmost(gw, True)
                return 'held'
            return 'fullscreen'
        if not (self.hold and self.enabled) or self.gave_up:
            return 'minimized'
        if gw in self.shown:                         # it minimised itself again after being shown
            self.retries = [t for t in self.retries if now - t < HOLD_WINDOW] + [now]
            if len(self.retries) >= HOLD_TRIES:
                self.gave_up = True
                self.shown.pop(gw, None)
                print(time.strftime('%H:%M:%S'), 'Game Full Screen tự thu nhỏ lại nhiều lần: Dugout thôi giữ game '
                      '(dùng chế độ không viền để game luôn hiện).', flush=True)
                return 'minimized'
        self._show(gw)
        return 'held'

    def _show(self, gw):
        user32.ShowWindow(gw, SW_SHOWNOACTIVATE)
        mon = self.mon.get(gw) or monitor_rect(gw)
        if user32.GetWindowLongPtrW(gw, GWL_STYLE) & FRAME and mon:
            self._borderless(gw, mon)
        elif mon:
            left, top, right, bottom = mon
            user32.SetWindowPos(gw, None, left, top, right - left, bottom - top,
                                SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
        self.top.pop(gw, None)
        self._topmost(gw, True)
        self.shown[gw] = time.time()

    def _borderless(self, gw, mon):
        style = user32.GetWindowLongPtrW(gw, GWL_STYLE)
        ex = user32.GetWindowLongPtrW(gw, GWL_EXSTYLE)
        if gw not in self.made:
            self.made[gw] = (style, ex, _rect(gw))
        user32.SetWindowLongPtrW(gw, GWL_STYLE, style & ~FRAME)
        user32.SetWindowLongPtrW(gw, GWL_EXSTYLE, ex & ~WS_EX_FRAME)
        left, top, right, bottom = mon
        user32.SetWindowPos(gw, None, left, top, right - left, bottom - top,
                            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_NOOWNERZORDER)

    def _topmost(self, gw, on):
        if self.top.get(gw) == on and bool(user32.GetWindowLongPtrW(gw, GWL_EXSTYLE) & WS_EX_TOPMOST) == on:
            return
        user32.SetWindowPos(gw, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
        self.top[gw] = on

    def release(self):
        """Give the game window its frame back (Dugout is stopping, or the manager turned this off)."""
        with self.lock:
            for gw, (style, ex, rect) in list(self.made.items()):
                if user32.IsWindow(gw):
                    user32.SetWindowPos(gw, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                    user32.SetWindowLongPtrW(gw, GWL_STYLE, style)
                    user32.SetWindowLongPtrW(gw, GWL_EXSTYLE, ex)
                    left, top, right, bottom = rect
                    user32.SetWindowPos(gw, None, left, top, right - left, bottom - top,
                                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            self.made.clear()
            self.top.clear()


# ------------------------------------------------------------------ the game's own screen mode
# settings.dat (Documents\KONAMI\...\settings.dat, written by FL26's Settings.exe): u32 magic 'WECF',
# u32 version, u32 option, u32 width, u32 height, ... - no checksum (Settings_b.dll writes the
# structure as it is). Full Screen is bit 0 of option (Bind.Wrapper.IsFullScreen / SetFullScreen).
SETTINGS_MAGIC = b'WECF'
OPTION_AT = 8
FULL_SCREEN_BIT = 1


def game_settings_path():
    import os
    return os.path.join(config.KONAMI_DIR, 'settings.dat')


def screen_setting():
    """{'mode': 'fullscreen' | 'window', 'width', 'height'} from the game's settings, or None."""
    import struct
    try:
        with open(game_settings_path(), 'rb') as f:
            head = f.read(20)
    except OSError:
        return None
    if len(head) < 20 or head[:4] != SETTINGS_MAGIC:
        return None
    option, width, height = struct.unpack_from('<III', head, OPTION_AT)
    return {'mode': 'fullscreen' if option & FULL_SCREEN_BIT else 'window', 'width': width, 'height': height}


def set_screen_mode(window_mode):
    """Switch the game between Window Mode (borderless with Dugout) and Full Screen, as Settings.exe
    would: only bit 0 of `option` changes. The old file is kept next to it first."""
    import os
    import shutil
    import struct
    if gamemem.find_game():
        raise ValueError('Hãy thoát FL26 trước: game chỉ đọc cài đặt này lúc khởi động.')
    path = game_settings_path()
    data = bytearray(open(path, 'rb').read())
    if len(data) < 20 or data[:4] != SETTINGS_MAGIC:
        raise ValueError('File cài đặt của game không đúng dạng; hãy chỉnh bằng Settings.exe.')
    option = struct.unpack_from('<I', data, OPTION_AT)[0]
    new = option & ~FULL_SCREEN_BIT if window_mode else option | FULL_SCREEN_BIT
    if new == option:
        return screen_setting()
    backup = path + time.strftime('.dugout-%Y%m%d-%H%M%S.bak')
    shutil.copy2(path, backup)
    struct.pack_into('<I', data, OPTION_AT, new)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)
    after = screen_setting()
    if not after or after['mode'] != ('window' if window_mode else 'fullscreen'):
        shutil.copy2(backup, path)
        raise ValueError('Không đổi được cài đặt của game (đã trả lại file cũ).')
    return after


KEEPER = None


def start():
    global KEEPER
    if KEEPER is None:
        KEEPER = Keeper().start()
    return KEEPER


def status():
    return KEEPER.state if KEEPER is not None else None

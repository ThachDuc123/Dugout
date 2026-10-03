"""The running game's memory (FL26 / PES 2021): the live Master League player table.

While a Master League career is loaded, every player lives in one table of 30,001 records of
380 bytes (the save keeps a packed 156-byte form of the same data; the game packs it when it
saves). Known fields of a live record:
  +7 bits 4-7  registered position        +28 & 63  age
  +44 u32      career index                +48 u32   player id
  +300 u16     team slot
The table is the start of the career block; the career clock (u16 year, u8 month, u8 day, u32 0,
u32 team identity) sits at +23,341,604 of the same block and the transfer / salary budget (u32,
euros / 100) at +24,038,388 / +24,038,408 (the exe's own budget code reads that offset, which is
checked in FL_2026.exe before any budget is shown). Market values are rows of 48 bytes elsewhere
(u32 career index, u32 id, u32 value / 100, u32 51), found by the players' ids.

Nothing else is assumed. Dugout finds the table by the players of the last save (career index +
id), checks it against that save, and finds the bits of every position grade and of the playing
style by matching each bit offset of the live records against the save's values for ~27,000
players ("calibration"). Only fields that match almost perfectly are ever written, a few bytes at
a time, each one checked before and after.
"""
import ctypes
import datetime as dt
import json
import os
import struct
import time
from ctypes import wintypes

import numpy as np

from . import config, terms
from .pes import career as pc

STRIDE = 380
COUNT = 30001
TABLE_SIZE = STRIDE * COUNT
INDEX_AT, ID_AT, TEAM_AT = 44, 48, 300
POSITION_FIELD = (60, 4)                 # bit offset in the record, width
CLOCK_AT = 23341604
TRANSFER_AT, SALARY_AT = 24038388, 24038408
BUDGET_CODE = bytes.fromhex('8B87F4CB6E018945C4488D55C4488D4DD0')     # mov eax,[rdi+16ECBF4h]; mov [rbp-3Ch],eax ...
MARKET_STRIDE, MARKET_MARK = 48, 51
WIDTH = {'style': 5, 'foot': 1}
MANAGER_GLOBAL_RVA, MANAGER_CAREER_AT = 0x3706010, 72     # FL26 build Touchline-era; only a hint, always checked
GAME_PROCESSES = ('fl_2026.exe', 'pes2021.exe', 'fl_2025.exe')
CALIBRATION = os.path.join(config.DATA_DIR, 'gamemem.json')
CAL_VERSION = 2                 # 2: + preferred foot

PROCESS_VM_OPERATION, PROCESS_VM_READ, PROCESS_VM_WRITE = 0x08, 0x10, 0x20
PROCESS_QUERY_INFORMATION = 0x400
MEM_COMMIT, MEM_PRIVATE = 0x1000, 0x20000
WRITABLE = {0x04, 0x08, 0x40, 0x80}
PAGE_GUARD = 0x100

GOOD = 0.97                  # a calibrated field must agree with the save for this share of players
UNIQUE = 0.90                # ... and no other offset may come close


class MemError(Exception):
    pass


class MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_ulonglong), ('AllocationBase', ctypes.c_ulonglong),
                ('AllocationProtect', wintypes.DWORD), ('PartitionId', wintypes.WORD),
                ('RegionSize', ctypes.c_size_t), ('State', wintypes.DWORD), ('Protect', wintypes.DWORD),
                ('Type', wintypes.DWORD)]


class _ProcessEntry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]


class _ModuleEntry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('th32ModuleID', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                ('GlblcntUsage', wintypes.DWORD), ('ProccntUsage', wintypes.DWORD),
                ('modBaseAddr', ctypes.c_void_p), ('modBaseSize', wintypes.DWORD), ('hModule', wintypes.HMODULE),
                ('szModule', ctypes.c_wchar * 256), ('szExePath', ctypes.c_wchar * 260)]


def _k32():
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.ReadProcessMemory.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                    ctypes.POINTER(ctypes.c_size_t))
    k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
    k.VirtualQueryEx.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t)
    k.VirtualQueryEx.restype = ctypes.c_size_t
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    return k


def find_game(names=GAME_PROCESSES):
    """(pid, exe name) of the running game, or None."""
    k = _k32()
    snap = k.CreateToolhelp32Snapshot(2, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return None
    try:
        e = _ProcessEntry()
        e.dwSize = ctypes.sizeof(e)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() in names:
                return int(e.th32ProcessID), e.szExeFile
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return None


class Process:
    """Read/write access to one process."""

    def __init__(self, pid, name=''):
        self.k = _k32()
        self.pid, self.name = pid, name
        rights = PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION
        self.handle = self.k.OpenProcess(rights, False, pid)
        if not self.handle:
            raise MemError(f'Không mở được tiến trình game (lỗi Windows {ctypes.get_last_error()}). '
                           'Nếu game chạy bằng quyền Administrator thì Dugout cũng phải chạy bằng quyền đó.')

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None

    def alive(self):
        code = wintypes.DWORD()
        return bool(self.handle) and self.k.GetExitCodeProcess(self.handle, ctypes.byref(code)) and code.value == 259

    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            return None
        return buf.raw[:got.value] if got.value == size else None

    def read_into(self, addr, buf, size):
        """ReadProcessMemory into a buffer kept by the caller (a whole-memory pass without a new 32 MB
        buffer and two copies per read). -> True when all `size` bytes were read"""
        got = ctypes.c_size_t()
        return bool(self.k.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))) \
            and got.value == size

    def write(self, addr, data):
        got = ctypes.c_size_t()
        ok = self.k.WriteProcessMemory(self.handle, ctypes.c_void_p(addr), data, len(data), ctypes.byref(got))
        return bool(ok) and got.value == len(data)

    def u64(self, addr):
        b = self.read(addr, 8)
        return struct.unpack('<Q', b)[0] if b else 0

    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack('<I', b)[0] if b else None

    def regions(self, min_size=0):
        """(base, size) of every committed, writable, private region."""
        out, addr, mbi = [], 0x10000, MBI()
        while addr < 0x7FFFFFFF0000:
            if not self.k.VirtualQueryEx(self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            base, size = int(mbi.BaseAddress), int(mbi.RegionSize)
            if (mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE and mbi.Protect & 0xFF in WRITABLE
                    and not mbi.Protect & PAGE_GUARD and size >= min_size):
                out.append((base, size))
            addr = base + max(size, 0x1000)
        return out

    def image_regions(self):
        """(base, size) of the writable parts of the game's exe image (its static data: what stays where it is
        while the game runs)."""
        mod = self.module_base()
        if not mod:
            return []
        out, addr, mbi = [], mod, MBI()
        while addr < mod + (1 << 32):
            if not self.k.VirtualQueryEx(self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            base, size = int(mbi.BaseAddress), int(mbi.RegionSize)
            if int(mbi.AllocationBase) != mod:
                break
            if mbi.State == MEM_COMMIT and mbi.Protect & 0xFF in WRITABLE and not mbi.Protect & PAGE_GUARD:
                out.append((base, size))
            addr = base + max(size, 0x1000)
        return out

    def module_base(self):
        k = self.k
        snap = k.CreateToolhelp32Snapshot(0x18, self.pid)          # TH32CS_SNAPMODULE | SNAPMODULE32
        if not snap or snap == wintypes.HANDLE(-1).value:
            return None
        try:
            e = _ModuleEntry()
            e.dwSize = ctypes.sizeof(e)
            if k.Module32FirstW(snap, ctypes.byref(e)):
                return int(e.modBaseAddr or 0)
        finally:
            k.CloseHandle(snap)
        return None


# ------------------------------------------------------------------------ the table
def _keys(rows):
    """Snapshot ids (database id, or 2^32 + career index for created players) of live rows."""
    idx = rows[:, INDEX_AT:INDEX_AT + 4].copy().view('<u4').ravel().astype(np.int64)
    mid = rows[:, ID_AT:ID_AT + 4].copy().view('<u4').ravel().astype(np.int64)
    created = mid >= pc.CREATED_FLAG
    keys = np.where(created, pc.CREATED_BASE + idx, mid)
    valid = ((mid >= 100) & (mid <= 1000000)) | created
    return np.where(valid, keys, -1)


def field(rows, bit, width):
    """A bit field of every row (little-endian, fields may cross byte boundaries)."""
    first = bit // 8
    span = (bit % 8 + width + 7) // 8
    word = np.zeros(len(rows), dtype=np.uint32)
    for k in range(span):
        word |= rows[:, first + k].astype(np.uint32) << np.uint32(8 * k)
    return ((word >> np.uint32(bit % 8)) & np.uint32((1 << width) - 1)).astype(np.int64)


def read_field(rec, bit, width):
    return pc.read_bits(rec, 0, bit, width)


class Table:
    """One read of the live table: rows (records x STRIDE) and snapshot id -> slot."""

    def __init__(self, base, raw):
        self.base = base
        self.rows = np.frombuffer(raw, dtype=np.uint8).reshape(len(raw) // STRIDE, STRIDE)
        self.keys = _keys(self.rows)
        self.slot = {int(k): s for s, k in enumerate(self.keys) if k >= 0}

    def address(self, slot):
        return self.base + slot * STRIDE


def _match(table, snap):
    """Share of the save's players found in the live table under the same id, and the pairs."""
    rows_live, rows_save = [], []
    for i, pid in enumerate(snap.ids):
        s = table.slot.get(int(pid))
        if s is not None:
            rows_live.append(s)
            rows_save.append(i)
    return len(rows_live) / max(1, len(snap.ids)), np.array(rows_live), np.array(rows_save)


def clock(proc, base):
    """(date, team identity) of the career clock next to the table, or (None, 0)."""
    raw = proc.read(base + CLOCK_AT, 12)
    if not raw:
        return None, 0
    year, a, b, _zero, ident = struct.unpack('<HBBII', raw)
    for month, day in ((a, b), (b, a)):
        if 2000 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return dt.date(year, month, day), ident
            except ValueError:
                continue
    return None, ident


def team_matches(ident, team_id):
    return bool(ident) and team_id in (ident >> 14, ident & 0x3FFF)


def locate(proc, snap, log=print, scan=True):
    """(base address, records) of the live player table of the career in `snap`, checked against
    the save. When the career clock pins the table start, records is COUNT; otherwise the span
    covers every start the players allow (a few empty records at either end)."""
    candidates = []
    # 1. the game's own pointer (valid on the FL26 build Dugout was built against; checked like any guess)
    try:
        mod = proc.module_base()
        if mod:
            manager = proc.u64(mod + MANAGER_GLOBAL_RVA)
            if manager > 0x10000:
                base = proc.u64(manager + MANAGER_CAREER_AT)
                if base > 0x10000:
                    candidates.append(base)
    except Exception:
        pass
    for base in candidates:
        raw = proc.read(base, TABLE_SIZE)
        if raw and _match(Table(base, raw), snap)[0] >= 0.85 and team_matches(clock(proc, base)[1], snap.team_id):
            return base, COUNT
    if not scan:
        return None
    # 2. search: the career index + id of the managed squad, then the whole table around each hit
    squad = [int(p['player_id']) for p in snap.squad_players] or [int(x) for x in snap.ids[:50]]
    anchors = []
    for pid in squad:
        i = snap.row.get(pid)
        if i is not None and pid < pc.CREATED_BASE:
            anchors.append(struct.pack('<II', int(snap.cidx[i]) & 0xFFFFFFFF, pid))
    if not anchors:
        raise MemError('Không có cầu thủ nào của save để dò bộ nhớ game.')
    found, t0 = [], time.time()
    regions = proc.regions(min_size=TABLE_SIZE)
    for rbase, rsize in sorted(regions, key=lambda r: -r[1]):
        pos, chunk = 0, 64 << 20
        while pos < rsize:
            size = min(chunk + 8, rsize - pos)
            data = proc.read(rbase + pos, size)
            if data is None:
                break
            for needle in anchors[:3]:
                at = data.find(needle)
                while at >= 0:
                    hit = rbase + pos + at
                    span = _table_around(proc, hit - INDEX_AT, rbase, rsize, snap)
                    if span is not None and span not in found:
                        found.append(span)
                    at = data.find(needle, at + 1)
            pos += chunk
        if found:
            break
    log(f'Dò bộ nhớ game: {len(regions)} vùng, {len(found)} bảng cầu thủ ({time.time() - t0:.1f}s).')
    if not found:
        return None
    if len(found) > 1:              # prefer the one whose clock belongs to the managed club
        own = [f for f in found if f[1] == COUNT]
        if len(own) != 1:
            raise MemError(f'Tìm thấy {len(found)} bảng cầu thủ trong bộ nhớ game, không chắc bảng nào đang dùng: '
                           'không sửa gì.')
        return own[0]
    return found[0]


def _table_around(proc, record, rbase, rsize, snap):
    """(start, records) of the 30,001-record table containing `record`, if the save's players fill
    it; pinned by the career clock when it is where it should be."""
    lo = max(rbase, record - (COUNT - 1) * STRIDE)
    lo = record - ((record - lo) // STRIDE) * STRIDE
    hi = min(rbase + rsize, record + COUNT * STRIDE)
    n = (hi - lo) // STRIDE
    raw = proc.read(lo, n * STRIDE)
    if raw is None or n < COUNT:
        return None
    ids = np.frombuffer(raw, dtype=np.uint8).reshape(n, STRIDE)
    keys = _keys(ids)
    known = np.isin(keys, snap.ids)
    run = np.concatenate([[0], np.cumsum(known)])
    window = run[COUNT:] - run[:-COUNT]
    starts = np.nonzero(window == window.max())[0]
    if window.max() / max(1, len(snap.ids)) < 0.85:
        return None
    for k in starts:
        if team_matches(clock(proc, lo + int(k) * STRIDE)[1], snap.team_id):
            return lo + int(k) * STRIDE, COUNT
    first, last = int(starts[0]), int(starts[-1])
    return lo + first * STRIDE, last - first + COUNT


# ------------------------------------------------------------------ calibration
def _words(rows):
    """24-bit little-endian words starting at every byte of the rows (bit fields up to 17 bits)."""
    return (rows[:, :-2].astype(np.uint32) | rows[:, 1:-1].astype(np.uint32) << np.uint32(8)
            | rows[:, 2:].astype(np.uint32) << np.uint32(16))


def _candidates(words, truth, width, transforms, keep=12):
    """[(score, bit, transform)], best first: how well each bit offset holds `truth`. The score is
    the lower of the agreement on rows where the value is 0 and on the others, so a field of
    zeros cannot pass for the mostly-zero grades."""
    mask = np.uint32((1 << width) - 1)
    zero = truth == 0
    out = []
    for name, fn in transforms:
        t = fn(truth).astype(np.uint32)
        for shift in range(8):
            eq = ((words >> np.uint32(shift)) & mask) == t[:, None]
            a0 = eq[zero].mean(0) if zero.any() else eq.mean(0)
            a1 = eq[~zero].mean(0) if (~zero).any() else eq.mean(0)
            score = np.minimum(a0, a1)
            for byte in np.argsort(-score)[:keep]:
                out.append((float(score[byte]), int(byte) * 8 + shift, name))
    out.sort(reverse=True)
    return out[:keep * 2]


def _overlaps(bit, width, used):
    return any(bit < b + w and b < bit + width for b, w in used)


IDENTITY = ('same', lambda v: v)
TO_CAREER_STYLE = {db: c for c, db in terms.CAREER_STYLE_TO_DB.items()}


def calibrate(table, snap, log=print):
    """Find where the live record keeps each position grade, the playing style and the
    preferred foot (from the database, for database players: the save has no foot)."""
    t0 = time.time()
    _share, live, save = _match(table, snap)
    if len(live) < 1000:
        raise MemError('Quá ít cầu thủ khớp giữa save và bộ nhớ game để dò các trường.')
    rng = np.random.default_rng(7)
    pick = rng.choice(len(live), size=min(len(live), 9000), replace=False)
    rows = table.rows[live[pick]]
    idx = save[pick]
    words = _words(rows)
    out = {'fields': {}, 'checks': {}}
    pos_live = field(rows, *POSITION_FIELD)
    out['checks']['position'] = round(float((pos_live == snap.position[idx]).mean()), 4)
    out['checks']['players'] = int(len(live))

    # every grade's candidates, then the best-scoring fields claim their bits first
    cands = {}
    for p, name in enumerate(terms.POSITIONS):
        cands['grade:' + name] = (_candidates(words, snap.grades[idx, p].astype(np.int64), 2,
                                              (IDENTITY, ('reversed', lambda v: 2 - v))), 2)
    career_style = np.array([TO_CAREER_STYLE.get(int(v), 0) for v in snap.style[idx]], dtype=np.int64)
    cands['style'] = (_candidates(words, career_style, 5, (IDENTITY,))
                      + _candidates(words, career_style, 5, (('database', lambda v: np.array(
                          [terms.CAREER_STYLE_TO_DB.get(int(x), 0) for x in v])),)), 5)
    cands['style'][0].sort(reverse=True)
    dbp = (snap.base_row[idx] >= 0) & ~snap.regen[idx]
    if dbp.sum() >= 1000:
        cands['foot'] = (_candidates(words[dbp], snap.left_foot[idx][dbp].astype(np.int64), 1,
                                     (IDENTITY, ('flip', lambda v: 1 - v))), 1)
    used = [POSITION_FIELD]
    chosen = {}
    for name in sorted(cands, key=lambda n: -cands[n][0][0][0] if cands[n][0] else 0):
        lst, width = cands[name]
        for score, bit, tr in lst:
            if not _overlaps(bit, width, used):
                chosen[name] = (score, bit, tr, width)
                used.append((bit, width))
                break
    for name, (score, bit, tr, width) in chosen.items():
        lst = cands[name][0]
        also = []
        if name == 'foot':               # the foot may be kept twice: every perfect copy is written
            for s2, b2, t2 in lst:
                if s2 >= GOOD and not _overlaps(b2, width, used) and not _overlaps(b2, width, [(b, 1) for b, _t in also]):
                    also.append((b2, t2))
        runner = max((s for s, b, _t in lst if not _overlaps(b, width, used + [(b2, 1) for b2, _t in also])), default=0.0)
        out['fields'][name] = {'bit': bit, 'transform': tr, 'score': round(score, 4), 'runner_up': round(runner, 4)}
        if also:
            out['fields'][name]['also'] = [[b2, t2] for b2, t2 in also]
    out['seconds'] = round(time.time() - t0, 2)
    out['version'] = CAL_VERSION
    log(f'Dò trường trong bộ nhớ game xong ({out["seconds"]}s): vị trí đăng ký khớp '
        f'{out["checks"]["position"] * 100:.1f}%, '
        + ', '.join(f'{k[6:] if k.startswith("grade:") else k} {v["score"] * 100:.0f}%' for k, v in out['fields'].items()))
    return out


def usable(cal, name):
    f = (cal or {}).get('fields', {}).get(name)
    return bool(f) and f['score'] >= GOOD and f['runner_up'] < UNIQUE


def exe_stamp():
    try:
        st = os.stat(config.GAME_EXE)
        return f'{int(st.st_mtime)}_{st.st_size}'
    except OSError:
        return ''


def load_calibration():
    try:
        data = json.load(open(CALIBRATION, encoding='utf-8'))
        return data if data.get('exe') == exe_stamp() else None
    except (OSError, ValueError):
        return None


def save_calibration(cal):
    try:
        with open(CALIBRATION, 'w', encoding='utf-8') as f:
            json.dump({**cal, 'exe': exe_stamp(), 'version': CAL_VERSION, 'at': time.strftime('%Y-%m-%d %H:%M:%S')}, f,
                      indent=1)
    except OSError:
        pass


def location(cal, name):
    """(bit, width, transform) of a writable field, or None."""
    locs = locations(cal, name)
    return locs[0] if locs else None


def locations(cal, name):
    """Every copy of a writable field: [(bit, width, transform)]."""
    if name == 'position':
        return [(POSITION_FIELD[0], POSITION_FIELD[1], 'same')]
    if not usable(cal, name):
        return []
    f = cal['fields'][name]
    width = WIDTH.get(name, 2)
    return [(f['bit'], width, f['transform'])] + [(b, width, t) for b, t in f.get('also', [])]


def encode(transform, value):
    if transform == 'reversed':
        return 2 - value
    if transform == 'flip':
        return 1 - value
    if transform == 'database':
        return terms.CAREER_STYLE_TO_DB.get(int(value), 0)
    return value


def decode(transform, raw):
    if transform == 'reversed':
        return 2 - raw
    if transform == 'flip':
        return 1 - raw
    if transform == 'database':
        return TO_CAREER_STYLE.get(int(raw), 0)
    return raw


# ------------------------------------------------------------------ budget and market values
_EXE_CHECK = {}


def budget_code_present():
    """True if FL_2026.exe reads the transfer budget at TRANSFER_AT of the career block (the exact
    instruction is in the file). Checked once per exe build."""
    stamp = exe_stamp()
    if stamp in _EXE_CHECK:
        return _EXE_CHECK[stamp]
    cache = os.path.join(config.DATA_DIR, 'gamemem_exe.json')
    try:
        data = json.load(open(cache, encoding='utf-8'))
        if data.get('exe') == stamp:
            _EXE_CHECK[stamp] = bool(data.get('budget'))
            return _EXE_CHECK[stamp]
    except (OSError, ValueError):
        pass
    found = False
    try:
        with open(config.GAME_EXE, 'rb') as f:
            tail = b''
            while True:
                chunk = f.read(32 << 20)
                if not chunk:
                    break
                if BUDGET_CODE in tail + chunk:
                    found = True
                    break
                tail = chunk[-len(BUDGET_CODE):]
    except OSError:
        return False
    _EXE_CHECK[stamp] = found
    try:
        with open(cache, 'w', encoding='utf-8') as f:
            json.dump({'exe': stamp, 'budget': found}, f)
    except OSError:
        pass
    return found


def read_budget(proc, base):
    """{'transfer', 'salary'} in euros from the career block, or None if implausible."""
    t, s_ = proc.u32(base + TRANSFER_AT), proc.u32(base + SALARY_AT)
    if t is None or s_ is None or t > 1_000_000_000 or s_ > 1_000_000_000:
        return None
    return {'transfer': t * 100, 'salary': s_ * 100}


def _market_rows(raw):
    """(snapshot ids, values in euros, valid mask) of 48-byte market rows."""
    n = len(raw) // MARKET_STRIDE
    a = np.frombuffer(raw[:n * MARKET_STRIDE], dtype='<u4').reshape(n, MARKET_STRIDE // 4)
    cidx, mid, val, mark = (a[:, k].astype(np.int64) for k in range(4))
    created = mid >= pc.CREATED_FLAG
    keys = np.where(created, pc.CREATED_BASE + cidx, mid)
    ok = (mark == MARKET_MARK) & (((mid >= 100) & (mid <= 1000000)) | created) & (val >= 1000) & (val <= 5000000)
    return keys, val * 100, ok


def find_market(proc, snap, near=None, log=print):
    """(start, rows) of the market value table, located by the squad's rows."""
    squad = [int(p['player_id']) for p in snap.squad_players]
    anchors = []
    for pid in squad:
        i = snap.row.get(pid)
        if i is not None and pid < pc.CREATED_BASE:
            anchors.append(struct.pack('<II', int(snap.cidx[i]) & 0xFFFFFFFF, pid))
    if not anchors:
        return None
    t0 = time.time()
    regions = proc.regions(min_size=1 << 16)
    if near:                                   # the region holding the career block first
        regions.sort(key=lambda r: (not r[0] <= near < r[0] + r[1], -r[1]))
    for rbase, rsize in regions:
        pos, chunk = 0, 64 << 20
        while pos < rsize:
            size = min(chunk + 16, rsize - pos)
            data = proc.read(rbase + pos, size)
            if data is None:
                break
            for needle in anchors[:4]:
                at = data.find(needle)
                while at >= 0:
                    if at + 16 <= len(data) and struct.unpack_from('<I', data, at + 12)[0] == MARKET_MARK:
                        span = _market_around(proc, rbase + pos + at, rbase, rsize)
                        if span:
                            log(f'Tìm thấy bảng giá trị cầu thủ trong bộ nhớ game ({span[1]} dòng, {time.time() - t0:.1f}s).')
                            return span
                    at = data.find(needle, at + 1)
            pos += chunk
    return None


def _market_around(proc, row, rbase, rsize):
    lo = max(rbase, row - COUNT * MARKET_STRIDE)
    lo = row - ((row - lo) // MARKET_STRIDE) * MARKET_STRIDE
    hi = min(rbase + rsize, row + COUNT * MARKET_STRIDE)
    raw = proc.read(lo, (hi - lo) // MARKET_STRIDE * MARKET_STRIDE)
    if raw is None:
        return None
    _keys_, _vals, ok = _market_rows(raw)
    at = (row - lo) // MARKET_STRIDE
    # the contiguous stretch of valid rows around the hit (a few gaps allowed)
    first = last = at
    gap = 0
    while first > 0 and gap < 8:
        first -= 1
        gap = 0 if ok[first] else gap + 1
    first += gap
    gap = 0
    while last < len(ok) - 1 and gap < 8:
        last += 1
        gap = 0 if ok[last] else gap + 1
    last -= gap
    count = last - first + 1
    if ok[first:last + 1].sum() < 200:
        return None
    return lo + first * MARKET_STRIDE, count


def read_market(proc, start, count):
    """{snapshot id: market value in euros}."""
    raw = proc.read(start, count * MARKET_STRIDE)
    if raw is None:
        return None
    keys, vals, ok = _market_rows(raw)
    return {int(k): int(v) for k, v, o in zip(keys, vals, ok) if o}

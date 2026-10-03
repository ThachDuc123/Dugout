"""Match ratings on Dugout's 10-point scale written into the game at full time (the manager asked for it on
2026-10-02: "làm cái 2 đi", the game's own ratings are too low: a hat-trick 8.x).

Where the game keeps them (found on Arsenal 3-2 Newcastle, read only):
- the career's fixture table in memory, in the save's own format (pes.world: rows of 596 bytes, appearances of 16
  bytes: u32 career index, u32 player id, u32 goals | assists << 8, u32 packed: minutes bits 0-6, rating in tenths
  bits 7-13): this is what the save gets. The row of the match is found during the match (its date and teams) and
  read again at full time until the game has written the ratings;
- each club's squad table (records of 36 bytes, player id at +0, the last match's rating as a float at +0x18):
  what the result screen shows. Found at full time from the squad's ids.
Only those data are written (no code), for the managed club's players who played; each record is checked before and
read back after; every write is logged in data\\rating_patch_log.json with the old value. Off with the setting
'rating_patch': false."""
import json
import os
import struct
import time

from . import config, simstate, store
from .events import rating10
from .pes import world

STRIDE, RATING = 0x24, 0x18
LOG = os.path.join(config.DATA_DIR, 'rating_patch_log.json')


def enabled():
    return config.settings().get('rating_patch', True)


def find_row(proc, date, home, away, stop=lambda: False):
    """The fixture row of the match in the game's memory (a pass over memory for its date): address or None."""
    y, m, d = date
    pat = struct.pack('<HBB', y, m, d)
    for b, sz in proc.regions():
        pos = 0
        while pos < sz:
            if stop():
                return None
            n = min(32 << 20, sz - pos)
            raw = proc.read(b + pos, n)
            if raw is None:
                break
            i = raw.find(pat)
            while i >= 0:
                row = b + pos + i - 4
                r = proc.read(row, world.FIXTURE_ROW)
                if r:
                    hw, aw = struct.unpack_from('<II', r, 16)
                    if hw >> world.PACK == home and aw >> world.PACK == away:
                        return row
                i = raw.find(pat, i + 1)
            pos += n
            time.sleep(0.002)
    return None


def read_row(proc, row):
    r = proc.read(row, world.FIXTURE_ROW)
    return world.decode_fixture(r, 0) if r else None


def patch_row(proc, row, side):
    """The managed club's appearances in the row (side 'home' / 'away') to the 10-point scale. -> writes"""
    base = row + (world.HOME_ENTRIES if side == 'home' else world.AWAY_ENTRIES)
    slots = world.HOME_SLOTS if side == 'home' else world.AWAY_SLOTS
    writes = []
    for k in range(slots):
        a = base + k * world.ENTRY
        raw = proc.read(a, world.ENTRY)
        if not raw:
            continue
        cidx, pid, ev, packed = struct.unpack('<IIII', raw)
        tenths = (packed >> 7) & 127
        if not pid or not (packed & 127) or not tenths:
            continue
        g, ast = ev & 255, (ev >> 8) & 255
        new = rating10(tenths / 10, g, ast, bool(packed & 0x80000 or packed & 0x40000), bool(packed & 0x100000))
        nt = int(round(new * 10))
        if nt == tenths:
            continue
        val = (packed & ~(127 << 7)) | (nt << 7)
        again = proc.read(a, world.ENTRY)
        if again != raw:                                   # the game is writing it now: next time
            continue
        ok = proc.write(a + 12, struct.pack('<I', val))
        back = proc.read(a + 12, 4)
        writes.append({'where': 'row', 'pid': pid, 'addr': a + 12, 'old': tenths / 10, 'new': nt / 10,
                       'old_word': packed, 'ok': bool(ok) and back == struct.pack('<I', val)})
    return writes


def find_table(proc, squad, stop=lambda: False):
    """The managed club's squad table: {player id: record address}, or None."""
    squad = set(squad)
    hits = simstate.scan_ids(proc, squad, stop=stop, regions=proc.regions())
    best = None
    for a in sorted(hits or {}):
        if hits.get(a - STRIDE) in squad:
            continue
        run, b = {}, a
        while hits.get(b) in squad and hits[b] not in run:
            raw = proc.read(b + RATING, 4)
            r = struct.unpack('<f', raw)[0] if raw else -1
            if not (r == 0.0 or 3.0 <= r <= 10.0):
                break
            run[hits[b]] = b
            b += STRIDE
        if len(run) >= 16 and (best is None or len(run) > len(best)):
            best = run
    return best


def patch_table(proc, table, new_by_pid):
    """The result screen's ratings of the managed club: the same 10-point ratings as the row."""
    writes = []
    for pid, a in table.items():
        new = new_by_pid.get(pid)
        raw = proc.read(a, RATING + 4)
        if new is None or not raw or struct.unpack_from('<I', raw, 0)[0] != pid:
            continue
        old = struct.unpack_from('<f', raw, RATING)[0]
        if not (3.0 <= old <= 10.0) or abs(old - new) < 0.05:
            continue
        ok = proc.write(a + RATING, struct.pack('<f', new))
        back = proc.read(a + RATING, 4)
        writes.append({'where': 'table', 'pid': pid, 'addr': a + RATING, 'old': round(old, 2), 'new': new,
                       'ok': bool(ok) and back is not None and abs(struct.unpack('<f', back)[0] - new) < 1e-4})
    return writes


def log(entry):
    try:
        with open(LOG, encoding='utf-8') as f:
            d = json.load(f)
        items = d if isinstance(d, list) else [d]
    except (OSError, ValueError):
        items = []
    store.write_json(LOG, (items + [entry])[-200:])

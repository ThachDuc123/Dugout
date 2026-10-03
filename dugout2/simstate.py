"""FL26's own match state: one object per player on the pitch. Each holds the player id twice (+0, +0xC),
his shirt number in this match (+0x5C) and where he is (x along the pitch +0x604, z across +0x60C; the body
the game draws stands within 6 cm). The 16 bytes before it: a value common to the match's objects, 0, the
object's slot (0-10 home, 11-21 away) and a value repeated at +8 (checked on two matches: Sheffield United -
Arsenal, Arsenal - Watford; the objects lie anywhere in memory, in any order). A substitution writes the
incoming player's id into the outgoing one's object at once, even a quick one at a dead ball. So the map
needs no guessing of who a body is: slot -> player id, shirt number, position. Read only."""
import math
import struct
import time

import numpy as np

ID2, ENTRY = 0xC, 0x8
NUM = 0x5C
X, Z = 0x604, 0x60C
READ = 0x610


CHUNK = 16 << 20


def scan_ids(proc, ids, stop=lambda: False, regions=None, pause=lambda: 0.0):
    """Every place a player id (u32) sits in the game's memory: {address: id}, or None when stopped. One
    pass over memory into one buffer kept for the pass (no new 32 MB buffer and two copies per read), the
    ids picked with a table over their range: about 5 ms of work per 16 MB. pause(): seconds to wait after
    each 16 MB (more while the match is played: the game first)."""
    want = np.array(sorted(ids), np.uint32)
    if not len(want):
        return {}
    lo, hi = int(want[0]), int(want[-1])
    table = np.zeros(hi - lo + 1, bool)
    table[want - lo] = True
    buf = __import__('ctypes').create_string_buffer(CHUNK)
    whole = np.frombuffer(buf, '<u4')
    tmp, m = np.empty(CHUNK // 4, np.uint32), np.empty(CHUNK // 4, bool)
    into = getattr(proc, 'read_into', None)
    hits = {}
    for base, size in (proc.regions() if regions is None else regions):
        pos = 0
        while pos < size:
            if stop():
                return None
            n = min(CHUNK, size - pos)
            if into is not None:
                if not into(base + pos, buf, n):
                    break
                u = whole[:n // 4]
            else:
                raw = proc.read(base + pos, n)
                if raw is None:
                    break
                u = np.frombuffer(raw, '<u4', n // 4)
            k = len(u)
            np.subtract(u, lo, out=tmp[:k])          # below lo wraps round to a huge value
            np.less_equal(tmp[:k], hi - lo, out=m[:k])
            c = np.flatnonzero(m[:k])
            if len(c):
                c = c[table[tmp[c]]]
                for i, v in zip(c.tolist(), u[c].tolist()):
                    hits[base + pos + i * 4] = v
            pos += n
            w = pause()
            if w:
                time.sleep(w)
    return hits


def refs(proc, targets, span, regions, stop=lambda: False, pause=lambda: 0.0, most=20000):
    """Where the game keeps a pointer to (up to `span` bytes before) each target:
    {location: (target, target - pointer)}, or None when stopped."""
    T = np.array(sorted(set(int(t) for t in targets)), np.int64)
    if not len(T):
        return {}
    lo, hi = int(T[0]) - span, int(T[-1])
    buf = __import__('ctypes').create_string_buffer(CHUNK)
    whole = np.frombuffer(buf, '<i8')
    into = getattr(proc, 'read_into', None)
    out = {}
    for base, size in regions:
        pos = 0
        while pos < size:
            if stop():
                return None
            n = min(CHUNK, size - pos) // 8 * 8
            if n <= 0:
                break
            if into is not None:
                if not into(base + pos, buf, n):
                    break
                q = whole[:n // 8]
            else:
                raw = proc.read(base + pos, n)
                if raw is None:
                    break
                q = np.frombuffer(raw, '<i8')
            c = np.flatnonzero((q >= lo) & (q <= hi))
            if len(c):
                v = q[c]
                i = np.minimum(np.searchsorted(T, v, side='left'), len(T) - 1)
                d = T[i] - v
                ok = (d >= 0) & (d <= span)
                for j in np.flatnonzero(ok).tolist():
                    out[base + pos + int(c[j]) * 8] = (int(T[i[j]]), int(d[j]))
                    if len(out) >= most:
                        return out
            pos += n
            w = pause()
            if w:
                time.sleep(w)
    return out


def arrays(found_refs, addrs, need=18):
    """Places holding pointers to most of the 22 objects close together (the game's list of them):
    [{'loc', 'entries': [[offset, slot, delta]]}]."""
    slot_of = {a: s for s, a in addrs.items()}
    locs = sorted(found_refs)
    out, used = [], set()
    for i, L in enumerate(locs):
        if L in used:
            continue
        ent, slots = [], set()
        for M in locs[i:]:
            if M - L > 22 * 0x80:
                break
            tgt, d = found_refs[M]
            s = slot_of.get(tgt)
            if s is not None and s not in slots:
                slots.add(s)
                ent.append([M - L, s, d])
        if len(slots) >= need:
            out.append({'loc': L, 'entries': ent})
            used.update(L + e[0] for e in ent)
    return out


def from_arrays(proc, learned, home, away, mod=None):
    """The match's objects straight from a list of them learnt before (same game session: the same place;
    `roots`: a pointer in the exe's static data to it, kept by the game across matches). -> {slot: address}"""
    home, away = set(home), set(away)
    tries = []
    for r in learned.get('roots') or []:
        if mod is None:
            continue
        raw = proc.read(mod + r['mod'], 8)
        if raw:
            tries.append((struct.unpack('<q', raw)[0] + r['delta'], r['entries']))
    for a in learned.get('arrays') or []:
        tries.append((a['loc'], a['entries']))
    best = None
    for L, entries in tries:
        # every pointer around the entries learnt, each object's slot from its own header (a list learnt with
        # 20 of the 22 gave 20/22 in the next matches; the two others sit next to them)
        offs = [e[0] for e in entries]
        deltas = sorted({e[2] for e in entries})
        lo, hi = min(offs) - 0x40, max(offs) + 0x48
        raw = proc.read(L + lo, hi - lo)
        if not raw:
            continue
        got, tag_of = {}, {}
        for o in range(0, len(raw) - 7, 8):
            v = struct.unpack_from('<q', raw, o)[0]
            if not 0x10000 < v < 0x7FFFFFFF0000:
                continue
            for d in deltas:
                h = head(proc, v + d)
                if h is None or h[1] in got or h[2] not in (home if h[1] < 11 else away):
                    continue
                got[h[1]], tag_of[h[1]] = v + d, h[0]
                break
        if not got:
            continue
        tags = {}
        for t in tag_of.values():
            tags[t] = tags.get(t, 0) + 1
        tag = max(tags, key=tags.get)
        got = {sl: a for sl, a in got.items() if tag_of[sl] == tag}       # this match's objects only
        if len(got) >= 18 and (best is None or len(got) > len(best)):
            best = got
            if len(best) == 22:
                break
    return best


def tables(hits, home, away, most=24):
    """Tables of one record per player among the places the ids sit: 11 or more of one team's players, all
    different, one stride apart (the squad lists, the team sheet, the game's other copies). Where the game may
    count each player's goals and cards. -> [(address, stride, records, team)]"""
    team_of = {v: 0 for v in home}
    team_of.update({v: 1 for v in away})
    by = sorted((a, v) for a, v in hits.items() if v in team_of)
    out, seen = [], set()
    for i, (a, v) in enumerate(by):
        t = team_of[v]
        for j in range(i + 1, min(i + 12, len(by))):
            b, w = by[j]
            st = b - a
            if st < 0x10 or st > 0x2000 or st % 4 or team_of[w] != t or w == v or (a, st) in seen:
                continue
            if team_of.get(hits.get(a - st)) == t:          # not the first record of its table
                continue
            run = [v]
            while True:
                x = hits.get(a + len(run) * st)
                if x is None or team_of.get(x) != t or x in run:
                    break
                run.append(x)
            seen.add((a, st))
            if len(run) >= 11:
                out.append((a, st, len(run), t))
    out.sort(key=lambda r: (r[1], -r[2]))
    keep = []
    for a, st, n, t in out:                  # every other record of a table found already: the same table
        if any(st % st2 == 0 and a2 <= a < a2 + n2 * st2 and (a - a2) % st2 == 0 for a2, st2, n2, _ in keep):
            continue
        keep.append((a, st, n, t))
    keep.sort(key=lambda r: (-r[2], r[1]))
    return keep[:most]


def head(proc, a):
    """(match value, slot, player id) of an object at a, or None if it does not look like one."""
    raw = proc.read(a - 16, 32)
    if not raw or len(raw) < 32:
        return None
    tag, _, slot, entry = struct.unpack_from('<IIII', raw, 0)
    pid, _, entry2, pid2 = struct.unpack_from('<IIII', raw, 16)
    if pid != pid2 or entry != entry2 or slot > 21:
        return None
    return tag, slot, pid


def find(proc, hits, home, away, why=None):
    """The match's 22 objects among the places the ids sit: {slot: address} (most of the 22 at least, both
    teams), or None. Objects left from an earlier match carry another match value or other players.
    why: filled with what was seen (pairs, objects, the largest groups) to tell a miss."""
    home, away = set(home), set(away)
    groups = {}
    pairs = headed = 0
    for a, v in hits.items():
        if hits.get(a + ID2) != v or (v not in home and v not in away):
            continue
        pairs += 1
        h = head(proc, a)
        if h is None:
            continue
        headed += 1
        tag, slot, pid = h
        if pid not in (home if slot < 11 else away):
            continue
        groups.setdefault(tag, {}).setdefault(slot, []).append(a)
    if why is not None:
        why.update(pairs=pairs, objects=headed,
                   groups=sorted((len(g) for g in groups.values()), reverse=True)[:3])
    if not groups:
        return None
    tag = max(groups, key=lambda t: len(groups[t]))
    best = groups[tag]
    if len(best) < 18 or sum(1 for s in best if s < 11) < 8 or sum(1 for s in best if s >= 11) < 8:
        return None
    out = {s: sorted(v)[0] for s, v in best.items()}
    for t, g in groups.items():                # a slot whose object the game made again (another value)
        if t != tag:
            for s, v in g.items():
                if s not in out and len(v) == 1:
                    out[s] = v[0]
    return out


SIZE = 0x1A5E0                   # an object, up to the next one's header (0x1A5F0 apart)


def ball_probe(proc, addrs, samples=4, gap=0.25, why=None):
    """Places that may hold the ball, from the 22 objects alone (no pass over memory): an (x, h, z) every
    object holds the same and that moves (the ball as every player knows it), or one in a structure all
    22 point at (the match, the ball). -> [address]; the caller checks them with the players."""
    objs = list(addrs.values())
    rows = []
    for t in range(samples):
        got = [proc.read(a, SIZE) for a in objs]
        if any(g is None for g in got):
            return []
        rows.append(np.stack([np.frombuffer(g, '<u4') for g in got]))
        if t < samples - 1:
            time.sleep(gap)
    out = []
    # 1. the same value in every object, at the same place, changing over time
    same = np.ones(rows[0].shape[1], bool)
    for r in rows:
        same &= (r == r[0]).all(0)
    f0, f1 = rows[0][0].view('<f4'), rows[-1][0].view('<f4')
    n = len(f0) - 2
    with np.errstate(invalid='ignore', over='ignore'):
        ok = (same[:n] & same[1:n + 1] & same[2:n + 2] & (np.abs(f0[:n]) <= 56) & (np.abs(f0[2:n + 2]) <= 37)
              & (f0[1:n + 1] >= 0.1) & (f0[1:n + 1] <= 30)
              & ((f0[:n] != f1[:n]) | (f0[2:n + 2] != f1[2:n + 2])))
    shared = [objs[0] + int(i) * 4 for i in np.flatnonzero(ok)]
    out += shared
    # 2. what every object points at
    q0 = rows[0][:, :rows[0].shape[1] // 2 * 2].copy().view('<u8')
    sameq = (q0 == q0[0]).all(0)
    ptrs = sorted({int(v) for v in q0[0][sameq] if 0x10000 < int(v) < 0x7FFFFFFF0000 and int(v) % 8 == 0
                   and not any(a <= int(v) < a + SIZE for a in objs)})[:300]
    pointed = []
    for p in ptrs:
        a, b = proc.read(p, 0x1000), None
        if a is None:
            continue
        pointed.append((p, np.frombuffer(a, '<f4')))
    time.sleep(gap)
    for p, fa in pointed:
        b = proc.read(p, 0x1000)
        if b is None:
            continue
        fb = np.frombuffer(b, '<f4')
        m = len(fa) - 2
        with np.errstate(invalid='ignore', over='ignore'):
            ok = ((np.abs(fa[:m]) <= 56) & (np.abs(fa[2:m + 2]) <= 37) & (fa[1:m + 1] >= 0.1) & (fa[1:m + 1] <= 30)
                  & ((fa[:m] != fb[:m]) | (fa[2:m + 2] != fb[2:m + 2])) & (np.abs(fa[:m] - fb[:m]) < 10))
        out += [p + int(i) * 4 for i in np.flatnonzero(ok)]
    if why is not None:
        why.update(shared=len(shared), pointers=len(ptrs), pointed=len(out) - len(shared))
    return out


def read_one(proc, a):
    """(player id, shirt number, x, z) of one object, or None (not a player object now)."""
    raw = proc.read(a, READ)
    if not raw or len(raw) < READ:
        return None
    pid, pid2 = struct.unpack_from('<I', raw, 0)[0], struct.unpack_from('<I', raw, ID2)[0]
    x, _, z = struct.unpack_from('<fff', raw, X)
    if pid != pid2 or not (math.isfinite(x) and math.isfinite(z)) or abs(x) > 70 or abs(z) > 55:
        return None
    num = raw[NUM]
    return pid, (num if 0 < num < 100 else None), float(x), float(z)


class SimState:
    """The 22 objects of one match and what was read from them (slot 0-10 home, 11-21 away)."""

    def __init__(self, addrs, home, away, how=''):
        self.addrs = dict(addrs)                 # slot -> address
        self.home, self.away = set(home), set(away)
        self.how = how
        self.found_at = time.time()
        self.pids = [None] * 22                  # who plays in each slot (as last settled)
        self.pend = {}                           # slot -> (new id, since): a change seen, not settled yet
        self.last, self.moved = {}, {}
        # all 22 under one match value: trusted at once (the numbers show even in the pause menu); fewer: once
        # they are seen moving. Either way dropped if they do not move in 20 s of play (a copy left behind)
        self.live = len(self.addrs) == 22
        self.run_t = 0.0
        self.bad_since = {}
        self.changed = {}                        # slot -> seconds of play its place has not changed at all
        self.noted = None
        self.ball = None
        self.layout = None

    def read(self, proc):
        """Each slot: (player id, shirt number, x, z) or None (no object, unreadable, not of its team)."""
        out = [None] * 22
        for s, a in self.addrs.items():
            g = read_one(proc, a)
            if g is not None and g[0] in (self.home if s < 11 else self.away):
                out[s] = g
        return out

    def note(self, got, now, running=False):
        """Movement (the live state moves; a copy left from before does not). -> slots unreadable 2 s"""
        dt = min(now - self.noted, 1.0) if self.noted is not None else 0.0
        self.noted = now
        if running:
            self.run_t += dt
        for s in self.addrs:
            g = got[s]
            if g is None:
                self.bad_since.setdefault(s, now)
                continue
            self.bad_since.pop(s, None)
            last = self.last.get(s)
            if last is not None:
                d = math.hypot(g[2] - last[0], g[3] - last[1])
                if d < 5:
                    self.moved[s] = self.moved.get(s, 0.0) + d
                if running:
                    self.changed[s] = self.changed.get(s, 0.0) + dt if d == 0 else 0.0
            self.last[s] = (g[2], g[3])
        if not self.live and sum(1 for v in self.moved.values() if v > 2.0) >= 8:
            self.live = True
        return [s for s, t in self.bad_since.items() if now - t > 2.0]

    def stale(self):
        """20 s of play and fewer than eight of them moved: not the match being played."""
        return self.run_t > 20 and sum(1 for v in self.moved.values() if v > 2.0) < 8

    def still(self):
        """Slots whose place has not changed at all for 90 s of play while the others' did: a copy the game
        left behind (it made that player's object anew)."""
        if sum(1 for v in self.changed.values() if v < 5) < 15:
            return []
        return [s for s, v in self.changed.items() if v > 90]

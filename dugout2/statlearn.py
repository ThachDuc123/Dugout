"""Where the game counts each player's goals and cards during a match, learnt from the game itself.

Every few seconds Dugout keeps a copy of the players' records it already reads (the squad lists, 0x100
bytes per player, and the game's own player objects). When something happens that Dugout knows for sure
(the score changes; the game loads a card screen, seen in the files list Dugout.lua writes), the records
just before and just after are compared: a byte that went up by one for exactly one player is a candidate
for that kind of event. A place that did so at every such event, and never without one, is the game's
counter: from then on the scorer (or the player booked) is read from it at once.
Pure logic: the tracker reads the memory and calls this.
"""
import zlib

import numpy as np

KEEP = 8            # snapshots kept (one every few seconds)
NEED = 2            # events a place must have explained before it is used
MOST = 4000         # candidate places kept per kind (whole player objects hold many counters)


class StatLearner:
    def __init__(self, learned=None):
        d = learned or {}
        # kind -> {key: [hits, events, unexplained]}; key = "src:offset"
        self.cands = {k: {kk: list(v) for kk, v in c.items()} for k, c in (d.get('cands') or {}).items()}
        self.events = dict(d.get('events') or {})          # kind -> events seen
        self.snaps = []                                    # [(t, {src: (pids, uint8 array)})]

    def state(self):
        return {'cands': self.cands, 'events': self.events}

    # ------------------------------------------------------------------ snapshots
    def snapshot(self, t, blocks):
        """blocks: {src: [(pid, bytes)]} -> stored as arrays (one row per player)."""
        snap = {}
        for src, rows in blocks.items():
            rows = [(p, b) for p, b in rows if p and b]
            if not rows:
                continue
            n = min(len(b) for _, b in rows)
            snap[src] = ([p for p, _ in rows], np.array([np.frombuffer(b[:n], np.uint8) for _, b in rows]))
        self.snaps.append((t, snap))
        del self.snaps[:-KEEP]
        return snap

    def before(self, t):
        older = [s for s in self.snaps if s[0] <= t - 0.3]
        return older[-1] if older else None

    # ------------------------------------------------------------------ comparing
    @staticmethod
    def _ups(s0, s1, allowed=None):
        """{key: pid}: places where exactly one player's byte went up by one (from a small count) and
        nobody else's changed there."""
        out = {}
        for src, (p1, a1) in s1.items():
            if src not in s0:
                continue
            p0, a0 = s0[src]
            idx0 = {p: i for i, p in enumerate(p0)}
            rows = [(i, idx0[p]) for i, p in enumerate(p1) if p in idx0]
            if not rows:
                continue
            n = min(a0.shape[1], a1.shape[1])
            A = a0[[j for _, j in rows], :n].astype(np.int16)
            B = a1[[i for i, _ in rows], :n].astype(np.int16)
            D = B - A
            changed = (D != 0).sum(0)
            up = (D == 1) & (A < 30)
            for off in np.flatnonzero((changed == 1) & up.any(0)):
                r = int(np.flatnonzero(up[:, off])[0])
                pid = p1[rows[r][0]]
                if allowed is None or pid in allowed:
                    out[f'{src}:{int(off)}'] = pid
        return out

    def learn(self, kind, t_event, s1, allowed=None):
        """An event of `kind` happened at t_event; s1 is a snapshot taken a few seconds later.
        -> the player the learnt counter names (or None)."""
        b = self.before(t_event)
        if b is None:
            return None
        ups = self._ups(b[1], s1, allowed)
        c = self.cands.setdefault(kind, {})
        self.events[kind] = self.events.get(kind, 0) + 1
        for key in ups:
            c.setdefault(key, [0, 0, 0])[0] += 1
        for key, v in c.items():
            v[1] = self.events[kind]
        # forget places that explained less than half of the events (keeps the table small)
        for key in [k for k, v in c.items() if v[1] >= 3 and v[0] < v[1] / 2]:
            del c[key]
        if len(c) > MOST:                                  # the ones that explained the most events
            for key in sorted(c, key=lambda k: -c[k][0])[MOST:]:
                del c[key]
        f = self.field(kind)
        return ups.get(f) if f else None

    def unexplained(self, s0, s1, quiet_kinds):
        """Between two snapshots with no event of these kinds: places that went up anyway are not
        their counters."""
        ups = self._ups(s0, s1)
        for kind in quiet_kinds:
            c = self.cands.get(kind) or {}
            for key in [k for k in c if k in ups]:
                c[key][2] += 1
                if c[key][2] > c[key][0] + 1:          # goes up without the event more than with it
                    del c[key]

    @staticmethod
    def dump(path, kind, team, s0, s1):
        """The two snapshots of an event, to the recording (studied after the match if no counter is learnt)."""
        parts = {}
        for name, snap in (('before', s0), ('after', s1)):
            for src, (pids, arr) in (snap or {}).items():
                parts[f'{name}|{src}|pids'] = np.array(pids, np.int64)
                parts[f'{name}|{src}|data'] = arr
        meta = np.frombuffer(zlib.compress(repr({'kind': kind, 'team': team}).encode()), np.uint8)
        np.savez_compressed(path, meta=meta, **parts)

    def field(self, kind):
        """The learnt counter of this kind: explained (nearly) every event, never went up without one."""
        best = None
        for key, (hits, events, bad) in (self.cands.get(kind) or {}).items():
            # a card the game shows with a screen it already loaded leaves no file: a counter may go up
            # 'unexplained' now and then
            if hits >= NEED and bad <= hits // 4 and hits >= 0.75 * events:
                if best is None or hits > best[1]:
                    best = (key, hits)
        return best[0] if best else None

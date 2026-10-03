"""Raw recording of each match on the live map: what Dugout read from the game ten times a second and what
it decided, in the career folder (live\\rec\\<date-time>_<match>\\). With it a detection (substitutions,
passes, shots) can be improved and tried again on a past match without playing it again.

 match.json    the fixture, both squads (id, name, number, role), the team sheet, the record addresses
 frames.jsonl  one line per 0.1 s: [time, clock, period, [home goals, away goals], running,
               ball [x, z, h] or null, [[x, z, h] or null for every record followed, by index]]
               (the game's own axes: x along the pitch, z across, h the height)
 events.jsonl  what Dugout saw and decided: each step of a substitution, the game's line-ups when they
               change, bodies found, goals, shots, the timeline
Only the last KEEP matches are kept. Restarting Dugout in the same match carries on the same recording.
"""
import json
import math
import os
import shutil
import time

KEEP = 20


def _clean(v):
    if isinstance(v, float):
        return round(v, 3) if math.isfinite(v) else None
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if hasattr(v, 'item'):                      # numpy numbers
        return _clean(v.item())
    return v


class Recorder:
    def __init__(self, root, key, meta, session=None):
        """root: the career's live\\rec folder; key: the match; session: the game process (a recording of the
        same match in the same game session is carried on)."""
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.folder = self._find(key, session) or os.path.join(
            root, time.strftime('%Y%m%d-%H%M%S') + '_' + str(key or 'tran').replace(':', '_'))
        self.carried = os.path.exists(os.path.join(self.folder, 'match.json'))
        os.makedirs(self.folder, exist_ok=True)
        self.meta = dict(meta, key=key, session=session)
        if not self.carried:
            self.meta['started'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self._write_meta()
        self.frames = open(os.path.join(self.folder, 'frames.jsonl'), 'a', encoding='utf-8')
        self.events = open(os.path.join(self.folder, 'events.jsonl'), 'a', encoding='utf-8')
        self.at = 0.0
        self.flushed = time.time()
        self.mem = {}
        self.n = 0
        self._prune()

    def _find(self, key, session):
        try:
            names = sorted(os.listdir(self.root), reverse=True)[:3]
        except OSError:
            return None
        for name in names:
            path = os.path.join(self.root, name)
            try:
                with open(os.path.join(path, 'match.json'), encoding='utf-8') as f:
                    m = json.load(f)
                if m.get('key') == key and m.get('session') == session and time.time() - os.path.getmtime(path) < 3 * 3600:
                    return path
            except (OSError, ValueError):
                continue
        return None

    def _prune(self):
        try:
            names = sorted(n for n in os.listdir(self.root) if os.path.isdir(os.path.join(self.root, n)))
            for n in names[:-KEEP]:
                shutil.rmtree(os.path.join(self.root, n), ignore_errors=True)
        except OSError:
            pass

    def _write_meta(self):
        tmp = os.path.join(self.folder, 'match.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_clean(self.meta), f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(self.folder, 'match.json'))

    def update_meta(self, **kv):
        self.meta.update(kv)
        try:
            self._write_meta()
        except OSError:
            pass

    def frame(self, now, clock, period, score, running, ball, P):
        """Ten times a second at most."""
        if now - self.at < 0.095 or self.frames is None:
            return
        self.at = now
        pts = []
        for v in P:
            x, z, h = float(v[0]), float(v[1]), float(v[2])
            pts.append([round(x, 2), round(z, 2), round(h, 2)] if math.isfinite(x) and math.isfinite(z) and math.isfinite(h) else None)
        b = [round(float(ball[0]), 2), round(float(ball[1]), 2), round(float(ball[2]), 2)] if ball is not None else None
        self.frames.write(json.dumps([round(now, 2), clock, period, score, bool(running), b, pts], separators=(',', ':')) + '\n')
        self.n += 1
        self._flush(now)

    def event(self, now_, clock_, kind_, **data):
        """One line: what happened (`data` may hold its own 'clock': the game minute it happened at)."""
        if self.events is None:
            return
        data.pop('kind', None)
        self.events.write(json.dumps(_clean({**data, 't': round(now_, 2), 'c': clock_, 'kind': kind_}), ensure_ascii=False,
                                     separators=(',', ':')) + '\n')
        self._flush(now_)

    def memory(self, now, clock, name, value):
        """Something read from the game (a line-up, a squad list): written when it changes."""
        v = _clean(value)
        if self.mem.get(name) == v:
            return
        self.mem[name] = v
        self.event(now, clock, 'mem', name=name, value=v)

    def _flush(self, now):
        if now - self.flushed >= 2.0:
            self.flushed = now
            try:
                self.frames.flush()
                self.events.flush()
            except (OSError, ValueError):
                pass

    def past_events(self, kind):
        """Events of one kind already written (a restart in the same match)."""
        out = []
        try:
            self.events.flush()
            with open(os.path.join(self.folder, 'events.jsonl'), encoding='utf-8') as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get('kind') == kind:
                        out.append(e)
        except OSError:
            pass
        return out

    def close(self, **kv):
        self.update_meta(ended=time.strftime('%Y-%m-%d %H:%M:%S'), frames=self.n, **kv)
        for f in (self.frames, self.events):
            try:
                f.close()
            except (OSError, ValueError, AttributeError):
                pass
        self.frames = self.events = None

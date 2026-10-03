"""Per-career storage under data/careers/<KONAMI folder>_<slot>/.

timeline/<date>.npz   every save the game date moves on, the players whose data changed since
                      the previous snapshot (the first snapshot holds everyone): age, 25 abilities,
                      skills, playing style, position grades and club. Rebuilding them gives each
                      player's development day by day; it is what the AI learns individual growth from.
conditions/<date>.npz every player's condition arrow and days out at each saved date (form stability,
                      injury record).
matches.json          every finished match of the managed club with both line-ups (the save only
                      keeps the current season, this keeps them all).
events.json           the inbox.
predictions.json      the AI's projected peak for the squad at every snapshot (to show how the
                      prediction moved and to announce big changes).
seen.json             what the previous load looked like, to tell what is new.
tasks.json            what the manager's answers in the conversations asked to follow up.
match_preds.json      the AI's last pre-match prediction of every fixture, and how it turned out.
world/<season>.json.gz every match played in the world with both line-ups and their strength (the save
                      drops the previous season at the season change; the match model learns from all).
tactics.json          both clubs' raw Game Plan rows as saved last before each of the club's matches
                      (to learn later which tactics work against what).
market/<date>.npz     every player's market value read live from the game (not in the save), with
                      the club budget in market/budget.json.
bundle.json           the last full screen payload, served instantly while a save is being read.
"""
import datetime as dt
import gzip
import json
import os
import shutil
import threading

import numpy as np

from . import config

N_AB = 25


def _read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data, compact=True):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Timeline:
    """Delta-coded player snapshots of one career."""

    FIELDS = ('age', 'abilities', 'skills', 'style', 'grades', 'team')

    def __init__(self, folder):
        self.dir = os.path.join(folder, 'timeline')
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.RLock()
        self._loaded = False
        self.dates = []
        self.deltas = []          # per date: dict of arrays (ids + FIELDS)
        self.state = None         # latest full state: dict pid -> row in self.cur arrays

    # ------------------------------------------------------------- persistence
    def _files(self):
        out = []
        for f in os.listdir(self.dir):
            if f.endswith('.npz'):
                try:
                    out.append((dt.date.fromisoformat(f[:-4]), f))
                except ValueError:
                    pass
        return sorted(out)

    def load(self):
        with self.lock:
            if self._loaded:
                return
            self.dates, self.deltas = [], []
            for d, f in self._files():
                z = np.load(os.path.join(self.dir, f))
                self.dates.append(d)
                self.deltas.append({k: z[k] for k in ('ids',) + self.FIELDS})
            self._rebuild_current()
            self._loaded = True

    def _rebuild_current(self):
        """Full latest state from all deltas."""
        slot = {}
        cols = {k: [] for k in self.FIELDS}
        ids = []
        for delta in self.deltas:
            for r, pid in enumerate(delta['ids']):
                pid = int(pid)
                if pid not in slot:
                    slot[pid] = len(ids)
                    ids.append(pid)
                    for k in self.FIELDS:
                        cols[k].append(delta[k][r])
                else:
                    j = slot[pid]
                    for k in self.FIELDS:
                        cols[k][j] = delta[k][r]
        self.cur_slot = slot
        self.cur = {k: (np.array(v) if v else None) for k, v in cols.items()}
        self.cur_ids = np.array(ids, dtype=np.int64)

    # ------------------------------------------------------------------ record
    def record(self, snap):
        """Store the snapshot if the game date moved on (or replace today's). Returns True if stored."""
        self.load()
        with self.lock:
            if self.dates and snap.date < self.dates[-1] - dt.timedelta(days=45):
                # The slot now holds a different (earlier) career: keep the old timeline aside.
                archive = os.path.join(os.path.dirname(self.dir),
                                       'archive_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S'))
                os.makedirs(archive, exist_ok=True)           # next to the files Career.reset put aside
                shutil.move(self.dir, os.path.join(archive, 'timeline'))
                os.makedirs(self.dir)
                self._loaded = False
                self.load()
            if self.dates and snap.date < self.dates[-1]:
                return False                                # an older save of the same career: ignore
            if self.dates and snap.date == self.dates[-1]:
                self.dates.pop()
                self.deltas.pop()
                self._rebuild_current()
            new = {'ids': snap.ids.astype(np.int64), 'age': snap.age.astype(np.uint8),
                   'abilities': np.clip(snap.abilities, 0, 255).astype(np.uint8),
                   'skills': snap.skills.astype(np.uint64), 'style': snap.style.astype(np.uint8),
                   'grades': snap.grades.astype(np.uint8), 'team': snap.team.astype(np.int64)}
            if self.cur_ids.size:
                rows = np.array([self.cur_slot.get(int(p), -1) for p in new['ids']])
                known = rows >= 0
                changed = ~known
                r = np.maximum(rows, 0)
                for k in self.FIELDS:
                    old = self.cur[k][r]
                    diff = (old != new[k])
                    if diff.ndim > 1:
                        diff = diff.any(1)
                    changed |= known & diff
                delta = {k: v[changed] for k, v in new.items()}
            else:
                delta = new
            path = os.path.join(self.dir, f'{snap.date.isoformat()}.npz')
            np.savez_compressed(path + '.tmp.npz', **delta)
            os.replace(path + '.tmp.npz', path)
            self.dates.append(snap.date)
            self.deltas.append(delta)
            self._rebuild_current()
            return True

    # ------------------------------------------------------------------- query
    def history(self, pid):
        """[(date, age, abilities(25), skills, style, grades(13), team)] for one player, oldest first."""
        self.load()
        out = []
        with self.lock:
            for d, delta in zip(self.dates, self.deltas):
                hit = np.nonzero(delta['ids'] == pid)[0]
                if len(hit):
                    r = hit[0]
                    out.append((d, int(delta['age'][r]), delta['abilities'][r].astype(np.float32),
                                int(delta['skills'][r]), int(delta['style'][r]), delta['grades'][r].copy(),
                                int(delta['team'][r])))
        return out

    def identity(self, pid, current_age):
        """History of the player's current generation: a regen restarts at 16, so entries before
        the age went backwards belong to the retired player."""
        h = [e for e in self.history(pid) if e[1] <= current_age]
        for k in range(len(h) - 1, 0, -1):
            if h[k][1] < h[k - 1][1]:
                return h[k:]
        return h

    def states_at(self, max_points=24, min_gap_days=30):
        """Full (ids, age, abilities) states at a spaced selection of dates (for learning drift)."""
        self.load()
        with self.lock:
            if not self.dates:
                return []
            pick, last = [], None
            for k, d in enumerate(self.dates):
                if last is None or (d - last).days >= min_gap_days:
                    pick.append(k)
                    last = d
            pick = pick[-max_points:]
            slot, ids, age, ab = {}, [], [], []
            out = []
            for k, (d, delta) in enumerate(zip(self.dates, self.deltas)):
                for r, pid in enumerate(delta['ids']):
                    pid = int(pid)
                    j = slot.get(pid)
                    if j is None:
                        slot[pid] = len(ids)
                        ids.append(pid)
                        age.append(int(delta['age'][r]))
                        ab.append(delta['abilities'][r])
                    else:
                        age[j] = int(delta['age'][r])
                        ab[j] = delta['abilities'][r]
                if k in pick:
                    out.append((d, np.array(ids, dtype=np.int64), np.array(age, dtype=np.int32),
                                np.array(ab, dtype=np.float32)))
            return out

    def span_pairs(self, min_years=0.4):
        """(first, last, years) per player identity across the timeline, for retraining growth."""
        states = self.states_at(max_points=2, min_gap_days=1)
        if len(states) < 2:
            return []
        (d0, ids0, age0, ab0), (d1, ids1, age1, ab1) = states[0], states[-1]
        years = (d1 - d0).days / 365.25
        if years < min_years:
            return []
        row1 = {int(p): i for i, p in enumerate(ids1)}
        out = []
        for i, p in enumerate(ids0):
            j = row1.get(int(p))
            if j is None or abs((age1[j] - age0[i]) - years) > 1.2:
                continue
            gk = ab0[i][20:].mean() > 60
            out.append(({'abilities': ab0[i], 'age': int(age0[i]), 'gk': bool(gk)},
                        {'abilities': ab1[j], 'age': int(age1[j])}, years))
        return out


class CondLog:
    """conditions/<date>.npz: every player's condition arrow and days out at each saved game date.
    Over time this shows who keeps his form and who is often injured (the database's own form and
    injury-resistance values could not be located reliably in FL26's Player.bin)."""

    def __init__(self, folder):
        self.dir = os.path.join(folder, 'conditions')
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.RLock()
        self.data = None                        # date -> (ids, cond, unavail)

    def load(self):
        with self.lock:
            if self.data is not None:
                return
            self.data = {}
            for f in sorted(os.listdir(self.dir)):
                if f.endswith('.npz') and '.tmp' not in f:
                    try:
                        z = np.load(os.path.join(self.dir, f))
                        self.data[dt.date.fromisoformat(f[:-4])] = (z['ids'], z['cond'], z['unavail'])
                    except (OSError, ValueError, KeyError):
                        pass

    def record(self, snap):
        self.load()
        with self.lock:
            if self.data and snap.date < max(self.data):
                return
            ids, cond, un = snap.ids.astype(np.uint32), snap.cond.astype(np.int8), snap.unavail.astype(np.int16)
            path = os.path.join(self.dir, f'{snap.date.isoformat()}.npz')
            np.savez_compressed(path + '.tmp.npz', ids=ids, cond=cond, unavail=un)
            os.replace(path + '.tmp.npz', path)
            self.data[snap.date] = (ids, cond, un)

    def player(self, pid):
        """[(date, cond, days out)] of one player, oldest first."""
        self.load()
        out = []
        with self.lock:
            for d in sorted(self.data):
                ids, cond, un = self.data[d]
                hit = np.nonzero(ids == pid)[0]
                if len(hit):
                    out.append((d, int(cond[hit[0]]), int(un[hit[0]])))
        return out

    def summary(self, pid):
        h = [x for x in self.player(pid) if x[1] >= 0]
        if not h:
            return {'n': 0}
        c = np.array([x[1] for x in h])
        spells, prev, worst = 0, 0, 0
        for _, _, u in self.player(pid):
            if u > 0 and prev == 0:
                spells += 1
            worst = max(worst, u)
            prev = u
        out = {'n': len(h), 'first': h[0][0].isoformat(), 'mean': round(float(c.mean()), 2),
               'good': int((c >= 3).sum()), 'bad': int((c <= 1).sum()), 'injuries': spells, 'worst_days': worst,
               'history': [[d.isoformat(), k] for d, k, _ in h[-30:]]}
        if len(h) >= 5:
            sd = float(c.std())
            out['stability'] = 'ổn định' if sd <= 0.6 else 'thất thường' if sd >= 1.1 else 'bình thường'
        return out


class WorldLog:
    """world/<season>.json.gz: every match played in the world, kept for good. A row is
    {k: fixture key, d: date, c: competition, h/a: clubs, hg/ag: goals, hs/as: [XI, attack, defence]
    strength when first seen, hl/al: [player, position code, started, minutes, rating x10, goals, assists]}."""

    def __init__(self, folder):
        self.dir = os.path.join(folder, 'world')
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.RLock()
        self.seasons = None                     # season -> {key: row}

    @staticmethod
    def season_of(date_iso):
        y, m = int(date_iso[:4]), int(date_iso[5:7])
        y = y if m >= 7 else y - 1
        return f'{y}-{(y + 1) % 100:02d}'

    def load(self):
        with self.lock:
            if self.seasons is not None:
                return
            self.seasons = {}
            for f in sorted(os.listdir(self.dir)):
                if f.endswith('.json.gz'):
                    try:
                        with gzip.open(os.path.join(self.dir, f), 'rt', encoding='utf-8') as fh:
                            self.seasons[f[:-8]] = {r['k']: r for r in json.load(fh)}
                    except (OSError, ValueError, KeyError, EOFError):
                        pass

    def merge(self, rows):
        """Add the matches not stored yet (the first sighting is kept). Returns how many were new."""
        self.load()
        new, touched = 0, set()
        with self.lock:
            for r in rows:
                season = self.season_of(r['d'])
                bucket = self.seasons.setdefault(season, {})
                if r['k'] not in bucket:
                    bucket[r['k']] = r
                    new += 1
                    touched.add(season)
            for season in touched:
                path = os.path.join(self.dir, f'{season}.json.gz')
                with gzip.open(path + '.tmp', 'wt', encoding='utf-8', compresslevel=6) as fh:
                    json.dump(list(self.seasons[season].values()), fh, separators=(',', ':'))
                os.replace(path + '.tmp', path)
        return new

    def rows(self):
        self.load()
        with self.lock:
            return [r for season in sorted(self.seasons) for r in self.seasons[season].values()]

    def counts(self):
        self.load()
        with self.lock:
            return {season: len(v) for season, v in sorted(self.seasons.items())}


class MarketLog:
    """market/<date>.npz: every player's market value as the running game showed it that day."""

    def __init__(self, folder):
        self.dir = os.path.join(folder, 'market')
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.Lock()

    def record(self, date, values, budget=None):
        if not values:
            return
        ids = np.fromiter(values.keys(), dtype=np.int64, count=len(values))
        val = np.fromiter(values.values(), dtype=np.int64, count=len(values))
        with self.lock:
            path = os.path.join(self.dir, f'{date.isoformat()}.npz')
            np.savez_compressed(path + '.tmp.npz', ids=ids, value=val)
            os.replace(path + '.tmp.npz', path)
            if budget:
                log = _read_json(os.path.join(self.dir, 'budget.json'), {})
                log[date.isoformat()] = budget
                write_json(os.path.join(self.dir, 'budget.json'), log)

    def dates(self):
        return sorted(f[:-4] for f in os.listdir(self.dir) if f.endswith('.npz') and not f.endswith('.tmp.npz'))


class Career:
    """Everything stored for one save slot."""

    def __init__(self, key):
        self.key = key
        self.dir = os.path.join(config.CAREERS_DIR, key)
        os.makedirs(self.dir, exist_ok=True)
        self.timeline = Timeline(self.dir)
        self.condlog = CondLog(self.dir)
        self.world = WorldLog(self.dir)
        self.market = MarketLog(self.dir)
        self.lock = threading.RLock()
        self.matches = _read_json(self.path('matches.json'), {})
        self.events = _read_json(self.path('events.json'), [])
        self.predictions = _read_json(self.path('predictions.json'), {})
        self.seen = _read_json(self.path('seen.json'), None)
        self.tasks = _read_json(self.path('tasks.json'), [])
        self.match_preds = _read_json(self.path('match_preds.json'), {})
        self.tactics = _read_json(self.path('tactics.json'), {})

    def path(self, name):
        return os.path.join(self.dir, name)

    def bundle_path(self):
        return self.path('bundle.json')

    def save(self):
        with self.lock:
            write_json(self.path('matches.json'), self.matches)
            write_json(self.path('events.json'), self.events[:1500])
            write_json(self.path('predictions.json'), self.predictions)
            write_json(self.path('tasks.json'), self.tasks)
            write_json(self.path('match_preds.json'), self.match_preds)
            write_json(self.path('tactics.json'), self.tactics)
            if self.seen is not None:
                write_json(self.path('seen.json'), self.seen)

    def reset(self):
        """A new career started in this slot: keep the old files aside and start clean."""
        with self.lock:
            archive = os.path.join(self.dir, 'archive_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S'))
            os.makedirs(archive, exist_ok=True)
            for name in ('matches.json', 'events.json', 'predictions.json', 'seen.json', 'tasks.json', 'match_preds.json',
                         'tactics.json', 'backup.json'):
                if os.path.exists(self.path(name)):
                    shutil.move(self.path(name), os.path.join(archive, name))
            for sub in ('conditions', 'world', 'market'):      # per-date logs of the old career
                if os.path.isdir(self.path(sub)):
                    shutil.move(self.path(sub), os.path.join(archive, sub))
            self.condlog, self.world, self.market = CondLog(self.dir), WorldLog(self.dir), MarketLog(self.dir)
            self.matches, self.events, self.predictions, self.seen = {}, [], {}, None
            self.tasks, self.match_preds, self.tactics = [], {}, {}

    def add_event(self, ev):
        with self.lock:
            ev.setdefault('read', False)
            ev['id'] = ev.get('id') or f'{ev["date"]}:{ev["kind"]}:{len(self.events)}:{abs(hash(ev.get("title", ""))) % 10**8}'
            if any(e['id'] == ev['id'] for e in self.events[:300]):
                return
            self.events.insert(0, ev)

    def mark_read(self, ids=None):
        with self.lock:
            for e in self.events:
                if ids is None or e['id'] in ids:
                    e['read'] = True
            write_json(self.path('events.json'), self.events[:1500])

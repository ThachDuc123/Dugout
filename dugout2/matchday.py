"""Matchday: condition and form of both squads, the best XI for the next match, a report on
the opponent, team instructions suited to both line-ups, and a match prediction learnt from
every result in the save.

Everything comes from the save: the condition arrow of every player, the Game Plan of every club
(current XI, formation, team and advanced instructions, see gameplan.py), and every match played
in the world this season with both line-ups and ratings."""
import datetime as dt
import math

import numpy as np

from . import analysis, gameplan, terms
from .events import rating10

POS = terms.POSITIONS
AB = {a: k for k, a in enumerate(terms.ABILITIES)}
COND_LETTER = 'EDCBA'                                 # condition code 0..4 -> the game's letter
COND_OVR = np.array([-3.0, -1.5, 0.0, 1.5, 3.0])      # assumed effect of the arrow, in OVR points
GRADE_PEN = {2: 0.0, 1: -2.0, 0: -7.0}                # playing at an A / B / C position
DEF_ROLES, DM_ROLES, MID_ROLES, AM_ROLES, FWD_ROLES = {1, 2, 3}, {4}, {5, 6, 7}, {8}, {9, 10, 11, 12}
LEFT_ROLES, RIGHT_ROLES = {2, 6, 9}, {3, 7, 10}
PLAYED = 64
SKILL_IDX = {s[0]: k for k, s in enumerate(terms.SKILLS)}
PERIODS = ['0–15', '16–30', '31–45', '46–60', '61–75', '76–90', 'Hiệp phụ']
THREAT_ABILITIES = ('speed', 'acceleration', 'dribbling', 'finishing', 'offensive_awareness', 'low_pass', 'lofted_pass',
                    'heading', 'kicking_power', 'ball_control', 'physical_contact', 'curl')
# pitch coordinates for line-ups without a Game Plan (x 0-104 left to right, y 0-47 own goal forwards)
SPOT = {0: (0, 52), 1: (11, 52), 2: (13, 16), 3: (13, 88), 4: (20, 52), 5: (27, 52), 6: (30, 14), 7: (30, 90),
        8: (34, 52), 9: (44, 16), 10: (44, 88), 11: (40, 52), 12: (46, 52)}


def fdate(f):
    return dt.date(f.year, f.month, f.day)


def fkey(f):
    return f'{f.year:04d}-{f.month:02d}-{f.day:02d}:{f.tournament_id}:{f.home_team}:{f.away_team}'


def ab(snap, i, *names):
    return float(np.mean([snap.abilities[i, AB[n]] for n in names]))


def base_rating(snap, i, role):
    return float(snap.ovr_all[i, role]) + GRADE_PEN[min(int(snap.grades[i, role]), 2)]


def cond_adj(snap, i):
    c = int(snap.cond[i])
    return float(COND_OVR[c]) if c >= 0 else 0.0


def outcome(f, tid):
    home = f.home_team == tid
    gf, ga = (f.home_goals, f.away_goals) if home else (f.away_goals, f.home_goals)
    if gf == ga and (f.home_shootout or f.away_shootout):
        ps = (f.home_shootout, f.away_shootout) if home else (f.away_shootout, f.home_shootout)
        return 'W' if ps[0] > ps[1] else 'L'
    return 'W' if gf > ga else 'L' if gf < ga else 'D'


# ------------------------------------------------------------------------------- world
class World:
    """Every club's played fixtures this season, sorted, and per-player season numbers."""

    def __init__(self, snap):
        self.snap = snap
        self.by_team = {}
        for f in snap.fixtures:
            if f.flags & PLAYED:
                for t in (f.home_team, f.away_team):
                    self.by_team.setdefault(t, []).append(f)
        for v in self.by_team.values():
            v.sort(key=lambda f: (f.year, f.month, f.day, f.kickoff_hour or 0))
        self._stats = {}

    def results(self, tid, n=6):
        s = self.snap
        out = []
        for f in self.by_team.get(tid, [])[-n:]:
            home = f.home_team == tid
            opp = f.away_team if home else f.home_team
            gf, ga = (f.home_goals, f.away_goals) if home else (f.away_goals, f.home_goals)
            out.append({'date': fdate(f).isoformat(), 'opp': opp, 'opp_name': s.club_name(opp), 'home': home,
                        'gf': gf, 'ga': ga, 'outcome': outcome(f, tid), 'comp': s.comp_name(f.tournament_id)})
        return out

    def player_stats(self, tid):
        """pid -> season apps, starts, goals, assists, minutes and ratings (oldest first) for this club."""
        if tid in self._stats:
            return self._stats[tid]
        st = {}
        for f in self.by_team.get(tid, []):
            side = f.home if f.home_team == tid else f.away
            d = fdate(f)
            for a in side:
                if not a.minutes:
                    continue
                x = st.setdefault(int(a.player_id), {'apps': 0, 'starts': 0, 'g': 0, 'a': 0, 'min': 0, 'r': [], 'dates': []})
                x['apps'] += 1
                x['starts'] += 1 if a.started else 0
                x['g'] += a.goals
                x['a'] += a.assists
                x['min'] += a.minutes
                x['dates'].append((d, a.minutes))
                if a.rating_tenths:
                    x['r'].append(a.rating_tenths / 10)
                    x.setdefault('r10', []).append(rating10(a.rating_tenths / 10, a.goals, a.assists,
                                                            a.yellow or a.second_yellow, a.red))
        self._stats[tid] = st
        return st


def form_adj(stats):
    """Recent match ratings against a normal 6.4, in OVR points (needs two rated games)."""
    r = (stats or {}).get('r') or []
    if len(r) < 2:
        return 0.0
    return float(np.clip((np.mean(r[-3:]) - 6.4) * 1.5, -2.0, 2.0))


def minutes_since(stats, since):
    return sum(m for d, m in (stats or {}).get('dates', []) if d >= since)


# ------------------------------------------------------------------------------ model
class MatchModel:
    """Goals of each side ~ Poisson(exp(b . features)), features: the line-ups' OVR difference,
    attack against defence, home, and the competition's scoring rate. Fitted on every match played
    in the world this season (the save's own results) plus the earlier seasons Dugout archived
    (store.WorldLog), tested on the most recent fifth."""

    PRIOR = np.array([0.045, 0.025, 0.22, 1.0])
    PRIOR_B0 = math.log(1.35)

    def __init__(self):
        self.coef, self.b0, self.comp_rate, self.global_rate = self.PRIOR, self.PRIOR_B0, {}, 1.35
        self.metrics = None
        self.n = self.n_now = self.n_history = 0
        self.archive = []

    @staticmethod
    def side(snap, apps):
        vals, att, dfn = [], [], []
        for a in apps:
            if not a.started:
                continue
            i = snap.row.get(int(a.player_id))
            if i is None:
                continue
            role = analysis.match_position(snap, i, a.position_code)
            if role is None:
                continue
            v = base_rating(snap, i, role)
            vals.append(v)
            (att if role in AM_ROLES | FWD_ROLES else dfn if role in DEF_ROLES | DM_ROLES | {0} else []).append(v)
        if len(vals) < 9:
            return None
        xi = float(np.mean(vals))
        return xi, float(np.mean(att)) if att else xi, float(np.mean(dfn)) if dfn else xi

    def _x(self, s, o, home, comp):
        rate = self.comp_rate.get(comp, self.global_rate)
        return [s[0] - o[0], s[1] - o[2], 1.0 if home else 0.0, math.log(rate / self.global_rate)]

    def fit(self, snap, history=()):
        """`history`: archived rows of matches the save no longer holds. Every played match of the
        save is also put in `self.archive`, in the archive's row form, for the caller to store."""
        rows, keys, self.archive = [], set(), []
        for f in snap.fixtures:
            if not f.flags & PLAYED:
                continue
            h, a = self.side(snap, f.home), self.side(snap, f.away)
            k = fkey(f)
            keys.add(k)
            rec = {'k': k, 'd': fdate(f).isoformat(), 'c': int(f.tournament_id), 'h': int(f.home_team),
                   'a': int(f.away_team), 'hg': int(f.home_goals), 'ag': int(f.away_goals),
                   'hs': [round(v, 2) for v in h] if h else None, 'as': [round(v, 2) for v in a] if a else None,
                   'hl': lineup_row(f.home), 'al': lineup_row(f.away)}
            if f.home_extra_time or f.away_extra_time or f.home_shootout or f.away_shootout:
                rec['x'] = [int(f.home_extra_time or 0), int(f.away_extra_time or 0),
                            int(f.home_shootout or 0), int(f.away_shootout or 0)]
            self.archive.append(rec)
            if h is None or a is None:
                continue
            rows.append((fdate(f), f.tournament_id, h, a, int(f.home_goals), int(f.away_goals)))
        self.n_now = len(rows)
        for r in history:
            if r['k'] in keys or not r.get('hs') or not r.get('as'):
                continue
            rows.append((dt.date.fromisoformat(r['d']), r['c'], tuple(r['hs']), tuple(r['as']), int(r['hg']), int(r['ag'])))
        self.n_history = len(rows) - self.n_now
        self.n = len(rows)
        if len(rows) < 300:
            return self
        rows.sort(key=lambda r: r[0])
        goals = {}
        for _, c, _h, _a, hg, ag in rows:
            g = goals.setdefault(c, [0, 0])
            g[0] += hg + ag
            g[1] += 2
        self.global_rate = sum(g[0] for g in goals.values()) / sum(g[1] for g in goals.values())
        self.comp_rate = {c: (g[0] + 10 * self.global_rate) / (g[1] + 10) for c, g in goals.items()}

        def design(rs):
            X, y = [], []
            for _, c, h, a, hg, ag in rs:
                X.append(self._x(h, a, True, c))
                y.append(hg)
                X.append(self._x(a, h, False, c))
                y.append(ag)
            return np.array(X), np.array(y, dtype=float)

        from sklearn.linear_model import PoissonRegressor
        cut = int(len(rows) * 0.8)
        X, y = design(rows[:cut])
        m = PoissonRegressor(alpha=1e-4, max_iter=500).fit(X, y)
        # held-out check on the most recent matches
        hits, ll, base_ll, n = 0, 0.0, 0.0, 0
        train_out = np.array([(1 if hg > ag else 0, 1 if hg == ag else 0, 1 if hg < ag else 0)
                              for _, _, _, _, hg, ag in rows[:cut]], dtype=float).mean(0)
        for _, c, h, a, hg, ag in rows[cut:]:
            lh = float(np.exp(m.intercept_ + np.dot(m.coef_, self._x(h, a, True, c))))
            la = float(np.exp(m.intercept_ + np.dot(m.coef_, self._x(a, h, False, c))))
            p = probs(lh, la)
            k = 0 if hg > ag else 1 if hg == ag else 2
            pk = [p['w'], p['d'], p['l']]
            hits += int(np.argmax(pk) == k)
            ll -= math.log(max(pk[k], 1e-6))
            base_ll -= math.log(max(train_out[k], 1e-6))
            n += 1
        X, y = design(rows)
        m = PoissonRegressor(alpha=1e-4, max_iter=500).fit(X, y)
        self.coef, self.b0 = m.coef_, float(m.intercept_)
        self.metrics = {'matches': len(rows), 'history': self.n_history, 'test': n, 'accuracy': round(hits / max(n, 1), 3),
                        'logloss': round(ll / max(n, 1), 3), 'baseline_logloss': round(base_ll / max(n, 1), 3),
                        'home_goals': round(float(np.exp(self.b0 + self.coef[2])), 2),
                        'per_ovr': round(float(self.coef[0]), 4)}
        return self

    def predict(self, s, o, home, comp):
        lh = float(np.exp(self.b0 + np.dot(self.coef, self._x(s, o, home, comp))))
        la = float(np.exp(self.b0 + np.dot(self.coef, self._x(o, s, not home, comp))))
        return probs(lh, la)


def lineup_row(apps):
    """[player, position code, started, minutes, rating x10, goals, assists] per appearance."""
    return [[int(a.player_id), int(a.position_code or 0), int(bool(a.started)), int(a.minutes or 0),
             int(a.rating_tenths or 0), int(a.goals or 0), int(a.assists or 0)] for a in apps]


def probs(l1, l2, top=10):
    p1 = np.array([math.exp(-l1) * l1 ** k / math.factorial(k) for k in range(top)])
    p2 = np.array([math.exp(-l2) * l2 ** k / math.factorial(k) for k in range(top)])
    M = np.outer(p1, p2)
    M /= M.sum()
    w, d, l = float(np.tril(M, -1).sum()), float(np.trace(M)), float(np.triu(M, 1).sum())
    flat = np.argsort(-M, axis=None)[:3]
    scores = [{'s': [int(k // top), int(k % top)], 'p': round(float(M.flat[k]) * 100)} for k in flat]
    return {'w': w, 'd': d, 'l': l, 'xg': [round(l1, 2), round(l2, 2)], 'scores': scores}


def lineup_strength(snap, lineup, with_cond=True):
    vals, att, dfn = [], [], []
    for p in lineup:
        v = base_rating(snap, p['i'], p['role']) + (cond_adj(snap, p['i']) if with_cond else 0.0)
        vals.append(v)
        (att if p['role'] in AM_ROLES | FWD_ROLES else dfn if p['role'] in DEF_ROLES | DM_ROLES | {0} else []).append(v)
    xi = float(np.mean(vals)) if vals else 70.0
    return xi, float(np.mean(att)) if att else xi, float(np.mean(dfn)) if dfn else xi


# ------------------------------------------------------------------------------ line-ups
def plan_lineup(snap, plan):
    out = []
    for p in plan['xi']:
        i = snap.row.get(p['id'])
        if i is not None:
            out.append({'i': i, 'id': p['id'], 'role': p['role'], 'x': p['x'], 'y': p['y'], 'slot': p['slot']})
    return out if len(out) == 11 else None


def last_lineup(snap, world, tid):
    """Starters of the club's last match, when it has no readable Game Plan."""
    fs = world.by_team.get(tid, [])
    if not fs:
        return None
    f = fs[-1]
    side = f.home if f.home_team == tid else f.away
    out = []
    for a in side:
        if not a.started:
            continue
        i = snap.row.get(int(a.player_id))
        role = analysis.match_position(snap, i, a.position_code) if i is not None else None
        if role is None:
            continue
        y, x = SPOT[role]
        out.append({'i': i, 'id': int(a.player_id), 'role': role, 'x': x, 'y': y, 'slot': len(out)})
    return out if len(out) >= 10 else None


def player_score(snap, i, role, stats, today):
    s = base_rating(snap, i, role) + cond_adj(snap, i) + form_adj(stats)
    s -= max(0, 100 - int(snap.stamina[i])) * 0.1
    if minutes_since(stats, today - dt.timedelta(days=8)) >= 180:
        s -= 0.5
    return s


def best_xi(snap, slots, candidates, stats, today, prefer=()):
    """Best player for every slot of the formation (Hungarian assignment on the expected match
    rating: OVR at the slot's role with the position grade, condition arrow, recent ratings and
    fatigue). Keepers only in goal."""
    from scipy.optimize import linear_sum_assignment
    cands = list(candidates)
    S = np.full((len(cands), len(slots)), -99.0)
    for a, i in enumerate(cands):
        gk = snap.main_pos[i] == 0
        st = stats.get(int(snap.ids[i]))
        for k, sl in enumerate(slots):
            if (sl['role'] == 0) != gk:
                continue
            S[a, k] = player_score(snap, i, sl['role'], st, today) + (0.4 if int(snap.ids[i]) in prefer else 0.0)
    rows, cols = linear_sum_assignment(-S)
    xi = []
    for a, k in zip(rows, cols):
        if S[a, k] <= -99:
            continue
        i = cands[a]
        xi.append({**slots[k], 'i': i, 'id': int(snap.ids[i]), 'score': round(float(S[a, k]), 1)})
    xi.sort(key=lambda p: p['slot'])
    used = {p['i'] for p in xi}
    rest = [(max(S[a]), cands[a]) for a in range(len(cands)) if cands[a] not in used]
    rest.sort(key=lambda t: -t[0])
    return xi, [i for _, i in rest]


# ------------------------------------------------------------------------- set pieces
def has_skill(snap, i, name):
    k = SKILL_IDX.get(name)
    return k is not None and bool(int(snap.skills[i]) >> k & 1)


def set_piece_score(snap, i, key):
    a = lambda n: float(snap.abilities[i, AB[n]])
    if key == 'fk_long':
        v = 0.45 * a('lofted_pass') + 0.35 * a('place_kicking') + 0.2 * a('curl')
    elif key in ('fk_short', 'fk_second'):
        v = 0.45 * a('place_kicking') + 0.35 * a('curl') + 0.2 * a('kicking_power')
        v += 3 * (has_skill(snap, i, 'Knuckle Shot') or has_skill(snap, i, 'Dipping Shot')) + 2 * has_skill(snap, i, 'Long Range Drive')
    elif key in ('ck_left', 'ck_right'):
        v = 0.5 * a('place_kicking') + 0.3 * a('curl') + 0.2 * a('lofted_pass') + 3 * has_skill(snap, i, 'Pinpoint Crossing')
        inswing = (not snap.left_foot[i]) if key == 'ck_left' else bool(snap.left_foot[i])
        v += 1.0 if inswing else 0.0
    else:
        v = 0.5 * a('place_kicking') + 0.3 * a('finishing') + 0.2 * a('kicking_power') + 5 * has_skill(snap, i, 'Penalty Specialist')
    return v + cond_adj(snap, i) / 1.5


def set_piece_why(snap, i, key):
    a = lambda n: int(snap.abilities[i, AB[n]])
    parts = {'fk_long': [f'Chuyền bổng {a("lofted_pass")}', f'Đá phạt {a("place_kicking")}', f'Độ xoáy {a("curl")}'],
             'fk_short': [f'Đá phạt {a("place_kicking")}', f'Độ xoáy {a("curl")}', f'Lực sút {a("kicking_power")}'],
             'ck_left': [f'Đá phạt {a("place_kicking")}', f'Độ xoáy {a("curl")}'],
             'pk': [f'Đá phạt {a("place_kicking")}', f'Dứt điểm {a("finishing")}']}
    p = parts.get({'fk_second': 'fk_short', 'ck_right': 'ck_left'}.get(key, key), [])
    for sk in ('Knuckle Shot', 'Dipping Shot', 'Long Range Drive', 'Pinpoint Crossing', 'Penalty Specialist'):
        if has_skill(snap, i, sk) and (sk in ('Pinpoint Crossing',) and key.startswith('ck') or
                                         sk == 'Penalty Specialist' and key == 'pk' or
                                         sk in ('Knuckle Shot', 'Dipping Shot', 'Long Range Drive') and key in ('fk_short', 'fk_second')):
            p.append(terms.skill_label(SKILL_IDX[sk]))
    p.append('chân trái' if snap.left_foot[i] else 'chân phải')
    if key.startswith('ck'):
        inswing = (not snap.left_foot[i]) if key == 'ck_left' else bool(snap.left_foot[i])
        p.append('bóng xoáy vào khung thành' if inswing else 'bóng xoáy ra ngoài')
    if snap.cond[i] >= 0:
        p.append(f'phong độ {COND_LETTER[snap.cond[i]]}')
    return ' · '.join(p)


def pick_set_pieces(snap, lineup, current=None):
    """Best taker of each set piece among the players on the pitch, against the current choice."""
    current = current or {}
    cands = [p['i'] for p in lineup if p['role'] != 0]
    on = {int(snap.ids[i]) for i in cands}
    out, chosen = [], {}
    for key, label in gameplan.SET_PIECE_KEYS:
        pool = cands
        if key == 'fk_second' and 'fk_short' in chosen:
            first = chosen['fk_short']
            other = [i for i in cands if i != first and snap.left_foot[i] != snap.left_foot[first]]
            pool = other or [i for i in cands if i != first]
        if not pool:
            continue
        best = max(pool, key=lambda i: set_piece_score(snap, i, key))
        chosen[key] = best
        rec = {'id': int(snap.ids[best]), 'name': snap.names[best], 'score': round(set_piece_score(snap, best, key), 1),
               'why': set_piece_why(snap, best, key)}
        cur = None
        cid = current.get(key)
        ci = snap.row.get(cid) if cid else None
        if ci is not None:
            cur = {'id': cid, 'name': snap.names[ci], 'score': round(set_piece_score(snap, ci, key), 1),
                   'on': cid in on, 'why': set_piece_why(snap, ci, key)}
        change = cur is None or (cur['id'] != rec['id'] and (not cur['on'] or rec['score'] - cur['score'] >= 2))
        note = ''
        if cur and not cur['on']:
            note = f'{cur["name"]} không có tên trong đội hình đề xuất.'
        elif key == 'fk_second':
            note = 'Người đá phạt thứ hai nên thuận chân khác để có thêm góc sút.'
        out.append({'key': key, 'label': label, 'cur': cur, 'rec': rec, 'change': bool(change and cur is not None and cur['id'] != rec['id']),
                    'note': note})
    return out


def aerial_targets(snap, lineup, n=3):
    rows = [p for p in lineup if p['role'] != 0]
    score = lambda p: ab(snap, p['i'], 'heading', 'jump', 'physical_contact') + (int(snap.height[p['i']]) - 180) * 0.5
    return [{'id': p['id'], 'name': snap.names[p['i']], 'height': int(snap.height[p['i']]),
             'heading': int(snap.abilities[p['i'], AB['heading']]), 'jump': int(snap.abilities[p['i'], AB['jump']])}
            for p in sorted(rows, key=score, reverse=True)[:n]]


# ---------------------------------------------------------------------------- report
class Matchday:
    def __init__(self, snap, extra, season_matches, model, derbies=None):
        self.s = snap
        self.extra = extra
        self.model = model
        self.derbies = derbies or set()
        self.world = World(snap)
        self.today = snap.date
        self.me = snap.team_id
        self.my_stats = self.world.player_stats(self.me)
        self.plan = snap.gameplans.get(self.me)
        self.season_matches = season_matches

    # ---- helpers
    def pl(self, p, stats=None, extra_fields=None):
        s = self.s
        i = p['i']
        st = stats.get(p['id']) if stats is not None else None
        c = int(s.cond[i])
        row = {'id': p['id'], 'name': s.names[i], 'role': POS[p['role']], 'x': p['x'], 'y': p['y'],
               'ovr': int(round(base_rating(s, i, p['role']))), 'ovr_main': int(s.ovr[i]),
               'cond': c, 'arrow': COND_LETTER[c] if c >= 0 else '', 'inj': int(s.unavail[i]),
               'stamina': int(s.stamina[i]), 'grade': 'CBA'[min(int(s.grades[i, p['role']]), 2)]}
        if st:
            row.update({'apps': st['apps'], 'g': st['g'], 'a': st['a'],
                        'last': st['r'][-5:], 'avg': round(float(np.mean(st['r'])), 2) if st['r'] else None,
                        'last10': (st.get('r10') or [])[-5:]})
        if extra_fields:
            row.update(extra_fields)
        return row

    def upcoming(self, n=3):
        s = self.s
        fs = [f for f in s.my_fixtures if not f.flags & PLAYED and f.home_team and f.away_team
              and fdate(f) >= self.today - dt.timedelta(days=1)]
        fs.sort(key=lambda f: (f.year, f.month, f.day, f.kickoff_hour or 0))
        return fs[:n]

    def squad_rows(self):
        s = self.s
        return [s.row[p] for p, x in self.extra.items() if p in s.row and not x.get('youth')]

    def my_best(self):
        s = self.s
        if self.plan and plan_lineup(s, self.plan):
            slots = [{'slot': p['slot'], 'role': p['role'], 'x': p['x'], 'y': p['y']} for p in self.plan['xi']]
            current = plan_lineup(s, self.plan)
        else:
            current = last_lineup(s, self.world, self.me)
            slots = [{'slot': p['slot'], 'role': p['role'], 'x': p['x'], 'y': p['y']} for p in (current or [])]
            if not slots:
                roles = [0, 1, 1, 3, 2, 4, 5, 5, 10, 9, 12]
                slots = [{'slot': k, 'role': r, 'x': SPOT[r][1], 'y': SPOT[r][0]} for k, r in enumerate(roles)]
        avail = [i for i in self.squad_rows() if s.unavail[i] <= 0 and not self.extra.get(int(s.ids[i]), {}).get('inj')]
        prefer = {p['id'] for p in current} if current else set()
        xi, rest = best_xi(s, slots, avail, self.my_stats, self.today, prefer)
        return current, xi, rest

    def changes(self, current, xi):
        """Who comes in for whom (paired by slot, then role), and who only changes position."""
        s = self.s
        out = []
        if not current:
            return out
        cur = {p['id']: p for p in current}
        rec = {p['id']: p for p in xi}
        outs = [p for p in current if p['id'] not in rec]
        line = lambda r: 0 if r == 0 else 1 if r in DEF_ROLES else 3 if r in FWD_ROLES else 2
        for p in xi:
            if p['id'] in cur and cur[p['id']]['role'] != p['role']:
                c, i = cur[p['id']], p['i']
                out.append({'type': 'move', 'id': p['id'], 'name': s.names[i], 'from': POS[c['role']], 'role': POS[p['role']],
                            'why': f'OVR ở {POS[p["role"]]} {int(round(base_rating(s, i, p["role"])))}, ở {POS[c["role"]]} '
                                   f'{int(round(base_rating(s, i, c["role"])))}'})
        ins = [p for p in xi if p['id'] not in cur]
        pairs = []
        for p in list(ins):                       # first: the player who held that very slot left the XI
            c = next((o for o in outs if o['slot'] == p['slot']), None)
            if c:
                pairs.append((p, c))
                outs.remove(c)
                ins.remove(p)
        for p in ins:                             # then: same role, same line, anyone
            if not outs:
                break
            c = min(outs, key=lambda o: (o['role'] != p['role'], line(o['role']) != line(p['role'])))
            outs.remove(c)
            pairs.append((p, c))
        for p, c in sorted(pairs, key=lambda pc: pc[0]['slot']):
            why = []
            ci, pi = c['i'], p['i']
            if s.unavail[ci] > 0:
                why.append(f'{s.names[ci]} đang chấn thương ({int(s.unavail[ci])} ngày)')
            if s.cond[pi] >= 0 and s.cond[ci] >= 0 and s.cond[pi] != s.cond[ci]:
                why.append(f'phong độ {COND_LETTER[s.cond[pi]]} so với {COND_LETTER[s.cond[ci]]}')
            ro = int(round(base_rating(s, pi, p['role']))), int(round(base_rating(s, ci, c['role'])))
            if c['role'] == p['role'] and ro[0] != ro[1]:
                why.append(f'OVR ở vị trí {POS[p["role"]]}: {ro[0]} so với {ro[1]}')
            elif c['role'] != p['role']:
                why.append(f'OVR {ro[0]} ở {POS[p["role"]]}, {s.names[ci]} {ro[1]} ở {POS[c["role"]]}')
            fa, fb = form_adj(self.my_stats.get(p['id'])), form_adj(self.my_stats.get(c['id']))
            if abs(fa - fb) >= 0.8:
                ra, rb = (self.my_stats.get(p['id']) or {}).get('r', []), (self.my_stats.get(c['id']) or {}).get('r', [])
                if ra and rb:
                    why.append(f'điểm 3 trận gần nhất {np.mean(ra[-3:]):.1f} so với {np.mean(rb[-3:]):.1f}')
            if s.stamina[ci] < 100 and s.stamina[ci] < s.stamina[pi]:
                why.append(f'{s.names[ci]} thể lực {int(s.stamina[ci])}%')
            out.append({'type': 'swap', 'slot': p['slot'], 'role': POS[p['role']], 'in': p['id'], 'in_name': s.names[pi],
                        'out': c['id'], 'out_name': s.names[ci], 'why': '; '.join(why) or 'tổng điểm đội hình cao hơn'})
        out.sort(key=lambda c: c['type'] != 'swap')
        return out

    def opponent_lineup(self, tid):
        s = self.s
        plan = s.gameplans.get(tid)
        lu = plan_lineup(s, plan) if plan else None
        source = 'gameplan'
        if not lu:
            lu = last_lineup(s, self.world, tid)
            source = 'last_match'
        if not lu:
            return None, None, None
        # the game will replace injured players: take the best fit from their bench
        bench = [s.row[p] for p in (plan or {}).get('bench', []) if p in s.row]
        out = []
        used = set()
        for p in lu:
            if s.unavail[p['i']] > 0 and bench:
                cand = [i for i in bench if i not in used and s.unavail[i] <= 0 and (s.main_pos[i] == 0) == (p['role'] == 0)]
                if cand:
                    j = max(cand, key=lambda i: base_rating(s, i, p['role']))
                    used.add(j)
                    out.append({**p, 'i': j, 'id': int(s.ids[j]), 'replaces': p['id']})
                    continue
            out.append(p)
        return out, plan, source

    # ---- analysis
    def unit(self, lineup, roles, *abil):
        xs = [ab(self.s, p['i'], *abil) for p in lineup if p['role'] in roles]
        return float(np.mean(xs)) if xs else None

    def side_players(self, lineup, side, roles):
        out = []
        for p in lineup:
            if p['role'] not in roles:
                continue
            if side == 'L' and (p['role'] in LEFT_ROLES or p['x'] < 35):
                out.append(p)
            elif side == 'R' and (p['role'] in RIGHT_ROLES or p['x'] > 69):
                out.append(p)
        return out

    def threats(self, lineup, stats):
        s = self.s
        rows = []
        for p in lineup:
            if p['role'] == 0 or p['role'] in DEF_ROLES:
                continue
            st = stats.get(p['id']) or {}
            apps = max(st.get('apps', 0), 1)
            ga = (st.get('g', 0) + 0.6 * st.get('a', 0)) / apps
            score = base_rating(s, p['i'], p['role']) + cond_adj(s, p['i']) + 4 * min(ga, 1.2)
            keys = [AB[k] for k in THREAT_ABILITIES]
            top = sorted(keys, key=lambda k: -s.abilities[p['i'], k])[:2]
            rows.append((score, {**self.pl(p, stats), 'why': [f'{terms.ABILITY_VI[terms.ABILITIES[k]]} {int(s.abilities[p["i"], k])}' for k in top]}))
        rows.sort(key=lambda t: -t[0])
        return [r for _, r in rows[:3]]

    def matchups(self, mine, theirs):
        """Their wide and central attackers against the defenders facing them."""
        s = self.s
        out = []
        pairs = [('Cánh trái của họ', self.side_players(theirs, 'L', MID_ROLES | FWD_ROLES | AM_ROLES),
                  self.side_players(mine, 'R', DEF_ROLES)),
                 ('Cánh phải của họ', self.side_players(theirs, 'R', MID_ROLES | FWD_ROLES | AM_ROLES),
                  self.side_players(mine, 'L', DEF_ROLES)),
                 ('Trung lộ', [p for p in theirs if p['role'] in (11, 12)], [p for p in mine if p['role'] == 1])]
        for label, att, dfn in pairs:
            if not att or not dfn:
                continue
            a = max(att, key=lambda p: ab(s, p['i'], 'speed', 'acceleration') + ab(s, p['i'], 'dribbling'))
            d = min(dfn, key=lambda p: ab(s, p['i'], 'speed', 'acceleration'))
            pace = ab(s, a['i'], 'speed', 'acceleration') - ab(s, d['i'], 'speed', 'acceleration')
            skill = ab(s, a['i'], 'dribbling') - ab(s, d['i'], 'defensive_awareness')
            aerial = ab(s, a['i'], 'heading', 'jump') - ab(s, d['i'], 'heading', 'jump')
            danger = pace + 0.5 * skill
            if label == 'Trung lộ':
                danger = max(danger, aerial)
            level = 'cao' if danger >= 8 else 'vừa' if danger >= 2 else 'thấp'
            notes = [f'tốc độ {int(ab(s, a["i"], "speed", "acceleration"))} vs {int(ab(s, d["i"], "speed", "acceleration"))}',
                     f'rê bóng {int(ab(s, a["i"], "dribbling"))} vs tư duy DEF {int(ab(s, d["i"], "defensive_awareness"))}']
            if label == 'Trung lộ':
                notes.append(f'không chiến {int(ab(s, a["i"], "heading", "jump"))} vs {int(ab(s, d["i"], "heading", "jump"))}')
            tip = ''
            if level == 'cao':
                if label == 'Trung lộ' and aerial >= 8:
                    tip = 'Hạn chế để họ tạt bóng: dồn ép hai cánh, trung vệ bám sát khi bóng bổng.'
                elif pace >= 6:
                    tip = f'Không để {s.names[d["i"]]} đối mặt 1-1 khi có khoảng trống sau lưng: hạ hàng thủ hoặc cho tiền vệ lùi hỗ trợ.'
                else:
                    tip = f'Cho thêm người bọc lót {s.names[d["i"]]}; cân nhắc Kèm người chặt chẽ.'
            out.append({'label': label, 'att': self.pl(a), 'def': self.pl(d), 'level': level,
                        'danger': round(danger, 1), 'notes': notes, 'tip': tip})
        return out

    def tactics(self, mine, theirs, their_plan, pred):
        """Team instructions for this opponent, starting from what the user runs now."""
        s = self.s
        cur = dict((self.plan or {}).get('toggles') or {})
        num = dict((self.plan or {}).get('numbers') or {})
        tt = (their_plan or {}).get('toggles') or {}
        tn = (their_plan or {}).get('numbers') or {}
        U = self.unit
        our_att_pace = U(mine, FWD_ROLES | {6, 7}, 'speed', 'acceleration')
        their_def_pace = U(theirs, {1}, 'speed', 'acceleration')
        their_att_pace = U(theirs, FWD_ROLES | {6, 7}, 'speed', 'acceleration')
        our_cb_pace = U(mine, {1}, 'speed', 'acceleration')
        our_mid_pass = U(mine, DM_ROLES | MID_ROLES | AM_ROLES, 'low_pass')
        their_build = U(theirs, {0, 1} | DM_ROLES, 'low_pass', 'ball_control')
        our_stamina = U(mine, DEF_ROLES | DM_ROLES | MID_ROLES | AM_ROLES | FWD_ROLES, 'stamina')
        our_wide = U(mine, {6, 7, 9, 10}, 'speed', 'dribbling')
        their_fb = U(theirs, {2, 3}, 'speed', 'defensive_awareness')
        our_centre = U(mine, {8, 11, 12}, 'finishing', 'offensive_awareness', 'physical_contact')
        their_cb = U(theirs, {1}, 'defensive_awareness', 'physical_contact', 'heading')
        our_air = U(mine, {11, 12}, 'heading', 'jump')
        their_air = U(theirs, {1}, 'heading', 'jump')
        f1 = lambda v: '—' if v is None else str(int(round(v)))
        their_press = tt.get('defensive_style') == 0 and tt.get('pressuring') == 0
        rec, why = {}, {}

        # attacking style
        perf = (s.club or {}).get('club_performance') or {}
        types = perf.get('types_scored') or {}
        through = f' {types.get("through_ball", 0)}/{sum(types.values())} bàn mùa này của bạn đến từ chọc khe.' if types.get('through_ball') else ''
        space = (their_def_pace and our_att_pace and our_att_pace - their_def_pace >= 4
                 and (tn.get('defensive_line', 5) >= 7 or tt.get('defensive_style') == 0))
        if space and pred['w'] < 0.55:
            rec['attacking_style'] = 0
            why['attacking_style'] = f'Họ dâng hàng thủ (mức {tn.get("defensive_line", "?")}) mà trung vệ chậm hơn hàng công của bạn (tốc độ {f1(their_def_pace)} so với {f1(our_att_pace)}): khoảng trống sau lưng là cơ hội.{through}'
        elif space and cur.get('attacking_style') == 1:
            why['attacking_style'] = (f'Bạn là cửa trên (AI: thắng {round(pred["w"] * 100)}%), giữ Kiểm soát thế trận nhưng tận dụng chọc khe: '
                                      f'hàng thủ họ dâng cao (mức {tn.get("defensive_line", "?")}) và chậm hơn hàng công của bạn ({f1(their_def_pace)} so với {f1(our_att_pace)}).{through}')
        elif pred['w'] >= 0.55 and (tt.get('defensive_style') == 1 or tn.get('defensive_line', 5) <= 4):
            rec['attacking_style'] = 1
            why['attacking_style'] = 'Bạn mạnh hơn và họ lùi sâu phòng ngự: cầm bóng, kéo giãn khối phòng ngự.'
        elif pred['l'] >= 0.45:
            rec['attacking_style'] = 0
            why['attacking_style'] = f'Đối thủ nhỉnh hơn (AI: thua {round(pred["l"] * 100)}%): chơi phản công an toàn hơn.'
        # build up
        if their_press and our_mid_pass is not None and our_mid_pass < 78:
            rec['build_up'] = 0
            why['build_up'] = f'Họ pressing tầm cao (Áp sát từ xa + Công kích) trong khi tuyến giữa của bạn chuyền sệt {f1(our_mid_pass)}: đưa bóng dài vượt tuyến pressing.'
        elif our_air and their_air and our_air - their_air >= 8 and rec.get('attacking_style', cur.get('attacking_style')) == 0:
            rec['build_up'] = 0
            why['build_up'] = f'Tiền đạo của bạn không chiến {f1(our_air)} so với trung vệ họ {f1(their_air)}: bóng dài có điểm đến.'
        elif our_mid_pass is not None and our_mid_pass >= 80:
            rec['build_up'] = 1
            why['build_up'] = f'Tuyến giữa chuyền sệt tốt ({f1(our_mid_pass)}): giữ Chuyền ngắn.'
        # attacking area
        if our_wide and their_fb and our_centre and their_cb:
            wide_edge, centre_edge = our_wide - their_fb, our_centre - their_cb
            if wide_edge - centre_edge >= 4:
                rec['attacking_area'] = 0
                why['attacking_area'] = f'Cánh là điểm yếu của họ: cầu thủ chạy cánh của bạn {f1(our_wide)} so với hậu vệ biên họ {f1(their_fb)} (tốc độ/rê bóng vs tốc độ/phòng ngự).'
            elif centre_edge - wide_edge >= 4:
                rec['attacking_area'] = 1
                why['attacking_area'] = f'Trung lộ có lợi hơn: tiền đạo/hộ công của bạn {f1(our_centre)} so với trung vệ họ {f1(their_cb)}.'
        # support range follows the style
        style = rec.get('attacking_style', cur.get('attacking_style'))
        sr = num.get('support_range')
        if sr:
            if style == 0 and sr < 6:
                rec['support_range'] = 7
                why['support_range'] = 'Phản công cần cầu thủ dàn rộng hơn để có đường chạy.'
            elif style == 1 and rec.get('build_up', cur.get('build_up')) == 1 and sr >= 8:
                rec['support_range'] = 6
                why['support_range'] = 'Chuyền ngắn cần cầu thủ đứng gần nhau hơn để phối hợp.'
        # defensive style
        if their_build is not None and their_build <= 70 and (our_stamina or 0) >= 75:
            rec['defensive_style'] = 0
            why['defensive_style'] = f'Hậu vệ và tiền vệ phòng ngự của họ xử lý bóng kém (chuyền/kiểm soát {f1(their_build)}), cầu thủ của bạn đủ thể lực ({f1(our_stamina)}): pressing để cướp bóng cao.'
        elif their_att_pace and our_cb_pace and their_att_pace - our_cb_pace >= 6:
            rec['defensive_style'] = 1
            why['defensive_style'] = f'Hàng công của họ nhanh hơn trung vệ bạn ({f1(their_att_pace)} so với {f1(our_cb_pace)}): lùi về tạo khối phòng ngự, không để lộ khoảng trống.'
        elif pred['l'] >= 0.5:
            rec['defensive_style'] = 1
            why['defensive_style'] = 'Đối thủ mạnh hơn: ưu tiên chắc chắn phía sau.'
        # containment area mirrors where they attack
        if 'attacking_area' in tt:
            want = 1 if tt['attacking_area'] == 0 else 0
            rec['containment_area'] = want
            why['containment_area'] = ('Họ tấn công rộng (Tấn công khu vực: Rộng): phòng ngự khắp sân.' if want == 1
                                       else 'Họ tấn công trung lộ: tập trung phòng ngự trung lộ.')
        # pressuring
        best_drib = max(theirs, key=lambda p: s.abilities[p['i'], AB['dribbling']]) if theirs else None
        if best_drib is not None and s.abilities[best_drib['i'], AB['dribbling']] >= 88:
            rec['pressuring'] = 1
            why['pressuring'] = f'{s.names[best_drib["i"]]} rê bóng {int(s.abilities[best_drib["i"], AB["dribbling"]])}: lao vào tranh bóng dễ bị qua người, nên Bảo toàn.'
        elif rec.get('defensive_style', cur.get('defensive_style')) == 0 and (our_stamina or 0) >= 72:
            rec['pressuring'] = 0
            why['pressuring'] = 'Đi cùng pressing: áp sát ngay khi mất bóng.'
        # defensive line
        dl = num.get('defensive_line')
        if dl and their_att_pace and our_cb_pace:
            if their_att_pace - our_cb_pace >= 6 and dl > 5:
                rec['defensive_line'] = 5
                why['defensive_line'] = f'Tiền đạo họ nhanh hơn trung vệ bạn {f1(their_att_pace - our_cb_pace)} điểm tốc độ: hạ hàng thủ để không bị chọc khe.'
            elif our_cb_pace - their_att_pace >= 4 and dl < 7 and rec.get('defensive_style', cur.get('defensive_style')) == 0:
                rec['defensive_line'] = 7
                why['defensive_line'] = 'Trung vệ của bạn nhanh hơn hàng công của họ: dâng cao để ép sân.'
        cp = num.get('compactness')
        if cp and tt.get('attacking_area') == 1 and cp < 7:
            rec['compactness'] = 7
            why['compactness'] = 'Họ đánh trung lộ: khép khoảng cách giữa các cầu thủ.'

        rows = []
        for k, vi, en, o0, o1 in gameplan.TOGGLES:
            c = cur.get(k)
            r = rec.get(k, c)
            rows.append({'key': k, 'label': vi, 'en': en, 'now': None if c is None else (o0, o1)[c][0],
                         'rec': None if r is None else (o0, o1)[r][0], 'rec_en': None if r is None else (o0, o1)[r][1],
                         'change': r is not None and c is not None and r != c, 'why': why.get(k, '')})
        for k, vi, en in gameplan.NUMBERS:
            c = num.get(k)
            r = rec.get(k, c)
            rows.append({'key': k, 'label': vi, 'en': en, 'now': c, 'rec': r, 'change': r is not None and c is not None and r != c,
                         'why': why.get(k, '')})

        # advanced instructions
        atk, dfn = [], []
        final = {k: rec.get(k, cur.get(k)) for k in ('attacking_style', 'build_up', 'attacking_area', 'defensive_style')}
        wingers = [p for p in mine if p['role'] in (9, 10)]
        fbs = [p for p in mine if p['role'] in (2, 3)]
        if final['attacking_style'] == 1 and final['build_up'] == 1 and (our_mid_pass or 0) >= 82:
            atk.append((6, f'Tuyến giữa chuyền sệt {f1(our_mid_pass)}: phối hợp ngắn liên tục.'))
        if len(wingers) == 2 and all(s.abilities[p['i'], AB['speed']] >= 84 and s.abilities[p['i'], AB['dribbling']] >= 80 for p in wingers):
            atk.append((5, 'Hai tiền đạo cánh đều nhanh và rê bóng tốt: đổi cánh làm rối hậu vệ biên.'))
        if fbs and np.mean([ab(s, p['i'], 'speed', 'offensive_awareness', 'stamina') for p in fbs]) >= 76 and (their_fb or 99) < 75:
            atk.append((4, 'Hậu vệ biên của bạn đủ tốc độ và thể lực để dâng cao.'))
        if our_air and their_air and our_air - their_air >= 6:
            atk.append((7, f'Không chiến: tiền đạo {f1(our_air)} so với trung vệ họ {f1(their_air)}.'))
        if final['attacking_area'] == 0 and not atk:
            atk.append((1, 'Tấn công rộng: cầu thủ chạy cánh bám sát đường biên để kéo giãn hàng thủ.'))
        if final['defensive_style'] == 0 and (our_stamina or 0) >= 75:
            dfn.append((13, f'Thể lực đội bạn {f1(our_stamina)}: đủ để pressing ngay khi mất bóng.'))
        if their_att_pace and our_cb_pace and their_att_pace - our_cb_pace >= 8:
            dfn.append((12, 'Hàng công họ quá nhanh so với trung vệ bạn: lùi sâu để không bị chọc khe.'))
        if final['attacking_style'] == 0:
            dfn.append((15, 'Phản công: giữ một tiền đạo trên cao làm điểm nhận bóng.'))
        if pred['l'] >= 0.55:
            dfn.append((11, 'Đối thủ mạnh hơn nhiều: dồn người về vòng cấm.'))
        have = set(((self.plan or {}).get('instructions') or {}).values())
        instr = [{'id': k, 'text': gameplan.instruction_label(k), 'why': w, 'have': k in have, 'kind': 'Tấn công' if k <= 10 else 'Phòng ngự'}
                 for k, w in atk[:2] + dfn[:2]]
        remove = []
        if 11 in have and pred['w'] >= 0.45:
            remove.append({'id': 11, 'text': gameplan.instruction_label(11),
                           'why': f'Dồn người về vòng cấm hợp khi phải chống đỡ, trong khi AI dự đoán bạn thắng {round(pred["w"] * 100)}%.'})
        if 12 in have and our_cb_pace and their_att_pace and our_cb_pace >= their_att_pace:
            remove.append({'id': 12, 'text': gameplan.instruction_label(12),
                           'why': 'Trung vệ của bạn không chậm hơn hàng công của họ: không cần lùi sâu.'})
        if 5 in have and len(wingers) == 2 and not all(s.abilities[p['i'], AB['speed']] >= 80 for p in wingers):
            slow = min(wingers, key=lambda p: s.abilities[p['i'], AB['speed']])
            remove.append({'id': 5, 'text': gameplan.instruction_label(5),
                           'why': f'{s.names[slow["i"]]} (tốc độ {int(s.abilities[slow["i"], AB["speed"]])}) không đủ nhanh để đổi cánh liên tục.'})
        current_instr = [{'id': v, 'text': gameplan.instruction_label(v)} for v in have]
        return {'rows': rows, 'instructions': instr, 'remove': remove, 'current_instructions': current_instr,
                'changes': sum(1 for r in rows if r['change']) + sum(1 for x in instr if not x['have']) + len(remove)}

    def weaknesses(self, theirs, their_stats):
        s = self.s
        out = []
        cbs = [p for p in theirs if p['role'] == 1]
        if cbs:
            slow = min(cbs, key=lambda p: ab(s, p['i'], 'speed', 'acceleration'))
            v = ab(s, slow['i'], 'speed', 'acceleration')
            if v < 75:
                out.append(f'Trung vệ {s.names[slow["i"]]} chậm (tốc độ/bứt tốc {int(v)}): chọc khe vào khoảng trống sau lưng anh ta.')
            low = min(cbs, key=lambda p: ab(s, p['i'], 'heading', 'jump'))
            v = ab(s, low['i'], 'heading', 'jump')
            if v < 72:
                out.append(f'{s.names[low["i"]]} không chiến yếu (đánh đầu/bật nhảy {int(v)}): tạt bóng và phạt góc về phía anh ta.')
        for p in theirs:
            if p['role'] in (2, 3) and s.abilities[p['i'], AB['defensive_awareness']] < 68:
                out.append(f'Hậu vệ biên {s.names[p["i"]]} phòng ngự kém (tư duy DEF {int(s.abilities[p["i"], AB["defensive_awareness"]])}): tấn công vào cánh {"trái" if p["role"] == 2 else "phải"} của họ.')
        bad = [p for p in theirs if 0 <= s.cond[p['i']] <= 1]
        if bad:
            out.append('Đang sa sút phong độ (mũi tên xuống): ' + ', '.join(f'{s.names[p["i"]]} ({COND_LETTER[s.cond[p["i"]]]})' for p in bad) + '.')
        gk = next((p for p in theirs if p['role'] == 0), None)
        if gk and ab(s, gk['i'], 'gk_reflexes', 'gk_reach') < 75:
            out.append(f'Thủ môn {s.names[gk["i"]]} phản xạ/tầm với {int(ab(s, gk["i"], "gk_reflexes", "gk_reach"))}: sút xa và sút sớm.')
        return out[:6]

    # ---- the whole page
    def build(self):
        s = self.s
        current, best, rest = self.my_best()
        stats = self.my_stats
        cur_rows = [self.pl(p, stats) for p in current] if current else []
        best_rows = [self.pl(p, stats) for p in best]
        bench = [self.pl({'i': i, 'id': int(s.ids[i]), 'role': int(s.main_pos[i]), 'x': 0, 'y': 0}, stats) for i in rest[:12]]
        changes = self.changes(current, best)
        fixtures = []
        for f in self.upcoming():
            opp = f.away_team if f.home_team == self.me else f.home_team
            home = f.home_team == self.me
            theirs, their_plan, source = self.opponent_lineup(opp)
            their_stats = self.world.player_stats(opp)
            rep = {'key': fkey(f), 'date': fdate(f).isoformat(), 'hour': f.kickoff_hour, 'days': (fdate(f) - self.today).days,
                   'comp': f.tournament_id, 'comp_name': s.comp_name(f.tournament_id), 'home': f.home_team, 'away': f.away_team,
                   'home_name': s.club_name(f.home_team), 'away_name': s.club_name(f.away_team), 'venue': 'home' if home else 'away',
                   'opp': opp, 'opp_name': s.club_name(opp), 'opp_results': self.world.results(opp),
                   'my_results': self.world.results(self.me, 5)}
            reg = s.regions.get(f.tournament_id)
            if reg and reg.table:
                for t in reg.table:
                    if t.team_id in (opp, self.me):
                        rep['pos_opp' if t.team_id == opp else 'pos_me'] = {'pos': t.position, 'pts': t.points, 'p': t.played,
                                                                            'gf': t.goals_for, 'ga': t.goals_against}
            if theirs:
                opp_str = lineup_strength(s, theirs)
                pred_best = self.model.predict(lineup_strength(s, best), opp_str, home, f.tournament_id)
                pred_cur = self.model.predict(lineup_strength(s, current), opp_str, home, f.tournament_id) if current else None
                rep.update({
                    'opp_xi': [self.pl(p, their_stats, {'replaces': s.player_name(p['replaces']) if p.get('replaces') else None}) for p in theirs],
                    'opp_source': source, 'opp_manager': (their_plan or {}).get('manager', ''),
                    'opp_shape': (their_plan or {}).get('shape', ''), 'opp_plan': gameplan.describe(their_plan),
                    'pred': _pct(pred_best), 'pred_current': _pct(pred_cur) if pred_cur else None,
                    'threats': self.threats(theirs, their_stats), 'weak': self.weaknesses(theirs, their_stats),
                    'matchups': self.matchups(best, theirs), 'tactics': self.tactics(best, theirs, their_plan, pred_best),
                    'opp_ovr': round(opp_str[0], 1), 'my_ovr': round(lineup_strength(s, best)[0], 1),
                    'opp_phases': self.phases(their_plan), 'opp_set_pieces': self.their_takers(their_plan)})
            rep['derby'] = frozenset((f.home_team, f.away_team)) in self.derbies
            fixtures.append(rep)
        form = []
        for i in self.squad_rows():
            pid = int(s.ids[i])
            st = stats.get(pid) or {}
            in_plan = 'start' if current and pid in {p['id'] for p in current} else \
                'bench' if self.plan and pid in self.plan.get('bench', []) else 'out'
            form.append({'id': pid, 'name': s.names[i], 'pos': POS[s.main_pos[i]], 'ovr': int(s.ovr[i]),
                         'cond': int(s.cond[i]), 'arrow': COND_LETTER[s.cond[i]] if s.cond[i] >= 0 else '',
                         'stamina': int(s.stamina[i]), 'inj': int(s.unavail[i]), 'last': st.get('r', [])[-5:],
                         'avg': round(float(np.mean(st['r'])), 2) if st.get('r') else None,
                         'last10': (st.get('r10') or [])[-5:],
                         'avg10': round(float(np.mean(st['r10'])), 2) if st.get('r10') else None,
                         'min14': minutes_since(st, self.today - dt.timedelta(days=14)), 'plan': in_plan,
                         'rec': pid in {p['id'] for p in best}})
        form.sort(key=lambda r: (-r['cond'], -r['ovr']))
        perf = (s.club or {}).get('club_performance') or {}
        style = {'areas': perf.get('attacking_areas_pct'), 'types_scored': perf.get('types_scored'),
                 'types_conceded': perf.get('types_conceded'), 'matches': perf.get('matches'),
                 'times_scored': perf.get('times_scored'), 'times_conceded': perf.get('times_conceded'),
                 'rankings': self.rankings(perf.get('rankings') or {})}
        style['periods_note'] = self.periods_note(style, form, rest)
        plan_bench = [self.pl({'i': s.row[p], 'id': p, 'role': int(s.main_pos[s.row[p]]), 'x': 0, 'y': 0}, stats)
                      for p in (self.plan or {}).get('bench', []) if p in s.row]
        return {'plan': gameplan.describe(self.plan), 'current': cur_rows, 'best': best_rows, 'bench': bench,
                'plan_bench': plan_bench, 'captain': (self.plan or {}).get('captain'),
                'changes': changes, 'fixtures': fixtures, 'form': form,
                'model': self.model.metrics, 'model_n': self.model.n, 'style': style,
                'set_pieces': pick_set_pieces(s, best, (self.plan or {}).get('set_pieces')),
                'aerial': aerial_targets(s, best), 'plan_phases': self.phases(self.plan),
                'squad_comp': (s.club or {}).get('squad_composition')}

    def phases(self, plan):
        if not plan:
            return None
        ids = [p['id'] for p in plan['xi']]
        out = gameplan.phase_summary(plan, ids)
        if out:
            for ph in out['phases']:
                for mv in ph['moves']:
                    mv['name'] = self.s.player_name(mv['id']) if mv.get('id') else ''
        return out

    def their_takers(self, plan):
        s = self.s
        out = []
        for key, label in gameplan.SET_PIECE_KEYS:
            pid = ((plan or {}).get('set_pieces') or {}).get(key)
            i = s.row.get(pid) if pid else None
            if i is None or key in ('ck_right', 'fk_second'):
                continue
            out.append({'key': key, 'label': label, 'id': pid, 'name': s.names[i], 'why': set_piece_why(s, i, key)})
        return out

    def rankings(self, rk):
        s = self.s
        vi = {'dribbling': 'Rê bóng thành công', 'passing': 'Chuyền thành công', 'received': 'Nhận bóng',
              'shooting': 'Sút', 'aerial': 'Không chiến', 'tackles': 'Tắc bóng'}
        out = []
        for k, rows in rk.items():
            top = rows[0] if rows else None
            if top and top.get('player_id'):
                out.append({'key': k, 'label': vi.get(k, k), 'id': int(top['player_id']), 'name': s.player_name(top['player_id']),
                            'value': top.get('successful'), 'rate': top.get('rate')})
        return out

    def periods_note(self, style, form, rest):
        tc, ts = style.get('times_conceded') or [], style.get('times_scored') or []
        if len(tc) < 6 or sum(tc) < 5:
            return ''
        k = int(np.argmax(tc[:6]))
        share = tc[k] / max(sum(tc), 1)
        note = f'Bạn thủng lưới nhiều nhất ở phút {PERIODS[k]} ({tc[k]}/{sum(tc)} bàn).'
        if k >= 4 and share >= 0.25:
            fresh = [r['name'] for r in form if r['plan'] != 'start' and r['cond'] >= 3 and not r['inj']][:3]
            note += ' Nên thay người sớm hơn (khoảng phút 60–65) để giữ sức cuối trận' + (f', ưu tiên dự bị đang có phong độ tốt: {", ".join(fresh)}.' if fresh else '.')
        elif k <= 1 and share >= 0.25:
            note += ' Đội hay nhập cuộc chậm: cân nhắc Phong cách phòng thủ chắc chắn hơn trong 15–30 phút đầu.'
        if len(ts) >= 6 and sum(ts):
            j = int(np.argmax(ts[:6]))
            note += f' Ghi bàn nhiều nhất ở phút {PERIODS[j]} ({ts[j]}/{sum(ts)} bàn).'
        return note


def _pct(p):
    return {'w': round(p['w'] * 100), 'd': round(p['d'] * 100), 'l': round(p['l'] * 100), 'xg': p['xg'], 'scores': p['scores']}

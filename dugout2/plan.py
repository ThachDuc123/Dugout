"""The summer transfer plan: who leaves for sure, who to sell, what the squad needs for next
season and whom to buy, within the budget.

Everything comes from the save (squad, contracts, wages, minutes, every player in the world, the
AI's projections) plus, when available, what only the running game knows: the budget and the
market values (live, or the last game day Dugout recorded). Without real market values the fees
are estimates from OVR, age, potential and contract; once values have been recorded, the estimate
is fitted to the game's own values.
"""
import datetime as dt
import glob
import json
import math
import os

import numpy as np

from . import terms

POS = terms.POSITIONS
# (key, label, positions)
GROUPS = [('GK', 'Thủ môn', ('GK',)), ('CB', 'Trung vệ', ('CB',)), ('LB', 'Hậu vệ trái', ('LB',)),
          ('RB', 'Hậu vệ phải', ('RB',)), ('DM', 'Tiền vệ phòng ngự', ('DMF',)), ('CM', 'Tiền vệ trung tâm', ('CMF',)),
          ('AM', 'Tiền vệ tấn công / hộ công', ('AMF', 'SS')),
          ('W', 'Cánh (tiền vệ / tiền đạo cánh)', ('LMF', 'RMF', 'LWF', 'RWF')), ('ST', 'Tiền đạo cắm', ('CF',))]
GROUP_OF = {p: k for k, _l, ps in GROUPS for p in ps}
DEFAULT_XI = {'GK': 1, 'CB': 2, 'LB': 1, 'RB': 1, 'DM': 1, 'CM': 2, 'AM': 0, 'W': 2, 'ST': 1}     # 4-3-3


def _season_end(date):
    """Contracts in PES run to 31 August (or 31 January): the ones ending by the end of the coming
    summer window end with this season."""
    return dt.date(date.year if date.month <= 8 else date.year + 1, 8, 31)


def _contract_date(v):
    v = int(v)
    if v <= 0:
        return None
    try:
        return dt.date(v // 10000, max(1, v // 100 % 100), max(1, v % 100))
    except ValueError:
        return dt.date(v // 10000, 6, 30)


# ------------------------------------------------------------------ market values
def recorded_values(career):
    """{player: euros} from the last game day Dugout recorded, and that day."""
    files = sorted(glob.glob(os.path.join(career.dir, 'market', '*.npz')))
    files = [f for f in files if not f.endswith('.tmp.npz')]
    if not files:
        return {}, None
    z = np.load(files[-1])
    return {int(k): int(v) for k, v in zip(z['ids'], z['value'])}, os.path.basename(files[-1])[:-4]


def recorded_budget(career):
    try:
        log = json.load(open(os.path.join(career.dir, 'market', 'budget.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not log:
        return None
    day = max(log)
    return {**log[day], 'date': day}


def _features(s, rows, today):
    ovr = s.ovr[rows].astype(np.float64)
    age = s.age[rows].astype(np.float64)
    room = np.clip(s.out['peak'][rows] - s.ovr[rows], 0, 20) * (age <= 24)
    years = np.array([max(0.0, ((_contract_date(c) or today) - today).days / 365) for c in s.contract_end[rows]])
    return np.stack([np.ones_like(ovr), ovr, ovr ** 2 / 100, age, age ** 2 / 100, room, np.minimum(years, 4)], axis=1)


def heuristic_values(s, rows, today):
    ovr = s.ovr[rows].astype(np.float64)
    age = s.age[rows]
    v = 1.2e6 * np.exp(0.23 * (ovr - 70))
    factor = np.select([age <= 21, age <= 25, age <= 29, age <= 31, age <= 33], [1.4, 1.2, 1.0, 0.7, 0.45], 0.25)
    room = np.clip(s.out['peak'][rows] - s.ovr[rows], 0, 20) * (age <= 23)
    years = np.array([((_contract_date(c) or today) - today).days / 365 for c in s.contract_end[rows]])
    v = v * factor * (1 + 0.06 * room) * np.where(years < 1, 0.6, 1.0)
    return v


class Values:
    """Market value of any player: the game's own when known, else a fitted or rough estimate."""

    def __init__(self, s, known, today, source):
        self.s, self.known, self.source, self.today = s, known, source, today
        self.coef = None
        rows = np.array([s.row[p] for p in known if p in s.row], dtype=np.int64)
        if len(rows) >= 300:
            X = _features(s, rows, today)
            y = np.log(np.array([known[int(s.ids[i])] for i in rows], dtype=np.float64))
            self.coef = np.linalg.lstsq(X, y, rcond=None)[0]
        self.kind = 'game' if known else 'estimate'

    def of(self, rows):
        rows = np.asarray(rows, dtype=np.int64)
        if self.coef is not None:
            est = np.exp(_features(self.s, rows, self.today) @ self.coef)
        else:
            est = heuristic_values(self.s, rows, self.today)
        out = []
        for i, e in zip(rows, est):
            v = self.known.get(int(self.s.ids[i]))
            out.append((int(v), True) if v else (int(round(e, -5)), False))
        return out


# ------------------------------------------------------------------ the plan
def build(engine):
    e = engine
    s, career = e.snap, e.career
    today = e.ingame.mem.game_date or s.date
    season_end = _season_end(today)
    window = dt.date(season_end.year, 7, 1), dt.date(season_end.year, 8, 31)
    if today >= window[0]:
        window = (today, window[1])
    live = e.live.status_json()
    if e.live.values:
        known, vsource = dict(e.live.values), 'đọc trực tiếp từ game'
    else:
        known, day = recorded_values(career)
        vsource = f'giá game ngày {day}' if known else 'ước tính (chưa có giá thật: mở game để Dugout đọc)'
    values = Values(s, known, today, vsource)
    budget = live.get('budget') or recorded_budget(career)
    payroll = ((s.club or {}).get('salary_payroll') or {}).get('annual_payroll_eur')
    comp = (s.club or {}).get('squad_composition') or {}

    extra = e.extra or {}
    senior = [p for p in extra if p in s.row and not extra[p].get('youth')]
    youth = [p for p in extra if p in s.row and extra[p].get('youth')]
    minutes = _minutes(e)
    total_min = max(1, max(minutes.values(), default=0))
    nxt = s.out['ovr'][:, 1] if s.out['ovr'].shape[1] > 1 else s.ovr
    loans_in = {int(a.get('player_id') or 0) for a in (s.club.get('club_agreements') or [])
                if a.get('kind') == 'loan' and a.get('direction') == 'incoming' and a.get('state') == 5}

    def group_ovr(i, g, next_season=True):
        """Best OVR of player row i in a position group he can play (grade B or A, or registered)."""
        best = None
        for p in dict((k, ps) for k, _l, ps in GROUPS)[g]:
            k = POS.index(p)
            if s.grades[i, k] >= 1 or s.main_pos[i] == k:
                v = float(s.ovr_all[i, k]) + (float(nxt[i] - s.ovr[i]) if next_season else 0)
                best = v if best is None else max(best, v)
        return best

    # ---- who leaves for sure / contracts to decide
    xi_need = _formation(s)
    leaving, contracts = [], []
    for pid in senior:
        i = s.row[pid]
        x = extra[pid]
        ce = _contract_date(s.contract_end[i])
        if x.get('retiring'):
            leaving.append(_p(s, i, values, 'Giải nghệ cuối mùa'))
        elif pid in loans_in:
            leaving.append(_p(s, i, values, 'Hết hạn mượn, về CLB chủ quản'))
        elif ce and ce <= season_end:
            contracts.append(i)

    # ---- the squad next season (before any business) and its strength by group
    stays = [s.row[p] for p in senior if not extra[p].get('retiring') and p not in loans_in]
    key_players = _best_xi(s, stays, xi_need, group_ovr)
    renew, let_go = [], []
    for i in contracts:
        pid = int(s.ids[i])
        young = s.age[i] <= 23 and s.out['peak'][i] >= s.ovr[i] + 3
        if pid in key_players or young:
            renew.append(_p(s, i, values, 'Trụ cột mùa sau' if pid in key_players else 'Trẻ, còn tiến bộ',
                            action='Gia hạn trước khi hết hợp đồng'))
        else:
            let_go.append(_p(s, i, values, 'Không nằm trong đội hình chính mùa sau', action='Bán ngay (còn thu phí) hoặc để ra đi tự do'))
    gone = {s.row[int(p['id'])] for p in let_go}
    squad_next = [i for i in stays if i not in gone]

    # ---- needs by group
    needs, groups = [], []
    league = _league_benchmark(s, xi_need, group_ovr)
    team_avg = np.mean([v for _i, v in _xi_values(s, squad_next, xi_need, group_ovr)] or [0])
    for g, label, _ps in GROUPS:
        want = xi_need.get(g, 0)
        depth_want = max(1, want * 2) if want else (1 if g in ('AM',) else 0)
        if g == 'GK':
            depth_want = 2
        cands = sorted(((group_ovr(i, g), i) for i in squad_next if group_ovr(i, g) is not None), reverse=True)
        natural = [(v, i) for v, i in cands if GROUP_OF.get(POS[s.main_pos[i]]) == g]
        starters = cands[:want] if want else []
        start_avg = float(np.mean([v for v, _i in starters])) if starters else None
        notes, score = [], 0.0
        if want and len(cands) < want:
            notes.append(f'thiếu người đá chính ({len(cands)}/{want})')
            score += 10 * (want - len(cands))
        if len(natural) < depth_want:
            notes.append(f'mỏng: {len(natural)} người đá sở trường, nên có {depth_want}')
            score += 3 * (depth_want - len(natural))
        if start_avg is not None and start_avg < team_avg - 2:
            notes.append(f'yếu hơn mặt bằng đội ({start_avg:.0f} so với {team_avg:.0f})')
            score += team_avg - start_avg
        bench = league.get(g)
        if start_avg is not None and bench and start_avg < bench - 1:
            notes.append(f'kém top 3 giải ({start_avg:.0f} so với {bench:.0f})')
            score += (bench - start_avg) * 0.8
        old = [i for _v, i in starters if s.age[i] >= 31]
        heirs = [i for _v, i in cands if s.age[i] <= 24 and s.out['peak'][i] >= (start_avg or 0) - 1]
        if old and heirs:
            old = []                           # a young successor is already there
        if old:
            notes.append('người đá chính đã ' + ', '.join(f'{s.player_name(int(s.ids[i]))} {int(s.age[i])}t' for i in old)
                         + ': cần người kế cận')
            score += 2 * len(old)
        succession = bool(old) and len(notes) == 1
        groups.append({'key': g, 'label': label, 'starters_needed': want, 'depth_needed': depth_want,
                       'succession': succession,
                       'players': [_p(s, i, values, '', ovr_next=round(v, 1)) for v, i in cands[:6]],
                       'start_avg': None if start_avg is None else round(start_avg, 1),
                       'league_top3': None if bench is None else round(bench, 1), 'notes': notes, 'score': round(score, 1)})
    order = sorted([gr for gr in groups if gr['score'] > 0], key=lambda gr: -gr['score'])
    for gr in order[:4]:
        target = gr['start_avg'] if gr['start_avg'] is not None else team_avg - 2
        gr['targets'] = _targets(s, gr['key'], target, values, today, season_end, group_ovr, budget,
                                 succession=gr['succession'])
        needs.append(gr)

    # ---- who to sell
    sell = _sell(s, stays, gone, extra, minutes, total_min, values, key_players, group_ovr, xi_need)

    # ---- youth to promote
    promote = []
    for pid in youth:
        i = s.row[pid]
        if s.age[i] >= 17 and s.out['peak'][i] >= 76:
            promote.append(_p(s, i, values, f'Ngưỡng AI {int(round(s.out["peak"][i]))}', action='Đôn lên đội một'))
    promote.sort(key=lambda p: -p['peak'])

    income = sum(p['value'] for p in sell if p.get('action', '').startswith('Bán'))
    spend = sum(gr['targets']['value'][0]['fee'] for gr in needs if gr['targets']['value'])
    return {'today': today.isoformat(), 'season_end': season_end.isoformat(),
            'window': [window[0].isoformat(), window[1].isoformat()], 'days_to_window': (window[0] - today).days,
            'budget': budget, 'payroll': payroll, 'composition': comp, 'values_source': values.source,
            'values_kind': values.kind, 'fitted': values.coef is not None,
            'leaving': leaving, 'renew': renew, 'let_go': let_go, 'needs': needs, 'groups': groups,
            'sell': sell, 'promote': promote[:6],
            'totals': {'sell_income': income, 'first_choice_spend': spend,
                       'balance': (budget or {}).get('transfer', 0) + income - spend if budget else None}}


def _p(s, i, values, why, action='', ovr_next=None, **more):
    pid = int(s.ids[i])
    v, real = values.of([i])[0]
    ce = int(s.contract_end[i])
    out = {'id': pid, 'name': s.player_name(pid), 'age': int(s.age[i]), 'pos': POS[int(s.main_pos[i])],
           'ovr': int(s.ovr[i]), 'next': ovr_next if ovr_next is not None else round(float(s.out['ovr'][i, 1]), 1),
           'peak': int(round(float(s.out['peak'][i]))), 'team': int(s.team[i]), 'team_name': s.club_name(int(s.team[i])),
           'contract': f'{ce % 100}/{ce // 100 % 100}/{ce // 10000}' if ce > 0 else '', 'salary': int(s.salary[i]),
           'value': v, 'value_real': real, 'why': why, 'action': action}
    out.update(more)
    return out


def _minutes(e):
    out = {}
    for m in getattr(e, 'season_matches', None) or []:
        if not m.get('played'):
            continue
        side = m['home_players'] if m['venue'] == 'home' else m['away_players']
        for p in side or []:
            out[p['id']] = out.get(p['id'], 0) + (p.get('min') or 0)
    return out


def _formation(s):
    plan = (s.gameplans or {}).get(s.team_id)
    if not plan or not plan.get('xi'):
        return dict(DEFAULT_XI)
    need = {g: 0 for g, _l, _p in GROUPS}
    for slot in plan['xi']:
        r = int(slot['role'])
        if 0 <= r < 13:
            need[GROUP_OF[POS[r]]] += 1
    return need if sum(need.values()) == 11 else dict(DEFAULT_XI)


def _xi_values(s, rows, need, group_ovr):
    """Greedy best XI for the formation: [(row, value)]."""
    used, out = set(), []
    for g, want in sorted(need.items(), key=lambda kv: kv[0] != 'GK'):
        cands = sorted(((group_ovr(i, g), i) for i in rows if i not in used and group_ovr(i, g) is not None), reverse=True)
        for v, i in cands[:want]:
            used.add(i)
            out.append((i, v))
    return out


def _best_xi(s, rows, need, group_ovr):
    return {int(s.ids[i]) for i, _v in _xi_values(s, rows, need, group_ovr)}


def _league_benchmark(s, need, group_ovr):
    """Average starter OVR by group of the three strongest clubs of the managed club's league."""
    table = None
    for tid in s.my_tournaments:
        r = s.regions.get(tid)
        if r and r.table and any(t.team_id == s.team_id for t in r.table):
            table = r.table
            break
    if not table:
        return {}
    teams = [t.team_id for t in table if t.team_id != s.team_id]
    strength = []
    for tid in teams:
        rows = np.nonzero(s.team == tid)[0]
        if len(rows) < 11:
            continue
        xi = _xi_values(s, rows, need, lambda i, g: group_ovr(i, g, next_season=False))
        strength.append((np.mean([v for _i, v in xi]), tid, xi))
    strength.sort(reverse=True)
    out = {}
    for g in need:
        by_g = []
        for _m, _tid, xi in strength[:3]:
            rows_xi = [i for i, _v in xi]
            gv = sorted((group_ovr(i, g, False) for i in rows_xi if group_ovr(i, g, False) is not None), reverse=True)
            by_g += gv[:need[g]]
        if by_g and need[g]:
            out[g] = float(np.mean(by_g))
    return out


def _targets(s, g, target, values, today, season_end, group_ovr, budget, succession=False):
    """Players worth buying for group g, better than the current starters (or, when the only
    worry is an ageing starter, young players who will reach his level): {'best': the strongest
    the budget allows, 'value': the most improvement per euro}."""
    pool = np.nonzero((s.team != s.team_id) & (s.age >= 17) & (s.age <= 31))[0]
    positions = [POS.index(p) for p in dict((k, ps) for k, _l, ps in GROUPS)[g]]
    ok = np.zeros(len(s.ids), dtype=bool)
    for k in positions:
        ok |= (s.grades[:, k] >= 1) | (s.main_pos == k)
    pool = pool[ok[pool]]
    nxt = s.out['ovr'][:, 1]
    best_pos = np.max(np.stack([np.where((s.grades[:, k] >= 1) | (s.main_pos == k), s.ovr_all[:, k], 0) for k in positions]),
                      axis=0)
    level = best_pos + (nxt - s.ovr)
    if succession:
        pool = pool[(s.age[pool] <= 24) & (s.out['peak'][pool] >= target) & (level[pool] >= target - 6)]
    else:
        pool = pool[level[pool] >= target + 1]
    if not len(pool):
        return {'best': [], 'value': []}
    states = s.states or {}
    vals = values.of(pool)
    cash = (budget or {}).get('transfer')
    out = []
    for (v, real), i in zip(vals, pool):
        pid = int(s.ids[i])
        st = states.get(pid, {})
        ce = _contract_date(s.contract_end[i])
        if int(s.team[i]) == 0 and ce is not None:
            continue                          # no club but a contract: a pool of the game, not a free agent
        free_now = int(s.team[i]) == 0
        expiring = ce is not None and ce <= season_end
        listed = bool(st.get('transfer_listed'))
        if st.get('is_retiring'):
            continue
        fee = 0 if free_now or expiring else int(v * (1.0 if listed else 1.3))
        tags = []
        if free_now:
            tags.append('tự do, ký ngay')
        elif expiring:
            tags.append(f'hết hợp đồng {ce.day}/{ce.month}/{ce.year}: ký tự do hè này')
        if listed:
            tags.append('đang được rao bán')
        if st.get('loan_listed'):
            tags.append('có thể mượn')
        if cash and fee > cash * 1.2:
            continue
        up = float(level[i] - target)
        grow = max(0.0, float(s.out['peak'][i] - nxt[i])) if s.age[i] <= 24 else 0.0
        if succession:
            up = float(s.out['peak'][i] - target) + 0.5 * float(level[i] - target)
        quality = up * 3 + grow * 0.6 + (3 if free_now or expiring else 0) + (1.5 if listed else 0)
        quality -= 0.4 * max(0, int(s.age[i]) - 28)
        if cash:
            quality -= 6 * max(0.0, fee / cash - 0.5)
        per_euro = quality / (1 + fee / 15e6)
        out.append((quality, per_euro, _p(s, i, values, '', ovr_next=round(float(level[i]), 1), fee=fee, tags=tags,
                                          gain=round(up, 1), fit=int(round(float(max(s.fit[i, k] for k in positions)))))))
    best = [p for _q, _e, p in sorted(out, key=lambda t: -t[0])[:3]]
    taken = {p['id'] for p in best}
    value = [p for _q, _e, p in sorted(out, key=lambda t: -t[1]) if p['id'] not in taken][:4]
    return {'best': best, 'value': value}


def _sell(s, stays, gone, extra, minutes, total_min, values, key_players, group_ovr, need):
    out = []
    by_group = {}
    for i in stays:
        g = GROUP_OF.get(POS[int(s.main_pos[i])])
        by_group.setdefault(g, []).append(i)
    for i in stays:
        if i in gone:
            continue
        pid = int(s.ids[i])
        if pid in key_players:
            continue
        reasons, score = [], 0.0
        g = GROUP_OF.get(POS[int(s.main_pos[i])])
        rivals = sorted(by_group.get(g, []), key=lambda j: -float(s.out['ovr'][j, 1]))
        rank = rivals.index(i) + 1 if i in rivals else 99
        depth = max(1, need.get(g, 1) * 2)
        young = s.age[i] <= 22 and s.out['peak'][i] >= s.ovr[i] + 4
        share = minutes.get(pid, 0) / total_min
        if rank > depth and not young:
            reasons.append(f'dư thừa ở {g} (xếp thứ {rank}, cần {depth})')
            score += 3 + rank - depth
        if s.age[i] >= 30 and s.out['ovr'][i, 1] < s.ovr[i] - 0.5:
            reasons.append(f'{int(s.age[i])} tuổi, AI dự đoán giảm ({int(s.ovr[i])} → {s.out["ovr"][i, 1]:.0f})')
            score += 2
        if share < 0.25 and s.age[i] >= 23:
            reasons.append(f'ít ra sân ({minutes.get(pid, 0)} phút)')
            score += 1.5
        if extra[pid].get('listed'):
            reasons.append('đang được rao bán trong game')
            score += 1
        if not reasons:
            continue
        action = 'Cho mượn' if young or (s.age[i] <= 21 and s.out['peak'][i] >= 75) else 'Bán'
        out.append((score, _p(s, i, values, '; '.join(reasons), action=action)))
    out.sort(key=lambda t: -t[0])
    return [p for _s, p in out[:10]]

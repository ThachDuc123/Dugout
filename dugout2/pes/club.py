"""The managed club's screen data: squad details (shirt, contract, salary, role, listing, release
clause), youth team, pending deals, club season stats, followers and world club ranking.

Some tables have no fixed address and are found by their content (the same way each time):
release clauses (48-byte rows: career index, player id, salary / 100, clause / 100), deals (60-byte
rows around the club's packed id), club stats (a block starting with the packed club id), followers
(a fixed 16-byte tail) and the world club ranking (16-byte rows: club, rank, points, flags).
"""
import struct

import numpy as np

from . import career

SALARY_SCALE = 100
RELEASE_STRIDE, RELEASE_GAP, RELEASE_MIN, RELEASE_MAX = 48, 16, 1, 20000000
DEAL_STRIDE, DEAL_PARENT, DEAL_BORROW, DEAL_STATE, DEAL_INDEX, DEAL_PLAYER, DEAL_FEE = 60, 32, 8, 12, 36, 40, 44
DEAL_START_DATE, DEAL_END_DATE = 16, 52
DEAL_SENTINELS = {0xFFFFFFFF, 0xFFFFFF, 0xFFFF}
DEAL_STATES = {1: 'pending', 2: 'rejected', 4: 'accepted', 5: 'completed'}
PERF_HEADER, PERF_ROW, PERF_MATCHES_MAX = 1276, 108, 80
GOAL_TYPES = ('dribbling', 'pass', 'cross', 'through_ball', 'set_piece', 'penalties')
FOLLOWERS_TAIL = b'\xff\xff\x00\x00\xff\xff\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff'
FOLLOWERS_HINT, FOLLOWERS_MIN, FOLLOWERS_MAX = 11938212, 10000, 99999999
RANKING_STRIDE, RANKING_MIN, RANKING_MAX = 16, 300, 700
YOUTH_MARK_AT, YOUTH_MARK, YOUTH_MAX = 139, 48, 40
MAX_TEAM = 262143


# ------------------------------------------------------------------------------ squad
def squad(data, team_id, team_offset, states):
    slots = career.team_squad(data, team_offset)
    clauses = release_clauses(data, slots, states)
    out = []
    for s in slots:
        st = states.get(s['player_id']) or states.get(s['ml_player_id']) or {}
        p = dict(s)
        p['team_id'] = team_id
        for k in ('age', 'nationality_id', 'contract_end_year', 'contract_end_month', 'contract_end_day',
                  'annual_salary_raw', 'team_role_id', 'role', 'transfer_listed', 'loan_listed', 'is_retiring',
                  'registered_position_id', 'unavailable_days'):
            if k in st:
                p[k] = st[k]
        c = clauses.get(s['player_id'])
        if c:
            p['release_clause'] = c
        out.append(p)
    return out


def release_clauses(data, slots, states):
    """{player: release clause in euros} for the squad."""
    roster, search = {}, []
    for slot in slots:
        sid = int(slot['player_id'])
        ml = int(slot.get('ml_player_id') or sid)
        st = states.get(sid) or states.get(ml) or {}
        euros = int(st.get('annual_salary_raw') or 0)
        stored = euros // SALARY_SCALE if euros else 0
        if not 1 <= stored <= 2000000:
            continue
        meta = {'snapshot_id': sid, 'career_index': int(slot.get('career_index') or st.get('career_index') or 0),
                'salary_raw': stored}
        for pid in {ml, sid}:
            if 1 <= pid <= 0xFFFFFFFF:
                roster.setdefault(pid, []).append(meta)
                if pid not in search:
                    search.append(pid)
    hits, bases = [], set()
    for pid in search:
        needle = struct.pack('<I', pid)
        at = data.find(needle)
        while at >= 0:
            base = at - 4
            if 0 <= base and base + 16 <= len(data) and base not in bases:
                cidx, player, salary, clause = struct.unpack_from('<IIII', data, base)
                for item in roster.get(player, []):
                    if item['career_index'] and cidx != item['career_index']:
                        continue
                    if item['salary_raw'] != salary or not RELEASE_MIN <= clause <= RELEASE_MAX:
                        continue
                    bases.add(base)
                    hits.append({'base': base, 'snapshot_id': item['snapshot_id'], 'clause_raw': clause})
                    break
            at = data.find(needle, at + 1)
    if not hits:
        return {}
    hits.sort(key=lambda h: h['base'])
    clusters, current = [], [hits[0]]
    for h in hits[1:]:
        gap = h['base'] - current[-1]['base']
        steps = gap // RELEASE_STRIDE if gap % RELEASE_STRIDE == 0 else 0
        if 1 <= steps <= RELEASE_GAP:
            current.append(h)
        else:
            clusters.append(current)
            current = [h]
    clusters.append(current)
    best = max(clusters, key=lambda c: (len({h['snapshot_id'] for h in c}), len(c)))
    return {h['snapshot_id']: h['clause_raw'] * SALARY_SCALE for h in best}


def youth_team(table, senior_ids):
    rows = []
    for start, mid, cidx in career.records(table):
        rec = table[start:start + career.RECORD]
        if rec[YOUTH_MARK_AT] != YOUTH_MARK or struct.unpack_from('<H', rec, 124)[0] != 65535:
            continue
        pid = career.snapshot_id(mid, cidx)
        if pid in senior_ids or mid in senior_ids:
            continue
        row = {'player_id': pid, 'ml_player_id': mid, 'career_index': cidx, 'shirt_number': 0}
        a = career.age(rec)
        if a is not None:
            row['age'] = a
        sal = career.salary(rec)
        if sal is not None:
            row['annual_salary_raw'] = sal
        p = career.position(rec)
        if p is not None:
            row['registered_position_id'] = p
        rows.append(row)
        if len(rows) > YOUTH_MAX:
            return []
    rows.sort(key=lambda r: (int(r['career_index']), int(r['player_id'])))
    for i, r in enumerate(rows, 1):
        r['roster_position'] = i
    return rows


# ----------------------------------------------------------------------- club stats
def _small(values, cap):
    return bool(values) and all(0 <= int(v) <= cap for v in values)


def _percents(values):
    total = sum(int(v) for v in values)
    if total <= 0:
        return [0] * len(values)
    raw = [v * 100 / total for v in values]
    rounded = [int(v + 0.5) for v in raw]
    while sum(rounded) > 100:
        i = max(range(len(rounded)), key=lambda k: rounded[k] - raw[k])
        rounded[i] -= 1
    while sum(rounded) < 100:
        i = max(range(len(rounded)), key=lambda k: raw[k] - rounded[k])
        rounded[i] += 1
    return rounded


def _performance_block(data, packed):
    needle = struct.pack('<I', packed)
    best, at = None, data.find(needle)
    while at >= 0:
        if at + 472 <= len(data):
            matches = struct.unpack_from('<I', data, at + 16)[0]
            if 1 <= matches <= PERF_MATCHES_MAX:
                ball = struct.unpack_from('<9I', data, at + 212)
                types = struct.unpack_from('<6I', data, at + 420)
                scored = struct.unpack_from('<7I', data, at + 364)
                if _small(ball, 2000) and _small(types, PERF_MATCHES_MAX) and _small(scored, PERF_MATCHES_MAX):
                    if best is None or matches > best[1]:
                        best = (at, matches)
        at = data.find(needle, at + 1)
    return best[0] if best else None


def _rate(successful, attempted):
    return int(successful * 100 / attempted + 0.5) if attempted > 0 else None


def performance(data, team_offset, slots):
    """Season stats of the club: goals by 15-minute period and by type, attacking areas and the
    squad's leaders in dribbling, passing, receiving, shooting, aerials and tackles."""
    if team_offset is None:
        return None
    packed = struct.unpack_from('<I', data, team_offset)[0]
    found = _performance_block(data, packed)
    if found is None:
        return None
    u = lambda off, n: list(struct.unpack_from(f'<{n}I', data, found + off))
    matches = struct.unpack_from('<I', data, found + 16)[0]
    play, ball = u(176, 9), u(212, 9)
    scored, conceded, t_scored, t_conceded = u(364, 7), u(392, 7), u(420, 6), u(448, 6)
    if not (_small(play, 20000) and _small(ball, 2000) and _small(scored, PERF_MATCHES_MAX)
            and _small(conceded, PERF_MATCHES_MAX) and _small(t_scored, PERF_MATCHES_MAX)
            and _small(t_conceded, PERF_MATCHES_MAX)):
        return None
    cols = [play[0] + play[3] + play[6], play[1] + play[4] + play[7], play[2] + play[5] + play[8]]
    roster = {}
    for s in slots:
        meta = {'snapshot_id': int(s['player_id']), 'career_index': int(s.get('career_index') or 0)}
        for pid in {int(s.get('ml_player_id') or s['player_id']), int(s['player_id'])}:
            roster.setdefault(pid, []).append(meta)
    rows = []
    for index in range(48):
        base = found + PERF_HEADER + index * PERF_ROW
        if base + PERF_ROW > len(data):
            break
        cidx, pid = struct.unpack_from('<II', data, base)
        slot = None
        for item in roster.get(pid, []):
            if item['career_index'] and item['career_index'] != cidx:
                continue
            slot = item
            break
        if slot is None:
            continue
        st = list(struct.unpack_from('<25I', data, base + 8))
        if not _small(st[:24], 20000):
            continue
        # [successful, attempted]
        rows.append({'player_id': slot['snapshot_id'], 'apps': st[0], 'dribbling': [st[8], st[7]],
                     'passing': [st[14] + st[16] + st[18] + st[20], st[13] + st[15] + st[17] + st[19]],
                     'received': [st[10], st[9]], 'shooting': [st[6], st[5]], 'aerial': st[12],
                     'tackles': st[21] + st[23]})

    def top(key, pair):
        ranked = []
        for r in rows:
            if pair:
                s, a = r[key]
                if a <= 0 and s <= 0:
                    continue
                ranked.append((s, a, r))
            else:
                won = int(r[key])
                if won > 0:
                    ranked.append((won, 0, r))
        ranked.sort(key=lambda x: (x[0], x[0] / x[1] if x[1] else 0.0), reverse=True)
        out = []
        for s, a, r in ranked[:5]:
            item = {'player_id': r['player_id'], 'successful': s}
            if pair:
                item['attempted'] = a
                rate = _rate(s, a)
                if rate is not None:
                    item['rate'] = rate
            out.append(item)
        return out

    return {'matches': matches, 'attacking_areas_pct': _percents(cols), 'play_area_pct': _percents(play),
            'ball_winning_pct': _percents(ball), 'times_scored': scored, 'times_conceded': conceded,
            'types_scored': dict(zip(GOAL_TYPES, t_scored)), 'types_conceded': dict(zip(GOAL_TYPES, t_conceded)),
            'rankings': {'dribbling': top('dribbling', True), 'passing': top('passing', True),
                         'received': top('received', True), 'shooting': top('shooting', True),
                         'aerial': top('aerial', False), 'tackles': top('tackles', False)}}


# ------------------------------------------------------------------ followers, ranking
def followers(data):
    hits, at = [], data.find(FOLLOWERS_TAIL)
    while at >= 0:
        base = at - 8
        if base >= 0:
            current, previous = struct.unpack_from('<II', data, base)
            if FOLLOWERS_MIN <= current <= FOLLOWERS_MAX and (not previous or FOLLOWERS_MIN <= previous <= FOLLOWERS_MAX):
                hits.append({'offset': base, 'followers': current, 'followers_previous': previous})
        at = data.find(FOLLOWERS_TAIL, at + 1)
    for h in hits:
        if h['offset'] == FOLLOWERS_HINT:
            return h
    return hits[0] if len(hits) == 1 else None


def world_ranking(data):
    """[(team, rank, points)] of the world club ranking, best first."""
    n = len(data) // 4
    words = np.frombuffer(data[:n * 4], dtype='<u4')
    # rows of 16 bytes: team << 14, rank, points, flags. Candidates: ranks 1, 2, 3 in consecutive rows.
    idx = np.nonzero(words[1:n - 8] == 1)[0] + 1
    idx = idx[(words[idx + 4] == 2) & (words[idx + 8] == 3)]
    candidates = []
    for rank_at in idx.tolist():
        base = (rank_at - 1) * 4
        entries, seen, steps, prev = [], set(), 0, None
        for rank in range(1, RANKING_MAX + 1):
            off = base + (rank - 1) * RANKING_STRIDE
            if off + RANKING_STRIDE > len(data):
                break
            packed, stored, points, _flags = struct.unpack_from('<IIII', data, off)
            team = packed >> 14
            if stored != rank or not 1 <= team <= MAX_TEAM or team in seen or points < 1:
                break
            if prev is not None and points <= prev:
                steps += 1
            prev = points
            seen.add(team)
            entries.append((team, rank, points))
        if len(entries) < RANKING_MIN or steps / max(1, len(entries) - 1) < 0.6:
            continue
        candidates.append(entries)
    if not candidates:
        return None
    candidates.sort(key=len, reverse=True)
    if len(candidates) > 1 and len(candidates[0]) == len(candidates[1]):
        return None
    return candidates[0]


# ------------------------------------------------------------------------------ deals
def _date(data, offset):
    if offset + 4 > len(data):
        return None
    y, m, d = struct.unpack_from('<HBB', data, offset)
    if 2020 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
        return {'year': y, 'month': m, 'day': d}
    return None


def deals(data, team):
    """Transfers and loans the club is part of (offers made or received, agreed, completed)."""
    if not data or team < 1:
        return []
    marker = struct.pack('<H', team >> 2)
    rows, seen = [], set()
    cursor = data.find(marker)
    while cursor != -1:
        for fld in (DEAL_PARENT, DEAL_BORROW):
            start = cursor - (fld + 2)
            if start < 0 or start + DEAL_STRIDE > len(data) or start in seen:
                continue
            seen.add(start)
            row = _deal(data, start, team)
            if row:
                rows.append(row)
        cursor = data.find(marker, cursor + 1)
    rows.sort(key=lambda r: (r['state'], r.get('player_id', 0)))
    return rows


def _deal(data, start, team):
    pid = struct.unpack_from('<I', data, start + DEAL_PLAYER)[0]
    if not 100 <= pid <= 1000000 or pid in DEAL_SENTINELS:
        return None
    seller = struct.unpack_from('<I', data, start + DEAL_PARENT)[0] >> 14
    buyer = struct.unpack_from('<I', data, start + DEAL_BORROW)[0] >> 14
    if not (1 <= seller <= MAX_TEAM and 1 <= buyer <= MAX_TEAM) or seller == buyer or team not in (seller, buyer):
        return None
    state = data[start + DEAL_STATE]
    if state not in DEAL_STATES:
        return None
    fee_a, fee_b = struct.unpack_from('<II', data, start + DEAL_FEE)
    if fee_a != fee_b:
        return None
    end = _date(data, start + DEAL_END_DATE)
    return {'state': state, 'state_name': DEAL_STATES[state], 'kind': 'loan' if end else 'transfer',
            'direction': 'outgoing' if seller == team else 'incoming', 'player_id': pid,
            'career_index': struct.unpack_from('<I', data, start + DEAL_INDEX)[0],
            'seller_team_id': seller, 'buyer_team_id': buyer, 'fee': fee_a,
            'start_date': _date(data, start + DEAL_START_DATE), 'end_date': end}


# ------------------------------------------------------------------------- snapshot
def snapshot(data, table, team_id, team_offset, states):
    """What the club screens need, in one dict."""
    players = squad(data, team_id, team_offset, states) if team_offset is not None else []
    senior = {int(p['player_id']) for p in players} | {int(p['ml_player_id']) for p in players}
    senior.discard(0)
    out = {'players': players, 'youth_team': youth_team(table, senior)}
    try:
        out['club_performance'] = performance(data, team_offset, players)
    except (struct.error, ValueError):
        out['club_performance'] = None
    info = {}
    f = followers(data)
    if f:
        info['followers'] = f['followers']
    ranking = world_ranking(data)
    if ranking:
        for team, rank, points in ranking:
            if team == team_id:
                info['club_rank'], info['club_rank_points'] = rank, points
                break
    out['career'] = info
    out['club_agreements'] = deals(data, team_id)
    # players out on loan still count against the 40 places and are still paid
    on_loan = {d['player_id'] for d in out['club_agreements']
               if d['kind'] == 'loan' and d['direction'] == 'outgoing' and d['state'] == 5} - senior
    wages = [p.get('annual_salary_raw') for p in players] + [(states.get(pid) or {}).get('annual_salary_raw') for pid in on_loan]
    out['salary_payroll'] = {'annual_payroll_eur': sum(w for w in wages if w)} if wages and all(wages) else {}
    out['squad_composition'] = {'squad_size': len(players), 'out_on_loan': len(on_loan),
                                'free_slots': max(0, career.MAX_SQUAD_SLOTS - len(players) - len(on_loan))}
    return out

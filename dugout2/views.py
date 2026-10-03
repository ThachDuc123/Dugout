"""Screen payloads. Everything the UI shows for a save is built once per load into one bundle,
so switching tabs never waits for the server."""
import datetime as dt

import numpy as np

from . import analysis, chat, events, models, pesdb, terms

POS = terms.POSITIONS
WEEKDAYS = ['Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy', 'Chủ nhật']


def vn_date(d):
    return f'{WEEKDAYS[d.weekday()]}, {d.day}/{d.month}/{d.year}'


def club_extra(snap):
    """pid -> club-screen details (managed squad and youth team)."""
    out = {}
    for p in snap.squad_players:
        pid = int(p['player_id'])
        st = snap.states.get(pid, {}) if snap.states else {}
        c = (p.get('contract_end_year'), p.get('contract_end_month'), p.get('contract_end_day'))
        out[pid] = {'shirt': p.get('shirt_number'), 'role': terms.TEAM_ROLES.get(p.get('role') or '', p.get('role') or ''),
                    'apps': p.get('season_appearances'), 'goals': p.get('season_goals'),
                    'assists': p.get('season_assists'), 'rating': p.get('season_rating_avg'),
                    'contract': list(c) if c[0] and c[0] < 3000 else None,
                    'inj': st.get('unavailable_days') or 0, 'listed': bool(p.get('transfer_listed')),
                    'loan_listed': bool(p.get('loan_listed')), 'retiring': bool(p.get('is_retiring')),
                    'clause': p.get('release_clause'), 'salary': p.get('annual_salary_raw'),
                    'form': st.get('form_code'), 'condition': st.get('condition'), 'youth': False}
    for p in snap.youth_players:
        pid = int(p['player_id'])
        out[pid] = {'shirt': p.get('shirt_number') or None, 'role': 'Đội trẻ', 'youth': True, 'inj': 0,
                    'salary': p.get('annual_salary_raw')}
    return out


def season_stats(matches, team_id):
    """Appearances, goals, assists, minutes, cards and average rating of the managed club's
    players, counted from every match line-up this season (the most reliable source in the save)."""
    out = {}
    for m in matches:
        if not m['played']:
            continue
        side = m['home_players'] if m['venue'] == 'home' else m['away_players']
        for p in side:
            if not p['min']:
                continue
            st = out.setdefault(p['id'], {'apps': 0, 'starts': 0, 'goals': 0, 'assists': 0, 'minutes': 0,
                                          'yellow': 0, 'red': 0, '_r': []})
            st['apps'] += 1
            st['starts'] += 1 if p['start'] else 0
            st['goals'] += p['g']
            st['assists'] += p['a']
            st['minutes'] += p['min']
            st['yellow'] += 1 if p['y'] else 0
            st['red'] += 1 if p['r'] else 0
            if p['rating']:
                st['_r'].append(p['rating'])
                st.setdefault('_r10', []).append(p.get('r10') or p['rating'])
    for st in out.values():
        r = st.pop('_r')
        r10 = st.pop('_r10', [])
        st['rating'] = round(sum(r) / len(r), 2) if r else None
        st['rating10'] = round(sum(r10) / len(r10), 2) if r10 else None      # Dugout's 10-point scale (shown)
    return out


class Builder:
    def __init__(self, engine):
        self.e = engine

    # ----------------------------------------------------------------- summary
    def summary(self, i, extra=None, played=None):
        s = self.e.snap
        o = s.out
        pid = int(s.ids[i])
        fit = s.fit[i]
        order = np.argsort(-(fit + s.ovr_all[i] * 0.01))
        best = [{'pos': POS[p], 'fit': int(round(fit[p])), 'ovr': int(s.ovr_all[i, p]),
                 'grade': 'CBA'[min(int(s.grades[i, p]), 2)]} for k, p in enumerate(order[:3]) if k == 0 or fit[p] >= 15]
        x = (extra or {}).get(pid, {})
        pace = float(s.vs_pred[i] - s.vs_pred_cohort[i]) if not np.isnan(s.vs_pred[i]) else None
        row = {
            'id': pid, 'name': s.names[i], 'age': int(s.age[i]), 'pos': POS[s.main_pos[i]],
            'team': int(s.team[i]), 'team_name': s.club_name(int(s.team[i])) or ('Tự do' if not x else s.team_name),
            'nation': self.e.nations.get(int(s.nation[i]), ''), 'height': int(s.height[i]),
            'foot': 'Trái' if s.left_foot[i] else 'Phải',
            'ovr': int(s.ovr[i]), 'peak': int(round(float(o['peak'][i]))), 'peak_low': int(round(float(o['peak_low'][i]))),
            'peak_high': int(round(float(o['peak_high'][i]))), 'peak_age': int(o['peak_age'][i]),
            'reach_age': int(o['reach_age'][i]), 'trend': int(s.trend[i]), 'regen': bool(s.regen[i]),
            'learned': bool(s.learned[i]), 'pace': None if pace is None else round(pace, 1),
            'style': terms.STYLES[int(s.style[i])][0], 'style_vi': terms.STYLES[int(s.style[i])][1],
            'skills_n': len(pesdb.skill_list(s.skills[i])), 'best': best, 'cond': int(s.cond[i]),
            'wf': [int(s.weak_usage[i]), int(s.weak_accuracy[i])], 'c_end': int(s.contract_end[i]) or None,
            'wage': int(s.salary[i]) or None,
        }
        if x:
            row['stamina'] = int(s.stamina[i])
        if played is not None and pid in played:
            row['played'] = POS[played[pid]]
        if x:
            row.update({k: v for k, v in x.items() if k not in ('form', 'condition')})
        return row

    # ------------------------------------------------------------------ detail
    def detail(self, i, extra=None, played=None, advice=None):
        e = self.e
        s = e.snap
        b = e.brain
        pid = int(s.ids[i])
        d = self.summary(i, extra, played)
        d['abilities'] = {a: int(v) for a, v in zip(terms.ABILITIES, s.abilities[i])}
        base = s.base_row[i]
        if base >= 0 and not s.regen[i]:
            d['abilities_start'] = {a: int(v) for a, v in zip(terms.ABILITIES, e.db.abilities[base])}
            d['start_label'] = 'đầu sự nghiệp (7/2025)'
        d['positions'] = [{'pos': POS[p], 'fit': int(round(s.fit[i, p])), 'ovr': int(s.ovr_all[i, p]),
                           'grade': 'CBA'[min(int(s.grades[i, p]), 2)]} for p in range(13)]
        d['reg_pos'] = POS[int(s.position[i])] if 0 <= int(s.position[i]) < 13 else None
        mine = {int(p['player_id']) for p in s.squad_players} | {int(p['player_id']) for p in s.youth_players}
        d['editable'] = pid in mine
        d['wf_acc'] = int(s.weak_accuracy[i])
        d['skills'] = [terms.skill_label(k) for k in pesdb.skill_list(s.skills[i])]
        d['com'] = [terms.com_label(k) for k in range(len(terms.COM_STYLES)) if int(s.com[i]) >> k & 1]
        d['style_label'] = terms.style_label(int(s.style[i]))
        if base >= 0 and not s.regen[i] and int(e.db.style[base]) != int(s.style[i]):
            d['style_start'] = terms.style_label(int(e.db.style[base]))
        if advice is None:
            advice = analysis.advise(s, b, [i], played or e.played).get(i)
        d['advice'] = advice
        o = s.out
        d['projection'] = [{'age': int(a), 'ovr': round(float(v), 1), 'low': round(float(lo), 1), 'high': round(float(hi), 1)}
                           for a, v, lo, hi in zip(o['ages'][i], o['ovr'][i], o['low'][i], o['high'][i]) if a <= 40]
        d['by_age'] = analysis.by_age(s, b, i)
        # history of the current generation from the saved timeline
        W, bias = b.ovr.W[s.main_pos[i]], b.ovr.b[s.main_pos[i]]
        hist = []
        for date, age, ab, skills, style, grades, team in e.career.timeline.identity(pid, int(s.age[i])):
            hist.append({'date': date.isoformat(), 'age': age, 'ovr': int(np.clip(np.rint(ab @ W + bias), 40, 99)),
                         'team': s.club_name(team)})
        if base >= 0 and not s.regen[i]:
            ab0 = e.db.abilities[base]
            hist.insert(0, {'date': '2025-07-01', 'age': int(e.db.age[base]),
                            'ovr': int(np.clip(np.rint(ab0 @ W + bias), 40, 99)), 'team': '', 'start': True})
        d['history'] = hist
        d['pred_history'] = e.career.predictions.get(str(pid), [])
        d['vs_pred'] = None if np.isnan(s.vs_pred[i]) else round(float(s.vs_pred[i]), 1)
        d['vs_pred_cohort'] = round(float(s.vs_pred_cohort[i]), 1)
        d['vs_pred_since'] = s.vs_pred_since[i] or None
        d['personal'] = round(float(s.personal[i]) * 100, 1)
        # the learned pace in OVR points per year: next year's projection with and without it
        age1 = np.array([s.age[i]], np.float32)
        W1, b1 = b.ovr.W[s.main_pos[i]], b.ovr.b[s.main_pos[i]]
        with_p = b.growth.project(s.abilities[i:i + 1], age1, 1.0, s.personal[i:i + 1])[0] @ W1 + b1
        without = b.growth.project(s.abilities[i:i + 1], age1, 1.0, None)[0] @ W1 + b1
        d['pace_ovr'] = round(float(with_p - without), 1)
        d['matches'] = self.player_matches(pid)
        d['similar'] = [self.summary(j) for j in models.similar(s.abilities, s.main_pos, i, k=6)]
        d['national'] = s.club_name(int(s.national[i])) if s.national[i] else ''
        d['observed'] = e.career.condlog.summary(pid)
        rc = s.release_clauses.get(pid)
        if rc and not d.get('clause'):
            d['clause'] = rc.get('release_clause') if isinstance(rc, dict) else rc
        return d

    def player_matches(self, pid):
        out = []
        for m in self.e.season_matches:
            if not m['played']:
                continue
            side = m['home_players'] if m['venue'] == 'home' else m['away_players']
            for p in side:
                if p['id'] == pid:
                    opp = m['away_name'] if m['venue'] == 'home' else m['home_name']
                    out.append({'date': m['date'], 'opp': opp, 'comp': m['comp_name'], 'min': p['min'],
                                'rating': p['rating'], 'r10': p.get('r10'), 'g': p['g'], 'a': p['a'], 'score': f'{m["hg"]}–{m["ag"]}',
                                'outcome': m['outcome'], 'venue': m['venue']})
        return out[::-1]

    # ------------------------------------------------------------------ bundle
    def bundle(self):
        e = self.e
        s = e.snap
        extra = e.extra
        played = e.played
        squad_rows = e.squad_rows
        youth_rows = e.youth_rows
        adv = e.advice

        squad = []
        for i in squad_rows:
            r = self.summary(i, extra, played)
            a = adv.get(int(i))
            if a:
                r['advice_n'] = a['count']
                r['advice_kinds'] = sorted({g['kind'] for g in a['suggestions']})
                r['training_n'] = len(a.get('training') or [])
                r['training_what'] = [g.get('to') or g.get('skill') or g.get('position') for g in a.get('training') or []]
            squad.append(r)
        squad.sort(key=lambda r: (POS.index(r['pos']), -r['ovr']))
        youth = []
        for i in youth_rows:
            r = self.summary(i, extra, played)
            a = adv.get(int(i))
            if a:
                r['advice_n'] = a['count']
                r['advice_kinds'] = sorted({g['kind'] for g in a['suggestions']})
                r['training_n'] = len(a.get('training') or [])
                r['training_what'] = [g.get('to') or g.get('skill') or g.get('position') for g in a.get('training') or []]
            youth.append(r)
        youth.sort(key=lambda r: -r['peak'])
        regen_idx = np.nonzero(s.regen)[0]
        regens = sorted((self.summary(i) for i in regen_idx), key=lambda r: -r['peak'])[:200]

        details = {}
        for i in list(squad_rows) + list(youth_rows):
            details[str(int(s.ids[i]))] = self.detail(i, extra, played, adv.get(int(i)))

        matches = e.season_matches
        comps = self.competitions()
        return {
            'version': e.version, 'built': dt.datetime.now().isoformat(timespec='seconds'),
            'save': s.save_path, 'save_name': s.save_path.replace('\\', '/').split('/')[-1], 'key': s.key,
            'date': s.date.isoformat(), 'date_vi': vn_date(s.date),
            'club': {'id': s.team_id, 'name': s.team_name, 'short': s.clubs.get(s.team_id, ('', ''))[1],
                     'followers': (s.club.get('career') or {}).get('followers'),
                     'rank': (s.club.get('career') or {}).get('club_rank'),
                     'payroll': (s.club.get('salary_payroll') or {}).get('annual_payroll_eur')},
            'home': self.home(squad, matches, comps),
            'squad': squad, 'lineup': self.lineup(matches),
            'youth': {'youth': youth, 'regens': regens},
            'matches': matches, 'comps': comps, 'archive': self.archive_seasons(),
            'inbox': [chat.decorate(dict(ev), s) for ev in e.career.events[:400]],
            'personas': chat.PERSONAS,
            'matchday': e.md,
            'market': self.market(),
            'details': details,
            'ai': self.ai_info(),
        }

    def competitions(self):
        s = self.e.snap
        out = []
        for tid in s.my_tournaments:
            r = s.regions.get(tid)
            comp = {'id': tid, 'name': s.comp_name(tid), 'table': [], 'scorers': [], 'assists': []}
            if r and r.table and r.team_count:
                form = self._form(tid)
                comp['table'] = [{'pos': t.position, 'team': t.team_id, 'name': s.club_name(t.team_id),
                                  'p': t.played, 'w': t.won, 'd': t.drawn, 'l': t.lost, 'gf': t.goals_for,
                                  'ga': t.goals_against, 'pts': t.points, 'form': form.get(t.team_id, '')}
                                 for t in sorted(r.table, key=lambda t: t.position)]
            if r:
                comp['scorers'] = [{'rank': g.rank, 'n': g.value, 'id': g.player_id, 'name': s.player_name(g.player_id),
                                    'team': g.team_id, 'team_name': s.club_name(g.team_id)} for g in r.goal_ranking[:15]]
                comp['assists'] = [{'rank': g.rank, 'n': g.value, 'id': g.player_id, 'name': s.player_name(g.player_id),
                                    'team': g.team_id, 'team_name': s.club_name(g.team_id)} for g in r.assist_ranking[:15]]
            ties = s.ties.get(tid) or []
            if ties and not comp['table']:
                comp['ties'] = [{'stage': events.round_label(t.legs[0]) if t.legs else '',
                                 'teams': [s.club_name(t.teams[0]), s.club_name(t.teams[1])],
                                 'ids': list(t.teams), 'agg': list(t.aggregate) if t.aggregate else None,
                                 'winner': t.winner, 'complete': t.complete} for t in ties]
            rounds = {}
            for f in s.league_fixtures:
                if f.tournament_id != tid:
                    continue
                key = events.round_label(f)
                rounds.setdefault(key, []).append({
                    'date': f'{f.year:04d}-{f.month:02d}-{f.day:02d}', 'home': f.home_team, 'away': f.away_team,
                    'home_name': s.club_name(f.home_team), 'away_name': s.club_name(f.away_team),
                    'hg': f.home_goals if f.flags & 64 else None, 'ag': f.away_goals if f.flags & 64 else None})
            comp['rounds'] = [{'label': k, 'matches': v} for k, v in rounds.items()]
            out.append(comp)
        out.sort(key=lambda c: (not c['table'], c['name']))      # leagues first, then cups
        return out

    def _form(self, tid):
        s = self.e.snap
        res = {}
        for f in sorted((f for f in s.league_fixtures if f.tournament_id == tid and f.flags & 64),
                        key=lambda f: (f.year, f.month, f.day)):
            for team, mine, theirs in ((f.home_team, f.home_goals, f.away_goals), (f.away_team, f.away_goals, f.home_goals)):
                res.setdefault(team, []).append('W' if mine > theirs else 'L' if mine < theirs else 'D')
        return {t: ''.join(v[-5:]) for t, v in res.items()}

    def lineup(self, matches):
        done = [m for m in matches if m['played']]
        if not done:
            return None
        m = done[-1]
        side = m['home_players'] if m['venue'] == 'home' else m['away_players']
        s = self.e.snap
        out = []
        for p in side:
            i = s.row.get(p['id'])
            pos = analysis.match_position(s, i, p['pos']) if i is not None else None
            out.append({**p, 'pos_name': POS[pos] if pos is not None else '', 'ovr': int(s.ovr[i]) if i is not None else None})
        return {'date': m['date'], 'opp': m['away_name'] if m['venue'] == 'home' else m['home_name'],
                'score': f'{m["hg"]}–{m["ag"]}', 'comp': m['comp_name'], 'players': out}

    def home(self, squad, matches, comps):
        s = self.e.snap
        done = [m for m in matches if m['played']]
        upcoming = [m for m in matches if not m['played']]
        nxt = upcoming[0] if upcoming else None
        if nxt:
            nd = dt.date.fromisoformat(nxt['date'])
            nxt = {**nxt, 'days': (nd - s.date).days, 'date_vi': vn_date(nd)}
        league = next((c for c in comps if c['table']), None)
        standing = None
        if league:
            me = next((t for t in league['table'] if t['team'] == s.team_id), None)
            if me:
                standing = {'comp': league['name'], **me, 'of': len(league['table'])}
        form = ''.join(m['outcome'] for m in done[-5:])
        top_goals = sorted((r for r in squad if r.get('goals')), key=lambda r: -r['goals'])[:5]
        top_assists = sorted((r for r in squad if r.get('assists')), key=lambda r: -r['assists'])[:5]
        top_rating = sorted((r for r in squad if r.get('rating') and (r.get('apps') or 0) >= 3),
                            key=lambda r: -(r.get('rating10') or r['rating']))[:5]
        growers = sorted((r for r in squad if r.get('pace') is not None and r['age'] <= 27),
                         key=lambda r: -r['pace'])[:5]
        advice = [r for r in squad if r.get('advice_n')]
        injured = [r for r in squad if r.get('inj')]
        season_end = s.date.year if s.date.month < 7 else s.date.year + 1
        expiring = [r for r in squad if r.get('contract') and r['contract'][0] <= season_end]
        return {'next': nxt, 'last': done[-1] if done else None, 'recent': done[-5:][::-1], 'standing': standing,
                'form': form, 'top_goals': top_goals, 'top_assists': top_assists, 'top_rating': top_rating,
                'growers': growers, 'advice': advice[:12], 'advice_total': len(advice), 'injured': injured,
                'expiring': expiring, 'unread': sum(1 for ev in self.e.career.events if not ev.get('read')),
                'record': self.record(done)}

    @staticmethod
    def record(done):
        w = sum(1 for m in done if m['outcome'] == 'W')
        d = sum(1 for m in done if m['outcome'] == 'D')
        l = sum(1 for m in done if m['outcome'] == 'L')
        gf = sum((m['hg'] if m['venue'] == 'home' else m['ag']) for m in done)
        ga = sum((m['ag'] if m['venue'] == 'home' else m['hg']) for m in done)
        return {'w': w, 'd': d, 'l': l, 'gf': gf, 'ga': ga, 'n': len(done)}

    def archive_seasons(self):
        """Finished matches from earlier seasons kept in the career archive."""
        current = {m['key'] for m in self.e.season_matches}
        old = [m for k, m in self.e.career.matches.items() if k not in current]
        old.sort(key=lambda m: m['date'])
        seasons = {}
        for m in old:
            d = dt.date.fromisoformat(m['date'])
            label = f'{d.year - 1}/{d.year}' if d.month < 7 else f'{d.year}/{d.year + 1}'
            seasons.setdefault(label, []).append({k: m[k] for k in ('key', 'date', 'comp_name', 'round', 'home', 'away',
                                                                     'home_name', 'away_name', 'hg', 'ag', 'venue',
                                                                     'outcome') if k in m})
        return [{'season': k, 'matches': v, 'record': self.record(v)} for k, v in sorted(seasons.items(), reverse=True)]

    def market(self):
        e = self.e
        s = e.snap
        listed = [self.summary(s.row[p]) for p in s.listed if p in s.row]
        ags = []
        for ag in (s.club.get('club_agreements') or []):
            pid = int(ag.get('player_id') or 0)
            ags.append({'player': s.player_name(pid), 'id': pid, 'kind': ag.get('kind'), 'direction': ag.get('direction'),
                        'state': ag.get('state_name'), 'fee': ag.get('fee'),
                        'buyer': s.club_name(ag.get('buyer_team_id') or 0), 'seller': s.club_name(ag.get('seller_team_id') or 0)})
        young = np.nonzero((s.age <= 21) & (s.team != s.team_id) & (s.out['peak'] >= 82))[0]
        young = young[np.argsort(-s.out['peak'][young])][:60]
        free = np.nonzero((s.team == 0) & (s.contract_end == 0) & (s.age >= 17) & (s.age <= 34))[0]
        free = free[np.argsort(-s.ovr[free])][:60]
        # contracts running out at the end of this season: free next summer
        season_end = (s.date.year if s.date.month <= 8 else s.date.year + 1) * 10000 + 831     # PES contracts end 31/8 or 31/1
        exp = np.nonzero((s.contract_end > 0) & (s.contract_end <= season_end) & (s.team != s.team_id) & (s.team != 0)
                         & (s.age <= 33) & (np.maximum(s.ovr, s.out['peak']) >= 75))[0]
        exp = exp[np.argsort(-(s.out['peak'][exp] + s.ovr[exp]))]
        gk = s.main_pos[exp] == 0
        exp = exp[~gk | (np.cumsum(gk) <= 6)][:80]          # keepers' late peaks would fill the list
        return {'listed': listed, 'agreements': ags, 'prospects': [self.summary(i) for i in young],
                'free': [self.summary(i) for i in free], 'expiring': [self.summary(i) for i in exp],
                'squad_comp': (s.club or {}).get('squad_composition')}

    def ai_info(self):
        e = self.e
        rep = e.brain_report()
        s = e.snap
        e.career.condlog.load()
        return {'report': rep, 'snapshots': len(e.career.timeline.dates),
                'first_snapshot': e.career.timeline.dates[0].isoformat() if e.career.timeline.dates else None,
                'learned': int(s.learned.sum()), 'players': int(len(s.ids)), 'regens': int(s.regen.sum()),
                'decode_seconds': round(s.decode_seconds, 1),
                'match_model': (e.md or {}).get('model'), 'match_model_n': (e.md or {}).get('model_n'),
                'predictions': chat.prediction_summary(e.career),
                'gameplans': len(s.gameplans), 'conditions': int((s.cond >= 0).sum()),
                'kept': {'world': e.career.world.counts(), 'tactics': len(e.career.tactics),
                         'matches': len(e.career.matches), 'conditions': len(e.career.condlog.data),
                         'market': len(e.career.market.dates())}}

    # ------------------------------------------------------------------ search
    def search(self, q):
        s = self.e.snap
        n = len(s.ids)
        m = np.ones(n, dtype=bool)
        text = fold(q.get('q', ''))
        if text:
            m &= np.array([text in t for t in self.e.name_fold])
        if q.get('pos') in POS:
            p = POS.index(q['pos'])
            m &= (s.main_pos == p) | (s.fit[:, p] >= 60)
        if q.get('age_max'):
            m &= s.age <= int(q['age_max'])
        if q.get('age_min'):
            m &= s.age >= int(q['age_min'])
        if q.get('min_peak'):
            m &= s.out['peak'] >= int(q['min_peak'])
        if q.get('min_ovr'):
            m &= s.ovr >= int(q['min_ovr'])
        if q.get('style'):
            m &= s.style == int(q['style'])
        if q.get('skill'):
            k = int(q['skill'])
            m &= ((s.skills >> np.uint64(k)) & np.uint64(1)).astype(bool)
        scope = q.get('scope', 'all')
        if scope == 'free':
            m &= (s.team == 0) & (s.national == 0)
        elif scope == 'mine':
            m &= s.team == s.team_id
        elif scope == 'others':
            m &= (s.team != s.team_id) & (s.team != 0)
        if q.get('regen') == '1':
            m &= s.regen
        idx = np.nonzero(m)[0]
        sort = q.get('sort', 'peak')
        o = s.out
        if sort == 'growth':
            key = -(o['peak'][idx] - s.ovr[idx])
        elif sort == 'ovr':
            key = -s.ovr[idx]
        elif sort == 'young':
            key = s.age[idx] - o['peak'][idx] / 100
        elif sort == 'fit' and q.get('pos') in POS:
            key = -s.fit[idx, POS.index(q['pos'])]
        elif sort == 'pace':
            key = -np.nan_to_num(s.vs_pred[idx] - s.vs_pred_cohort[idx], nan=-99)
        else:
            key = -o['peak'][idx] - s.ovr[idx] / 100
        idx = idx[np.argsort(key, kind='stable')][:int(q.get('limit', 100))]
        return {'total': int(m.sum()), 'players': [self.summary(i) for i in idx]}


def fold(text):
    import unicodedata
    t = unicodedata.normalize('NFD', text or '').replace('đ', 'd').replace('Đ', 'D')
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn').lower()

"""Decode everything the app shows from one Master League save. Read-only.

Dugout's own reader (package `pes`) decrypts the save and decodes the career player table,
squads, player states, fixtures with line-ups, league tables, rankings and the club screens;
this module adds player skills, playing style and position grades as they stand in the career
(so skills learned in training show up) and lines everything up by player.
"""
import datetime as dt
import os
import time

import numpy as np

from . import config, gameplan, terms
from .pes import career as pc
from .pes import club as pclub
from .pes import container, crypto, world
from .pes import training as ptraining

ML_START = dt.date(2025, 7, 1)   # the database's ages and abilities are the career's starting point


def years_since_start(date):
    return max(0.0, (date - ML_START).days / 365.25)


def _field(R, bit, width):
    byte, shift = bit // 8, bit % 8
    span = (shift + width + 7) // 8
    v = np.zeros(len(R), dtype=np.int64)
    for k in range(span):
        v |= R[:, byte + k].astype(np.int64) << (8 * k)
    return (v >> shift) & ((1 << width) - 1)


def is_national(team_id):
    """PES numbers national teams 1-99 and 1000-1999; clubs use the other ranges."""
    return 0 < team_id < 100 or 1000 <= team_id < 2000


def career_table(inflated):
    """Every occupied row of the career player table."""
    size = pc.RECORD
    ids, cidx, ages, pos, abil, rows, pre = [], [], [], [], [], [], []
    for start, mid, idx in pc.records(inflated):
        rec = inflated[start:start + size]
        ab = pc.abilities(inflated, start)
        if len(ab) != 25:
            continue
        ids.append(pc.snapshot_id(mid, idx))
        cidx.append(idx)
        ages.append(pc.age(rec) or 0)
        p = pc.position(rec)
        pos.append(-1 if p is None else p)
        abil.append([ab[a] for a in terms.ABILITIES])
        rows.append(np.frombuffer(rec, dtype=np.uint8))
        pre.append(np.frombuffer(inflated[start - 8:start], dtype=np.uint8))
    R = np.array(rows, dtype=np.uint8).reshape(-1, size)
    P = np.array(pre, dtype=np.uint8).reshape(-1, 8)          # the 8 bytes before each record
    skills = np.zeros(len(R), dtype=np.uint64)
    for k, s in enumerate(terms.SKILLS):
        skills |= _field(R, s[3], 1).astype(np.uint64) << np.uint64(k)
    style_raw = _field(R, terms.CAREER_STYLE_BIT, 5)
    style = np.array([terms.CAREER_STYLE_TO_DB.get(int(v), 0) for v in style_raw], dtype=np.int8)
    grades = np.full((len(R), 13), -1, dtype=np.int8)
    for p, name in enumerate(terms.POSITIONS):
        if name in terms.CAREER_GRADE_BITS:
            grades[:, p] = _field(R, terms.CAREER_GRADE_BITS[name], 2)
    grades[:, terms.POSITIONS.index('SS')] = (P[:, 7] >> 6) & 3        # bits -2..-1
    grades[:, terms.POSITIONS.index('CF')] = (P[:, 3] >> 6) & 3        # bits -34..-33
    return {'ids': np.array(ids, dtype=np.int64), 'cidx': np.array(cidx, dtype=np.int64),
            'age': np.array(ages, dtype=np.int32), 'position': np.array(pos, dtype=np.int32),
            'abilities': np.array(abil, dtype=np.float32).reshape(-1, 25), 'skills': skills,
            'style': style, 'grades': grades}


class Snapshot:
    """One decoded save. Player arrays are aligned by row; `row` maps player id -> row."""

    def __init__(self, save_path, db):
        t0 = time.time()
        self.save_path = save_path
        self.save_mtime = os.path.getmtime(save_path)
        self.key = config.career_key(save_path)
        data = crypto.read(save_path).data
        table = container.inflate_any(data)
        clocks = pc.clocks(data)
        if clocks:
            self.team_id, c = next(iter(clocks.items()))
            self.clock = c
            self.date = dt.date(c['year'], c['month'], c['day'])
        else:
            self.team_id, self.clock, self.date = 0, None, ML_START

        # ---- every player in the world
        t = career_table(table)
        self.ids, self.cidx, self.age, self.position = t['ids'], t['cidx'], t['age'], t['position']
        self.abilities, self.skills, self.style, self.grades = t['abilities'], t['skills'], t['style'], t['grades']
        self.row = {int(p): i for i, p in enumerate(self.ids)}
        base = np.array([db.index.get(int(p), -1) for p in self.ids])
        ok = base >= 0
        b = np.maximum(base, 0)
        self.base_row = base
        self.height = np.where(ok, db.height[b], 178)
        self.left_foot = np.where(ok, db.left_foot[b], 0)
        self.nation = np.where(ok, db.nation[b], 0)
        self.base_age = np.where(ok, db.age[b], 0)
        self.com = np.where(ok, db.com[b], 0).astype(np.uint8)
        self.grades = np.maximum(self.grades, 0)
        # A regenerated player keeps the database name and face of the retired player.
        self.names = [db.names[i] if i >= 0 and db.names[i] else f'Cầu thủ {p}' for p, i in zip(self.ids, base)]
        elapsed = years_since_start(self.date)
        self.regen = ok & (self.age < self.base_age + np.floor(elapsed) - 1)

        # ---- clubs and who plays where
        club_table = world.clubs(data)
        self.clubs = {tid: (c.name, c.short_name) for tid, c in club_table.items()}
        team_of, national_of, shirt_of = {}, {}, {}
        self.roster, self.gameplans, self.gameplan_raw = {}, {}, {}
        gp_start = pc.gameplan_table_start(data)
        for tid, c in club_table.items():
            try:
                slots = pc.team_squad(data, c.offset)
            except Exception:
                continue
            self.roster[tid] = [int(s['player_id']) for s in slots]
            if not is_national(tid):
                try:
                    plan = gameplan.read(data, gp_start, c.offset, self.roster[tid])
                except Exception:
                    plan = None
                if plan:
                    self.gameplans[tid] = plan
                    self.gameplan_raw[tid] = gameplan.row_bytes(data, gp_start, c.offset)
            for s in slots:
                pid = int(s['player_id'])
                if is_national(tid):
                    national_of[pid] = tid
                    continue
                team_of[pid] = tid
                if s.get('shirt_number'):
                    shirt_of[pid] = int(s['shirt_number'])
        self.team = np.array([team_of.get(int(p), 0) for p in self.ids], dtype=np.int64)
        self.national = np.array([national_of.get(int(p), 0) for p in self.ids], dtype=np.int64)
        self.shirt_of = shirt_of
        self.team_name = self.clubs.get(self.team_id, ('', ''))[0]

        # ---- managed club details (contracts, roles, youth team, deals, club stats...)
        try:
            self.states = pc.player_states(table)
        except Exception:
            self.states = {}
        # condition arrow (0 = E ... 4 = A, -1 unknown), fitness and days out, for every player
        n = len(self.ids)
        self.cond = np.full(n, -1, dtype=np.int8)
        self.stamina = np.full(n, 100, dtype=np.int16)
        self.unavail = np.zeros(n, dtype=np.int16)
        self.contract_end = np.zeros(n, dtype=np.int32)          # yyyymmdd, 0 unknown
        self.salary = np.zeros(n, dtype=np.int64)                # euros a year
        self.weak_accuracy = np.where(ok, db.weak_accuracy[b], 0).astype(np.int8)
        self.weak_usage = np.where(ok, db.weak_usage[b], 0).astype(np.int8)
        for pid, st in self.states.items():
            i = self.row.get(int(pid))
            if i is None:
                continue
            c = st.get('condition')
            if isinstance(c, int) and 0 <= c <= 4 and st.get('form_verified', True):
                self.cond[i] = c
            if isinstance(st.get('stamina'), int):
                self.stamina[i] = st['stamina']
            self.unavail[i] = int(st.get('unavailable_days') or 0)
            y = st.get('contract_end_year')
            if isinstance(y, int) and 2000 < y < 2100:
                self.contract_end[i] = y * 10000 + int(st.get('contract_end_month') or 6) * 100 + int(st.get('contract_end_day') or 30)
            self.salary[i] = int(st.get('annual_salary_raw') or 0)
            if st.get('weak_foot_accuracy'):
                self.weak_accuracy[i] = int(st['weak_foot_accuracy'])
        try:
            own = club_table.get(self.team_id)
            self.club = pclub.snapshot(data, table, self.team_id, own.offset if own else None, self.states)
        except Exception:
            self.club = {}
        self.release_clauses = {int(p['player_id']): p['release_clause'] for p in self.squad_players
                                if p.get('release_clause')}
        for p in self.squad_players:          # the managed squad as the club screen lists it
            i = self.row.get(int(p['player_id']))
            if i is not None:
                self.team[i] = self.team_id
        try:
            self.listed = pc.negotiation_list(table)
        except Exception:
            self.listed = []
        try:
            self.dev = self._individual_training(data, table, club_table)
        except Exception:
            self.dev = {}

        # ---- competitions: every fixture in the world (with both line-ups), tables and rankings
        self.comp_names = config.competition_names()
        fixtures = world.fixtures(data)
        self.fixtures = fixtures                         # the whole world, for the match model
        self.my_fixtures = [f for f in fixtures if self.team_id in (f.home_team, f.away_team)]
        self.my_tournaments = sorted({f.tournament_id for f in self.my_fixtures})
        self.league_fixtures = [f for f in fixtures if f.tournament_id in self.my_tournaments]
        self.regions = {r.tournament_id: r for r in world.regions(data) if r.tournament_id in self.my_tournaments}
        self.ties = {}
        for tid in self.my_tournaments:
            try:
                self.ties[tid] = world.knockout_ties(self.league_fixtures, tid)
            except Exception:
                self.ties[tid] = []
        self.decode_seconds = time.time() - t0

    def _individual_training(self, data, table, club_table):
        """The club's in-game individual training, per player id: {'skills': {skill index: 0..10000},
        'positions': {position index: 0..10000}, 'style': database style trained towards (0 none)}.
        Only what is in progress: a skill part learned, a position between two grades, a style set
        that differs from the current one."""
        own = club_table.get(self.team_id)
        if own is None:
            return {}
        squad = [(int(s['career_index']), int(s['ml_player_id'])) for s in pc.team_squad(data, own.offset)]
        known = {(idx, mid) for _s, mid, idx in pc.records(table)}
        db_to_career = {v: k for k, v in terms.CAREER_STYLE_TO_DB.items()}
        out = {}
        for (cidx, mid), raw in ptraining.read(data, squad, known).items():
            i = self.row.get(pc.snapshot_id(mid, cidx))
            if i is None:
                continue
            skills = {k: v for k, s in enumerate(terms.SKILLS)
                      if 0 < (v := ptraining.skill_value(raw, s[3])) < ptraining.FULL}
            prof = ptraining.positions(raw)
            positions = {terms.POSITIONS.index(p): v for p, v in prof.items()
                         if v % ptraining.GRADE_B and v < ptraining.FULL}
            target = ptraining.style_target(raw, db_to_career.get(int(self.style[i]), 0))
            style = terms.CAREER_STYLE_TO_DB.get(target, 0)
            if skills or positions or style:
                out[int(self.ids[i])] = {'skills': skills, 'positions': positions, 'style': style}
        return out

    # ------------------------------------------------------------------ helpers
    def club_name(self, tid):
        return self.clubs.get(int(tid), ('', ''))[0] if tid else ''

    def comp_name(self, tid):
        return self.comp_names.get(int(tid), f'Giải đấu #{tid}')

    def player_name(self, pid):
        i = self.row.get(int(pid))
        return self.names[i] if i is not None else f'Cầu thủ {pid}'

    @property
    def squad_players(self):
        return self.club.get('players', []) if self.club else []

    @property
    def youth_players(self):
        return self.club.get('youth_team', []) if self.club else []

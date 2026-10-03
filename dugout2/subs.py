"""Substitutions on the live map: who plays in each slot of the two line-ups, and which body on the pitch
is his, through substitutions made from the pause menu or quickly at a dead ball.

What the game does (checked on real matches, FL26):
 - the one going off: his body record is emptied at once (the goalkeeper Guillaume Restes, 77'), or he
   walks to the halfway line and stays just off the touchline (Endrick, same substitution);
 - the one coming on: a body of its own (a new record, or one emptied earlier) that appears on the
   touchline at the halfway line and runs to his place; two who come on together appear there together,
   so at that moment they cannot be told apart (binding the first one seen to the goalkeeper's slot put
   Rasmus Højlund in goal and David Raya up front on the map);
 - his name: the line-ups the game plays with (and the squad lists after a pause-menu change) say who is
   in each slot, but late: Restes and Endrick left at 77', the line-up named David Raya and Rasmus
   Højlund at 83'.
Best of all (game_objects, when found): the game keeps one object per player of the match with his id and
his position (checked on a whole match: within 6 cm of his body); a substitution puts the incoming
player's id in the outgoing one's object at once, a quick one too. Then who each body is, and who came on
for whom, is read, not guessed (the line-ups named the wrong player when a substitution also moved
players to other places: Tiago Gabriel "for Ayden Heaven", in fact for Myles Lewis-Skelly).

Without them: a slot opens when its body goes, walks off, or the line-up names somebody else in it; a body that came
on is bound to an open slot only once it has run towards where that slot plays (relative to its team:
a goalkeeper to his goal, a striker up front) and the choice holds for a moment; bindings made in the
same few minutes are checked again while they play (two newcomers the wrong way round are swapped); the
name comes from the game when it says it (a goalkeeper's slot: the only goalkeeper on the bench is shown
at once, marked as a guess).

Coordinates are the game's: x along the pitch (goals at about +-52.5 m), z across (touchlines +-34 m),
h the height of the followed bone. Pure logic (no memory reading): the tracker feeds it the positions.
"""
import itertools
import math

import numpy as np

EXIT_X, EXIT_Z = 9.0, 33.8          # where the one going off waits: the halfway line, just off the touchline
EXIT_FAR = 35.8                     # well off it (a throw-in is taken on the line: Junior Tchamadeu at 35.1 m)
ON_X, ON_Z = 52.0, 33.5             # on the pitch
READY_AFTER, READY_MOVED, READY_LONG = 2.5, 6.0, 10.0     # a newcomer is judged once he has run a little
MARGIN, HOLD = 6.0, 3               # the best binding must beat the next one by this (m), this many times
LONELY_COST, LONELY_WAIT = 25.0, 20.0   # one newcomer for one slot: still wait if he does not fit at all
RECHECK_SPAN, RECHECK_GAIN = 240.0, 8.0
PROFILE_TIME = 60.0                 # seconds of play the role of a slot is averaged over


class Slot:
    def __init__(self, team, idx, pid, body):
        self.team, self.idx = team, idx
        self.pid = pid              # who plays in it (None: came on, the game has not said who yet)
        self.body = body            # his body (None: open, the newcomer's body not bound yet)
        self.old = body             # the body before (kept while the slot is open)
        self.gen = 0                # substitutions made in this slot
        self.sub = None             # the last one: {'out', 'in', 'clock', 't', 'why'}
        self.prof = None            # (depth, lateral) relative to the team, averaged over play
        self.ref = None             # the role when it opened: where the one coming on should play
        self.guess = None           # a likely name before the game says it
        self.manual = False
        self.bound_at = None


class Newcomer:
    def __init__(self, k, now, x, z, addr=None):
        self.k, self.addr = k, addr
        self.t0 = now
        self.spawn = (x, z)
        self.path = [(now, x, z)]
        self.alive_at = now
        self.entered = abs(z) < ON_Z and abs(x) < ON_X

    def moved(self):
        t, x, z = self.path[-1]
        return math.hypot(x - self.spawn[0], z - self.spawn[1])

    def ready(self, now):
        age = now - self.t0
        return self.entered and age >= READY_AFTER and (self.moved() >= READY_MOVED or age >= READY_LONG)

    def ahead(self, secs=1.5):
        """Where he is going: the position a moment ahead at his recent speed."""
        t1, x1, z1 = self.path[-1]
        old = [p for p in self.path if t1 - p[0] >= 0.8]
        if not old:
            return x1, z1
        t0, x0, z0 = old[-1]
        dt = max(t1 - t0, 1e-3)
        x, z = x1 + (x1 - x0) / dt * secs, z1 + (z1 - z0) / dt * secs
        return max(-ON_X, min(ON_X, x)), max(-ON_Z, min(ON_Z, z))


class SubResolver:
    def __init__(self, pids, bodies, people, bench=None, home_me=True):
        """pids: the 22 ids by slot (home 0-10, away 11-21, each goalkeeper first); bodies: {'home': [k] * 11,
        'away': [k] * 11}; people: id -> {'role', 'team' ('me'/'opp'), 'name'}; bench: {'home': [ids], 'away': [ids]}."""
        self.people = people
        self.side = {'home': 'me' if home_me else 'opp', 'away': 'opp' if home_me else 'me'}
        self.bench = bench or {'home': [], 'away': []}
        self.slots = {}
        for team, base in (('home', 0), ('away', 11)):
            for i in range(11):
                self.slots[(team, i)] = Slot(team, i, pids[base + i], bodies[team][i])
        self.new = {}               # k -> Newcomer: bodies that came on, not bound to a slot yet
        self.leaving = {}           # k -> {'pid', 't'}: the body of one who went off, while he walks
        self.retired = {}           # k -> emptied since it was given up (only then can it come back)
        self.ignored = set()        # bodies that never came onto the pitch (a coach, a ball boy)
        self.gone = set()
        self.events = []            # drained by the tracker
        self.gkx, self.attack = {}, {}
        self.last, self.empty_since, self.still, self.ball_near = {}, {}, {}, {}
        self.rel = {}               # k -> (depth, lateral) relative to his team, averaged over a few seconds
        self.want = 0.0             # a newcomer search is wanted since
        self.eval_at = self.check_at = 0.0
        self.streak = (None, 0)
        self.fix = {}
        self.prev = None
        self.oracle = False         # the game's player objects are read (game_objects): they decide
        self.obj_slot = {}          # object address -> slot key
        self.obj_bad = {}           # slot key -> consecutive reads with its body far from its object
        self.obj_seen = {}          # object address -> last time read fine

    # ------------------------------------------------------------------ state
    @property
    def pids(self):
        return [self.slots[(t, i)].pid for t in ('home', 'away') for i in range(11)]

    def bodies(self, team):
        """The body of each slot; an open slot keeps its old one (records the tracker reads anyway)."""
        return [s.body if s.body is not None else s.old for s in (self.slots[(team, i)] for i in range(11))]

    def set_bodies(self, bodies):
        """The tracker settled who is where (a kick-off, the flanks): the bound slots take these bodies."""
        for team, ks in bodies.items():
            for i, k in enumerate(ks):
                s = self.slots[(team, i)]
                if s.body is not None:
                    s.body = s.old = k

    def open_slots(self):
        return [s for s in self.slots.values() if s.body is None]

    def followed(self, k):
        """Not a newcomer: a body that is somebody's already (or one going off that has not vanished)."""
        if k in self.new or k in self.ignored:
            return True
        if any(s.body == k for s in self.slots.values()):
            return True
        return k in self.retired and not self.retired[k]

    def who(self, k):
        """What a body is now, for the map: {'team', 'pid', 'slot', 'new', 'out', 'guess', 'leaving'} or None."""
        for s in self.slots.values():
            if s.body == k:
                return {'team': s.team, 'slot': s.idx, 'pid': s.pid, 'out': (s.sub or {}).get('out') if s.pid is None else None,
                        'guess': s.guess if s.pid is None else None, 'gen': s.gen}
        if k in self.new:
            teams = {s.team for s in self.open_slots()}
            return {'team': teams.pop() if len(teams) == 1 else None, 'slot': None, 'pid': None, 'new': True,
                    'out': None, 'guess': None}
        if k in self.leaving:
            return {'team': None, 'slot': None, 'pid': self.leaving[k]['pid'], 'leaving': True}
        return None

    # ------------------------------------------------------------------ input
    def add_newcomer(self, k, now, x, z, addr=None):
        if self.followed(k) or k in self.new:
            return False
        self.retired.pop(k, None)
        self.leaving.pop(k, None)
        self.new[k] = Newcomer(k, now, x, z, addr)
        return True

    def bind_known(self, k, pid, now):
        """A newcomer whose body was seen before for this player (Dugout restarted): his slot at once."""
        s = next((s for s in self.slots.values() if s.pid == pid and s.body is None), None)
        if s is None or k not in self.new:
            return None
        return self._bind(s, k, now, 'known')

    def named(self, team, idx, pid_in, now, clock, initial=False):
        """The game says `pid_in` plays in this slot (its line-up, or the squad list)."""
        s = self.slots[(team, idx)]
        if self.oracle and not initial:
            return False                     # the game's player objects say it (game_objects)
        if pid_in is None or pid_in == s.pid or pid_in in self.gone or pid_in in self.pids:
            return False                     # the same; one who went off cannot come back; a stale copy
        if s.pid is None and s.sub:          # came on already (his body may be bound): now his name
            s.pid, s.sub['in'] = pid_in, pid_in
            s.guess = None
            self.events.append({'kind': 'named', 'team': team, 'idx': idx, 'out': s.sub['out'], 'in': pid_in,
                                'clock': s.sub['clock'], 'bound': s.body is not None})
            return True
        self._open(s, now, clock, 'before' if initial else 'named', pid_in=pid_in)
        return True

    def manual(self, k, pid, now, clock):
        """The manager says body k is player `pid` (a tap on the map). -> text"""
        nm = lambda i: (self.people.get(i) or {}).get('name') or str(i)
        s1 = next((s for s in self.slots.values() if s.body == k), None)
        s2 = next((s for s in self.slots.values() if s.pid == pid), None)
        if s1 is not None and s1 is s2:
            s1.manual = True
            return f'Giữ nguyên: đây là {nm(pid)}.'
        if s2 is not None:                   # he plays: his slot takes this body
            if s1 is not None:
                s1.body, s2.body = s2.body, k
                s1.old = s1.body if s1.body is not None else s1.old
                s1.manual = True
            else:
                prev = s2.body
                self.new.pop(k, None)
                self.leaving.pop(k, None)
                s2.body = k
                if prev is not None and prev != k:
                    p = self.last.get(prev)
                    if p:
                        self.new[prev] = Newcomer(prev, now - READY_LONG, p[1], p[2])
            s2.old, s2.manual, s2.bound_at = k, True, now
            return f'Đã sửa: chấm này là {nm(pid)}.'
        team = (self.people.get(pid) or {}).get('team')
        if s1 is None:                       # a newcomer: the open slot of his team
            opens = [s for s in self.open_slots() if self._team_of(s) == team]
            if len(opens) != 1:
                return 'Chưa biết người này vào thay ai: chạm vào cầu thủ vừa ra sân trước.'
            s1 = opens[0]
            self.new.pop(k, None)
            s1.body = s1.old = k
            s1.bound_at = now
        if s1.pid is not None and s1.pid != pid:
            self.gone.add(s1.pid)
            s1.sub = {'out': s1.pid, 'in': pid, 'clock': clock, 't': now, 'why': 'manual'}
        elif s1.sub:
            s1.sub['in'] = pid
        out = (s1.sub or {}).get('out')
        s1.pid, s1.guess, s1.manual = pid, None, True
        self.events.append({'kind': 'named', 'team': s1.team, 'idx': s1.idx, 'out': out, 'in': pid,
                            'clock': (s1.sub or {}).get('clock', clock), 'bound': True, 'manual': True})
        return f'Đã sửa: chấm này là {nm(pid)}' + (f' (vào thay {nm(out)}).' if out else '.')

    def _team_of(self, s):
        return self.side[s.team]

    # ------------------------------------------------------------------ every read
    def step(self, now, P, running, ball=None, clock=None, right=None, frozen=False):
        """P: (x, z, h) of every record followed, by index. `frozen`: the end of a half or of the match (the
        game takes the bodies away and makes new ones: no substitution is read then).
        -> [('bind', team, idx, k)]"""
        acts = []
        n = len(P)
        dt = min(0.5, now - self.prev) if self.prev else 0.05
        self.prev = now

        def alive(k):
            """A person there (lying on the grass too: a tackle); not a record emptied or turned into the
            object the game keeps on the centre spot."""
            if k is None or k >= n:
                return False
            v = P[k]
            if not (np.isfinite(v).all() and v[2] >= 0.05 and abs(v[0]) <= 60 and abs(v[1]) <= 45):
                return False
            return not (abs(v[0]) < 1.6 and abs(v[1]) < 1.6 and v[2] < 1.0)

        # a record handed straight to the one coming on: one body (not many: a replay) jumps to the touchline
        jumps = []
        for s in self.slots.values():
            k = s.body
            if k is not None and alive(k) and k in self.last:
                t, x0, z0 = self.last[k]
                x, z = float(P[k, 0]), float(P[k, 1])
                if now - t < 0.4 and math.hypot(x - x0, z - z0) > 10:
                    jumps.append((s, x, z))
        if not running:
            frozen = True                    # the clock stands: a replay, a celebration (bodies moved then)
            self.empty_since.clear()
        if len(jumps) == 1 and abs(jumps[0][1]) < 12 and abs(jumps[0][2]) > 30 and not frozen:
            s, x, z = jumps[0]
            k = s.body
            self._open(s, now, clock, 'jump')
            self.retired[k] = True
            self.add_newcomer(k, now, x, z)
        for k in list(self.leaving):             # the record of one going off handed to the one coming on
            if alive(k) and k in self.last:
                t, x0, z0 = self.last[k]
                if now - t < 0.4 and math.hypot(float(P[k, 0]) - x0, float(P[k, 1]) - z0) > 10:
                    self.leaving.pop(k)
                    self.retired[k] = True
        for k in set(self.new) | set(self.leaving) | {s.body for s in self.slots.values() if s.body is not None} | set(self.retired):
            if alive(k):
                self.last[k] = (now, float(P[k, 0]), float(P[k, 1]))
            elif k in self.retired:
                self.retired[k] = True       # emptied: the record may be given to somebody else
        # which way each team attacks: away from its goalkeeper
        for team in ('home', 'away'):
            gk = self.slots[(team, 0)]
            if gk.body is not None and alive(gk.body) and running and gk.pid is not None:
                x = float(P[gk.body, 0])
                self.gkx[team] = x if team not in self.gkx else self.gkx[team] + (x - self.gkx[team]) * min(1.0, dt / 8)
                if abs(self.gkx[team]) > 15:
                    self.attack[team] = -1 if self.gkx[team] > 0 else 1
        cen = {team: self._centre(team, P, alive) for team in ('home', 'away')}
        # the role of each slot, while it plays
        for s in self.slots.values():
            k = s.body
            if k is None or not alive(k) or cen[s.team] is None or s.team not in self.attack:
                continue
            x, z = float(P[k, 0]), float(P[k, 1])
            if abs(z) > ON_Z + 1 or abs(x) > ON_X + 1:
                continue
            rel = self._rel(s.team, x, z, cen)
            r = self.rel.get(k)
            self.rel[k] = rel if r is None else (r[0] + (rel[0] - r[0]) * min(1.0, dt / 8), r[1] + (rel[1] - r[1]) * min(1.0, dt / 8))
            if running and s.pid is not None and (s.bound_at is None or now - s.bound_at > 90 or s.manual):
                p = s.prof
                a = min(1.0, dt / PROFILE_TIME)
                s.prof = rel if p is None else (p[0] + (rel[0] - p[0]) * a, p[1] + (rel[1] - p[1]) * a)
        # a slot opens: its body went, or walked off at the halfway line
        for s in list(self.slots.values()):
            k = s.body
            if k is None or frozen:
                continue
            if not alive(k):
                t0 = self.empty_since.setdefault(k, now)
                if now - t0 >= 0.5:
                    self._open(s, now, clock, 'gone', right=right)
                continue
            self.empty_since.pop(k, None)
            x, z = float(P[k, 0]), float(P[k, 1])
            if ball is None or math.hypot(ball[0] - x, ball[1] - z) <= 4:
                self.ball_near[k] = now            # the ball with him (or not seen): a throw-in maybe
            if abs(x) < EXIT_X and abs(z) > EXIT_Z:
                st = self.still.get(k)
                if st is None or math.hypot(x - st[1], z - st[2]) > 0.5:
                    self.still[k] = (now, x, z)
                elif now - st[0] >= 2.0 and (abs(z) > EXIT_FAR or now - self.ball_near.get(k, 0) >= 2.0):
                    self._open(s, now, clock, 'off', right=right)      # not a throw-in: no ball with him
            else:
                self.still.pop(k, None)
        # the one going off came back (treatment off the pitch, not a substitution): his slot again
        for s in self.slots.values():
            if s.body is None and s.sub and s.sub.get('why') == 'off' and s.pid is None and s.old in self.leaving:
                k = s.old
                if alive(k) and abs(float(P[k, 1])) < ON_Z - 1 and now - s.sub['t'] < 120:
                    self.leaving.pop(k, None)
                    self.retired.pop(k, None)
                    s.body, s.pid = k, s.sub['out']
                    self.gone.discard(s.pid)
                    self.events.append({'kind': 'back', 'team': s.team, 'idx': s.idx, 'pid': s.pid, 'clock': clock})
                    s.sub = None
                    acts.append(('bind', s.team, s.idx, k))
        # newcomers: where they run
        for k, nw in list(self.new.items()):
            if alive(k):
                x, z = float(P[k, 0]), float(P[k, 1])
                nw.path.append((now, x, z))
                nw.path = [p for p in nw.path if now - p[0] <= 4.0]
                nw.alive_at = now
                nw.entered = nw.entered or (abs(z) < ON_Z and abs(x) < ON_X)
            elif now - nw.alive_at > 2.0:
                del self.new[k]
                continue
            if not nw.entered and now - nw.t0 > 90:
                del self.new[k]
                self.ignored.add(k)
        for k in [k for k, v in self.leaving.items() if now - v['t'] > 180 or not alive(k)]:
            del self.leaving[k]
        # who came on for whom
        opens = self.open_slots()
        ready = [nw for nw in self.new.values() if nw.ready(now)]
        if opens and ready and now - self.eval_at >= 0.5 and not frozen:
            self.eval_at = now
            ranked = self._rank(opens, ready, cen)
            if ranked:
                best = ranked[0]
                key = tuple(sorted((s.team, s.idx, nw.k) for s, nw in best[1]))
                margin = ranked[1][0] - best[0] if len(ranked) > 1 else math.inf
                worst = max(c for c in best[2]) if best[2] else 0.0
                waited = min(now - nw.t0 for _, nw in best[1])
                ok = margin >= MARGIN and (worst <= LONELY_COST or waited >= LONELY_WAIT)
                held = self.streak[1] + 1 if ok and key == self.streak[0] else (1 if ok else 0)
                self.streak = (key, held)
                if held >= HOLD or waited >= 30:
                    for s, nw in best[1]:
                        acts.append(self._bind(s, nw.k, now, 'sure' if held >= HOLD else 'best guess'))
                    self.streak = (None, 0)
        # bindings of the last minutes, checked again while they play
        if now - self.check_at >= 1.0 and not frozen and not self.oracle:
            self.check_at = now
            acts += self._recheck(now, cen)
        return acts

    # ------------------------------------------------------------------ the game's own player objects
    def game_objects(self, objs, P, now, clock, frozen=False, running=True):
        """objs: [(address, player id, x, z)] read from the game's player objects together with P.
        Who plays in each slot and which body is his. An object is trusted once it has run with its
        player's body (5 m within 0.6 m of it: the game keeps still copies too, taken at a dead ball they
        look the same); nothing is decided while the clock stands (a replay moves the bodies, not the
        objects) or when many bodies disagree at once. -> [('bind', team, idx, k)]"""
        acts = []
        n = len(P)
        if frozen or not running:
            return acts

        def pos(k):
            if k is None or k >= n or not np.isfinite(P[k]).all() or P[k, 2] < 0.05:
                return None
            return float(P[k, 0]), float(P[k, 1])
        info = self.__dict__.setdefault('obj_info', {})
        drop = []
        live = {}
        for a, pid, x, z in objs:
            self.obj_seen[a] = now
            o = info.setdefault(a, {'pid': pid, 'ok': False, 'moved': 0.0, 'bad': 0, 'last': (x, z)})
            moved = math.hypot(x - o['last'][0], z - o['last'][1])
            o['last'] = (x, z)
            if not o['ok']:                      # not trusted yet: does it run with its player's body?
                s = next((s for s in self.slots.values() if s.pid == pid), None)
                q = pos(s.body) if s else None
                if q is None:
                    continue
                if math.hypot(q[0] - x, q[1] - z) < 0.6:
                    o['moved'] += moved
                    o['bad'] = 0
                    if o['moved'] >= 5.0 and (s.team, s.idx) not in self.obj_slot.values():
                        o['ok'] = True
                        self.obj_slot[a] = (s.team, s.idx)
                elif math.hypot(q[0] - x, q[1] - z) > 2.0:
                    o['bad'] += 1
                    if o['bad'] >= 12:           # a still copy: not his
                        drop.append(a)
                continue
            key = self.obj_slot.get(a)
            if key is not None:
                live[key] = (a, pid, x, z)
        for a in drop:
            info.pop(a, None)
        self.dropped = getattr(self, 'dropped', []) + drop
        self.oracle = len(live) >= 15
        if not self.oracle:
            return acts
        # many bodies away from their objects at once: a scene of the game, not a mistake of Dugout
        far = 0
        for key, (a, pid, x, z) in live.items():
            q = pos(self.slots[key].body)
            if self.slots[key].pid == pid and q is not None and math.hypot(q[0] - x, q[1] - z) > 2.5:
                far += 1
        if far >= 3:
            self.obj_bad.clear()
            return acts
        for key, (a, pid, x, z) in live.items():
            s = self.slots[key]
            if s.pid is None and s.sub and pid == s.sub.get('out'):
                # the game still has him in this slot: he never went off (Dugout took a moment of the game
                # for it: O'Hare and Karl "went off" at 59' and 66', they played on until 75')
                s.pid, s.guess = pid, None
                self.gone.discard(pid)
                self.leaving.pop(s.old, None)
                self.events.append({'kind': 'back', 'team': s.team, 'idx': s.idx, 'pid': pid, 'clock': clock,
                                    'out': pid, 'key_out': pid})
                s.sub = None
            if pid != s.pid and pid not in self.gone:
                if s.pid is None and s.sub:              # came on already: now his name
                    s.pid, s.sub['in'], s.guess = pid, pid, None
                    self.events.append({'kind': 'named', 'team': s.team, 'idx': s.idx, 'out': s.sub['out'], 'in': pid,
                                        'clock': s.sub['clock'], 'bound': s.body is not None, 'game': True})
                elif s.pid is not None:                  # a substitution: his id in the one going off's object
                    self._open(s, now, clock, 'game', pid_in=pid)
            q = pos(s.body)
            if s.body is not None and q is not None and math.hypot(q[0] - x, q[1] - z) <= 2.5:
                self.obj_bad[key] = 0
                continue
            self.obj_bad[key] = self.obj_bad.get(key, 0) + 1
            if s.body is not None and self.obj_bad[key] < 8:
                continue                             # two seconds apart before anything is changed
            best = None
            for k in list(self.new) + [s2.body for s2 in self.slots.values() if s2.body is not None and s2 is not s]:
                qk = pos(k)
                if qk is None:
                    continue
                d = math.hypot(qk[0] - x, qk[1] - z)
                if d < 1.0 and (best is None or d < best[0]):
                    best = (d, k)
            if best is None:
                if s.body is None:
                    self.want = now                  # his body is not followed yet: look for it
                continue
            k = best[1]
            other = next((s2 for s2 in self.slots.values() if s2.body == k), None)
            if other is not None:
                continue                             # it is somebody else's: his own check will settle it
            self.new.pop(k, None)
            self.leaving.pop(k, None)
            fresh = s.body is None
            prev = s.body
            if prev is not None and pos(prev):
                p0 = pos(prev)
                self.new[prev] = Newcomer(prev, now - READY_LONG, p0[0], p0[1])
            s.body = s.old = k
            s.bound_at = now
            self.obj_bad[key] = 0
            if fresh and s.sub:
                s.gen += 1
                self.events.append({'kind': 'in', 'team': s.team, 'idx': s.idx, 'k': k, 'out': s.sub.get('out'),
                                    'in': s.pid, 'guess': None, 'clock': s.sub.get('clock'), 'how': 'game'})
            else:
                self.events.append({'kind': 'fix', 'team': s.team, 'idx': s.idx, 'k': k, 'pid': s.pid,
                                    'out': (s.sub or {}).get('out'), 'game': True})
            acts.append(('bind', s.team, s.idx, k))
        # an object the game no longer keeps: found again (the game moved it)
        for a, key in list(self.obj_slot.items()):
            if now - self.obj_seen.get(a, now) > 5:
                del self.obj_slot[a]
                info.pop(a, None)
                s = self.slots[key]
                self.events.append({'kind': 'lost', 'team': s.team, 'idx': s.idx, 'pid': s.pid, 'clock': clock})
        return acts

    # ------------------------------------------------------------------ helpers
    def _centre(self, team, P, alive):
        pts = []
        for i in range(1, 11):
            k = self.slots[(team, i)].body
            if k is not None and alive(k) and abs(P[k, 1]) <= ON_Z + 1 and abs(P[k, 0]) <= ON_X + 1:
                pts.append((float(P[k, 0]), float(P[k, 1])))
        if len(pts) < 5:
            return None
        return float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))

    def _rel(self, team, x, z, cen):
        att = self.attack.get(team, 1)
        c = cen.get(team) or (0.0, 0.0)
        return (x - c[0]) * att, (z - c[1]) * att

    def _fallback(self, s, right=None):
        """The role of a slot never seen playing: its usual place (goalkeeper deep, the others by position)."""
        role = (self.people.get(s.pid) or {}).get('role', '')
        if s.idx == 0 or role == 'GK':
            return (-32.0, 0.0)
        depth = {'CB': -12, 'LB': -10, 'RB': -10, 'DMF': -5, 'CMF': 0, 'LMF': 4, 'RMF': 4, 'AMF': 6,
                 'LWF': 12, 'RWF': 12, 'SS': 12, 'CF': 16}.get(role, 0)
        lat = {'LB': -18, 'LMF': -18, 'LWF': -16, 'RB': 18, 'RMF': 18, 'RWF': 16}.get(role, 0)
        rs = (right or {}).get(s.team)
        att = self.attack.get(s.team, 1)
        return float(depth), float(lat * rs * att) if rs else 0.0

    def _cost(self, s, nw, cen):
        if s.ref is None:
            return 20.0
        x, z = nw.ahead()
        rel = self._rel(s.team, x, z, cen)
        return math.hypot(rel[0] - s.ref[0], 0.8 * (rel[1] - s.ref[1]))

    def _rank(self, opens, ready, cen):
        opens, ready = opens[:6], ready[:6]
        C = {(id(s), nw.k): self._cost(s, nw, cen) for s in opens for nw in ready}
        out = []
        if len(ready) >= len(opens):
            for perm in itertools.permutations(ready, len(opens)):
                pairs = list(zip(opens, perm))
                cs = [C[(id(s), nw.k)] for s, nw in pairs]
                out.append((sum(cs), pairs, cs))
        else:
            for perm in itertools.permutations(opens, len(ready)):
                pairs = list(zip(perm, ready))
                cs = [C[(id(s), nw.k)] for s, nw in pairs]
                out.append((sum(cs), pairs, cs))
        out.sort(key=lambda t: t[0])
        return out

    def _open(self, s, now, clock, why, right=None, pid_in=None):
        out = s.pid
        s.sub = {'out': out, 'in': pid_in, 'clock': clock, 't': now, 'why': why}
        if s.ref is None or why != 'jump':
            s.ref = s.prof if s.prof is not None else self._fallback(s, right)
        if s.body is not None:
            s.old = s.body
        k = s.old
        s.body = None
        s.pid = pid_in
        if out is not None:
            self.gone.add(out)
        if k is not None and why in ('off', 'named', 'game'):
            self.leaving[k] = {'pid': out, 't': now}
        if k is not None:
            self.retired[k] = why in ('gone', 'before')
        s.guess = self._guess(s) if pid_in is None else None
        s.manual = False
        self.want = now
        self.events.append({'kind': 'out', 'team': s.team, 'idx': s.idx, 'out': out, 'in': pid_in, 'clock': clock,
                            'why': why, 'guess': s.guess})

    def _guess(self, s):
        """The goalkeeper's slot: the only goalkeeper left on the bench."""
        out_role = (self.people.get((s.sub or {}).get('out')) or {}).get('role')
        if s.idx != 0 and out_role != 'GK':
            return None
        on = set(self.pids)
        gks = [i for i in self.bench.get(s.team, []) if (self.people.get(i) or {}).get('role') == 'GK'
               and i not in self.gone and i not in on]
        if getattr(self, 'bench_ordered', False):
            return gks[0] if gks else None       # the game's own order: the substitutes first
        return gks[0] if len(gks) == 1 else None

    def _bind(self, s, k, now, how):
        self.new.pop(k, None)
        self.leaving.pop(k, None)
        s.body = s.old = k
        s.bound_at = now
        s.gen += 1
        self.events.append({'kind': 'in', 'team': s.team, 'idx': s.idx, 'k': k, 'out': (s.sub or {}).get('out'),
                            'in': s.pid, 'guess': s.guess, 'clock': (s.sub or {}).get('clock'), 'how': how})
        return ('bind', s.team, s.idx, k)

    def _recheck(self, now, cen):
        """Newcomers bound in the last minutes: the other way round if they clearly play each other's role
        (held for a few checks); a newcomer still waiting who plays a just-bound slot's role far better
        takes it (the one bound before waits again)."""
        acts = []
        for team in ('home', 'away'):
            recent = [s for s in self.slots.values() if s.team == team and s.body is not None and s.bound_at
                      and now - s.bound_at < RECHECK_SPAN and not s.manual and s.ref is not None]
            if not recent:
                continue
            ks = [s.body for s in recent if s.body in self.rel]
            if len(ks) != len(recent):
                continue
            cost = lambda s, k: math.hypot(self.rel[k][0] - s.ref[0], 0.8 * (self.rel[k][1] - s.ref[1]))
            fixes = []
            if len(recent) >= 2:
                cur = sum(cost(s, s.body) for s in recent)
                best = min(itertools.permutations(ks), key=lambda p: sum(cost(s, k) for s, k in zip(recent, p)))
                gain = cur - sum(cost(s, k) for s, k in zip(recent, best))
                changed = sum(1 for s, k in zip(recent, best) if s.body != k)
                if changed and gain >= RECHECK_GAIN * changed:
                    fixes = [(s, k) for s, k in zip(recent, best) if s.body != k]
            for nw in self.new.values():     # a newcomer waiting who fits a recent slot far better
                if fixes or not nw.ready(now):
                    continue
                same = [s for s in recent if s.sub and abs(nw.t0 - s.sub['t']) < 90]   # came on at that time
                if not same:
                    continue
                c_new = {id(s): self._cost(s, nw, cen) for s in same}
                s = min(same, key=lambda s: c_new[id(s)])
                if c_new[id(s)] + 2 * RECHECK_GAIN < cost(s, s.body):
                    fixes = [(s, nw.k)]
            key = tuple(sorted((s.idx, k) for s, k in fixes))
            if not fixes:
                self.fix.pop(team, None)
                continue
            n = self.fix.get(team, (None, 0))
            n = (key, n[1] + 1 if n[0] == key else 1)
            self.fix[team] = n
            if n[1] < 3:
                continue
            self.fix.pop(team, None)
            for s, k in fixes:
                prev = s.body
                if k in self.new:                # the one bound before waits again for his slot
                    self.new.pop(k)
                    p = self.last.get(prev)
                    if prev is not None and p:
                        self.new[prev] = Newcomer(prev, now - READY_LONG, p[1], p[2])
                s.body = s.old = k
                s.bound_at = now
                acts.append(('bind', s.team, s.idx, k))
                self.events.append({'kind': 'fix', 'team': s.team, 'idx': s.idx, 'k': k, 'pid': s.pid,
                                    'out': (s.sub or {}).get('out')})
        return acts

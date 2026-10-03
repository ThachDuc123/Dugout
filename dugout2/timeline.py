"""What happened in the match, read from the live map: kick-off, half time, goals (who scored, who passed
to him), shots, substitutions, the end; passes and balls won counted for each team and player.

The ball and who has it say it (matchlive: the nearest player within 1.3 m of the ball on the ground):
 - a pass: the ball goes from one player to a team-mate (counted when the second one has it);
 - a ball won: it goes from a player to an opponent (a tackle, an interception);
 - a shot: the ball struck fast (15 m/s or more) towards a goal it would reach within two seconds, near
   the posts, last touched by a player of the team attacking that goal; on target when it would cross
   the line between the posts and under the bar;
 - a goal: the score changes; the scorer is the one who shot (else the last of that team with the
   ball), the assist the team-mate whose pass he had.
Map coordinates: our team attacks towards +x, the goals at x = +-52.5 m, the posts at y = +-3.66 m.
Cards and fouls are not read from the game yet.
"""
import collections
import math

HALF_L, POST, BAR = 52.5, 3.66, 2.44
SHOT_SPEED, SHOT_REACH, SHOT_WIDE, SHOT_FAR = 15.0, 2.0, 9.0, 35.0
HOLD = 0.2                       # seconds with the ball before he counts as having it
PASS_GAP = 6.0                   # seconds the ball may travel between two players


def gmin(clock):
    return f"{int(clock // 60) + 1}'" if clock is not None else ''


def _blank():
    return {'passes': 0, 'won': 0, 'lost': 0, 'shots': 0, 'on_target': 0, 'goals': 0}


class Timeline:
    def __init__(self, people):
        """people: id -> {'name', 'num', 'team' ('me'/'opp')}"""
        self.people = people
        self.items = []
        self.next_id = 1
        self.team = {'me': _blank(), 'opp': _blank()}
        self.player = {}
        self.holder = None          # {'pid', 'team', 'k', 'at', 'clock'}: the last one with the ball (confirmed)
        self.cand = None            # (k, since)
        self.last_pass = None       # (from, to, team, now, clock)
        self.ball = collections.deque(maxlen=12)
        self.shot = None            # the last shot: {'id', 'pid', 'team', 'now', 'clock'}
        self.pending = None         # a strike not yet known to be a shot
        self.period_new = None      # (period, clock) a period that has not run yet
        self.score = None
        self.period = None
        self.started = False
        self.last_clock = None
        # who scored, from the ball itself: the touches before it, the moment it went in (the score the game
        # reports comes 5.5-7 s later, after the celebration: the one "with the ball" then was the keeper fetching
        # it or nobody, 7 of 12 goals unnamed); the rule to name the scorer is learnt after each match against the
        # save (events.fix_live_logs -> scorer_rules)
        self.touches = collections.deque(maxlen=40)   # (now, pid, team, dist, h)
        self.cross = None                             # {'now', 'team', 'touches'}: the ball in a goal mouth
        self.rules = ['team_last', 'shot', 'last']
        self.subs = {}              # substitution key -> item id
        self.changed = 0
        self.dirty = []             # items made or changed since the last drain (for the recording)

    # ------------------------------------------------------------------ items
    def _name(self, pid):
        p = self.people.get(pid) or {}
        return p.get('name') or 'Cầu thủ'

    def _label(self, pid):
        p = self.people.get(pid) or {}
        return f"{p.get('name')} ({p['num']})" if p.get('num') is not None and p.get('name') else self._name(pid)

    def add(self, kind, clock, text, team=None, **data):
        item = {'id': self.next_id, 'kind': kind, 't': clock, 'min': gmin(clock), 'team': team, 'text': text, **data}
        self.next_id += 1
        self.items.append(item)
        self.items.sort(key=lambda i: (i['t'] if i['t'] is not None else -1, i['id']))
        self.changed += 1
        self.dirty.append(item['id'])
        return item

    def update(self, iid, **kv):
        for it in self.items:
            if it['id'] == iid:
                it.update(kv)
                self.changed += 1
                self.dirty.append(iid)
                return it
        return None

    def ps(self, pid):
        return self.player.setdefault(pid, _blank() | {'received': 0})

    def restore(self, items):
        """Items written before (Dugout restarted in the same match)."""
        for it in items:
            if it.get('deleted'):
                continue
            it = {k: v for k, v in it.items() if k not in ('t_rec', 'c', 'kind_rec')}
            self.items.append(it)
            self.next_id = max(self.next_id, int(it.get('id') or 0) + 1)
            if it.get('kind') == 'sub' and it.get('key'):
                self.subs[it['key']] = it['id']
        self.items.sort(key=lambda i: (i['t'] if i['t'] is not None else -1, i['id']))
        if self.items:
            self.started = True

    # ------------------------------------------------------------------ substitutions (from matchlive)
    def sub(self, key, clock, team, out, inn, guess=None, before=False):
        who = 'Bạn' if team == 'me' else 'Đối thủ'
        if inn:
            text = f'{who} thay người: {self._label(inn)} vào, {self._label(out)} ra' + (' (trước khi Dugout theo dõi).' if before else '.')
        elif guess:
            text = f'{who} thay người: {self._label(out)} ra, có lẽ {self._label(guess)} vào (game chưa báo tên).'
        else:
            text = f'{who} thay người: {self._label(out)} ra (game chưa báo tên người vào).'
        iid = self.subs.get(key)
        if iid is not None:
            return self.update(iid, text=text, inn=inn, out=out)
        it = self.add('sub', clock, text, team=team, out=out, inn=inn, key=key)
        self.subs[key] = it['id']
        return it

    def unsub(self, key):
        """A substitution that was not one (the player is still on): its line goes."""
        iid = self.subs.pop(key, None)
        if iid is None:
            return
        self.items = [i for i in self.items if i['id'] != iid]
        self.changed += 1
        self.gone_ids = getattr(self, 'gone_ids', []) + [iid]

    def drain(self):
        ids, self.dirty = self.dirty, []
        out = [it for it in self.items if it['id'] in set(ids)]
        for iid in getattr(self, 'gone_ids', []):
            out.append({'id': iid, 'deleted': True})
        self.gone_ids = []
        return out

    def end(self, clock, score):
        if not self.started:
            return None
        return self.add('end', clock, f'Hết trận {score[0]}–{score[1]}.' if score and None not in score else 'Hết trận.')

    # ------------------------------------------------------------------ every frame
    def feed(self, now, clock, period, score, running, players, ball, carrier, home_me=True):
        """players: map players [{'k', 'id', 'team', 'x', 'y'}]; ball: {'x', 'y', 'h'} or None; carrier: from
        matchlive (state 'held' with 'k', 'id', 'team'). -> new items"""
        new = []
        if clock is None:
            return new
        if not self.started and running:
            self.started = True
            new.append(self.add('start', clock, 'Bắt đầu trận.' if clock < 120 else 'Dugout bắt đầu theo dõi trận.'))
        if period != self.period:
            if self.period is not None and period and self.started:
                if self.period == 1 and period == 2:
                    new.append(self.add('period', self.last_clock, 'Hết hiệp 1.'))
                self.period_new = (period, clock)     # said once its clock runs (the final whistle sets the next
            self.period = period                      # period too: no 'extra time' after a match that ended)
        pn = self.period_new
        if pn and pn[0] == period and running and clock >= pn[1] + 5:
            self.period_new = None
            new.append(self.add('period', pn[1], {2: 'Bắt đầu hiệp 2.', 3: 'Bắt đầu hiệp phụ thứ nhất.',
                                                  4: 'Bắt đầu hiệp phụ thứ hai.', 5: 'Đá luân lưu.'}.get(period, 'Hiệp mới.')))
        self.last_clock = clock
        if score and None not in score:
            if self.score is not None and list(score) != list(self.score):
                for side in (0, 1):
                    for _ in range(max(0, score[side] - self.score[side])):
                        team = ('me' if (side == 0) == home_me else 'opp')
                        new.append(self._goal(now, clock, team, score, home_me))
                self.holder, self.last_pass, self.pending = None, None, None    # a kick-off follows
            self.score = list(score)
        if ball is not None:
            self.ball.append((now, ball['x'], ball['y'], ball['h']))
        if not running:
            self.cand = None
            return new
        if ball is not None:
            self._touch(now, players, ball)
        self._holders(now, clock, carrier)
        s = self._shot(now, clock)
        if s:
            new.append(s)
        return new

    def _touch(self, now, players, ball):
        """Who touches the ball (the nearest player within 1.6 m of it on the ground, 2.4 m in the air up to a
        header's height), and the moment it goes into a goal mouth (ours on the left of the map)."""
        x, y, h = ball['x'], ball['y'], ball['h']
        best = None
        for p in players:
            if p.get('team') not in ('me', 'opp') or not p.get('id'):
                continue
            d = math.hypot(p['x'] - x, p['y'] - y)
            if best is None or d < best[0]:
                best = (d, p)
        if best and (best[0] <= 1.6 and h < 1.2 or best[0] <= 2.4 and h < 2.6):
            d, p = best
            if self.touches and self.touches[-1][1] == p['id']:
                self.touches[-1] = (now, p['id'], p['team'], round(d, 2), round(h, 2))
            else:
                self.touches.append((now, p['id'], p['team'], round(d, 2), round(h, 2)))
        if abs(x) > HALF_L - 0.1 and abs(y) < POST + 0.15 and h < BAR + 0.2 and                 not (self.cross and now - self.cross['now'] < 20):
            self.cross = {'now': now, 'team': 'me' if x > 0 else 'opp',
                          'touches': [list(t) for t in self.touches if now - t[0] <= 8]}

    def _pick(self, team):
        """The scorer by the rules in the order learnt: 'team_last' (the scoring side's last touch before the ball
        went in: a keeper's or a defender's touch on the way is a save that failed), 'last' (the last touch of
        anyone: an own goal if of the other side), 'shot' (the strike seen). -> (pid, own, rule, candidates)"""
        c = self.cross if self.cross and self.cross['team'] == team else None
        cands = [[t[1], t[2], round(c['now'] - t[0], 2), t[3], t[4]] for t in c['touches']] if c else []
        shot = self.shot['pid'] if self.shot and self.shot['team'] == team else None
        for rule in self.rules:
            if rule == 'team_last' and c:
                mine = [t for t in c['touches'] if t[2] == team and c['now'] - t[0] <= 6]
                if mine:
                    return mine[-1][1], False, rule, cands
            elif rule == 'last' and c and c['touches']:
                t = c['touches'][-1]
                return t[1], t[2] != team, rule, cands
            elif rule == 'shot' and shot:
                return shot, False, rule, cands
        return None, False, None, cands

    def _holders(self, now, clock, carrier):
        if not carrier or carrier.get('state') != 'held' or not carrier.get('id'):
            self.cand = None
            return
        k = carrier.get('k')
        if self.cand is None or self.cand[0] != k:
            self.cand = (k, now)
            return
        if now - self.cand[1] < HOLD:
            return
        pid, team = carrier['id'], carrier.get('team')
        h = self.holder
        if h and h['pid'] == pid:
            h['at'] = now
            return
        if h and now - h['at'] <= PASS_GAP and team in ('me', 'opp') and h['team'] in ('me', 'opp'):
            if team == h['team']:
                self.team[team]['passes'] += 1
                self.ps(h['pid'])['passes'] += 1
                self.ps(pid)['received'] += 1
                self.last_pass = (h['pid'], pid, team, now, clock)
            else:
                self.team[team]['won'] += 1
                self.team[h['team']]['lost'] += 1
                self.ps(pid)['won'] += 1
                self.ps(h['pid'])['lost'] += 1
            self.changed += 1
        self.holder = {'pid': pid, 'team': team, 'k': k, 'at': now, 'clock': clock}

    def _shot(self, now, clock):
        """A strike towards a goal: kept pending until the ball says what it was (a through ball that a
        team-mate takes is a pass, not a shot)."""
        if self.pending is not None:
            return self._settle(now, clock)
        if len(self.ball) < 4:
            return None
        t1, x1, y1, h1 = self.ball[-1]
        old = [b for b in self.ball if 0.1 <= t1 - b[0] <= 0.35]
        if not old:
            return None
        t0, x0, y0, h0 = old[-1]
        dt = t1 - t0
        vx, vy, vh = (x1 - x0) / dt, (y1 - y0) / dt, (h1 - h0) / dt
        if math.hypot(vx, vy) < SHOT_SPEED or abs(vx) < 1e-3:
            return None
        goal = HALF_L if vx > 0 else -HALF_L
        attacker = 'me' if goal > 0 else 'opp'
        reach = (goal - x1) / vx
        if not (0 < reach <= SHOT_REACH) or abs(goal - x1) > SHOT_FAR:
            return None
        y_cross = y1 + vy * reach
        h_cross = h1 + vh * reach - 4.9 * reach * reach
        if abs(y_cross) > SHOT_WIDE or h_cross > 6.0:
            return None
        h = self.holder
        if not h or h['team'] != attacker or now - h['at'] > 1.2:
            return None                      # a clearance, a pass back, a deflection
        if self.shot and now - self.shot['now'] < 2.5:
            return None
        on = abs(y_cross) <= POST + 0.2 and -0.5 <= h_cross <= BAR + 0.3
        self.pending = {'pid': h['pid'], 'team': attacker, 'goal': goal, 'now': now, 'clock': clock, 'on': on,
                        'closest': abs(goal - x1)}
        return None

    def _settle(self, now, clock, scored=False):
        """What a strike was: a shot (in, wide, saved, blocked) or a pass after all."""
        p = self.pending
        _, x1, y1, h1 = self.ball[-1] if self.ball else (now, 0.0, 0.0, 0.0)
        p['closest'] = min(p['closest'], abs(p['goal'] - x1))
        h = self.holder
        took = h if h and h['pid'] != p['pid'] and h['at'] > p['now'] + 0.05 else None
        how = None
        if scored:
            how = 'goal'
        elif p['closest'] <= 1.0:                     # at the goal line: in, wide or over
            p['on'] = abs(y1) <= POST + 0.2 and h1 <= BAR + 0.3
            how = 'line'
        elif took and took['team'] == p['team']:
            how = 'pass'                              # a team-mate took it: a pass, a cross
        elif took:
            how = 'stopped' if p['closest'] <= 16.5 else 'pass'
        elif now - p['now'] > 3.0:
            how = 'stopped' if p['closest'] <= 16.5 else 'pass'
        if how is None:
            return None
        self.pending = None
        if how == 'pass':
            return None
        on = p['on'] or how == 'goal'
        keeper = bool(took) and (self.people.get(took['pid']) or {}).get('role') == 'GK'
        if how == 'stopped' and took and not keeper:
            on, what = False, 'bị chặn'
        elif how == 'stopped' and keeper:
            on, what = True, 'thủ môn cản phá'
        else:
            what = 'trúng đích' if on else 'chệch khung thành'
        st = self.team[p['team']]
        st['shots'] += 1
        st['on_target'] += 1 if on else 0
        ps = self.ps(p['pid'])
        ps['shots'] += 1
        ps['on_target'] = ps.get('on_target', 0) + (1 if on else 0)
        it = self.add('shot', p['clock'], f"{self._label(p['pid'])} sút: {what}.", team=p['team'], pid=p['pid'],
                      on_target=on)
        self.shot = {'id': it['id'], 'pid': p['pid'], 'team': p['team'], 'now': p['now'], 'clock': p['clock']}
        return it

    def _goal(self, now, clock, team, score, home_me):
        st = self.team[team]
        st['goals'] += 1
        scorer, own, how = None, False, ''
        if self.pending is not None and self.pending['team'] == team:
            self._settle(now, clock, scored=True)
        rule, cands = None, []
        if self.cross and now - self.cross['now'] <= 15:
            scorer, own, rule, cands = self._pick(team)    # the ball went in a moment ago: its touches say who
        if scorer is None and self.shot and self.shot['team'] == team and now - self.shot['now'] <= 15:
            scorer, rule = self.shot['pid'], 'shot'
        elif scorer is None and self.holder and now - self.holder['at'] <= 10:
            scorer = self.holder['pid']
            own = self.holder['team'] != team
            rule = 'holder'
        if scorer and self.shot and self.shot['pid'] == scorer and now - self.shot['now'] <= 15:
            self.update(self.shot['id'], text=f'{self._label(scorer)} sút: VÀO!', goal=True)
        self.cross = None
        assist = None
        lp = self.last_pass
        if scorer and not own and lp and lp[1] == scorer and lp[2] == team and now - lp[3] <= 15:
            assist = lp[0]
        if scorer and not own:
            self.ps(scorer)['goals'] += 1
            how = f'{self._label(scorer)} ghi bàn' + (f' (kiến tạo: {self._label(assist)})' if assist else '')
        elif scorer and own:
            how = f'có thể là phản lưới nhà ({self._label(scorer)} chạm bóng cuối)'
        else:
            how = 'bàn thắng'
        who = 'Bạn' if team == 'me' else 'Đối thủ'
        return self.add('goal', clock, f'{who}: {how}. Tỉ số {score[0]}–{score[1]}.', team=team, scorer=scorer,
                        assist=assist, score=list(score), own=own, rule=rule, cands=cands,
                        shot_pid=self.shot['pid'] if self.shot and self.shot['team'] == team else None)

    def stats(self):
        return {t: dict(v) for t, v in self.team.items()}

    def recent(self, n=40):
        return list(reversed(self.items[-n:]))

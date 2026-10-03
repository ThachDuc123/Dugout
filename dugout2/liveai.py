"""Live Tactical AI: what the positions of both teams show during the match, in a manager's words.

matchlive feeds it the map twice a second (our team attacks towards +x, our right side is +y, metres
from the centre spot) with the game clock, the score and who is who. From the last minutes of play
it measures: the shape and the height of the block of each team (with and without the ball), where
the ball goes in each third (which flank is attacked), who is isolated, gaps between the lines, how
much everybody runs and how tired they probably are; it compares that with the pre-match analysis
(threats, weak points, flank duels) and says what to do: flank to attack, player to watch, who to
take off and whom to bring on. Nothing is sent to the game.

Tiredness: the game's own stamina value is used when matchlive finds it in the player records
(see StaminaFinder); otherwise it is an estimate: the player's fitness before the match, minus a
drain per game minute that depends on his Stamina and on how much he ran compared with everybody.
"""
import collections
import math

import numpy as np

from . import terms

POS = terms.POSITIONS
HALF_L, HALF_W = 52.5, 34.0
WINDOW = 300                 # game seconds: shape, flanks, possession
ISOLATION = 480              # game seconds: an attacker cut off from his team-mates
EVERY = 20                   # game seconds between two analyses
COOLDOWN = 420               # the same remark is not repeated within (game seconds)
CHANNEL = 11.0               # |y| beyond this: a flank
RIGHT, LEFT = ('RB', 'RMF', 'RWF'), ('LB', 'LMF', 'LWF')
DEFENDERS, ATTACKERS = ('CB', 'LB', 'RB'), ('LWF', 'RWF', 'SS', 'CF', 'AMF', 'LMF', 'RMF')
FLANK_VI = {'R': 'cánh phải', 'L': 'cánh trái', 'C': 'trung lộ'}


def gmin(clock):
    return f"{int(clock // 60) + 1}'" if clock is not None else ''


class Person:
    """One player as the analysis knows him (from the save)."""

    def __init__(self, pid, team, num, name, role, stamina=70, speed=70, fitness=100, ovr=None, arrow=None):
        self.id, self.team, self.num, self.name, self.role = pid, team, num, name, role
        self.stamina, self.speed, self.fitness, self.ovr, self.arrow = stamina, speed, fitness, ovr, arrow

    def label(self):
        return f"{self.name} (số {self.num})" if self.num is not None else self.name


class Body:
    """What a player did on the pitch this match."""

    def __init__(self):
        self.dist = self.hsr = 0.0
        self.sprints = self.touches = 0
        self.seconds = 0.0          # game seconds on the pitch
        self.last = None
        self.fast = False
        self.game_stamina = None


class StaminaFinder:
    """The game's stamina value in the player records: a field that only goes down during a period,
    for nearly every player, and goes down more for those who run more. Checked, never assumed."""

    def __init__(self, stride):
        self.stride = stride
        self.snaps = []              # (game clock, period, {id: record bytes})
        self.found = None            # (offset, kind, scale)
        self.tried_at = 0

    def add(self, clock, period, records):
        if self.found or clock is None:
            return
        if self.snaps and clock - self.snaps[-1][0] < 30:
            return
        self.snaps.append((clock, period, records))
        self.snaps = self.snaps[-40:]

    def search(self, drain):
        """`drain`: {id: estimated drain so far} to check against. -> found or None"""
        if self.found or len(self.snaps) < 6 or self.snaps[-1][0] - self.snaps[0][0] < 900:
            return self.found
        if len(self.snaps) == self.tried_at:
            return None
        self.tried_at = len(self.snaps)
        ids = [i for i in self.snaps[0][2] if all(i in s[2] for s in self.snaps) and i in drain]
        if len(ids) < 14:
            return None
        raw = np.array([[np.frombuffer(s[2][i], np.uint8) for i in ids] for s in self.snaps])   # snaps, ids, stride
        periods = [s[1] for s in self.snaps]
        best = None
        for kind, width in (('f32', 4), ('u8', 1), ('u16', 2)):
            for off in range(0, self.stride - width + 1, width):
                b = np.ascontiguousarray(raw[:, :, off:off + width])
                v = b.view({'f32': '<f4', 'u8': 'u1', 'u16': '<u2'}[kind])[:, :, 0].astype(np.float64)
                if kind == 'f32':
                    if not np.isfinite(v).all():
                        continue
                    scale = 1.0 if v.max() <= 1.001 else 100.0 if v.max() <= 100.5 else None
                else:
                    scale = 100.0 if v.max() <= 100 else None if kind == 'u8' else (1000.0 if v.max() <= 1000 else None)
                if scale is None or v.min() < 0 or v.max() <= 0:
                    continue
                pct = v / scale * 100
                ok = True
                for t in range(1, len(pct)):         # never up within a period (half time may refill)
                    if periods[t] == periods[t - 1] and (pct[t] > pct[t - 1] + 0.6).mean() > 0.1:
                        ok = False
                        break
                if not ok:
                    continue
                fell = pct[0] - pct[-1] if periods[0] == periods[-1] else pct[0] - pct[-1] + 10
                if (fell > 1.5).mean() < 0.7 or np.ptp(pct[-1]) < 3 or pct[-1].max() > 100.5:
                    continue
                d = np.array([drain[i] for i in ids])
                r = np.corrcoef(np.argsort(np.argsort(fell)), np.argsort(np.argsort(d)))[0, 1]
                if r >= 0.3 and (best is None or r > best[0]):
                    best = (r, off, kind, scale)
        if best:
            self.found = {'offset': best[1], 'kind': best[2], 'scale': best[3], 'r': round(float(best[0]), 2)}
        return self.found

    def read(self, record):
        f = self.found
        if not f or record is None:
            return None
        width = {'f32': 4, 'u8': 1, 'u16': 2}[f['kind']]
        b = record[f['offset']:f['offset'] + width]
        if len(b) < width:
            return None
        v = float(np.frombuffer(b, {'f32': '<f4', 'u8': 'u1', 'u16': '<u2'}[f['kind']])[0])
        return max(0.0, min(100.0, v / f['scale'] * 100))


class Analyst:
    def __init__(self, people, me, opp, bench=(), prematch=None):
        self.people = people                 # id -> Person (both squads)
        self.me, self.opp = me, opp
        self.bench = list(bench)             # our players who could come on: Person, with .grades (13)
        self.pre = prematch or {}
        self.samples = collections.deque()   # (clock, {id: (x, y)}, ball, possession)
        self.body = {}                       # id -> Body
        self.on = {}                         # id -> team ('me' / 'opp') currently on the pitch
        self.used = set()                    # ids that have played (a substituted player cannot come back)
        self.feed = []                       # remarks, newest first
        self.said = {}                       # key -> game clock
        self.events = []
        self.last_poss, self.last_poss_at = None, None
        self.next_at = None
        self.period = None
        self.score = None
        self.shape = {'me': None, 'opp': None}
        self.block = {'me': None, 'opp': None}
        self.window = {}
        self.subs = []
        self.finder = None
        self.prev_clock = None
        self.clock = 0
        self.on_since = {}                   # id -> game clock he came on (starters: kick-off)
        self.shapes = {'me': [], 'opp': []}  # the last few shapes measured (a change is said once it holds)

    # ------------------------------------------------------------------ input
    def feed_frame(self, clock, period, score, players, ball, running, dt):
        """players: [{'id', 'team', 'x', 'y'}] (display metres), ball: {'x','y','h'} or None."""
        if clock is None:
            return
        self.clock = clock
        self._events(clock, period, score, running)
        pos, now_on = {}, {}
        for p in players:
            pid = p.get('id')
            if not pid or p.get('team') not in ('me', 'opp'):
                continue
            pos[pid] = (p['x'], p['y'])
            now_on[pid] = p['team']
        self._subs(clock, now_on)
        poss = self._possession(clock, pos, ball, now_on)
        dclock = clock - self.prev_clock if self.prev_clock is not None and 0 <= clock - self.prev_clock <= 30 else 0
        self.prev_clock = clock
        if running:
            for pid, (x, y) in pos.items():
                b = self.body.setdefault(pid, Body())
                b.seconds += dclock
                if b.last is not None:
                    d = math.hypot(x - b.last[0], y - b.last[1])
                    if d < 6 * dt + 1:                 # not a jump (restart, replay)
                        b.dist += d
                        v = d / max(dt, 1e-3)
                        if v > 5.5:
                            b.hsr += d
                        if v > 7.0 and not b.fast:
                            b.sprints += 1
                        b.fast = v > 7.0
                b.last = (x, y)
            self.samples.append((clock, pos, (ball['x'], ball['y'], ball['h']) if ball else None, poss))
            while self.samples and clock - self.samples[0][0] > ISOLATION + 60:
                self.samples.popleft()
        if self.next_at is None:
            self.next_at = clock + 60
        if running and clock >= self.next_at:
            self.next_at = clock + EVERY
            self._analyse(clock)

    def _events(self, clock, period, score, running=True):
        if period != self.period:
            if self.period is not None and period:
                self.period_new = (period, clock)     # said once its clock runs: the final whistle sets the
            self.period = period                      # next period too ("extra time" after a 1-0 win)
        pn = getattr(self, 'period_new', None)
        if pn and pn[0] == period and running and clock >= pn[1] + 5:
            self.period_new = None
            self._say(clock, 'event', 'info', f'period-{period}', {2: 'Bắt đầu hiệp 2.', 3: 'Hiệp phụ thứ nhất.',
                                                                    4: 'Hiệp phụ thứ hai.', 5: 'Đá luân lưu.'}.get(period, 'Hiệp mới.'))
        if score and None not in score:
            if self.score and list(score) != list(self.score):
                self.events.append({'t': clock, 'kind': 'goal', 'score': list(score)})
                self._say(clock, 'event', 'info', f'goal-{score[0]}-{score[1]}', f'⚽ Tỉ số {score[0]}–{score[1]}.')
            self.score = list(score)

    def _subs(self, clock, now_on):
        if not self.on:
            self.on = dict(now_on)
            self.used.update(now_on)
            for i in now_on:
                self.on_since.setdefault(i, 0)
            return
        # who came on for whom is said by matchlive (note_sub: the slot each one plays in), never guessed
        # here from the order names appear in (that paired Ayden Heaven with Endrick)
        gone = [i for i in self.on if i not in now_on]
        came = [i for i in now_on if i not in self.on]
        if gone or came:
            self.on = dict(now_on)
            self.used.update(now_on)
            for i in now_on:
                self.on_since.setdefault(i, clock)

    def note_sub(self, clock, a, b, quiet=False):
        """A substitution: `b` came on for `a` in the same slot (matchlive: the game's line-up, the bodies on
        the pitch). Said once; `quiet`: made before Dugout was watching (only kept)."""
        pa, pb = self.people.get(a), self.people.get(b)
        if not pa or not pb or any(x['out'] == a and x['in'] == b for x in self.subs):
            return
        team = pa.team
        self.subs.append({'t': clock, 'team': team, 'out': a, 'in': b})
        if clock is not None:
            self.on_since[b] = clock
        self.used.add(b)
        if quiet:
            return
        who = 'Bạn' if team == 'me' else 'Đối thủ'
        text = f'{who} thay người: {pb.label()} vào, {pa.label()} ra.'
        if team == 'opp':
            threat = next((t for t in self.pre.get('threats', []) if t.get('id') == b), None)
            if threat:
                text += f" Cầu thủ nguy hiểm trước trận: {', '.join(threat.get('why') or [])}."
            elif pb.speed >= 85:
                text += f' Tốc độ {pb.speed}: chú ý khoảng trống sau lưng hàng thủ.'
        self._say(clock, 'event', 'info', f'sub-{a}-{b}', text)

    def _possession(self, clock, pos, ball, team_of):
        poss = None
        if ball and ball['h'] < 2.0 and pos:
            pid, d = min(((i, math.hypot(x - ball['x'], y - ball['y'])) for i, (x, y) in pos.items()), key=lambda t: t[1])
            if d <= 2.0:
                poss = team_of.get(pid)
                if d <= 1.5:
                    b = self.body.setdefault(pid, Body())
                    if getattr(b, 'touching', False) is False:
                        b.touches += 1
                    b.touching = True
                for i, bb in self.body.items():
                    if i != pid:
                        bb.touching = False
        if poss:
            self.last_poss, self.last_poss_at = poss, clock
        elif self.last_poss_at is not None and clock - self.last_poss_at <= 20:
            poss = self.last_poss
        return poss

    # ------------------------------------------------------------------ tiredness
    def stamina(self, pid):
        """(percent, from the game?)"""
        b, p = self.body.get(pid), self.people.get(pid)
        if b is None or p is None:
            return None, False
        if b.game_stamina is not None:
            return round(b.game_stamina), True
        played = self.clock - self.on_since.get(pid, 0)
        if self.period and self.period >= 2 and self.on_since.get(pid, 0) < 45 * 60:
            played -= 300                             # a little stamina back at half time
        minutes = max(0.0, played / 60)
        rate = 0.55 * (1.6 - p.stamina / 100) / 0.85
        if p.role == 'GK':
            rate *= 0.3
        else:
            per = [x.dist / max(x.seconds, 1) for i, x in self.body.items()
                   if x.seconds > 120 and self.people.get(i) and self.people[i].role != 'GK']
            if per and b.seconds > 120:
                ratio = (b.dist / b.seconds) / max(np.median(per), 1e-6)
                rate *= 0.5 + 0.5 * min(1.5, max(0.6, ratio))
        return round(max(5.0, min(100.0, p.fitness - rate * minutes))), False

    def drain(self):
        return {i: self.people[i].fitness - (self.stamina(i)[0] or 0) for i in self.body if i in self.people}

    # ------------------------------------------------------------------ analysis
    def _window(self, clock, span):
        return [s for s in self.samples if clock - s[0] <= span]

    def _avg(self, samples, team, poss=None):
        """Average position of each player of `team` (present in most samples)."""
        acc = {}
        n = 0
        for _, pos, _, ps in samples:
            if poss is not None and ps != poss:
                continue
            n += 1
            for pid, (x, y) in pos.items():
                if self.on.get(pid) == team:
                    a = acc.setdefault(pid, [0.0, 0.0, 0])
                    a[0] += x
                    a[1] += y
                    a[2] += 1
        return {pid: (a[0] / a[2], a[1] / a[2]) for pid, a in acc.items() if a[2] >= 0.6 * n}, n

    def _depth(self, team, x):
        return x + HALF_L if team == 'me' else HALF_L - x

    def _lines(self, team, avg):
        """(formation 'd-m-f', outfield [(depth, id)] sorted, gk id) of a team's average positions."""
        if len(avg) < 8:
            return None, [], None
        gk = next((i for i in avg if self.people.get(i) and self.people[i].role == 'GK'), None)
        if gk is None:
            gk = min(avg, key=lambda i: self._depth(team, avg[i][0]))
        out = sorted((self._depth(team, avg[i][0]), i) for i in avg if i != gk)
        d = [a for a, _ in out]
        gaps = sorted(((d[k + 1] - d[k], k) for k in range(len(d) - 1)), reverse=True)
        big = [g for g in gaps if g[0] >= 4.5][:3]
        if len(big) < 2:
            big = gaps[:2]
        cuts = sorted(k for _, k in big)
        counts, prev = [], 0
        for c in cuts:
            counts.append(c + 1 - prev)
            prev = c + 1
        counts.append(len(d) - prev)
        while len(counts) > 2 and counts[0] < 3:      # a back line has three players or more
            counts[1] += counts.pop(0)
        if len(d) != 10:                              # a player off (red card, injury): no shape name
            return None, out, gk
        return '-'.join(map(str, counts)), out, gk

    def _say(self, clock, cat, level, key, text, tip=None):
        last = self.said.get(key)
        if last is not None and clock - last < COOLDOWN:
            return False
        self.said[key] = clock
        self.feed.insert(0, {'t': clock, 'min': gmin(clock), 'cat': cat, 'level': level, 'text': text, 'tip': tip})
        del self.feed[60:]
        return True

    def _name(self, pid):
        p = self.people.get(pid)
        return p.label() if p else 'Cầu thủ'

    def _analyse(self, clock):
        win = self._window(clock, WINDOW)
        if len(win) < 40:
            return
        has_ball = sum(1 for s in win if s[3]) >= 0.3 * len(win)
        out = {}
        # ---- possession and territory
        known = [s for s in win if s[3]]
        if known:
            mine = sum(1 for s in known if s[3] == 'me') / len(known)
            out['possession'] = round(100 * mine)
        balls = [s[2] for s in win if s[2]]
        if balls:
            out['territory'] = round(100 * sum(1 for b in balls if b[0] > 0) / len(balls))
        # ---- shapes and blocks (each team without the ball when that is known)
        for team in ('me', 'opp'):
            other = 'opp' if team == 'me' else 'me'
            avg, n = self._avg(win, team, other if has_ball else None)
            if n < 20:
                avg, n = self._avg(win, team)
            shape, lines, gk = self._lines(team, avg)
            if not shape:
                continue
            back = [a for a, _ in lines[:4]]
            line = sum(back) / len(back)
            block = 'thấp' if line < 20 else 'trung bình' if line < 32 else 'cao'
            depths = [a for a, _ in lines]
            out[team] = {'shape': shape, 'line': round(line, 1), 'block': block,
                         'length': round(depths[-1] - depths[0], 1),
                         'width': round(max(avg[i][1] for _, i in lines) - min(avg[i][1] for _, i in lines), 1)}
            hist = self.shapes[team]
            hist.append(shape)
            del hist[:-3]
            prev = self.shape[team]
            if len(hist) == 3 and len(set(hist)) == 1:
                if prev and prev != shape and clock - self.said.get(f'shape-{team}', -9999) >= 360:
                    who = 'Đối thủ' if team == 'opp' else 'Đội bạn'
                    extra = f', khối phòng ngự {block} (hàng thủ cách khung thành ~{round(line)} m)'
                    self.said[f'shape-{team}'] = clock
                    self._say(clock, 'shape', 'warn' if team == 'opp' else 'info', f'shape-{team}-{prev}-{shape}',
                              f'{who} chuyển từ {prev} sang {shape}{extra}.', self._shape_tip(team, shape, block))
                self.shape[team] = shape
            if self.block[team] and self.block[team] != block and self.window.get(team, {}).get('block') == block:
                if team == 'opp':
                    self._say(clock, 'shape', 'warn', f'block-opp-{block}',
                              f'Đối thủ chuyển sang khối phòng ngự {block} (hàng thủ cách khung thành ~{round(line)} m).',
                              self._shape_tip('opp', shape, block))
                self.block[team] = block
            elif not self.block[team]:
                self.block[team] = block
            # gaps between the lines (without the ball)
            if len(lines) >= 8:
                dl = [a for a, _ in lines[:4]]
                ml = [a for a, _ in lines[4:8]]
                gap = sum(ml) / len(ml) - sum(dl) / len(dl)
                out[team]['gap'] = round(gap, 1)
                if gap >= 16:
                    self._gap_remark(clock, team, gap, win, lines, avg)
        self.window = out
        if has_ball:
            self._flanks(clock, win)
        self._isolation(clock)
        self._fatigue(clock)
        self._context(clock, out)
        self._weak_points(clock, out)

    def _shape_tip(self, team, shape, block):
        if team == 'opp' and block == 'thấp':
            return 'Họ lùi sâu: kiên nhẫn chuyền, đưa hậu vệ cánh lên (Hậu vệ công), sút xa và tạt sớm; tránh dồn người vào trung lộ.'
        if team == 'opp' and block == 'cao':
            return 'Họ dâng cao: chọc khe, chuyền dài vào khoảng trống sau hàng thủ (Kiểu tấn công: Phản công).'
        if team == 'opp' and shape.startswith('5'):
            return 'Năm hậu vệ: tấn công từ hai cánh thiếu người (hành lang giữa biên và trung vệ lệch).'
        return None

    def _gap_remark(self, clock, team, gap, win, lines, avg):
        other = 'opp' if team == 'me' else 'me'
        lo = sum(a for a, _ in lines[:4]) / 4
        hi = sum(a for a, _ in lines[4:8]) / 4
        count = collections.Counter()
        for _, pos, _, _ in win:
            for pid, (x, y) in pos.items():
                if self.on.get(pid) != other:
                    continue
                d = self._depth(team, x)
                if lo + 3 < d < hi - 3 and abs(y) < 22:
                    count[pid] += 1
        who = count.most_common(1)
        if team == 'me':
            text = f'Khoảng trống giữa hàng hậu vệ và tiền vệ của bạn ~{round(gap)} m khi mất bóng.'
            if who and who[0][1] >= 0.25 * len(win):
                text += f' {self._name(who[0][0])} thường đứng ở khoảng trống này.'
            self._say(clock, 'defence', 'bad', 'gap-me', text,
                      'Tăng Sự chắc chắn (Compactness), cho tiền vệ phòng ngự lùi sát hàng thủ hoặc dâng hàng thủ.')
        else:
            text = f'Đối thủ hở khoảng giữa hai tuyến (~{round(gap)} m).'
            mine = [pid for pid, c in count.most_common(3)]
            if mine:
                text += f' {self._name(mine[0])} đang có khoảng trống ở đó: chuyền vào chân.'
            self._say(clock, 'attack', 'good', 'gap-opp', text,
                      'Chuyền sệt vào giữa hai tuyến, cho AMF/SS lùi nhận bóng rồi xoay người.')

    def _flanks(self, clock, win):
        def chan(y):
            return 'R' if y > CHANNEL else 'L' if y < -CHANNEL else 'C'
        # our defensive third, the opponent with the ball
        dz = [s for s in win if s[2] and s[2][0] < -HALF_L / 3 and s[3] == 'opp']
        if len(dz) >= 16:
            c = collections.Counter(chan(s[2][1]) for s in dz)
            side, n = max(((k, c[k]) for k in ('L', 'R')), key=lambda t: t[1])
            other = c['L' if side == 'R' else 'R']
            if n / len(dz) >= 0.5 and n >= 1.6 * max(other, 1):
                share = round(100 * n / len(dz))
                ours = self._player_in(win, 'me', side, defensive=True)
                theirs = self._ball_player(dz, 'opp', side, chan)
                text = f'Đối thủ đang khai thác hành lang {FLANK_VI[side].split()[1]} của bạn: {share}% thời gian bóng ở 1/3 sân nhà nằm ở {FLANK_VI[side]}.'
                if theirs:
                    text += f' {self._name(theirs)} nhận bóng nhiều nhất ở đó.'
                tip = 'Cho tiền vệ cánh bên đó lùi hỗ trợ, hoặc dùng Kèm người chặt chẽ lên cầu thủ đó.'
                if ours:
                    st, _ = self.stamina(ours)
                    tip = f'{self._name(ours)} đang phải đối mặt một mình. ' + tip
                    if st is not None and st < 60:
                        tip += f' {self.people[ours].name} đã mệt (thể lực {st}%): cân nhắc thay.'
                m = next((x for x in self.pre.get('matchups', []) if x.get('side') == side), None)
                if m:
                    tip += f" Trước trận đã cảnh báo: {m.get('text')}."
                self._say(clock, 'defence', 'bad', f'flank-def-{side}', text, tip)
        # their defensive third, us with the ball
        az = [s for s in win if s[2] and s[2][0] > HALF_L / 3 and s[3] == 'me']
        if len(az) >= 16:
            c = collections.Counter(chan(s[2][1]) for s in az)
            side, n = max(((k, c[k]) for k in ('L', 'R')), key=lambda t: t[1])
            weak = self.pre.get('weak_side')
            if n / len(az) >= 0.55:
                text = f'Bạn tấn công dồn sang {FLANK_VI[side]} ({round(100 * n / len(az))}% bóng ở 1/3 sân đối thủ).'
                tip = None
                if weak and weak != side:
                    tip = f'Theo phân tích trước trận, {FLANK_VI[weak]} của bạn (đối diện {self.pre.get("weak_side_text", "hậu vệ yếu hơn của họ")}) dễ đánh hơn: đổi hướng tấn công.'
                self._say(clock, 'attack', 'info', f'flank-att-{side}', text, tip)

    def _player_in(self, win, team, side, defensive=False):
        """Our player who most often stands on that flank of our half."""
        c = collections.Counter()
        for _, pos, _, _ in win:
            for pid, (x, y) in pos.items():
                if self.on.get(pid) != team:
                    continue
                if (y > CHANNEL if side == 'R' else y < -CHANNEL) and (x < 0 if defensive else True):
                    c[pid] += 1
        best = c.most_common(1)
        return best[0][0] if best else None

    def _ball_player(self, samples, team, side, chan):
        c = collections.Counter()
        for _, pos, ball, _ in samples:
            if not ball or chan(ball[1]) != side:
                continue
            near = min(((pid, math.hypot(x - ball[0], y - ball[1])) for pid, (x, y) in pos.items()
                        if self.on.get(pid) == team), key=lambda t: t[1], default=None)
            if near and near[1] < 2.5:
                c[near[0]] += 1
        best = c.most_common(1)
        return best[0][0] if best else None

    def _isolation(self, clock):
        win = self._window(clock, ISOLATION)
        if len(win) < 60:
            return
        has_ball = sum(1 for s in win if s[2]) >= 0.5 * len(win)
        ours = sum(1 for s in win if s[3] == 'me')
        worst = None
        for pid, team in self.on.items():
            p = self.people.get(pid)
            if team != 'me' or not p or p.role not in ATTACKERS:
                continue
            near, touches = [], 0
            for _, pos, ball, ps in win:
                if pid not in pos:
                    continue
                x, y = pos[pid]
                d = min((math.hypot(x - a, y - b) for q, (a, b) in pos.items() if q != pid and self.on.get(q) == 'me'), default=None)
                if d is not None:
                    near.append(d)
            if len(near) < 0.6 * len(win):
                continue
            mean = sum(near) / len(near)
            touches = self._touches_in(pid, win) if has_ball else None
            cut = (touches <= 1 and mean >= 13 and ours >= 0.3 * len(win)) if has_ball else mean >= 17
            if cut and (worst is None or mean > worst[0]):
                worst = (mean, pid, touches)
        if worst:
            mean, pid, touches = worst
            if touches is not None:
                self._say(clock, 'attack', 'warn', f'iso-{pid}',
                          f'{self._name(pid)} đang bị cô lập {ISOLATION // 60} phút qua: chạm bóng {touches} lần, '
                          f'đồng đội gần nhất trung bình cách {round(mean)} m.',
                          'Kéo tiền vệ hoặc hậu vệ cánh lên gần hơn, chuyền nhanh ra cánh của anh ấy, hoặc đổi vị trí với một tiền vệ.')
            else:
                self._say(clock, 'attack', 'warn', f'iso-{pid}',
                          f'{self._name(pid)} đứng tách khỏi đồng đội {ISOLATION // 60} phút qua (đồng đội gần nhất trung bình cách {round(mean)} m).',
                          'Thu hẹp khoảng cách các tuyến (Support Range thấp hơn).')

    def _touches_in(self, pid, win):
        n, was = 0, False
        for _, pos, ball, _ in win:
            if not ball or pid not in pos:
                was = False
                continue
            near = min(pos.items(), key=lambda kv: math.hypot(kv[1][0] - ball[0], kv[1][1] - ball[1]))
            now = near[0] == pid and math.hypot(near[1][0] - ball[0], near[1][1] - ball[1]) <= 1.5
            if now and not was:
                n += 1
            was = now
        return n

    def _fatigue(self, clock):
        if clock < 50 * 60:
            return
        tired = []
        for pid, team in self.on.items():
            p = self.people.get(pid)
            if team != 'me' or not p or p.role == 'GK':
                continue
            st, game = self.stamina(pid)
            if st is not None and st <= 60:
                tired.append((st, pid, game))
        tired.sort()
        for st, pid, game in tired[:2]:
            sub = self.substitute(pid)
            src = 'theo game' if game else 'ước tính'
            text = f'{self._name(pid)} đã mệt: thể lực {st}% ({src}).'
            tip = None
            if sub:
                q = self.people[sub]
                tip = f'Gợi ý thay: {q.label()} ({q.role}' + (f', OVR {q.ovr}' if q.ovr else '') + \
                      (f', phong độ {q.arrow}' if q.arrow else '') + ') vào thay.'
            self._say(clock, 'fitness', 'warn', f'tired-{pid}', text, tip)
        # the opponent's back line tiring: bring pace on
        backs = [self.stamina(i)[0] for i, t in self.on.items() if t == 'opp' and self.people.get(i)
                 and self.people[i].role in DEFENDERS]
        backs = [b for b in backs if b is not None]
        if len(backs) >= 3 and sum(backs) / len(backs) <= 60:
            fast = max((q for q in self.bench if q.id not in self.used), key=lambda q: q.speed, default=None)
            tip = f'Tung cầu thủ tốc độ vào: {fast.label()} (tốc độ {fast.speed}).' if fast and fast.speed >= 82 else None
            self._say(clock, 'fitness', 'good', 'opp-backs-tired',
                      f'Hàng thủ đối thủ đã mệt (thể lực trung bình ~{round(sum(backs) / len(backs))}%).', tip)

    def substitute(self, pid):
        """The best player on our bench for the role of `pid`."""
        p = self.people.get(pid)
        if not p:
            return None
        idx = POS.index(p.role) if p.role in POS else None
        best = None
        for q in self.bench:
            if q.id in self.used or q.role == 'GK' and p.role != 'GK':
                continue
            grade = q.grades[idx] if idx is not None and getattr(q, 'grades', None) is not None else (2 if q.role == p.role else 0)
            if q.role != p.role and grade < 2:
                continue
            score = (2 if q.role == p.role else 1, (q.ovr or 0) + (q.fitness - 80) * 0.2)
            if best is None or score > best[0]:
                best = (score, q.id)
        return best[1] if best else None

    def suggestions(self):
        """Current substitution ideas for the panel: [(out, in, stamina, source)]"""
        out = []
        for pid, team in self.on.items():
            p = self.people.get(pid)
            if team != 'me' or not p or p.role == 'GK':
                continue
            st, game = self.stamina(pid)
            if st is not None and st <= 65:
                out.append((st, pid, game))
        out.sort()
        res = []
        for st, pid, game in out[:3]:
            sub = self.substitute(pid)
            res.append({'out': pid, 'in': sub, 'stamina': st, 'game': game})
        return res

    def _context(self, clock, out):
        if not self.score or clock < 60 * 60:
            return
        a, b = self.score
        mine, theirs = (a, b) if self.pre.get('home_me', True) else (b, a)
        if mine < theirs:
            tip = 'Chuyển Kiểu tấn công sang Kiểm soát thế trận hoặc thêm một tiền đạo; dâng hàng thủ (Defensive Line cao hơn).'
            if self.block.get('opp') == 'thấp':
                tip = 'Họ đã lùi sâu: thêm người vào vòng cấm (Tập trung vòng cấm / Xe buýt hai tầng), tạt bóng và sút xa.'
            self._say(clock, 'context', 'bad', f'losing-{clock // 600}', f'Đang thua {mine}–{theirs} ở phút {gmin(clock)}.', tip)
        elif mine > theirs and clock >= 75 * 60:
            self._say(clock, 'context', 'good', f'leading-{clock // 600}', f'Đang dẫn {mine}–{theirs} ở phút {gmin(clock)}.',
                      'Giữ tỉ số: Phong cách phòng thủ Chuyên phòng ngự, tăng Sự chắc chắn, thay tiền đạo mệt bằng tiền vệ phòng ngự.')

    def _weak_points(self, clock, out):
        """The pre-match weak points, checked against what happens."""
        opp = out.get('opp')
        for w in self.pre.get('weak', []):
            pid = w.get('id')
            if not pid or pid not in self.on:
                continue
            if 'chậm' in w.get('text', '') and opp and opp.get('line', 0) >= 30:
                fast = max((i for i, t in self.on.items() if t == 'me' and self.people.get(i)
                            and self.people[i].role in ATTACKERS), key=lambda i: self.people[i].speed, default=None)
                tip = f'Chọc khe cho {self._name(fast)} (tốc độ {self.people[fast].speed}) vào sau lưng anh ta.' if fast else None
                self._say(clock, 'attack', 'good', f'weak-{pid}',
                          f'Hàng thủ đối thủ đang dâng cao (~{round(opp["line"])} m) mà {self._name(pid)} chậm: đúng điểm yếu trước trận.', tip)

    # ------------------------------------------------------------------ output
    def players(self):
        out = {}
        for pid, b in self.body.items():
            st, game = self.stamina(pid)
            out[pid] = {'dist': round(b.dist), 'hsr': round(b.hsr), 'sprints': b.sprints, 'touches': b.touches,
                        'stamina': st, 'stamina_game': game, 'min': round(b.seconds / 60)}
        return out

    def state(self):
        return {'feed': self.feed[:30], 'window': self.window, 'subs_now': self.suggestions(),
                'subs': self.subs[-10:], 'stamina_source': 'game' if self.finder and self.finder.found else 'estimate'}

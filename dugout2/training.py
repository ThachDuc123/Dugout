"""Position training over time: a player learns a position the way he would on the training
ground, one grade at a time (C -> B -> A), instead of at once.

A step takes about six weeks of the game's calendar; every 90 minutes he actually plays in that
position during the step saves a week; young players learn faster, veterans slower; never less
than two weeks. Progress is measured from the game's own data: the in-game date (live from the
game's memory while it runs, otherwise the save's) and the minutes in the save's match records.
When a step is complete the grade is raised like a manual "learn": in the game's memory while
FL26 runs, otherwise in the save (backed up first). The plan ends at grade A or when cancelled;
a grade the player gained on his own (the game's training) counts too.
"""
import datetime as dt
import os
import threading

from . import analysis, store, terms

BASE_DAYS = 42
DAYS_PER_90 = 7
MIN_DAYS = 14
POS = terms.POSITIONS


def age_factor(age):
    if age <= 21:
        return 0.7
    if age <= 25:
        return 0.85
    if age <= 29:
        return 1.0
    if age <= 32:
        return 1.25
    return 1.5


class Trainer:
    def __init__(self, career_dir):
        self.path = os.path.join(career_dir, 'training.json')
        self.lock = threading.RLock()
        self.plans = store._read_json(self.path, [])

    def _save(self):
        store.write_json(self.path, self.plans, compact=False)

    def active(self, pid=None):
        return [p for p in self.plans if p['status'] == 'active' and (pid is None or p['pid'] == int(pid))]

    def find(self, pid, pos):
        return next((p for p in self.active(pid) if p['pos'] == int(pos)), None)

    def start(self, snap, pid, pos, grade, today):
        with self.lock:
            if grade >= 2:
                raise ValueError(f'Cầu thủ đã thạo {POS[pos]} (hạng A).')
            if self.find(pid, pos):
                raise ValueError(f'Đang tập {POS[pos]} rồi.')
            if len(self.active(pid)) >= 2:
                raise ValueError('Mỗi cầu thủ tập tối đa 2 vị trí cùng lúc.')
            plan = {'id': f'{pid}:{pos}:{today.isoformat()}', 'pid': int(pid), 'pos': int(pos),
                    'name': snap.player_name(pid), 'started': today.isoformat(), 'step_from': today.isoformat(),
                    'grade': int(grade), 'target': 2, 'status': 'active', 'steps': []}
            self.plans.insert(0, plan)
            self._save()
            return plan

    def cancel(self, pid, pos):
        with self.lock:
            plan = self.find(pid, pos)
            if plan is None:
                raise ValueError('Không có kế hoạch tập vị trí này.')
            plan['status'] = 'cancelled'
            self._save()
            return plan

    # ------------------------------------------------------------------ progress
    @staticmethod
    def minutes(snap, pid, pos, since):
        """Minutes the player played in `pos` in the club's matches since `since`."""
        i = snap.row.get(int(pid))
        if i is None:
            return 0
        total = 0
        for f in snap.my_fixtures:
            if not f.flags & 64:
                continue
            try:
                when = dt.date(f.year, f.month, f.day)
            except ValueError:
                continue
            if when < since:
                continue
            side = f.home if f.home_team == snap.team_id else f.away
            for a in side:
                if int(a.player_id) == int(pid) and a.minutes:
                    if analysis.match_position(snap, i, a.position_code) == pos:
                        total += int(a.minutes)
        return total

    def progress(self, snap, plan, today):
        i = snap.row.get(plan['pid'])
        age = int(snap.age[i]) if i is not None else 25
        since = dt.date.fromisoformat(plan['step_from'])
        days = max(0, (today - since).days)
        mins = self.minutes(snap, plan['pid'], plan['pos'], since)
        need = max(MIN_DAYS, BASE_DAYS * age_factor(age))
        done = days + DAYS_PER_90 * mins / 90
        pct = min(100, int(done / need * 100))
        left = max(0, need - done)
        return {'days': days, 'minutes': mins, 'need_days': round(need), 'pct': pct, 'eta_days': int(round(left)),
                'next': 'CBA'[min(2, plan['grade'] + 1)], 'grade': 'CBA'[plan['grade']]}

    def due(self, snap, today, grade_of):
        """Plans whose step is complete. `grade_of(pid, pos)` is the current grade (live or save);
        a grade gained meanwhile moves the plan on (or ends it)."""
        out = []
        with self.lock:
            changed = False
            for plan in self.active():
                g = grade_of(plan['pid'], plan['pos'])
                if g is None:
                    continue
                if g > plan['grade']:                 # learned meanwhile (the game's own training, or by hand)
                    plan['grade'] = g
                    plan['step_from'] = today.isoformat()
                    changed = True
                if plan['grade'] >= plan['target']:
                    plan['status'] = 'done'
                    changed = True
                    continue
                if self.progress(snap, plan, today)['pct'] >= 100:
                    out.append(plan)
            if changed:
                self._save()
        return out

    def step_done(self, plan, new_grade, today, info):
        with self.lock:
            plan['steps'].append({'date': today.isoformat(), 'grade': 'CBA'[new_grade], **info})
            plan['grade'] = new_grade
            plan['step_from'] = today.isoformat()
            if new_grade >= plan['target']:
                plan['status'] = 'done'
            self._save()

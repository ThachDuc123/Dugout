"""AI on top of a decoded save: OVR, position fit, growth outlook (with each player's own pace
learned from the saved timeline), and development advice (playing style, skills, positions,
abilities to focus on) that can be carried out in the game's training menus."""
import numpy as np

from . import models, pesdb, save_reader, terms

POS = terms.POSITIONS
OUTFIELD = models.OUTFIELD
GK_ONLY = models.GK_ONLY
STYLE_MIN_GAIN = 0.20        # suggest a style change when another style fits this much better
SKILL_MIN_FIT = 0.50         # suggest a skill when the model rates it at least this likely


def analyze(snap, brain, db, timeline):
    """Adds the AI arrays to `snap` (in place)."""
    b = brain
    n = len(snap.ids)
    snap.ovr_all = b.ovr.all_positions(snap.abilities)
    snap.main_pos = np.where((snap.position >= 0) & (snap.position < 13), snap.position,
                             np.argmax(snap.ovr_all, axis=1)).astype(np.int32)
    snap.ovr = snap.ovr_all[np.arange(n), snap.main_pos]
    snap.fit = position_fit(snap, b)
    snap.personal, snap.learned, snap.vs_pred, snap.vs_pred_since = personal_pace(snap, b, db, timeline)
    snap.out = outlook_cached(snap, b)
    nxt = snap.out['ovr'][:, 1]
    snap.trend = np.where(snap.out['reach_age'] > snap.age, 1, np.where(nxt < snap.ovr - 0.5, -1, 0))
    return snap


_FIT_CACHE = {}


def position_fit(snap, brain):
    """Position fit for every player, recomputed only for players whose stats changed since the
    previous load (after a match only a handful do)."""
    keys = np.column_stack([snap.abilities.astype(np.uint8), (snap.height - 100).astype(np.uint8),
                            snap.left_foot.astype(np.uint8)])
    fit = np.zeros((len(snap.ids), 13), dtype=np.float32)
    todo = []
    for i, (pid, ci, k) in enumerate(zip(snap.ids, snap.cidx, keys)):
        hit = _FIT_CACHE.get((int(pid), int(ci)))
        if hit is not None and hit[0] == k.tobytes():
            fit[i] = hit[1]
        else:
            todo.append(i)
    if todo:
        todo = np.array(todo)
        fit[todo] = brain.positions.predict(snap.abilities[todo], snap.height[todo], snap.left_foot[todo])
        for i in todo:
            _FIT_CACHE[(int(snap.ids[i]), int(snap.cidx[i]))] = (keys[i].tobytes(), fit[i].copy())
    return fit


_OUT_CACHE = {}
_OUT_KEYS = ('peak', 'peak_low', 'peak_high', 'peak_age', 'stop_age', 'reach_age', 'ages', 'ovr', 'low', 'high')


def outlook_cached(snap, brain):
    """Growth outlook, recomputed only for players whose stats, age, position or learned pace changed."""
    n = len(snap.ids)
    keys = [snap.abilities[i].astype(np.uint8).tobytes() + bytes([int(snap.age[i]), int(snap.main_pos[i])])
            + np.float32(round(float(snap.personal[i]), 5)).tobytes() for i in range(n)]
    ident = [(int(p), int(c)) for p, c in zip(snap.ids, snap.cidx)]    # ids can repeat; career index cannot
    todo = [i for i in range(n) if _OUT_CACHE.get(ident[i], (None,))[0] != keys[i]]
    if todo:
        t = np.array(todo)
        o = brain.outlook(snap.abilities[t], snap.age[t].astype(np.float32), snap.main_pos[t], snap.personal[t])
        for j, i in enumerate(todo):
            _OUT_CACHE[ident[i]] = (keys[i], {k: o[k][j] for k in _OUT_KEYS})
    rows = [_OUT_CACHE[x][1] for x in ident]
    return {k: np.array([r[k] for r in rows]) for k in _OUT_KEYS}


def _mean_logit_gap(now, expect, gk):
    gk_mask = np.zeros(25, bool)
    gk_mask[GK_ONLY] = True
    cols = np.where(gk[:, None], gk_mask[None, :], ~gk_mask[None, :])
    keep = cols & (expect > 40.5) & (now > 40.5)
    diff = (models.logit(now) - models.logit(expect)) * keep
    cnt = keep.sum(1)
    return np.where(cnt >= 3, diff.sum(1) / np.maximum(cnt, 1), np.nan)


def personal_pace(snap, brain, db, timeline):
    """Per-player extra growth (logit per year) learned by comparing where each player is now
    with where the model expected him to be from every earlier point we know: the database
    start of the career (not for regens) and each saved snapshot of his current generation.
    Also returns how far his OVR is above/below what was predicted from the earliest point."""
    n = len(snap.ids)
    growth = brain.growth
    num = np.zeros(n)
    den = np.zeros(n)
    span = np.zeros(n)
    vs_pred = np.full(n, np.nan, dtype=np.float32)
    since = np.full(n, '', dtype=object)
    gk = snap.main_pos == 0
    W = brain.ovr.W[snap.main_pos]
    bias = brain.ovr.b[snap.main_pos]

    points = []
    # the database is the career's starting point for every non-regenerated player
    ok = (snap.base_row >= 0) & ~snap.regen
    if ok.any():
        I = np.nonzero(ok)[0]
        points.append((save_reader.ML_START, I, db.age[snap.base_row[I]], db.abilities[snap.base_row[I]]))
    for d, ids, age, ab in timeline.states_at(max_points=12, min_gap_days=45):
        row = snap.row
        I, J = [], []
        for j, p in enumerate(ids):
            i = row.get(int(p))
            if i is not None:
                I.append(i)
                J.append(j)
        if I:
            points.append((d, np.array(I), age[np.array(J)], ab[np.array(J)]))

    for d, I, age0, ab0 in points:
        years = (snap.date - d).days / 365.25
        if years < 0.25:
            continue
        same = (np.abs((snap.age[I] - age0) - years) <= 1.2) & (snap.age[I] >= age0)
        I, age0, ab0 = I[same], age0[same], ab0[same]
        if not len(I):
            continue
        expect = growth.project(ab0, age0, years)
        gap = _mean_logit_gap(snap.abilities[I], expect, gk[I])
        good = ~np.isnan(gap)
        I, gap, expect = I[good], gap[good], expect[good]
        num[I] += gap * years
        den[I] += years * years
        first = span[I] < years
        span[I] = np.maximum(span[I], years)
        exp_ovr = np.clip(np.sum(expect * W[I], axis=1) + bias[I], 40, 99)
        k = I[first]
        vs_pred[k] = (snap.ovr_all[k, snap.main_pos[k]] - exp_ovr[first]).astype(np.float32)
        since[k] = d.isoformat()
    learned = den > 0
    drift = np.where(learned, num / np.maximum(den, 1e-9), 0.0)
    # Relative to players of the same age in this save: a save-wide lag (e.g. a snapshot taken
    # before the season's development has been applied) is not an individual trait.
    band = np.clip(snap.age // 2, 7, 20)
    base = np.zeros(n)
    vs_base = np.zeros(n, dtype=np.float32)
    for g in np.unique(band):
        m = (band == g) & learned
        if m.sum() >= 30:
            base[band == g] = np.median(drift[m])
            vs_base[band == g] = np.nanmedian(vs_pred[m])
    weight = span / (span + 1.5)                     # trust grows with the time observed
    drift = np.clip((drift - base) * weight, -0.06, 0.06).astype(np.float32)
    snap.vs_pred_cohort = vs_base
    return drift, learned & (span >= 0.4), vs_pred, since


# ------------------------------------------------------------------ positions played
# Match appearances record a position category, not the side: 2 full-back, 5 side midfielder,
# 8 wing forward. The side is taken from the player's own grades.
MATCH_POSITION = {0: ('GK',), 1: ('CB',), 2: ('LB', 'RB'), 3: ('DMF',), 4: ('CMF',), 5: ('LMF', 'RMF'),
                  6: ('AMF',), 7: ('SS',), 8: ('LWF', 'RWF'), 9: ('CF',)}


def match_position(snap, i, code):
    """Position index for a match position code, choosing the side that suits the player."""
    names = MATCH_POSITION.get(int(code))
    if not names:
        return None
    if len(names) == 1:
        return POS.index(names[0])
    a, b = POS.index(names[0]), POS.index(names[1])
    if snap.main_pos[i] in (a, b):
        return int(snap.main_pos[i])
    ka = (snap.grades[i, a], snap.fit[i, a])
    kb = (snap.grades[i, b], snap.fit[i, b])
    return a if ka >= kb else b


def played_positions(snap, limit=10):
    """pid -> position index the player filled most (by minutes) in the club's last `limit` matches."""
    counts = {}
    played = [f for f in snap.my_fixtures if f.flags & 64]
    played.sort(key=lambda f: (f.year, f.month, f.day))
    for f in played[-limit:]:
        side = f.home if f.home_team == snap.team_id else f.away
        for a in side:
            i = snap.row.get(int(a.player_id))
            if i is None or not a.minutes:
                continue
            p = match_position(snap, i, a.position_code)
            if p is not None:
                c = counts.setdefault(int(a.player_id), {})
                c[p] = c.get(p, 0) + a.minutes
    return {pid: max(c, key=c.get) for pid, c in counts.items()}


# ---------------------------------------------------------------------------- advice
def advise(snap, brain, rows, played=None, own_training=None):
    """Development advice for the given player rows. Returns {row: advice dict}.
    Training already under way (in the game, read from the save, or Dugout's timed position
    training `own_training` {player id: {position index: plan}}) replaces the suggestion of the
    same kind: advice['training'] lists it and advice['suggestions'] leaves it out."""
    rows = np.asarray(rows, dtype=np.int64)
    if not len(rows):
        return {}
    played = played or {}
    pos = np.array([played.get(int(snap.ids[i]), snap.main_pos[i]) for i in rows], dtype=np.int32)
    A = snap.abilities[rows]
    H = snap.height[rows]
    F = snap.left_foot[rows]
    style_p = brain.styles.predict(A, H, F, pos)
    skill_p = brain.skills.predict(A, H, F, pos)
    out = {}
    dev = getattr(snap, 'dev', None) or {}
    own_training = own_training or {}
    for k, i in enumerate(rows):
        pid = int(snap.ids[i])
        out[int(i)] = _advice_one(snap, brain, int(i), int(pos[k]), style_p[k], skill_p[k],
                                  dev.get(pid) or {}, own_training.get(pid) or {})
    return out


def _grade_step(v):
    """(grade letter now, next grade letter, % of the way there) of a position proficiency 0..10000."""
    if v < 5000:
        return 'C', 'B', int(v * 100 // 5000)
    return 'B', 'A', int((v - 5000) * 100 // 5000)


def _training(snap, i, pos, style_p, skill_p, dev, own):
    """What the player is being trained in right now, for the development tab."""
    out = []
    if dev.get('style'):
        t = int(dev['style'])
        out.append({'kind': 'style', 'to': terms.style_label(t), 'to_idx': t, 'from': terms.style_label(int(snap.style[i])),
                    'fit_to': int(round(style_p[t] * 100)), 'source': 'game',
                    'note': 'Game không lưu % tiến độ đổi phong cách; khi xong, cầu thủ sẽ báo trong Hộp thư.'})
    for k, v in sorted((dev.get('skills') or {}).items(), key=lambda kv: -kv[1]):
        out.append({'kind': 'skill', 'skill': terms.skill_label(k), 'skill_idx': int(k), 'pct': round(v / 100, 1),
                    'fit': int(round(skill_p[k] * 100)), 'source': 'game'})
    for p, v in sorted((dev.get('positions') or {}).items()):
        if snap.fit[i, p] < 50:
            continue                            # a few minutes played out of position, not a target
        now, nxt, pct = _grade_step(v)
        out.append({'kind': 'position', 'position': POS[p], 'position_vi': terms.POS_VI[POS[p]], 'grade': now,
                    'next': nxt, 'pct': pct, 'fit': int(round(snap.fit[i, p])), 'source': 'game'})
    for p, plan in own.items():
        if any(x['kind'] == 'position' and x['position'] == POS[p] for x in out):
            continue
        g = int(snap.grades[i, p])
        out.append({'kind': 'position', 'position': POS[p], 'position_vi': terms.POS_VI[POS[p]], 'grade': 'CBA'[g],
                    'next': 'CBA'[min(2, g + 1)], 'pct': int(plan.get('pct') or 0), 'eta': plan.get('eta_days'),
                    'fit': int(round(snap.fit[i, p])), 'source': 'dugout'})
    return out


def _advice_one(snap, brain, i, pos, style_p, skill_p, dev=None, own=None):
    gk = pos == 0
    cur = int(snap.style[i])
    training = _training(snap, i, pos, style_p, skill_p, dev or {}, own or {})
    busy = {x['kind'] for x in training if x['kind'] != 'position'}
    busy_pos = {x['position'] for x in training if x['kind'] == 'position'}
    order = [int(s) for s in np.argsort(-style_p) if style_p[s] > 0.01][:4]
    styles = [{'idx': s, 'label': terms.style_label(s), 'fit': int(round(style_p[s] * 100)), 'current': s == cur}
              for s in order]
    advice = {'pos': POS[pos], 'styles': styles, 'style_now': terms.style_label(cur),
              'style_now_fit': int(round(style_p[cur] * 100)) if cur else 0, 'suggestions': [],
              'training': training}

    # ---- playing style
    best = order[0] if order else 0
    cur_ok = cur and brain.styles.compat[pos, cur]
    if 'style' not in busy and best and best != cur and (not cur_ok or style_p[best] - style_p[cur] >= STYLE_MIN_GAIN) and style_p[best] >= 0.30:
        why = _style_reasons(snap, i, best, pos)
        advice['suggestions'].append({
            'kind': 'style', 'to': terms.style_label(best), 'to_idx': best, 'from': terms.style_label(cur),
            'fit_to': int(round(style_p[best] * 100)), 'fit_from': int(round(style_p[cur] * 100)) if cur else 0,
            'why': why,
            'how': f'Trong game: Master League → Tập luyện → chọn {snap.names[i]} → tập luyện cá nhân theo phong cách '
                   f'"{terms.STYLES[best][0]}". Khi thành công game gửi email "Đã có một sự tiến triển trong tập luyện".'})

    # ---- skills
    have = int(snap.skills[i])
    cands = []
    for k, (name, vi, *_r) in enumerate(terms.SKILLS):
        if have >> k & 1 or name in terms.NOT_TRAINABLE:
            continue
        if (name in terms.GK_SKILLS) != gk:
            continue
        if skill_p[k] >= SKILL_MIN_FIT:
            cands.append((float(skill_p[k]), k))
    cands.sort(reverse=True)
    for p, k in ([] if 'skill' in busy else cands[:3]):
        need = []
        ready = True
        for a, low, med in brain.skills.key[k]:
            v = int(snap.abilities[i, a])
            need.append({'ability': terms.ABILITY_VI[terms.ABILITIES[a]], 'value': v, 'typical': int(round(med)),
                         'min': int(round(low))})
            if v < low:
                ready = False
        advice['suggestions'].append({
            'kind': 'skill', 'skill': terms.skill_label(k), 'skill_idx': k, 'fit': int(round(p * 100)),
            'ready': ready, 'need': need,
            'how': f'Trong game: Master League → Tập luyện → Tập luyện kỹ năng → Chọn Kỹ năng → '
                   f'"{terms.SKILLS[k][0]}" cho {snap.names[i]}.'})

    # ---- positions worth learning (position training)
    fit = snap.fit[i]
    main_ovr = snap.ovr_all[i, snap.main_pos[i]]
    for p in np.argsort(-fit)[:4]:
        p = int(p)
        if snap.grades[i, p] >= 2 or p == snap.main_pos[i] or fit[p] < 65:
            continue
        if POS[p] in busy_pos:
            break                               # already training this one
        if snap.ovr_all[i, p] < main_ovr - 3:
            continue
        advice['suggestions'].append({
            'kind': 'position', 'position': POS[p], 'position_vi': terms.POS_VI[POS[p]],
            'grade': 'CBA'[int(snap.grades[i, p])], 'fit': int(round(fit[p])), 'ovr': int(snap.ovr_all[i, p]),
            'how': f'Trong game: Master League → Tập luyện → Luyện tập Vị trí → "{POS[p]}" cho {snap.names[i]}.'})
        break

    # ---- abilities to prioritise (training focus): biggest OVR gain per point that still has room
    W = brain.ovr.W[pos]
    peak_ab = brain.growth.project(snap.abilities[i:i + 1], np.array([snap.age[i]], np.float32),
                                   float(max(0, snap.out['peak_age'][i] - snap.age[i])), snap.personal[i:i + 1])[0]
    room = np.clip(np.maximum(peak_ab, snap.abilities[i] + 3) - snap.abilities[i], 0, None)
    room = np.where(snap.abilities[i] >= 97, 0, room)
    score = W * np.minimum(room, 10)
    focus = [int(a) for a in np.argsort(-score)[:4] if W[a] > 0.02 and room[a] > 0]
    advice['focus'] = [{'ability': terms.ABILITY_VI[terms.ABILITIES[a]], 'key': terms.ABILITIES[a],
                        'value': int(snap.abilities[i, a]), 'weight': round(float(W[a]), 3)} for a in focus[:3]]
    advice['count'] = len(advice['suggestions'])
    advice['training_n'] = len(training)
    return advice


def _style_reasons(snap, i, style, pos):
    """The player's standout abilities that the suggested style relies on."""
    A = snap.abilities
    same = snap.main_pos == pos
    peers = A[same] if same.sum() > 50 else A
    z = (A[i] - peers.mean(0)) / (peers.std(0) + 1e-6)
    tops = [int(a) for a in np.argsort(-z)[:3] if z[a] > 0.3 and (pos == 0) == (a in GK_ONLY)]
    return [f'{terms.ABILITY_VI[terms.ABILITIES[a]]} {int(A[i, a])}' for a in tops]


# ------------------------------------------------------------------- age by age
def by_age(snap, brain, i):
    """Projection for every coming year: OVR at the main position (with 80% band), best position
    and the key abilities, so a transfer target's development can be judged age by age."""
    o = snap.out
    ages = o['ages'][i]
    rows = []
    for j, a in enumerate(ages):
        if a > 40:
            break
        years = float(j)
        proj = brain.growth.project(snap.abilities[i:i + 1], np.array([snap.age[i]], np.float32), years,
                                    snap.personal[i:i + 1])[0]
        ovr_all = brain.ovr.all_positions(proj[None, :])[0]
        best = int(np.argmax(ovr_all + snap.fit[i] * 0.02))
        rows.append({'age': int(a), 'year': snap.date.year + j, 'ovr': round(float(o['ovr'][i, j]), 1),
                     'low': round(float(o['low'][i, j]), 1), 'high': round(float(o['high'][i, j]), 1),
                     'best_pos': POS[best], 'best_ovr': int(ovr_all[best]),
                     'abilities': {terms.ABILITIES[k]: int(round(proj[k])) for k in range(25)}})
    return rows

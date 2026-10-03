"""Train (or retrain) the models from the data on this PC.

  OVR weights    data/ovr_samples.jsonl                       -> data/ovr_weights.json
  Position fit   Player.bin position grades                   -> data/position_model.pkl
  Style fit      Player.bin playing styles                    -> data/style_model.pkl
  Skill fit      Player.bin player skills                     -> data/skill_model.pkl
  Growth         Player.bin + every ML save in Documents/KONAMI + backed-up saves (backup.py)
                 + the saved timeline of every followed career -> data/growth_model.json
"""
import datetime as dt
import json
import os
import pickle
import sys

import numpy as np

from . import config, models, pesdb, save_reader, terms
from .pes import career as pc
from .pes import container, crypto

PARTS = ('ovr', 'positions', 'styles', 'skills', 'growth')
SAMPLE_KEYS = {'offensive_awareness': 'Offensive Awareness', 'ball_control': 'Ball Control', 'dribbling': 'Dribbling',
               'tight_possession': 'Tight Possession', 'low_pass': 'Low Pass', 'lofted_pass': 'Lofted Pass',
               'finishing': 'Finishing', 'heading': 'Heading', 'place_kicking': 'Place Kicking', 'curl': 'Curl',
               'speed': 'Speed', 'acceleration': 'Acceleration', 'kicking_power': 'Kicking Power', 'jump': 'Jump',
               'physical_contact': 'Physical Contact', 'balance': 'Balance', 'stamina': 'Stamina',
               'defensive_awareness': 'Defensive Awareness', 'ball_winning': 'Ball Winning', 'aggression': 'Aggression',
               'gk_awareness': 'GK Awareness', 'gk_catching': 'GK Catching', 'gk_clearing': 'GK Clearing',
               'gk_reflexes': 'GK Reflexes', 'gk_reach': 'GK Reach'}


def missing_parts():
    files = {'ovr': 'ovr_weights.json', 'positions': 'position_model.pkl', 'styles': 'style_model.pkl',
             'skills': 'skill_model.pkl', 'growth': 'growth_model.json'}
    return [p for p, f in files.items() if not os.path.exists(os.path.join(config.DATA_DIR, f))]


def train_ovr(log=print, alpha=30.0):
    """Hierarchical ridge: OVR = shared weights + position-group weights. Official PES 2021 OVRs
    are close to linear, and sharing lets ~200 samples fit ten position groups."""
    from sklearn.linear_model import Ridge
    rows = [json.loads(l) for l in open(os.path.join(config.DATA_DIR, 'ovr_samples.jsonl'), encoding='utf-8')]
    groups = sorted(set(models.POS_GROUP.values()))
    rows = [r for r in rows if models.POS_GROUP.get(r['pos']) in groups]
    X = np.array([[r[SAMPLE_KEYS[a]] for a in pesdb.ABILITIES] for r in rows], dtype=float)
    y = np.array([r['ovr'] for r in rows], dtype=float)
    g = np.array([groups.index(models.POS_GROUP[r['pos']]) for r in rows])

    def expand(X, g):
        return np.hstack([X] + [X * (g == k)[:, None] for k in range(len(groups))] + [np.eye(len(groups))[g]])

    fold = np.arange(len(y)) % 5
    err = np.zeros(len(y))
    for f in range(5):
        m = Ridge(alpha=alpha).fit(expand(X[fold != f], g[fold != f]), y[fold != f])
        err[fold == f] = np.abs(np.rint(m.predict(expand(X[fold == f], g[fold == f]))) - y[fold == f])
    reg = Ridge(alpha=alpha).fit(expand(X, g), y)
    n = len(pesdb.ABILITIES)
    shared = reg.coef_[:n]
    out, report = {}, {}
    for k, grp in enumerate(groups):
        w = shared + reg.coef_[n * (k + 1):n * (k + 2)]
        b = reg.intercept_ + reg.coef_[n * (len(groups) + 1) + k]
        out[grp] = {'w': {a: float(v) for a, v in zip(pesdb.ABILITIES, w)}, 'b': float(b)}
        e = err[g == k]
        report[grp] = {'samples': int(len(e)), 'mae': float(e.mean()) if len(e) else 0.0,
                       'exact_or_1': float((e <= 1).mean()) if len(e) else 0.0}
    log(f'  OVR: sai số trung bình {err.mean():.2f} điểm, {np.mean(err <= 1):.0%} lệch không quá 1')
    json.dump({'groups': out, 'meta': report}, open(os.path.join(config.DATA_DIR, 'ovr_weights.json'), 'w'), indent=1)
    return report


def growth_pairs(db, log=print):
    """(start, end) ability pairs: database -> every save of this game-data version, plus the
    first and latest snapshot of every player in each followed career's timeline."""
    from . import store
    A0, A1, a0, a1, yrs, gk = [], [], [], [], [], []
    active = config.active_save()
    same_version = os.path.dirname(os.path.dirname(active)) if active else None
    from . import backup
    saves = [p for p in config.all_saves()
             if not same_version or os.path.dirname(os.path.dirname(p)) == same_version]
    saves += backup.backup_saves(os.path.basename(same_version) if same_version else None)
    for path in saves:
        try:
            data = crypto.read(path).data
            clocks = pc.clocks(data)
            if not clocks:
                continue
            c = next(iter(clocks.values()))
            date = dt.date(c['year'], c['month'], c['day'])
            t = save_reader.career_table(container.inflate_any(data))
        except Exception as exc:
            log(f'  bỏ qua {path}: {exc}')
            continue
        if date < save_reader.ML_START:
            continue
        T = save_reader.years_since_start(date)
        n = 0
        for pid, age, ab in zip(t['ids'], t['age'], t['abilities']):
            i = db.index.get(int(pid))
            if i is None or not age:
                continue
            if abs((age - db.age[i]) - T) > 1.2 or age <= db.age[i]:
                continue                      # regen or a different person
            A0.append(db.abilities[i]); A1.append(ab); a0.append(db.age[i]); a1.append(age)
            yrs.append(T); gk.append(db.position[i] == 0); n += 1
        where = os.path.basename(os.path.dirname(os.path.dirname(path)))
        log(f'  {where[:40]}/{os.path.basename(path)}  ngày {date}  {n} cặp')
    extra = 0
    folders = []
    for key in os.listdir(config.CAREERS_DIR):
        career = os.path.join(config.CAREERS_DIR, key)
        folders.append((key, career))
        for sub in os.listdir(career) if os.path.isdir(career) else []:
            if sub.startswith('archive_') and os.path.isdir(os.path.join(career, sub, 'timeline')):
                folders.append((f'{key}/{sub}', os.path.join(career, sub)))   # earlier careers of the slot
    for key, folder in folders:
        if not os.path.isdir(os.path.join(folder, 'timeline')):
            continue
        try:
            tl = store.Timeline(folder)
            for first, last, years in tl.span_pairs(min_years=0.4):
                A0.append(first['abilities']); A1.append(last['abilities']); a0.append(first['age'])
                a1.append(last['age']); yrs.append(years); gk.append(first['gk']); extra += 1
        except Exception as exc:
            log(f'  bỏ qua dòng thời gian {key}: {exc}')
    if extra:
        log(f'  + {extra} cặp từ dòng thời gian các lần lưu game')
    return {'A0': np.array(A0), 'A1': np.array(A1), 'a0': np.array(a0), 'a1': np.array(a1),
            'years': np.array(yrs, dtype=np.float32), 'gk': np.array(gk)}


def main(log=print, parts=PARTS):
    report_path = os.path.join(config.DATA_DIR, 'training_report.json')
    try:
        report = json.load(open(report_path, encoding='utf-8'))
    except (OSError, ValueError):
        report = {}
    report['trained_at'] = dt.datetime.now().isoformat(timespec='seconds')
    db = pesdb.PlayerDB()
    step = 0
    total = len(parts)
    if 'ovr' in parts:
        step += 1
        log(f'{step}/{total} Công thức OVR theo vị trí')
        report['ovr'] = train_ovr(log)
    if 'positions' in parts:
        step += 1
        log(f'{step}/{total} Độ hợp vị trí (học từ hạng A/B/C của {len(db.ids)} cầu thủ)')
        pm = models.PositionModel.train(db, lambda m: None)
        pickle.dump(pm, open(os.path.join(config.DATA_DIR, 'position_model.pkl'), 'wb'))
        report['positions'] = pm.metrics
    if 'styles' in parts:
        step += 1
        log(f'{step}/{total} Phong cách chơi hợp chỉ số')
        sm_ = models.StyleModel.train(db, log)
        pickle.dump(sm_, open(os.path.join(config.DATA_DIR, 'style_model.pkl'), 'wb'))
        report['styles'] = sm_.metrics
    if 'skills' in parts:
        step += 1
        log(f'{step}/{total} Kỹ năng cầu thủ hợp chỉ số (41 kỹ năng)')
        sk = models.SkillModel.train(db, log)
        pickle.dump(sk, open(os.path.join(config.DATA_DIR, 'skill_model.pkl'), 'wb'))
        report['skills'] = {'mean_auc': sk.metrics.get('_mean_auc')}
    if 'growth' in parts:
        step += 1
        log(f'{step}/{total} Phát triển theo tuổi (database gốc -> các save Master League)')
        pairs = growth_pairs(db, log)
        gm = models.GrowthModel.train(pairs, log)
        json.dump({'curve': gm.curve.tolist(), 'beta': gm.beta.tolist(), 'sigma': gm.sigma, 'meta': gm.meta,
                   'trained_at': report['trained_at'], 'version': models.MODEL_VERSION},
                  open(os.path.join(config.DATA_DIR, 'growth_model.json'), 'w'))
        report['growth'] = gm.meta
    json.dump(report, open(report_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log('Xong.')
    return report


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main(parts=sys.argv[1:] or PARTS)

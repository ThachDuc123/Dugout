"""The AI models.

OVR           per-position linear formula (fitted to PES 2021 official ratings).
Style fit     multi-class gradient boosting on the database's playing styles, evaluated at the
              position a player actually plays: which in-game playing style his stats suit.
Skill fit     one gradient-boosted classifier per player skill: how typical the skill is for a
              player with these stats at this position (what Skill Training should target).
Position fit  one gradient-boosted classifier per position, trained on the A/B/C position
              grades of every player in the database, applied to *current* abilities.
Growth        per-ability age curves in logit space, learned from the database (career
              start) against every Master League save on this PC (0.1 to 13+ years later),
              plus a level term. Individual deviations are learned from the player's own
              saved history (see history.py) and widen/shift the projection.
"""
import json
import os
import pickle

import numpy as np

from . import config, pesdb, terms

N_AB = len(pesdb.ABILITIES)
AGES = np.arange(15, 46)
OUTFIELD = [i for i, a in enumerate(pesdb.ABILITIES) if not a.startswith('gk_')]
GK_ONLY = [i for i, a in enumerate(pesdb.ABILITIES) if a.startswith('gk_')]
POS_GROUP = {'GK': 'GK', 'CB': 'CB', 'LB': 'SB', 'RB': 'SB', 'DMF': 'DMF', 'CMF': 'CMF', 'LMF': 'SMF',
             'RMF': 'SMF', 'AMF': 'AMF', 'LWF': 'WF', 'RWF': 'WF', 'SS': 'SS', 'CF': 'CF'}
MODEL_VERSION = 4


class _Unpickler(pickle.Unpickler):
    """Models trained by the earlier AI Scout app pickled their class as aiscout.models."""
    def find_class(self, module, name):
        if module == 'aiscout.models':
            module = __name__
        return super().find_class(module, name)


def load_pickle(path):
    with open(path, 'rb') as f:
        return _Unpickler(f).load()


def logit(a):
    a = np.clip(a, 40, 99)
    return np.log((a - 39.5) / (99.5 - a))


def inv_logit(x):
    e = np.exp(np.clip(x, -30, 30))
    return (99.5 * e + 39.5) / (1 + e)


# ----------------------------------------------------------------------------- OVR
class OVRModel:
    """OVR(position) = b + w . abilities. Weights come from data/ovr_weights.json."""

    def __init__(self):
        path = os.path.join(config.DATA_DIR, 'ovr_weights.json')
        spec = json.load(open(path, encoding='utf-8'))
        self.meta = spec.get('meta', {})
        self.W = np.zeros((13, N_AB), dtype=np.float32)
        self.b = np.zeros(13, dtype=np.float32)
        for p, pos in enumerate(pesdb.POSITIONS):
            g = spec['groups'][POS_GROUP[pos]]
            self.W[p] = [g['w'][a] for a in pesdb.ABILITIES]
            self.b[p] = g['b']

    def all_positions(self, abilities):
        """abilities (..., 25) -> OVR (..., 13)"""
        return np.clip(np.rint(abilities @ self.W.T + self.b), 40, 99)


# ------------------------------------------------------------------- position fit
class PositionModel:
    FEATURES = 'abilities + height + stronger foot'

    def __init__(self, models, metrics):
        self.models, self.metrics = models, metrics

    @staticmethod
    def features(abilities, height, left_foot):
        return np.column_stack([abilities, height, left_foot]).astype(np.float32)

    @classmethod
    def train(cls, db, log=print):
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.metrics import roc_auc_score
        X = cls.features(db.abilities, db.height, db.left_foot)
        rng = np.random.default_rng(1)
        test = rng.random(len(X)) < 0.2
        models, metrics = [], {}
        for p, pos in enumerate(pesdb.POSITIONS):
            y = np.minimum(db.grades[:, p], 2)
            clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, max_leaf_nodes=31,
                                                 random_state=0).fit(X[~test], y[~test])
            prob = clf.predict_proba(X[test])
            score = cls._score(prob, clf.classes_)
            can = y[test] >= 1
            auc = float(roc_auc_score(can, score)) if can.any() and (~can).any() else 1.0
            metrics[pos] = {'accuracy': float((clf.predict(X[test]) == y[test]).mean()), 'auc': auc}
            log(f'  {pos:4s} độ chính xác {metrics[pos]["accuracy"]:.3f}  AUC {auc:.3f}')
            clf.fit(X, y)                       # final model on all data
            models.append(clf)
        return cls(models, metrics)

    @staticmethod
    def _score(prob, classes):
        cls = list(classes)
        a = prob[:, cls.index(2)] if 2 in cls else 0
        b = prob[:, cls.index(1)] if 1 in cls else 0
        return a + 0.5 * b

    def predict(self, abilities, height, left_foot):
        """-> (N, 13) suitability 0..100"""
        X = self.features(abilities, height, left_foot)
        out = np.zeros((len(X), 13), dtype=np.float32)
        for p, clf in enumerate(self.models):
            out[:, p] = self._score(clf.predict_proba(X), clf.classes_) * 100
        return out


# --------------------------------------------------------------- style / skill fit
def fit_features(abilities, height, left_foot, pos):
    """abilities + body + the position being evaluated (one-hot)."""
    onehot = np.zeros((len(abilities), 13), dtype=np.float32)
    onehot[np.arange(len(abilities)), np.clip(pos, 0, 12)] = 1
    return np.column_stack([abilities, height, left_foot, onehot]).astype(np.float32)


class StyleModel:
    """P(playing style | stats, position). compat[p, s] says whether style s is used at position p."""

    def __init__(self, clf, compat, metrics):
        self.clf, self.compat, self.metrics = clf, compat, metrics

    @classmethod
    def train(cls, db, log=print):
        from sklearn.ensemble import HistGradientBoostingClassifier
        n_styles = len(terms.STYLES)
        has = (db.style > 0) & (db.position >= 0) & (db.position < 13)
        X = fit_features(db.abilities[has], db.height[has], db.left_foot[has], db.position[has])
        y = db.style[has].astype(int)
        # a style "exists" at a position when enough players rated A there use it
        compat = np.zeros((13, n_styles), dtype=bool)
        for p in range(13):
            at = y[(db.grades[has, p] >= 2) | (db.position[has] == p)]
            if len(at):
                counts = np.bincount(at, minlength=n_styles)
                compat[p] = counts >= max(8, 0.01 * len(at))
        rng = np.random.default_rng(3)
        test = rng.random(len(X)) < 0.2
        params = dict(learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                      random_state=0)
        clf = HistGradientBoostingClassifier(max_iter=400, early_stopping=True, validation_fraction=0.1,
                                             n_iter_no_change=20, **params).fit(X[~test], y[~test])
        prob = clf.predict_proba(X[test])
        order = np.argsort(-prob, axis=1)
        classes = clf.classes_
        top1 = float((classes[order[:, 0]] == y[test]).mean())
        top3 = float(np.mean([y[test][i] in classes[order[i, :3]] for i in range(len(order))]))
        log(f'  phong cách chơi: đúng ngay {top1:.1%}, nằm trong 3 gợi ý đầu {top3:.1%}')
        # final model on all data with the validated number of rounds (no second early stop)
        clf = HistGradientBoostingClassifier(max_iter=int(clf.n_iter_), early_stopping=False, **params).fit(X, y)
        return cls(clf, compat, {'top1': top1, 'top3': top3, 'samples': int(len(X))})

    def predict(self, abilities, height, left_foot, pos):
        """-> (N, n_styles) probabilities, restricted to styles used at pos and renormalised."""
        n_styles = len(terms.STYLES)
        pos = np.broadcast_to(np.asarray(pos), (len(abilities),))
        prob = np.zeros((len(abilities), n_styles), dtype=np.float32)
        prob[:, self.clf.classes_] = self.clf.predict_proba(fit_features(abilities, height, left_foot, pos))
        prob *= self.compat[np.clip(pos, 0, 12)]
        total = prob.sum(1, keepdims=True)
        return np.where(total > 0, prob / np.maximum(total, 1e-9), 0)


class SkillModel:
    """One classifier per skill, plus the abilities that set its owners apart (for advice)."""

    def __init__(self, models, key, metrics):
        self.models, self.key, self.metrics = models, key, metrics

    @classmethod
    def train(cls, db, log=print):
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.metrics import roc_auc_score
        ok = (db.position >= 0) & (db.position < 13)
        X = fit_features(db.abilities[ok], db.height[ok], db.left_foot[ok], db.position[ok])
        A = db.abilities[ok]
        gk = db.position[ok] == 0
        mask = db.skills[ok]
        rng = np.random.default_rng(5)
        test = rng.random(len(X)) < 0.2
        models, key, metrics = [], [], {}
        for k, (name, *_rest) in enumerate(terms.SKILLS):
            y = ((mask >> np.uint64(k)) & np.uint64(1)).astype(bool)
            if y.sum() < 20:
                models.append(None)
                key.append([])
                continue
            params = dict(learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=30, l2_regularization=1.0,
                          random_state=0)
            clf = HistGradientBoostingClassifier(max_iter=300, early_stopping=True, validation_fraction=0.1,
                                                 n_iter_no_change=20, **params).fit(X[~test], y[~test])
            p = clf.predict_proba(X[test])[:, 1]
            auc = float(roc_auc_score(y[test], p)) if y[test].any() and (~y[test]).any() else 1.0
            metrics[name] = {'auc': auc, 'owners': int(y.sum())}
            clf = HistGradientBoostingClassifier(max_iter=int(clf.n_iter_), early_stopping=False, **params).fit(X, y)
            models.append(clf)
            # the abilities where owners stand out most within their own role (GK vs outfield)
            grp = gk if name in terms.GK_SKILLS else ~gk
            own, rest = A[y & grp], A[~y & grp]
            if len(own) < 10:
                key.append([])
                continue
            z = (own.mean(0) - rest.mean(0)) / (A[grp].std(0) + 1e-6)
            top = [int(i) for i in np.argsort(-z)[:3] if z[i] > 0.25]
            key.append([(i, float(np.percentile(own[:, i], 25)), float(np.median(own[:, i]))) for i in top])
        mean_auc = float(np.mean([m['auc'] for m in metrics.values()]))
        log(f'  kỹ năng cầu thủ: {len(metrics)} mô hình, AUC trung bình {mean_auc:.3f}')
        metrics['_mean_auc'] = mean_auc
        return cls(models, key, metrics)

    def predict(self, abilities, height, left_foot, pos):
        """-> (N, 41) probability each skill fits the player."""
        pos = np.broadcast_to(np.asarray(pos), (len(abilities),))
        X = fit_features(abilities, height, left_foot, pos)
        out = np.zeros((len(X), len(terms.SKILLS)), dtype=np.float32)
        for k, clf in enumerate(self.models):
            if clf is not None:
                out[:, k] = clf.predict_proba(X)[:, 1]
        return out


# ------------------------------------------------------------------------ growth
class GrowthModel:
    def __init__(self, curve, beta, sigma, meta):
        self.curve = np.asarray(curve, dtype=np.float32)   # (25, 31) logit offset by age 15..45
        self.beta = np.asarray(beta, dtype=np.float32)     # (25,) level effect per year
        self.sigma = float(sigma)                          # individual sd of logit drift per sqrt(year)
        self.meta = meta

    @classmethod
    def train(cls, pairs, log=print):
        """pairs: dict with arrays A0 (n,25), A1, a0, a1, years, gk(bool)."""
        A0, A1, a0, a1, yrs, gk = (pairs[k] for k in ('A0', 'A1', 'a0', 'a1', 'years', 'gk'))
        level = np.sort(A0[:, OUTFIELD], axis=1)[:, -8:].mean(1)
        curve = np.zeros((N_AB, len(AGES)), dtype=np.float64)
        beta = np.zeros(N_AB)
        rng = np.random.default_rng(0)
        test = rng.random(len(A0)) < 0.2
        maes, base_maes, resid_player = [], [], np.zeros(len(A0))
        for k, name in enumerate(pesdb.ABILITIES):
            m = (gk if name.startswith('gk_') else ~gk) & (a0 >= 15) & (a1 <= 45) & (a1 > a0)
            n = int(m.sum())
            X = np.zeros((n, len(AGES) + 1))
            r = np.arange(n)
            X[r, a1[m] - 15] += 1
            X[r, a0[m] - 15] -= 1
            X[:, -1] = (level[m] - 74.0) * yrs[m]
            X = np.delete(X, 10, axis=1)                   # anchor c(25) = 0
            y = logit(A1[m, k]) - logit(A0[m, k])
            tr = ~test[m]
            coef, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
            coef_full, *_ = np.linalg.lstsq(X, y, rcond=None)
            pred_test = X[~tr] @ coef
            p1 = inv_logit(logit(A0[m, k][~tr]) + pred_test)
            maes.append(float(np.abs(p1 - A1[m, k][~tr]).mean()))
            base_maes.append(float(np.abs(A0[m, k][~tr] - A1[m, k][~tr]).mean()))
            c = np.insert(coef_full[:-1], 10, 0.0)
            curve[k] = c
            beta[k] = coef_full[-1]
            if not name.startswith('gk_'):
                resid_player[m] += (y - X @ coef_full) / len(OUTFIELD)
        long = (yrs >= 5) & ~gk
        sigma = float(np.std(resid_player[long]) / np.sqrt(np.mean(yrs[long]))) if long.any() else 0.04
        meta = {'pairs': int(len(A0)), 'long_pairs': int(long.sum()), 'mae': float(np.mean(maes)),
                'mae_no_change': float(np.mean(base_maes)), 'max_years': float(yrs.max())}
        log(f'  sai số dự đoán chỉ số trung bình {meta["mae"]:.2f} (nếu coi như không đổi: {meta["mae_no_change"]:.2f})')
        return cls(curve, beta, sigma, meta)

    def project(self, abilities, age, years, personal=None):
        """Project abilities `years` ahead (scalar or array per player). Returns (N, 25)."""
        a0 = np.clip(age, 15, 45).astype(int)
        a1 = np.clip(np.rint(age + years), 15, 45).astype(int)
        level = np.sort(abilities[:, OUTFIELD], axis=1)[:, -8:].mean(1)
        yrs = np.broadcast_to(np.asarray(years, dtype=np.float32), a0.shape)
        drift = self.curve[:, a1 - 15].T - self.curve[:, a0 - 15].T + ((level - 74.0) * yrs)[:, None] * self.beta
        if personal is not None:
            grow_years = np.clip(np.minimum(age + years, 30) - age, 0, None)
            drift = drift + (personal * grow_years)[:, None]
        out = inv_logit(logit(abilities) + drift)
        return np.where(abilities <= 40.0, abilities, out)   # untouched 40s (e.g. GK stats of outfielders) stay 40


# ----------------------------------------------------------------------- bundle
class Brain:
    def __init__(self):
        self.ovr = OVRModel()
        self.positions = load_pickle(os.path.join(config.DATA_DIR, 'position_model.pkl'))
        self.styles = load_pickle(os.path.join(config.DATA_DIR, 'style_model.pkl'))
        self.skills = load_pickle(os.path.join(config.DATA_DIR, 'skill_model.pkl'))
        g = json.load(open(os.path.join(config.DATA_DIR, 'growth_model.json'), encoding='utf-8'))
        self.growth = GrowthModel(g['curve'], g['beta'], g['sigma'], g['meta'])
        self.trained = g.get('trained_at', '')

    @staticmethod
    def ready():
        return all(os.path.exists(os.path.join(config.DATA_DIR, f)) for f in
                   ('ovr_weights.json', 'position_model.pkl', 'growth_model.json', 'style_model.pkl',
                    'skill_model.pkl'))

    def trajectory(self, abilities, age, pos, personal=None, horizon=16):
        """OVR at `pos` for every future year: returns ages (H,), ovr (N,H), low (N,H), high (N,H)."""
        n = len(abilities)
        years = np.arange(0, horizon + 1, dtype=np.float32)
        ovr = np.zeros((n, len(years)), dtype=np.float32)
        low, high = ovr.copy(), ovr.copy()
        W = self.ovr.W[pos]
        b = self.ovr.b[pos]
        for j, y in enumerate(years):
            mid = self.growth.project(abilities, age, y, personal)
            ovr[:, j] = np.clip(np.sum(mid * W, axis=1) + b, 40, 99)
            if y == 0:
                low[:, j] = high[:, j] = ovr[:, j]
                continue
            spread = 1.2816 * self.growth.sigma * np.sqrt(min(float(y), 10.0))   # 80% band
            for arr, sgn in ((low, -1), (high, 1)):
                shifted = np.where(mid <= 40, mid, inv_logit(logit(mid) + sgn * spread))
                arr[:, j] = np.clip(np.sum(shifted * W, axis=1) + b, 40, 99)
        return age[:, None] + years[None, :], ovr, low, high

    def outlook(self, abilities, age, pos, personal=None):
        """Peak OVR, peak age and the age growth stops, for every player."""
        ages, ovr, low, high = self.trajectory(abilities, age, pos, personal)
        valid = ages <= 40
        ovr_v = np.where(valid, ovr, -1)
        j = np.argmax(ovr_v, axis=1)
        rows = np.arange(len(ovr))
        peak = ovr[rows, j]
        peak_age = ages[rows, j]
        # growth stops: first year whose gain to the next year is below half a point
        gain = np.diff(ovr, axis=1)
        below = gain < 0.5
        stop = np.where(below.any(1), below.argmax(1), gain.shape[1])
        stop_age = ages[rows, stop]
        # the age the ceiling is practically reached (within half a point of the peak)
        reach = np.argmax(ovr_v >= (peak - 0.5)[:, None], axis=1)
        reach_age = ages[rows, reach]
        return {'peak': peak, 'peak_low': low[rows, j], 'peak_high': high[rows, j], 'peak_age': peak_age,
                'stop_age': stop_age, 'reach_age': reach_age, 'ages': ages, 'ovr': ovr, 'low': low, 'high': high}


def similar(abilities, positions, target_row, k=8):
    """Nearest players by ability profile within the same position group."""
    grp = POS_GROUP[pesdb.POSITIONS[positions[target_row]]]
    cols = GK_ONLY + [OUTFIELD[i] for i in (0, 1, 4, 10, 16)] if grp == 'GK' else OUTFIELD
    X = abilities[:, cols]
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = (X - mu) / sd
    same = np.array([POS_GROUP[pesdb.POSITIONS[p]] == grp if 0 <= p < 13 else False for p in positions])
    d = np.linalg.norm(Z - Z[target_row], axis=1)
    d[~same] = np.inf
    d[target_row] = np.inf
    return np.argsort(d)[:k]

"""Self-check of every decoded save.

Dugout reads the save with its own decoder (package `pes`), and an update of FL26 or the database
can shift what it reads without raising any error: the app would then show (and learn from) wrong
numbers. Each save is checked against what a healthy FL26 career looks like and against
the previous save. A save with an 'error' is shown with a warning and is not written into the data
the AI learns from; 'warn' only means one part of the app may be incomplete.

Updates of FL_2026.exe and Player.bin are also noticed (size and time of the file), because each
needs something from the manager (check the app still reads the save right, retrain the AI...).
"""
import datetime as dt
import json
import os
import time

import numpy as np

from . import config, save_reader, store

STATE = os.path.join(config.DATA_DIR, 'health.json')
SHOW_CHANGE_DAYS = 7          # how long a noticed update stays on screen

WATCHED = (
    ('game', 'FL_2026.exe',
     'FL_2026.exe đã thay đổi (game vừa cập nhật): Dugout đã tự kiểm tra lại cách đọc save (xem các dòng dưới).'),
    ('database', 'Database (Player.bin)',
     'Database cầu thủ (Player.bin) đã thay đổi: nên bấm "Huấn luyện lại AI" ở mục AI dự đoán.'),
)


def _watched_paths():
    return {'game': config.GAME_EXE,
            'database': config.effective_file(os.path.join('common', 'etc', 'pesdb', 'Player.bin'))}


def _fingerprint(path):
    try:
        st = os.stat(path)
        return f'{st.st_size}:{int(st.st_mtime)}'
    except (OSError, TypeError):
        return None


def file_changes():
    """Notice updated program / database files. Returns the notes to show (kept for a week)."""
    state = store._read_json(STATE, {})
    prints = state.get('files', {})
    changed = state.get('changed', {})
    first = not prints
    now = time.time()
    for key, path in _watched_paths().items():
        fp = _fingerprint(path)
        if fp is None:
            continue
        if not first and prints.get(key) and prints[key] != fp:
            changed[key] = now
        prints[key] = fp
    state['files'], state['changed'] = prints, changed
    try:
        store.write_json(STATE, state, compact=False)
    except OSError:
        pass
    out = []
    for key, name, text in WATCHED:
        at = changed.get(key)
        if at and now - at < SHOW_CHANGE_DAYS * 86400:
            out.append({'level': 'info', 'text': text, 'when': time.strftime('%d/%m %H:%M', time.localtime(at))})
    return out


def _dec(x):
    return f'{x:.1f}'.replace('.', ',')


def _pct(x):
    return f'{x * 100:.0f}%'


def check(snap, timeline=None):
    """{'level': ok|warn|error, 'items': [{'level', 'text'}], ...} for one decoded save."""
    items = []

    def add(level, text):
        items.append({'level': level, 'text': text})

    n = len(snap.ids)
    num = lambda v: f'{v:,}'.replace(',', '.')

    # ---- the basics every part of the app relies on
    if n < 10000:
        add('error', f'Chỉ đọc được {num(n)} cầu thủ (save FL26 bình thường có khoảng 27 nghìn).')
    else:
        add('ok', f'Đọc được {num(n)} cầu thủ.')
    if snap.clock is None or not (save_reader.ML_START <= snap.date <= dt.date(2075, 12, 31)):
        add('error', f'Ngày trong game đọc ra không hợp lệ ({snap.date}).')
    squad = len(snap.squad_players)
    if not snap.team_id or not snap.team_name:
        add('error', 'Không nhận ra CLB bạn đang quản lý.')
    elif not 14 <= squad <= 50:
        add('error', f'Đội hình {snap.team_name} đọc ra {squad} người (bất thường).')
    else:
        add('ok', f'CLB {snap.team_name}: {squad} cầu thủ, ngày {snap.date.day}/{snap.date.month}/{snap.date.year}.')
    if n:
        age_ok = float(np.mean((snap.age >= 14) & (snap.age <= 46)))
        A = snap.abilities
        ab_ok = float(np.mean((A >= 20) & (A <= 99)))
        ab_mean = float(A.mean())
        if age_ok < 0.95:
            add('error', f'Tuổi cầu thủ đọc ra bất thường ({_pct(1 - age_ok)} ngoài khoảng 14–46).')
        if ab_ok < 0.98 or not 50 <= ab_mean <= 75:
            add('error', f'Chỉ số cầu thủ đọc ra bất thường (trung bình {_dec(ab_mean)}, {_pct(1 - ab_ok)} ngoài khoảng 20–99).')
        elif age_ok >= 0.95:
            add('ok', f'Tuổi và 25 chỉ số hợp lệ (chỉ số trung bình {_dec(ab_mean)}).')

    # ---- against the previous save of this career: a shifted offset changes everyone at once
    if timeline is not None and n:
        try:
            timeline.load()
            if timeline.dates and timeline.cur_ids.size:
                last = timeline.dates[-1]
                gap = (snap.date - last).days
                if 0 <= gap <= 400:
                    rows = np.array([timeline.cur_slot.get(int(p), -1) for p in snap.ids])
                    known = rows >= 0
                    overlap = known.sum() / max(timeline.cur_ids.size, 1)
                    diff = np.abs(timeline.cur['abilities'][rows[known]].astype(np.float32) - snap.abilities[known]).mean(1)
                    moved = float(np.mean(diff > 8)) if diff.size else 0.0
                    if overlap < 0.7:
                        add('error', f'Chỉ {_pct(overlap)} cầu thủ của lần lưu trước ({last.day}/{last.month}) còn được nhận ra.')
                    elif moved > 0.2:
                        add('error', f'{_pct(moved)} cầu thủ có chỉ số đổi mạnh so với lần lưu trước ({last.day}/{last.month}): '
                                     'cách đọc save có thể đã bị lệch.')
                    else:
                        add('ok', f'Khớp với lần lưu trước ({last.day}/{last.month}/{last.year}): '
                                  f'{_pct(overlap)} cầu thủ nhận ra, {_pct(moved)} đổi chỉ số mạnh.')
        except Exception as exc:
            add('warn', f'Không so được với lần lưu trước: {exc!r}')

    # ---- parts of the app (a failure here only leaves that part empty)
    clubs = [t for t in snap.clubs if not save_reader.is_national(t)]
    if len(clubs) < 150:
        add('warn', f'Chỉ đọc được {len(clubs)} CLB.')
    if not snap.my_fixtures:
        add('warn', 'Không đọc được lịch thi đấu của CLB: trang Lịch thi đấu và Trận tới sẽ trống.')
    else:
        played = [f for f in snap.fixtures if f.flags & 64]
        odd = sum(1 for f in played if max(f.home_goals, f.away_goals) > 20)
        if odd:
            add('warn', f'{odd} trận có tỉ số bất thường (trên 20 bàn).')
        else:
            add('ok', f'Lịch thi đấu: {len(snap.my_fixtures)} trận của CLB, {num(len(played))} trận đã đá trên thế giới.')
    mine = snap.gameplans.get(snap.team_id)
    squad_ids = {int(p['player_id']) for p in snap.squad_players}
    if not mine:
        add('warn', 'Không đọc được Game Plan của bạn: phần so sánh đội hình / chiến thuật đang đặt trong game sẽ trống.')
    else:
        xi = [x['id'] for x in mine['xi']]
        if len(set(xi)) != 11 or not set(xi) <= squad_ids:
            add('warn', 'Đội hình trong Game Plan của bạn đọc ra không khớp đội hình CLB.')
        else:
            cover = len(snap.gameplans) / max(len(clubs), 1)
            (add('ok', f'Game Plan: của bạn và {num(len(snap.gameplans))} CLB ({_pct(cover)}).') if cover >= 0.8 else
             add('warn', f'Chỉ đọc được Game Plan của {_pct(cover)} CLB: phân tích đối thủ có thể thiếu.'))
    rows = [snap.row[p] for p in squad_ids if p in snap.row]
    if rows:
        known = snap.cond >= 0
        share = np.bincount(snap.cond[known], minlength=5).max() / max(known.sum(), 1)
        sq_known = float(np.mean(snap.cond[rows] >= 0))
        if sq_known < 0.8 or share > 0.9:
            add('warn', 'Mũi tên phong độ đọc ra bất thường: đội hình đề xuất có thể không tính đúng phong độ.')
        else:
            add('ok', f'Mũi tên phong độ: {num(int(known.sum()))} cầu thủ.')
        today = int(snap.date.strftime('%Y%m%d'))
        c_ok = float(np.mean(snap.contract_end[rows] > today))
        if c_ok < 0.8:
            add('warn', f'Hợp đồng đọc ra bất thường ({_pct(1 - c_ok)} cầu thủ của bạn đã hết hạn hoặc không rõ).')
    wf = float(np.mean((snap.weak_accuracy >= 1) & (snap.weak_accuracy <= 4))) if n else 1.0
    if wf < 0.95:
        add('warn', 'Chân không thuận đọc ra bất thường.')

    level = 'error' if any(i['level'] == 'error' for i in items) else \
        'warn' if any(i['level'] == 'warn' for i in items) else 'ok'
    return {'level': level, 'items': items, 'save_date': snap.date.isoformat(), 'at': time.strftime('%H:%M:%S')}


def failed(exc):
    """The save could not be decoded at all."""
    return {'level': 'error', 'items': [{'level': 'error', 'text': f'Không giải mã được save: {exc!r}'}],
            'save_date': None, 'at': time.strftime('%H:%M:%S')}


def headline(report):
    for lvl in ('error', 'warn'):
        for i in report.get('items', []):
            if i['level'] == lvl:
                return i['text']
    return ''

"""Backups outside the app and game folders, so the data the AI learns from survives a reinstall,
a deleted folder or a corrupted save. Nothing is ever restored automatically (see README below).

<backup dir>\\<slot> - <club> (<first date>)\\save\\<game date>.sav     the Master League save itself:
        the source of everything Dugout knows; the growth model also learns from these copies.
<backup dir>\\<slot> - <club> (<first date>)\\dugout\\<game date>.zip   Dugout's own data of the career
        (player timeline, conditions, every season's matches of the world, inbox, AI logs, Game Plans
        before each match, market values) plus the shared AI files under _ai\\.

Only saves that passed the health check are copied under their game date; a save that failed it is
kept as chua_kiem_tra_<time>.sav (last 3). Kept: every copy of the last 14 game days, then the last
one of each game month. A new career in the same slot gets its own folder.
"""
import datetime as dt
import json
import os
import re
import shutil
import threading
import time
import zipfile

from . import config, store

KEEP_RECENT_DAYS = 14
UNVERIFIED_KEEP = 3
SHARED = ('ovr_samples.jsonl', 'ovr_weights.json', 'growth_model.json', 'training_report.json', 'health.json', 'edits.json',
          'settings.json')
_LOCK = threading.Lock()

README = """FL26 DUGOUT - SAO LƯU

Dugout tự sao lưu mỗi lần bạn lưu game, sau khi kiểm tra save đọc đúng.
Mỗi career có một thư mục: <slot save> - <CLB> (<ngày bắt đầu theo dõi>).

  save\\<ngày trong game>.sav
      Bản sao file save Master League. Đây là dữ liệu gốc: mọi thứ Dugout biết đều đọc từ đây,
      và AI phát triển cầu thủ học thêm từ các bản sao này khi bấm "Huấn luyện lại AI".
      chua_kiem_tra_*.sav: save không qua được bước kiểm tra (giữ 3 bản gần nhất để xem lại).
  dugout\\<ngày trong game>.zip
      Dữ liệu riêng của Dugout: chỉ số mọi cầu thủ qua từng lần lưu, mũi tên phong độ và chấn thương,
      mọi trận đã đá trên thế giới qua các mùa, Game Plan hai đội trước mỗi trận của bạn, hộp thư,
      dự đoán của AI, giá trị cầu thủ (khi game mở). Thư mục _ai: các file AI dùng chung.
  truoc_khi_sua\\<thời gian>_<slot>.sav  và  <thời gian save>_<slot>_truoc_sua_trong_game.sav
      Save nguyên vẹn ngay trước mỗi lần Dugout sửa save (đổi / học vị trí, hoàn tác), và save hiện có
      trước lần đổi vị trí đầu tiên ngay trong game (tên có "truoc_sua_trong_game").
      Không bao giờ tự xóa. Nếu game báo lỗi save sau khi sửa: thoát game, chép file này đè lên save.

Giữ lại: mọi bản của 14 ngày (trong game) gần nhất; cũ hơn thì giữ bản cuối cùng của mỗi tháng.
Khoảng 20 MB mỗi bản save, tức khoảng 250 MB mỗi mùa.

KHÔI PHỤC (làm tay, Dugout không bao giờ tự ghi đè)
  Dữ liệu Dugout: tắt Dugout, giải nén file .zip vào
      {careers}\\<slot save, ví dụ 2026_ML00000002>
  Save game: tắt game, chép save hiện tại ra chỗ khác trước, rồi chép file .sav vào
      {saves}\\<thư mục>\\save
  và đổi tên thành đúng tên slot (ví dụ ML00000002).

Đổi nơi sao lưu: tạo file {settings} với nội dung {{"backup_dir": "E:\\\\Dugout Backup"}}
"""


def root():
    return config.backup_dir()


def _safe(name):
    return re.sub(r'[<>:"/\\|?*]+', '', name).strip() or 'career'


def folder_for(career_key, snap=None, since=None):
    """This career's backup folder, named after the slot, the club and the day Dugout started following
    the career. Named once (at the first backup) and remembered in the career's backup.json, which
    moves to the archive when a new career starts in the slot."""
    meta_path = os.path.join(config.CAREERS_DIR, career_key, 'backup.json')
    meta = store._read_json(meta_path, {})
    if not meta.get('folder'):
        if snap is None or not os.path.isdir(os.path.dirname(meta_path)):
            return os.path.join(root(), _safe(career_key))
        meta = {'folder': _safe(f'{career_key} - {snap.team_name} ({(since or snap.date).isoformat()})'),
                'created': dt.datetime.now().isoformat(timespec='seconds')}
        store.write_json(meta_path, meta, compact=False)
    return os.path.join(root(), meta['folder'])


def _readme():
    path = os.path.join(root(), 'DOC TOI.txt')
    text = README.format(careers=config.CAREERS_DIR, saves=config.KONAMI_DIR, settings=config.SETTINGS)
    text = text.replace('\n', '\r\n')
    try:
        if open(path, encoding='utf-8-sig', newline='').read() == text:
            return
    except OSError:
        pass
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(text)


def run(career_key, save_path, save_key, snap=None, verified=True, career=None):
    """Back up after a load. `save_key` = (path, mtime, size) of the file the snapshot was decoded
    from: a save the game rewrote meanwhile is left for the next load."""
    with _LOCK:
        since = career.timeline.dates[0] if career is not None and career.timeline.dates else None
        base = folder_for(career_key, snap if verified else None, since)
        os.makedirs(base, exist_ok=True)
        _readme()
        out = {}
        if verified and snap is not None:
            out['save'] = _copy_save(save_path, save_key, os.path.join(base, 'save'), f'{snap.date.isoformat()}.sav')
            if career is not None:
                out['zip'] = _zip_career(career, os.path.join(base, 'dugout'), snap)
            _prune(os.path.join(base, 'save'), '.sav')
            _prune(os.path.join(base, 'dugout'), '.zip')
        else:
            out['save'] = _copy_save(save_path, save_key, os.path.join(base, 'save'),
                                     'chua_kiem_tra_' + time.strftime('%Y%m%d_%H%M%S') + '.sav')
            _prune_unverified(os.path.join(base, 'save'))
        return out


def _copy_save(src, key, folder, name):
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, name)
    st = os.stat(src)
    if (st.st_mtime, st.st_size) != (key[1], key[2]):
        return None
    if os.path.exists(dst):
        d = os.stat(dst)
        if d.st_size == st.st_size and int(d.st_mtime) == int(st.st_mtime):
            return dst                                   # this very save is already backed up
    tmp = dst + '.tmp'
    shutil.copy2(src, tmp)
    st = os.stat(src)
    if (st.st_mtime, st.st_size) != (key[1], key[2]) or os.path.getsize(tmp) != key[2]:
        os.remove(tmp)                                   # the game wrote the save meanwhile
        return None
    os.replace(tmp, dst)
    return dst


def _zip_career(career, folder, snap):
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, f'{snap.date.isoformat()}.zip')
    tmp = dst + '.tmp'
    info = {'career': career.key, 'club': snap.team_name, 'game_date': snap.date.isoformat(),
            'backed_up': dt.datetime.now().isoformat(timespec='seconds'), 'save': os.path.basename(snap.save_path)}
    with career.lock:                                    # no JSON of the career is rewritten meanwhile
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for dirpath, _dirs, files in os.walk(career.dir):
                for f in files:
                    if f == 'bundle.json' or '.tmp' in f:
                        continue
                    full = os.path.join(dirpath, f)
                    packed = f.endswith(('.npz', '.gz', '.zip'))
                    z.write(full, os.path.relpath(full, career.dir),
                            compress_type=zipfile.ZIP_STORED if packed else zipfile.ZIP_DEFLATED)
            for f in SHARED:
                p = os.path.join(config.DATA_DIR, f)
                if os.path.exists(p):
                    z.write(p, '_ai/' + f)
            z.writestr('_info.json', json.dumps(info, ensure_ascii=False, indent=1))
    os.replace(tmp, dst)
    return dst


def _dated(folder, ext):
    out = []
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            if f.endswith(ext):
                try:
                    out.append((dt.date.fromisoformat(f[:-len(ext)]), f))
                except ValueError:
                    pass
    return sorted(out)


def _prune(folder, ext):
    files = _dated(folder, ext)
    if not files:
        return
    newest = files[-1][0]
    keep, last_of_month = set(), {}
    for d, f in files:
        if 0 <= (newest - d).days <= KEEP_RECENT_DAYS:
            keep.add(f)
        last_of_month[(d.year, d.month)] = f
    keep |= set(last_of_month.values())
    for _d, f in files:
        if f not in keep:
            try:
                os.remove(os.path.join(folder, f))
            except OSError:
                pass


def _prune_unverified(folder):
    names = sorted(f for f in os.listdir(folder) if f.startswith('chua_kiem_tra_') and f.endswith('.sav'))
    for f in names[:-UNVERIFIED_KEEP]:
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass


def status(career_key):
    """What is backed up for this career, for the app."""
    base = folder_for(career_key)
    out = {'root': root(), 'dir': base, 'saves': 0, 'zips': 0, 'unverified': 0, 'mb': 0.0,
           'last': None, 'last_date': None, 'first_date': None}
    newest = 0.0
    for sub, ext, k in (('save', '.sav', 'saves'), ('dugout', '.zip', 'zips')):
        folder = os.path.join(base, sub)
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if not f.endswith(ext):
                continue
            p = os.path.join(folder, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out['mb'] += st.st_size / 1048576
            if f.startswith('chua_kiem_tra_'):
                out['unverified'] += 1
                continue
            out[k] += 1
            newest = max(newest, st.st_mtime)
        dates = _dated(folder, ext)
        if dates and sub == 'save':
            out['first_date'], out['last_date'] = dates[0][0].isoformat(), dates[-1][0].isoformat()
    out['mb'] = round(out['mb'], 1)
    out['last'] = time.strftime('%d/%m %H:%M', time.localtime(newest)) if newest else None
    return out


def backup_saves(same_version_prefix, limit=12):
    """Backed-up saves of this game-data version (for the growth model), spread over time."""
    out = []
    r = root()
    if not os.path.isdir(r):
        return out
    for d in os.listdir(r):
        if same_version_prefix and not d.startswith(same_version_prefix + '_'):
            continue
        for date, f in _dated(os.path.join(r, d, 'save'), '.sav'):
            out.append((date, os.path.join(r, d, 'save', f)))
    out.sort()
    if len(out) > limit:
        step = (len(out) - 1) / (limit - 1)
        out = [out[round(k * step)] for k in range(limit)]
    return [p for _d, p in out]

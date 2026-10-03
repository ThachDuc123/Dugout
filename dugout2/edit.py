"""Careful edits of the Master League save: a player's registered position and position grades.

The game itself has no screen for this. Every edit:
  1. refuses while FL26 is running (the game would overwrite the save, or read a half-written one);
  2. decrypts the save and checks its SHA-512 blocks;
  3. changes only the bits asked for in the career player table, recompresses only the touched
     256 KB chunks to exactly their old size (nothing else in the file moves), re-encrypts;
  4. decrypts the result again and checks that the only bytes that differ are the ones meant to;
  5. copies the untouched save to the backup folder (truoc_khi_sua\\, never deleted automatically);
  6. replaces the save only if the game did not write it meanwhile, then reads it back.
Each edit is logged (data\\edits.json) and can be undone: undo writes the old values back into
the current save (keeping everything played since), or the whole backup can be put back.
While the game runs, the same edits go into its memory instead (ingame.py) and share this log.

The preferred foot is not in the Master League save (the game takes it from its database), so it
is not edited here.
"""
import ctypes
import datetime as dt
import hashlib
import os
import shutil
import threading
import time
from ctypes import wintypes

import numpy as np

from . import backup, config, store, terms
from .pes import career as pc
from .pes import container, crypto

GAME_PROCESSES = {'fl_2026.exe', 'pes2021.exe', 'fl_2025.exe'}
LOG = os.path.join(config.DATA_DIR, 'edits.json')
_LOCK = threading.Lock()


class EditError(Exception):
    pass


# --------------------------------------------------------------------------- the game
class _ProcessEntry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]


def running_processes():
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)            # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return set()
    names = set()
    try:
        e = _ProcessEntry()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            names.add(e.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return names


def game_running():
    return bool(running_processes() & GAME_PROCESSES)


# ------------------------------------------------------------------------ the fields
def _fields(table, start):
    rec = table[start:start + pc.RECORD]
    return {'position': pc.position(rec), 'style': pc.read_bits(table, start, pc.STYLE_BIT, 5),
            'grades': {p: pc.grade(table, start, p) for p in pc.POSITIONS}}


def _location(field):
    """(offset from record start in bits, width) of a field name: position | style | grade:<POS>."""
    if field == 'position':
        return pc.POSITION_AT[0] * 8 + pc.POSITION_AT[1], pc.POSITION_AT[2]
    if field == 'style':
        return pc.STYLE_BIT, 5
    if field.startswith('grade:') and field[6:] in pc.GRADE_BITS:
        return pc.GRADE_BITS[field[6:]], 2
    raise EditError(f'Trường không hợp lệ: {field}')


def _valid(field, value):
    if field == 'position':
        return 0 <= value <= 12
    if field == 'style':
        return value in terms.CAREER_STYLE_TO_DB
    return 0 <= value <= 2


def position_writes(table, start, player_id, position, grade_a=True):
    """The field writes that make `position` the player's registered position."""
    return writes_for(_fields(table, start), player_id, 'position', position, grade_a)


def writes_for(cur, player_id, action, position, grade_a=True, value=None):
    """Field writes from the current values {'position', 'style', 'grades'} of one player.
    action 'position': make `position` the registered one (goalkeeper and outfield styles do not
    mix, so moving between the two clears the style); 'learn': raise its grade one step;
    'style': the career style number `value` (0 = none)."""
    if action == 'style':
        value = int(value)
        if value not in terms.CAREER_STYLE_TO_DB:
            raise EditError('Phong cách không hợp lệ.')
        style_db = terms.CAREER_STYLE_TO_DB[value]
        if value and (style_db in pc.GK_STYLES) != (cur['position'] == 0):
            raise EditError('Phong cách thủ môn chỉ dành cho thủ môn, và ngược lại.')
        if cur['style'] == value:
            raise EditError('Cầu thủ đã có phong cách này.')
        return [{'player_id': player_id, 'field': 'style', 'old': cur['style'], 'new': value}]
    pos_name = pc.POSITIONS[position]
    if action == 'learn':
        g = cur['grades'][pos_name]
        if g >= 2:
            raise EditError(f'Đã thạo vị trí {pos_name} (hạng A) rồi.')
        return [{'player_id': player_id, 'field': 'grade:' + pos_name, 'old': g, 'new': g + 1}]
    writes = []
    if cur['position'] != position:
        writes.append({'player_id': player_id, 'field': 'position', 'old': cur['position'], 'new': position})
    if grade_a and cur['grades'][pos_name] != 2:
        writes.append({'player_id': player_id, 'field': 'grade:' + pos_name, 'old': cur['grades'][pos_name], 'new': 2})
    was_gk, now_gk = cur['position'] == 0, position == 0
    style_db = terms.CAREER_STYLE_TO_DB.get(cur['style'], 0)
    if cur['style'] and was_gk != now_gk and (style_db in pc.GK_STYLES) != now_gk:
        writes.append({'player_id': player_id, 'field': 'style', 'old': cur['style'], 'new': 0})
    return writes


# ------------------------------------------------------------------------ the edit
def _record_starts(table):
    return {pc.snapshot_id(mid, cidx): start for start, mid, cidx in pc.records(table)}


def _read_save(save_path):
    raw = open(save_path, 'rb').read()
    st = os.stat(save_path)
    s = crypto.decrypt(raw)                                       # checks the SHA-512 blocks
    chunks = container.locate(s.data)                             # the exact layout, or refuse
    table = bytearray(container.inflate(s.data, chunks))
    return raw, (st.st_mtime, st.st_size), s, chunks, table


def apply(save_path, career_key, build, label, allowed_ids=None):
    """Edit the save. `build(table, starts)` returns the field writes
    [{'player_id', 'field', 'old', 'new'}]; values are checked against the current save."""
    with _LOCK:
        if game_running():
            raise EditError('Game đang mở. Thoát hẳn FL26 rồi bấm lại: sửa save khi game đang chạy thì game sẽ '
                            'ghi đè mất thay đổi hoặc làm hỏng save.')
        raw, stamp, s, chunks, table = _read_save(save_path)
        original = bytes(table)
        starts = _record_starts(table)
        writes = build(table, starts)
        if not writes:
            return {'ok': True, 'changed': 0, 'message': 'Không có gì cần đổi: save đã đúng như vậy.'}
        expected = set()
        for w in writes:
            pid = int(w['player_id'])
            if allowed_ids is not None and pid not in allowed_ids:
                raise EditError('Chỉ sửa được cầu thủ của CLB bạn đang dẫn dắt.')
            start = starts.get(pid)
            if start is None:
                raise EditError(f'Không tìm thấy cầu thủ {pid} trong save.')
            bit, width = _location(w['field'])
            value = int(w['new'])
            if not _valid(w['field'], value):
                raise EditError(f'Giá trị không hợp lệ cho {w["field"]}: {value}')
            now = pc.read_bits(table, start, bit, width)
            if w.get('old') is not None and now != int(w['old']):
                raise EditError('Save đã thay đổi so với lúc chuẩn bị sửa (có thể bạn vừa lưu game). Hãy thử lại.')
            w['old'] = now
            pc.write_bits(table, start, bit, width, value)
            absolute = start * 8 + bit
            expected.update(range(absolute // 8, (absolute + width + 7) // 8))
        new_table = bytes(table)
        new_data, rewritten = container.replace(s.data, chunks, new_table)
        new_raw = crypto.encrypt(crypto.SaveFile(s.key, s.file_header, s.description, s.logo, new_data, s.serial))

        # check the result before touching anything
        if len(new_raw) != len(raw):
            raise EditError('Kiểm tra thất bại: kích thước save thay đổi.')
        check = crypto.decrypt(new_raw)
        if (check.description, check.logo, check.serial) != (s.description, s.logo, s.serial):
            raise EditError('Kiểm tra thất bại: phần ngoài dữ liệu bị đổi.')
        if container.inflate(check.data) != new_table:
            raise EditError('Kiểm tra thất bại: bảng cầu thủ đọc lại không khớp.')
        diff = np.nonzero(np.frombuffer(original, np.uint8) != np.frombuffer(new_table, np.uint8))[0]
        if not set(diff.tolist()) <= expected:
            raise EditError('Kiểm tra thất bại: có byte ngoài dự định bị đổi.')
        moved = np.nonzero(np.frombuffer(new_data, np.uint8) != np.frombuffer(s.data, np.uint8))[0]
        inside = np.zeros(len(new_data), dtype=bool)
        for c in rewritten:
            inside[c.stream:c.stream + c.comp] = True
        if moved.size and not inside[moved].all():
            raise EditError('Kiểm tra thất bại: dữ liệu ngoài các khối được sửa bị đổi.')

        # back up the untouched save, then replace it if the game did not write it meanwhile
        folder = os.path.join(backup.folder_for(career_key), 'truoc_khi_sua')
        os.makedirs(folder, exist_ok=True)
        stamp_txt = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(folder, f'{stamp_txt}_{os.path.basename(save_path)}.sav')
        with open(backup_path, 'wb') as f:
            f.write(raw)
        st = os.stat(save_path)
        if (st.st_mtime, st.st_size) != stamp:
            raise EditError('Game vừa ghi save trong lúc sửa: không ghi gì cả. Hãy thử lại.')
        tmp = save_path + '.dugout.tmp'
        with open(tmp, 'wb') as f:
            f.write(new_raw)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(20):
            try:
                os.replace(tmp, save_path)
                break
            except PermissionError:
                time.sleep(0.25)
        else:
            os.remove(tmp)
            raise EditError('Không ghi được save (file đang bị chương trình khác mở).')
        if open(save_path, 'rb').read() != new_raw:
            shutil.copy2(backup_path, save_path)
            raise EditError('Đọc lại save sau khi ghi không khớp: đã trả lại save gốc.')

        entry = record({'label': label, 'career': career_key, 'save': save_path, 'mode': 'save', 'writes': writes,
                        'backup': backup_path, 'sha_before': hashlib.sha256(raw).hexdigest(),
                        'sha_after': hashlib.sha256(new_raw).hexdigest()})
        return {'ok': True, 'changed': len(writes), 'entry': entry,
                'message': f'Đã sửa save ({len(writes)} thay đổi). Bản gốc: {backup_path}'}


def record(entry):
    """Add an edit to the log (newest first) with a unique id; returns the stored entry."""
    log = store._read_json(LOG, [])
    now = dt.datetime.now()
    entry_id = now.strftime('%Y%m%d_%H%M%S')
    while any(e['id'] == entry_id for e in log):
        entry_id += '_'
    entry = {'id': entry_id, 'time': now.isoformat(timespec='seconds'), **entry}
    log.insert(0, entry)
    store.write_json(LOG, log[:500], compact=False)
    return entry


def update(entry_id, **fields):
    log = store._read_json(LOG, [])
    for e in log:
        if e['id'] == entry_id:
            e.update(fields)
    store.write_json(LOG, log, compact=False)


def change_position(save_path, career_key, player_id, position, grade_a, label, allowed_ids, action='position',
                    value=None):
    def build(table, starts):
        start = starts.get(int(player_id))
        if start is None:
            raise EditError(f'Không tìm thấy cầu thủ {player_id} trong save.')
        return writes_for(_fields(table, start), int(player_id), action,
                          None if position is None else int(position), grade_a, value)
    return apply(save_path, career_key, build, label, allowed_ids)


def reverse_writes(entry):
    return [{'player_id': w['player_id'], 'field': w['field'], 'old': w['new'], 'new': w['old']}
            for w in reversed(entry['writes'])]


def undo(entry_id, label, in_game=None):
    """Put back the old values of one edit, keeping everything played since. With the game
    running, `in_game(writes, label)` writes them into the game's memory; otherwise they go into
    the current save (fields the game never saved are already old and are left alone)."""
    entry = next((e for e in store._read_json(LOG, []) if e['id'] == entry_id), None)
    if entry is None:
        raise EditError('Không tìm thấy lần sửa này.')
    if entry.get('undone'):
        raise EditError('Lần sửa này đã được hoàn tác.')
    reverse = reverse_writes(entry)
    if in_game is not None:
        out = in_game([dict(w) for w in reverse], label)
    else:
        def build(table, starts):
            todo = []
            for w in reverse:
                start = starts.get(int(w['player_id']))
                if start is None:
                    raise EditError(f'Không tìm thấy cầu thủ {w["player_id"]} trong save.')
                bit, width = _location(w['field'])
                now = pc.read_bits(table, start, bit, width)
                if now == int(w['new']):
                    continue                   # already the old value (the game never saved the edit)
                if now != int(w['old']):
                    raise EditError('Save đang có giá trị khác cả trước lẫn sau lần sửa này (có thể game đã đổi '
                                    'tiếp): không hoàn tác tự động được.')
                todo.append(dict(w))
            return todo
        out = apply(entry['save'], entry['career'], build, label)
    update(entry_id, undone=out.get('entry', {}).get('id') or True)
    return out


def history(career_key=None):
    return [e for e in store._read_json(LOG, []) if career_key is None or e.get('career') == career_key]

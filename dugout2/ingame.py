"""Changing players from inside the game, and the live link to the running game.

The Sider module modules\\Dugout.lua adds a "Dugout" page to Sider's overlay (Space, then key 1
to reach it). It is only a screen: it shows content\\dugout\\state.txt and writes the manager's
choices to content\\dugout\\request.txt. This module answers those requests while FL26 runs:
registered position, learning a position (at once, or over weeks: training.py), playing style and
preferred foot.

Changes go into the game's memory (gamemem): the running game keeps the career in memory and
writes it to the save when it saves, so this is the only way to change it without quitting.
Before the first change of a save, that save is copied to the backup folder (truoc_khi_sua\\);
every change is logged like a save edit and can be undone, in the game or later in the save;
after the next save Dugout checks that the game stored it. The preferred foot is not in the save
at all: Dugout keeps the swaps (feet.json) and writes them again whenever the career is loaded.

While the game runs, the link also reads the transfer / salary budget and the players' market
values for the app (live.py), read-only.
"""
import datetime as dt
import os
import shutil
import threading
import time
import traceback

import numpy as np

from . import backup, config, edit, gamemem, store, terms
from .pes import career as pc

FOLDER = os.path.join(config.SIDER_DIR, 'content', 'dugout')
STATE = os.path.join(FOLDER, 'state.txt')
ALIVE = os.path.join(FOLDER, 'alive.txt')
REQUEST = os.path.join(FOLDER, 'request.txt')
POS = terms.POSITIONS
VERDICTS = ('Không hợp', 'Tạm được', 'Hợp', 'Rất hợp')
FOOT = ('Phải', 'Trái')
TICK_SECONDS = 10            # live link: re-read the table, re-apply feet, budget, training
SCAN_EVERY = 180             # a full memory search while the career is not found
SCAN_AFTER = 45              # ... not before the game has run this long
MARKET_EVERY = 60
MARKET_SEARCH_EVERY = 600


def verdict(fit, delta):
    """How well a position suits a player: position fit (0-100, from his abilities and build) and
    his OVR there compared with his registered position."""
    if fit >= 80 and delta >= -1:
        return 3
    if fit >= 65 and delta >= -3:
        return 2
    if fit >= 50 and delta >= -6:
        return 1
    return 0


def _clean(text, size=None):
    text = str(text).replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')
    return text if size is None or len(text) <= size else text[:size - 1] + '…'


def style_name(career_style):
    return terms.style_label(terms.CAREER_STYLE_TO_DB.get(int(career_style), 0)) or 'Không có phong cách'



def _match_on():
    """A match is loading or being played (the live map is on)."""
    try:
        from . import matchlive
        t = matchlive.TRACKER
        return t is not None and t.state in ('loading', 'live', 'searching', 'waiting')
    except Exception:
        return False

class Feet:
    """Preferred-foot swaps of one career: {player id: {'left', 'orig_left', 'name', 'time'}}."""

    def __init__(self, career_dir):
        self.path = os.path.join(career_dir, 'feet.json')
        self.data = {int(k): v for k, v in store._read_json(self.path, {}).items()}

    def get(self, pid):
        return self.data.get(int(pid))

    def set(self, pid, left, orig_left, name):
        self.data[int(pid)] = {'left': int(left), 'orig_left': int(orig_left), 'name': name,
                               'time': dt.datetime.now().isoformat(timespec='seconds')}
        self._save()

    def remove(self, pid):
        self.data.pop(int(pid), None)
        self._save()

    def _save(self):
        store.write_json(self.path, {str(k): v for k, v in self.data.items()}, compact=False)


class Memory:
    """The live player table of the running game, found and checked against the last save."""

    def __init__(self, log):
        self.log = log
        self.proc = None
        self.base, self.count = None, gamemem.COUNT
        self.game_date = None
        self.cal = None
        self.cal_checked = None
        self.status, self.message = 'off', 'Game chưa mở.'

    def close(self):
        if self.proc:
            self.proc.close()
        self.proc, self.base, self.cal_checked, self.game_date = None, None, None, None

    @property
    def pinned(self):
        return self.base is not None and self.count == gamemem.COUNT

    def table(self, snap, scan=True, quiet=False):
        """A fresh read of the live table (calibrated), or MemError. `scan`: search the whole
        memory if the table is not where it was; `quiet`: a failed try leaves the status alone."""
        before = self.status, self.message
        try:
            return self._table(snap, scan)
        except gamemem.MemError as exc:
            if quiet:
                self.status, self.message = before
            else:
                self.status, self.message = 'error', str(exc)
            raise

    def _table(self, snap, scan):
        game = gamemem.find_game()
        if not game:
            self.close()
            self.status, self.message = 'off', 'Game chưa mở.'
            raise gamemem.MemError('Game chưa mở.')
        if self.proc is None or self.proc.pid != game[0] or not self.proc.alive():
            self.close()
            self.proc = gamemem.Process(*game)
        table = None
        if self.base:
            raw = self.proc.read(self.base, self.count * gamemem.STRIDE)
            if raw:
                table = gamemem.Table(self.base, raw)
                if gamemem._match(table, snap)[0] < 0.85:
                    table = None
            if table is None:
                self.base, self.cal_checked = None, None
        if table is None:
            if scan:
                self.status, self.message = 'searching', 'Đang dò bộ nhớ game…'
            found = gamemem.locate(self.proc, snap, self.log, scan=scan)
            if found is None:
                raise gamemem.MemError('Chưa thấy career này trong bộ nhớ game. Hãy vào Master League (tải đúng '
                                       'save mà Dugout đang theo dõi) rồi mở lại trang này.')
            self.base, self.count = found
            raw = self.proc.read(self.base, self.count * gamemem.STRIDE)
            if not raw:
                self.base = None
                raise gamemem.MemError('Không đọc được bảng cầu thủ trong bộ nhớ game.')
            table = gamemem.Table(self.base, raw)
            self.cal_checked = None
        if self.pinned:                          # the table start is pinned: its clock names the club
            date, ident = gamemem.clock(self.proc, self.base)
            if not gamemem.team_matches(ident, snap.team_id):
                self.base = None
                raise gamemem.MemError('Game đang mở một career khác (CLB khác) với save Dugout đang theo dõi. Hãy '
                                       'lưu game để Dugout đọc đúng career rồi thử lại.')
            self.game_date = date
        else:
            self.game_date = None
        if self.cal_checked != (self.base, snap.save_mtime):
            self.cal = self._calibration(table, snap)
            self.cal_checked = (self.base, snap.save_mtime)
        missing = [f'grade:{p}' for p in POS if not gamemem.usable(self.cal, f'grade:{p}')]
        if missing:
            self.status = 'partial'
            self.message = ('Chưa xác định chắc chỗ lưu hạng vị trí ' + ', '.join(m[6:] for m in missing)
                            + ' trong bộ nhớ game: các vị trí đó chỉ xem, không sửa.')
        else:
            self.status, self.message = 'ready', 'Đã kết nối bộ nhớ game.'
        return table

    def _calibration(self, table, snap):
        cached = gamemem.load_calibration()
        if cached and cached.get('version') == gamemem.CAL_VERSION and self._still_good(cached, table, snap):
            return cached
        cal = gamemem.calibrate(table, snap, self.log)
        if cal['checks']['position'] < 0.9:
            raise gamemem.MemError('Bảng cầu thủ trong bộ nhớ game không khớp với save (vị trí đăng ký chỉ khớp '
                                   f'{cal["checks"]["position"] * 100:.0f}%): không sửa gì.')
        gamemem.save_calibration(cal)
        return cal

    def _still_good(self, cal, table, snap):
        """The saved field locations still read the save's values on this table."""
        _s, live, save = gamemem._match(table, snap)
        if len(live) < 1000:
            return False
        rows = table.rows[live]
        for p, name in enumerate(POS):
            loc = gamemem.location(cal, 'grade:' + name)
            if loc is None:
                continue
            bit, width, tr = loc
            got = gamemem.decode(tr, gamemem.field(rows, bit, width))
            truth = snap.grades[save, p]
            for part in (truth > 0, truth == 0):
                if part.any() and (got[part] == truth[part]).mean() < 0.95:
                    return False
        return True

    # ------------------------------------------------------------ player values
    def values(self, table, pid):
        slot = table.slot.get(int(pid))
        if slot is None:
            return None
        return self._decode(bytes(table.rows[slot]))

    def _decode(self, rec):
        cal = self.cal
        out = {'position': gamemem.read_field(rec, *gamemem.POSITION_FIELD), 'grades': {}, 'style': 0, 'foot': None,
               'known': set()}
        for name in POS:
            loc = gamemem.location(cal, 'grade:' + name)
            if loc:
                bit, width, tr = loc
                out['grades'][name] = gamemem.decode(tr, gamemem.read_field(rec, bit, width))
                out['known'].add('grade:' + name)
        for name in ('style', 'foot'):
            loc = gamemem.location(cal, name)
            if loc:
                bit, width, tr = loc
                out[name] = gamemem.decode(tr, gamemem.read_field(rec, bit, width))
                out['known'].add(name)
        return out

    def write(self, table, writes):
        """Write field changes into the game's memory, each checked before and after."""
        by_pid = {}
        for w in writes:
            by_pid.setdefault(int(w['player_id']), []).append(w)
        done = []
        try:
            for pid, ws in by_pid.items():
                slot = table.slot.get(pid)
                if slot is None:
                    raise edit.EditError('Không tìm thấy cầu thủ này trong bộ nhớ game.')
                addr = table.address(slot)
                orig = self.proc.read(addr, gamemem.STRIDE)
                if orig is None or gamemem._keys(np.frombuffer(orig, np.uint8).reshape(1, -1))[0] != pid:
                    raise edit.EditError('Bản ghi cầu thủ trong bộ nhớ game vừa thay đổi. Thử lại.')
                rec = bytearray(orig)
                for w in ws:
                    locs = gamemem.locations(self.cal, w['field'])
                    if not locs:
                        what = {'style': 'phong cách chơi', 'foot': 'chân thuận'}.get(w['field'], w['field'].replace('grade:', 'hạng '))
                        raise edit.EditError(f'Chưa xác định chắc chỗ lưu {what} trong bộ nhớ game: không sửa.')
                    bit, width, tr = locs[0]
                    now = gamemem.decode(tr, pc.read_bits(rec, 0, bit, width))
                    if w.get('old') is not None and now != int(w['old']):
                        raise edit.EditError('Giá trị trong game đã khác lúc chuẩn bị sửa. Mở lại trang và thử lại.')
                    w['old'] = now
                    for bit, width, tr in locs:
                        pc.write_bits(rec, 0, bit, width, gamemem.encode(tr, int(w['new'])))
                changed = [k for k in range(gamemem.STRIDE) if rec[k] != orig[k]]
                done.append((addr, orig, changed))
                for k in changed:
                    if not self.proc.write(addr + k, bytes([rec[k]])):
                        raise edit.EditError('Windows không cho ghi vào bộ nhớ game.')
                after = self.proc.read(addr, gamemem.STRIDE)
                if after is None or any(after[k] != rec[k] for k in changed):
                    raise edit.EditError('Đọc lại bộ nhớ game sau khi ghi không khớp.')
        except Exception:
            for addr, orig, changed in done:          # put back what was already written
                for k in changed:
                    self.proc.write(addr + k, orig[k:k + 1])
            raise
        return writes


class Bridge:
    """Answers the in-game page, does edits in the game's memory (also for the web app) and keeps
    the live link (feet, training, budget, market values) while the game runs."""

    def __init__(self, engine):
        self.e = engine
        self.mem = Memory(engine.log)
        self.lock = threading.RLock()
        self.game = None
        self.game_since = None
        self.game_left = time.time()
        self.opened = False
        self.last_seq = None
        self.req_stamp = None
        self.state_version = None
        self.result = None
        self.backed_up = set()
        self._feet = None
        self.last_tick = self.last_scan = 0.0
        self.market_span, self.market_tried, self.market_read = None, 0.0, 0.0
        self.market_values = None
        self.feet_applied = set()
        self.last_state = 0.0
        os.makedirs(FOLDER, exist_ok=True)
        threading.Thread(target=self._run, daemon=True).start()

    def feet(self):
        key = self.e.career.key if self.e.career else None
        if self._feet is None or self._feet[0] != key:
            self._feet = (key, Feet(self.e.career.dir) if key else None)
        return self._feet[1]

    # ------------------------------------------------------------------- loop
    def _run(self):
        last_game_check = last_alive = 0.0
        try:                                    # an old request must not run when the game starts
            self.req_stamp = self._stamp()
            self.last_seq = self._read_request()[0] if self.req_stamp else None
        except Exception:
            pass
        while True:
            try:
                now = time.time()
                if now - last_game_check > 2:
                    last_game_check = now
                    game = gamemem.find_game()
                    if bool(game) != bool(self.game):
                        if game:
                            self.game_since = now
                            self.mem.status = 'idle'
                            self.mem.message = ('Game đang mở. Dugout kết nối bộ nhớ game khi vào Master League '
                                                '(hoặc khi bạn mở trang DUGOUT trong game).')
                            self.e.live.off('Game đang mở: vào Master League để Dugout đọc ngân sách')
                        else:
                            self._game_closed(now)
                    self.game = game
                    self.e.game_on = bool(game)
                if self.game:
                    if now - last_alive > 2:
                        last_alive = now
                        self._write(ALIVE, f'{int(now)}\n')
                    stamp = self._stamp()
                    if stamp and stamp != self.req_stamp:
                        self.req_stamp = stamp
                        self._handle()
                    elif self.opened and self.state_version != self.e.version:
                        self.write_state()                    # a new save was read: refresh the page
                    elif now - self.last_tick > TICK_SECONDS:
                        self.last_tick = now
                        self._tick()
                time.sleep(0.2 if self.game else 1.0)
            except Exception as exc:
                self.e.log('Trang trong game lỗi: ' + repr(exc))
                traceback.print_exc()
                time.sleep(2)

    def _game_closed(self, now):
        self.game_left, self.opened = now, False
        self.mem.close()
        self.mem.status, self.mem.message = 'off', 'Game chưa mở.'
        self.market_span, self.market_values, self.feet_applied = None, None, set()
        self.e.live.off('')

    def _tick(self):
        """The live link: find the career in memory (cheaply, a full search now and then), then
        keep the preferred-foot swaps, run position training and read budget / market values."""
        e, snap = self.e, self.e.snap
        if snap is None or e.career is None or e.training:
            return
        now = time.time()
        # no pass over the game's memory while a match loads or is played (it made the game stutter, and
        # the live map searches then): the budget and values wait for the menus
        busy = _match_on()
        scan = (self.mem.base is None and now - self.last_scan > SCAN_EVERY
                and now - (self.game_since or now) > SCAN_AFTER and not busy)
        if scan:
            self.last_scan = now
        try:
            table = self.mem.table(snap, scan=scan, quiet=not scan)
        except gamemem.MemError:
            e.live.off('Game đang mở: vào Master League để Dugout đọc ngân sách')
            return
        changed = self._apply_feet(snap, table)
        try:
            changed += e.training_check(self.mem.game_date or snap.date, in_game=True)
        except Exception as exc:
            e.log('Tập luyện vị trí lỗi: ' + repr(exc))
            traceback.print_exc()
        self._read_live(snap)
        if self.opened and (changed or now - self.last_state > 15):
            self.write_state()                   # keep the in-game page current

    def _read_live(self, snap):
        now = time.time()
        budget = None
        if self.mem.pinned and gamemem.budget_code_present():
            budget = gamemem.read_budget(self.mem.proc, self.mem.base)
        if self.market_span is None and now - self.market_tried > MARKET_SEARCH_EVERY and not _match_on():
            self.market_tried = now
            try:
                self.market_span = gamemem.find_market(self.mem.proc, snap, near=self.mem.base, log=self.e.log)
            except Exception:
                traceback.print_exc()
        if self.market_span and now - self.market_read > MARKET_EVERY:
            self.market_read = now
            vals = gamemem.read_market(self.mem.proc, *self.market_span)
            if vals is None or len(vals) < 200:
                self.market_span, self.market_values = None, None
            else:
                self.market_values = vals
        if budget is None and not self.market_values:
            self.e.live.off('Chưa đọc được ngân sách từ game')
            return
        self.e.live.update(budget=budget, values=self.market_values or {}, date=self.mem.game_date or snap.date,
                           team=snap.team_id)

    def _apply_feet(self, snap, table):
        feet = self.feet()
        if not feet or not feet.data or not gamemem.usable(self.mem.cal, 'foot'):
            return 0
        writes = []
        for pid, f in feet.data.items():
            vals = self.mem.values(table, pid)
            if vals and 'foot' in vals['known'] and vals['foot'] != f['left']:
                writes.append({'player_id': pid, 'field': 'foot', 'old': vals['foot'], 'new': f['left']})
        if writes:
            with edit._LOCK:
                self.mem.write(table, writes)
            names = ', '.join(feet.data[w['player_id']]['name'] for w in writes)
            self.e.log(f'Áp lại chân thuận đã đổi trong game: {names}.')
        return len(writes)

    @staticmethod
    def _stamp():
        try:
            st = os.stat(REQUEST)
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    @staticmethod
    def _read_request():
        try:
            line = open(REQUEST, encoding='utf-8', errors='replace').read()
        except OSError:
            return None, []
        if not line.endswith('\n') or '\tEND' not in line:
            return None, []
        parts = line.split('\tEND')[0].split('\t')
        return parts[0], parts[1:]

    @staticmethod
    def _write(path, text):
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        for _ in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:          # the game is reading it this very moment
                time.sleep(0.05)

    def _handle(self):
        seq, args = self._read_request()
        if seq is None or seq == self.last_seq:
            return
        self.last_seq = seq
        cmd = args[0] if args else ''
        ok, msg = True, ''
        try:
            if cmd in ('open', 'refresh'):
                self.opened = True
            elif cmd in ('position', 'learn'):
                msg = self.edit(int(args[1]), int(args[2]), cmd, source='trong game')['message']
            elif cmd == 'style':
                msg = self.edit(int(args[1]), None, 'style', source='trong game', value=int(args[2]))['message']
            elif cmd == 'foot':
                msg = self.foot(int(args[1]), source='trong game')['message']
            elif cmd == 'train':
                msg = self.e.train_position(int(args[1]), int(args[2]))['message']
            elif cmd == 'undo':
                msg = self.e.undo_edit(args[2]).get('message', 'Đã hoàn tác.')
            else:
                ok, msg = False, f'Lệnh không rõ: {cmd}'
        except (edit.EditError, gamemem.MemError, ValueError) as exc:
            ok, msg = False, str(exc)
        except Exception as exc:
            traceback.print_exc()
            ok, msg = False, 'Lỗi: ' + repr(exc)
        self.result = (seq, ok, msg)
        self.write_state()

    # ------------------------------------------------------------------- edits
    def allowed(self, snap, table=None):
        ids = {int(p['player_id']) for p in snap.squad_players} | {int(p['player_id']) for p in snap.youth_players}
        if table is not None:
            ids |= self._arrivals(snap, table, ids)
        return ids

    def _arrivals(self, snap, table, squad):
        """Players who joined the club since the save (same live team slot as the squad)."""
        slots = [table.slot[p] for p in squad if p in table.slot]
        if len(slots) < 10:
            return set()
        teams = table.rows[slots, gamemem.TEAM_AT].astype(np.int64) | table.rows[slots, gamemem.TEAM_AT + 1].astype(np.int64) << 8
        values, counts = np.unique(teams, return_counts=True)
        top = int(values[np.argmax(counts)])
        if counts.max() < 0.8 * len(slots) or top in (0, 0xFFFF):
            return set()
        all_teams = table.rows[:, gamemem.TEAM_AT].astype(np.int64) | table.rows[:, gamemem.TEAM_AT + 1].astype(np.int64) << 8
        members = {int(table.keys[s]) for s in np.nonzero(all_teams == top)[0] if table.keys[s] >= 0}
        if not 15 <= len(members) <= 70:
            return set()
        return {p for p in members if p in snap.row} - squad

    def _checked(self, pid):
        e = self.e
        snap = e.snap
        if snap is None or e.career is None:
            raise edit.EditError('Dugout chưa đọc xong save.')
        table = self.mem.table(snap)
        if pid not in self.allowed(snap, table):
            raise edit.EditError('Chỉ sửa được cầu thủ của CLB bạn đang dẫn dắt.')
        cur = self.mem.values(table, pid)
        if cur is None:
            raise edit.EditError('Không tìm thấy cầu thủ này trong bộ nhớ game.')
        return snap, table, cur

    def edit(self, pid, pos, action, grade_a=True, source='trong game', value=None):
        """In the running game: registered position ('position'), one more grade ('learn') or the
        playing style ('style', `value` = the career's style number)."""
        e = self.e
        with edit._LOCK:
            snap, table, cur = self._checked(pid)
            who = snap.player_name(pid)
            if action == 'style':
                if 'style' not in cur['known']:
                    raise edit.EditError('Chưa xác định chắc chỗ lưu phong cách chơi trong bộ nhớ game: không sửa.')
                value = int(value)
                db = terms.CAREER_STYLE_TO_DB.get(value)
                if db is None:
                    raise edit.EditError('Phong cách không hợp lệ.')
                if value and (db in pc.GK_STYLES) != (cur['position'] == 0):
                    raise edit.EditError('Phong cách thủ môn chỉ dành cho thủ môn, và ngược lại.')
                if cur['style'] == value:
                    return {'ok': True, 'changed': 0, 'message': f'{who} đã có phong cách này.'}
                writes = edit.writes_for(cur, pid, 'style', None, value=value)
                label = f'{who}: phong cách {style_name(cur["style"])} → {style_name(value)}'
            else:
                name = POS[pos]
                if 'grade:' + name not in cur['known']:
                    raise edit.EditError(f'Chưa xác định chắc chỗ lưu hạng {name} trong bộ nhớ game: không sửa.')
                if action == 'position' and source == 'trong game' and cur['grades'][name] == 0:
                    raise edit.EditError(f'{who} chưa biết đá {name} (hạng C). Nhấn L để học vị trí trước (C → B), '
                                         'hoặc T để tập theo thời gian, rồi mới đăng ký làm vị trí chính.')
                if action == 'position' and 'style' not in cur['known'] and (cur['position'] == 0) != (pos == 0):
                    raise edit.EditError('Chưa xác định chắc chỗ lưu phong cách chơi trong bộ nhớ game, nên chưa đổi '
                                         'giữa thủ môn và cầu thủ ngoài sân được.')
                if action == 'position' and cur['position'] == pos and cur['grades'][name] == 2:
                    return {'ok': True, 'changed': 0, 'message': f'{name} đã là vị trí đăng ký của cầu thủ này.'}
                writes = edit.writes_for(cur, pid, action, pos, grade_a)
                old_name = POS[cur['position']] if 0 <= cur['position'] < 13 else '?'
                if action == 'learn':
                    label = f'{who}: học vị trí {name} ({"CBA"[writes[0]["old"]]} → {"CBA"[writes[0]["new"]]})'
                else:
                    label = f'{who}: vị trí đăng ký {old_name} → {name}{" (hạng A)" if grade_a else ""}'
            backup_path = self._backup(snap)
            self.mem.write(table, writes)
            entry = edit.record({'label': label + f' · {source}', 'career': e.career.key, 'save': snap.save_path,
                                 'mode': 'game', 'writes': writes, 'backup': backup_path, 'persisted': False})
        e.log('Sửa trong game: ' + label)
        e.edit_log = edit.history(e.career.key)
        return {'ok': True, 'changed': len(writes), 'entry': entry,
                'message': f'Đã đổi trong game: {label}. Thay đổi được ghi vào save khi game lưu (lưu tay hoặc tự động lưu).'}

    def foot(self, pid, source='trong game', reset=False):
        """Swap a two-footed player's preferred foot (or put the original back). The save has no
        foot, so the swap is kept by Dugout and written again each time the career is loaded."""
        e = self.e
        feet = self.feet()
        snap = e.snap
        if snap is None or feet is None:
            raise edit.EditError('Dugout chưa đọc xong save.')
        i = snap.row.get(int(pid))
        swap = feet.get(pid)
        who = snap.player_name(pid)
        if not swap and reset:
            return {'ok': True, 'message': f'{who} đang dùng chân thuận gốc.'}
        if not swap and (i is None or int(snap.weak_accuracy[i]) < 4):
            raise edit.EditError(f'{who} không thuận hai chân (độ chính xác chân còn lại dưới 4/4): đổi chân thuận '
                                 'sẽ làm cầu thủ yếu đi, nên Dugout chỉ đổi cho cầu thủ thuận hai chân.')
        game = gamemem.find_game()
        if not game and swap:                      # nothing in memory to change: the next load uses the original
            feet.remove(pid)
            self._foot_log(pid, who, swap['orig_left'], swap['left'], source, undo=True)
            return {'ok': True, 'message': f'Đã bỏ đổi chân thuận của {who}: lần mở game tới dùng lại chân '
                                           f'{FOOT[swap["orig_left"]].lower()}.'}
        if not game:
            raise edit.EditError('Đổi chân thuận chỉ làm được khi game đang mở (chân thuận không nằm trong save).')
        with edit._LOCK:
            snap, table, cur = self._checked(pid)
            if 'foot' not in cur['known']:
                raise edit.EditError('Chưa xác định chắc chỗ lưu chân thuận trong bộ nhớ game: không đổi.')
            now_left = int(cur['foot'])
            if swap:
                target = int(swap['orig_left'])
            else:
                target = 1 - now_left
            if now_left != target:
                self.mem.write(table, [{'player_id': pid, 'field': 'foot', 'old': now_left, 'new': target}])
            if swap:
                feet.remove(pid)
            else:
                feet.set(pid, target, now_left, who)
        self._foot_log(pid, who, now_left, target, source, undo=bool(swap))
        if swap:
            return {'ok': True, 'message': f'{who} dùng lại chân thuận gốc ({FOOT[target].lower()}).'}
        return {'ok': True, 'message': f'Đã đổi chân thuận của {who}: {FOOT[now_left].lower()} → {FOOT[target].lower()}. '
                                       'Save không lưu chân thuận, nên Dugout tự áp lại mỗi lần bạn mở game '
                                       '(cần Dugout đang chạy).'}

    def _foot_log(self, pid, who, old, new, source, undo):
        e = self.e
        if undo:                                   # the swap entries of this player are over
            for entry in edit.history(e.career.key):
                if entry.get('mode') == 'foot' and not entry.get('undone') and entry['writes'][0]['player_id'] == pid:
                    edit.update(entry['id'], undone=True)
            e.log(f'Bỏ đổi chân thuận: {who}')
        else:
            edit.record({'label': f'{who}: chân thuận {FOOT[old].lower()} → {FOOT[new].lower()} · {source}',
                         'career': e.career.key, 'save': e.snap.save_path, 'mode': 'foot',
                         'writes': [{'player_id': pid, 'field': 'foot', 'old': old, 'new': new}]})
            e.log(f'Đổi chân thuận trong game: {who} {FOOT[old].lower()} → {FOOT[new].lower()}')
        e.edit_log = edit.history(e.career.key)

    def undo(self, writes, label):
        """edit.undo's in-game writer."""
        snap = self.e.snap
        with edit._LOCK:
            table = self.mem.table(snap)
            self.mem.write(table, writes)
            entry = edit.record({'label': label, 'career': self.e.career.key, 'save': snap.save_path,
                                 'mode': 'game', 'writes': writes, 'backup': self._backup(snap), 'persisted': False})
        return {'ok': True, 'entry': entry,
                'message': 'Đã hoàn tác trong game. Thay đổi được ghi vào save khi game lưu.'}

    def live_values(self, pid):
        """The player's fields in the running game, if the link is up (never searches)."""
        snap = self.e.snap
        if snap is None or self.mem.base is None:
            return None
        try:
            table = self.mem.table(snap, scan=False, quiet=True)
        except gamemem.MemError:
            return None
        return self.mem.values(table, pid)

    def grade_now(self, pid, pos):
        """The player's grade at `pos` in the running game (None if unknown)."""
        snap = self.e.snap
        try:
            table = self.mem.table(snap, scan=False, quiet=True)
        except gamemem.MemError:
            return None
        vals = self.mem.values(table, pid)
        if not vals or 'grade:' + POS[pos] not in vals['known']:
            return None
        return int(vals['grades'][POS[pos]])

    def _backup(self, snap):
        """The save as it was before the first in-game change reaches it (once per save written)."""
        key = (snap.save_path, os.path.getmtime(snap.save_path))
        folder = os.path.join(backup.folder_for(self.e.career.key), 'truoc_khi_sua')
        name = f'{dt.datetime.fromtimestamp(key[1]):%Y%m%d_%H%M%S}_{os.path.basename(snap.save_path)}_truoc_sua_trong_game.sav'
        path = os.path.join(folder, name)
        if key not in self.backed_up or not os.path.exists(path):
            os.makedirs(folder, exist_ok=True)
            if not os.path.exists(path):
                shutil.copy2(snap.save_path, path)
            self.backed_up.add(key)
        return path

    def check_persisted(self, snap, career_key):
        """After the game wrote the save: mark in-game edits it stored (or that a later edit of the
        same fields replaced)."""
        later = set()                                  # fields changed by newer edits
        for entry in edit.history(career_key):         # newest first
            if entry.get('mode') == 'foot':
                continue
            fields = {(int(w['player_id']), w['field']) for w in entry['writes']}
            pending = entry.get('mode') == 'game' and not entry.get('persisted') and not entry.get('undone')
            if pending and fields <= later:
                edit.update(entry['id'], persisted='replaced')
            elif pending and all(self._saved_value(snap, w) == int(w['new']) for w in entry['writes']):
                edit.update(entry['id'], persisted=dt.datetime.fromtimestamp(snap.save_mtime).isoformat(timespec='seconds'))
                self.e.log('Game đã lưu thay đổi: ' + entry['label'])
            if not entry.get('undone'):
                later |= fields

    @staticmethod
    def _saved_value(snap, w):
        i = snap.row.get(int(w['player_id']))
        if i is None:
            return None
        f = w['field']
        if f == 'position':
            return int(snap.position[i])
        if f == 'style':
            return gamemem.TO_CAREER_STYLE.get(int(snap.style[i]), 0)
        return int(snap.grades[i, POS.index(f[6:])])

    # ------------------------------------------------------------------- state
    def status(self):
        cal = self.mem.cal
        return {'game': bool(self.game), 'memory': self.mem.status, 'message': self.mem.message,
                'fields': sum(1 for p in POS if gamemem.usable(cal, 'grade:' + p)) if cal else 0,
                'style': gamemem.usable(cal, 'style'), 'foot': gamemem.usable(cal, 'foot'),
                'feet': {str(k): v for k, v in (self.feet().data if self.feet() else {}).items()}}

    def write_state(self):
        e = self.e
        snap = e.snap
        lines = ['V\t2']
        table = None
        if snap is not None:
            try:
                table = self.mem.table(snap)
            except gamemem.MemError:
                table = None
            except Exception as exc:
                traceback.print_exc()
                self.mem.status, self.mem.message = 'error', 'Lỗi đọc bộ nhớ game: ' + repr(exc)
        code = self.mem.status if snap is not None else 'nosave'
        msg = self.mem.message if snap is not None else 'Dugout chưa đọc xong save.'
        date = self.mem.game_date or (snap.date if snap is not None else None)
        lines.append('\t'.join(['H', str(int(time.time())), code, _clean(msg),
                                _clean(snap.team_name if snap is not None else ''),
                                f'{date.day}/{date.month}/{date.year}' if date else '']))
        if self.result:
            seq, ok, rmsg = self.result
            lines.append('\t'.join(['R', str(seq), '1' if ok else '0', _clean(rmsg)]))
        if snap is not None:
            lines.extend(self._player_lines(snap, table, date))
        lines.append('E')
        self._write(STATE, '\n'.join(lines) + '\n')
        self.state_version, self.last_state = e.version, time.time()

    def _player_lines(self, snap, table, today):
        e = self.e
        allowed = self.allowed(snap, table)
        played = getattr(e, 'played', None) or {}
        feet = self.feet()
        undo_of = {}
        for entry in edit.history(e.career.key if e.career else None):
            if entry.get('undone'):
                continue
            for w in entry['writes']:
                undo_of.setdefault(int(w['player_id']), entry)
        rows = []
        for pid in allowed:
            i = snap.row.get(pid)
            if i is None:
                continue
            live = self.mem.values(table, pid) if table is not None else None
            reg = live['position'] if live else int(snap.position[i])
            grades = [live['grades'].get(p, int(snap.grades[i, k])) if live else int(snap.grades[i, k])
                      for k, p in enumerate(POS)]
            rows.append((pid, i, reg, grades, live))
        rows.sort(key=lambda r: (r[2] if 0 <= r[2] < 13 else 99, -int(snap.ovr_all[r[1], max(r[2], 0)])))
        styles = self._style_options(snap, rows)
        trainer = getattr(e, 'trainer', None)
        can_edit = table is not None and self.mem.status in ('ready', 'partial')
        out = []
        for (pid, i, reg, grades, live), opts in zip(rows, styles):
            reg_ok = 0 <= reg < 13
            reg_ovr = int(snap.ovr_all[i, reg]) if reg_ok else 0
            pos_rows, best = [], None
            for k in range(13):
                ovr, fit = int(snap.ovr_all[i, k]), int(round(float(snap.fit[i, k])))
                v = verdict(fit, ovr - reg_ovr)
                if k != reg and v >= 2 and (best is None or (v, ovr, fit) > best[1:]):
                    best = (k, v, ovr, fit)
                pos_rows.append('\t'.join(['G', str(pid), str(k), str(grades[k]), str(ovr), str(fit), str(v)]))
            pl = played.get(pid)
            entry = undo_of.get(pid)
            swap = feet.get(pid) if feet else None
            foot_now = live['foot'] if live and live.get('foot') is not None else int(snap.left_foot[i])
            style_now = live['style'] if live and 'style' in live['known'] else gamemem.TO_CAREER_STYLE.get(int(snap.style[i]), 0)
            foot_ok = can_edit and live is not None and 'foot' in live['known'] and (int(snap.weak_accuracy[i]) >= 4 or swap)
            style_ok = can_edit and live is not None and 'style' in live['known']
            out.append('\t'.join(['P', str(pid), str(snap.shirt_of.get(pid, '') or ''), _clean(snap.player_name(pid), 26),
                                  str(int(snap.age[i])), str(reg), str(reg_ovr), str(pl if pl is not None else -1),
                                  str(best[0] if best else -1), str(best[1] if best else -1),
                                  entry['id'] if entry else '', _clean(entry['label'], 70) if entry else '',
                                  '1' if can_edit and live is not None else '0',
                                  str(foot_now), str(int(snap.weak_accuracy[i])), '1' if swap else '0',
                                  '1' if foot_ok else '0', _clean(style_name(style_now), 60), str(style_now),
                                  '1' if style_ok else '0']))
            out.extend(pos_rows)
            for enum, label, fit, cur, sugg in opts:
                out.append('\t'.join(['Y', str(pid), str(enum), _clean(label, 60), str(fit), '1' if cur else '0',
                                      '1' if sugg else '0']))
            for plan in (trainer.active(pid) if trainer else []):
                pr = trainer.progress(snap, plan, today or snap.date)
                out.append('\t'.join(['T', str(pid), str(plan['pos']), str(pr['pct']), str(pr['eta_days']), pr['next']]))
        return out

    def _style_options(self, snap, rows):
        """For each row: [(career style, label, fit %, current, suggested)] the player can use at his
        registered position, best first."""
        brain = self.e.brain
        if not rows or brain is None:
            return [[] for _ in rows]
        idx = np.array([r[1] for r in rows])
        pos = np.array([r[2] if 0 <= r[2] < 13 else int(snap.main_pos[r[1]]) for r in rows], dtype=np.int32)
        try:
            prob = brain.styles.predict(snap.abilities[idx], snap.height[idx], snap.left_foot[idx], pos)
            compat = brain.styles.compat
        except Exception:
            traceback.print_exc()
            return [[] for _ in rows]
        out = []
        for k, (pid, i, reg, grades, live) in enumerate(rows):
            cur_db = int(snap.style[i]) if live is None or 'style' not in live['known'] else \
                terms.CAREER_STYLE_TO_DB.get(int(live['style']), 0)
            gk = pos[k] == 0
            opts = []
            for enum, db in terms.CAREER_STYLE_TO_DB.items():
                if not db or (db in pc.GK_STYLES) != gk:
                    continue
                if not compat[pos[k], db] and db != cur_db:
                    continue
                opts.append((enum, terms.style_label(db), int(round(float(prob[k, db]) * 100)), db == cur_db))
            opts.sort(key=lambda o: -o[2])
            top = next((o[0] for o in opts if not o[3]), None)
            opts = [(e_, l_, f_, c_, e_ == top and f_ >= 30) for e_, l_, f_, c_ in opts]
            opts.append((0, 'Không có phong cách', 0, cur_db == 0, False))
            out.append(opts)
        return out

"""The running app: watches the active Master League save, re-reads it every time the game
writes it (the game can stay open), updates the career's timeline, inbox and AI predictions,
and keeps one ready-made screen bundle in memory (and on disk, so the next start is instant)."""
import datetime as dt
import gzip
import json
import os
import threading
import time
import traceback
import zlib

import numpy as np

from . import (analysis, backup, chat, config, edit, events, gamemem, health, ingame, labels, live, matchday, models,
               pesdb, plan, save_reader, store, terms, training, views)

POLL_SECONDS = 1.0
SETTLE_SECONDS = 1.5          # the save must stop changing this long before it is read


class Engine:
    def __init__(self):
        self.lock = threading.RLock()
        self.status = {'state': 'starting', 'message': 'Đang khởi động…', 'log': []}
        self.version = 0
        self.bundle_bytes = None
        self.bundle_obj = None
        self.bundle_gz = None
        self.snap = None
        self.brain = None
        self.db = None
        self.career = None
        self.training = False
        self._force = False
        self._detail_cache = {}
        self.match_model, self.match_model_key = None, None
        self.md = None
        self.derbies = set()
        self.health = {'level': 'unknown', 'items': [], 'at': None}
        self.health_files = []
        self.backup_info = None
        self._backup_request = False
        self._last_load = None                  # (career key, save, file key, snapshot, may back up)
        self._unverified_key = None
        self.game_on = False
        self.edit_log = []
        self._trainer = None
        self._load_cached_bundle()
        self.live = live.Live(self.log)
        self.live.on_world = self._record_market
        self.ingame = ingame.Bridge(self)          # the in-game page; also keeps game_on current
        threading.Thread(target=self._run, daemon=True).start()

    # ------------------------------------------------------------------- utils
    def log(self, msg):
        with self.lock:
            self.status['log'] = (self.status['log'] + [f'{time.strftime("%H:%M:%S")}  {msg}'])[-200:]
            self.status['message'] = msg
        print(time.strftime('%H:%M:%S'), msg, flush=True)

    def set_state(self, state, message=None):
        with self.lock:
            self.status['state'] = state
            if message:
                self.status['message'] = message

    def brain_report(self):
        try:
            return json.load(open(os.path.join(config.DATA_DIR, 'training_report.json'), encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def _publish(self, bundle):
        raw = json.dumps(bundle, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        gz = gzip.compress(raw, 5)
        with self.lock:
            self.bundle_bytes, self.bundle_gz = raw, gz
            self.bundle_obj = bundle            # the live match map reads the pre-match analysis
        return raw

    def _load_cached_bundle(self):
        """Serve the last bundle of the active save right away, before anything is decoded."""
        try:
            save = config.active_save()
            if not save:
                return
            path = os.path.join(config.CAREERS_DIR, config.career_key(save), 'bundle.json')
            raw = open(path, 'rb').read()
            self.bundle_obj = json.loads(raw)
            self.version = int(self.bundle_obj.get('version', 0))
            self.bundle_bytes, self.bundle_gz = raw, gzip.compress(raw, 5)
            self.status.update(state='cached', message='Đang hiện dữ liệu lần trước, đang đọc lại save…')
        except (OSError, ValueError):
            pass

    # ---------------------------------------------------------------- lifecycle
    def _run(self):
        try:
            self.db = pesdb.PlayerDB()
            self.nations = labels.nationality_names()
            try:
                self.derbies = pesdb.derbies()
            except Exception:
                self.derbies = set()
            missing = []
            from . import train
            missing = train.missing_parts()
            if missing:
                self.train(missing)
            self.brain = models.Brain()
            self.health_files = health.file_changes()
            save = config.active_save()
            if save:
                self.backup_info = backup.status(config.career_key(save))
        except Exception as exc:
            self.log('Lỗi khởi động: ' + repr(exc))
            traceback.print_exc()
            self.set_state('error')
            return
        last, pending, pending_since = None, None, 0.0
        while True:
            try:
                save = config.active_save()
                if not save:
                    self.set_state('waiting', 'Không tìm thấy save Master League nào.')
                else:
                    st = os.stat(save)
                    key = (save, st.st_mtime, st.st_size)
                    if self._force:
                        self._force, last = False, None
                    if key != last and not self.training:
                        if pending != key:           # the file changed: wait until the game has finished writing
                            pending, pending_since = key, time.time()
                            if self.snap is not None:
                                self.set_state('syncing', 'Phát hiện save mới, đang chờ game ghi xong…')
                        if self.snap is None or time.time() - pending_since >= SETTLE_SECONDS:
                            self.load(save, key)
                            last, pending = key, None
                if self._backup_request:
                    self._backup_request = False
                    self._backup_again()
            except Exception as exc:
                self.log('Lỗi khi đọc save: ' + repr(exc))
                traceback.print_exc()
                self.set_state('error')
                time.sleep(5)
                last = pending = None
                if self.snap is None:
                    time.sleep(10)
            time.sleep(POLL_SECONDS)

    def reload(self):
        self._force = True

    def train(self, parts=None):
        if self.training:
            return
        from . import train
        self.training = True
        self.set_state('training', 'Đang huấn luyện AI…')
        try:
            train.main(self.log, parts=tuple(parts or train.PARTS))
            self.brain = models.Brain()
            if self.snap is not None and self.career is not None:
                self._derive_and_publish(self.snap, first_run=False, record=False)
        except Exception as exc:
            self.log('Huấn luyện lỗi: ' + repr(exc))
            traceback.print_exc()
            self.set_state('error')
        finally:
            self.training = False

    # --------------------------------------------------------------------- load
    def load(self, save, file_key=None):
        t0 = time.time()
        self.set_state('syncing', 'Đang đọc save ' + os.path.basename(save) + '…')
        key = config.career_key(save)
        try:
            snap = save_reader.Snapshot(save, self.db)
        except Exception as exc:
            self.health = health.failed(exc)
            self._backup_unverified(key, save, file_key)       # keep the save itself: a later Dugout may read it
            raise
        if self.career is None or self.career.key != key:
            self.career = store.Career(key)
        # a save that does not look like a healthy career is shown as such and kept out of the AI's data
        report = health.check(snap, self.career.timeline)
        self.health, self.health_files = report, health.file_changes()
        if report['level'] == 'error':
            self.log('Kiểm tra dữ liệu: ' + health.headline(report) + ' Lần đọc này không được ghi vào dữ liệu AI.')
            self._backup_unverified(key, save, file_key)
            if self.bundle_bytes is None:          # nothing else to show: show it, keep nothing
                try:
                    self._derive_and_publish(snap, first_run=False, record=False, announce=False, persist=False)
                except Exception:
                    traceback.print_exc()
            self.set_state('error', 'Save đọc có vẻ sai: ' + health.headline(report))
            return
        seen_date = (self.career.seen or {}).get('date')
        older = False
        if seen_date:
            seen_date = dt.date.fromisoformat(seen_date)
            if snap.date < seen_date - dt.timedelta(days=45):
                self.log('Slot này đang chứa một career khác (ngày sớm hơn nhiều): bắt đầu dữ liệu mới, dữ liệu cũ được cất riêng.')
                self.career.reset()
            elif snap.date < seen_date:
                older = True                 # an older save of the same career was loaded: show it, announce nothing
        first_run = self.career.seen is None
        recorded = self.career.timeline.record(snap)
        self._derive_and_publish(snap, first_run, recorded, announce=not older)
        self.log(f'Đồng bộ xong: {snap.team_name}, ngày {snap.date.day}/{snap.date.month}/{snap.date.year} '
                 f'({time.time() - t0:.1f}s).')
        self._last_load = (key, save, file_key, snap, not older)
        try:
            self.ingame.check_persisted(snap, key)
            if not gamemem.find_game():          # with the game running, the live link does it
                self.training_check(snap.date, in_game=False)
            if not older:
                self._announce_plan(snap)
        except Exception:
            traceback.print_exc()
        if file_key and not older:                 # an older save of the career is not backed up over newer data
            self._backup(key, save, file_key, snap)

    # ------------------------------------------------------------------ backup
    def _backup(self, key, save, file_key, snap):
        try:
            backup.run(key, save, file_key, snap, verified=True, career=self.career)
            self.backup_info = backup.status(key)
        except Exception as exc:
            self.log('Sao lưu lỗi: ' + repr(exc))
            traceback.print_exc()
            self.backup_info = {**(self.backup_info or {}), 'error': repr(exc)}

    def _backup_unverified(self, key, save, file_key):
        if not file_key or file_key == self._unverified_key:
            return                                 # once per save written by the game
        self._unverified_key = file_key
        try:
            backup.run(key, save, file_key, None, verified=False)
            self.backup_info = backup.status(key)
        except Exception as exc:
            self.log('Sao lưu lỗi: ' + repr(exc))

    # ------------------------------------------------------------------ save edits
    def _editable(self):
        snap = self.snap
        if snap is None or self.career is None:
            raise edit.EditError('Chưa đọc xong save.')
        return snap, {int(p['player_id']) for p in snap.squad_players} | {int(p['player_id']) for p in snap.youth_players}

    def edit_position(self, pid, pos, grade_a=True, action='position', value=None, source='từ app'):
        """Registered position ('position'), one more grade at a position ('learn') or the playing
        style ('style', `value` = career style number): in the game's memory while FL26 runs,
        otherwise in the save."""
        snap, allowed = self._editable()
        pid = int(pid)
        if action != 'style':
            pos = int(pos)
            if not 0 <= pos < 13:
                raise edit.EditError('Vị trí không hợp lệ.')
        if gamemem.find_game():
            return self.ingame.edit(pid, pos, action, bool(grade_a), source=source, value=value)
        i = snap.row.get(pid)
        if i is None or pid not in allowed:
            raise edit.EditError('Chỉ sửa được cầu thủ của CLB bạn đang dẫn dắt.')
        old = int(snap.position[i])
        who = snap.player_name(pid)
        if action == 'style':
            cur = ingame.gamemem.TO_CAREER_STYLE.get(int(snap.style[i]), 0)
            label = f'{who}: phong cách {ingame.style_name(cur)} → {ingame.style_name(int(value))}'
        elif action == 'learn':
            g = int(snap.grades[i, pos])
            label = f'{who}: học vị trí {terms.POSITIONS[pos]} ({"CBA"[g]} → {"CBA"[min(g + 1, 2)]})'
        else:
            label = (f'{who}: vị trí đăng ký {terms.POSITIONS[old] if old >= 0 else "?"} → '
                     f'{terms.POSITIONS[pos]}{" (hạng A)" if grade_a else ""}')
        if source != 'từ app':
            label += f' · {source}'
        out = edit.change_position(snap.save_path, self.career.key, pid, pos, bool(grade_a), label, allowed, action,
                                   value)
        if out.get('changed'):
            self.log('Sửa save: ' + label)
            self._force = True                       # read the edited save at once
        self.edit_log = edit.history(self.career.key)
        return out

    def undo_edit(self, entry_id):
        if self.career is None:
            raise edit.EditError('Chưa đọc xong save.')
        entry = next((e for e in edit.history(self.career.key) if e['id'] == entry_id), None)
        if entry is None:
            raise edit.EditError('Không tìm thấy lần sửa này.')
        if entry.get('undone'):
            raise edit.EditError('Lần sửa này đã được hoàn tác.')
        if entry.get('mode') == 'foot':
            return self.ingame.foot(int(entry['writes'][0]['player_id']), source='hoàn tác', reset=True)
        if gamemem.find_game():
            out = edit.undo(entry_id, 'Hoàn tác: ' + entry.get('label', ''), in_game=self.ingame.undo)
            self.log('Hoàn tác trong game: ' + entry.get('label', ''))
        else:
            out = edit.undo(entry_id, 'Hoàn tác: ' + entry.get('label', ''))
            self.log('Hoàn tác sửa save: ' + entry.get('label', ''))
            self._force = True
        self.edit_log = edit.history(self.career.key)
        return out

    # ------------------------------------------------------------ foot and training
    def set_foot(self, pid):
        """Swap a two-footed player's preferred foot, or put the original back (in the game)."""
        self._editable()
        return self.ingame.foot(int(pid), source='từ app')

    @property
    def trainer(self):
        c = self.career
        if c is None:
            return None
        if self._trainer is None or self._trainer[0] != c.key:
            self._trainer = (c.key, training.Trainer(c.dir))
        return self._trainer[1]

    def _grade(self, pid, pos):
        """Current grade: the running game's when it is connected, else the save's."""
        if gamemem.find_game():
            return self.ingame.grade_now(pid, pos)
        i = self.snap.row.get(int(pid)) if self.snap is not None else None
        return None if i is None else int(self.snap.grades[i, pos])

    def train_position(self, pid, pos):
        """Start (or stop) training a position over time."""
        snap, allowed = self._editable()
        pid, pos = int(pid), int(pos)
        if pid not in allowed and pid not in self.ingame.allowed(snap):
            raise edit.EditError('Chỉ tập được cho cầu thủ của CLB bạn đang dẫn dắt.')
        trainer = self.trainer
        who, name = snap.player_name(pid), terms.POSITIONS[pos]
        if trainer.find(pid, pos):
            trainer.cancel(pid, pos)
            self.log(f'Dừng tập vị trí: {who} ({name})')
            return {'ok': True, 'message': f'Đã dừng tập {name} cho {who}.'}
        grade = self._grade(pid, pos)
        if grade is None:
            raise edit.EditError('Chưa đọc được hạng vị trí hiện tại (Dugout chưa kết nối bộ nhớ game).')
        today = self.ingame.mem.game_date or snap.date
        plan = trainer.start(snap, pid, pos, grade, today)
        pr = trainer.progress(snap, plan, today)
        self.log(f'Bắt đầu tập vị trí: {who} ({name}, hạng {"CBA"[grade]})')
        return {'ok': True, 'message': f'{who} bắt đầu tập {name}: lên hạng {pr["next"]} sau khoảng {pr["need_days"] // 7} '
                                       f'tuần trong game (mỗi 90 phút đá ở {name} bớt 1 tuần).'}

    def training_check(self, today, in_game=False):
        """Raise the grade of every training step that is complete (in the game or in the save)."""
        trainer, snap = self.trainer, self.snap
        if trainer is None or snap is None or not trainer.active():
            return 0
        grade_of = self.ingame.grade_now if in_game else self._grade
        done = 0
        for plan in trainer.due(snap, today, grade_of):
            info = trainer.progress(snap, plan, today)
            try:
                self.edit_position(plan['pid'], plan['pos'], action='learn', source='tập luyện')
            except (edit.EditError, gamemem.MemError) as exc:
                self.log(f'Chưa nâng được hạng tập luyện của {plan["name"]}: {exc}')
                continue
            new = plan['grade'] + 1
            trainer.step_done(plan, new, today, {'days': info['days'], 'minutes': info['minutes']})
            pos = terms.POSITIONS[plan['pos']]
            self.career.add_event({
                'date': today.isoformat(), 'kind': 'training', 'from': 'assistant', 'players': [plan['pid']],
                'title': f'{plan["name"]} tập xong vị trí {pos}: lên hạng {"CBA"[new]}',
                'body': f'Sau {info["days"]} ngày tập và {info["minutes"]} phút đá ở vị trí {pos} '
                        f'({terms.POS_VI[pos]}), {plan["name"]} đã lên hạng {"CBA"[new]}.'
                        + (' Đã thạo hoàn toàn vị trí này.' if new >= 2 else ' Tiếp tục tập để lên hạng A.')})
            self.career.save()
            done += 1
        return done

    def edit_info(self, pid):
        """What the app's edit tab needs, fresh: playing styles that fit, training in progress, the
        preferred foot and whether edits go to the game or the save."""
        snap = self.snap
        pid = int(pid)
        i = snap.row.get(pid)
        if i is None:
            return None
        live = self.ingame.live_values(pid)
        reg = live['position'] if live else int(snap.position[i])
        opts = self.ingame._style_options(snap, [(pid, i, reg, None, live)])[0]
        trainer = self.trainer
        today = self.ingame.mem.game_date or snap.date
        feet = self.ingame.feet()
        swap = feet.get(pid) if feet else None
        foot_now = live['foot'] if live and live.get('foot') is not None else int(snap.left_foot[i])
        return {'styles': [{'id': o[0], 'label': o[1], 'fit': o[2], 'current': o[3], 'sugg': o[4]} for o in opts],
                'training': [{'pos': terms.POSITIONS[p['pos']], 'pos_idx': p['pos'], 'started': p['started'],
                              **trainer.progress(snap, p, today)} for p in trainer.active(pid)],
                'done': [{'pos': terms.POSITIONS[p['pos']], 'steps': p['steps']} for p in trainer.plans
                         if p['pid'] == pid and p['status'] == 'done'][:5],
                'foot': {'left': int(foot_now), 'wf': int(snap.weak_accuracy[i]), 'swap': swap},
                'game': bool(gamemem.find_game()), 'live': live is not None, 'ingame': self.ingame.status()}

    def edits(self):
        if self.career is None:
            return []
        self.edit_log = edit.history(self.career.key)
        return self.edit_log

    def request_backup(self):
        self._backup_request = True

    def _backup_again(self):
        """'Back up now': the last healthy load again (the save copy is skipped if the game rewrote it)."""
        if not self._last_load or not self._last_load[4]:
            self.log('Chưa có lần đọc save hợp lệ để sao lưu.')
            return
        key, save, file_key, snap, _ok = self._last_load
        self._backup(key, save, file_key, snap)
        self.log('Đã sao lưu vào ' + (self.backup_info or {}).get('dir', ''))

    def _record_market(self, values, budget):
        """Live market values (only the running game has them): kept per game date for the AI."""
        career, snap = self.career, self.snap
        if career is None or snap is None:
            return
        if budget and budget.get('team') and int(budget['team']) != snap.team_id:
            return                                 # the game shows another career than the last save
        date = snap.date
        try:
            date = dt.date.fromisoformat(str((budget or {}).get('date') or '')[:10])
        except ValueError:
            pass
        career.market.record(date, values, budget)

    def _derive_and_publish(self, snap, first_run, record=True, announce=True, persist=True):
        analysis.analyze(snap, self.brain, self.db, self.career.timeline)
        extra = views.club_extra(snap)
        squad_rows = np.array([snap.row[p] for p in extra if p in snap.row and not extra[p].get('youth')], dtype=np.int64)
        youth_rows = np.array([snap.row[p] for p in extra if p in snap.row and extra[p].get('youth')], dtype=np.int64)
        played = analysis.played_positions(snap)
        own = {}                                   # Dugout's own timed position training
        try:
            trainer = self.trainer
            for plan in (trainer.active() if trainer else []):
                own.setdefault(plan['pid'], {})[plan['pos']] = trainer.progress(snap, plan, snap.date)
        except Exception:
            traceback.print_exc()
        advice = analysis.advise(snap, self.brain, np.concatenate([squad_rows, youth_rows]), played, own)
        for i, a in advice.items():
            pid = int(snap.ids[i])
            if pid in extra:
                extra[pid]['advice'] = '\n'.join(_advice_line(g) for g in a['suggestions'])
                extra[pid]['adv'] = [_advice_task(snap, i, g) for g in a['suggestions']]
                extra[pid]['training'] = [_training_key(g) for g in a['training']]

        # matches of this season (the archive keeps earlier seasons)
        season = sorted(snap.my_fixtures, key=lambda f: (f.year, f.month, f.day, f.kickoff_hour or 0))
        season_matches = [events.match_record(snap, f) for f in season]
        try:                                       # own goals: not in the save, named from the live logs
            events.own_goals(season_matches, os.path.join(self.career.dir, 'live') if self.career else None)
            # the live logs: scorers and cards the map missed (a replay skipped), from the save
            if self.career and events.fix_live_logs(os.path.join(self.career.dir, 'live'), season_matches):
                from . import matchlive
                if matchlive.TRACKER is not None:
                    matchlive.TRACKER.last_log, matchlive.TRACKER._last_try = None, 0.0   # read again
        except Exception:
            traceback.print_exc()
        played_now = [m for m in season_matches if m['played']]
        stats = views.season_stats(season_matches, snap.team_id)
        for pid, x in extra.items():
            st = stats.get(pid)
            x.update(st if st else {'apps': 0, 'goals': 0, 'assists': 0, 'rating': None, 'minutes': 0} if not x.get('youth') else {})
        old_seen = self.career.seen or {}
        done_before = set(old_seen.get('fixtures_done', []))
        played_new = [m for m in played_now if m['key'] not in done_before]
        if persist:
            for m in played_now:
                self.career.matches[m['key']] = m

        # next matches: form, best XI, opponent report, tactics, prediction
        n_played = sum(1 for f in snap.fixtures if f.flags & 64)
        if self.match_model is None or self.match_model_key != (snap.key, n_played):
            self.match_model = matchday.MatchModel().fit(snap, self.career.world.rows())
            self.match_model_key = (snap.key, n_played)
            if persist and announce:               # every match of the world, kept past the season change
                try:
                    new = self.career.world.merge(self.match_model.archive)
                    if new:
                        self.log(f'Lưu trữ thêm {new:,} trận trên thế giới vào dữ liệu của AI.'.replace(',', '.'))
                except Exception:
                    traceback.print_exc()
        if persist and announce:                   # both Game Plans as they stand before the next match
            nxt = next((f for f in season if not f.flags & 64), None)
            if nxt is not None:
                plans = {str(t): snap.gameplan_raw[t].hex() for t in (nxt.home_team, nxt.away_team)
                         if snap.gameplan_raw.get(t)}
                if plans:
                    self.career.tactics[events.fixture_key(nxt)] = {
                        'seen': snap.date.isoformat(), 'home': int(nxt.home_team), 'away': int(nxt.away_team),
                        'plans': plans}
        md = matchday.Matchday(snap, extra, season_matches, self.match_model, self.derbies).build()
        if record and announce:
            try:
                self.career.condlog.record(snap)
            except Exception:
                traceback.print_exc()

        # what changed since the previous load -> inbox
        rows = np.concatenate([squad_rows, youth_rows])
        new_seen = {'date': snap.date.isoformat(), 'squad': events.squad_state(snap, rows, extra),
                    'fixtures_done': [m['key'] for m in played_now], 'regens': int(snap.regen.sum())}
        regen_idx = np.nonzero(snap.regen)[0]
        top = regen_idx[np.argsort(-snap.out['peak'][regen_idx])][:6]
        new_seen['regen_top'] = [f'• {snap.names[i]} ({POS(snap, i)}, {snap.age[i]} tuổi) — OVR {int(snap.ovr[i])}, '
                                 f'ngưỡng dự đoán {int(round(float(snap.out["peak"][i])))} · {snap.club_name(int(snap.team[i])) or "tự do"}'
                                 for i in top]
        ags = []
        for ag in (snap.club.get('club_agreements') or []):
            pid = int(ag.get('player_id') or 0)
            k = f'{ag.get("kind")}:{ag.get("direction")}:{pid}:{ag.get("buyer_team_id")}:{ag.get("state_name")}'
            name = snap.player_name(pid)
            buyer, seller = snap.club_name(ag.get('buyer_team_id') or 0), snap.club_name(ag.get('seller_team_id') or 0)
            fee = ag.get('fee')
            fee_txt = f'{fee:,}'.replace(',', '.') if isinstance(fee, int) else '?'
            state = {'pending': 'đang chờ', 'accepted': 'đã chấp nhận', 'completed': 'đã hoàn tất',
                     'rejected': 'bị từ chối'}.get(ag.get('state_name'), ag.get('state_name'))
            kind = 'cho mượn' if ag.get('kind') == 'loan' else 'chuyển nhượng'
            if ag.get('direction') == 'outgoing':
                title = f'{buyer} muốn có {name}'
            else:
                title = f'Thương vụ {name} từ {seller}'
            ags.append({'key': k, 'event': {'date': snap.date.isoformat(), 'kind': 'offer', 'title': title,
                                             'body': f'Thỏa thuận {kind} {name}: {seller} → {buyer}, phí {fee_txt} ({state}).',
                                             'players': [pid]}})
        new_seen['agreements_full'] = ags
        if announce:
            events.diff(snap, self.career, new_seen, played_now, first_run)
            new_seen['agreements'] = [a['key'] for a in ags]
            new_seen.pop('agreements_full', None)
            chat.after_load(snap, self.career, md, old_seen, new_seen, played_new, first_run, season_matches,
                            _standing(snap))
            self.career.seen = new_seen

        # AI prediction log for the squad (to chart how the prediction moved)
        for i in rows if announce else []:
            pid = str(int(snap.ids[i]))
            lst = self.career.predictions.setdefault(pid, [])
            entry = [snap.date.isoformat(), int(snap.ovr[i]), int(round(float(snap.out['peak'][i]))), int(snap.age[i])]
            if lst and lst[-1][0] == entry[0]:
                lst[-1] = entry
            else:
                lst.append(entry)
            if len(lst) > 400:
                del lst[:len(lst) - 400]
        if persist:
            self.career.save()

        with self.lock:
            self.snap = snap
            self.extra, self.played, self.advice = extra, played, advice
            self.squad_rows, self.youth_rows = squad_rows, youth_rows
            self.season_matches = season_matches
            self.md = md
            self.name_fold = [views.fold(n) for n in snap.names]
            self._detail_cache = {}
            self.version += 1
        bundle = views.Builder(self).bundle()
        raw = self._publish(bundle)
        if persist:
            store_path = self.career.bundle_path()
            tmp = store_path + '.tmp'
            open(tmp, 'wb').write(raw)
            os.replace(tmp, store_path)
        self.status.update(state='ready', updated=time.strftime('%H:%M:%S'),
                           message=f'Đã đồng bộ lúc {time.strftime("%H:%M:%S")}')
        threading.Thread(target=self._warm_faces, args=(rows,), daemon=True).start()

    def _warm_faces(self, rows):
        from .server import face_png
        for i in rows:
            try:
                face_png(int(self.snap.ids[i]))
            except Exception:
                pass

    # ----------------------------------------------------------------- queries
    def detail(self, pid):
        with self.lock:
            snap = self.snap
            if snap is None:
                return None
            i = snap.row.get(pid)
            if i is None:
                return None
            if pid in self._detail_cache:
                return self._detail_cache[pid]
        d = views.Builder(self).detail(i, self.extra, self.played)
        with self.lock:
            self._detail_cache[pid] = d
        return d

    def _announce_plan(self, snap):
        """Six weeks before the summer window the sporting director sends the plan (once a season)."""
        window = dt.date(snap.date.year if snap.date.month <= 8 else snap.date.year + 1, 7, 1)
        if not 0 < (window - snap.date).days <= 42:
            return
        path = self.career.path('plan_announced.json')
        done = store._read_json(path, [])
        if window.year in done:
            return
        p = self.summer_plan()
        if p is None:
            return
        lines = [f'Kỳ chuyển nhượng hè mở ngày 1/7/{window.year}. Tôi đã chuẩn bị kế hoạch (Chuyển nhượng → Kế hoạch hè):']
        for g in p['needs'][:3]:
            pick = (g['targets']['value'] or g['targets']['best'] or [None])[0]
            lines.append(f'• {g["label"]}: {"; ".join(g["notes"])}'
                         + (f'. Đáng chú ý: {pick["name"]} ({pick["team_name"] or "tự do"}, {pick["age"]} tuổi)' if pick else ''))
        if p['renew']:
            lines.append('• Nên gia hạn: ' + ', '.join(x['name'] for x in p['renew'][:4]))
        if p['sell']:
            lines.append('• Có thể bán / cho mượn: ' + ', '.join(x['name'] for x in p['sell'][:4]))
        if not p['needs']:
            lines.append('• Đội hình mùa sau không có tuyến nào thiếu rõ rệt.')
        self.career.add_event({'date': snap.date.isoformat(), 'kind': 'transfer', 'from': 'director',
                               'title': f'Kế hoạch chuyển nhượng hè {window.year}', 'body': '\n'.join(lines),
                               'players': [x['id'] for g in p['needs'][:3] for x in (g['targets']['value'] or [])[:1]]})
        self.career.save()
        store.write_json(path, done + [window.year])

    def summer_plan(self):
        if self.snap is None or self.career is None or getattr(self, 'extra', None) is None:
            return None
        return plan.build(self)

    def search(self, q):
        if self.snap is None:
            return {'total': 0, 'players': []}
        return views.Builder(self).search(q)

    def mark_read(self, ids=None):
        if self.career is None:
            return
        self.career.mark_read(ids)

    def unread_ids(self):
        """The unread messages among those the page shows (the bundle's 400): what is read on one device (the
        phone, the PC) is read on the other one."""
        if self.career is None:
            return []
        with self.career.lock:
            return [e['id'] for e in self.career.events[:400] if not e.get('read')]

    def reply(self, ev_id, choice):
        """The manager answered a message: store it and publish the conversation at once."""
        if self.career is None:
            return None
        out = chat.reply(self.career, self.snap, ev_id, choice)
        if out and self.bundle_bytes:
            with self.lock:
                bundle = json.loads(self.bundle_bytes)
                bundle['inbox'] = [chat.decorate(dict(e), self.snap) for e in self.career.events[:400]]
                self.version += 1
                bundle['version'] = self.version
            raw = self._publish(bundle)
            try:
                tmp = self.career.bundle_path() + '.tmp'
                open(tmp, 'wb').write(raw)
                os.replace(tmp, self.career.bundle_path())
            except OSError:
                pass
        return out

    def status_json(self):
        with self.lock:
            s = dict(self.status)
            s['log'] = s['log'][-15:]
            s['version'] = self.version
            s['unread'] = sum(1 for e in self.career.events if not e.get('read')) if self.career else None
        ids = self.unread_ids()
        s['unread_sig'] = f'{len(ids)}:{zlib.crc32("|".join(ids).encode()):08x}'
        s['live'] = self.live.status_json()
        h = self.health
        s['health'] = {'level': h.get('level'), 'headline': health.headline(h), 'items': h.get('items', []),
                       'at': h.get('at'), 'save_date': h.get('save_date'), 'files': self.health_files}
        s['backup'] = self.backup_info
        snap = self.snap
        s['save'] = {'age': int(time.time() - snap.save_mtime) if snap is not None else None, 'game_on': self.game_on,
                     'game_date': snap.date.isoformat() if snap is not None else None}
        s['edits'] = [{'id': e['id'], 'time': e['time'], 'label': e.get('label', ''), 'undone': bool(e.get('undone')),
                       'mode': e.get('mode', 'save'), 'persisted': e.get('persisted')} for e in self.edit_log[:8]]
        s['ingame'] = self.ingame.status()
        return s


def POS(snap, i):
    return terms.POSITIONS[int(snap.main_pos[i])]


def _standing(snap):
    for tid in snap.my_tournaments:
        r = snap.regions.get(tid)
        if r and r.table:
            for t in r.table:
                if t.team_id == snap.team_id:
                    return {'pos': t.position, 'of': len(r.table), 'pts': t.points, 'comp': snap.comp_name(tid)}
    return None


def _advice_task(snap, i, g):
    """[kind, index, value before] of one suggestion, for following it up from later saves."""
    if g['kind'] == 'style':
        return ['style', int(g['to_idx']), int(snap.style[i])]
    if g['kind'] == 'skill':
        return ['skill', int(g['skill_idx']), 0]
    p = terms.POSITIONS.index(g['position'])
    return ['position', p, int(snap.grades[i, p])]


def _training_key(g):
    """[kind, what, source] of one training under way, for noticing when it starts."""
    what = g.get('to') or g.get('skill') or g.get('position')
    return [g['kind'], what, g.get('source', 'game')]


def _advice_line(g):
    if g['kind'] == 'style':
        return f'• Phong cách: nên chuyển sang {g["to"]} (hợp {g["fit_to"]}%, hiện tại {g["fit_from"]}%).'
    if g['kind'] == 'skill':
        return f'• Kỹ năng nên tập: {g["skill"]} (hợp {g["fit"]}%{"" if g["ready"] else ", cần tăng thêm chỉ số"}).'
    if g['kind'] == 'position':
        return f'• Vị trí nên luyện: {g["position"]} (hạng {g["grade"]}, OVR {g["ovr"]} ở vị trí này).'
    return ''

"""Live numbers from the running game (transfer and salary budget, market values): the save does
not hold them, only the game's memory does.

Dugout's own reader (gamemem, through ingame.Bridge) fills this while FL26 runs with the career
loaded; reads only. The budget is shown only when FL_2026.exe is the build whose budget code
Dugout checked; market values only from rows that carry the game's own marker and belong to
players of the save. Each game day's values are kept for the AI (store.MarketLog).
"""
import threading
import time

AI_TEXT = 'Giá trị cầu thủ và ngân sách: đọc từ game khi game đang mở (mỗi ngày trong game được lưu lại)'


class Live:
    def __init__(self, log=None):
        self.log = log or (lambda m: None)
        self.lock = threading.Lock()
        self.status = 'off'
        self.text = ''
        self.error = ''
        self.budget = None
        self.values = {}
        self.cond = {}
        self.version = 0
        self.read_at = 0.0
        self.on_world = None       # called with (values, budget) after each read, to keep them
        self._kept = None

    def update(self, budget=None, values=None, date=None, team=None):
        """New readings from the game. Only changes bump the version the web app watches."""
        with self.lock:
            changed = False
            if budget is not None:
                b = {**budget, 'team': team, 'date': date.isoformat() if date else None}
                if b != self.budget:
                    self.budget, changed = b, True
            if values is not None and values != self.values:
                self.values, changed = values, True
            self.status, self.error, self.read_at = 'active', '', time.time()
            self.text = 'Đang đọc từ game'
            if changed:
                self.version += 1
            keep = (date, len(self.values), (self.budget or {}).get('transfer'))
        if self.on_world and self.values and keep != self._kept:
            self._kept = keep
            try:
                self.on_world(dict(self.values), dict(self.budget or {}))
            except Exception as exc:
                self.log('Lưu giá trị cầu thủ lỗi: ' + repr(exc))

    def off(self, text='', error=''):
        with self.lock:
            if self.status != 'off' or self.text != text:
                self.status, self.text, self.error = 'off', text, error
                self.budget, self.values = None, {}
                self.version += 1

    def status_json(self):
        with self.lock:
            return {'status': self.status, 'text': self.text, 'ai_text': AI_TEXT, 'error': self.error,
                    'budget': self.budget, 'values': len(self.values), 'version': self.version}

    def data(self):
        with self.lock:
            return {'values': {str(k): v for k, v in self.values.items()}, 'cond': {}, 'budget': self.budget,
                    'status': self.status}

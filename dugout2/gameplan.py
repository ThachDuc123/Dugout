"""Game Plan rows of the save: for every manager, the club's current squad selection (starting XI
in pitch-slot order, bench, captain), the formation (role and pitch coordinates of each slot), the
team instructions and the advanced instructions. Read-only.

Rows are 0x258 bytes, one per manager; the club -> row index is a u16 at team record +0x28C.
Rows are addressed directly (the table has gaps, and the user's own row sits after one).
  +59   formation of preset 1 (33 bytes): 8 role bytes for slots 3-10 (slots 1-2 are always CB),
        1 byte, keeper x, then (y, x) for the 10 outfield slots. The lineup order matches these
        slots (checked against the registered positions of every club's XI).
  +155  the seven team instructions, 0 = first option in the game's menu (+157 Attacking Area
        and +161 Pressuring were checked by changing them in game).
  +164 +172 attacking advanced instructions 1-2, +180 +188 defensive 1-2 (0 = none).
  +196 Support Range, +198 Defensive Line, +199 Compactness (1-10).
  +576 set-piece takers, roster indices in the game's menu order: long free kick, short free kick,
        second free-kick taker, left corner, right corner, penalty (checked: Salah, Mbappé and
        Højlund take penalties, de Jong and Tchouaméni long free kicks).
  Formations: 3 preset tactics (+59, +219, +379), each with 3 records 33 bytes apart: at
        kick-off, in possession, out of possession (the game's "Khi giao bóng / Khi kiểm soát
        bóng / Khi mất bóng"). The lineup follows preset 1.
"""
import struct

from . import terms
from .pes import career as pc

ROW = 600
LINEUP = 536
SET_PIECES = 576
CAPTAIN = 585
TEAM_INDEX = 652            # u16 in the team record
FORMATION = 59
PRESETS = (59, 219, 379)
PHASES = (('kickoff', 'Khi giao bóng'), ('attack', 'Khi kiểm soát bóng'), ('defence', 'Khi mất bóng'))
SET_PIECE_KEYS = [('fk_long', 'Đá phạt xa'), ('fk_short', 'Đá phạt gần'), ('fk_second', 'Cầu thủ Đá Phạt Thứ 2'),
                  ('ck_left', 'Đá phạt góc trái'), ('ck_right', 'Đá phạt góc phải'), ('pk', 'Đá Penalty')]
TOGGLE_AT = 155
INSTR_AT = {'atk1': 164, 'atk2': 172, 'def1': 180, 'def2': 188}
NUMBER_AT = {'support_range': 196, 'defensive_line': 198, 'compactness': 199}

# (key, VH21 name, English, (option 0 VH21, English), (option 1 VH21, English))
TOGGLES = [
    ('attacking_style', 'Kiểu tấn công', 'Attacking Style', ('Phản công', 'Counter Attack'), ('Kiểm soát thế trận', 'Possession Game')),
    ('build_up', 'Build Up', 'Build Up', ('Chuyền dài', 'Long Pass'), ('Chuyền ngắn', 'Short Pass')),
    ('attacking_area', 'Tấn công khu vực', 'Attacking Area', ('Rộng', 'Wide'), ('Trung lộ', 'Centre')),
    ('positioning', 'Vị trí', 'Positioning', ('Giữ đội hình', 'Maintain Formation'), ('Linh hoạt', 'Flexible')),
    ('defensive_style', 'Phong cách phòng thủ', 'Defensive Style', ('Áp sát từ xa', 'Frontline Pressure'), ('Chuyên phòng ngự', 'All-out Defence')),
    ('containment_area', 'Chính sách khu vực', 'Containment Area', ('Trung lộ', 'Middle'), ('Khắp sân', 'Wide')),
    ('pressuring', 'Áp lực', 'Pressuring', ('Công kích', 'Aggressive'), ('Bảo toàn', 'Conservative')),
]
NUMBERS = [('support_range', 'Support Range', 'Support Range'),
           ('defensive_line', 'Phòng thủ theo các tuyến', 'Defensive Line'),
           ('compactness', 'Sự chắc chắn', 'Compactness')]
# Advanced instructions as VH21 names them. 1-10 attacking, 11-16 defensive.
INSTRUCTIONS = {1: ('Dạt biên', 'Hug the Touchline'), 2: ('Số 9 ảo', 'False No. 9'),
                3: ('Hậu vệ cánh ảo', 'False Full-backs'), 4: ('Hậu vệ công', 'Attacking Full-backs'),
                5: ('Đảo cánh', 'Wing Rotation'), 6: ('Tiki-Taka', 'Tiki-Taka'),
                7: ('Tập trung vòng cấm', 'Centering Targets'), 8: ('Tiền vệ cánh ảo', ''),
                9: ('Hậu vệ cánh giữ vị trí', ''), 10: ('Tiền vệ mỏ neo', 'Anchoring'),
                11: ('Xe buýt hai tầng', 'Swarm the Box'), 12: ('Hàng phòng ngự lùi sâu', 'Deep Defensive Line'),
                13: ('Pressing tầm cao', 'Gegenpress'), 14: ('Kèm người chặt chẽ', 'Tight Marking'),
                15: ('Phòng ngự phản công', 'Counter Target'), 16: ('Phòng ngự', '')}


def instruction_label(k):
    vi, en = INSTRUCTIONS.get(k, (f'#{k}', ''))
    return f'{vi} ({en})' if en and en != vi else vi


def toggle_label(key, value):
    for k, vi, en, o0, o1 in TOGGLES:
        if k == key:
            o = (o0, o1)[int(value) & 1]
            return f'{o[0]} ({o[1]})'
    return str(value)


def shape_label(roles, points):
    """e.g. 4-2-3-1: the defenders (CB/LB/RB roles) first, the others banded back to front by depth."""
    if len(roles) != 10 or len(points) != 10:
        return ''
    defenders = sum(1 for r in roles if r in (1, 2, 3))
    ys = sorted(y for r, (y, x) in zip(roles, points) if r not in (1, 2, 3))
    bands = [defenders] if defenders else []
    cur = []
    for y in ys:
        if cur and y - cur[-1] > 5:
            bands.append(len(cur))
            cur = []
        cur.append(y)
    if cur:
        bands.append(len(cur))
    return '-'.join(map(str, bands)) if len(bands) <= 5 else ''


def table_start(data):
    try:
        return pc.gameplan_table_start(data)
    except Exception:
        return None


def row_index(data, team_offset):
    return struct.unpack_from('<H', data, team_offset + TEAM_INDEX)[0]


def row_bytes(data, start, team_offset):
    """The club's raw Game Plan row, kept with each match to learn later which tactics work."""
    if start is None:
        return None
    idx = row_index(data, team_offset)
    off = start + idx * ROW
    if idx == 0xFFFF or off + ROW > len(data):
        return None
    return bytes(data[off:off + ROW])


def read(data, start, team_offset, roster):
    """Game Plan of one club. `roster` = the club's player ids in squad-list order.
    Returns None when the row is missing or does not look like a Game Plan."""
    if start is None:
        return None
    idx = row_index(data, team_offset)
    off = start + idx * ROW
    if idx == 0xFFFF or off + ROW > len(data):
        return None
    r = data[off:off + ROW]
    if not pc.valid_gameplan_row(r):
        return None
    manager = pc.gameplan_name(r)
    order = [b for b in r[LINEUP:LINEUP + 40] if b != 0xFF]
    if len(order) < 11 or any(b >= len(roster) for b in order[:11]):
        return None
    formation = _record(r, FORMATION)
    if formation is None:
        return None
    roles, points = formation
    xi =[{'id': int(roster[order[s]]), 'slot': s, 'role': roles[s], 'y': points[s][0], 'x': points[s][1]}
          for s in range(11)]
    bench = [int(roster[b]) for b in order[11:23] if b < len(roster)]
    cap = r[CAPTAIN]
    toggles = {k: int(r[TOGGLE_AT + j]) & 1 for j, (k, *_x) in enumerate(TOGGLES)}
    numbers = {k: int(r[at]) for k, at in NUMBER_AT.items()}
    instr = {k: int(r[at]) for k, at in INSTR_AT.items() if r[at]}
    takers = {}
    for j, (k, _label) in enumerate(SET_PIECE_KEYS):
        b = r[SET_PIECES + j]
        if b < len(roster):
            takers[k] = int(roster[b])
    # the three phases of each preset: roles per slot and the shape
    presets = []
    for base in PRESETS:
        phases = {}
        for k, (key, _label) in enumerate(PHASES):
            rec = _record(r, base + 33 * k)
            if rec:
                phases[key] = {'roles': rec[0], 'points': rec[1], 'shape': shape_label(rec[0][1:], rec[1][1:])}
        presets.append(phases)
    return {'manager': manager, 'row': idx, 'xi': xi, 'bench': bench,
            'captain': int(roster[cap]) if cap < len(roster) else None,
            'shape': shape_label(roles[1:], points[1:]), 'toggles': toggles, 'numbers': numbers,
            'instructions': instr, 'set_pieces': takers, 'presets': presets}


def _record(r, off):
    """(roles of the 11 slots, (y, x) of the 11 slots) of one formation record, or None."""
    f = r[off:off + 33]
    if len(f) < 33 or not any(f[10:30]):
        return None
    roles = [0, 1, 1] + [int(v) for v in f[:8]]
    if any(v > 12 for v in roles):
        return None
    points = [(0, int(f[9]))] + [(int(f[10 + 2 * j]), int(f[11 + 2 * j])) for j in range(10)]
    return roles, points


def phase_summary(plan, xi_ids=None):
    """How the side reshapes with and without the ball, and the other presets' shapes."""
    if not plan or not plan.get('presets'):
        return None
    p1 = plan['presets'][0]
    out = {'phases': [], 'presets': []}
    base = p1.get('kickoff')
    for key, label in PHASES:
        ph = p1.get(key)
        if not ph:
            continue
        moves = []
        if base and key != 'kickoff':
            for s in range(1, 11):
                if ph['roles'][s] != base['roles'][s]:
                    moves.append({'slot': s, 'from': terms.POSITIONS[base['roles'][s]], 'to': terms.POSITIONS[ph['roles'][s]],
                                  'id': xi_ids[s] if xi_ids and s < len(xi_ids) else None})
        out['phases'].append({'key': key, 'label': label, 'shape': ph['shape'], 'moves': moves})
    for k, pr in enumerate(plan['presets'][1:], start=2):
        ph = pr.get('kickoff')
        if ph and ph['roles'] != (base or {}).get('roles'):
            out['presets'].append({'n': k, 'shape': ph['shape'],
                                   'attack': (pr.get('attack') or {}).get('shape', ''),
                                   'defence': (pr.get('defence') or {}).get('shape', '')})
    return out


def describe(plan):
    """Readable team instructions for the UI."""
    if not plan:
        return None
    rows = []
    for k, vi, en, o0, o1 in TOGGLES:
        v = plan['toggles'].get(k, 0)
        o = (o0, o1)[v]
        rows.append({'key': k, 'label': vi, 'en': en, 'value': v, 'text': o[0], 'text_en': o[1]})
    for k, vi, en in NUMBERS:
        rows.append({'key': k, 'label': vi, 'en': en, 'value': plan['numbers'].get(k), 'text': str(plan['numbers'].get(k))})
    return {'rows': rows,
            'instructions': [{'slot': k, 'id': v, 'text': instruction_label(v)} for k, v in plan['instructions'].items()],
            'shape': plan['shape'], 'manager': plan['manager']}


def role_name(role):
    return terms.POSITIONS[role]

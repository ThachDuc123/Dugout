"""The career side of a Master League save: game date, the career player table (inflated from
the compressed block), squads, player states and Game Plan rows.

Career player record (156 bytes, table phase 8 in the inflated block):
  10        age << 2 (6 bits)                 13 bit 3  registered position (4 bits)
  16 bit 6  weak foot accuracy - 1 (2 bits)   24  u32 career index      28  u32 player id
  96        team role & 31                    108 u32 annual salary / 100
  124 u16   contract end year (65535 = no contract), 126 month, 127 day
  130       affection   136 u16 nationality   139 youth-team mark (48)
  140       days unavailable                  144 u16 stamina (7 bits) | condition << 7 (3 bits)
  145       retiring 0x40                     146 transfer listed 1, loan listed 2, free exit 4
  153       career impact
Abilities are 6-bit fields (+40), some in the record and some in the 8 bytes before it.
"""
import datetime as dt
import struct

RECORD = 156
PHASE = 8
ID_AT, INDEX_AT = 28, 24
CREATED_FLAG = 0x80000000
CREATED_BASE = 1 << 32

HEADER_ABILITIES = (('place_kicking', 0, 0), ('curl', 0, 6), ('gk_catching', 1, 4), ('gk_clearing', 2, 2),
                    ('gk_reflexes', 3, 0), ('gk_reach', 4, 0), ('speed', 4, 6), ('physical_contact', 5, 4),
                    ('balance', 6, 2), ('kicking_power', 7, 0), ('acceleration', 8, 0), ('jump', 8, 6),
                    ('stamina', 9, 4), ('tight_possession', 11, 0), ('aggression', 12, 0))
EXTENDED_ABILITIES = (('offensive_awareness', -8, 0), ('defensive_awareness', -8, 6), ('gk_awareness', -7, 4),
                      ('dribbling', -6, 2), ('ball_control', -5, 0), ('finishing', -4, 0), ('low_pass', -4, 6),
                      ('lofted_pass', -3, 4), ('heading', -2, 2), ('ball_winning', -1, 0))
POSITION_AT = (13, 3, 4)
WEAK_FOOT_AT = (16, 6, 2)
POSITIONS = ('GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF', 'AMF', 'LWF', 'RWF', 'SS', 'CF')
# position grades, 2 bits (0 C, 1 B, 2 A), bit offsets from the record start; SS and CF sit in the
# 8 bytes before the record (like the extended abilities)
GRADE_BITS = {'GK': 132, 'CB': 125, 'LB': 128, 'RB': 130, 'DMF': 117, 'CMF': 119, 'LMF': 121, 'RMF': 123,
              'AMF': 94, 'LWF': 30, 'RWF': 62, 'SS': -2, 'CF': -34}
STYLE_BIT = 102                     # 5 bits, career enum (0 = none)
GK_STYLES = {16, 17}                # database style ids that only a goalkeeper has

# squads (team records in the data block)
TEAM_RECORD_MIN = 748
SQUAD_SLOT_START, ROSTER_INDEX_START, SQUAD_SLOT_SIZE = 336, 332, 8
SHIRT_NUMBER_START = 666
SQUAD_COUNT_AT = 1062
MAX_SQUAD_SLOTS, FIRST_TEAM_SLOTS = 40, 23

# Game Plan rows
GAMEPLAN_STRIDE = 600
GAMEPLAN_LINEUP, GAMEPLAN_CAPTAIN, GAMEPLAN_NO_CAPTAIN = 536, 585, 255

TEAM_ROLE_NAMES = ('', 'Youth Prospect', 'Protege', 'Team Player', 'Playmaker', 'Star Player', 'Leader', 'General',
                   'Creator', 'Maestro', 'Workhorse', 'Smart Player', 'Fighter', 'Key Player', 'Superstar', 'Hero',
                   'Virtuoso', 'Conductor', 'Bandiera', 'Legend', 'Rising Star', 'Bad Boy', 'Risk-Taker')


def read_bits(buf, offset, bit, width):
    absolute = offset * 8 + bit
    first, final = absolute // 8, (absolute + width + 7) // 8
    return (int.from_bytes(buf[first:final], 'little') >> (absolute % 8)) & ((1 << width) - 1)


def write_bits(buf, offset, bit, width, value):
    absolute = offset * 8 + bit
    first, final = absolute // 8, (absolute + width + 7) // 8
    word = int.from_bytes(buf[first:final], 'little')
    mask = ((1 << width) - 1) << (absolute % 8)
    word = (word & ~mask) | ((value << (absolute % 8)) & mask)
    buf[first:final] = word.to_bytes(final - first, 'little')


def is_database_id(pid):
    return 100 <= int(pid) <= 1000000


def is_created_id(pid):
    return int(pid) >= CREATED_FLAG


def occupied(pid):
    return is_database_id(pid) or is_created_id(pid)


def snapshot_id(ml_id, career_index):
    """Database players keep their id; created players (regens...) get 2^32 + their career index."""
    return CREATED_BASE + (int(career_index) & 0xFFFFFFFF) if is_created_id(ml_id) else int(ml_id)


# ------------------------------------------------------------------------- game date
def _fixed_doy(month, day):
    return sum((31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[:month - 1]) + day - 1


def clocks(data):
    """{managed team id: {'year', 'month', 'day'}}: the career clock record is
    u16 day-of-year, u16 year, u32 days-in-year, u16 year, u8 month, u8 day, u32 0, u32 team << 14."""
    found = {}
    for anchor in (365, 366):
        needle = struct.pack('<I', anchor)
        start = 4
        while True:
            pos = data.find(needle, start)
            if pos < 0:
                break
            start = pos + 1
            at = pos + 4
            if at < 8 or at + 12 > len(data):
                continue
            year = struct.unpack_from('<H', data, at)[0]
            if not 2018 <= year <= 2199:
                continue
            month, day = data[at + 2], data[at + 3]
            try:
                d = dt.date(year, month, day)
            except ValueError:
                continue
            if struct.unpack_from('<I', data, at + 4)[0] != 0:
                continue
            team = struct.unpack_from('<I', data, at + 8)[0] >> 14
            if team < 1:
                continue
            doy, year2, days = struct.unpack_from('<HHI', data, at - 8)
            if year2 != year or days not in (365, 366):
                continue
            if doy not in (_fixed_doy(month, day), d.toordinal() - dt.date(year, 1, 1).toordinal()):
                continue
            found.setdefault(team, set()).add((year, month, day))
    return {team: {'year': v[0], 'month': v[1], 'day': v[2]}
            for team, values in found.items() if len(values) == 1 for v in values}


# ------------------------------------------------------------------ career player table
def records(table):
    """(record start, ml player id, career index) of every occupied record."""
    out = []
    for start in range(PHASE, len(table) - RECORD + 1, RECORD):
        mid = struct.unpack_from('<I', table, start + ID_AT)[0]
        if occupied(mid):
            out.append((start, mid, struct.unpack_from('<I', table, start + INDEX_AT)[0]))
    return out


def abilities(table, start):
    rec = table[start:start + RECORD]
    out = {}
    for key, offset, bit in HEADER_ABILITIES:
        v = read_bits(rec, offset, bit, 6) + 40
        if 40 <= v <= 99:
            out[key] = v
    for key, delta, bit in EXTENDED_ABILITIES:
        at = start + delta
        if at < 0 or at + 2 > len(table):
            continue
        v = read_bits(table, at, bit, 6) + 40
        if 40 <= v <= 99:
            out[key] = v
    return out


def age(rec):
    a = (rec[10] >> 2) & 63
    return a if 15 <= a <= 55 else None


def position(rec):
    v = read_bits(rec, *POSITION_AT)
    return v if v < 13 else None


def grade(table, start, pos):
    return read_bits(table, start, GRADE_BITS[pos], 2)


def weak_foot_accuracy(rec):
    return read_bits(rec, *WEAK_FOOT_AT) + 1


def salary(rec):
    v = struct.unpack_from('<I', rec, 108)[0]
    return v * 100 if 1 <= v <= 2000000 else None


def player_states(table, include_unassigned=False):
    """Contract, condition, fitness, availability, role and listing of every player under contract."""
    states = {}
    for start, mid, cidx in records(table):
        rec = table[start:start + RECORD]
        pid = snapshot_id(mid, cidx)
        year = struct.unpack_from('<H', rec, 124)[0]
        nationality = struct.unpack_from('<H', rec, 136)[0]
        role = rec[96] & 31
        unassigned = year == 65535
        if unassigned and not include_unassigned:
            continue
        if not ((unassigned or 1900 <= year <= 2200) and nationality <= 1024 and role <= 31):
            continue
        word = struct.unpack_from('<H', rec, 144)[0]
        form = (word >> 7) & 7
        form = None if form > 4 else form
        st = {'player_id': pid, 'ml_player_id': mid, 'career_index': cidx,
              'contract_end_year': None if unassigned else year,
              'contract_end_month': None if unassigned else rec[126],
              'contract_end_day': None if unassigned else rec[127],
              'affection': rec[130], 'age': age(rec), 'weak_foot_accuracy': weak_foot_accuracy(rec),
              'nationality_id': nationality, 'form_code': form, 'condition': form,
              'form_verified': form is not None, 'stamina': word & 127, 'unavailable_days': rec[140],
              'transfer_listed': bool(rec[146] & 1), 'loan_listed': bool(rec[146] & 2),
              'free_exit_window': bool(rec[146] & 4), 'is_retiring': bool(rec[145] & 64),
              'team_role_id': role, 'role': TEAM_ROLE_NAMES[role] if role < len(TEAM_ROLE_NAMES) else '',
              'career_impact': rec[153]}
        if unassigned:
            st['unassigned_pool'] = True
            st['youth_team_mark'] = rec[139] == 48
        sal = salary(rec)
        if sal is not None:
            st['annual_salary_raw'] = sal
        p = position(rec)
        if p is not None:
            st['registered_position_id'] = p
        if is_created_id(mid):
            st['created_player'] = True
        states[pid] = st
    return states


# ------------------------------------------------------------------------------ squads
def team_squad(data, team_offset, max_slots=MAX_SQUAD_SLOTS):
    """The club's squad list: player id, career index, roster position (1-based) and shirt number."""
    slots, seen = [], set()
    for index in range(max(1, min(int(max_slots), MAX_SQUAD_SLOTS))):
        id_at = team_offset + SQUAD_SLOT_START + index * SQUAD_SLOT_SIZE
        index_at = team_offset + ROSTER_INDEX_START + index * SQUAD_SLOT_SIZE
        if id_at + 4 > len(data) or index_at + 4 > len(data):
            break
        mid = struct.unpack_from('<I', data, id_at)[0]
        if not occupied(mid):
            continue
        cidx = struct.unpack_from('<I', data, index_at)[0]
        if is_created_id(mid) and cidx == 0:
            continue
        pid = snapshot_id(mid, cidx)
        if pid in seen:
            continue
        seen.add(pid)
        shirt_at = team_offset + SHIRT_NUMBER_START + index * 2
        shirt = struct.unpack_from('<H', data, shirt_at)[0] if shirt_at + 2 <= len(data) else 0
        slot = {'player_id': pid, 'ml_player_id': mid, 'career_index': cidx, 'roster_position': index + 1,
                'shirt_number': shirt if 1 <= shirt <= 999 else 0}
        if is_created_id(mid):
            slot['created_player'] = 1
        slots.append(slot)
    return slots


# --------------------------------------------------------------------------- Game Plan
def _printable_name(raw):
    try:
        name = raw.split(b'\0', 1)[0].decode('utf-8').strip()
    except UnicodeDecodeError:
        return ''
    if not name or not all(ch.isprintable() for ch in name) or not any(ch.isalpha() for ch in name):
        return ''
    return name


def gameplan_name(row):
    return _printable_name(bytes(row[:48]))


def valid_gameplan_row(row):
    if len(row) < GAMEPLAN_STRIDE or not gameplan_name(row):
        return False
    captain = struct.unpack_from('<I', row, GAMEPLAN_CAPTAIN)[0]
    if captain > 39 and captain != GAMEPLAN_NO_CAPTAIN:
        return False
    return all(b == 255 or b <= 39 for b in row[GAMEPLAN_LINEUP:GAMEPLAN_LINEUP + 40])


def gameplan_table_start(data):
    """The first of the consecutive Game Plan rows (one per club). Candidates are narrowed with
    numpy (two rows in a row whose 40 line-up bytes are all slot numbers or 255), then checked."""
    import numpy as np
    d = np.frombuffer(data, dtype=np.uint8)
    limit = max(0, len(data) - 2 * GAMEPLAN_STRIDE)
    ok = ((d <= 39) | (d == 255)).astype(np.int32)
    run = np.concatenate([[0], np.cumsum(ok)])
    n = len(d) - GAMEPLAN_LINEUP - 40 + 1
    if n <= 0 or limit <= 0:
        return None
    lineup_ok = (run[GAMEPLAN_LINEUP + 40:GAMEPLAN_LINEUP + 40 + n] - run[GAMEPLAN_LINEUP:GAMEPLAN_LINEUP + n]) == 40
    m = min(limit, len(lineup_ok) - GAMEPLAN_STRIDE)
    cand = np.nonzero(lineup_ok[:m] & lineup_ok[GAMEPLAN_STRIDE:GAMEPLAN_STRIDE + m]
                      & (d[:m] >= 65) & (d[:m] <= 90))[0]
    for start in cand.tolist():
        if not valid_gameplan_row(data[start:start + GAMEPLAN_STRIDE]):
            continue
        if not valid_gameplan_row(data[start + GAMEPLAN_STRIDE:start + 2 * GAMEPLAN_STRIDE]):
            continue
        while start >= GAMEPLAN_STRIDE and valid_gameplan_row(data[start - GAMEPLAN_STRIDE:start]):
            start -= GAMEPLAN_STRIDE
        return start
    return None


def negotiation_list(table):
    """Players on the manager's negotiation list (flag 0x10 at byte 145); nothing when the flag
    looks like it means something else (more than 1% of players set)."""
    occupied_n, rows = 0, []
    for start, mid, cidx in records(table):
        occupied_n += 1
        if table[start + 145] & 16:
            rows.append(snapshot_id(mid, cidx))
    if not occupied_n or len(rows) / occupied_n > 0.01:
        return []
    return rows

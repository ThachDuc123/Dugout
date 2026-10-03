"""The club's development table in a Master League save: one 368-byte record for every player the
manager's club develops (first team and youth team), holding the in-game individual training.

Record (offsets from the record start):
  48        u32 career index, 52 u32 player id
  72        13 x u16 position proficiency: 0 = C, 5000 = B, 10000 = A; a value in between is the
            progress towards the next grade (position training, or playing there)
            order CF SS LWF RWF AMF DMF CMF LMF RMF CB LB RB GK
  190       7 x u16 COM playing styles, 10000 = has it
  204..     one u16 per skill: 10000 = has it, a value in between = skill training in progress
            (skill with career bit b at 176 + 2 * (b - 125); Scissors Feint at 204)
  296       u32 the playing style the player trains towards (own numbering, STYLE_CODE); the current
            style when no style training is set, 22 = none

Checked against the career table on 7 saves (grades and skills agree 100%).
"""
import collections
import struct

RECORD = 368
SLOTS = 84                       # records in the table
PAIR_AT = 48
POSITION_AT = 72
POSITION_ORDER = ('CF', 'SS', 'LWF', 'RWF', 'AMF', 'DMF', 'CMF', 'LMF', 'RMF', 'CB', 'LB', 'RB', 'GK')
COM_AT = 190
SKILL_BASE = 176
STYLE_AT = 296
FULL, GRADE_B = 10000, 5000
NO_STYLE = 22

# career style enum (the 5-bit field of the career record) -> the number used at STYLE_AT
STYLE_CODE = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10, 11: 11, 12: 12, 13: 13,
              14: 15, 15: 17, 16: 16, 17: 18, 18: 14, 19: 19, 20: 20, 21: 21}
CODE_STYLE = {v: k for k, v in STYLE_CODE.items()}


def skill_offset(career_bit):
    return SKILL_BASE + 2 * (14 if career_bit == 127 else career_bit - 125)


def _pair(cidx, pid):
    return struct.pack('<II', cidx & 0xFFFFFFFF, pid & 0xFFFFFFFF)


def locate(data, squad):
    """Record offsets of the table, found from the club's squad [(career index, player id)]: the
    squad's records sit at one stride; returns (first, last) record offsets holding a squad player."""
    found = []
    for cidx, pid in squad:
        pat = _pair(cidx, pid)
        at = data.find(pat)
        while at >= 0:
            found.append(at - PAIR_AT)
            at = data.find(pat, at + 1)
    groups = collections.defaultdict(list)
    for off in found:
        groups[off % RECORD].append(off)
    best = None
    for offs in groups.values():
        offs.sort()
        j = 0
        for i in range(len(offs)):
            while offs[i] - offs[j] >= SLOTS * RECORD:
                j += 1
            if best is None or i - j + 1 > best[0]:
                best = (i - j + 1, offs[j], offs[i])
    if best is None or best[0] < max(3, len(squad) // 2):
        return None
    return best[1], best[2]


def read(data, squad, known):
    """{(career index, player id): record} for the club's players. `known` is the set of every
    (career index, player id) in the career table: a record counts only if its pair is one."""
    loc = locate(data, squad)
    if loc is None:
        return {}
    first, last = loc
    lo = max(0, first - (SLOTS - 1) * RECORD)
    lo += (first - lo) % RECORD
    out = {}
    for off in range(lo, min(len(data) - RECORD, last + (SLOTS - 1) * RECORD) + 1, RECORD):
        pair = struct.unpack_from('<II', data, off + PAIR_AT)
        if pair in known:
            out[pair] = bytes(data[off:off + RECORD])
    return out


def positions(raw):
    """{position name: proficiency 0..10000}."""
    return dict(zip(POSITION_ORDER, struct.unpack_from('<13H', raw, POSITION_AT)))


def skill_value(raw, career_bit):
    return struct.unpack_from('<H', raw, skill_offset(career_bit))[0]


def style_target(raw, current_career_style):
    """Career style enum the player trains towards, or 0 when no style training is set."""
    code = struct.unpack_from('<I', raw, STYLE_AT)[0]
    if code == NO_STYLE or code not in CODE_STYLE or code == STYLE_CODE.get(current_career_style):
        return 0
    return CODE_STYLE[code]

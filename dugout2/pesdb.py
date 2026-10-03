"""PES 2021 database reader (Player.bin / Team.bin) for the FL26 UML database.

Bit layout of the 312-byte Player.bin record, derived by matching every field against
the 27,155-player career table of a decoded Master League save and against pesdb.net:
  +0x08 u32 player id, +0x44 name, +0x81 shirt name
  abilities: 6-bit value + 40 at the bit offsets in ABILITY_BITS
  base age: 5 bits @408 + 15, height: 7 bits @216 + 100, nationality: 9 bits @233,
  stronger foot: 1 bit @514 (1 = left), playing style: 5 bits @155
  registered position: 4 bits @434, position grades: 2 bits each (0 C, 1 B, 2 A)
  player skills and COM playing styles: one bit each (terms.SKILLS / terms.COM_STYLES)
  weak foot accuracy: 2 bits @462 + 1 (matches the save's value for 99.99% of 17,921 players),
  weak foot usage: 2 bits @454 + 1 (11 of 15 players match pesdb.net's PES 2021 values; FL26 edits
  some). Form and injury resistance could not be located with confidence and are not read.
Derby.bin: 12-byte records (team, team, id).
"""
import os
import struct
import zlib

import numpy as np

from . import config, terms

RECORD = 312
ABILITIES = terms.ABILITIES
ABILITY_BITS = {'place_kicking': 250, 'low_pass': 263, 'gk_clearing': 269, 'defensive_awareness': 275,
                'ball_control': 281, 'heading': 288, 'jump': 294, 'gk_reach': 300, 'speed': 306,
                'ball_winning': 312, 'gk_reflexes': 320, 'gk_awareness': 326, 'curl': 332, 'stamina': 338,
                'acceleration': 344, 'dribbling': 352, 'kicking_power': 358, 'gk_catching': 364,
                'offensive_awareness': 370, 'balance': 376, 'aggression': 384, 'physical_contact': 390,
                'finishing': 396, 'lofted_pass': 402, 'tight_possession': 416}
POSITIONS = terms.POSITIONS
GRADE_BITS = {'GK': 350, 'CB': 468, 'LB': 318, 'RB': 474, 'DMF': 414, 'CMF': 456, 'LMF': 466,
              'RMF': 460, 'AMF': 464, 'LWF': 472, 'RWF': 476, 'SS': 478, 'CF': 470}
AGE_BIT, HEIGHT_BIT, NATION_BIT, POS_BIT, LEFT_FOOT_BIT, STYLE_BIT = 408, 216, 233, 434, 514, 155
WEAK_USAGE_BIT, WEAK_ACCURACY_BIT = 454, 462

TEAM_RECORD = 1532


def wesys(path):
    d = open(path, 'rb').read()
    if d[3:8] == b'WESYS':
        csize = struct.unpack_from('<I', d, 8)[0]
        return zlib.decompress(d[16:16 + csize])
    return d


def bits(records, bit, width):
    """Read a little-endian bit field from every row of a uint8 record matrix."""
    byte, shift = bit // 8, bit % 8
    span = (shift + width + 7) // 8
    v = np.zeros(len(records), dtype=np.int64)
    for k in range(span):
        v |= records[:, byte + k].astype(np.int64) << (8 * k)
    return (v >> shift) & ((1 << width) - 1)


def pack_flags(records, bit_list):
    """One bit per entry of bit_list -> uint64 mask (bit k = entry k)."""
    out = np.zeros(len(records), dtype=np.uint64)
    for k, b in enumerate(bit_list):
        out |= bits(records, b, 1).astype(np.uint64) << np.uint64(k)
    return out


def _text(raw, off, size):
    return raw[off:off + size].split(b'\0', 1)[0].decode('utf-8', 'replace')


class PlayerDB:
    def __init__(self, path=None):
        path = path or config.effective_file(os.path.join('common', 'etc', 'pesdb', 'Player.bin'))
        if not path:
            raise FileNotFoundError('Không tìm thấy Player.bin trong livecpk')
        self.path = path
        raw = wesys(path)
        n = len(raw) // RECORD
        rec = np.frombuffer(raw[:n * RECORD], dtype=np.uint8).reshape(n, RECORD)
        self.ids = rec[:, 8:12].copy().view('<u4').ravel().astype(np.int64)
        self.index = {int(pid): i for i, pid in enumerate(self.ids)}
        self.abilities = np.stack([bits(rec, ABILITY_BITS[a], 6) + 40 for a in ABILITIES], axis=1).astype(np.float32)
        self.age = (bits(rec, AGE_BIT, 5) + 15).astype(np.int32)
        self.height = (bits(rec, HEIGHT_BIT, 7) + 100).astype(np.int32)
        self.nation = bits(rec, NATION_BIT, 9).astype(np.int32)
        self.position = bits(rec, POS_BIT, 4).astype(np.int32)
        self.left_foot = bits(rec, LEFT_FOOT_BIT, 1).astype(np.int8)
        self.style = bits(rec, STYLE_BIT, 5).astype(np.int8)
        self.style[self.style >= len(terms.STYLES)] = 0
        self.grades = np.stack([bits(rec, GRADE_BITS[p], 2) for p in POSITIONS], axis=1).astype(np.int8)
        self.skills = pack_flags(rec, [s[2] for s in terms.SKILLS])
        self.com = pack_flags(rec, [c[2] for c in terms.COM_STYLES]).astype(np.uint8)
        self.weak_usage = (bits(rec, WEAK_USAGE_BIT, 2) + 1).astype(np.int8)
        self.weak_accuracy = (bits(rec, WEAK_ACCURACY_BIT, 2) + 1).astype(np.int8)
        self.names = [_text(raw, i * RECORD + 0x44, 61).strip() for i in range(n)]
        self.shirt_names = [_text(raw, i * RECORD + 0x81, 61) for i in range(n)]

    def name(self, pid):
        i = self.index.get(int(pid))
        return self.names[i] if i is not None and self.names[i] else f'#{pid}'


class TeamDB:
    def __init__(self, path=None):
        path = path or config.effective_file(os.path.join('common', 'etc', 'pesdb', 'Team.bin'))
        raw = wesys(path)
        self.names, self.short = {}, {}
        for i in range(len(raw) // TEAM_RECORD):
            base = i * TEAM_RECORD
            tid = struct.unpack_from('<I', raw, base + 8)[0]
            self.names[tid] = _text(raw, base + 368, 70)
            self.short[tid] = _text(raw, base + 1462, 70) or self.names[tid]

    def name(self, tid):
        return self.names.get(tid) or ''


def derbies():
    """Pairs of club ids the database marks as derbies."""
    path = config.effective_file(os.path.join('common', 'etc', 'pesdb', 'Derby.bin'))
    out = set()
    if not path:
        return out
    raw = wesys(path)
    for k in range(0, len(raw) - 11, 12):
        a, b, _id = struct.unpack_from('<III', raw, k)
        if a and b and a != b and a < 100000 and b < 100000:
            out.add(frozenset((a, b)))
    return out


def skill_list(mask):
    """uint64 mask -> list of skill indexes."""
    m = int(mask)
    return [k for k in range(len(terms.SKILLS)) if m >> k & 1]

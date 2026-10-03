"""Clubs, fixtures (with both line-ups), league tables, scorer rankings and knockout ties.

Club record (1680 bytes from offset 80): u32 team << 14, name (64) at 4, short name (4) at 74,
stadium (64) at 80.
Fixture row (596 bytes): u16 tournament, u8 stage, u8 flags (played 64, second leg 16, single match
32), u16 year, u8 month, u8 day, u32, u32 kick-off hour, u32 home << 14, u32 away << 14, goals /
extra time / shoot-out for home then away (6 bytes at 24), 17 home and 18 away appearances of 16
bytes (at 32 and 304), u32 row id at 592.
Region (league) header every 6268 bytes: u32 teams, u32 tournament, u32 last matchday, u32 1;
current table 1924 bytes before it, rankings of scorers (60) and assists (872) after it.
"""
import datetime as dt
import struct
from dataclasses import dataclass, field

PACK = 14
UNDECIDED = 262143
TEAM_RECORD_SIZE, TEAM_TABLE_START, TEAM_TABLE_MAX, TEAM_STOP_AFTER_INVALID = 1680, 80, 1400, 64
FIXTURE_ROW, FIXTURE_HINT, FIXTURE_MAX_ROWS, FIXTURE_STOP_AFTER_EMPTY = 596, 3316484, 16000, 256
HOME_ENTRIES, HOME_SLOTS, AWAY_ENTRIES, AWAY_SLOTS, ENTRY = 32, 17, 304, 18, 16
PLAYED, SECOND_LEG, SINGLE_MATCH = 64, 16, 32
REGION_HINT, REGION_STRIDE, REGION_MAX, REGION_STOP_AFTER_INVALID = 13321016, 6268, 512, 48
TABLE_CURRENT, TABLE_PREVIOUS, TABLE_SLOTS = -1924, -960, 48
GOALS, GOALS_COUNT, ASSISTS, ASSISTS_COUNT, RANKING_SLOTS = 60, 860, 872, 1672, 40
AWARDS_STATE, PARTICIPANTS_HEADER, PARTICIPANTS, PARTICIPANT_SLOTS = 1688, -2716, -2696, 48
STAGE_LEAGUE_MAX = 45


@dataclass
class ClubRecord:
    offset: int
    team_id: int
    name: str
    short_name: str
    stadium: str


@dataclass
class Appearance:
    career_index: int
    player_id: int
    minutes: int
    rating_tenths: int
    started: bool
    goals: int
    assists: int
    yellow: bool
    second_yellow: bool
    red: bool
    position_code: int


@dataclass
class Fixture:
    offset: int
    row_id: int
    tournament_id: int
    stage: int
    year: int
    month: int
    day: int
    kickoff_hour: int
    flags: int
    home_team: int
    away_team: int
    home_goals: int
    away_goals: int
    home_extra_time: int
    away_extra_time: int
    home_shootout: int
    away_shootout: int
    home: list = field(default_factory=list)
    away: list = field(default_factory=list)

    @property
    def played(self):
        return bool(self.flags & PLAYED)

    @property
    def second_leg(self):
        return bool(self.flags & SECOND_LEG)

    @property
    def two_legged(self):
        return not self.flags & SINGLE_MATCH

    @property
    def date(self):
        return dt.date(self.year, self.month, self.day)

    @property
    def undecided(self):
        return UNDECIDED in (self.home_team, self.away_team)

    @property
    def home_total(self):
        return self.home_goals + self.home_extra_time

    @property
    def away_total(self):
        return self.away_goals + self.away_extra_time

    @property
    def went_to_shootout(self):
        return self.played and self.home_shootout + self.away_shootout > 0


@dataclass
class TableRow:
    position: int
    team_id: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int


@dataclass
class RankingRow:
    rank: int
    value: int
    player_id: int
    career_index: int
    team_id: int


@dataclass
class Region:
    index: int
    header_offset: int
    tournament_id: int
    team_count: int
    last_matchday: int
    season_start_year: int
    season_end_year: int
    table: list
    previous_table: list
    goal_ranking: list
    assist_ranking: list
    participants: list


@dataclass
class Tie:
    tournament_id: int
    stage: int
    teams: tuple
    legs: list
    complete: bool
    aggregate: tuple
    shootout: tuple
    winner: int


def _cstring(data, offset, length):
    try:
        return bytes(data[offset:offset + length]).split(b'\0', 1)[0].decode('utf-8')
    except UnicodeDecodeError:
        return ''


def _plausible_name(name):
    return len(name) >= 3 and any(ch.isalpha() for ch in name) and all(ch.isprintable() for ch in name)


# ------------------------------------------------------------------------------- clubs
def clubs(data, start=TEAM_TABLE_START):
    out, offset, invalid = {}, start, 0
    for _ in range(TEAM_TABLE_MAX):
        if offset + TEAM_RECORD_SIZE > len(data):
            break
        team = struct.unpack_from('<I', data, offset)[0] >> PACK
        name = _cstring(data, offset + 4, 64)
        if 1 <= team < UNDECIDED and _plausible_name(name):
            invalid = 0
            if team not in out:
                out[team] = ClubRecord(offset, team, name, _cstring(data, offset + 74, 4), _cstring(data, offset + 80, 64))
        else:
            invalid += 1
            if invalid >= TEAM_STOP_AFTER_INVALID and out:
                break
        offset += TEAM_RECORD_SIZE
    return out


# ---------------------------------------------------------------------------- fixtures
def _valid_row(data, offset):
    if offset < 0 or offset + FIXTURE_ROW > len(data):
        return False
    tid = struct.unpack_from('<H', data, offset)[0]
    year, month, day = struct.unpack_from('<HBB', data, offset + 4)
    if tid in (0, 65535) or not 2000 <= year <= 2199 or not 1 <= month <= 12 or not 1 <= day <= 31:
        return False
    try:
        dt.date(year, month, day)
    except ValueError:
        return False
    return True


def locate_fixture_table(data, hint=FIXTURE_HINT):
    if all(_valid_row(data, hint + k * FIXTURE_ROW) for k in range(8)):
        return hint
    for start in range(0, len(data) - 8 * FIXTURE_ROW, 4):
        if all(_valid_row(data, start + k * FIXTURE_ROW) for k in range(8)):
            return start
    return None


def _appearance(data, offset):
    cidx, pid, events, packed = struct.unpack_from('<IIII', data, offset)
    if pid == 0 or (cidx == 65535 and pid == 0):
        return None
    return Appearance(cidx, pid, packed & 127, (packed >> 7) & 127, bool(packed & 0x200000),
                      events & 255, (events >> 8) & 255, bool(packed & 0x80000), bool(packed & 0x40000),
                      bool(packed & 0x100000), ((packed >> 14) & 3) | (((packed >> 16) & 3) << 2))


def decode_fixture(data, offset, with_entries=True):
    tid, stage, flags = struct.unpack_from('<HBB', data, offset)
    year, month, day = struct.unpack_from('<HBB', data, offset + 4)
    _unknown, kickoff = struct.unpack_from('<II', data, offset + 8)
    home_word, away_word = struct.unpack_from('<II', data, offset + 16)
    g = data[offset + 24:offset + 30]
    f = Fixture(offset, struct.unpack_from('<I', data, offset + 592)[0], tid, stage, year, month, day,
                kickoff if kickoff <= 23 else None, flags, home_word >> PACK, away_word >> PACK,
                g[0], g[3], g[1], g[4], g[2], g[5])
    if with_entries and flags & PLAYED:
        for slot in range(HOME_SLOTS):
            a = _appearance(data, offset + HOME_ENTRIES + slot * ENTRY)
            if a:
                f.home.append(a)
        for slot in range(AWAY_SLOTS):
            a = _appearance(data, offset + AWAY_ENTRIES + slot * ENTRY)
            if a:
                f.away.append(a)
    return f


def fixtures(data, with_entries=True):
    start = locate_fixture_table(data)
    if start is None:
        return []
    rows, empty = [], 0
    for index in range(FIXTURE_MAX_ROWS):
        offset = start + index * FIXTURE_ROW
        if offset + FIXTURE_ROW > len(data):
            break
        if _valid_row(data, offset):
            empty = 0
            rows.append(decode_fixture(data, offset, with_entries))
        else:
            empty += 1
            if empty >= FIXTURE_STOP_AFTER_EMPTY:
                break
    return rows


# ----------------------------------------------------------------------------- regions
def _valid_region(data, header):
    if header - 2716 < 0 or header + 3552 > len(data):
        return False
    teams, tid, _last, flag = struct.unpack_from('<4I', data, header)
    if flag != 1 or tid in (0, 65535) or tid > 20000 or teams > TABLE_SLOTS:
        return False
    gc, gcap = struct.unpack_from('<II', data, header + GOALS_COUNT)
    ac, acap = struct.unpack_from('<II', data, header + ASSISTS_COUNT)
    if gcap != RANKING_SLOTS or acap != RANKING_SLOTS or gc > RANKING_SLOTS or ac > RANKING_SLOTS:
        return False
    return struct.unpack_from('<I', data, header + AWARDS_STATE)[0] in (1, 14)


def _first_region(data, hint=REGION_HINT):
    if _valid_region(data, hint):
        return hint
    for header in range(2716, len(data) - REGION_STRIDE, 4):
        if _valid_region(data, header) and _valid_region(data, header + REGION_STRIDE):
            return header
    return None


def _table_row(data, offset):
    packed, rank, a, b, _c = struct.unpack_from('<5I', data, offset)
    team = packed >> PACK
    if rank == 0 or rank > TABLE_SLOTS or not 1 <= team < UNDECIDED:
        return None
    return TableRow(rank, team, (b >> 24) & 255, (a >> 8) & 63, (a >> 20) & 63, (a >> 14) & 63,
                    b & 4095, (b >> 12) & 4095, a & 255)


def _table(data, base):
    rows = []
    for slot in range(TABLE_SLOTS):
        row = _table_row(data, base + slot * 20)
        if row is None or row.position != slot + 1:
            break
        rows.append(row)
    return rows


def _ranking(data, base):
    rows = []
    for slot in range(RANKING_SLOTS):
        cidx, pid, packed, rank, value = struct.unpack_from('<5I', data, base + slot * 20)
        if pid in (0, 0xFFFFFFFF) or rank in (0, 0xFFFFFFFF):
            break
        rows.append(RankingRow(rank, value, pid, cidx, packed >> PACK))
    return rows


def regions(data):
    first = _first_region(data)
    if first is None:
        return []
    out, invalid = [], 0
    for index in range(REGION_MAX):
        header = first + index * REGION_STRIDE
        if header + 3552 > len(data):
            break
        if not _valid_region(data, header):
            invalid += 1
            if invalid >= REGION_STOP_AFTER_INVALID:
                break
            continue
        invalid = 0
        teams, tid, last_md, _flag = struct.unpack_from('<4I', data, header)
        year_word, _t2, _k, _f, end_word = struct.unpack_from('<5I', data, header + PARTICIPANTS_HEADER)
        end_year = end_word & 0xFFFF
        participants = []
        for slot in range(PARTICIPANT_SLOTS):
            team = struct.unpack_from('<I', data, header + PARTICIPANTS + slot * 16)[0] >> PACK
            if 1 <= team < UNDECIDED:
                participants.append(team)
        out.append(Region(index, header, tid, teams, last_md, year_word >> 16,
                          None if end_year in (0xFFFF, 0) else end_year,
                          _table(data, header + TABLE_CURRENT), _table(data, header + TABLE_PREVIOUS),
                          _ranking(data, header + GOALS), _ranking(data, header + ASSISTS), participants))
    return out


# ------------------------------------------------------------------------------ ties
def knockout_ties(all_fixtures, tournament_id):
    groups = {}
    for f in all_fixtures:
        if f.tournament_id != tournament_id or f.stage <= STAGE_LEAGUE_MAX or f.undecided:
            continue
        a, b = sorted((f.home_team, f.away_team))
        groups.setdefault((f.stage, a, b), []).append(f)
    ties = []
    for (stage, a, b), legs in sorted(groups.items()):
        legs.sort(key=lambda f: (f.second_leg, f.date))
        complete = all(leg.played for leg in legs) and (len(legs) == 2 or not legs[0].two_legged)
        aggregate = shootout = winner = None
        if complete:
            goals = {a: 0, b: 0}
            for leg in legs:
                goals[leg.home_team] += leg.home_total
                goals[leg.away_team] += leg.away_total
            aggregate = (goals[a], goals[b])
            decider = legs[-1]
            if goals[a] != goals[b]:
                winner = a if goals[a] > goals[b] else b
            elif decider.went_to_shootout:
                shootout = (decider.home_shootout, decider.away_shootout)
                winner = decider.home_team if decider.home_shootout > decider.away_shootout else decider.away_team
        ties.append(Tie(tournament_id, stage, (a, b), legs, complete, aggregate, shootout, winner))
    return ties

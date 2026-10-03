"""Paths. Everything is located relative to SiderAddons, so the app keeps working if FL26 moves."""
import glob
import json
import os
import re

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIDER_DIR = os.path.dirname(APP_DIR)
GAME_DIR = os.path.dirname(SIDER_DIR)
GAME_EXE = os.path.join(GAME_DIR, 'FL_2026.exe')
DATA_DIR = os.path.join(APP_DIR, 'data')
WEB_DIR = os.path.join(APP_DIR, 'web')
FACE_CACHE = os.path.join(DATA_DIR, 'faces')
BADGE_CACHE = os.path.join(DATA_DIR, 'badges')
CAREERS_DIR = os.path.join(DATA_DIR, 'careers')
SETTINGS = os.path.join(DATA_DIR, 'settings.json')

LIVECPK = os.path.join(SIDER_DIR, 'livecpk')
PACKAGE_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
COMPETITIONS_JSON = os.path.join(PACKAGE_DATA, 'competitions.json')
NATIONALITIES_JSON = os.path.join(PACKAGE_DATA, 'nationalities.json')
KONAMI_DIR = os.path.join(os.path.expanduser('~'), 'Documents', 'KONAMI', 'eFootball PES 2021 SEASON UPDATE')

for d in (DATA_DIR, FACE_CACHE, BADGE_CACHE, CAREERS_DIR):
    os.makedirs(d, exist_ok=True)


def settings():
    try:
        return json.load(open(SETTINGS, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def backup_dir():
    """Backups live outside the game and app folders (default: 'FL26 Dugout Backup' next to the
    FL26 folder), so reinstalling either keeps them. settings.json "backup_dir" overrides it."""
    return settings().get('backup_dir') or os.path.join(os.path.dirname(GAME_DIR), 'FL26 Dugout Backup')


def cpk_roots():
    """livecpk roots in Sider priority order (first listed wins)."""
    roots = []
    ini = os.path.join(SIDER_DIR, 'sider.ini')
    if os.path.exists(ini):
        for line in open(ini, encoding='utf-8', errors='replace'):
            m = re.match(r'\s*cpk\.root\s*=\s*"?([^"\r\n]+)"?', line)
            if m:
                path = m.group(1).strip()
                if path.startswith('.'):
                    path = os.path.normpath(os.path.join(SIDER_DIR, path))
                roots.append(path)
    return roots


def effective_file(relative):
    """The copy of a game file the game actually loads (first livecpk root that has it)."""
    for root in cpk_roots():
        p = os.path.join(root, relative)
        if os.path.exists(p):
            return p
    fallback = os.path.join(LIVECPK, 'UML_Database', relative)
    return fallback if os.path.exists(fallback) else None


def miniface_path(player_id):
    rel = os.path.join('common', 'render', 'symbol', 'player', f'{player_id}.dds')
    for root in cpk_roots():
        p = os.path.join(root, rel)
        if os.path.exists(p):
            return p
    return None


_BADGES = {}


def badge_path(team_id):
    """Club crest: the game's emblem PNG from the livecpk logo packs, else Dugout's own copy."""
    if team_id in _BADGES:
        return _BADGES[team_id]
    found = None
    rel = os.path.join('common', 'render', 'symbol', 'flag', f'e_{team_id:06d}_r.png')
    for root in cpk_roots():
        p = os.path.join(root, rel)
        if os.path.exists(p):
            found = p
            break
    if not found:
        p = os.path.join(BADGE_CACHE, f'{team_id}.png')
        found = p if os.path.exists(p) else None
    _BADGES[team_id] = found
    return found


def all_saves():
    return sorted(glob.glob(os.path.join(KONAMI_DIR, '*', 'save', 'ML0000000*')))


def active_save():
    """The Master League save the game wrote last (the career being played)."""
    saves = all_saves()
    return max(saves, key=os.path.getmtime) if saves else None


def career_key(save_path):
    """One folder per save slot of one game-data version: '<KONAMI sub-folder>_<slot>'."""
    slot = os.path.basename(save_path)
    folder = os.path.basename(os.path.dirname(os.path.dirname(save_path)))
    return f'{folder}_{slot}'


def competition_names():
    """Tournament id -> name as FL26 shows it (Dugout's table, dugout/data/competitions.json)."""
    try:
        return {int(k): str(v) for k, v in json.load(open(COMPETITIONS_JSON, encoding='utf-8')).items()}
    except (OSError, ValueError):
        return {}


def nationality_names():
    """Nationality id -> name (dugout/data/nationalities.json)."""
    try:
        return {int(k): str(v) for k, v in json.load(open(NATIONALITIES_JSON, encoding='utf-8')).items()}
    except (OSError, ValueError):
        return {}

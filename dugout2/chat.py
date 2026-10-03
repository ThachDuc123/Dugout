"""Conversations. Every inbox message comes from someone at the club (assistant manager, club
doctor, fitness coach, scout, sporting director, board, data analyst) or from the player himself,
and most can be answered. An answer gets a reply, and some answers become tasks that the next
saves check (did the promised player start? has the skill been learned? was the suggested XI used?).

Only what the save shows is reported: results, conditions, minutes, skills, contracts, the Game
Plan. Replies are the manager's side of the story; nothing is written to the game."""
import datetime as dt

import numpy as np

from . import matchday, pesdb, terms

PERSONAS = {
    'assistant': {'name': 'Trợ lý HLV', 'icon': '🧢', 'role': 'Kết quả, đội hình, chiến thuật'},
    'fitness': {'name': 'HLV thể lực', 'icon': '💪', 'role': 'Phong độ, thể lực, tập luyện'},
    'medical': {'name': 'Bác sĩ trưởng', 'icon': '🩺', 'role': 'Chấn thương'},
    'analyst': {'name': 'Phân tích dữ liệu', 'icon': '🤖', 'role': 'AI dự đoán'},
    'scout': {'name': 'Tuyển trạch viên', 'icon': '🔭', 'role': 'Regen, tài năng trẻ'},
    'director': {'name': 'Giám đốc thể thao', 'icon': '💼', 'role': 'Chuyển nhượng, hợp đồng'},
    'academy': {'name': 'Giám đốc học viện', 'icon': '🌱', 'role': 'Đội trẻ'},
    'board': {'name': 'Ban lãnh đạo', 'icon': '🏛', 'role': 'Đánh giá kết quả'},
}
KIND_FROM = {'result': 'assistant', 'growth': 'fitness', 'position': 'assistant', 'ai': 'analyst', 'advice': 'assistant',
             'transfer': 'director', 'offer': 'director', 'contract': 'director', 'injury': 'medical', 'youth': 'academy',
             'regen': 'scout', 'welcome': 'analyst', 'preview': 'assistant', 'form': 'fitness', 'review': 'analyst',
             'board': 'board', 'skill': 'assistant', 'style': 'assistant', 'retire': 'assistant'}
ARROW_VI = {4: 'A · rất tốt', 3: 'B · tốt', 2: 'C · bình thường', 1: 'D · kém', 0: 'E · rất kém'}

# (kind, answer) -> (answer shown, reply, task, action). {first} = the player's first name.
ANSWERS = {
    'result': {
        'W': [('good', 'Tốt lắm, tiếp tục như vậy', 'Rõ. Tôi sẽ theo dõi phong độ và thể lực của mọi người trước trận tới.'),
              ('next', 'Chuẩn bị trận tới thôi', 'Báo cáo đối thủ, đội hình và chiến thuật đề xuất đã sẵn sàng ở mục Trận tới.', None, 'match')],
        'D': [('good', 'Một điểm cũng tốt', 'Rõ. Tôi sẽ xem lại những tình huống chưa tận dụng được.'),
              ('next', 'Chuẩn bị trận tới thôi', 'Báo cáo đối thủ, đội hình và chiến thuật đề xuất đã sẵn sàng ở mục Trận tới.', None, 'match')],
        'L': [('fix', 'Chúng ta phải thay đổi', 'Tôi đã xem lại trận đấu. Đội hình và chiến thuật đề xuất cho trận tới nằm ở mục Trận tới.', None, 'match'),
              ('calm', 'Không sao, còn nhiều trận', 'Đúng vậy. Tôi sẽ nói chuyện với các cầu thủ để giữ tinh thần.')],
    },
    'preview': [('use', 'Dùng đội hình đề xuất', 'Tốt. Anh đổi trong màn hình Chiến thuật của game trước trận rồi lưu game, tôi sẽ kiểm tra lại.', 'use_xi'),
                ('own', 'Tôi giữ đội hình của mình', 'Rõ. Nếu có ai sa sút phong độ trước trận, tôi sẽ báo.'),
                ('open', 'Xem phân tích chi tiết', 'Mời anh xem ở mục Trận tới.', None, 'match')],
    'form': [('ok', 'Cảm ơn, tôi sẽ cân nhắc', 'Rõ. Mũi tên phong độ được game làm mới trước mỗi trận, tôi sẽ báo lại khi có thay đổi.'),
             ('rest', 'Cho người phong độ thấp nghỉ', 'Được. Đội hình đề xuất ở mục Trận tới đã tính cả phong độ và thể lực.', None, 'match')],
    'playtime': [('promise', 'Cậu sẽ đá chính trận tới', 'Cảm ơn thầy! Em sẽ không làm thầy thất vọng.', 'start_next'),
                 ('work', 'Hãy chứng minh trên sân tập', 'Vâng, em hiểu. Em sẽ cố gắng hơn nữa.'),
                 ('loan', 'Tôi sẽ tìm nơi cho cậu mượn', 'Em hiểu. Được ra sân thường xuyên là điều em cần lúc này.')],
    'skill': [('praise', 'Làm tốt lắm!', 'Em cảm ơn thầy! Em sẽ dùng nó ngay khi có cơ hội.'),
              ('use', 'Dùng nó thật hiệu quả nhé', 'Vâng ạ, em sẽ không lạm dụng đâu.')],
    'style': [('ok', 'Phong cách mới hợp với cậu', 'Em sẽ thích nghi thật nhanh ạ.')],
    'retire': [('thanks', 'Cảm ơn những gì cậu đã cống hiến', 'Cảm ơn thầy. Được chơi dưới sự dẫn dắt của thầy là niềm vinh dự.'),
               ('stay', 'Hãy cân nhắc thêm', 'Em đã suy nghĩ kỹ rồi thầy ạ. Em muốn kết thúc khi còn đứng vững.')],
    'advice': [('do', 'Tôi sẽ làm trong game', 'Tốt. Khi save cho thấy thay đổi, tôi sẽ báo lại anh.', 'watch'),
               ('later', 'Để sau', 'Được, tôi sẽ nhắc lại khi có thay đổi.'),
               ('open', 'Xem chi tiết', 'Chi tiết và cách làm nằm trong tab Phát triển của cầu thủ.', None, 'dev')],
    'injury': [('ok', 'Cứ để cậu ấy hồi phục hoàn toàn', 'Chúng tôi sẽ theo dõi sát và báo khi cậu ấy sẵn sàng.'),
               ('asap', 'Tôi cần cậu ấy trở lại sớm', 'Tôi hiểu, nhưng vội vàng dễ tái phát. Tôi sẽ báo ngay khi cậu ấy tập lại được.')],
    'growth': [('ok', 'Tốt, tiếp tục giáo án', 'Rõ. Báo cáo tiếp theo sẽ có sau lần lưu game tới.')],
    'position': [('ok', 'Tốt', 'Tôi đã tính vị trí mới vào đội hình đề xuất.')],
    'ai': [('ok', 'Ghi nhận', 'AI sẽ tiếp tục học sau mỗi lần anh lưu game.'),
           ('why', 'Vì sao lại thay đổi?', 'AI so chỉ số hiện tại với dự đoán từ các lần lưu trước. Lên nhanh hơn cầu thủ cùng tuổi thì ngưỡng được nâng, chậm hơn thì hạ. Biểu đồ trong trang cầu thủ cho thấy rõ.', None, 'player')],
    'transfer': [('ok', 'Cảm ơn, tôi nắm rồi', 'Tôi sẽ cập nhật khi có diễn biến mới.')],
    'offer': [('ok', 'Tôi sẽ cân nhắc', 'Rõ. Anh trả lời lời đề nghị trong mục chuyển nhượng của game.')],
    'contract': [('renew', 'Ưu tiên gia hạn người quan trọng', 'Rõ. Anh xử lý gia hạn trong mục hợp đồng của game trước khi hết mùa.'),
                 ('let', 'Để họ ra đi', 'Được. Họ sẽ rời CLB theo dạng tự do khi hợp đồng kết thúc.')],
    'regen': [('watch', 'Theo dõi giúp tôi', 'Tôi sẽ báo khi có regen tiềm năng cao mới.'),
              ('open', 'Xem danh sách', 'Danh sách ở mục Đội trẻ & Regen.', None, 'youth')],
    'youth': [('ok', 'Tốt, theo dõi cậu ấy', 'Tôi sẽ báo khi cậu ấy sẵn sàng lên đội một.')],
    'review': [('ok', 'Ghi nhận', 'AI sẽ tiếp tục học từ mỗi trận.')],
    'board': [('improve', 'Chúng tôi sẽ làm tốt hơn', 'Ban lãnh đạo tin tưởng anh. Chúng tôi sẽ theo dõi tháng tới.'),
              ('confident', 'Đội đang đi đúng hướng', 'Chúng tôi hy vọng kết quả sẽ chứng minh điều đó.')],
}


def _answers(ev):
    a = ANSWERS.get(ev.get('kind'))
    if isinstance(a, dict):
        a = a.get(ev.get('outcome') or 'W')
    return a or []


def first_name(name):
    parts = (name or '').split()
    return parts[0] if parts else ''


def decorate(ev, snap=None):
    """Sender and answers of a message (older messages were stored without them)."""
    if ev.get('from') is None:
        ev['from'] = KIND_FROM.get(ev.get('kind'), 'assistant')
    if ev['from'].startswith('player:') and not ev.get('from_name') and snap is not None:
        ev['from_name'] = snap.player_name(int(ev['from'].split(':')[1]))
    if 'choices' not in ev:
        ev['choices'] = [{'id': a[0], 'label': a[1]} for a in _answers(ev)] if ev.get('kind') not in ('followup', 'welcome') else []
    return ev


def reply(career, snap, ev_id, choice):
    """The manager answers a message: store the answer, add the reply, set a task if any."""
    with career.lock:
        ev = next((e for e in career.events if e.get('id') == ev_id), None)
        if ev is None or ev.get('reply'):
            return None
        decorate(ev, snap)
        ans = next((a for a in _answers(ev) if a[0] == choice), None)
        if ans is None:
            return None
        text, task, action = ans[2], ans[3] if len(ans) > 3 else None, ans[4] if len(ans) > 4 else None
        today = snap.date.isoformat() if snap is not None else dt.date.today().isoformat()
        ev.update(reply=choice, reply_text=ans[1], replied=today, read=True)
        pid = (ev.get('players') or [None])[0]
        fu = {'date': today, 'kind': 'followup', 'from': ev['from'], 'from_name': ev.get('from_name'),
              'title': text[:70], 'body': text, 'read': True, 'reply_to': ev_id, 'players': ev.get('players', [])[:1]}
        career.add_event(fu)
        if task == 'use_xi' and ev.get('xi'):
            career.tasks.append({'type': 'use_xi', 'date': today, 'xi': ev['xi'], 'fixture': ev.get('fixture'),
                                 'opp': ev.get('opp_name', ''), 'pred': ev.get('pred')})
        elif task == 'start_next' and pid:
            career.tasks.append({'type': 'start_next', 'date': today, 'pid': pid, 'from': ev['from'], 'from_name': ev.get('from_name')})
        elif task == 'watch' and pid:
            for kind, idx, before in ev.get('advice_struct') or []:
                career.tasks.append({'type': 'watch_' + kind, 'date': today, 'pid': pid, 'idx': idx, 'before': before})
        career.save()
        if action == 'dev' and pid:
            action = f'player:{pid}:dev'
        elif action == 'player' and pid:
            action = f'player:{pid}:overview'
        return {'event': fu, 'action': action}


# ---------------------------------------------------------------------------- follow-ups
def check_tasks(snap, career, played_new):
    """Tasks set by earlier answers, checked against this save."""
    out = []
    today = snap.date
    for t in career.tasks:
        if t.get('done'):
            continue
        made = dt.date.fromisoformat(t['date'])
        if (today - made).days > 150:
            t['done'] = 'expired'
            continue
        after = [m for m in played_new if m['date'] >= t['date']]
        if t['type'] == 'start_next' and after:
            m = after[0]
            side = m['home_players'] if m['venue'] == 'home' else m['away_players']
            me = next((p for p in side if p['id'] == t['pid']), None)
            opp = m['away_name'] if m['venue'] == 'home' else m['home_name']
            name = snap.player_name(t['pid'])
            if me and me['start']:
                body = f'Cảm ơn thầy đã giữ lời! Em đá chính trận gặp {opp}' + (f' và được {me.get("r10") or me["rating"]} điểm' if me.get('rating') else '') + \
                       (f', ghi {me["g"]} bàn' if me.get('g') else '') + '.'
            else:
                body = f'Thầy đã hứa cho em đá chính trận gặp {opp}, nhưng em ' + ('chỉ vào sân từ ghế dự bị.' if me and me['min'] else 'không được ra sân.') + \
                       ' Em mong thầy nhớ đến em ở trận tới.'
            out.append({'date': today.isoformat(), 'kind': 'followup', 'from': f'player:{t["pid"]}', 'from_name': name,
                        'title': body[:70], 'body': body, 'players': [t['pid']]})
            t['done'] = today.isoformat()
        elif t['type'] == 'use_xi':
            m = next((m for m in after if m['key'] == t.get('fixture')), None) or (after[0] if after else None)
            if not m:
                continue
            side = m['home_players'] if m['venue'] == 'home' else m['away_players']
            starters = {p['id'] for p in side if p['start']}
            n = len(starters & set(t['xi']))
            word = {'W': 'thắng', 'D': 'hòa', 'L': 'thua'}[m['outcome']]
            body = f'Trận gặp {t.get("opp") or "đối thủ"}: anh dùng {n}/11 cầu thủ trong đội hình đề xuất. Kết quả {m["hg"]}–{m["ag"]}, chúng ta {word}.'
            if t.get('pred'):
                body += f' Trước trận AI dự đoán thắng {t["pred"]["w"]}% · hòa {t["pred"]["d"]}% · thua {t["pred"]["l"]}%.'
            out.append({'date': today.isoformat(), 'kind': 'followup', 'from': 'assistant', 'title': body[:70], 'body': body})
            t['done'] = today.isoformat()
        elif t['type'].startswith('watch_'):
            i = snap.row.get(t['pid'])
            if i is None:
                continue
            name = snap.names[i]
            done = None
            if t['type'] == 'watch_skill' and int(snap.skills[i]) >> t['idx'] & 1:
                done = f'Việc anh giao đã xong: {name} đã học được kỹ năng {terms.skill_label(t["idx"])}.'
            elif t['type'] == 'watch_style' and int(snap.style[i]) == t['idx']:
                done = f'Việc anh giao đã xong: {name} đã chuyển sang phong cách {terms.style_label(t["idx"])}.'
            elif t['type'] == 'watch_position' and int(snap.grades[i, t['idx']]) > (t.get('before') or 0):
                done = f'Việc anh giao đã có kết quả: {name} lên hạng {"CBA"[min(int(snap.grades[i, t["idx"]]), 2)]} ở vị trí {terms.POSITIONS[t["idx"]]}.'
            if done:
                out.append({'date': today.isoformat(), 'kind': 'followup', 'from': 'assistant', 'title': done[:70], 'body': done,
                            'players': [t['pid']]})
                t['done'] = today.isoformat()
    career.tasks = [t for t in career.tasks if not t.get('done') or t['done'] >= (today - dt.timedelta(days=200)).isoformat()]
    return out


# ------------------------------------------------------------------------------ messages
def _days(n):
    return 'hôm nay' if n <= 0 else 'ngày mai' if n == 1 else f'còn {n} ngày'


def preview_message(snap, md, fx):
    p, pc = fx['pred'], fx.get('pred_current')
    d = dt.date.fromisoformat(fx['date'])
    xg = f'{p["xg"][0]:.1f}–{p["xg"][1]:.1f}'.replace('.', ',')
    lines = [f'Trận tới: {fx["home_name"]} – {fx["away_name"]} · {fx["comp_name"]} · {d.day}/{d.month}/{d.year} ({_days(fx["days"])}).',
             f'AI dự đoán với đội hình đề xuất: thắng {p["w"]}% · hòa {p["d"]}% · thua {p["l"]}% (bàn thắng kỳ vọng của bạn–đối thủ {xg}).']
    if pc:
        lines.append(f'Với đội hình Game Plan hiện tại của anh: thắng {pc["w"]}% · hòa {pc["d"]}% · thua {pc["l"]}%.')
    if fx.get('derby'):
        lines.insert(0, '🔥 Đây là trận DERBY.')
    form = ''.join(r['outcome'] for r in fx.get('opp_results', [])[-5:]).replace('W', 'T').replace('D', 'H').replace('L', 'B')
    lines.append(f'Đối thủ: HLV {fx.get("opp_manager") or "?"}, sơ đồ {fx.get("opp_shape") or "?"}' + (f', 5 trận gần nhất {form}' if form else '') + '.')
    ph = {p['key']: p['shape'] for p in ((fx.get('opp_phases') or {}).get('phases') or [])}
    if ph.get('attack') and ph.get('defence') and (ph['attack'] != ph.get('kickoff') or ph['defence'] != ph.get('kickoff')):
        lines.append(f'Họ đổi hình khi có bóng thành {ph["attack"]}, khi mất bóng thành {ph["defence"]}.')
    swaps = [c for c in md['changes'] if c['type'] == 'swap']
    moves = [c for c in md['changes'] if c['type'] == 'move']
    if swaps or moves:
        lines.append('Thay đổi so với Game Plan của anh:')
        lines += [f'• {c["in_name"]} vào thay {c["out_name"]} ({c["role"]}): {c["why"]}.' for c in swaps[:5]]
        lines += [f'• {c["name"]} chuyển {c["from"]} → {c["role"]}.' for c in moves[:3]]
    else:
        lines.append('Đội hình Game Plan hiện tại của anh đã là phương án tốt nhất.')
    tac = [r for r in fx['tactics']['rows'] if r['change']]
    if tac:
        lines.append('Chiến thuật nên chỉnh: ' + '; '.join(f'{r["label"]}: {r["now"]} → {r["rec"]}' for r in tac[:3]) + '.')
    sp = [r for r in md.get('set_pieces') or [] if r['change']]
    if sp:
        lines.append('Người đá phạt nên đổi: ' + '; '.join(f'{r["label"]}: {r["cur"]["name"]} → {r["rec"]["name"]}' for r in sp[:4]) + '.')
    if fx.get('threats'):
        t = fx['threats'][0]
        lines.append(f'Cần chú ý nhất: {t["name"]} ({t.get("g", 0)} bàn, {t.get("a", 0)} kiến tạo mùa này, phong độ {t["arrow"] or "?"}).')
    return {'date': snap.date.isoformat(), 'kind': 'preview', 'from': 'assistant',
            'title': f'Chuẩn bị trận gặp {fx["opp_name"]}: AI dự đoán thắng {p["w"]}%',
            'body': '\n'.join(lines), 'fixture': fx['key'], 'opp_name': fx['opp_name'],
            'xi': [r['id'] for r in md['best']], 'pred': {k: p[k] for k in ('w', 'd', 'l')}, 'teams': [fx['home'], fx['away']]}


def form_message(snap, md, fx):
    rows = [r for r in md['form'] if not r['inj']]
    top = [r for r in rows if r['cond'] == 4]
    good = [r for r in rows if r['cond'] == 3]
    low = [r for r in rows if 0 <= r['cond'] <= 1]
    tired = [r for r in rows if r['stamina'] < 97]
    if not (top or low or tired):
        return None
    lines = [f'Phong độ trước trận gặp {fx["opp_name"]} (mũi tên trong game):']
    if top:
        lines.append('🔴 A · rất tốt: ' + ', '.join(r['name'] for r in top))
    if good:
        lines.append('🟠 B · tốt: ' + ', '.join(r['name'] for r in good))
    if low:
        lines.append('🔵 D/E · sa sút: ' + ', '.join(f'{r["name"]} ({r["arrow"]})' for r in low))
    if tired:
        lines.append('Thể lực chưa hồi phục hết: ' + ', '.join(f'{r["name"]} {r["stamina"]}%' for r in tired))
    in_plan_low = [r for r in low if r['plan'] == 'start']
    if in_plan_low:
        lines.append('Đang có tên trong đội hình chính của anh dù phong độ kém: ' + ', '.join(r['name'] for r in in_plan_low) + '.')
    return {'date': snap.date.isoformat(), 'kind': 'form', 'from': 'fitness',
            'title': f'Phong độ đội: {len(top)} cầu thủ A, {len(low)} cầu thủ sa sút', 'body': '\n'.join(lines),
            'players': [r['id'] for r in (top + low)][:12]}


def playtime_message(snap, md, season_matches, seen_pt):
    played = [m for m in season_matches if m['played']][-6:]
    if len(played) < 6:
        return None
    minutes, starts = {}, {}
    for m in played:
        side = m['home_players'] if m['venue'] == 'home' else m['away_players']
        for p in side:
            minutes[p['id']] = minutes.get(p['id'], 0) + (p['min'] or 0)
            starts[p['id']] = starts.get(p['id'], 0) + (1 if p['start'] else 0)
    rows = [r for r in md['form'] if not r['inj']]
    if not rows:
        return None
    med = float(np.median([r['ovr'] for r in rows]))
    cands = []
    for r in rows:
        i = snap.row.get(r['id'])
        if i is None or snap.age[i] < 18 or r['ovr'] < med - 4 or r['pos'] == 'GK':
            continue
        last = seen_pt.get(str(r['id']))
        if last and (snap.date - dt.date.fromisoformat(last)).days < 75:
            continue
        if starts.get(r['id'], 0) == 0 and minutes.get(r['id'], 0) <= 60:
            cands.append(r)
    if not cands:
        return None
    r = max(cands, key=lambda r: r['ovr'])
    mins = minutes.get(r['id'], 0)
    body = f'Thầy ơi, em đã không được đá chính 6 trận liền rồi' + (f', tổng cộng chỉ {mins} phút' if mins else '') + '. '
    body += ('Phong độ của em đang rất tốt, em nghĩ mình xứng đáng có cơ hội.' if r['cond'] >= 3 else
             'Em biết em cần thể hiện nhiều hơn, nhưng em cần được ra sân để lấy lại cảm giác.')
    seen_pt[str(r['id'])] = snap.date.isoformat()
    return {'date': snap.date.isoformat(), 'kind': 'playtime', 'from': f'player:{r["id"]}', 'from_name': r['name'],
            'title': f'{r["name"]} muốn được ra sân nhiều hơn', 'body': body, 'players': [r['id']]}


def board_message(snap, career, old_date, standing):
    if old_date is None or (old_date.year, old_date.month) == (snap.date.year, snap.date.month):
        return None
    y, mth = old_date.year, old_date.month
    ms = [m for m in career.matches.values() if m.get('played') and m['date'][:7] == f'{y:04d}-{mth:02d}']
    if len(ms) < 2:
        return None
    w = sum(1 for m in ms if m['outcome'] == 'W')
    d = sum(1 for m in ms if m['outcome'] == 'D')
    l = sum(1 for m in ms if m['outcome'] == 'L')
    gf = sum(m['hg'] if m['venue'] == 'home' else m['ag'] for m in ms)
    ga = sum(m['ag'] if m['venue'] == 'home' else m['hg'] for m in ms)
    ppg = (3 * w + d) / len(ms)
    tone = ('rất hài lòng với phong độ của đội' if ppg >= 2.2 else 'hài lòng với tháng vừa qua' if ppg >= 1.6 else
            'chưa hài lòng, chúng tôi mong đợi nhiều hơn' if ppg >= 1.0 else 'thất vọng với kết quả tháng này')
    lines = [f'Tổng kết tháng {mth}/{y}: {len(ms)} trận, {w} thắng · {d} hòa · {l} thua, ghi {gf} bàn, thủng lưới {ga}.']
    if standing:
        lines.append(f'Hiện đội đứng thứ {standing["pos"]}/{standing["of"]} ở {standing["comp"]} với {standing["pts"]} điểm.')
    lines.append(f'Ban lãnh đạo {tone}.')
    return {'date': snap.date.isoformat(), 'kind': 'board', 'from': 'board', 'title': f'Ban lãnh đạo đánh giá tháng {mth}/{y}',
            'body': '\n'.join(lines), 'outcome': 'W' if ppg >= 1.6 else 'L'}


def log_predictions(snap, career, md):
    """Keep the latest pre-match prediction of every upcoming fixture."""
    cond = {str(r['id']): r['cond'] for r in md['form'] if r['cond'] >= 0}
    for fx in md['fixtures']:
        if 'pred' not in fx:
            continue
        old = career.match_preds.get(fx['key'], {})
        if old.get('result'):
            continue
        career.match_preds[fx['key']] = {'date': fx['date'], 'made': snap.date.isoformat(), 'opp': fx['opp_name'],
                                         'venue': fx['venue'], 'comp': fx['comp_name'], 'pred': fx['pred'],
                                         'pred_current': fx.get('pred_current'), 'xi': [r['id'] for r in md['best']],
                                         'plan_xi': [r['id'] for r in md['current']], 'cond': cond}


def review_predictions(snap, career, played_new):
    out = []
    for m in played_new:
        rec = career.match_preds.get(m['key'])
        if not rec or rec.get('result'):
            continue
        p = rec['pred']
        k = {'W': 'w', 'D': 'd', 'L': 'l'}[m['outcome']]
        best = max(('w', 'd', 'l'), key=lambda x: p[x])
        side = m['home_players'] if m['venue'] == 'home' else m['away_players']
        rec.update(result=m['outcome'], score=[m['hg'], m['ag']], hit=best == k,
                   ratings={str(x['id']): x['rating'] for x in side if x.get('rating') and (x['min'] or 0) >= 45},
                   started=[x['id'] for x in side if x['start']])
        done = [r for r in career.match_preds.values() if r.get('result')]
        hits = sum(1 for r in done if r['hit'])
        word = {'W': 'Thắng', 'D': 'Hòa', 'L': 'Thua'}[m['outcome']]
        top = p.get('scores', [{}])[0].get('s')
        body = (f'Trước trận gặp {rec["opp"]}, AI dự đoán: thắng {p["w"]}% · hòa {p["d"]}% · thua {p["l"]}%'
                + (f', tỉ số khả năng nhất {top[0]}–{top[1]}' if top and rec['venue'] == 'home' else
                   f', tỉ số khả năng nhất {top[1]}–{top[0]}' if top else '') + '.\n'
                f'Kết quả: {m["home_name"]} {m["hg"]}–{m["ag"]} {m["away_name"]} ({word}). '
                f'{"✓ AI đoán đúng." if best == k else "✗ AI đoán sai."}\n'
                f'Tổng cộng AI đúng {hits}/{len(done)} trận đã theo dõi.')
        out.append({'date': snap.date.isoformat(), 'kind': 'review', 'from': 'analyst',
                    'title': f'Đối chiếu dự đoán: {m["home_name"]} {m["hg"]}–{m["ag"]} {m["away_name"]} {"✓" if best == k else "✗"}',
                    'body': body, 'match': m['key'], 'outcome': m['outcome']})
    return out


def prediction_summary(career):
    done = sorted((r for r in career.match_preds.values() if r.get('result')), key=lambda r: r['date'])
    rows = [{'date': r['date'], 'opp': r['opp'], 'venue': r['venue'], 'pred': r['pred'], 'result': r['result'],
             'score': r['score'], 'hit': r['hit']} for r in done[-30:]][::-1]
    by = {}
    for r in done:
        for pid, rating in (r.get('ratings') or {}).items():
            c = (r.get('cond') or {}).get(pid)
            if c is not None and rating:
                by.setdefault(c, []).append(rating)
    cond = [{'arrow': matchday.COND_LETTER[c], 'n': len(v), 'avg': round(float(np.mean(v)), 2)} for c, v in sorted(by.items(), reverse=True)]
    return {'n': len(done), 'hits': sum(1 for r in done if r['hit']), 'rows': rows, 'cond': cond}


def after_load(snap, career, md, old_seen, new_seen, played_new, first_run, season_matches, standing):
    """New conversations for this save and follow-ups of earlier answers."""
    for k in ('preview_for', 'form_for', 'playtime'):
        if k not in new_seen:
            new_seen[k] = (old_seen or {}).get(k)
    new_seen['playtime'] = dict(new_seen.get('playtime') or {})
    evs = []
    evs += review_predictions(snap, career, played_new)
    evs += check_tasks(snap, career, played_new)
    fx = next((f for f in md['fixtures'] if 'pred' in f), None)
    if fx and new_seen.get('preview_for') != fx['key']:
        evs.append(preview_message(snap, md, fx))
        new_seen['preview_for'] = fx['key']
    if fx and new_seen.get('form_for') != fx['key']:
        m = form_message(snap, md, fx)
        if m:
            evs.append(m)
        new_seen['form_for'] = fx['key']
    old_date = (old_seen or {}).get('date')
    if not first_run and old_date != snap.date.isoformat():      # once per new game day, not per app start
        m = playtime_message(snap, md, season_matches, new_seen['playtime'])
        if m:
            evs.append(m)
        m = board_message(snap, career, dt.date.fromisoformat(old_date) if old_date else None, standing)
        if m:
            evs.append(m)
    log_predictions(snap, career, md)
    for ev in evs:
        career.add_event(ev)
    return evs

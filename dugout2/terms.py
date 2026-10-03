"""Game enums and their names as the game's Vietnamese translation (VH21) writes them.

Skills and playing styles keep the English name the game shows, followed by the VH21
Vietnamese name in brackets, e.g. "Prolific Winger (Đột phá từ cánh)".
"""

POSITIONS = ['GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF', 'AMF', 'LWF', 'RWF', 'SS', 'CF']
POS_VI = {'GK': 'Thủ môn', 'CB': 'Trung vệ', 'LB': 'Hậu vệ trái', 'RB': 'Hậu vệ phải', 'DMF': 'Tiền vệ phòng ngự',
          'CMF': 'Tiền vệ trung tâm', 'LMF': 'Tiền vệ trái', 'RMF': 'Tiền vệ phải', 'AMF': 'Tiền vệ tấn công',
          'LWF': 'Tiền đạo cánh trái', 'RWF': 'Tiền đạo cánh phải', 'SS': 'Hộ công', 'CF': 'Tiền đạo cắm'}

ABILITIES = ['offensive_awareness', 'ball_control', 'dribbling', 'tight_possession', 'low_pass', 'lofted_pass',
             'finishing', 'heading', 'place_kicking', 'curl', 'speed', 'acceleration', 'kicking_power', 'jump',
             'physical_contact', 'balance', 'stamina', 'defensive_awareness', 'ball_winning', 'aggression',
             'gk_awareness', 'gk_catching', 'gk_clearing', 'gk_reflexes', 'gk_reach']
ABILITY_VI = {
    'offensive_awareness': 'Tư duy ATK', 'ball_control': 'Kiểm soát bóng', 'dribbling': 'Rê bóng',
    'tight_possession': 'Kiểm soát trong không gian hẹp', 'low_pass': 'Chuyền sệt', 'lofted_pass': 'Chuyền bổng',
    'finishing': 'Dứt điểm', 'heading': 'Đánh đầu', 'place_kicking': 'Đá phạt', 'curl': 'Độ xoáy',
    'speed': 'Tốc độ', 'acceleration': 'Bứt tốc', 'kicking_power': 'Lực sút', 'jump': 'Bật nhảy',
    'physical_contact': 'Tỳ đè', 'balance': 'Thăng bằng', 'stamina': 'Thể lực',
    'defensive_awareness': 'Tư duy DEF', 'ball_winning': 'Tranh bóng', 'aggression': 'Xông xáo',
    'gk_awareness': 'Tư duy TM', 'gk_catching': 'Bắt bóng TM', 'gk_clearing': 'Đẩy bóng TM',
    'gk_reflexes': 'Phản xạ TM', 'gk_reach': 'Tầm với TM'}

# Playing styles, in the database (Player.bin) enum order. 0 = none.
STYLES = [
    ('', ''),
    ('Goal Poacher', 'Phá bẫy việt vị'),
    ('Dummy Runner', 'Cầu thủ chim mồi'),
    ('Fox in the Box', 'Sát thủ vòng cấm'),
    ('Prolific Winger', 'Đột phá từ cánh'),
    ('Classic No. 10', 'Số 10 cổ điển'),
    ('Hole Player', 'Đột phá vòng cấm'),
    ('Box-to-Box', 'Tiền vệ con thoi'),
    ('Anchor Man', 'Tiền vệ mỏ neo'),
    ('The Destroyer', 'Không ngại va chạm'),
    ('Extra Frontman', 'Trung vệ tấn công'),
    ('Offensive Full-back', 'LB/RB dâng cao'),
    ('Defensive Full-back', 'Hậu vệ chuẩn mực'),
    ('Target Man', 'Tiền đạo làm tường'),
    ('Creative Playmaker', 'Nhạc trưởng'),
    ('Build Up', 'Phát động tấn công'),
    ('Offensive Goalkeeper', 'Thủ môn "quét"'),
    ('Defensive Goalkeeper', 'Thủ môn chuẩn mực'),
    ('Roaming Flank', 'Chuyên gia cắt mặt'),
    ('Cross Specialist', 'Chuyên gia tạt bóng'),
    ('Orchestrator', 'Lùi sâu phát động tấn công'),
    ('Full-back Finisher', 'Hậu vệ tham gia tấn công'),
]
# The save's career record numbers styles in the in-game menu order; map it to the database enum.
CAREER_STYLE_TO_DB = {0: 0, 1: 1, 2: 2, 3: 3, 4: 13, 5: 14, 6: 4, 7: 18, 8: 19, 9: 5, 10: 6, 11: 7, 12: 9, 13: 20,
                      14: 8, 15: 11, 16: 21, 17: 12, 18: 15, 19: 10, 20: 16, 21: 17}

# Player skills: (English as the game shows it, VH21 name, Player.bin bit, save career-record bit).
SKILLS = [
    ('Scissors Feint', 'Đảo chân rang lạc', 519, 127),
    ('Double Touch', 'Xử lý hai chạm', 523, 176),
    ('Flip Flap', 'Đổi hướng rê bóng bằng 1 chân', 485, 140),
    ('Marseille Turn', 'Phong cách rê bóng Marseille', 497, 141),
    ('Sombrero', 'Tâng bóng qua đầu', 482, 142),
    ('Cross Over Turn', 'Giật gót chéo chân', 287, 177),
    ('Cut Behind & Turn', 'Giả sút/chuyền rồi ngoặt bóng', 528, 143),
    ('Scotch Move', 'Giật bóng và đánh gót sang ngang', 525, 144),
    ('Step On Skill Control', 'Rê bóng cắt kéo đổi chân', 500, 171),
    ('Heading', 'Đánh đầu tốt', 495, 145),
    ('Long Range Drive', 'Sút xoáy từ xa', 527, 146),
    ('Chip Shot Control', 'Khả năng bấm bóng tốt', 506, 170),
    ('Long Range Shooting', 'Sút xa', 518, 178),
    ('Knuckle Shot', 'Cú sút lắc lư', 513, 147),
    ('Dipping Shot', 'Sút căng xoáy đập đất', 494, 172),
    ('Rising Shots', 'Sút căng tầm thấp lên cao', 499, 173),
    ('Acrobatic Finishing', 'Dứt điểm ở tư thế khó', 524, 148),
    ('Heel Trick', 'Xử lý bằng gót', 505, 149),
    ('First-time Shot', 'Sút một chạm', 511, 150),
    ('One-touch Pass', 'Chuyền một chạm', 507, 151),
    ('Through Passing', 'Chọc khe chuẩn', 487, 179),
    ('Weighted Pass', 'Chuyền có điểm rơi', 484, 152),
    ('Pinpoint Crossing', 'Chuyền vượt tuyến chuẩn xác', 483, 153),
    ('Outside Curler', 'Chuyền cuộn và xoáy từ xa', 493, 154),
    ('Rabona', 'Chuyền cắt kéo chân', 515, 155),
    ('No Look Pass', 'Chuyền không cần nhìn', 512, 167),
    ('Low Lofted Pass', 'Chuyền bổng quỹ đạo thấp', 488, 156),
    ('GK Low Punt', 'Phát bóng quỹ đạo thấp', 490, 157),
    ('GK High Punt', 'Phát bóng cao, xa, có điểm rơi', 496, 174),
    ('Long Throw', 'Ném biên mạnh', 521, 158),
    ('GK Long Throw', 'Thủ môn ném bóng mạnh', 522, 159),
    ('Penalty Specialist', 'Chuyên gia sút phạt đền', 501, 168),
    ('GK Penalty Saver', 'Cản phá phạt đền tốt', 502, 169),
    ('Malicia', 'Kịch sĩ', 491, 160),
    ('Man Marking', 'Kèm người chặt', 504, 161),
    ('Track Back', 'Theo người cướp bóng', 517, 162),
    ('Interception', 'Đánh chặn', 503, 175),
    ('Acrobatic Clear', 'Phá bóng ở tư thế khó', 530, 163),
    ('Captaincy', 'Tố chất đội trưởng', 492, 164),
    ('Super-sub', 'Siêu dự bị', 516, 165),
    ('Fighting Spirit', 'Tinh thần chiến đấu cao', 486, 166),
]
GK_SKILLS = {'GK Low Punt', 'GK High Punt', 'GK Long Throw', 'GK Penalty Saver'}
# Traits a player is born with rather than learns: never suggested as training targets.
NOT_TRAINABLE = {'Captaincy', 'Super-sub', 'Fighting Spirit', 'Malicia'}

# COM playing styles (Player.bin bits). They do not change during a career.
COM_STYLES = [
    ('Trickster', 'Chạy chỗ, di chuyển khôn ngoan', 489),
    ('Mazing Run', 'Chuyên gia rê bóng', 531),
    ('Speeding Bullet', 'Đứa con thần gió', 526),
    ('Incisive Run', 'Đột phá từ cánh', 510),
    ('Long Ball Expert', 'Chuyên gia chuyền dài', 529),
    ('Early Cross', 'Tạt bóng sớm', 447),
    ('Long Ranger', 'Chuyên gia sút xa', 520),
]

# Position grades stored in the save's career record (2 bits: 0 C, 1 B, 2 A). SS and CF sit in the
# 8 bytes before the record (see pes.career.GRADE_BITS).
CAREER_GRADE_BITS = {'GK': 132, 'CB': 125, 'LB': 128, 'RB': 130, 'DMF': 117, 'CMF': 119, 'LMF': 121,
                     'RMF': 123, 'AMF': 94, 'LWF': 30, 'RWF': 62}
CAREER_STYLE_BIT = 102

TEAM_ROLES = {
    '': '', 'Youth Prospect': 'Triển vọng trẻ', 'Protege': 'Học trò', 'Team Player': 'Cầu thủ đồng đội',
    'Playmaker': 'Kiến thiết', 'Star Player': 'Ngôi sao', 'Leader': 'Thủ lĩnh', 'General': 'Vị tướng',
    'Creator': 'Nhà sáng tạo', 'Maestro': 'Bậc thầy', 'Workhorse': 'Cỗ máy', 'Smart Player': 'Cầu thủ thông minh',
    'Fighter': 'Chiến binh', 'Key Player': 'Trụ cột', 'Superstar': 'Siêu sao', 'Hero': 'Người hùng',
    'Virtuoso': 'Nghệ sĩ', 'Conductor': 'Nhạc trưởng', 'Bandiera': 'Biểu tượng CLB', 'Legend': 'Huyền thoại',
    'Rising Star': 'Ngôi sao đang lên', 'Bad Boy': 'Trai hư', 'Risk-Taker': 'Kẻ liều lĩnh'}

STAGE_VI = {51: 'Tứ kết', 52: 'Bán kết', 53: 'Chung kết', 54: 'Tranh hạng ba'}


def style_label(idx):
    if not idx or idx >= len(STYLES):
        return ''
    en, vi = STYLES[idx]
    return f'{en} ({vi})'


def skill_label(k):
    en, vi = SKILLS[k][:2]
    return f'{en} ({vi})'


def com_label(k):
    en, vi = COM_STYLES[k][:2]
    return f'{en} ({vi})'

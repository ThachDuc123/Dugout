'use strict';
// Dugout on the phone: an app of its own, made for a phone in one hand: five big tabs at the bottom, lists
// and cards instead of the PC's wide tables, one thing per screen; a tap opens the details on the whole
// screen and the phone's back button closes them. The data is the PC's (the same /api, through the tunnel;
// sw.js keeps the last data for when the PC is off). Editing the save stays on the PC.

const POS = ['GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF', 'AMF', 'LWF', 'RWF', 'SS', 'CF'];
const POS_VI = {GK: 'Thủ môn', CB: 'Trung vệ', LB: 'Hậu vệ trái', RB: 'Hậu vệ phải', DMF: 'Tiền vệ phòng ngự',
  CMF: 'Tiền vệ trung tâm', LMF: 'Tiền vệ trái', RMF: 'Tiền vệ phải', AMF: 'Tiền vệ tấn công',
  LWF: 'Tiền đạo cánh trái', RWF: 'Tiền đạo cánh phải', SS: 'Hộ công', CF: 'Tiền đạo cắm'};
const SPOT = {CF: [50, 8], SS: [50, 20], LWF: [16, 14], RWF: [84, 14], AMF: [50, 31], LMF: [13, 42], RMF: [87, 42],
  CMF: [50, 45], DMF: [50, 59], LB: [14, 69], RB: [86, 69], CB: [50, 77], GK: [50, 92]};
const AB = {
  offensive_awareness: 'Tư duy ATK', ball_control: 'Kiểm soát bóng', dribbling: 'Rê bóng',
  tight_possession: 'Giữ bóng hẹp', low_pass: 'Chuyền sệt', lofted_pass: 'Chuyền bổng',
  finishing: 'Dứt điểm', heading: 'Đánh đầu', place_kicking: 'Đá phạt', curl: 'Độ xoáy',
  speed: 'Tốc độ', acceleration: 'Bứt tốc', kicking_power: 'Lực sút', jump: 'Bật nhảy',
  physical_contact: 'Tỳ đè', balance: 'Thăng bằng', stamina: 'Thể lực',
  defensive_awareness: 'Tư duy DEF', ball_winning: 'Tranh bóng', aggression: 'Xông xáo',
  gk_awareness: 'Tư duy TM', gk_catching: 'Bắt bóng TM', gk_clearing: 'Đẩy bóng TM', gk_reflexes: 'Phản xạ TM', gk_reach: 'Tầm với TM'};
const GROUPS = [
  ['Tấn công', ['offensive_awareness', 'ball_control', 'dribbling', 'tight_possession', 'low_pass', 'lofted_pass', 'finishing', 'heading', 'place_kicking', 'curl']],
  ['Thể chất', ['speed', 'acceleration', 'kicking_power', 'jump', 'physical_contact', 'balance', 'stamina']],
  ['Phòng ngự', ['defensive_awareness', 'ball_winning', 'aggression']],
  ['Thủ môn', ['gk_awareness', 'gk_catching', 'gk_clearing', 'gk_reflexes', 'gk_reach']]];
const KIND = {result: ['⚽', 'Kết quả'], growth: ['📈', 'Phát triển'], skill: ['✨', 'Kỹ năng'], style: ['🔄', 'Phong cách'],
  position: ['🧭', 'Vị trí'], ai: ['🤖', 'AI'], advice: ['💡', 'Gợi ý'], transfer: ['⇄', 'Chuyển nhượng'],
  offer: ['💰', 'Đề nghị'], injury: ['🩹', 'Chấn thương'], contract: ['📝', 'Hợp đồng'], retire: ['👋', 'Giải nghệ'],
  youth: ['🌱', 'Đội trẻ'], regen: ['♻', 'Regen'], welcome: ['★', 'Dugout'], preview: ['🎯', 'Trận tới'],
  form: ['📊', 'Phong độ'], playtime: ['🗣', 'Thời gian thi đấu'], review: ['🤖', 'Đối chiếu dự đoán'], board: ['🏛', 'Ban lãnh đạo'],
  followup: ['↩', 'Trả lời'], training: ['⏳', 'Tập luyện']};
const ARROW = ['↓', '↘', '→', '↗', '↑'];
const ARROW_VI = ['E · rất kém', 'D · kém', 'C · bình thường', 'B · tốt', 'A · rất tốt'];
const STYLES = ['Goal Poacher', 'Dummy Runner', 'Fox in the Box', 'Prolific Winger', 'Classic No. 10', 'Hole Player',
  'Box-to-Box', 'Anchor Man', 'The Destroyer', 'Extra Frontman', 'Offensive Full-back', 'Defensive Full-back', 'Target Man',
  'Creative Playmaker', 'Build Up', 'Offensive Goalkeeper', 'Defensive Goalkeeper', 'Roaming Flank', 'Cross Specialist',
  'Orchestrator', 'Full-back Finisher'];
const SKILLS = ['Scissors Feint', 'Double Touch', 'Flip Flap', 'Marseille Turn', 'Sombrero', 'Cross Over Turn',
  'Cut Behind & Turn', 'Scotch Move', 'Step On Skill Control', 'Heading', 'Long Range Drive', 'Chip Shot Control',
  'Long Range Shooting', 'Knuckle Shot', 'Dipping Shot', 'Rising Shots', 'Acrobatic Finishing', 'Heel Trick',
  'First-time Shot', 'One-touch Pass', 'Through Passing', 'Weighted Pass', 'Pinpoint Crossing', 'Outside Curler', 'Rabona',
  'No Look Pass', 'Low Lofted Pass', 'GK Low Punt', 'GK High Punt', 'Long Throw', 'GK Long Throw', 'Penalty Specialist',
  'GK Penalty Saver', 'Malicia', 'Man Marking', 'Track Back', 'Interception', 'Acrobatic Clear', 'Captaincy', 'Super-sub',
  'Fighting Spirit'];
const PERSONAS_FB = {assistant: {name: 'Trợ lý HLV', icon: '🧢'}, fitness: {name: 'HLV thể lực', icon: '💪'},
  medical: {name: 'Bác sĩ trưởng', icon: '🩺'}, analyst: {name: 'Phân tích dữ liệu', icon: '🤖'}, scout: {name: 'Tuyển trạch viên', icon: '🔭'},
  director: {name: 'Giám đốc thể thao', icon: '💼'}, academy: {name: 'Giám đốc học viện', icon: '🌱'}, board: {name: 'Ban lãnh đạo', icon: '🏛'}};
const BALL_WHY = {goal: 'Bàn thắng', kickoff: 'Giao bóng', throw: 'Ném biên', corner: 'Phạt góc', goalkick: 'Phát bóng',
  foul: 'Phạm lỗi', pk: 'Phạt đền', sub: 'Thay người', timeup: 'Hết hiệp', stop: 'Bóng chết'};
const TL_ICON = {goal: '⚽', shot: '🎯', sub: '🔁', period: '⏱', start: '▶', end: '🏁', card: '🟨', pen: '❗', pos: '🔀'};
const FEED_ICON = {defence: '🛡', attack: '⚔', shape: '▦', fitness: '🔋', event: '•', context: '⏱'};
const TYPE_VI = {dribbling: 'Rê bóng', pass: 'Phối hợp', cross: 'Tạt bóng', through_ball: 'Chọc khe', set_piece: 'Cố định', penalties: 'Phạt đền'};

const TABS = [['home', '⌂', 'Trang chủ'], ['match', '⚔', 'Trận tới'], ['live', '◉', 'Trực tiếp'], ['inbox', '✉', 'Tin nhắn'], ['more', '☰', 'Thêm']];
const MORE = [['fixtures', '📅', 'Lịch & kết quả', 'Mọi trận, tỉ số, điểm cầu thủ'], ['table', '🏆', 'Bảng xếp hạng', 'Các giải đang đá'],
  ['scorers', '⚽', 'Vua phá lưới', 'Ghi bàn, kiến tạo'], ['squad', '👥', 'Đội hình', 'Cầu thủ, phong độ, gợi ý'],
  ['market', '⇄', 'Chuyển nhượng', 'Kế hoạch hè, tìm cầu thủ'], ['youth', '🌱', 'Đội trẻ & Regen', 'Tài năng trẻ'],
  ['ai', '🤖', 'AI dự đoán', 'Độ chính xác, sao lưu'], ['conn', '📶', 'Kết nối', 'Máy tính, save, cập nhật']];

const S = {bundle: null, version: -1, status: null, tab: 'home', sub: null, nav: [], scroll: {}, readNow: {},
  homeTop: 'goals', matchSel: 0, matchSec: 'overview', fixTab: 'list', fixComp: null, fixRound: null, scComp: null,
  squadView: 'list', squadFilter: 'all', marketTab: 'plan', youthTab: 'youth', lvTab: 'tl', liveDots: {}};

// ------------------------------------------------------------------ helpers
const $ = s => document.querySelector(s);
const SVGNS = 'http://www.w3.org/2000/svg';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const num = v => String(v ?? '').replace('.', ',');
const ovrClass = v => v >= 90 ? 'o90' : v >= 85 ? 'o85' : v >= 80 ? 'o80' : v >= 75 ? 'o75' : v >= 70 ? 'o70' : 'o0';
const ovr = v => v == null ? '' : `<span class="ovr ${ovrClass(v)}">${v}</span>`;
const face = (id, cls = '') => id ? `<img class="face ${cls}" loading="lazy" src="/face/${id}.png" onerror="this.style.visibility='hidden'">` : `<span class="face ${cls}"></span>`;
const initials = n => esc((n || '?').replace(/\b(FC|AFC|CF|SC|AC)\b/g, '').trim().split(/\s+/).map(w => w[0]).join('').slice(0, 3).toUpperCase());
function crest(tid, name, size = '') {
  if (!tid) return '';
  const px = size === 'lg' ? 58 : size === 'md' ? 40 : 24;
  return `<img class="crest ${size}" src="/badge/${tid}.png" alt="" onerror="this.outerHTML='<span class=&quot;crest crest-fb ${size}&quot; style=&quot;width:${px}px;height:${px}px&quot;>${initials(name)}</span>'">`;
}
const shortTeam = n => String(n || '').replace(/\s+(FC|AFC|CF|SC)$/, '').replace(/^(FC|AFC|AC)\s+/, '');
const res = o => o ? `<span class="res ${o}">${{W: 'T', D: 'H', L: 'B'}[o]}</span>` : '';
const arrow = c => c == null || c < 0 ? '' : `<span class="arw a${c}">${ARROW[c]}</span>`;
const rtc = r => r == null || r === '' ? '' : `<span class="rt ${r >= 8 ? 'hi' : r >= 7 ? 'ok' : r < 6 ? 'lo' : ''}">${r}</span>`;
const rt = p => p.r10 ?? p.rating;
const vnDate = iso => { if (!iso) return ''; const [y, m, d] = iso.split('-').map(Number); return `${d}/${m}/${y}`; };
const shortDate = iso => { if (!iso) return ''; const [, m, d] = iso.split('-').map(Number); return `${d}/${m}`; };
const WD = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
const weekday = iso => WD[new Date(iso + 'T00:00:00').getDay()];
const daysTxt = d => d <= 0 ? 'Hôm nay' : d === 1 ? 'Ngày mai' : `còn ${d} ngày`;
const lastWord = n => String(n || '').split(' ').slice(-1)[0];
function money(v) {
  if (v == null || isNaN(v)) return '—';
  if (v >= 1e9) return '€' + (v / 1e9).toFixed(2).replace('.', ',') + ' tỷ';
  if (v >= 1e6) return '€' + (v / 1e6).toFixed(1).replace('.', ',') + ' tr';
  if (v >= 1e3) return '€' + Math.round(v / 1e3) + ' nghìn';
  return '€' + v;
}
function tags(p) {
  let t = '';
  if (p.inj) t += `<span class="tag inj">🩹 ${p.inj} ngày</span>`;
  if (p.regen) t += '<span class="tag">Regen</span>';
  if (p.youth) t += '<span class="tag">Đội trẻ</span>';
  if (p.listed) t += '<span class="tag y">Rao bán</span>';
  if (p.retiring) t += '<span class="tag">Sắp giải nghệ</span>';
  if (p.training_n) t += `<span class="tag y">⏳ ${p.training_n}</span>`;
  if (p.advice_n) t += `<span class="tag ok">💡 ${p.advice_n}</span>`;
  return t;
}
const trendTxt = p => p.trend > 0 ? `<span class="up">▲ còn tăng tới ~${p.reach_age} tuổi</span>` : p.trend < 0 ? '<span class="down">▼ đang giảm</span>' : '<span class="mut">■ chững</span>';
const bar = (v, max, cls = '') => `<div class="bar ${cls}"><i style="width:${Math.max(0, Math.min(100, v / max * 100))}%"></i></div>`;

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  return r.json();
}
const post = (path, body) => fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Dugout': '1'}, body: JSON.stringify(body || {})});
function toast(text, ms = 2600) {
  const el = $('#toast');
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(S.toastT);
  S.toastT = setTimeout(() => el.classList.remove('show'), ms);
}

// the chips bars keep where they were scrolled to when a screen is drawn again
const keepChips = root => [...root.querySelectorAll('.chips')].map(c => c.scrollLeft);
const restoreChips = (root, left) => root.querySelectorAll('.chips').forEach((c, i) => { if (left[i]) c.scrollLeft = left[i]; });
function showOn(root) {                          // the chosen chip in view (a bar scrolled sideways)
  root.querySelectorAll('.chips').forEach(c => {
    const on = c.querySelector('.chip.on');
    if (!on) return;
    const l = on.offsetLeft - c.offsetLeft;
    if (l < c.scrollLeft || l + on.offsetWidth > c.scrollLeft + c.clientWidth) c.scrollLeft = Math.max(0, l - (c.clientWidth - on.offsetWidth) / 2);
  });
}

// ------------------------------------------------------------------ navigation
// Every screen on top of a tab (a page of "Thêm", a player, a match, a conversation, the sideways map) is one
// step back: the phone's back button (or ‹) closes it.
function push(entry) {
  S.nav.push(entry);
  try { history.pushState({dg: S.nav.length}, ''); } catch (e) {}
}
function back() { if (S.nav.length) history.back(); }
window.addEventListener('popstate', () => {
  if (S.skipPop) { S.skipPop = false; return; }
  const e = S.nav.pop();
  if (e) undo(e, true);
});
function undo(e, redraw) {
  if (e.kind === 'sheet') closeSheet(e.el);
  else if (e.kind === 'sub') {
    saveScroll();
    S.sub = null;
    if (e.from && e.from !== S.tab) S.tab = e.from;
    if (redraw) draw(true);
  } else if (e.kind === 'full') { S.fullBtn = false; S.fullOff = LAND_Q.matches; exitFs(); }
  fullUpdate();
}
function resetNav() {                           // a tab tapped: everything on top closed at once
  if (!S.nav.length) return;
  const n = S.nav.length;
  S.nav.splice(0).reverse().forEach(e => undo(e, false));
  S.skipPop = true;
  history.go(-n);
}
function saveScroll() { if (S.drawnKey) S.scroll[S.drawnKey] = $('#page').scrollTop; }
function go(tab) {
  const was = S.tab;
  resetNav();
  if (tab === was && S.drawnKey === tab) { $('#page').scrollTo({top: 0, behavior: 'smooth'}); return; }
  saveScroll();
  S.tab = tab;
  S.sub = null;
  if (tab === 'live') S.fullOff = false;
  draw(true);
  fullUpdate();
}
function openSub(name, from) {
  saveScroll();
  push({kind: 'sub', from: from && from !== 'more' ? from : null});
  S.tab = 'more';
  S.sub = name;
  draw(true);
}

// Sheets: a player, a match, a conversation… on the whole screen, sliding up; several can be open (a player
// from a conversation), the back button closes the top one.
function openSheet(e) {
  const el = document.createElement('section');
  el.className = 'sheet';
  el.innerHTML = '<header class="hdr"><button class="back" data-back aria-label="Quay lại">‹</button><div class="hx" data-head></div></header><div class="page" data-body></div>';
  document.body.appendChild(el);
  e.kind = 'sheet';
  e.el = el;
  fillSheet(e);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('open')));
  push(e);
  fullUpdate();
  return e;
}
function fillSheet(e, keep) {
  const body = e.el.querySelector('[data-body]'), y = body.scrollTop, nearEnd = body.scrollHeight - y - body.clientHeight < 80;
  e.el.querySelector('[data-head]').innerHTML = e.head ? e.head() : `<div class="t"><b>${esc(e.title || '')}</b>${e.sub ? `<small>${esc(e.sub)}</small>` : ''}</div>`;
  const left = keepChips(body);
  body.innerHTML = e.draw(e);
  restoreChips(body, left);
  showOn(body);
  if (e.bottom && (!keep || nearEnd)) {
    const end = () => { body.scrollTop = body.scrollHeight; };
    end(); setTimeout(end, 150);
  } else if (keep) body.scrollTop = y;
  else body.scrollTop = 0;
}
function closeSheet(el) {
  el.classList.remove('open');
  setTimeout(() => el.remove(), 260);
}
const topSheet = () => { for (let i = S.nav.length - 1; i >= 0; i--) if (S.nav[i].kind === 'sheet') return S.nav[i]; return null; };
function refreshSheets() { S.nav.filter(e => e.kind === 'sheet' && !e.fixed).forEach(e => fillSheet(e, true)); }

// ------------------------------------------------------------------ chrome
function dotState() {
  const s = S.status || {};
  return S.connErr ? 'error' : s.offline ? 'offline' : s.state || '';
}
function header() {
  const b = S.bundle, s = S.status || {};
  const st = b.home.standing;
  const line = S.connErr ? 'Mất kết nối với máy tính' : s.offline ? s.message || 'Máy tính chưa kết nối'
    : s.state === 'syncing' ? 'Đang đọc save…' : `${b.date_vi}${st ? ` · hạng ${st.pos}/${st.of}` : ''}`;
  const html = S.tab === 'more' && S.sub
    ? `<button class="back" data-back aria-label="Quay lại">‹</button><div class="t"><b>${MORE.find(m => m[0] === S.sub)[2]}</b><small>${esc(line)}</small></div>`
    : `${crest(b.club.id, b.club.name)}<div class="t"><b>${esc(b.club.name)}</b><small>${esc(line)}</small></div>`;
  const now = new Date();                       // full screen hides the phone's clock: ours instead
  const clock = FULLSCREEN_APP.matches ? `<span class="clock">${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}</span>` : '';
  const full = html + clock + `<span class="dot ${dotState()}"></span>`;
  if (full !== S.hdrSig) { S.hdrSig = full; $('#hdr').innerHTML = full; }
}
function tabbar() {
  const b = S.bundle, ml = (S.status || {}).matchlive || {};
  const unread = b ? b.inbox.filter(e => !e.read).length : 0;
  const badge = {inbox: unread ? String(unread > 99 ? '99+' : unread) : '', live: ml.state === 'live' ? 'LIVE' : ml.live ? '•' : ''};
  const html = TABS.map(([k, ic, l]) => `<button data-tab="${k}" class="${S.tab === k ? 'on' : ''}"><i>${ic}</i>${l}<span class="bd ${k}">${badge[k] || ''}</span></button>`).join('');
  if (html !== S.tabSig) { S.tabSig = html; $('#tabbar').innerHTML = html; }
}

const FULLSCREEN_APP = matchMedia('(display-mode: fullscreen)');
const VIEWS = {home: vHome, match: vMatch, inbox: vInbox, more: vMore};
const SUBS = {fixtures: vFixtures, table: vTable, scorers: vScorers, squad: vSquad, market: vMarket, youth: vYouth, ai: vAi, conn: vConn};
const viewKey = () => S.tab + (S.tab === 'more' && S.sub ? ':' + S.sub : '');
function draw(fresh) {
  if (!S.bundle) return;
  header();
  tabbar();
  const page = $('#page');
  if (S.tab === 'live') { S.drawnKey = 'live'; drawLiveShell(); return; }
  page.classList.remove('is-live');
  const key = viewKey(), same = !fresh && S.drawnKey === key;
  const left = same ? keepChips(page) : [], y = page.scrollTop;
  page.innerHTML = S.tab === 'more' && S.sub ? SUBS[S.sub]() : VIEWS[S.tab]();
  if (same) { restoreChips(page, left); page.scrollTop = y; } else page.scrollTop = S.scroll[key] || 0;
  showOn(page);
  S.drawnKey = key;
  const f = S.after;
  S.after = null;
  if (f) f(page);
}
// a section / a filter chosen: the page stays where it is, the list starts right under the chips
function setAndDraw(key, val) {
  S[key] = /^\d+$/.test(val) ? Number(val) : val;
  draw(false);
  const page = $('#page'), a = page.querySelector('[data-anchor]');
  if (a) {
    const y = a.getBoundingClientRect().top - page.getBoundingClientRect().top + page.scrollTop;
    if (page.scrollTop > y) page.scrollTop = y;
  }
}

// ------------------------------------------------------------------ data
async function loadBundle() {
  if (S.loading) return;
  S.loading = true;
  try {
    const first = !S.bundle;
    const b = await api('/api/bundle');
    S.bundle = b;
    S.version = b.version;
    S.unreadSig = null;
    S.plan = null;
    for (const e of b.inbox) if (S.readNow[e.id] && Date.now() - S.readNow[e.id] < 8000) e.read = true;
    draw(first);
    refreshSheets();
    $('#splash').classList.add('gone');
  } catch (e) {
    console.error('Dugout', e && e.stack || e);
    setTimeout(() => { S.loading = false; loadBundle(); }, 1500);
    return;
  }
  S.loading = false;
}
async function poll() {
  try {
    const s = await api('/api/status');
    S.status = s;
    S.connErr = false;
    S.remote = !!s.remote;
    const lv = s.live || {};
    if (lv.version && lv.version !== S.liveVersion) {      // player values read from the running game
      S.liveVersion = lv.version;
      try { S.live = await api('/api/live'); } catch (e) {}
    }
    if (s.version > S.version) await loadBundle();
    if (s.unread_sig && s.unread_sig !== S.unreadSig && S.bundle) syncUnread(s.unread_sig);
    const ml = s.matchlive || {};
    if (ml.live && ml.key && S.autoKey !== ml.key && S.bundle) {   // a match started: the live tab, once
      S.autoKey = ml.key;
      if (S.tab !== 'live') go('live');
    }
    if (s.build && !s.offline) {                 // Dugout updated on the PC: the app reloads itself
      if (!S.build) S.build = s.build;
      else if (s.build !== S.build && !S.reloading) {
        S.reloading = true;
        toast('Dugout vừa được cập nhật: đang tải bản mới…');
        setTimeout(() => location.reload(), 1200);
      }
    }
  } catch (e) {
    S.connErr = true;
    if (!S.bundle) $('#splash div').textContent = 'Chưa kết nối được máy tính… (Dugout trên máy tính đang chạy?)';
  }
  if (S.bundle) {
    header();
    tabbar();
    if (S.tab === 'more' && (S.sub === 'conn' || S.sub === 'ai')) draw(false);
    if (S.tab === 'home' && S.liveWas !== !!((S.status || {}).matchlive || {}).live) draw(false);
    S.liveWas = !!((S.status || {}).matchlive || {}).live;
  }
  clearTimeout(S.pollT);
  S.pollT = setTimeout(poll, document.hidden ? 6000 : 2000);
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { clearTimeout(S.pollT); poll(); if (S.tab === 'live') startLive(); }
});

// ------------------------------------------------------------------ messages
function persona(key, e) {
  const P = S.bundle.personas || PERSONAS_FB;
  if (key && key.startsWith('player:')) {
    const pid = Number(key.split(':')[1]);
    const sq = S.bundle.squad.find(p => p.id === pid) || S.bundle.youth.youth.find(p => p.id === pid);
    return {name: (e && e.from_name) || (sq && sq.name) || 'Cầu thủ', role: sq ? `${sq.pos} · ${sq.age} tuổi` : 'Cầu thủ', pid};
  }
  const p = P[key] || {name: key, icon: '•', role: ''};
  return {name: p.name, role: p.role, icon: p.icon};
}
const avatar = (p, cls = '') => p.pid ? `<img class="av ${cls}" src="/face/${p.pid}.png" onerror="this.style.visibility='hidden'">`
  : `<span class="av ${cls}">${p.icon || '•'}</span>`;
function threads() {
  const map = new Map();
  for (const e of S.bundle.inbox) {
    const k = e.from || 'assistant';
    if (!map.has(k)) map.set(k, {key: k, events: [], unread: 0, info: persona(k, e)});
    const t = map.get(k);
    t.events.push(e);
    if (!e.read) t.unread++;
  }
  return [...map.values()];
}
const ago = iso => {
  const days = Math.round((new Date(S.bundle.date + 'T00:00:00') - new Date(iso + 'T00:00:00')) / 864e5);
  return days <= 0 ? 'Hôm nay' : days === 1 ? 'Hôm qua' : days < 7 ? `${days} ngày` : shortDate(iso);
};
function threadRow(t) {
  const last = t.events[0];
  return `<div class="row tap ${t.unread ? 'unread' : ''}" data-thread="${esc(t.key)}">${avatar(t.info)}
    <div class="grow"><span class="nm">${esc(t.info.name)}</span><div class="sub">${last.reply_text ? 'Bạn: ' + esc(last.reply_text) : esc(last.title)}</div></div>
    <div class="end"><small class="mut">${ago(last.date)}</small>${t.unread ? `<div class="bdg">${t.unread}</div>` : ''}</div></div>`;
}
function vInbox() {
  const ts = threads(), total = ts.reduce((a, t) => a + t.unread, 0);
  return `<div class="sec">Đoạn chat${total ? ` · ${total} chưa đọc` : ''}</div>
    <div class="card threads">${ts.map(threadRow).join('') || '<div class="empty">Chưa có tin nhắn.</div>'}</div>
    ${total ? '<button class="wide" data-readall>Đánh dấu đã đọc tất cả</button>' : ''}`;
}
function openThread(key) {
  const find = () => threads().find(t => t.key === key);
  const t0 = find();
  if (!t0) return;
  openSheet({type: 'thread', key, bottom: true,
    head: () => { const t = find() || t0; return `${avatar(t.info, 'sm')}<div class="t"><b>${esc(t.info.name)}</b><small>${esc(t.info.role || '')}</small></div>${t.info.pid ? `<button class="hbtn" data-pid="${t.info.pid}">Hồ sơ</button>` : ''}`; },
    draw: () => convHtml(find() || t0)});
  if (t0.unread) markRead(t0.events.filter(e => !e.read).map(e => e.id));
}
function convHtml(t) {
  const evs = t.events.slice(0, 60).reverse();
  const since = new Date(new Date(S.bundle.date + 'T00:00:00') - 14 * 864e5).toISOString().slice(0, 10);
  const lastAsk = [...evs].reverse().find(e => e.kind !== 'followup');
  let day = null;
  const sq = id => (S.bundle.squad.find(p => p.id === id) || {}).name || 'Cầu thủ';
  return `<div class="conv">${evs.map(e => {
    const [ic, label] = KIND[e.kind] || ['•', ''];
    const players = (e.players || []).filter(id => id !== t.info.pid).slice(0, 6);
    const links = [...players.map(id => `<button data-pid="${id}">${esc(sq(id))}</button>`),
      e.match ? `<button data-match="${esc(e.match)}">Xem trận đấu</button>` : '',
      e.fixture ? '<button data-tab="match">Phân tích trận</button>' : ''].join('');
    const ask = (e === lastAsk || e.date >= since) && !e.reply && (e.choices || []).length
      ? e.choices.map(c => `<button class="q" data-reply="${esc(e.id)}" data-choice="${esc(c.id)}">${esc(c.label)}</button>`).join('') : '';
    const sep = e.date !== day ? `<div class="daysep"><span>${vnDate(e.date)}</span></div>` : '';
    day = e.date;
    const head = e.kind !== 'followup' ? `<span class="k">${ic} ${label}</span>${e.title !== e.body ? `<b class="t">${esc(e.title)}</b>` : ''}` : '';
    return `${sep}<div class="bub">${head}<div class="bb">${esc(e.body)}</div>${links || ask ? `<div class="acts">${links}${ask}</div>` : ''}</div>`
      + (e.reply_text ? `<div class="bub out"><div class="bb">${esc(e.reply_text)}</div></div>` : '');
  }).join('')}</div>`;
}
function markRead(ids) {
  const now = Date.now();
  S.bundle.inbox.forEach(e => { if (!ids || ids.includes(e.id)) { if (!e.read) S.readNow[e.id] = now; e.read = true; } });
  post('/api/read', {ids}).catch(() => {});
  tabbar();
  if (S.tab === 'inbox' || S.tab === 'home') draw(false);
}
async function syncUnread(sig) {
  if (S.unreadBusy || !S.bundle) return;
  S.unreadBusy = true;
  try {
    const r = await api('/api/unread');
    const un = new Set(r.ids || []), now = Date.now();
    let changed = false;
    for (const e of S.bundle.inbox) {
      const rd = !un.has(e.id) || now - (S.readNow[e.id] || 0) < 8000;
      if (!!e.read !== rd) { e.read = rd; changed = true; }
    }
    S.unreadSig = sig;
    if (changed) { tabbar(); if (S.tab === 'inbox' || S.tab === 'home') draw(false); }
  } catch (e) {} finally { S.unreadBusy = false; }
}
async function sendReply(id, choice, btn) {
  const box = btn.closest('.acts');
  box.querySelectorAll('button').forEach(x => x.disabled = true);
  let out;
  try { out = await (await post('/api/reply', {id, choice})).json(); } catch (e) { out = null; }
  if (!out || !out.ok) { box.querySelectorAll('button').forEach(x => x.disabled = false); toast(out && out.error || 'Chưa gửi được (máy tính chưa kết nối?)'); return; }
  const e = S.bundle.inbox.find(x => x.id === id);
  const c = (e.choices || []).find(x => x.id === choice);
  Object.assign(e, {reply: choice, reply_text: c ? c.label : '', replied: out.event.date, read: true});
  S.bundle.inbox.unshift(out.event);
  refreshSheets();
  if (S.tab === 'inbox') draw(false);
  const a = out.action || '';
  if (a === 'match') setTimeout(() => go('match'), 700);
  else if (a === 'youth') setTimeout(() => { go('more'); openSub('youth'); }, 700);
  else if (a.startsWith('player:')) { const [, pid, tab] = a.split(':'); setTimeout(() => openPlayer(pid, tab), 500); }
}

// ------------------------------------------------------------------ home
function predBar(p, venue) {
  const lab = (v, w) => v >= 26 ? `${w} ${v}%` : v >= 11 ? `${v}%` : '';
  const sc = (p.scores || []).slice(0, 2).map(x => { const s = venue === 'home' ? x.s : [x.s[1], x.s[0]]; return `${s[0]}–${s[1]} (${x.p}%)`; }).join(' · ');
  return `<div class="pbar"><span class="w" style="flex:${p.w}">${lab(p.w, 'Thắng')}</span><span class="d" style="flex:${p.d}">${lab(p.d, 'Hòa')}</span><span class="l" style="flex:${p.l}">${lab(p.l, 'Thua')}</span></div>
    <div class="sub wrap" style="margin-top:6px">AI: thắng ${p.w}% · hòa ${p.d}% · thua ${p.l}%${p.xg ? ` · bàn kỳ vọng ${num(p.xg[0])}–${num(p.xg[1])}` : ''}${sc ? ` · dễ xảy ra ${sc}` : ''}</div>`;
}
// who scored, under each side; own goals under the side they count for
function scorers(m) {
  const og = m.og || {};
  const ogl = o => `⚽ ${o.name ? esc(o.name) + ' <span class="og">(phản lưới)</span>' : '<span class="og">Phản lưới nhà</span>'}`;
  const g = (arr, own) => (arr || []).filter(p => p.g).map(p => `⚽ ${esc(p.name)}${p.g > 1 ? ` (${p.g})` : ''}`).concat((own || []).map(ogl)).join('<br>');
  const hs = g(m.home_players, og.home), as = g(m.away_players, og.away);
  return hs || as ? `<div class="scorers"><div class="h">${hs || '—'}</div><div>${as || '—'}</div></div>` : '';
}
function heroTeams(m, mid, size = 'lg') {
  const me = S.bundle.club.id;
  return `<div class="hero"><div class="tm ${m.home === me ? 'me' : ''}">${crest(m.home, m.home_name, size)}<span>${esc(shortTeam(m.home_name))}</span></div>
    <div class="mid">${mid}</div><div class="tm ${m.away === me ? 'me' : ''}">${crest(m.away, m.away_name, size)}<span>${esc(shortTeam(m.away_name))}</span></div></div>`;
}
function vHome() {
  const b = S.bundle, h = b.home, me = b.club.id, ml = (S.status || {}).matchlive || {};
  let out = '';
  if (ml.live) out += `<div class="card tap livecard" data-tab="live"><span class="pulse"></span><div class="grow"><b>Đang có trận</b>
    <div class="sub">Bản đồ trực tiếp, nhận định AI, thể lực: chạm để xem</div></div><span class="chev">›</span></div>`;
  const nx = h.next;
  if (nx) {
    const mf = ((b.matchday || {}).fixtures || []).find(f => f.key === nx.key);
    out += `<div class="card"><h3>Trận tiếp theo <span class="more" data-tab="match">Phân tích ›</span></h3>
      ${heroTeams(nx, `<b>VS</b><small>${nx.hour != null ? nx.hour + ':00' : ''}</small>`)}
      <div class="meta"><span>${esc(nx.comp_name)} · ${esc(nx.round)}</span><span>${weekday(nx.date)} ${shortDate(nx.date)}</span><span class="hl">${daysTxt(nx.days)}</span></div>
      ${mf && mf.pred ? predBar(mf.pred, mf.venue) : ''}</div>`;
  } else out += '<div class="card"><h3>Trận tiếp theo</h3><div class="empty">Chưa có lịch.</div></div>';
  const last = h.last;
  if (last) out += `<div class="card tap" data-match="${esc(last.key)}"><h3>Trận gần nhất ${res(last.outcome)}<span class="more">Chi tiết ›</span></h3>
      ${heroTeams(last, `<b>${last.hg}–${last.ag}</b><small>${shortDate(last.date)}</small>`, 'md')}
      <div class="meta"><span>${esc(last.comp_name)} · ${esc(last.round)}</span></div>${scorers(last)}</div>`;
  const st = h.standing, comp = b.comps.find(c => c.table && c.table.length);
  if (st) {
    let mini = '';
    if (comp) {
      const idx = comp.table.findIndex(t => t.team === me), from = Math.max(0, Math.min(idx - 2, comp.table.length - 5));
      mini = `<table class="t"><tbody>${comp.table.slice(from, from + 5).map(t => `<tr class="${t.team === me ? 'me' : ''}"><td>${t.pos}</td>
        <td>${crest(t.team, t.name)} ${esc(shortTeam(t.name))}</td><td>${t.p}</td><td>${t.gf - t.ga > 0 ? '+' : ''}${t.gf - t.ga}</td><td><b>${t.pts}</b></td></tr>`).join('')}</tbody></table>`;
    }
    const r = h.record;
    out += `<div class="card tap" data-sub="table"><h3>${esc(st.comp)} <span class="more">Bảng ›</span></h3>
      <div class="grid2"><div class="stat"><b>${st.pos}<small class="mut">/${st.of}</small></b><small>Thứ hạng</small></div>
        <div class="stat"><b>${st.pts}</b><small>điểm · ${st.p} trận</small></div></div>
      <div class="formrow">${[...(h.form || '')].map(res).join('')}<small class="mut">${r.w}T ${r.d}H ${r.l}B · ${r.gf}–${r.ga}</small></div>${mini}</div>`;
  }
  const lowForm = ((b.matchday || {}).form || []).filter(r => r.plan === 'start' && r.cond >= 0 && r.cond <= 1);
  const att = [
    ...lowForm.map(r => `<div class="row tap" data-pid="${r.id}">${arrow(r.cond)}<div class="grow"><span class="nm">${esc(r.name)}</span><div class="sub">phong độ ${r.arrow} nhưng đang đá chính</div></div><span class="chev">›</span></div>`),
    ...h.injured.map(r => `<div class="row tap" data-pid="${r.id}"><span class="ic">🩹</span><div class="grow"><span class="nm">${esc(r.name)}</span><div class="sub">chấn thương ${r.inj} ngày</div></div><span class="chev">›</span></div>`),
    ...h.expiring.map(r => `<div class="row tap" data-pid="${r.id}"><span class="ic">📝</span><div class="grow"><span class="nm">${esc(r.name)}</span><div class="sub">hết hợp đồng ${r.contract ? `${r.contract[2]}/${r.contract[1]}/${r.contract[0]}` : ''}</div></div><span class="chev">›</span></div>`)];
  if (att.length) out += `<div class="card"><h3>Cần chú ý</h3>${att.join('')}</div>`;
  const T3 = {goals: ['Ghi bàn', h.top_goals, r => r.goals], assists: ['Kiến tạo', h.top_assists, r => r.assists],
    rating: ['Điểm TB', h.top_rating, r => (r.rating10 ?? r.rating ?? 0).toFixed(2).replace('.', ',')]};
  const cur = T3[S.homeTop] || T3.goals;
  out += `<div class="card"><h3>Cầu thủ nổi bật</h3><div class="chips">${Object.entries(T3).map(([k, [l]]) => `<button class="chip ${cur === T3[k] ? 'on' : ''}" data-set="homeTop:${k}">${l}</button>`).join('')}</div>
    ${cur[1].map(r => `<div class="row tap" data-pid="${r.id}">${face(r.id, 'sm')}<div class="grow"><span class="nm">${esc(r.name)}</span></div><b>${cur[2](r)}</b></div>`).join('') || '<div class="empty">Chưa có dữ liệu.</div>'}</div>`;
  if (h.advice_total) out += `<div class="card"><h3>💡 Gợi ý phát triển <span class="more" data-sub="squad" data-filter="advice">${h.advice_total} cầu thủ ›</span></h3>
    ${h.advice.slice(0, 4).map(r => `<div class="row tap" data-pid="${r.id}" data-ptab="dev">${face(r.id, 'sm')}<div class="grow"><span class="nm">${esc(r.name)}</span>
      <div class="sub">${r.pos}${(r.advice_kinds || []).length ? ' · ' + r.advice_kinds.map(k => ({style: 'Phong cách', skill: 'Kỹ năng', position: 'Vị trí'}[k] || k)).join(', ') : ''}</div></div><span class="chev">›</span></div>`).join('')}</div>`;
  out += `<div class="card threads"><h3>Tin nhắn <span class="more" data-tab="inbox">Tất cả ›</span></h3>${threads().slice(0, 3).map(threadRow).join('') || '<div class="empty">Chưa có tin.</div>'}</div>`;
  return out;
}

// ------------------------------------------------------------------ next match
function pitchXI(players, flip, captain, opp) {
  return `<div class="pitch ${opp ? 'opp' : ''}">${players.map(p => {
    let left = p.x / 104 * 100, top = 100 - (p.y / 50 * 84 + 8);
    if (flip) { left = 100 - left; top = 100 - top; }
    left = Math.max(10, Math.min(90, left));
    return `<div class="pp tap" style="left:${left}%;top:${top}%" data-pid="${p.id}"><img src="/face/${p.id}.png" onerror="this.style.visibility='hidden'">${arrow(p.cond)}
      <span class="n">${p.id === captain ? '© ' : ''}${esc(lastWord(p.name))}</span><span class="p">${p.role} · ${p.ovr}${p.inj ? ' · 🩹' : ''}</span></div>`;
  }).join('')}</div>`;
}
const phaseBox = P => P && P.phases ? `<div class="sub" style="margin-top:10px">Sơ đồ theo tình huống</div>${P.phases.map(p => `<div class="kv"><span>${esc(p.label)}</span>
  <b>${esc(p.shape)}${p.moves.length ? ` <small class="mut">(${p.moves.map(m => `${esc(m.name || '')} ${m.from}→${m.to}`).join(', ')})</small>` : ''}</b></div>`).join('')}
  ${P.presets.length ? `<div class="kv"><span>Bộ dự phòng</span><b>${P.presets.map(x => `#${x.n}: ${esc(x.shape)}`).join(' · ')}</b></div>` : ''}` : '';
const MSEC = [['overview', 'Tổng quan'], ['lineup', 'Đội hình'], ['tactics', 'Chiến thuật'], ['opponent', 'Đối thủ'], ['duels', 'Đối đầu'], ['form', 'Phong độ']];
function vMatch() {
  const b = S.bundle, md = b.matchday;
  if (!md || !md.fixtures.length) return '<div class="empty">Chưa có trận nào sắp tới trong lịch.</div>';
  const fxs = md.fixtures;
  if (S.matchSel >= fxs.length) S.matchSel = 0;
  const f = fxs[S.matchSel], me = b.club.id, them = shortTeam(f.opp_name);
  const pick = fxs.length > 1 ? `<div class="chips">${fxs.map((x, k) => `<button class="chip ${k === S.matchSel ? 'on' : ''}" data-set="matchSel:${k}">${esc(shortTeam(x.opp_name))} · ${shortDate(x.date)}</button>`).join('')}</div>` : '';
  const pos = tid => { const p = tid === me ? f.pos_me : f.pos_opp; return p ? `<small class="mut">hạng ${p.pos}</small>` : ''; };
  const hero = `<div class="card">${f.derby ? '<div class="derby">🔥 TRẬN DERBY</div>' : ''}
    <div class="hero"><div class="tm ${f.home === me ? 'me' : ''}">${crest(f.home, f.home_name, 'lg')}<span>${esc(shortTeam(f.home_name))}</span>${pos(f.home)}</div>
      <div class="mid"><b>VS</b><small>${f.hour != null ? f.hour + ':00' : ''}</small></div>
      <div class="tm ${f.away === me ? 'me' : ''}">${crest(f.away, f.away_name, 'lg')}<span>${esc(shortTeam(f.away_name))}</span>${pos(f.away)}</div></div>
    <div class="meta"><span>${esc(f.comp_name)}</span><span>${f.venue === 'home' ? 'Sân nhà' : 'Sân khách'}</span><span>${weekday(f.date)} ${vnDate(f.date)}</span><span class="hl">${daysTxt(f.days)}</span></div>
    ${f.pred ? predBar(f.pred, f.venue) + `<div class="sub wrap">OVR đội hình: bạn ${f.my_ovr} · ${esc(them)} ${f.opp_ovr}${f.pred_current ? ` · nếu giữ Game Plan hiện tại: T${f.pred_current.w} H${f.pred_current.d} B${f.pred_current.l}` : ''}</div>`
      : '<div class="empty">Không đọc được đội hình đối thủ.</div>'}</div>`;
  if (!f.pred) return pick + hero;

  const swaps = md.changes.filter(c => c.type === 'swap'), moves = md.changes.filter(c => c.type === 'move');
  const T = f.tactics, tacRows = T.rows.filter(r => r.change);
  const instrAdd = T.instructions.filter(x => !x.have), instrDel = T.remove || [];
  const SP = md.set_pieces || [], spCh = SP.filter(r => r.change);
  const hot = f.matchups.filter(x => x.level === 'cao');
  const count = {lineup: md.changes.length, tactics: tacRows.length + instrAdd.length + instrDel.length + spCh.length, duels: hot.length};
  const sec = MSEC.some(([k]) => k === S.matchSec) ? S.matchSec : 'overview';
  const nav = `<div class="chips sticky" data-anchor>${MSEC.map(([k, l]) => `<button class="chip ${k === sec ? 'on' : ''}" data-set="matchSec:${k}">${l}${count[k] ? `<span class="n">${count[k]}</span>` : ''}</button>`).join('')}</div>`;
  const res6 = (f.opp_results || []).map(r => res(r.outcome)).join('');
  const threat = t => `<div class="row tap" data-pid="${t.id}">${face(t.id)}<div class="grow"><span class="nm">${esc(t.name)} ${arrow(t.cond)}</span>
      <div class="sub">${t.role} · OVR ${t.ovr} · ${t.g || 0} bàn · ${t.a || 0} kiến tạo</div><div class="sub wrap">${t.why.map(esc).join(', ')}</div></div>
      <div class="end">${(t.last10 || t.last || []).slice(-3).map(rtc).join('')}</div></div>`;
  const goRow = (k, title, sub, cls = '') => `<div class="row tap" data-set="matchSec:${k}"><div class="grow"><b class="${cls}">${title}</b><div class="sub wrap">${sub}</div></div><span class="chev">›</span></div>`;

  // overview: what to do before kick-off, what to watch out for
  const todo = [];
  if (md.changes.length) todo.push(goRow('lineup', `Đội hình: ${md.changes.length} thay đổi`,
    swaps.slice(0, 3).map(c => `▲ ${esc(c.in_name)} ▼ ${esc(c.out_name)}`).concat(moves.slice(0, 2).map(c => `⇄ ${esc(c.name)} → ${c.role}`)).join(' · ')));
  if (tacRows.length) todo.push(goRow('tactics', `Chiến thuật: ${tacRows.length} mục nên đổi`, tacRows.map(r => `${esc(r.label)} → <b>${esc(r.rec)}</b>`).join(' · ')));
  if (instrAdd.length || instrDel.length) todo.push(goRow('tactics', 'Hướng dẫn nâng cao', [...instrAdd.map(x => '＋ ' + esc(x.text)), ...instrDel.map(x => '✕ ' + esc(x.text))].join(' · ')));
  if (spCh.length) todo.push(goRow('tactics', `Người đá phạt: ${spCh.length} thay đổi`, spCh.map(r => `${esc(r.label)}: <b>${esc(r.rec.name)}</b>`).join(' · ')));
  const overview = `<div class="card"><h3>✅ Việc cần làm trước trận</h3>${todo.join('') || '<div class="note">Game Plan hiện tại đã khớp đề xuất của AI: không cần đổi gì.</div>'}</div>
    <div class="card"><h3>⚠ Cần chú ý ở ${esc(them)}</h3><div class="kv"><span>${(f.opp_results || []).length} trận gần nhất</span><span>${res6}</span></div>
      ${f.threats.slice(0, 3).map(threat).join('')}
      ${hot.length ? goRow('duels', 'Đối đầu nguy hiểm', hot.map(x => `${esc(x.label)}: ${esc(x.att.name)} vs ${esc(x.def.name)}`).join(' · '), 'down') : ''}
      ${f.weak.length ? goRow('opponent', 'Điểm yếu của họ', f.weak.slice(0, 3).map(esc).join(' · ')) : ''}</div>`;

  // your side
  const lineup = `<div class="card"><h3>Đội hình đề xuất · ${esc(md.plan ? md.plan.shape : '')}</h3>${pitchXI(md.best, false, md.captain)}
      <div class="sub wrap" style="margin-top:8px">Theo sơ đồ trong Game Plan: OVR ở đúng vị trí, mũi tên phong độ, điểm 3 trận gần nhất và thể lực; người chấn thương bị loại. © đội trưởng.</div></div>
    <div class="card"><h3>Thay đổi so với Game Plan</h3>
      ${swaps.map(c => `<div class="row tap" data-pid="${c.in}"><div class="grow"><span class="nm"><span class="up">▲ ${esc(c.in_name)}</span></span>
        <div class="sub"><span class="down">▼ ${esc(c.out_name)}</span> · ${c.role}</div><div class="sub wrap">${esc(c.why)}</div></div><span class="chev">›</span></div>`).join('')}
      ${moves.map(c => `<div class="row tap" data-pid="${c.id}"><div class="grow"><span class="nm">⇄ ${esc(c.name)}</span><div class="sub">${c.from} → <b>${c.role}</b></div>
        <div class="sub wrap">${esc(c.why)}</div></div><span class="chev">›</span></div>`).join('')}
      ${md.changes.length ? '' : '<div class="note">Đội hình trong Game Plan đã là phương án tốt nhất.</div>'}
      <div class="note">Trong game: Chiến thuật trước trận → <b>Thay đổi đội hình</b>. Lưu game sau khi đổi, Dugout đọc lại và kiểm tra.</div></div>`;
  const keep = T.rows.filter(r => !r.change);
  const tactics = `<div class="card"><h3>Chiến thuật nên đổi</h3>
      ${tacRows.map(r => `<div class="row"><div class="grow"><b>${esc(r.label)}</b><div class="sub wrap">${esc(r.now ?? '—')} → <b class="up">${esc(r.rec)}</b></div>
        ${r.why ? `<div class="sub wrap">${esc(r.why)}</div>` : ''}</div></div>`).join('') || '<div class="note">Không cần đổi mục nào.</div>'}
      ${keep.length ? `<details><summary>Giữ nguyên (${keep.length} mục)</summary>${keep.map(r => `<div class="kv"><span>${esc(r.label)}</span><b>${esc(r.rec ?? r.now ?? '—')}</b></div>`).join('')}</details>` : ''}</div>
    <div class="card"><h3>Hướng dẫn nâng cao</h3>
      ${T.instructions.map(x => `<div class="row"><span class="ic ${x.have ? 'mut' : 'up'}">${x.have ? '✓' : '＋'}</span><div class="grow"><b>${esc(x.text)}</b> <small class="mut">${esc(x.kind)}</small>
        <div class="sub wrap">${esc(x.why)}</div></div><small class="${x.have ? 'mut' : 'up'}">${x.have ? 'đang dùng' : 'nên thêm'}</small></div>`).join('')}
      ${instrDel.map(x => `<div class="row"><span class="ic down">✕</span><div class="grow"><b>${esc(x.text)}</b><div class="sub wrap">${esc(x.why)}</div></div><small class="down">nên bỏ</small></div>`).join('')}
      ${!T.instructions.length && !instrDel.length ? '<div class="sub">Không có đề xuất.</div>' : ''}
      <div class="note">Đang dùng: ${T.current_instructions.map(x => esc(x.text)).join(', ') || 'không có'}.</div></div>
    ${SP.length ? `<div class="card"><h3>Người đá phạt</h3>${SP.map(r => `<div class="row tap" data-pid="${r.rec.id}"><div class="grow"><b>${esc(r.label)}</b>
        <div class="sub wrap">${r.change ? `<span class="down">${esc((r.cur || {}).name || '')}</span> → <b class="up">${esc(r.rec.name)}</b>` : `<b>${esc(r.rec.name)}</b> ✓ giữ`}</div>
        <div class="sub wrap">${esc(r.rec.why)}</div>${r.note ? `<div class="sub wrap warn">${esc(r.note)}</div>` : ''}</div></div>`).join('')}
      ${md.aerial && md.aerial.length ? `<div class="sub wrap">Điểm đến bóng bổng: ${md.aerial.map(a => `${esc(a.name)} (${a.height} cm)`).join(', ')}</div>` : ''}</div>` : ''}
    <div class="note">Trong game: Chiến thuật trước trận → <b>Chiến thuật của Đội</b>, <b>Hướng dẫn nâng cao</b>, <b>Chọn Cầu thủ Đá Phạt</b>.</div>`;

  // the opponent
  const n = (f.opp_results || []).length || 1;
  const gf = (f.opp_results || []).reduce((a, r) => a + r.gf, 0), ga = (f.opp_results || []).reduce((a, r) => a + r.ga, 0);
  const opponent = `<div class="card"><h3>Đội hình dự kiến · ${esc(f.opp_shape || '')}</h3>${pitchXI(f.opp_xi, true, null, true)}
      <div class="sub wrap" style="margin-top:8px">${f.opp_source === 'gameplan' ? 'Từ Game Plan hiện tại của họ trong save (họ tấn công xuống dưới). Game có thể đổi người sát giờ đá.' : 'Không đọc được Game Plan của họ: dùng đội hình trận gần nhất.'}${f.opp_manager ? ` HLV ${esc(f.opp_manager)}.` : ''}
      ${f.opp_xi.filter(p => p.replaces).map(p => `<br>🩹 ${esc(p.replaces)} chấn thương → ${esc(p.name)}`).join('')}</div></div>
    <div class="card"><h3>Phong độ</h3>
      ${(f.opp_results || []).map(r => `<div class="kv"><span>${shortDate(r.date)} ${r.home ? 'vs' : '@'} ${esc(shortTeam(r.opp_name))}</span><b>${res(r.outcome)} ${r.gf}–${r.ga}</b></div>`).join('')}
      <div class="kv"><span>Ghi / thủng mỗi trận</span><b>${num((gf / n).toFixed(1))} / ${num((ga / n).toFixed(1))}</b></div>
      ${f.pos_opp ? `<div class="kv"><span>Bảng xếp hạng</span><b>hạng ${f.pos_opp.pos} · ${f.pos_opp.pts} điểm</b></div>` : ''}</div>
    <div class="card"><h3>Cầu thủ nguy hiểm</h3>${f.threats.map(threat).join('') || '<div class="sub">—</div>'}</div>
    <div class="card"><h3>Điểm yếu có thể khai thác</h3>${f.weak.map(w => `<div class="row"><span class="ic">•</span><div class="grow wrap">${esc(w)}</div></div>`).join('') || '<div class="sub">Không thấy điểm yếu rõ rệt.</div>'}</div>
    ${f.opp_plan ? `<div class="card"><h3>Game Plan của họ</h3>${f.opp_plan.rows.map(r => `<div class="kv"><span>${esc(r.label)}</span><b>${esc(r.text)}</b></div>`).join('')}
      <div class="kv"><span>Hướng dẫn nâng cao</span><b>${f.opp_plan.instructions.map(x => esc(x.text)).join(', ') || 'không có'}</b></div>${phaseBox(f.opp_phases)}</div>` : ''}
    ${(f.opp_set_pieces || []).length ? `<div class="card"><h3>Người đá phạt của họ</h3>${f.opp_set_pieces.map(t => `<div class="row tap" data-pid="${t.id}"><div class="grow"><b>${esc(t.label)}</b>
      <div class="sub wrap">${esc(t.name)} · ${esc(t.why)}</div></div></div>`).join('')}</div>` : ''}`;

  // duels: their attacker against your defender
  const duel = x => `<div class="card"><h3>${esc(x.label)} <span class="tag ${x.level === 'cao' ? 'inj' : x.level === 'vừa' ? 'y' : ''}">nguy hiểm ${esc(x.level)}</span></h3>
      <div class="row tap" data-pid="${x.att.id}"><span class="sn opp">⚔</span><div class="grow"><span class="nm">${esc(x.att.name)} ${arrow(x.att.cond)}</span><div class="sub">${esc(them)} tấn công · ${x.att.role}</div></div></div>
      <div class="row tap" data-pid="${x.def.id}"><span class="sn me">🛡</span><div class="grow"><span class="nm">${esc(x.def.name)} ${arrow(x.def.cond)}</span><div class="sub">Bạn phòng ngự · ${x.def.role}</div></div></div>
      <div class="sub wrap">${x.notes.map(esc).join(' · ')}</div>${x.tip ? `<div class="note">→ ${esc(x.tip)}</div>` : ''}</div>`;

  // form and how you play
  const PLAN = {start: 'Đá chính', bench: 'Dự bị', out: 'Ngoài'};
  const formRows = md.form.map(r => `<div class="row tap" data-pid="${r.id}">${face(r.id)}<div class="grow"><span class="nm">${esc(r.name)}${r.rec ? ' <small class="up">✓ AI chọn</small>' : ''}</span>
      <div class="sub">${r.pos} · OVR ${r.ovr} · thể lực ${r.stamina}% · ${PLAN[r.plan] || ''}${r.min14 ? ` · ${r.min14}' /14 ngày` : ''}</div>
      <div class="chipline">${(r.last10 || r.last || []).slice(-5).map(rtc).join('')}${r.inj ? ` <span class="tag inj">🩹 ${r.inj} ngày</span>` : ''}</div></div>
      <div class="end">${arrow(r.cond)}<div class="sub">TB ${num(r.avg10 ?? r.avg ?? '—')}</div></div></div>`).join('');
  const st = md.style || {};
  const types = st.types_scored ? Object.entries(st.types_scored) : [], conc = st.types_conceded ? Object.entries(st.types_conceded) : [];
  const sumT = types.reduce((a, [, v]) => a + v, 0) || 1, sumC = conc.reduce((a, [, v]) => a + v, 0) || 1;
  const bars = (arr, sum, cls) => arr.map(([k, v]) => `<div class="abil"><span>${TYPE_VI[k] || k}</span><b>${v}</b>${bar(v, sum, cls)}</div>`).join('');
  const styleCard = types.length ? `<div class="card"><h3>Cách đội bạn chơi mùa này <span class="more">${st.matches || ''} trận</span></h3>
      ${st.areas ? `<div class="kv"><span>Khu vực tấn công</span><b>Trái ${st.areas[0]}% · Giữa ${st.areas[1]}% · Phải ${st.areas[2]}%</b></div>` : ''}
      <div class="grid2" style="margin-top:8px"><div><div class="sub">Ghi bàn từ</div>${bars(types, sumT, '')}</div><div><div class="sub">Thủng lưới từ</div>${bars(conc, sumC, 'low')}</div></div>
      ${st.times_scored ? `<div class="sub" style="margin-top:10px">Ghi / thủng theo từng 15 phút</div><div class="periods">${['0–15', '16–30', '31–45', '46–60', '61–75', '76–90'].map((l, k) =>
        `<div><b class="up">${st.times_scored[k]}</b>/<b class="down">${st.times_conceded[k]}</b><small>${l}'</small></div>`).join('')}</div>` : ''}
      ${st.periods_note ? `<div class="note">${esc(st.periods_note)}</div>` : ''}
      ${(st.rankings || []).length ? `<div class="sub wrap" style="margin-top:8px">Dẫn đầu đội: ${st.rankings.map(r => `${esc(r.label)} <b>${esc(r.name)}</b> (${r.value}${r.rate ? ', ' + r.rate + '%' : ''})`).join(' · ')}</div>` : ''}
      ${phaseBox(md.plan_phases)}</div>` : '';

  const bodies = {overview, lineup, tactics, opponent, duels: f.matchups.map(duel).join('') || '<div class="empty">Không có đối đầu đáng chú ý.</div>',
    form: `<div class="card"><h3>Phong độ hôm nay <span class="more">điểm 5 trận gần nhất</span></h3>${formRows}</div>${styleCard}`};
  return pick + hero + nav + bodies[sec];
}

// ------------------------------------------------------------------ a played match (sheet)
function findMatch(key) {
  const b = S.bundle;
  return b.matches.find(x => x.key === key) || (b.home.recent || []).find(x => x.key === key)
    || b.archive.flatMap(s => s.matches || []).find(x => x.key === key);
}
function openMatch(key) {
  const m = findMatch(key);
  if (!m || !m.played) return toast('Trận này chưa có dữ liệu.');
  const me = S.bundle.club.id;
  openSheet({type: 'match', key, side: m.away === me ? 'away' : 'home',
    title: `${shortTeam(m.home_name)} ${m.hg}–${m.ag} ${shortTeam(m.away_name)}`, sub: `${m.comp_name || ''} · ${m.round || ''} · ${vnDate(m.date)}`,
    draw: e => matchSheet(findMatch(key) || m, e)});
}
function matchSheet(m, e) {
  const own = {};
  for (const o of [...((m.og || {}).home || []), ...((m.og || {}).away || [])]) if (o.id) own[o.id] = (own[o.id] || 0) + 1;
  const side = e.side === 'away' ? m.away_players : m.home_players;
  const rows = (side || []).filter(p => p.min || p.start).sort((a, b) => (b.start - a.start) || (b.min - a.min)).map(p => `<div class="row tap" data-pid="${p.id}">
      ${face(p.id, 'sm')}<div class="grow"><span class="nm">${p.start ? '' : '<small class="up">▲</small> '}${esc(p.name)}</span>
      <div class="sub">${POS[p.pos] || ''} · ${p.min}'${p.g ? ' · ' + '⚽'.repeat(Math.min(p.g, 4)) : ''}${own[p.id] ? ' · <span class="og">⚽ phản lưới</span>' : ''}${p.a ? ` · 🅰${p.a > 1 ? p.a : ''}` : ''}${p.y ? ' · 🟨' : ''}${p.r ? ' · 🟥' : ''}</div></div>
      <div class="end">${p.rating ? rtc(rt(p)) : ''}</div></div>`).join('');
  return `<div class="card">${heroTeams(m, `<b>${m.hg}–${m.ag}</b>${m.pens ? `<small>luân lưu ${m.pens[0]}–${m.pens[1]}</small>` : ''}`)}${scorers(m)}</div>
    <div class="chips">${[['home', m.home_name], ['away', m.away_name]].map(([k, nm]) => `<button class="chip ${e.side === k ? 'on' : ''}" data-sheet-set="side:${k}">${esc(shortTeam(nm))}</button>`).join('')}</div>
    <div class="card">${rows || '<div class="empty">Không có đội hình.</div>'}</div><div class="sub" style="margin:0 4px">Điểm theo thang 10 của Dugout · ▲ vào sân từ ghế dự bị.</div>`;
}

// ------------------------------------------------------------------ more
function vMore() {
  return `<div class="menu">${MORE.map(([k, ic, t, sub]) => `<button data-sub="${k}"><i>${ic}</i><b>${t}</b><small>${sub}</small></button>`).join('')}</div>
    <div class="note">Sửa save (vị trí, phong cách, chân thuận…) chỉ làm trên máy tính, để không bấm nhầm trên điện thoại.</div>`;
}
function fxRow(m, me, nextId) {
  const sc = m.played ? `<div class="sc">${m.hg}–${m.ag}</div>` : `<div class="sc up">${m.hour != null ? m.hour + ':00' : 'vs'}</div>`;
  const mdIdx = !m.played && S.bundle.matchday ? (S.bundle.matchday.fixtures || []).findIndex(f => f.key === m.key) : -1;
  const act = m.played && (m.home_players || []).length ? `class="fx tap" data-match="${esc(m.key)}"` : mdIdx >= 0 ? `class="fx tap" data-gofx="${mdIdx}"` : 'class="fx"';
  return `<div ${act}${nextId ? ' id="fx-next"' : ''}><div class="when"><span>${weekday(m.date)} ${shortDate(m.date)}${m.comp_name ? ' · ' + esc(m.comp_name) : ''}${m.round ? ' · ' + esc(m.round) : ''}</span>${m.outcome && me ? res(m.outcome) : ''}</div>
    <div class="h"><span class="${m.home === me ? 'me' : ''}">${esc(shortTeam(m.home_name))}</span>${crest(m.home, m.home_name)}</div>${sc}
    <div class="a">${crest(m.away, m.away_name)}<span class="${m.away === me ? 'me' : ''}">${esc(shortTeam(m.away_name))}</span></div></div>`;
}
function vFixtures() {
  const b = S.bundle, me = b.club.id;
  const tabs = [['list', 'Lịch & kết quả'], ['rounds', 'Các vòng đấu'], ['archive', 'Mùa trước']];
  let body = '';
  if (S.fixTab === 'rounds') {
    const comps = b.comps.filter(c => c.rounds && c.rounds.length);
    const comp = comps.find(c => c.id === S.fixComp) || comps[0];
    if (comp) {
      let cur = comp.rounds.find(r => r.label === S.fixRound);
      if (!cur) cur = comp.rounds.find(r => r.matches.some(m => m.hg == null)) || comp.rounds[comp.rounds.length - 1];
      body = `${comps.length > 1 ? `<div class="chips">${comps.map(c => `<button class="chip ${c === comp ? 'on' : ''}" data-set="fixComp:${c.id}">${esc(c.name)}</button>`).join('')}</div>` : ''}
        <select data-setsel="fixRound">${comp.rounds.map(r => `<option ${r === cur ? 'selected' : ''}>${esc(r.label)}</option>`).join('')}</select>
        <div class="card" style="margin-top:10px">${cur.matches.map(m => fxRow({...m, comp_name: '', round: ''}, me)).join('')}</div>`;
    } else body = '<div class="empty">Chưa có vòng đấu.</div>';
  } else if (S.fixTab === 'archive') {
    body = b.archive.length ? b.archive.map(s => `<div class="month">Mùa ${esc(s.season)} · ${s.record.w}T ${s.record.d}H ${s.record.l}B · ${s.record.gf}–${s.record.ga}</div>
      <div class="card">${s.matches.map(m => fxRow(m, me)).join('')}</div>`).join('')
      : '<div class="empty">Dugout lưu lại mọi trận đã đá. Các mùa trước hiện ở đây khi sang mùa mới.</div>';
  } else {
    let month = '', chunk = [], next = false;
    const out = [];
    const flush = () => { if (chunk.length) out.push(`<div class="month">Tháng ${Number(month.slice(5))}/${month.slice(0, 4)}</div><div class="card">${chunk.join('')}</div>`); chunk = []; };
    for (const m of b.matches) {
      const mm = m.date.slice(0, 7);
      if (mm !== month) { flush(); month = mm; }
      const isNext = !m.played && !next;
      if (isNext) next = true;
      chunk.push(fxRow(m, me, isNext));
    }
    flush();
    const r = b.home.record;
    body = `<div class="note" style="margin-top:0">Mùa này: ${r.w} thắng · ${r.d} hòa · ${r.l} thua · ${r.gf}–${r.ga}. Chạm một trận đã đá để xem đội hình, người ghi bàn và điểm.</div>`
      + (out.join('') || '<div class="empty">Chưa có lịch thi đấu.</div>');
    if (!S.fxScrolled) {
      S.fxScrolled = true;
      S.after = page => { const el = page.querySelector('#fx-next'); if (el) page.scrollTop = Math.max(0, el.offsetTop - 140); };
    }
  }
  return `<div class="chips">${tabs.map(([k, l]) => `<button class="chip ${S.fixTab === k ? 'on' : ''}" data-set="fixTab:${k}">${l}</button>`).join('')}</div>${body}`;
}
function vTable() {
  const b = S.bundle, me = b.club.id;
  return b.comps.filter(c => (c.table || []).length || c.ties).map(c => (c.table || []).length ? `<div class="card"><h3>${esc(c.name)}</h3>
      <table class="t"><thead><tr><th>#</th><th>Đội</th><th>Tr</th><th>T-H-B</th><th>HS</th><th>Đ</th></tr></thead><tbody>
      ${c.table.map(t => `<tr class="${t.team === me ? 'me' : ''}"><td>${t.pos}</td><td>${crest(t.team, t.name)} ${esc(shortTeam(t.name))}</td><td>${t.p}</td>
        <td><small>${t.w}-${t.d}-${t.l}</small></td><td>${t.gf - t.ga > 0 ? '+' : ''}${t.gf - t.ga}</td><td><b>${t.pts}</b></td></tr>`).join('')}</tbody></table></div>`
    : `<div class="card"><h3>${esc(c.name)}</h3>${(c.ties || []).map(t => {
        const w = k => t.complete && t.winner === t.ids[k] ? 'up' : '';
        return `<div class="row"><div class="grow"><div class="sub">${esc(t.stage)}</div><span class="nm"><span class="${w(0)}">${esc(shortTeam(t.teams[0]))}</span>
          <small class="mut">–</small> <span class="${w(1)}">${esc(shortTeam(t.teams[1]))}</span></span></div><b>${t.agg ? t.agg.join('–') : ''}</b></div>`;
      }).join('') || '<div class="empty">Chưa có cặp đấu.</div>'}</div>`).join('')
    || '<div class="empty">Chưa có bảng xếp hạng.</div>';
}
function vScorers() {
  const b = S.bundle, me = b.club.id, comps = b.comps.filter(c => (c.scorers || []).length);
  if (!comps.length) return '<div class="empty">Chưa có dữ liệu.</div>';
  const c = comps.find(x => x.id === S.scComp) || comps[0];
  const list = rows => rows.map(r => `<div class="row tap" data-pid="${r.id}"><span class="rank">${r.rank}</span>${face(r.id, 'sm')}
    <div class="grow"><span class="nm">${esc(r.name)}</span><div class="sub">${crest(r.team, r.team_name)} ${esc(shortTeam(r.team_name))}</div></div><b class="${r.team === me ? 'up' : ''}">${r.n}</b></div>`).join('');
  return `${comps.length > 1 ? `<div class="chips">${comps.map(x => `<button class="chip ${x === c ? 'on' : ''}" data-set="scComp:${x.id}">${esc(x.name)}</button>`).join('')}</div>` : ''}
    <div class="card"><h3>⚽ Ghi bàn</h3>${list(c.scorers)}</div><div class="card"><h3>🅰 Kiến tạo</h3>${list(c.assists || [])}</div>`;
}

// a player in a list: face, name, position and age, form and OVR (→ the AI's ceiling)
function pRow(p, o = {}) {
  const stats = o.stats ? `${p.apps ?? 0} trận · ${p.goals || 0} bàn · ${p.assists || 0} KT${p.rating ? ' · điểm ' + num((p.rating10 ?? p.rating).toFixed(1)) : ''}` : '';
  const live = S.live && S.live.values && S.live.values[p.id] ? ' · ' + money(S.live.values[p.id]) : '';
  return `<div class="row tap" data-pid="${p.id}"${o.tab ? ` data-ptab="${o.tab}"` : ''}>${face(p.id)}<div class="grow">
      <span class="nm">${esc(p.name)}${p.shirt ? ` <small class="mut">#${p.shirt}</small>` : ''}</span>
      <div class="sub">${p.pos}${p.played && p.played !== p.pos ? '→' + p.played : ''} · ${p.age} tuổi${o.team && p.team_name ? ' · ' + esc(shortTeam(p.team_name)) : ''}${o.contract && p.c_end ? ` · hết HĐ ${Number(String(p.c_end).slice(4, 6))}/${String(p.c_end).slice(0, 4)}` : ''}${live}</div>
      ${stats ? `<div class="sub">${stats}</div>` : ''}${tags(p) ? `<div class="chipline">${tags(p)}</div>` : ''}</div>
    <div class="end">${arrow(p.cond)} ${ovr(p.ovr)}<div class="sub">${p.peak > p.ovr ? '→ ' + p.peak : ''}</div></div></div>`;
}
function vSquad() {
  const b = S.bundle, f = S.squadFilter, md = b.matchday;
  const views = [['list', 'Danh sách'], ['plan', 'Game Plan'], ['pitch', 'Trận gần nhất']];
  let body;
  if (S.squadView === 'plan' && md && md.current && md.current.length) {
    body = `<div class="card"><h3>Game Plan hiện tại · ${esc(md.plan ? md.plan.shape : '')}</h3>${pitchXI(md.current, false, md.captain)}</div>
      <div class="card"><h3>Dự bị (${md.plan_bench.length})</h3>${md.plan_bench.map(p => `<div class="row tap" data-pid="${p.id}">${face(p.id, 'sm')}<div class="grow"><span class="nm">${esc(p.name)}</span>
        <div class="sub">${p.role} · OVR ${p.ovr}</div></div><div class="end">${arrow(p.cond)} ${(p.last10 || p.last || []).slice(-3).map(rtc).join('')}</div></div>`).join('')}</div>
      ${md.plan ? `<div class="card"><h3>Chiến thuật đang đặt</h3>${md.plan.rows.map(r => `<div class="kv"><span>${esc(r.label)}</span><b>${esc(r.text)}</b></div>`).join('')}
        <div class="kv"><span>Hướng dẫn nâng cao</span><b>${md.plan.instructions.map(x => esc(x.text)).join(', ') || 'không có'}</b></div></div>` : ''}`;
  } else if (S.squadView === 'pitch' && b.lineup) {
    const L = b.lineup, starters = L.players.filter(p => p.start), used = {};
    const pp = starters.map(p => {
      const key = p.pos_name || 'CMF', k = (used[key] = (used[key] || 0) + 1), same = starters.filter(q => (q.pos_name || 'CMF') === key).length;
      let [x, y] = SPOT[key] || [50, 50];
      if (same > 1) x = x + (k - (same + 1) / 2) * (['CB', 'CMF', 'DMF', 'CF'].includes(key) ? 24 : 12);
      x = Math.max(10, Math.min(90, x));
      return `<div class="pp tap" style="left:${x}%;top:${y}%" data-pid="${p.id}"><img src="/face/${p.id}.png" onerror="this.style.visibility='hidden'">
        <span class="n">${esc(lastWord(p.name))}</span><span class="p">${p.pos_name} ${p.rating ? '· ' + rt(p) : ''}${p.g ? ' ⚽' + (p.g > 1 ? p.g : '') : ''}</span></div>`;
    }).join('');
    body = `<div class="card"><h3>${esc(L.comp)} · gặp ${esc(shortTeam(L.opp))} · ${L.score}</h3><div class="sub">${vnDate(L.date)}</div><div class="pitch">${pp}</div></div>
      <div class="card"><h3>Dự bị</h3>${L.players.filter(p => !p.start).map(p => `<div class="row tap" data-pid="${p.id}">${face(p.id, 'sm')}<div class="grow"><span class="nm">${esc(p.name)}</span>
        <div class="sub">${p.min ? p.min + "' vào sân" : 'không vào sân'}</div></div><div class="end">${p.rating ? rtc(rt(p)) : ''}</div></div>`).join('')}</div>`;
  } else {
    let list = b.squad;
    if (f === 'advice') list = list.filter(p => p.advice_n || p.training_n);
    else if (f === 'inj') list = list.filter(p => p.inj);
    else if (f === 'young') list = list.filter(p => p.age <= 21);
    else if (f === 'form') list = list.filter(p => p.cond >= 3).sort((a, c) => c.cond - a.cond || c.ovr - a.ovr);
    const nAdv = b.squad.filter(p => p.advice_n || p.training_n).length, nForm = b.squad.filter(p => p.cond >= 3).length, nInj = b.squad.filter(p => p.inj).length;
    body = `<div class="chips" data-anchor>${[['all', `Tất cả ${b.squad.length}`], ['advice', `💡 Gợi ý ${nAdv}`], ['form', `Phong độ A/B ${nForm}`], ['inj', `Chấn thương ${nInj}`], ['young', 'U21']]
      .map(([k, l]) => `<button class="chip ${f === k ? 'on' : ''}" data-set="squadFilter:${k}">${l}</button>`).join('')}</div>
      <div class="card">${list.map(p => pRow(p, {stats: true, tab: f === 'advice' ? 'dev' : ''})).join('') || '<div class="empty">Không có cầu thủ nào.</div>'}</div>`;
  }
  return `<div class="chips">${views.map(([k, l]) => `<button class="chip ${S.squadView === k ? 'on' : ''}" data-set="squadView:${k}">${l}</button>`).join('')}</div>${body}`;
}

// ------------------------------------------------------------------ market
function vMarket() {
  const m = S.bundle.market;
  const tabs = [['plan', '📋 Kế hoạch hè'], ['search', '🔎 Tìm'], ['prospects', `Tài năng trẻ ${m.prospects.length}`], ['expiring', `Hết HĐ ${(m.expiring || []).length}`],
    ['free', 'Tự do'], ['listed', 'Đàm phán'], ['deals', 'Thỏa thuận'], ['needs', 'Đội cần gì']];
  let body = '';
  const t = S.marketTab;
  if (t === 'plan') {
    body = S.plan ? planHtml(S.plan) : '<div id="plan-box"><div class="empty"><span class="spin"></span>Đang lập kế hoạch…</div></div>';
    if (!S.plan) S.after = () => loadPlan();
  } else if (t === 'search') {
    const q = S.mq || {};
    const opt = (list, cur) => list.map(([v, l]) => `<option value="${v}" ${String(cur ?? '') === String(v) ? 'selected' : ''}>${l}</option>`).join('');
    body = `<form id="mk-form" class="card form">
      <label>Tên cầu thủ<input name="q" placeholder="Nhập tên" value="${esc(q.q || '')}"></label>
      <div class="grid2"><label>Vị trí<select name="pos">${opt([['', 'Tất cả'], ...POS.map(p => [p, p])], q.pos)}</select></label>
        <label>Phạm vi<select name="scope">${opt([['all', 'Tất cả'], ['others', 'Đội khác'], ['free', 'Tự do'], ['mine', 'Đội của tôi']], q.scope)}</select></label></div>
      <div class="grid2"><label>Tuổi từ<input name="age_min" type="number" inputmode="numeric" min="15" max="45" value="${esc(q.age_min || '')}"></label>
        <label>đến<input name="age_max" type="number" inputmode="numeric" min="15" max="45" value="${esc(q.age_max || '')}"></label></div>
      <div class="grid2"><label>OVR ≥<input name="min_ovr" type="number" inputmode="numeric" value="${esc(q.min_ovr || '')}"></label>
        <label>Ngưỡng ≥<input name="min_peak" type="number" inputmode="numeric" value="${esc(q.min_peak || '')}"></label></div>
      <div class="grid2"><label>Phong cách<select name="style">${opt([['', 'Bất kỳ'], ...STYLES.map((s, i) => [i + 1, s])], q.style)}</select></label>
        <label>Kỹ năng<select name="skill">${opt([['', 'Bất kỳ'], ...SKILLS.map((s, i) => [i, s])], q.skill)}</select></label></div>
      <label>Sắp xếp<select name="sort">${opt([['peak', 'Ngưỡng cao nhất'], ['growth', 'Còn tăng nhiều nhất'], ['ovr', 'OVR hiện tại'], ['young', 'Trẻ nhất'], ['pace', 'Vượt dự đoán nhiều nhất'], ['fit', 'Hợp vị trí đã chọn']], q.sort)}</select></label>
      <label class="check"><input type="checkbox" name="regen" value="1" ${q.regen ? 'checked' : ''}> Chỉ regen</label>
      <button class="primary wide" type="submit">Tìm</button></form>
      <div id="mk-result">${S.marketResult ? searchHtml(S.marketResult) : ''}</div>`;
  } else if (t === 'needs') {
    body = needsHtml(m.squad_comp);
  } else if (t === 'deals') {
    const st = {pending: 'Đang chờ', accepted: 'Đã chấp nhận', completed: 'Hoàn tất', rejected: 'Bị từ chối'};
    body = m.agreements.length ? `<div class="card">${m.agreements.map(a => `<div class="row tap" data-pid="${a.id}">${face(a.id)}<div class="grow"><span class="nm">${esc(a.player)}</span>
        <div class="sub">${a.kind === 'loan' ? 'Cho mượn' : 'Chuyển nhượng'} · ${esc(shortTeam(a.seller))} → ${esc(shortTeam(a.buyer))}</div></div>
        <div class="end"><b>${money(a.fee)}</b><div class="sub">${st[a.state] || esc(a.state)}</div></div></div>`).join('')}</div>`
      : '<div class="empty">Không có thỏa thuận nào đang diễn ra.</div>';
  } else {
    const list = {prospects: m.prospects, expiring: m.expiring || [], free: m.free, listed: m.listed}[t] || [];
    const hint = {expiring: 'Cầu thủ đội khác hết hợp đồng cuối mùa này: có thể đàm phán để ký tự do mùa sau.', listed: 'Danh sách đàm phán / theo dõi của CLB trong game.',
      prospects: 'Cầu thủ trẻ có ngưỡng AI dự đoán cao nhất thế giới.', free: 'Cầu thủ không có CLB.'}[t];
    body = `${hint ? `<div class="note" style="margin-top:0">${hint}</div>` : ''}<div class="card">${list.map(p => pRow(p, {team: true, tab: 'age', contract: t === 'expiring'})).join('') || '<div class="empty">Không có cầu thủ nào.</div>'}</div>`;
  }
  return `<div class="chips">${tabs.map(([k, l]) => `<button class="chip ${t === k ? 'on' : ''}" data-set="marketTab:${k}">${l}</button>`).join('')}</div>${body}`;
}
const searchHtml = r => `<div class="sec">${r.total} cầu thủ phù hợp${r.total > r.players.length ? ` · hiện ${r.players.length} đầu tiên` : ''}</div>
  <div class="card">${r.players.map(p => pRow(p, {team: true, tab: 'age'})).join('') || '<div class="empty">Không có ai.</div>'}</div>`;
async function runSearch(form) {
  const q = Object.fromEntries(new FormData(form).entries());
  S.mq = q;
  const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v !== '')).toString();
  const box = $('#mk-result');
  if (box) box.innerHTML = '<div class="empty"><span class="spin"></span>Đang tìm…</div>';
  try { S.marketResult = await api('/api/search?' + qs); } catch (e) { if (box) box.innerHTML = '<div class="empty">Chưa tìm được (máy tính chưa kết nối?)</div>'; return; }
  const b2 = $('#mk-result');
  if (b2) { b2.innerHTML = searchHtml(S.marketResult); b2.scrollIntoView({behavior: 'smooth', block: 'start'}); }
}
async function loadPlan() {
  try { S.plan = await api('/api/plan'); } catch (e) {
    const box = $('#plan-box');
    if (box) box.innerHTML = '<div class="empty">Chưa lập được kế hoạch (Dugout đang đọc save).</div>';
    return;
  }
  if (S.tab === 'more' && S.sub === 'market' && S.marketTab === 'plan') draw(false);
}
function planRow(x, kind) {
  const club = x.team ? esc(shortTeam(x.team_name)) : 'tự do';
  const extra = kind === 'target' ? `${club}${x.contract ? ' · HĐ ' + esc(x.contract) : ''}${(x.tags || []).length ? ' · ' + x.tags.map(esc).join(', ') : ''}`
    : kind === 'renew' ? `${esc(x.why)} · HĐ ${esc(x.contract)} · lương ${money(x.salary)}`
    : kind === 'letgo' ? `${esc(x.why)} · HĐ ${esc(x.contract)}` : esc(x.why || '');
  const end = kind === 'target' ? `<b>${x.fee ? money(x.fee) : '<span class="up">tự do</span>'}</b><div class="sub up">+${num(x.gain)}</div>`
    : kind === 'sell' || kind === 'letgo' ? `<b>${money(x.value)}${x.value_real ? '' : '<small class="mut">*</small>'}</b><div class="sub">${esc(x.action || '')}</div>`
    : x.action ? `<small><b>${esc(x.action)}</b></small>` : '';
  return `<div class="row tap" data-pid="${x.id}" data-ptab="age">${face(x.id, 'sm')}<div class="grow"><span class="nm">${esc(x.name)}</span>
    <div class="sub">${x.pos} · ${x.age}t · OVR ${x.ovr} → ${Math.round(x.next)} · ngưỡng ${x.peak}</div><div class="sub wrap">${extra}</div></div><div class="end">${end}</div></div>`;
}
const planList = (list, kind) => list && list.length ? list.map(x => planRow(x, kind)).join('') : '<div class="sub">Không có.</div>';
function planHtml(p) {
  const b = p.budget, t = p.totals, vd = iso => vnDate(iso);
  let out = `<div class="card"><h3>Kỳ chuyển nhượng hè</h3>
    <div class="kv"><span>Thời gian</span><b>${vd(p.window[0])} – ${vd(p.window[1])}${p.days_to_window > 0 ? ` <small class="mut">(còn ${p.days_to_window} ngày)</small>` : ' · đang mở'}</b></div>
    <div class="kv"><span>Ngân sách chuyển nhượng</span><b>${b ? money(b.transfer) : '<small class="mut">mở game để Dugout đọc</small>'}</b></div>
    <div class="kv"><span>Ngân sách lương · quỹ lương</span><b>${b ? money(b.salary) : '—'} · ${money(p.payroll)}/năm</b></div>
    <div class="kv"><span>Đội hình</span><b>${p.composition.squad_size || '?'} người · còn ${p.composition.free_slots ?? '?'} chỗ</b></div>
    <div class="kv"><span>Tiền bán dự kiến</span><b>${money(t.sell_income)}</b></div>
    <div class="kv"><span>Chi cho lựa chọn đáng tiền</span><b>${money(t.first_choice_spend)}${t.balance != null ? ` · <span class="${t.balance >= 0 ? 'up' : 'down'}">còn ${money(t.balance)}</span>` : ''}</b></div>
    <div class="sub wrap">Giá cầu thủ: ${esc(p.values_source)}${p.fitted ? ' (đã hiệu chỉnh theo giá game)' : ''}. <small>* ước tính</small></div></div>`;
  out += p.needs.length ? p.needs.map((g, k) => `<div class="card"><h3>${k + 1}. ${esc(g.label)}</h3>${g.notes.length ? `<div class="sub wrap warn">${g.notes.map(esc).join(' · ')}</div>` : ''}
      <div class="sub wrap">Hiện có: ${g.players.slice(0, 4).map(x => `${esc(x.name)} ${Math.round(x.next)}`).join(', ') || 'không ai'}</div>
      <div class="sec">${g.succession ? 'Người kế cận trẻ' : 'Mạnh nhất'}${b ? ' trong ngân sách' : ''}</div>${planList(g.targets.best, 'target')}
      <div class="sec">Đáng tiền nhất</div>${planList(g.targets.value, 'target')}</div>`).join('')
    : '<div class="card"><h3>Tuyến cần tăng cường</h3><div class="sub">Đội hình mùa sau không có tuyến nào thiếu hay yếu rõ rệt.</div></div>';
  out += `<div class="card"><h3>Nên bán / cho mượn</h3>${planList(p.sell, 'sell')}</div>`;
  out += `<div class="card"><h3>Hợp đồng và người ra đi</h3>
    ${p.leaving.length ? `<div class="sec">Ra đi chắc chắn</div>${planList(p.leaving, 'leave')}` : ''}
    ${p.renew.length ? `<div class="sec">Nên gia hạn</div>${planList(p.renew, 'renew')}` : ''}
    ${p.let_go.length ? `<div class="sec">Hết hợp đồng, không cần giữ</div>${planList(p.let_go, 'letgo')}` : ''}
    ${!p.leaving.length && !p.renew.length && !p.let_go.length ? '<div class="sub">Không ai hết hợp đồng, giải nghệ hay hết hạn mượn trong hè này.</div>' : ''}</div>`;
  if (p.promote.length) out += `<div class="card"><h3>Đôn từ đội trẻ</h3>${planList(p.promote, 'promote')}</div>`;
  out += `<div class="card"><h3>Đội hình mùa sau theo tuyến</h3>${p.groups.map(g => `<div class="row"><div class="grow"><b>${esc(g.label)}</b> <small class="mut">${g.starters_needed} đá chính · TB ${g.start_avg ?? '—'}${g.league_top3 != null ? ' · top 3 giải ' + g.league_top3 : ''}</small>
      <div class="sub wrap">${g.players.slice(0, 4).map(x => `${esc(x.name)} ${Math.round(x.next)}`).join(', ')}</div>${g.notes.length ? `<div class="sub wrap warn">${g.notes.map(esc).join('; ')}</div>` : ''}</div></div>`).join('')}</div>`;
  return out;
}
function needsHtml(sc) {
  const b = S.bundle, sq = b.squad, d = new Date(b.date), endYear = d.getMonth() < 6 ? d.getFullYear() : d.getFullYear() + 1;
  const groups = [['Thủ môn', ['GK'], 2], ['Trung vệ', ['CB'], 4], ['Hậu vệ biên', ['LB', 'RB'], 4], ['Tiền vệ phòng ngự', ['DMF'], 2],
    ['Tiền vệ trung tâm', ['CMF', 'LMF', 'RMF'], 3], ['Tiền vệ tấn công', ['AMF'], 2], ['Tiền đạo cánh', ['LWF', 'RWF'], 4], ['Tiền đạo', ['CF', 'SS'], 3]];
  return `<div class="note" style="margin-top:0">Số cầu thủ theo vị trí so với mức tối thiểu cho một mùa nhiều giải.${sc ? ` Đội có ${sc.squad_size} cầu thủ, còn ${sc.free_slots} chỗ.` : ''}</div>
    <div class="card">${groups.map(([label, pos, need]) => {
      const ps = sq.filter(p => pos.includes(p.pos)).sort((a, c) => c.ovr - a.ovr), best = ps[0], notes = [];
      if (ps.length < need) notes.push(`thiếu ${need - ps.length} người`);
      if (best && best.age >= 31) notes.push(`người tốt nhất đã ${best.age} tuổi`);
      const exp = ps.filter(p => p.contract && p.contract[0] <= endYear);
      if (exp.length) notes.push(`${exp.length} người hết HĐ cuối mùa`);
      return `<div class="row"><div class="grow"><b>${label}</b> <small class="${ps.length < need ? 'down' : 'mut'}">${ps.length}/${need}</small>
        <div class="sub wrap">${ps.slice(0, 4).map(p => `${esc(p.name)} ${p.ovr}${p.peak > p.ovr ? '→' + p.peak : ''}`).join(', ')}</div>${notes.length ? `<div class="sub wrap warn">${notes.join('; ')}</div>` : ''}</div>
        ${notes.length ? `<button class="mini" data-needpos="${pos[0]}">Tìm ${pos[0]}</button>` : ''}</div>`;
    }).join('')}</div>`;
}

function vYouth() {
  const y = S.bundle.youth;
  const tabs = [['youth', `Đội trẻ ${y.youth.length}`], ['regens', `Regen thế giới ${y.regens.length}`]];
  const body = S.youthTab === 'youth'
    ? `<div class="note" style="margin-top:0">Ngưỡng AI giúp chọn ai nên đôn lên đội một.</div><div class="card">${y.youth.map(p => pRow(p, {tab: p.advice_n || p.training_n ? 'dev' : ''})).join('') || '<div class="empty">Không có.</div>'}</div>`
    : `<div class="note" style="margin-top:0">Cầu thủ giải nghệ quay lại ở tuổi 16 cùng tên, chỉ số mới; AI dự đoán lại từ đầu.</div><div class="card">${y.regens.slice(0, 120).map(p => pRow(p, {team: true, tab: 'age'})).join('')}</div>`;
  return `<div class="chips">${tabs.map(([k, l]) => `<button class="chip ${S.youthTab === k ? 'on' : ''}" data-set="youthTab:${k}">${l}</button>`).join('')}</div>${body}`;
}

function vAi() {
  const b = S.bundle, a = b.ai, r = a.report || {}, s = S.status || {};
  const pct = v => v == null ? '—' : (v * 100).toFixed(1).replace('.', ',') + '%';
  const m = a.match_model, P = a.predictions || {rows: [], cond: []};
  const h = s.health || {}, bk = s.backup || {};
  const icon = {ok: '✓', warn: '!', error: '✗', info: 'i'};
  const checks = [...(h.files || []).map(f => ({level: 'info', text: `${f.text} (${f.when})`})), ...(h.items || [])];
  const posAcc = r.positions ? Object.values(r.positions).reduce((x, v) => x + v.auc, 0) / Object.keys(r.positions).length : null;
  const ovrMae = r.ovr ? Object.values(r.ovr).reduce((x, v) => x + v.mae * v.samples, 0) / Object.values(r.ovr).reduce((x, v) => x + v.samples, 0) : null;
  return `<div class="grid2">
      <div class="stat"><b>${a.snapshots}</b><small>lần lưu game đã ghi${a.first_snapshot ? ` từ ${vnDate(a.first_snapshot)}` : ''}</small></div>
      <div class="stat"><b>${a.learned.toLocaleString('vi')}</b><small>cầu thủ đã học tốc độ riêng</small></div>
      <div class="stat"><b>${m ? pct(m.accuracy) : '—'}</b><small>đoán đúng kết quả${m ? ` (${m.test} trận gần nhất)` : ''}</small></div>
      <div class="stat"><b>${P.n ? `${P.hits}/${P.n}` : '—'}</b><small>dự đoán trận của bạn đúng</small></div></div>
    <div class="card" style="margin-top:12px"><h3>Đối chiếu sau trận</h3>
      ${P.rows.length ? P.rows.slice(0, 10).map(x => `<div class="row"><span class="ic ${x.hit ? 'up' : 'down'}">${x.hit ? '✓' : '✗'}</span><div class="grow"><span class="nm">${x.venue === 'home' ? 'vs' : '@'} ${esc(shortTeam(x.opp))}</span>
        <div class="sub">${vnDate(x.date)} · AI: T${x.pred.w} H${x.pred.d} B${x.pred.l}</div></div><div class="end">${res(x.result)} <b>${x.score[0]}–${x.score[1]}</b></div></div>`).join('')
        : '<div class="sub">Dugout lưu dự đoán trước mỗi trận và đối chiếu khi bạn lưu game sau trận.</div>'}</div>
    ${P.cond.length ? `<div class="card"><h3>Điểm trung bình theo mũi tên phong độ</h3>${P.cond.map(c => `<div class="kv"><span>${arrow('EDCBA'.indexOf(c.arrow))} ${c.arrow}</span><b>${num(c.avg)} <small class="mut">(${c.n} lượt)</small></b></div>`).join('')}</div>` : ''}
    <div class="card"><h3>So với dự đoán ban đầu</h3>${b.home.growers.map(x => `<div class="row tap" data-pid="${x.id}">${face(x.id, 'sm')}<div class="grow"><span class="nm">${esc(x.name)}</span><div class="sub">${x.pos} · ${x.age} tuổi</div></div>
        <b class="${x.pace >= 0 ? 'up' : 'down'}">${x.pace > 0 ? '+' : ''}${num(x.pace)}</b></div>`).join('') || '<div class="sub">AI cần thêm vài lần lưu game.</div>'}
      <div class="sub wrap">OVR thực tế so với dự đoán ban đầu, đã trừ mức chung của cầu thủ cùng tuổi.</div></div>
    <div class="card"><h3>Kiểm tra dữ liệu <span class="more">${esc(h.at || '')}</span></h3>${checks.map(i => `<div class="row"><span class="ic ${i.level === 'ok' ? 'up' : i.level === 'error' ? 'down' : 'warn'}">${icon[i.level] || '·'}</span><div class="grow wrap">${esc(i.text)}</div></div>`).join('') || '<div class="sub">Chưa đọc save lần nào.</div>'}</div>
    <div class="card"><h3>Sao lưu</h3>
      <div class="kv"><span>Bản save đã sao lưu</span><b>${(bk.saves || 0).toLocaleString('vi')}</b></div>
      <div class="kv"><span>Dung lượng</span><b>${bk.mb != null ? num(bk.mb) + ' MB' : '—'}</b></div>
      <div class="kv"><span>Lần gần nhất</span><b>${esc(bk.last || 'chưa có')}</b></div>
      ${bk.error ? `<div class="sub wrap down">${esc(bk.error)}</div>` : ''}
      <button class="wide" data-act="backup">Sao lưu ngay</button></div>
    <div class="card"><h3>Các mô hình</h3>
      <div class="kv"><span>OVR theo vị trí (sai số)</span><b>${ovrMae != null ? num(ovrMae.toFixed(2)) + ' điểm' : '—'}</b></div>
      <div class="kv"><span>Hợp vị trí (AUC)</span><b>${posAcc ? num(posAcc.toFixed(3)) : '—'}</b></div>
      <div class="kv"><span>Phong cách: đúng ngay / trong 3</span><b>${pct((r.styles || {}).top1)} / ${pct((r.styles || {}).top3)}</b></div>
      <div class="kv"><span>41 kỹ năng (AUC)</span><b>${(r.skills || {}).mean_auc ? num(r.skills.mean_auc.toFixed(3)) : '—'}</b></div>
      <div class="kv"><span>Học từ</span><b>${m ? m.matches.toLocaleString('vi') + ' trận' : '—'}</b></div>
      <div class="kv"><span>Huấn luyện lúc</span><b>${esc((r.trained_at || '').replace('T', ' '))}</b></div>
      <button class="wide" data-act="train">Huấn luyện lại AI</button><div class="sub wrap">Nên chạy khi sang mùa mới.</div></div>`;
}

function vConn() {
  const b = S.bundle, s = S.status || {}, sv = s.save || {}, lv = s.live || {};
  const mins = sv.age != null ? Math.floor(sv.age / 60) : null;
  const age = mins == null ? '—' : mins < 1 ? 'vừa xong' : mins < 60 ? `${mins} phút trước` : `${Math.floor(mins / 60)} giờ ${mins % 60} phút trước`;
  const state = S.connErr ? 'Mất kết nối' : s.offline ? 'Máy tính chưa kết nối' : {ready: 'Đã đồng bộ', syncing: 'Đang đọc save', starting: 'Đang khởi động', training: 'Đang huấn luyện AI', error: 'Lỗi'}[s.state] || s.state || '—';
  return `<div class="card"><h3><span class="dot ${dotState()}"></span> ${esc(state)}</h3><div class="sub wrap">${esc(s.message || '')}</div></div>
    <div class="card"><h3>Save</h3>
      <div class="kv"><span>Câu lạc bộ</span><b>${esc(b.club.name)}</b></div>
      <div class="kv"><span>Ngày trong game</span><b>${esc(b.date_vi)}</b></div>
      <div class="kv"><span>Game ghi save</span><b>${age}</b></div>
      <div class="kv"><span>Game đang mở</span><b>${sv.game_on ? 'Có' : 'Không'}</b></div>
      <div class="kv"><span>File save</span><b>${esc(b.save_name)}</b></div>
      <div class="kv"><span>Đọc trực tiếp từ game</span><b>${esc(lv.text || (lv.budget ? 'đang đọc' : 'khi game mở'))}</b></div>
      <button class="wide" data-act="reload">↻ Đọc lại save ngay</button></div>
    <div class="card"><h3>App điện thoại</h3>
      <div class="sub wrap">Dữ liệu lấy từ Dugout trên máy tính. Khi máy tính tắt, app vẫn mở và hiện dữ liệu lần đồng bộ cuối; bản đồ trực tiếp chỉ có khi máy tính đang chạy.
      Sửa save chỉ làm trên máy tính.</div>
      <div class="kv"><span>Dữ liệu tạo lúc</span><b>${esc((b.built || '').replace('T', ' '))}</b></div>
      <div class="kv"><span>Phiên bản</span><b>${esc(S.build || s.build || '—')}</b></div>
      <button class="wide" data-act="appreload">Tải lại app</button>
      <a class="wide btn" href="/index.html">Mở giao diện đầy đủ (như máy tính)</a></div>`;
}

// ------------------------------------------------------------------ a player (sheet)
async function openPlayer(pid, tab) {
  pid = Number(pid);
  const e = {type: 'player', pid, ptab: tab || 'overview', title: 'Cầu thủ',
    draw: x => x.d ? playerHtml(x.d, x) : x.err ? `<div class="empty">${x.err}</div>` : '<div class="empty"><span class="spin"></span>Đang tải…</div>'};
  e.d = S.bundle.details[pid];
  if (e.d) e.title = e.d.name;
  openSheet(e);
  if (e.d) return;
  try { e.d = await api('/api/player/' + pid); e.title = e.d.name; } catch (err) { e.err = 'Không tìm thấy cầu thủ (máy tính chưa kết nối?).'; }
  if (e.el.isConnected) fillSheet(e);
}
function playerHtml(d, e) {
  const nAdv = d.advice ? d.advice.count : 0, nTr = d.advice ? (d.advice.training || []).length : 0;
  const tabs = [['overview', 'Tổng quan'], ['dev', `Phát triển${nAdv ? ' 💡' + nAdv : ''}${nTr ? ' ⏳' + nTr : ''}`], ['stats', 'Chỉ số'], ['age', 'Theo tuổi'],
    ['matches', `Trận${d.matches.length ? ' ' + d.matches.length : ''}`], ['similar', 'Tương tự']];
  const body = ({overview: pOverview, dev: pDev, stats: pStats, age: pAge, matches: pMatches, similar: pSimilar}[e.ptab] || pOverview)(d);
  return `<div class="phead">${face(d.id, 'xl')}<div style="min-width:0"><h2>${esc(d.name)}</h2>
      <div class="sub">${d.pos} · ${POS_VI[d.pos]}${d.played && d.played !== d.pos ? ` (đang đá ${d.played})` : ''}</div>
      <div class="sub">${d.age} tuổi · ${esc(d.nation)} · ${d.height} cm · chân ${String(d.foot || '').toLowerCase()}</div>
      <div class="sub">${crest(d.team, d.team_name)} ${esc(shortTeam(d.team_name))}${d.shirt ? ` · số ${d.shirt}` : ''}</div>
      ${tags(d) ? `<div class="chipline">${tags(d)}</div>` : ''}</div></div>
    <div class="pbig"><div>Phong độ<b>${d.cond >= 0 ? arrow(d.cond) : '—'}</b></div><div>OVR<b>${ovr(d.ovr)}</b></div>
      <div>Ngưỡng AI<b>${ovr(d.peak)}</b><small>${d.peak_low}–${d.peak_high}</small></div><div>Chạm ngưỡng<b>${d.reach_age <= d.age ? 'đã chạm' : d.reach_age + 't'}</b></div></div>
    <div class="chips sticky" style="margin-top:12px">${tabs.map(([k, l]) => `<button class="chip ${e.ptab === k ? 'on' : ''}" data-sheet-set="ptab:${k}">${l}</button>`).join('')}</div>${body}`;
}
function growthChart(d) {
  const W = 360, H = 210, L = 28, R = 8, T = 12, B = 24;
  const now = new Date(S.bundle.date + 'T00:00:00');
  const hist = (d.history || []).map(h => ({t: (new Date(h.date + 'T00:00:00') - now) / 3.15576e10, v: h.ovr}));
  const proj = d.projection.filter(p => p.age - d.age <= 12);
  if (!proj.length) return '';
  const t0 = Math.min(0, ...hist.map(h => h.t)), t1 = Math.max(1, ...proj.map(p => p.age - d.age));
  const vals = [...hist.map(h => h.v), ...proj.flatMap(p => [p.low, p.high])];
  const v0 = Math.max(40, Math.floor((Math.min(...vals) - 2) / 5) * 5), v1 = Math.min(100, Math.ceil((Math.max(...vals) + 2) / 5) * 5);
  const X = t => L + (t - t0) / (t1 - t0) * (W - L - R), Y = v => T + (v1 - v) / (v1 - v0) * (H - T - B);
  let g = '';
  for (let v = v0; v <= v1; v += 5) g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#243041"/><text x="${L - 5}" y="${Y(v) + 4}" fill="#8a97a8" font-size="10" text-anchor="end">${v}</text>`;
  const step = (t1 - t0) > 8 ? 2 : 1;
  for (let a = Math.ceil(d.age + t0); a <= d.age + t1; a += step) g += `<text x="${X(a - d.age)}" y="${H - 7}" fill="#8a97a8" font-size="10" text-anchor="middle">${a}t</text>`;
  g += `<line x1="${X(0)}" x2="${X(0)}" y1="${T}" y2="${H - B}" stroke="#5d6a7b" stroke-dasharray="3 3"/>`;
  const band = proj.map(p => `${X(p.age - d.age)},${Y(p.high)}`).join(' ') + ' ' + proj.slice().reverse().map(p => `${X(p.age - d.age)},${Y(p.low)}`).join(' ');
  g += `<polygon points="${band}" fill="rgba(34,197,94,.18)"/><polyline points="${proj.map(p => `${X(p.age - d.age)},${Y(p.ovr)}`).join(' ')}" fill="none" stroke="#22c55e" stroke-width="2.5"/>`;
  const pk = proj.reduce((a, c) => c.ovr > a.ovr ? c : a, proj[0]);
  g += `<circle cx="${X(pk.age - d.age)}" cy="${Y(pk.ovr)}" r="4" fill="#eab308"/><text x="${Math.min(W - 30, X(pk.age - d.age))}" y="${Y(pk.ovr) - 8}" fill="#eab308" font-size="11" text-anchor="middle">đỉnh ${Math.round(pk.ovr)}</text>`;
  if (hist.length) g += `<polyline points="${hist.map(h => `${X(h.t)},${Y(h.v)}`).join(' ')} ${X(0)},${Y(d.ovr)}" fill="none" stroke="#38bdf8" stroke-width="2"/>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${g}</svg>`;
}
function pOverview(d) {
  const ce = d.c_end ? String(d.c_end) : '';
  const contract = d.contract ? `${d.contract[2]}/${d.contract[1]}/${d.contract[0]}` : ce ? `${Number(ce.slice(6))}/${Number(ce.slice(4, 6))}/${ce.slice(0, 4)}` : '';
  const ob = d.observed || {};
  const kv = (k, v) => v ? `<div class="kv"><span>${k}</span><b>${v}</b></div>` : '';
  const pos = d.positions.slice().sort((a, b) => b.fit - a.fit);
  return `<div class="card"><h3>Phát triển: đã qua và dự đoán</h3>${growthChart(d)}
      <div class="legend"><span><i style="background:#38bdf8"></i>Đã ghi lại</span><span><i style="background:#22c55e"></i>AI dự đoán</span><span><i style="background:rgba(34,197,94,.3)"></i>Khoảng 80%</span></div></div>
    <div class="card"><h3>Tóm tắt</h3>
      ${kv('Xu hướng', trendTxt(d))}
      ${kv('Ngưỡng dự đoán', `${d.peak} ở ${d.peak_age} tuổi <small class="mut">(${d.peak_low}–${d.peak_high})</small>`)}
      ${kv('Tốc độ riêng AI học', d.learned ? `<span class="${d.pace_ovr >= 0 ? 'up' : 'down'}">${d.pace_ovr > 0 ? '+' : ''}${num(d.pace_ovr)} OVR/năm</span>` : 'chưa đủ dữ liệu')}
      ${d.vs_pred != null ? kv('So với dự đoán ban đầu', `<span class="${d.pace >= 0 ? 'up' : 'down'}">${d.vs_pred > 0 ? '+' : ''}${num(d.vs_pred)}</span> <small class="mut">(cùng tuổi ${d.vs_pred_cohort > 0 ? '+' : ''}${num(d.vs_pred_cohort)})</small>`) : ''}
      ${d.apps != null ? kv('Mùa này', `${d.apps} trận · ${d.goals || 0} bàn · ${d.assists || 0} KT${d.rating ? ' · ' + num((d.rating10 ?? d.rating).toFixed(2)) + '/10' : ''}`) : ''}
      ${kv('Phong cách', esc(d.style_label || 'Không có'))}
      ${kv('Hợp đồng đến', contract)}${kv('Lương năm', d.salary || d.wage ? money(d.salary || d.wage) : '')}
      ${kv('Giá trị (đọc từ game)', S.live && S.live.values && S.live.values[d.id] ? money(S.live.values[d.id]) : '')}
      ${kv('Phí giải phóng', d.clause ? money(d.clause) : '')}
      ${d.wf && d.wf[1] ? kv('Chân không thuận', `${d.wf[0]}/4 · ${d.wf[1]}/4`) : ''}
      ${ob.n ? kv(`Phong độ ghi lại (${ob.n} lần)`, `${ob.good} lần A/B · ${ob.bad} lần D/E`) + kv('Chấn thương ghi lại', ob.injuries ? `${ob.injuries} lần, lâu nhất ${ob.worst_days} ngày` : 'chưa lần nào') : ''}
      ${kv('Kỹ năng', String(d.skills.length))}</div>
    <div class="card"><h3>Độ hợp 13 vị trí <span class="more">chữ: hạng · số: độ hợp AI</span></h3>
      <div class="posgrid">${pos.map(p => `<div class="${p.grade}" style="background:${p.fit >= 80 ? '#14532d' : p.fit >= 60 ? '#365314' : p.fit >= 40 ? '#422006' : 'var(--panel2)'}"><b>${p.pos}</b>${p.grade} · ${p.fit}<br><small class="mut">OVR ${p.ovr}</small></div>`).join('')}</div></div>
    ${d.editable ? '<div class="note">Sửa save cho cầu thủ này (vị trí, phong cách, chân thuận): mở trên máy tính.</div>' : ''}`;
}
function pDev(d) {
  const a = d.advice;
  if (!a) return '<div class="empty">Không có dữ liệu.</div>';
  const src = t => t.source === 'dugout' ? 'Dugout' : 'trong game';
  const training = (a.training || []).map(t => {
    if (t.kind === 'style') return `<div class="card"><h3>⏳ Phong cách: ${esc(t.from || 'không có')} → ${esc(t.to)}</h3><div class="sub wrap">${src(t)} · AI chấm hợp ${t.fit_to}% · ${esc(t.note)}</div></div>`;
    if (t.kind === 'skill') return `<div class="card"><h3>⏳ Kỹ năng: ${esc(t.skill)}</h3><div class="abil"><span>Tiến độ (${src(t)})</span><b>${t.pct}%</b>${bar(t.pct, 100, 'mid')}</div></div>`;
    return `<div class="card"><h3>⏳ Vị trí ${t.position}: hạng ${t.grade} → ${t.next}</h3><div class="abil"><span>Tiến độ${t.eta != null ? ` · còn ~${Math.max(1, Math.round(t.eta / 7))} tuần` : ''}</span><b>${t.pct}%</b>${bar(t.pct, 100)}</div></div>`;
  }).join('');
  const sug = a.suggestions.map(s => {
    if (s.kind === 'style') return `<div class="card"><h3>🔄 Nên đổi phong cách</h3>
      <div class="abil"><span>${esc(s.from || 'Hiện tại: không có')}</span><b>${s.fit_from}%</b>${bar(s.fit_from, 100, 'mid')}</div>
      <div class="abil"><span><b>→ ${esc(s.to)}</b></span><b>${s.fit_to}%</b>${bar(s.fit_to, 100)}</div>
      ${s.why.length ? `<div class="sub wrap">Hợp vì: ${s.why.map(esc).join(', ')}</div>` : ''}<div class="note">${esc(s.how)}</div></div>`;
    if (s.kind === 'skill') return `<div class="card"><h3>✨ Nên tập: ${esc(s.skill)} <span class="more">hợp ${s.fit}%</span></h3>
      <div class="chipline">${s.need.map(n => `<span class="tag ${n.value >= n.min ? 'ok' : 'inj'}">${esc(n.ability)} ${n.value}/${n.typical}</span>`).join('')}</div>
      <div class="sub wrap">${s.ready ? 'Chỉ số đã đủ, có thể tập ngay.' : 'Nên tăng các chỉ số màu đỏ trước.'}</div><div class="note">${esc(s.how)}</div></div>`;
    return `<div class="card"><h3>🧭 Nên luyện vị trí: ${s.position}</h3><div class="sub">${esc(s.position_vi)} · hạng ${s.grade} · độ hợp ${s.fit} · OVR ${s.ovr}</div><div class="note">${esc(s.how)}</div></div>`;
  }).join('') || (training ? '' : '<div class="note">Chưa có gợi ý: phong cách và kỹ năng đang hợp với chỉ số.</div>');
  return `${training}${sug}<div class="card"><h3>Phong cách hợp nhất khi đá ${a.pos}</h3>${a.styles.map(s => `<div class="abil"><span>${s.current ? '● ' : ''}${esc(s.label)}</span><b>${s.fit}%</b>${bar(s.fit, 100, s.current ? 'mid' : '')}</div>`).join('')}</div>
    <div class="card"><h3>Nên ưu tiên khi tập</h3><div class="chipline">${(a.focus || []).map(f => `<span class="tag">${esc(f.ability)} ${f.value}</span>`).join('') || '<span class="sub">—</span>'}</div>
      <div class="sec">Kỹ năng đang có (${d.skills.length})</div><div class="chipline">${d.skills.map(s => `<span class="tag">${esc(s)}</span>`).join('') || '<span class="sub">Chưa có</span>'}</div>
      ${d.com.length ? `<div class="sec">Phong cách MÁY</div><div class="chipline">${d.com.map(s => `<span class="tag">${esc(s)}</span>`).join('')}</div>` : ''}</div>`;
}
function pStats(d) {
  const start = d.abilities_start, gk = d.pos === 'GK';
  const col = v => v >= 90 ? '#a855f7' : v >= 80 ? '#ef4444' : v >= 75 ? '#f97316' : v >= 70 ? '#eab308' : v >= 60 ? '#22c55e' : '#64748b';
  return GROUPS.filter(([n]) => gk || n !== 'Thủ môn').map(([name, keys]) => `<div class="card"><h3>${name}</h3>${keys.map(k => {
    const v = d.abilities[k], s0 = start ? start[k] : null, dv = s0 != null ? v - s0 : 0;
    return `<div class="abil"><span>${AB[k]}${dv ? ` <small class="${dv > 0 ? 'up' : 'down'}">${dv > 0 ? '+' : ''}${dv}</small>` : ''}</span><b>${v}</b>
      <div class="bar"><i style="width:${Math.max(0, Math.min(100, (v - 40) / 59 * 100))}%;background:${col(v)}"></i></div></div>`;
  }).join('')}</div>`).join('') + (start ? `<div class="sub" style="margin:0 4px">Số nhỏ: thay đổi so với ${esc(d.start_label)}.</div>` : '');
}
function pAge(d) {
  const rows = d.by_age, peak = rows.reduce((a, b) => b.ovr > a.ovr ? b : a, rows[0]);
  let cmp = '';
  const mine = S.bundle.squad.filter(p => p.pos === d.pos && p.id !== d.id).sort((a, b) => b.ovr - a.ovr)[0];
  if (mine && d.team !== S.bundle.club.id) {
    const over = rows.find(r => r.ovr >= mine.ovr);
    cmp = `<div class="note" style="margin-top:0">${d.pos} tốt nhất của bạn: <b>${esc(mine.name)}</b> (OVR ${mine.ovr}, ngưỡng ${mine.peak}). ${over ? (over.age === d.age ? `${esc(d.name)} đã ngang hoặc hơn ngay bây giờ.`
      : `${esc(d.name)} dự kiến vượt mức ${mine.ovr} năm ${over.year} (${over.age} tuổi).`) : `${esc(d.name)} khó vượt mức ${mine.ovr}.`}</div>`;
  }
  return `${cmp}<div class="card">${rows.map(r => `<div class="row"><div class="grow"><span class="nm">${r.age} tuổi <small class="mut">· ${r.year}</small>${r === peak ? ' <small class="gold">đỉnh</small>' : r.age === d.age ? ' <small class="mut">hiện tại</small>' : ''}</span>
      <div class="sub">tốt nhất ${r.best_pos} ${r.best_ovr} · khoảng ${Math.round(r.low)}–${Math.round(r.high)}</div></div><div class="end">${ovr(Math.round(r.ovr))}</div></div>`).join('')}</div>
    <div class="sub wrap" style="margin:0 4px">Đường cong tuổi của AI cộng tốc độ riêng của cầu thủ (${d.learned ? 'đã học' : 'chưa đủ dữ liệu'}). Khoảng 80%: 8/10 trường hợp rơi vào đây.</div>`;
}
function pMatches(d) {
  if (!d.matches.length) return '<div class="empty">Chưa có trận nào cho CLB của bạn mùa này.</div>';
  return `<div class="card">${d.matches.map(m => `<div class="row"><div class="grow"><span class="nm">${m.venue === 'home' ? 'vs' : '@'} ${esc(shortTeam(m.opp))}</span>
    <div class="sub">${vnDate(m.date)} · ${esc(m.comp)} · ${m.min}'${m.g ? ' · ⚽' + (m.g > 1 ? m.g : '') : ''}${m.a ? ' · 🅰' + (m.a > 1 ? m.a : '') : ''}</div></div>
    <div class="end">${res(m.outcome)} <b>${m.score}</b><div>${rtc(m.r10 ?? m.rating)}</div></div></div>`).join('')}</div>`;
}
function pSimilar(d) {
  return `<div class="note" style="margin-top:0">Bộ chỉ số gần giống nhất trong cùng nhóm vị trí.</div><div class="card">${(d.similar || []).map(p => pRow(p, {team: true})).join('') || '<div class="empty">—</div>'}</div>`;
}

// ------------------------------------------------------------------ live
const PITCH_SVG = `<svg class="lvpitch" viewBox="-56 -37.5 112 75" preserveAspectRatio="xMidYMid meet">
  <rect x="-56" y="-37.5" width="112" height="75" class="grass"/>
  ${[...Array(10)].map((_, i) => `<rect x="${-52.5 + i * 10.5}" y="-34" width="10.5" height="68" class="${i % 2 ? 'stripe' : 'stripe2'}"/>`).join('')}
  <g class="lines">
    <rect x="-52.5" y="-34" width="105" height="68"/>
    <line x1="0" y1="-34" x2="0" y2="34"/><circle r="9.15"/><circle r="0.35" class="spot"/>
    <rect x="-52.5" y="-20.16" width="16.5" height="40.32"/><rect x="36" y="-20.16" width="16.5" height="40.32"/>
    <rect x="-52.5" y="-9.16" width="5.5" height="18.32"/><rect x="47" y="-9.16" width="5.5" height="18.32"/>
    <circle cx="-41.5" r="0.35" class="spot"/><circle cx="41.5" r="0.35" class="spot"/>
    <path d="M -36 -7.3 A 9.15 9.15 0 0 1 -36 7.3"/><path d="M 36 -7.3 A 9.15 9.15 0 0 0 36 7.3"/>
    <rect x="-54.5" y="-3.66" width="2" height="7.32" class="goal"/><rect x="52.5" y="-3.66" width="2" height="7.32" class="goal"/>
  </g>
  <g id="lv-dots"></g>
</svg>`;
const LV_TABS = [['tl', 'Diễn biến'], ['fit', 'Thể lực'], ['stats', 'Số liệu'], ['pre', 'Trước trận']];
const LAND_Q = matchMedia('(orientation: landscape) and (max-height: 540px)');
const PORTRAIT_Q = matchMedia('(orientation: portrait)');

function drawLiveShell() {
  const page = $('#page');
  if (!page.querySelector('.lvpitch')) {
    page.innerHTML = `<div class="lvhead" id="lv-head"></div>
      <div class="map" id="lv-map"><div class="fullui fmini" id="lv-mini"></div><div class="fullui fsubs" id="lv-fsubs"></div>
        <div class="fullui fwhy" id="lv-fwhy"></div><button class="fullui fx-x" data-full="0" aria-label="Thoát xem ngang">✕</button>
        ${PITCH_SVG}<div class="msg" id="lv-msg"></div></div>
      <div class="lvbar"><span id="lv-carrier"></span><button data-full="1">⛶ Xem ngang</button></div>
      <div id="lv-notice"></div>
      <div class="chips" id="lv-tabs"></div>
      <div id="lv-body"></div>`;
    S.liveDots = {};
    S.lvSig = S.lvBodyHtml = S.lvTabsSig = null;
    page.querySelector('.lvpitch').setAttribute('viewBox', S.full ? FULL_BOX : PITCH_BOX);
    S.lvFrames = [];
    page.scrollTop = 0;
  }
  page.classList.add('is-live');
  lvTabs();
  if (S.liveLast) drawLive(S.liveLast);
  startLive();
}
function lvTabs() {
  const html = LV_TABS.map(([k, l]) => `<button class="chip ${S.lvTab === k ? 'on' : ''}" data-lvtab="${k}">${l}</button>`).join('');
  const el = $('#lv-tabs');
  if (el && html !== S.lvTabsSig) { S.lvTabsSig = html; el.innerHTML = html; }
}
function startLive() {
  if (S.liveOn) return;
  S.liveOn = true;
  const loop = async () => {
    if (S.tab !== 'live' || document.hidden) { S.liveOn = false; return; }
    try {
      // the frames since the last one we have come along (trail); the analysis and the timeline (most of the
      // bytes) about every 1.5 s only (3 s on the sideways map)
      const was = S.liveLast || {};
      const full = was.state !== 'live' || !S.liveSlowAt || Date.now() - S.liveSlowAt > (S.full ? 3000 : 1500);
      const q = [];
      if (S.lvSince) q.push('since=' + S.lvSince);
      if (!full) q.push('lite=1');
      let d = await api('/api/matchlive' + (q.length ? '?' + q.join('&') : ''));
      if (d.lite) d = Object.assign({}, S.liveSlow || {}, d);
      else if (d.state === 'live') {
        S.liveSlow = {ai: d.ai, timeline: d.timeline, tstats: d.tstats, shape: d.shape, identity: d.identity};
        S.liveSlowAt = Date.now();
      }
      if ((d.key || 'idle') !== S.liveInfoKey) {          // a new match (or none): what does not change
        S.liveInfoKey = d.key || 'idle';
        try { S.liveInfo = await api('/api/matchlive/info'); } catch (e) { S.liveInfo = null; }
        S.lvBodyHtml = null;
      }
      S.liveLast = d;
      drawLive(d);
    } catch (e) { drawLive({state: 'error', message: 'Mất kết nối với máy tính.'}); }
    setTimeout(loop, S.remote ? 150 : 110);
  };
  loop();
}
function liveClock(m) {
  if (!m || m.minute == null) return '';
  return `${m.minute}:${String(m.second || 0).padStart(2, '0')}${m.added ? ` +${m.added}'` : ''}`;
}
const lvWho = id => { const p = ((S.liveInfo || {}).people || {})[id]; return p ? `${p.num != null ? `<span class="sn ${p.team}">${p.num}</span> ` : ''}${esc(p.name)}` : ''; };
const lvWhoText = x => x && x.name ? `${x.num != null ? `<span class="sn opp">${x.num}</span> ` : ''}<b>${esc(x.name)}</b>` : '';

function drawLive(d) {
  if (!$('#lv-head')) return;
  const m = d.match, fx = (S.liveInfo || {}).fixture;
  const sig = JSON.stringify([d.state, d.message, m && [m.home.id, m.away.id, m.score, m.pk, m.minute, m.second, m.period, m.paused], !!fx]);
  if (sig !== S.lvSig) {
    S.lvSig = sig;
    $('#lv-head').innerHTML = m ? `<div class="lvsc"><div class="tm ${m.home.me ? 'me' : ''}">${crest(m.home.id, m.home.name)}<span>${esc(shortTeam(m.home.name))}</span></div>
        <div><div class="n">${m.score[0] ?? '-'} – ${m.score[1] ?? '-'}</div><div class="c">${liveClock(m)}</div></div>
        <div class="tm ${m.away.me ? 'me' : ''}"><span>${esc(shortTeam(m.away.name))}</span>${crest(m.away.id, m.away.name)}</div></div>
        <div class="sub" style="text-align:center">${esc(m.period_vi || '')}${m.paused ? ' · tạm dừng' : ''}${m.pk && (m.pk[0] || m.pk[1]) ? ` · luân lưu ${m.pk[0]}–${m.pk[1]}` : ''}${fx ? ' · ' + esc(fx.comp_name || '') : ''}${fx && fx.derby ? ' · DERBY' : ''}</div>`
      : `<b>◉ Trực tiếp</b><div class="sub wrap">Vào trận trong game: trang này tự mở. Bản đồ, nhận định AI, thể lực và gợi ý thay người hiện ngay khi trận bắt đầu.</div>`;
    $('#lv-mini').innerHTML = m ? `${crest(m.home.id, m.home.name)}<b>${m.score[0] ?? '-'}–${m.score[1] ?? '-'}</b>${crest(m.away.id, m.away.name)}<span class="c">${liveClock(m)}</span>${m.paused ? '<small>tạm dừng</small>' : ''}` : '';
    const msg = d.state === 'live' ? '' : d.message || '';
    $('#lv-msg').innerHTML = msg ? `<div>${d.state === 'searching' || d.state === 'loading' ? '<span class="spin"></span>' : ''}${esc(msg)}</div>` : '';
    $('#lv-msg').classList.toggle('show', !!msg);
  }
  drawDots(d);
  if (S.full) { drawFullSubs(d); return; }
  if (Date.now() - (S.lvBodyAt || 0) > 900 || S.lvBodyHtml == null) {
    S.lvBodyAt = Date.now();
    const html = ({tl: lvTl, fit: lvFit, stats: lvStats, pre: lvPre}[S.lvTab] || lvTl)(d);
    if (html !== S.lvBodyHtml) { S.lvBodyHtml = html; $('#lv-body').innerHTML = html; }
  }
}
// on the sideways map, under the score: the last three substitutions, "67' ▲ in ▼ out"
function drawFullSubs(d) {
  const el = $('#lv-fsubs');
  if (!el) return;
  const people = (S.liveInfo || {}).people || {};
  const short = pid => esc(lastWord((people[pid] || people[String(pid)] || {}).name || ''));
  const subs = (d.state === 'live' ? d.timeline || [] : []).filter(i => i.kind === 'sub' && i.inn).sort((a, b) => (a.t ?? 0) - (b.t ?? 0)).slice(-3);
  const html = subs.map(i => `<div><span class="t ${i.team || ''}"></span><span>${esc(i.min || '')}</span><span class="on">▲ ${short(i.inn)}</span><span class="off">▼ ${short(i.out)}</span></div>`).join('');
  if (el.innerHTML !== html) el.innerHTML = html;
}
function drawDots(d) {
  const dots = $('#lv-dots');
  if (!dots) return;
  const cam = d.view || [1, 1], vx = cam[0], vy = cam[1];           // like the game's camera / radar
  const seen = new Set(), pos = {};
  const players = d.state === 'live' ? d.players || [] : [];
  for (const p of players) {
    const key = 'p' + p.k;
    seen.add(key);
    let g = S.liveDots[key];
    if (!g) {
      g = document.createElementNS(SVGNS, 'g');
      g.innerHTML = '<circle class="ring" r="2.5"/><circle class="body" r="1.7"/><text y="0.62"></text>';
      dots.appendChild(g);
      S.liveDots[key] = g;
    }
    g.setAttribute('class', 'pl ' + (p.team || 'unk') + (d.carrier && d.carrier.k === p.k ? ' carrier' : '') + (p.leaving ? ' leaving' : ''));
    g.dataset.k = p.k;
    g.dataset.team = p.team || 'unk';
    pos[key] = [vx * p.x, vy * p.y];
    const t = g.querySelector('text'), label = p.num != null ? String(p.num) : '';
    if (t.textContent !== label) t.textContent = label;
  }
  if (d.state === 'live' && d.ball) {
    seen.add('ball');
    let g = S.liveDots.ball;
    if (!g) {
      g = document.createElementNS(SVGNS, 'g');
      g.innerHTML = '<ellipse class="shadow" rx="0.9" ry="0.5"/><circle r="1"/>';
      dots.appendChild(g);
      S.liveDots.ball = g;
    }
    const bs = d.bstate || {};
    g.setAttribute('class', 'ball ' + (bs.state || ''));
    pos.ball = [vx * d.ball.x, vy * d.ball.y, d.ball.h];
  }
  for (const [k, g] of Object.entries(S.liveDots)) if (!seen.has(k)) { g.remove(); delete S.liveDots[k]; }
  liveBuffer(d, pos);
  // who has the ball; a dead ball: why
  const c = d.state === 'live' ? d.carrier : null, bs = d.state === 'live' ? d.bstate || {} : {};
  const owner = bs.owner ? (d.players || []).find(p => p.id === bs.owner) : null;
  const why = bs.state === 'dead' && bs.why ? `⚽ ${esc(BALL_WHY[bs.why] || 'Bóng chết')}` : '';
  const html = why ? `<span class="why">${why}</span>`
    : c && c.state === 'held' ? `<span class="sn ${c.team}">${c.num ?? ''}</span> <b>${esc(c.name || 'Cầu thủ')}</b> <small class="mut">cầm bóng</small>`
    : bs.guess && owner ? `<span class="sn ${owner.team}">${owner.num ?? ''}</span> <b>${esc(owner.name || 'Cầu thủ')}</b> <small class="mut">giữ bóng</small>`
    : c && c.state === 'air' ? '<small class="mut">⚽ Bóng đang bay</small>' : c ? '<small class="mut">⚽ Bóng tự do</small>'
    : d.state === 'live' && !d.ball ? '<small class="mut">⚽ Đang tìm quả bóng…</small>' : '';
  const cb = $('#lv-carrier');
  if (cb && cb.innerHTML !== html) cb.innerHTML = html;
  const fw = $('#lv-fwhy');
  if (fw && fw.innerHTML !== html) fw.innerHTML = html;
  const nb = $('#lv-notice');
  const nh = d.state === 'live' && (d.notices || []).length ? d.notices.slice(-2).reverse().map(t => `<div class="note">${esc(t)}</div>`).join('') : '';
  if (nb && nb.innerHTML !== nh) nb.innerHTML = nh;
}
// Smooth map: frames kept with the game time they were read at (server clock) and drawn a little behind,
// moving between two frames on every screen refresh; a late frame (phone, internet) does not make the dots jump.
function liveBuffer(d, pos) {
  if (d.state !== 'live' || !d.ts) { S.lvFrames = []; S.lvSince = null; return; }
  const now = performance.now() / 1000;
  const off = d.ts - now;
  S.lvOff = S.lvOff == null || off > S.lvOff ? off : S.lvOff - 0.001;
  const fr = S.lvFrames || (S.lvFrames = []);
  if (fr.length) {
    const L = S.lvLags || (S.lvLags = []);
    L.push(now + S.lvOff - fr[fr.length - 1].ts);
    if (L.length > 40) L.shift();
    const srt = L.slice().sort((x, y) => x - y);
    S.lvTarget = Math.min(2.5, Math.max(S.remote ? 0.3 : 0.15, srt[Math.floor((srt.length - 1) * 0.9)] + 0.08));
  }
  const cam = d.view || [1, 1], vx = cam[0], vy = cam[1];
  for (const [ts, pl, b] of d.trail || []) {
    if (fr.length && fr[fr.length - 1].ts >= ts) continue;
    const p = {};
    for (const [k, x, y] of pl) p['p' + k] = [vx * x, vy * y];
    if (b) p.ball = [vx * b[0], vy * b[1], b[2]];
    fr.push({ts, pos: p});
  }
  if (!fr.length || fr[fr.length - 1].ts < d.ts) fr.push({ts: d.ts, pos});
  S.lvSince = fr[fr.length - 1].ts;
  while (fr.length > 2 && fr[1].ts < d.ts - Math.max(3, (S.lvDelay || 0) + 1)) fr.shift();
  if (!S.lvAnim) { S.lvAnim = true; requestAnimationFrame(liveAnimate); }
}
function liveAnimate() {
  const fr = S.lvFrames || [];
  if (S.tab !== 'live' || !fr.length) { S.lvAnim = false; return; }
  const nowS = performance.now() / 1000 + (S.lvOff || 0);
  if (S.lvDelay == null) S.lvDelay = S.lvTarget || (S.remote ? 0.5 : 0.18);
  if (nowS - S.lvDelay > fr[fr.length - 1].ts) S.lvDelay = Math.min(2.5, S.lvDelay + 0.02);
  else S.lvDelay += ((S.lvTarget || S.lvDelay) - S.lvDelay) * 0.004;
  const tr = nowS - S.lvDelay;
  let a = fr[0], b = fr[fr.length - 1];
  for (let i = 0; i < fr.length - 1; i++) if (fr[i].ts <= tr && fr[i + 1].ts > tr) { a = fr[i]; b = fr[i + 1]; break; }
  if (tr >= b.ts) a = b;
  const f = b.ts > a.ts ? Math.min(1, Math.max(0, (tr - a.ts) / (b.ts - a.ts))) : 1;
  for (const [k, g] of Object.entries(S.liveDots || {})) {
    const p0 = a.pos[k], p1 = b.pos[k] || p0, q = p0 || p1;
    if (!q) continue;
    const x = p0 && p1 ? p0[0] + (p1[0] - p0[0]) * f : q[0], y = p0 && p1 ? p0[1] + (p1[1] - p0[1]) * f : q[1];
    g.style.transform = `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px)`;
    if (k === 'ball') {
      const h = p0 && p1 ? p0[2] + (p1[2] - p0[2]) * f : q[2];
      g.querySelector('circle').style.transform = `translate(0px, ${(-Math.min(6, h * 0.6)).toFixed(2)}px) scale(${(1 + Math.min(0.8, h * 0.06)).toFixed(3)})`;
    }
  }
  requestAnimationFrame(liveAnimate);
}
function lvTl(d) {
  let items = d.state === 'live' ? d.timeline || [] : [], st = d.state === 'live' ? d.tstats : null;
  let feed = d.state === 'live' ? (d.ai || {}).feed || [] : [], title = '';
  if (!d.match && S.liveInfo && S.liveInfo.last) {
    const l = S.liveInfo.last;
    items = (l.timeline || []).slice().reverse();
    feed = l.feed || [];
    st = l.tstats;
    title = `<div class="sec">Trận vừa đá: ${esc(shortTeam(l.home_name))} ${(l.score || [])[0] ?? ''}–${(l.score || [])[1] ?? ''} ${esc(shortTeam(l.away_name))}</div>`;
  }
  const rows = items.map(i => ({t: i.t, ord: 1, html: `<div class="tl ${i.kind === 'goal' || i.goal ? 'goal' : ''} ${i.kind === 'card' ? 'yc' + (i.card === 'red' ? ' red' : '') : ''}">
      <span class="min">${esc(i.min || '')}</span><span>${i.kind === 'card' && i.card === 'red' ? '🟥' : TL_ICON[i.kind] || '•'}</span><span>${esc(i.text)}</span></div>`}))
    .concat(feed.filter(f => f.cat !== 'event').map(f => ({t: f.t, ord: 0, html: `<div class="tl ai"><span class="min">${esc(f.min || '')}</span><span>${FEED_ICON[f.cat] || '•'}</span>
      <span>${esc(f.text)}${f.tip ? `<div class="tip">→ ${esc(f.tip)}</div>` : ''}</span></div>`})));
  rows.sort((x, y) => ((y.t ?? -1) - (x.t ?? -1)) || (y.ord - x.ord));
  if (!rows.length && !st) return d.state === 'live' ? '<div class="empty">AI cần khoảng 1–2 phút thi đấu để có nhận định đầu tiên.</div>' : '';
  const sr = (a, b, l) => `<div class="kv"><b>${a}</b><span class="mut">${l}</span><b>${b}</b></div>`;
  const shots = x => `${x.shots}${x.shots ? ` <small class="mut">(${x.on_target} trúng)</small>` : ''}`;
  return title + (st ? `<div class="card">${sr('Bạn', 'Đối thủ', '')}${sr(st.me.passes, st.opp.passes, 'Chuyền tới đồng đội')}${sr(shots(st.me), shots(st.opp), 'Sút')}${sr(st.me.won, st.opp.won, 'Cướp được bóng')}</div>` : '')
    + (rows.length ? `<div class="card tlcard">${rows.map(r => r.html).join('')}</div>` : '');
}
function lvFit(d) {
  const info = S.liveInfo || {}, people = info.people || {};
  let players = d.state === 'live' ? d.players || [] : [], pre = '', out = '';
  if (d.state !== 'live' && !d.match && info.last && info.last.players) {
    players = Object.values(info.last.players).map(p => ({...p, st: p.stamina}));
    pre = 'Trận vừa đá · ';
  }
  if (d.state === 'live') {
    const ai = d.ai || {};
    out += `<div class="card"><h3>Gợi ý thay người <span class="more">${ai.stamina_source === 'game' ? 'đọc từ game' : 'ước tính theo quãng chạy'}</span></h3>
      ${(ai.subs_now || []).map(s => { const pi = people[s.in] || {}; return `<div class="row"><div class="grow"><div><span class="down">▼</span> ${lvWho(s.out)} <small class="mut">${s.stamina}%</small></div>
        <div><span class="up">▲</span> ${s.in ? `${lvWho(s.in)} <small class="mut">${esc(pi.role || '')}${pi.ovr ? ' · OVR ' + pi.ovr : ''}${pi.arrow ? ' · phong độ ' + pi.arrow : ''}</small>` : '<small class="mut">không có người cùng vị trí trên ghế</small>'}</div></div></div>`; }).join('')
        || '<div class="sub">Chưa ai đuối sức (dưới 65%).</div>'}
      ${(ai.subs || []).filter(s => s.team === 'me').map(s => `<div class="sub">Đã thay: ${lvWho(s.in)} vào, ${lvWho(s.out)} ra</div>`).join('')}</div>`;
  }
  const list = (team, title) => {
    const ps = players.filter(p => p.team === team).sort((a, b) => (a.st ?? 101) - (b.st ?? 101) || (b.dist || 0) - (a.dist || 0));
    if (!ps.length) return '';
    return `<div class="card"><h3>${pre}${title} <span class="more">thể lực · km</span></h3>${ps.map(p => `<div class="row ${p.id ? 'tap' : ''}"${p.id ? ` data-pid="${p.id}"` : ''}>
      <span class="sn ${team}">${p.num ?? ''}</span><div class="grow"><span class="nm">${esc(p.name || 'Cầu thủ')} <small class="mut">${esc(p.pos || p.role || '')}</small></span>
      <div class="bar ${p.st != null && p.st <= 55 ? 'low' : p.st != null && p.st <= 70 ? 'mid' : ''}"><i style="width:${p.st ?? 0}%"></i></div></div>
      <div class="end"><b>${p.st != null ? p.st + '%' : '—'}</b><div class="sub">${((p.dist || 0) / 1000).toFixed(2).replace('.', ',')} km</div></div></div>`).join('')}</div>`;
  };
  return (out + list('me', 'Đội bạn') + list('opp', 'Đối thủ')) || '<div class="empty">Thể lực hiện khi trận đang diễn ra.</div>';
}
function lvStats(d) {
  if (d.state !== 'live') return '<div class="empty">Số liệu hiện khi trận đang diễn ra.</div>';
  const info = S.liveInfo || {}, w = (d.ai || {}).window || {};
  const pos = w.possession != null ? [w.possession, 100 - w.possession] : d.possession;
  const shape = (x, who, planned) => x ? `<div class="row"><div class="grow"><b>${who}</b><div class="sub wrap">${esc(x.shape)}${planned && planned !== x.shape ? ` (dự kiến ${esc(planned)})` : ''} · khối ${esc(x.block)} · hàng thủ cách khung thành ${x.line} m${x.gap != null ? ` · giữa hai tuyến ${x.gap} m` : ''}</div></div></div>` : '';
  return `<div class="card"><h3>Trong trận <span class="more">5 phút gần nhất</span></h3>
    ${pos ? `<div class="kv"><span>Kiểm soát bóng</span><b>${pos[0]}% – ${pos[1]}%</b></div><div class="bar poss"><i style="width:${pos[0]}%"></i></div>` : '<div class="sub">Kiểm soát bóng: cần thấy bóng một lúc.</div>'}
    ${w.territory != null ? `<div class="kv"><span>Bóng ở phần sân đối thủ</span><b>${w.territory}%</b></div>` : ''}
    ${shape(w.me, 'Đội bạn (khi mất bóng)')}${shape(w.opp, 'Đối thủ (khi mất bóng)', (info.prematch || {}).opp_shape)}
    ${!w.me && !w.opp ? '<div class="sub">Sơ đồ thật của hai đội: sau khoảng 1 phút thi đấu.</div>' : ''}</div>`;
}
function lvPre(d) {
  const info = S.liveInfo || {}, pre = info.prematch;
  if (!pre || !Object.keys(pre).length) return `<div class="empty">${d.match ? 'Trận này không có trong lịch Dugout đã phân tích (giao hữu, cúp mới bốc thăm…).' : 'Phân tích trước trận hiện khi trận bắt đầu.'}</div>`;
  const li = h => `<div class="row"><div class="grow wrap">${h}</div></div>`;
  const card = (title, arr, fn) => (arr || []).length ? `<div class="card"><h3>${title}</h3>${arr.map(x => li(fn(x))).join('')}</div>` : '';
  return `${pre.pred ? `<div class="card"><h3>AI dự đoán</h3>${predBar(pre.pred, (info.fixture || {}).venue || 'home')}</div>` : ''}
    ${card('Điểm yếu của đối thủ', pre.weak, w => `${(w.players || (w.name ? [w] : [])).map(lvWhoText).join(', ')}${(w.players || []).length || w.name ? ': ' : ''}${esc(w.text)}`)}
    ${card('Cầu thủ nguy hiểm của họ', pre.threats, t => `${lvWhoText(t)} <small class="mut">${esc(t.role || '')}</small><div class="sub wrap">${esc((t.why || []).join(', '))}</div>`)}
    ${card('Đối đầu từng cánh', pre.matchups, mu => `<b>${esc(mu.label)}</b> <span class="tag">${esc(mu.level || '')}</span><div>${lvWhoText(mu.att)} đấu ${mu.def && mu.def.name ? `<span class="sn me">${mu.def.num ?? ''}</span> <b>${esc(mu.def.name)}</b>` : ''}</div>${mu.tip ? `<div class="tip">→ ${esc(mu.tip)}</div>` : ''}`)}
    ${card('Chiến thuật nên đổi', pre.tactics, t => `<b>${esc(t.label)}</b>: ${esc(t.now || '')} → <b class="up">${esc(t.rec || '')}</b><div class="sub wrap">${esc(t.why || '')}</div>`)}
    ${pre.opp_shape ? `<div class="note">Sơ đồ dự kiến của đối thủ: ${esc(pre.opp_shape)}</div>` : ''}`;
}
// a tap on a dot: who is it? (a newcomer the game has not named yet, or a name the map got wrong)
function whoIs(k, team) {
  const info = S.liveInfo || {}, people = info.people || {}, d = S.liveLast || {};
  const on = new Set((d.players || []).filter(p => p.id).map(p => p.id));
  const dot = (d.players || []).find(p => p.k === k) || {};
  const ids = Object.keys(people).filter(i => team === 'unk' || people[i].team === team)
    .sort((a, b) => (on.has(+b) - on.has(+a)) || ((people[a].role === 'GK') - (people[b].role === 'GK')) || String(people[a].name).localeCompare(people[b].name));
  openSheet({type: 'whois', fixed: true, title: 'Chấm này là ai?', sub: 'Hiện tại: ' + (dot.name || 'chưa biết'),
    draw: () => `<div class="note" style="margin-top:0">Chọn đúng cầu thủ: Dugout đổi tên chấm này (và người đang mang tên đó nếu cần), nhớ cho cả trận.</div>
      <div class="card">${ids.map(i => `<div class="row tap" data-whois="${i}" data-k="${k}"><span class="sn ${people[i].team}">${people[i].num ?? ''}</span>
        <div class="grow"><span class="nm">${esc(people[i].name)}</span><div class="sub">${esc(people[i].role || '')}${on.has(+i) ? ' · đang trên sân' : ''}</div></div></div>`).join('') || '<div class="empty">Chưa có danh sách cầu thủ.</div>'}</div>`});
}

// The map alone on the whole screen, sideways: the button (full screen + the screen turned where the phone
// lets a page do it, else the map turned on the screen: hold the phone sideways), or the phone simply turned
// sideways on the live tab. Either way ✕ or the phone's back button leaves it; after leaving, a phone still
// held sideways shows the normal page (turn it upright and sideways again, or "Xem ngang", for the map).
const PITCH_BOX = '-56 -37.5 112 75', FULL_BOX = '-55.5 -36.8 111 73.6';    // full screen: the pitch, less margin
function wantFull() {
  return S.tab === 'live' && !S.nav.some(e => e.kind === 'sheet') && (S.fullBtn || (LAND_Q.matches && !S.fullOff));
}
async function enterFs() {                       // real full screen: no status / navigation bars
  try { if (!document.fullscreenElement && document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen({navigationUI: 'hide'}); } catch (e) {}
  if (S.fullBtn && !S.locked) { try { await screen.orientation.lock('landscape'); S.locked = true; } catch (e) {} }
  fullUpdate();
}
async function exitFs() {
  S.locked = false;
  try { screen.orientation.unlock(); } catch (e) {}
  try { if (document.fullscreenElement) await document.exitFullscreen(); } catch (e) {}
}
function setFull(on) {
  if (on) { S.fullBtn = true; S.fullOff = false; fullUpdate(); enterFs(); return; }
  S.fullBtn = false;
  S.fullOff = LAND_Q.matches;
  exitFs();
  fullUpdate();
}
function closeFull() {                           // ✕: through the back step when the map has one
  if (S.nav.length && S.nav[S.nav.length - 1].kind === 'full') return back();
  setFull(false);
}
function fullUpdate() {
  const b = document.body, on = wantFull();
  b.classList.toggle('rot', on && !!S.fullBtn && !S.locked && PORTRAIT_Q.matches);
  if (on === !!S.full) return;
  S.full = on;
  b.classList.toggle('full', on);
  const svg = document.querySelector('.lvpitch');
  if (svg) svg.setAttribute('viewBox', on ? FULL_BOX : PITCH_BOX);
  if (on && !S.nav.some(e => e.kind === 'full')) push({kind: 'full'});          // the back button leaves the map
  if (!on) {                                     // left another way: its back step goes too
    const i = S.nav.length - 1;
    if (i >= 0 && S.nav[i].kind === 'full') { S.nav.pop(); S.skipPop = true; history.back(); }
  }
  S.lvSig = S.lvBodyHtml = null;
  (async () => {                                 // the screen stays on while the map is on the whole screen
    try {
      if (on && navigator.wakeLock && !S.wake) S.wake = await navigator.wakeLock.request('screen');
      else if (!on && S.wake) { S.wake.release(); S.wake = null; }
    } catch (e) {}
  })();
  if (S.liveLast) drawLive(S.liveLast);
}
LAND_Q.addEventListener('change', () => { if (!LAND_Q.matches) S.fullOff = false; fullUpdate(); });
PORTRAIT_Q.addEventListener('change', fullUpdate);
document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && S.fullBtn && S.locked) closeFull();       // swiped out of full screen
});

// ------------------------------------------------------------------ taps
document.addEventListener('click', ev => {
  const t = ev.target;
  const q = s => t.closest(s);
  if (q('[data-back]')) return back();
  let el;
  if ((el = q('[data-full]'))) {
    if (el.dataset.full === '1') return setFull(true);
    return closeFull();
  }
  if ((el = q('[data-lvtab]'))) { S.lvTab = el.dataset.lvtab; S.lvBodyHtml = null; lvTabs(); if (S.liveLast) drawLive(S.liveLast); return; }
  if ((el = q('[data-sheet-set]'))) {
    const e = topSheet();
    if (!e) return;
    const [k, v] = el.dataset.sheetSet.split(':');
    e[k] = v;
    fillSheet(e, true);
    return;
  }
  if ((el = q('[data-whois]'))) {
    (async () => {
      try {
        const r = await (await post('/api/matchlive/fix', {k: Number(el.dataset.k), pid: Number(el.dataset.whois)})).json();
        toast(r.message || 'Đã sửa.');
      } catch (e) { toast('Không gửi được tới máy tính.'); }
      back();
    })();
    return;
  }
  if ((el = q('[data-reply]'))) return sendReply(el.dataset.reply, el.dataset.choice, el);
  if ((el = q('[data-pid]'))) return openPlayer(el.dataset.pid, el.dataset.ptab);
  if ((el = q('[data-thread]'))) return openThread(el.dataset.thread);
  if ((el = q('[data-match]'))) return openMatch(el.dataset.match);
  if ((el = q('[data-gofx]'))) { S.matchSel = Number(el.dataset.gofx); S.matchSec = 'overview'; return go('match'); }
  if ((el = q('[data-set]'))) { const i = el.dataset.set.indexOf(':'); return setAndDraw(el.dataset.set.slice(0, i), el.dataset.set.slice(i + 1)); }
  if ((el = q('[data-sub]'))) {
    if (el.dataset.filter) { S.squadFilter = el.dataset.filter; S.squadView = 'list'; }
    return openSub(el.dataset.sub, S.tab);
  }
  if ((el = q('[data-tab]'))) return go(el.dataset.tab);
  if (q('[data-readall]')) return markRead(null);
  if ((el = q('[data-needpos]'))) {
    S.mq = {pos: el.dataset.needpos, scope: 'others', sort: 'peak', age_max: '26'};
    S.marketTab = 'search';
    draw(false);
    const f = $('#mk-form');
    if (f) runSearch(f);
    return;
  }
  if ((el = q('[data-act]'))) {
    const a = el.dataset.act;
    if (a === 'appreload') return location.reload();
    if (a === 'reload') { post('/api/reload').then(() => toast('Đang đọc lại save…')).catch(() => toast('Máy tính chưa kết nối.')); return; }
    if (a === 'backup') { post('/api/backup').then(() => toast('Đang sao lưu…')).catch(() => toast('Máy tính chưa kết nối.')); return; }
    if (a === 'train') {
      if (!confirm('Huấn luyện lại AI trên máy tính? (mất vài phút, Dugout vẫn chạy bình thường)')) return;
      post('/api/train').then(() => toast('AI đang huấn luyện lại…')).catch(() => toast('Máy tính chưa kết nối.'));
      return;
    }
  }
  const dot = q('#lv-dots .pl');
  if (dot && !S.full) return whoIs(Number(dot.dataset.k), dot.dataset.team);
  if (S.full && q('#lv-map') && !document.fullscreenElement) enterFs();      // a tap: the whole screen (no bars)
});
document.addEventListener('change', ev => {
  const el = ev.target.closest('[data-setsel]');
  if (el) setAndDraw(el.dataset.setsel, el.value);
});
document.addEventListener('submit', ev => {
  if (ev.target.id === 'mk-form') { ev.preventDefault(); document.activeElement && document.activeElement.blur(); runSearch(ev.target); }
});

// ------------------------------------------------------------------ start
tabbar();
poll();

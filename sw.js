/* Dugout on the phone (service worker): keeps the app and the last data it received on the phone,
   so the app opens and shows that data with the PC off, and syncs again as soon as Dugout runs.
   Every request goes to the PC through the Cloudflare tunnel; a tunnel gets a new address each time
   it starts, so when the address stops answering the new one is read from the pairing key's private
   ntfy.sh topic (posted by dugout/phone.py). Only used over https (the tunnel), never on the PC. */
const CACHE = 'dugout-phone-v2';
const KEY = new URL(self.location.href).searchParams.get('key') || '';
// '/' is the phone's own app (web/m) through the tunnel; the PC's full page is kept too (index.html)
const SHELL = ['/', '/m/m.js', '/m/m.css', '/index.html', '/app.js', '/style.css', '/icon.png', '/icon-512.png'];
const DEAD = new Set([502, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530]);   // Cloudflare: tunnel gone
let base = null;
let lastLook = 0;

const timeout = ms => { const c = new AbortController(); setTimeout(() => c.abort(), ms); return c.signal; };
const json = (obj, status) => new Response(JSON.stringify(obj), {status: status || 200, headers: {'Content-Type': 'application/json; charset=utf-8'}});

async function topic() {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('dugout:' + KEY));
  return 'dugout-' + [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 24);
}
async function getBase() {
  if (base) return base;
  const r = await (await caches.open(CACHE)).match('/__base');
  base = r ? await r.text() : self.location.origin;
  return base;
}
async function setBase(b) {
  base = b;
  await (await caches.open(CACHE)).put('/__base', new Response(b));
}
function cacheKey(url) {
  const q = new URLSearchParams(url.search);
  q.delete('key');
  const s = q.toString();
  return self.location.origin + url.pathname + (s ? '?' + s : '');
}

async function send(b, url, req, body, ms) {
  const headers = new Headers({'X-Dugout-Key': KEY});
  for (const h of ['content-type', 'x-dugout', 'accept']) if (req.headers.get(h)) headers.set(h, req.headers.get(h));
  const r = await fetch(b + url.pathname + url.search, {method: req.method, headers, body, mode: 'cors', credentials: 'omit',
    cache: 'no-store', signal: timeout(ms)});
  if (DEAD.has(r.status)) throw new Error('tunnel ' + r.status);
  return r;
}

// the PC's current address: the pairing key's ntfy.sh topic holds the addresses of the last 12 hours
async function lookUp(dead) {
  if (Date.now() - lastLook < 20000) return null;
  lastLook = Date.now();
  const found = [];
  try {
    const r = await fetch(`https://ntfy.sh/${await topic()}/json?poll=1&since=12h`, {cache: 'no-store', signal: timeout(8000)});
    const msgs = (await r.text()).split('\n').filter(Boolean).map(l => { try { return JSON.parse(l); } catch (e) { return null; } })
      .filter(m => m && m.event === 'message');
    for (const m of msgs.reverse()) { try { const u = JSON.parse(m.message).url; if (u && !found.includes(u)) found.push(u); } catch (e) {} }
  } catch (e) { return null; }
  for (const u of found) {
    if (u === dead) continue;
    try {
      const r = await fetch(u + '/api/status', {headers: {'X-Dugout-Key': KEY}, mode: 'cors', cache: 'no-store', signal: timeout(7000)});
      if (r.ok) { await setBase(u); return u; }
    } catch (e) {}
  }
  return null;
}

async function offline(req, url) {
  const c = await caches.open(CACHE);
  if (req.method !== 'GET')
    return json({ok: false, error: 'Máy tính chưa kết nối (Dugout trên máy tính chưa chạy): chưa gửi được.'}, 503);
  if (url.pathname === '/api/matchlive')
    return json({state: 'offline', message: 'Máy tính chưa kết nối: bản đồ trận đấu chỉ có khi Dugout trên máy tính đang chạy.'});
  if (url.pathname === '/api/status') {
    const r = await c.match('/__status');
    const s = r ? await r.json() : {};
    const at = s._at ? new Date(s._at) : null;
    const when = at ? `${at.getHours()}:${String(at.getMinutes()).padStart(2, '0')} ngày ${at.getDate()}/${at.getMonth() + 1}` : '';
    return json({...s, state: 'offline', offline: true,
      message: 'Máy tính chưa kết nối · đang xem dữ liệu' + (when ? ' đồng bộ lúc ' + when : ' lần trước'),
      log: s.log || [], version: s.version || 0});
  }
  const hit = await c.match(cacheKey(url)) || (req.mode === 'navigate' ? await c.match(self.location.origin + '/') : null);
  return hit || new Response('', {status: 504});
}

async function handle(req) {
  const url = new URL(req.url);
  const body = req.method === 'POST' ? await req.clone().arrayBuffer() : undefined;
  let b = await getBase();
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await send(b, url, req, body, url.pathname === '/api/status' ? 6000 : 20000);
      if (req.method === 'GET' && r.ok && url.pathname !== '/api/matchlive') {
        const c = await caches.open(CACHE);
        if (url.pathname === '/api/status') {
          const s = await r.clone().json();
          c.put('/__status', new Response(JSON.stringify({...s, _at: Date.now()})));
        } else {
          c.put(cacheKey(url), r.clone());
        }
      }
      return r;
    } catch (e) {
      const nb = await lookUp(b);
      if (!nb) break;
      b = nb;
    }
  }
  return offline(req, url);
}

self.addEventListener('install', ev => ev.waitUntil((async () => {
  const c = await caches.open(CACHE);
  await Promise.all(SHELL.map(async p => {
    try {
      const r = await fetch(p + '?key=' + encodeURIComponent(KEY), {cache: 'no-store'});
      if (r.ok) await c.put(self.location.origin + p, r);
    } catch (e) {}
  }));
  await self.skipWaiting();
})()));
// a new version: the PC's address and the last status move over from the old cache, which is then removed
self.addEventListener('activate', ev => ev.waitUntil((async () => {
  const c = await caches.open(CACHE);
  for (const name of await caches.keys()) {
    if (name === CACHE || !name.startsWith('dugout-phone-')) continue;
    const old = await caches.open(name);
    for (const k of ['/__base', '/__status']) {
      const r = await old.match(k);
      if (r && !(await c.match(k))) await c.put(k, r);
    }
    await caches.delete(name);
  }
  base = null;
  await self.clients.claim();
})()));
self.addEventListener('fetch', ev => {
  const url = new URL(ev.request.url);
  if (url.origin !== self.location.origin || url.pathname === '/sw.js') return;
  ev.respondWith(handle(ev.request));
});

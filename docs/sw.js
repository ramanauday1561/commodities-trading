// Service worker: lets the home-screen app open offline and start fast.
// Network first for everything (forecasts change several times a day); the cached copy is used only when offline.
const CACHE = 'forecast-v1';
const SHELL = ['./', 'index.html', 'lightweight-charts.js?v=2', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;     // GitHub API calls go straight to the network
  const key = url.pathname.includes('/data/') ? url.origin + url.pathname : req.url;   // data files: ignore the ?t= cache buster
  e.respondWith(fetch(req).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
    return res;
  }).catch(() => caches.match(key).then(hit => hit || caches.match(req, { ignoreSearch: true }))
    .then(hit => hit || (req.mode === 'navigate' ? caches.match('index.html') : Response.error()))));
});

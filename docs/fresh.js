// The latest data files, without the 5-minute delay (2 Nov 2026).
// Every 10-minute run saves the data to the site-data branch. raw.githubusercontent.com serves each branch file from a
// 5-minute cache and ignores "?t=" cache-busters, so a page could show data up to 5 minutes old. Instead, ask GitHub's
// API for site-data's newest commit (a conditional request: an unchanged answer, 304, does not count against the
// 60-an-hour limit for visitors) and load files from that exact commit, which no cache can serve stale. If the API is
// unavailable (or the limit is reached), fall back to the branch file, then to the copy published with the site.
(function () {
  const REPO = 'ramanauday1561/commodities-trading';
  const RAW = `https://raw.githubusercontent.com/${REPO}/`;
  // the newest commit, shared by all the files a page loads at once, and kept across pages so the next check can be a
  // free 304; at most one check every 15 seconds
  let sha = null, etag = null, checked = 0, pending = null;
  try { const k = JSON.parse(sessionStorage.getItem('siteData') || '{}'); sha = k.sha || null; etag = k.etag || null; } catch (e) {}

  async function check() {
    try {
      const h = { Accept: 'application/vnd.github.sha' };
      if (etag) h['If-None-Match'] = etag;
      const r = await fetch(`https://api.github.com/repos/${REPO}/commits/site-data`, { headers: h, cache: 'no-store' });
      if (r.ok) {
        const s = (await r.text()).trim();
        if (/^[0-9a-f]{40}$/.test(s)) {
          sha = s; etag = r.headers.get('ETag');
          try { sessionStorage.setItem('siteData', JSON.stringify({ sha, etag })); } catch (e) {}
        }
      }
    } catch (e) { /* the fallbacks below */ }
    return sha;
  }
  function latest() {
    if (pending) return pending;
    if (sha && Date.now() - checked < 15000) return Promise.resolve(sha);
    pending = check().finally(() => { pending = null; checked = Date.now(); });
    return pending;
  }

  // 11 Nov 2026: the order server (VPS) runs the 10-minute updates and serves the same files seconds after each run.
  // Used while its heartbeat (runner.json) is under 15 minutes old; otherwise GitHub as before. Checked every 15 s.
  const VPS = 'https://189-72-149-115.sslip.io/data/';
  let vps = false, vpsAt = 0, vpsPending = null;
  async function get(u, ms) {
    const c = new AbortController(), t = setTimeout(() => c.abort(), ms);
    try { return await fetch(u, { cache: 'no-store', signal: c.signal }); } finally { clearTimeout(t); }
  }
  function vpsLive() {
    if (vpsPending) return vpsPending;
    if (Date.now() - vpsAt < 15000) return Promise.resolve(vps);
    vpsPending = get(VPS + 'runner.json', 2500).then(r => r.ok ? r.json() : null).then(j => {
      vps = !!j && j.by === 'vps' && Date.now() - Date.parse(j.at) < 15 * 60000;
    }).catch(() => { vps = false; }).finally(() => { vpsPending = null; vpsAt = Date.now(); }).then(() => vps);
    return vpsPending;
  }

  // fetch(name) -> Response (or null): the VPS while it runs the updates, else the file from site-data's newest
  // commit, else the branch, else the site copy
  async function siteFile(name, { site = true } = {}) {
    if (await vpsLive()) {
      try { const r = await get(VPS + name, 4000); if (r.ok) return r; } catch (e) { /* GitHub below */ }
    }
    const s = await latest();
    const urls = [...(s ? [RAW + s + '/' + name] : []), RAW + 'site-data/' + name, ...(site ? ['data/' + name + '?t=' + Date.now()] : [])];
    for (const u of urls) {
      try {
        const r = await fetch(u, { cache: u.startsWith('data/') ? 'no-store' : 'default' });
        if (r.ok) return r;
      } catch (e) { /* next */ }
    }
    return null;
  }

  // How fresh the data is, ticking on its own (2 Nov 2026): a dot and "2 min ago" next to a page's update time.
  // live = during the session and at most 12 minutes old (runs come every 10); late = older during the session.
  function ago(ms) {
    const m = Math.max(0, Math.round(ms / 60000));
    return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ${m % 60} min ago`;
  }
  function paint(el) {
    const t = Date.parse(el.dataset.ts), open = el.dataset.open === '1', age = Date.now() - t;
    if (!isFinite(t)) return;
    const state = !open ? 'off' : age <= 12 * 60000 ? 'live' : 'late';
    el.className = 'fresh ' + state;
    el.innerHTML = `<i></i>${state === 'live' ? 'live · ' : state === 'late' ? 'late · ' : ''}${ago(age)}`;
  }
  // freshTag(isoTime, sessionOpen) -> HTML; the tag repaints itself every 20 seconds
  window.freshTag = (iso, open) => iso ? `<span class="fresh" data-ts="${iso}" data-open="${open ? 1 : 0}"></span>` : '';
  const css = document.createElement('style');
  css.textContent = `.fresh { white-space:nowrap; } .fresh i { display:inline-block; width:7px; height:7px; border-radius:50%;
    margin:0 5px 1px 5px; vertical-align:middle; background:#6b7688; } .fresh.live i { background:#34d1bf;
    box-shadow:0 0 0 3px rgba(52,209,191,.18); } .fresh.late i { background:#f2c14e; }`;
  document.head.appendChild(css);
  // new tags are painted as they appear (only unpainted ones, so painting does not retrigger), all of them every 20 s
  new MutationObserver(() => document.querySelectorAll('.fresh[data-ts]:empty').forEach(paint))
    .observe(document.documentElement, { childList: true, subtree: true });
  setInterval(() => document.querySelectorAll('.fresh[data-ts]').forEach(paint), 20000);

  // when the next run's data should be out, from this data's run time: runs start as each 10-minute candle closes
  // (09:25, 09:35 ... IST) and save about 90 seconds later (3 Nov 2026: the 10:35 run's data was saved at 10:36:24),
  // so the next data lands about 11.5 minutes after this run; "due now" once that has passed
  // (an HTML tag that repaints itself every 20 seconds, like freshTag, as the page redraws only on new data)
  function nextText(iso) {
    const t = Date.parse(iso) + 11.5 * 60000;
    if (!isFinite(t)) return '';
    if (Date.now() > t) return 'next update due now';
    const ist = new Date(Math.ceil(t / 60000) * 60000 + 19800000);
    return `next ~${String(ist.getUTCHours()).padStart(2, '0')}:${String(ist.getUTCMinutes()).padStart(2, '0')}`;
  }
  window.nextRun = (iso) => `<span class="nextrun" data-ts="${iso}">${nextText(iso)}</span>`;
  setInterval(() => document.querySelectorAll('.nextrun[data-ts]').forEach(el => { el.textContent = nextText(el.dataset.ts); }), 20000);

  window.siteFile = siteFile;
  window.siteJSON = async (name, opts) => { const r = await siteFile(name, opts); return r ? r.json() : null; };
})();

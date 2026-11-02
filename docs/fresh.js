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

  // fetch(name) -> Response (or null): the file from site-data's newest commit, else the branch, else the site copy
  async function siteFile(name, { site = true } = {}) {
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

  window.siteFile = siteFile;
  window.siteJSON = async (name, opts) => { const r = await siteFile(name, opts); return r ? r.json() : null; };
})();

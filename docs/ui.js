// The app's shared building blocks (12 Nov 2026; kit.css has the looks): icons, sections that open and close and
// remember it per page, stat tiles and small formatters. Every page draws its own data with these.
(function () {
  const P = {
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    size: '<path d="M12 3v18M8 7l4-4 4 4M8 17l4 4 4-4"/>',
    up: '<path d="M12 19V5M6 11l6-6 6 6"/>', down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
    check: '<path d="M5 12l5 5 9-10"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
    activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    rupee: '<path d="M6 4h12M6 9h12M9 4c4 0 6 2 6 5s-2 5-6 5H6l8 7"/>',
    chart: '<path d="M3 21h18M6 17v-6M11 17V5M16 17v-9M21 17v-3"/>',
    list: '<path d="M9 6h12M9 12h12M9 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    alert: '<path d="M12 3l9.5 17h-19z"/><path d="M12 10v4M12 17h.01"/>',
    chev: '<path d="M9 6l6 6-6 6"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
    news: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h10M7 16h6"/>',
    wallet: '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18M16 15h2"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="M10 8l6 4-6 4z"/>',
    pause: '<circle cx="12" cy="12" r="9"/><path d="M10 9v6M14 9v6"/>',
    trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
  };
  const ico = (n, cls = '') => `<svg class="k-ico ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[n] || P.info}</svg>`;
  const page = (location.pathname.split('/').pop() || 'index.html').replace('.html', '');
  let open = {};
  try { open = JSON.parse(localStorage.getItem('open:' + page) || '{}'); } catch (e) {}
  // one section: icon, title (and a short line under it), the summary on the right, a chevron; open by default unless
  // shut is true, and then as the viewer last left it
  function sec(key, icon, title, sub, summary, body, shut) {
    if (!body) return '';
    const isOpen = key in open ? open[key] : !shut;
    return `<details class="k-sec" data-sec="${key}"${isOpen ? ' open' : ''}><summary>
      <span class="k-badge-ic">${icon && icon.startsWith('<') ? icon : ico(icon)}</span><span class="k-t">${title}${sub ? `<small>${sub}</small>` : ''}</span>
      <span class="k-s">${summary || ''}</span>${ico('chev', 'k-chev')}</summary><div class="k-body">${body}</div></details>`;
  }
  document.addEventListener('toggle', e => {
    const k = e.target && e.target.dataset && e.target.dataset.sec;
    if (!k) return;
    open[k] = e.target.open;
    try { localStorage.setItem('open:' + page, JSON.stringify(open)); } catch (err) {}
  }, true);
  const tile = (value, label, cls = '') => `<div class="k-tile"><b class="${cls}">${value}</b><span>${label}</span></div>`;
  const pill = (text, cls = 'm', icon) => `<span class="k-pill ${cls}">${icon ? ico(icon) : ''}${text}</span>`;
  const alertBox = (html, cls = '', icon = 'alert') => `<div class="k-alert ${cls}">${ico(icon)}<div>${html}</div></div>`;
  // Today vs the backtest (16 Nov 2026): one day of automatic * picks read against nine years of the same rule
  // (star-days.json from scripts/star_days.py: per number of picks, the day's Rs after costs, 20 quantiles)
  let days = null;
  const starDays = () => days || (days = fetch('star-days.json', { cache: 'no-cache' }).then(r => r.ok ? r.json() : null).catch(() => null));
  const rsk = x => `${x > 0 ? '+' : x < 0 ? '−' : ''}₹${Math.abs(Math.round(x)).toLocaleString('en-IN')}`;
  function dayVsBacktest(n, net, t, sofar) {
    if (!t) return '';
    if (!n) return `<div class="k-note">No automatic ★ pick today, so nothing to compare. Over nine years ★ picks came on ${Math.round(t.star_days_share * 100)}% of days.</div>`;
    const b = t.by_picks[String(Math.min(n, 6))];
    if (!b) return '';
    const q = b.q;                                            // 21 quantiles, 0% .. 100%
    let pct = 0;
    if (net <= q[0]) pct = 0; else if (net >= q[20]) pct = 100;
    else for (let i = 1; i <= 20; i++) if (net <= q[i]) { pct = 5 * (i - 1) + 5 * (net - q[i - 1]) / ((q[i] - q[i - 1]) || 1); break; }
    pct = Math.round(pct);
    const cls = v => v >= 0 ? 'up' : 'down';
    return `<div class="k-tiles">${tile(rsk(net), `today, ${n} ★ pick${n > 1 ? 's' : ''}${sofar ? ' so far' : ''}`, cls(net))}
        ${tile(rsk(b.p50), `typical day with ${n >= 6 ? '6+' : n} pick${n > 1 ? 's' : ''}`, cls(b.p50))}
        ${tile(`${pct}%`, `of those days were worse than today`)}</div>
      <div class="k-note">Nine years (${t.from.slice(0, 4)}-${t.to.slice(0, 4)}), the server's rule, after costs: 8 in 10 such days ended between
        <b class="${cls(b.p10)}">${rsk(b.p10)}</b> and <b class="${cls(b.p90)}">${rsk(b.p90)}</b>; ${Math.round(b.up_share * 100)}% of them were up.
        Over all ★ picks the average was <b class="${cls(t.per_trade)}">${rsk(t.per_trade)}</b> a pick: read one day against that, not on its own.</div>`;
  }
  window.UI = { ico, sec, tile, pill, alert: alertBox, starDays, dayVsBacktest, star: `<svg class="k-ico k-star" viewBox="0 0 24 24" aria-label="star">${P.star}</svg>` };
})();

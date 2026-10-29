// The collapsible sidebar shared by every page (29 Oct 2026: the pages kept growing, so they live in one menu).
// Each page marks where the menu button goes with data-nav and loads this file; a new page only needs a line in PAGES.
(function () {
  const PAGES = [
    ['index.html', 'Home', 'Forecasts and today\'s call'],
    ['status.html', 'Status', 'CALL, PUT, STAY, SELL or NOTHING now'],
    ['live.html', 'Live', 'Today: predictions vs the real price'],
    ['next.html', 'Next 10 min', 'The model\'s lean per candle (information)'],
    ['history.html', 'History', 'Every day\'s calls and trades'],
  ];
  const here = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  const css = `
    .nav-host { display:flex; align-items:center; gap:10px; min-width:0; }
    .nav-btn { flex:none; width:34px; height:34px; border-radius:10px; border:1px solid rgba(255,255,255,.14);
      background:rgba(255,255,255,.07); color:inherit; display:grid; place-items:center; cursor:pointer; padding:0; }
    .nav-btn svg { width:18px; height:18px; }
    .nav-shade { position:fixed; inset:0; background:rgba(0,0,0,.45); opacity:0; pointer-events:none; transition:opacity .2s; z-index:1000; }
    .nav-drawer { display:block; margin:0; text-align:left; position:fixed; top:0; bottom:0; left:0; width:min(280px, 82vw); z-index:1001; transform:translateX(-102%);
      transition:transform .22s ease; background:rgba(10,14,24,.97); color:#eef1f6; border-right:1px solid rgba(255,255,255,.10);
      padding:calc(env(safe-area-inset-top) + 28px) 12px calc(env(safe-area-inset-bottom) + 16px) calc(env(safe-area-inset-left) + 12px);
      font:14px/1.35 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; overflow-y:auto; -webkit-backdrop-filter:blur(14px); backdrop-filter:blur(14px); }
    .nav-open .nav-drawer { transform:none; } .nav-open .nav-shade { opacity:1; pointer-events:auto; }
    .nav-drawer .nav-head { display:flex; justify-content:space-between; align-items:center; margin:0 4px 12px; }
    .nav-drawer .nav-head b { font-size:16px; } .nav-drawer .nav-head button { background:none; border:0; color:#9aa6b8; font-size:22px; cursor:pointer; }
    .nav-drawer a { display:block; width:auto; font-size:15px; font-weight:600; padding:10px 12px; margin:2px 0; border-radius:10px; color:#eef1f6; text-decoration:none; }
    .nav-drawer a small { display:block; color:#9aa6b8; font-size:12px; font-weight:400; margin-top:2px; }
    .nav-drawer a:hover { background:rgba(255,255,255,.06); }
    .nav-drawer a.on { background:rgba(124,180,255,.16); box-shadow:inset 3px 0 0 #7cb4ff; }
    @media (prefers-reduced-motion: reduce) { .nav-drawer, .nav-shade { transition:none; } }`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  const shade = document.createElement('div');
  shade.className = 'nav-shade';
  // an <aside>, not a <nav>: pages style their own <nav> (the Home page's market chips are a 4-column grid)
  const drawer = document.createElement('aside');
  drawer.className = 'nav-drawer';
  drawer.setAttribute('role', 'navigation');
  drawer.setAttribute('aria-label', 'Pages');
  drawer.innerHTML = '<div class="nav-head"><b>Pages</b><button type="button" aria-label="Close menu">×</button></div>'
    + PAGES.map(([href, name, sub]) => `<a href="${href}"${href === here ? ' class="on" aria-current="page"' : ''}>${name}<small>${sub}</small></a>`).join('');
  document.body.append(shade, drawer);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'nav-btn';
  btn.setAttribute('aria-label', 'Open menu');
  btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
  const host = document.querySelector('[data-nav]') || document.body;
  host.classList.add('nav-host');
  host.prepend(btn);

  const set = open => {
    document.documentElement.classList.toggle('nav-open', open);
    btn.setAttribute('aria-expanded', String(open));
    if (open) drawer.querySelector('a.on, a').focus({ preventScroll: true });
  };
  btn.addEventListener('click', () => set(!document.documentElement.classList.contains('nav-open')));
  shade.addEventListener('click', () => set(false));
  drawer.querySelector('.nav-head button').addEventListener('click', () => set(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
})();

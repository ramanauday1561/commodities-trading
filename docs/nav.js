// The collapsible sidebar shared by every page (29 Oct 2026: the pages kept growing, so they live in one menu).
// Each page marks where the menu button goes with data-nav and loads this file; a new page only needs a line in PAGES.
(function () {
  const PAGES = [
    ['today.html', 'Today', 'The day on one screen'],
    ['index.html', 'Home', 'Forecasts and today\'s call'],
    ['status.html', 'Status', 'CALL, PUT, STAY, SELL or NOTHING now'],
    ['live.html', 'Live', 'Today: predictions vs the real price'],
    ['next.html', 'Next 10 min', 'The model\'s lean per candle (information)'],
    ['history.html', 'History', 'Every day\'s calls and trades'],
    ['kite.html', 'Kite login', 'Once each morning: Kite\'s own prices'],
    ['orders.html', 'Orders', 'Your own picks, real money (order server)'],
    ['money.html', 'Money', 'Your Kite account: up or down today, after charges'],
  ];
  const here = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  const css = `
    .nav-host { display:flex; align-items:center; gap:10px; min-width:0; }
    .nav-btn { flex:none; width:34px; height:34px; border-radius:10px; border:1px solid rgba(75,83,32,0.22);
      background:rgba(75,83,32,0.11); color:inherit; display:grid; place-items:center; cursor:pointer; padding:0; }
    .nav-btn svg { width:18px; height:18px; }
    .nav-shade { position:fixed; inset:0; background:rgba(0,0,0,.45); opacity:0; pointer-events:none; transition:opacity .2s; z-index:1000; }
    .nav-drawer { display:block; margin:0; text-align:left; position:fixed; top:0; bottom:0; left:0; width:min(280px, 82vw); z-index:1001; transform:translateX(-102%);
      transition:transform .22s ease; background:rgba(247,232,216,.97); color:#2B2F14; border-right:1px solid rgba(75,83,32,0.16);
      padding:calc(env(safe-area-inset-top) + 28px) 12px calc(env(safe-area-inset-bottom) + 16px) calc(env(safe-area-inset-left) + 12px);
      font:14px/1.35 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; overflow-y:auto; -webkit-backdrop-filter:blur(14px); backdrop-filter:blur(14px); }
    .nav-open .nav-drawer { transform:none; } .nav-open .nav-shade { opacity:1; pointer-events:auto; }
    .nav-drawer .nav-head { display:flex; justify-content:space-between; align-items:center; margin:0 4px 12px; }
    .nav-drawer .nav-head b { font-size:16px; } .nav-drawer .nav-head button { background:none; border:0; color:#57532F; font-size:22px; cursor:pointer; }
    .nav-drawer a { display:block; width:auto; font-size:15px; font-weight:600; padding:10px 12px; margin:2px 0; border-radius:10px; color:#2B2F14; text-decoration:none; }
    .nav-drawer a small { display:block; color:#57532F; font-size:12px; font-weight:400; margin-top:2px; }
    .nav-drawer a:hover { background:rgba(75,83,32,0.1); }
    .nav-drawer a.on { background:rgba(36,82,156,.16); box-shadow:inset 3px 0 0 #24529C; }
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
  btn.setAttribute('data-plain', '');                       // never turned into a glass button (the tab bar replaces it)
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

  // Liquid Glass (5 Nov 2026, Glisse on React, vendor/glass-ui.js): a glass tab bar for the main pages and a "More" menu
  // for the rest, glass behind the cards, glass buttons. The sidebar above stays as the fallback: if the module cannot
  // load (an old browser, or ?classic in the address), the page keeps it and works as before.
  const theme = document.createElement('link');
  theme.rel = 'stylesheet';
  theme.href = 'theme.css?v=9';
  document.documentElement.dataset.theme = 'light';        // 11 Nov 2026: the sand theme; Glisse's light mode
  document.head.appendChild(theme);
  // 6 Nov 2026: Next 10 first, the screen the app opens on (index.html sends a fresh launch there)
  // 11 Nov 2026 (asked by the owner): Money in the bar, Live moved to the ⋯ menu
  const TABS = [['next.html', 'Next 10', 'next'], ['today.html', 'Today', 'today'], ['status.html', 'Status', 'status'],
                ['money.html', 'Money', 'money'], ['index.html', 'Forecast', 'home']];
  try { sessionStorage.setItem('opened', '1'); } catch (e) { /* private mode */ }
  // ?debug (6 Nov 2026): the viewport sizes the phone reports, to find the gap under the tab bar in the home-screen app
  if (/[?&]debug\b/.test(location.search)) {
    const probe = h => { const d = document.createElement('div'); d.style.cssText = `position:fixed;top:0;left:0;width:1px;visibility:hidden;height:${h}`;
      document.body.append(d); const v = d.getBoundingClientRect().height; d.remove(); return Math.round(v); };
    const show = () => {
      const vv = window.visualViewport, bar = document.querySelector('.gui-tabbar');
      let box = document.getElementById('vp-debug');
      if (!box) { box = document.createElement('pre'); box.id = 'vp-debug'; box.style.cssText = 'position:fixed;top:30%;left:8px;right:8px;z-index:2000;margin:0;padding:10px;'
        + 'background:#000c;color:#7cf;font:12px/1.4 ui-monospace,Menlo,monospace;border:1px solid #7cf;border-radius:8px;white-space:pre-wrap;'; document.body.append(box); }
      box.textContent = [`standalone ${!!(navigator.standalone || matchMedia('(display-mode: standalone)').matches)}  ${navigator.userAgent.match(/OS [\d_]+/) || ''}`,
        `screen ${screen.width}x${screen.height}  inner ${innerWidth}x${innerHeight}  outer ${outerHeight}`,
        `clientHeight ${document.documentElement.clientHeight}  visualViewport ${vv ? Math.round(vv.height) + ' +' + Math.round(vv.offsetTop) : '-'}`,
        `100vh ${probe('100vh')}  100svh ${probe('100svh')}  100dvh ${probe('100dvh')}  100lvh ${probe('100lvh')}`,
        `safe-area top ${probe('env(safe-area-inset-top)')}  bottom ${probe('env(safe-area-inset-bottom)')}`,
        `tab bar bottom ${bar ? Math.round(bar.getBoundingClientRect().bottom) : '-'}`].join('\n');
    };
    addEventListener('load', () => setTimeout(show, 800));
    addEventListener('resize', show);
  }
  const MORE = [['live.html', 'Live', 'live'], ['orders.html', 'Orders', 'next'], ['history.html', 'History', 'history'], ['kite.html', 'Kite login', 'kite'],
                ['next.html?debug', 'Screen check', 'status']];      // 6 Nov 2026, for a while: the tab bar's gap (?debug below)
  if (!/[?&]classic\b/.test(location.search)) {
    import('./vendor/glass-ui.js?v=3')
      .then(m => m.start({ nav: { here: here === '' ? 'index.html' : here,
                                  tabs: TABS.map(([href, label, icon]) => ({ href, label, icon })),
                                  more: MORE.map(([href, label, icon]) => ({ href, label, icon })) } }))
      .catch(e => console.warn('glass UI not loaded; the classic menu stays', e));
  }
})();

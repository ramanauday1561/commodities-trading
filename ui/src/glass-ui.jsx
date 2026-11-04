// Liquid Glass for the app's static pages (5 Nov 2026, asked by the user): Glisse (MIT, glisse.kelvinzhang.ca) on
// React 18, bundled into docs/vendor/glass-ui.js by `npm run build` here, so nothing loads from a CDN at run time.
// The pages stay plain HTML and JavaScript; this module only adds on top of them, and every page still works without it:
//   - nav(): an iOS-style glass tab bar at the bottom (the main pages) and a glass "More" menu (the rest);
//   - glass surfaces behind every card (.card, .box, [data-glass]): the content stays the page's own DOM, the glass is
//     a layer underneath, so the pages keep updating their cards as before;
//   - glass buttons (and switches for buttons marked data-switch) mirroring the page's own buttons: a click on the glass
//     button clicks the original, so the page's own click handlers still do the work.
import React from "react";
import { createRoot } from "react-dom/client";
import { Button, Glass, Menu, Switch, TabBar } from "glisse";

const roots = new Map();
function mount(host, node) {
  let r = roots.get(host);
  if (!r) {
    r = createRoot(host);
    roots.set(host, r);
  }
  r.render(node);
}
function sweep() {
  for (const [host, r] of roots) {
    if (!host.isConnected) {
      r.unmount();
      roots.delete(host);
    }
  }
}

// ---------------------------------------------------------------- icons (24px line glyphs)
const P = {
  today: "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4",
  status: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
  live: "M3 17l5-6 4 3 5-7 4 4",
  next: "M5 12h12M13 7l5 5-5 5",
  home: "M4 11l8-7 8 7v9h-5v-6H9v6H4z",
  history: "M4 12a8 8 0 1 0 2.3-5.6M4 4v4h4M12 8v4l3 2",
  kite: "M7 11V8a5 5 0 0 1 10 0v3M5 11h14v9H5z",
};
const Icon = ({ name }) => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={P[name] || P.next} /></svg>
);

// ---------------------------------------------------------------- navigation
export function nav({ tabs, more, here }) {
  document.body.classList.add("gui-on");
  const bar = document.createElement("nav");
  bar.className = "gui-tabbar";
  bar.setAttribute("aria-label", "Pages");
  document.body.append(bar);
  const current = tabs.some((t) => t.href === here) ? here : null;
  mount(bar, <TabBar items={tabs.map((t) => ({ value: t.href, label: t.label, icon: <Icon name={t.icon} />, href: t.href }))}
                     defaultValue={current} />);
  if (more && more.length) {
    const m = document.createElement("div");
    const head = document.querySelector("[data-nav]");
    m.className = head ? "gui-more gui-more-inline" : "gui-more";   // in the page's header row when it has one
    (head || document.body).append(m);
    mount(m, <Menu aria-label="More pages" items={more.map((p) => ({ label: p.label, icon: <Icon name={p.icon} />,
                                                                      onSelect: () => { location.href = p.href; } }))} />);
  }
}

// ---------------------------------------------------------------- glass behind cards
const SURFACES = ".card, .box, .glass, [data-glass]";
function addLayer(el) {
  if (el.tagName === "DETAILS" || el.hidden || el.querySelector(":scope > .gui-layer")) return;   // closed details hide children
  if (el.closest("[data-glass-skip]") || (el.parentElement && el.parentElement.closest(".gui-host"))) return;
  el.classList.add("gui-host");
  const layer = document.createElement("div");
  layer.className = "gui-layer";
  layer.setAttribute("aria-hidden", "true");
  el.prepend(layer);
  mount(layer, <Glass className="gui-glass" />);
}

// ---------------------------------------------------------------- glass buttons mirroring the page's buttons
function label(btn) {
  return <span className="gui-label" dangerouslySetInnerHTML={{ __html: btn.innerHTML }} />;
}
function mirror(btn) {
  if (btn.__gui || btn.hasAttribute("data-plain") || btn.closest(".gui-btn, .gui-tabbar, .gui-more, .nav-drawer, [data-glass-skip]")) return;
  const host = document.createElement("span");
  host.className = "gui-btn" + (btn.dataset.switch !== undefined ? " gui-switch" : "");
  btn.after(host);
  btn.classList.add("gui-hidden");
  btn.__gui = host;
  const click = (e) => {
    if (e && e.stopPropagation) e.stopPropagation();     // the page hears the original's click, not this one
    btn.click();
  };
  const render = () => {
    if (!host.isConnected) return;
    if (btn.hidden) return mount(host, null);
    if (btn.dataset.switch !== undefined) {
      return mount(host, <label className="gui-switch-row">{label(btn)}
        <Switch checked={btn.dataset.switch === "on"} onCheckedChange={() => click()} aria-label={btn.textContent.trim()} /></label>);
    }
    const on = btn.classList.contains("on") || btn.getAttribute("aria-pressed") === "true" || btn.dataset.variant === "filled";
    mount(host, <Button variant={on ? "filled" : "glass"} disabled={btn.disabled} onClick={click} title={btn.title || undefined}
                        aria-label={btn.getAttribute("aria-label") || undefined}
                        className={(btn.getAttribute("class") || "").replace(/\bgui-hidden\b/, "").trim() + " gui-b"}>{label(btn)}</Button>);
  };
  render();
  new MutationObserver(render).observe(btn, { attributes: true, childList: true, subtree: true, characterData: true });
}

// ---------------------------------------------------------------- everything, kept up as the pages redraw
let queued = false;
function scan() {
  queued = false;
  sweep();
  document.querySelectorAll(SURFACES).forEach(addLayer);
  document.querySelectorAll("button").forEach(mirror);
}
export function start(options = {}) {
  document.documentElement.setAttribute("data-theme", "dark");
  if (options.nav) nav(options.nav);
  scan();
  new MutationObserver(() => {
    if (!queued) {
      queued = true;
      requestAnimationFrame(scan);
    }
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
}

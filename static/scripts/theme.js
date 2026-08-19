/* ── ScenePlay Theme Engine ───────────────────────────────────────────────────
   Loaded in <head> — the IIFE runs synchronously before first paint so there
   is zero flash of unstyled content.  The rest of the functions run after
   DOMContentLoaded.
   ──────────────────────────────────────────────────────────────────────── */

/* Picker order: all light themes first, then all dark — the `dark` flag
   draws the group label, so keep each group contiguous. */
const SP_THEMES = [
  { id: 'daylight',      name: 'Daylight',  swatch: '#2f6fed' },
  { id: 'ttrpg-classic', name: 'Classic',   swatch: '#c9a84c' },
  { id: 'forest',        name: 'Forest',    swatch: '#6ecf80' },
  { id: 'ocean',         name: 'Ocean',     swatch: '#18c8e8' },
  { id: 'frost',         name: 'Frost',     swatch: '#90d8f8' },
  { id: 'parchment',     name: 'Parchment', swatch: '#e0b860' },
  { id: 'midnight',      name: 'Midnight',  swatch: '#00e5c8', dark: true },
  { id: 'crimson',       name: 'Crimson',   swatch: '#f05050', dark: true },
  { id: 'ember',         name: 'Ember',     swatch: '#ffa020', dark: true },
  { id: 'royal',         name: 'Royal',     swatch: '#b888ff', dark: true },
  { id: 'steel',         name: 'Steel',     swatch: '#9abcd4', dark: true },
];

/* ── Contrast utility ────────────────────────────────────────────────────────
   Returns '#ffffff' or a dark near-black depending on which provides the
   higher WCAG contrast ratio against the given hex background.
   Used to ensure text is always readable on any coloured surface.           */
function spContrastText(hex) {
  hex = hex.replace(/^#/, '');
  if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
  var r = parseInt(hex.slice(0,2),16) / 255;
  var g = parseInt(hex.slice(2,4),16) / 255;
  var b = parseInt(hex.slice(4,6),16) / 255;
  // Gamma-correct perceived luminance (WCAG formula)
  function lin(c) { return c <= 0.04045 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4); }
  var L = 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b);
  // Contrast ratio against white vs near-black (#111118)
  var onDark  = (L + 0.05) / (0.004 + 0.05);   // contrast vs #111118 (L≈0.004)
  var onLight = (1.0 + 0.05) / (L + 0.05);      // contrast vs #ffffff
  return onLight > onDark ? '#ffffff' : '#111118';
}

/* Apply --sp-on-accent as an inline custom property so it overrides the
   theme stylesheet value and is always correct for the current accent.      */
function _spApplyOnAccent() {
  var accent = getComputedStyle(document.documentElement)
                 .getPropertyValue('--sp-accent').trim();
  if (!accent) return;
  var best = spContrastText(accent);
  document.documentElement.style.setProperty('--sp-on-accent', best);
}

/* ── IIFE: apply theme synchronously before first paint ─────────────────── */
(function () {
  var saved = localStorage.getItem('sp-theme') || 'daylight';
  document.documentElement.setAttribute('data-theme', saved);
}());

/* ── Public API ─────────────────────────────────────────────────────────── */
function spSetTheme(id) {
  document.documentElement.setAttribute('data-theme', id);
  localStorage.setItem('sp-theme', id);
  // Recompute on-accent after CSS vars have updated (next microtask)
  requestAnimationFrame(_spApplyOnAccent);
  _spUpdateSwatchStates(id);
}

function spTogglePicker() {
  var p = document.getElementById('sp-theme-panel');
  if (!p) return;
  var open = p.style.display === 'block';
  p.style.display = open ? 'none' : 'block';
  if (!open) _spUpdateSwatchStates(localStorage.getItem('sp-theme') || 'daylight');
}

function _spUpdateSwatchStates(activeId) {
  document.querySelectorAll('[data-sp-swatch]').forEach(function (el) {
    var on = el.dataset.spSwatch === activeId;
    el.style.outline       = on ? '3px solid var(--sp-accent)' : '2px solid transparent';
    el.style.outlineOffset = on ? '2px'              : '0';
    el.style.transform     = on ? 'scale(1.22)'      : 'scale(1)';
  });
}

/* ── Build swatch grid once DOM is ready ────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {
  // Compute and apply on-accent now that CSS has loaded
  _spApplyOnAccent();

  var container = document.getElementById('sp-swatches');
  if (!container) return;

  var active = localStorage.getItem('sp-theme') || 'daylight';

  function addGroupLabel(text) {
    var el = document.createElement('div');
    el.textContent = text;
    el.style.cssText = 'grid-column:1/-1;font-size:.62rem;font-weight:600;' +
                       'letter-spacing:.08em;text-transform:uppercase;' +
                       'color:var(--sp-muted);border-bottom:1px solid var(--sp-border);' +
                       'padding-bottom:3px;margin-bottom:-4px;';
    container.appendChild(el);
  }

  var darkStarted = false;
  addGroupLabel('Light');
  SP_THEMES.forEach(function (t) {
    if (t.dark && !darkStarted) { darkStarted = true; addGroupLabel('Dark'); }

    var btn = document.createElement('button');
    btn.title            = t.name;
    btn.dataset.spSwatch = t.id;
    btn.style.cssText    = [
      'width:32px', 'height:32px', 'border-radius:50%', 'border:none',
      'cursor:pointer', 'padding:0', 'transition:transform .15s, outline .1s',
      'background:' + t.swatch,
      'display:block',
    ].join(';');
    btn.onclick = function () { spSetTheme(t.id); };

    var label = document.createElement('div');
    label.textContent   = t.name;
    label.style.cssText = 'font-size:.62rem;margin-top:3px;text-align:center;' +
                          'color:var(--sp-muted);line-height:1.2;';

    var wrap = document.createElement('div');
    wrap.style.cssText  = 'display:flex;flex-direction:column;align-items:center;';
    wrap.appendChild(btn);
    wrap.appendChild(label);
    container.appendChild(wrap);
  });

  _spUpdateSwatchStates(active);
});

/* ── Close picker when clicking outside ────────────────────────────────── */
document.addEventListener('click', function (e) {
  var p   = document.getElementById('sp-theme-panel');
  var btn = document.getElementById('sp-theme-btn');
  if (!p || p.style.display !== 'block') return;
  if (!p.contains(e.target) && btn && !btn.contains(e.target)) {
    p.style.display = 'none';
  }
});

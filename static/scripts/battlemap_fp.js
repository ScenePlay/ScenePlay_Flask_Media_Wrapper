/* battlemap_fp.js — DM floorplan editor for 3D mode (LOCAL map page only; the
 * relay portal is view-only and never loads this file).
 *
 * Draws the map's wall/door/elevation floorplan into #floorplan-layer and lets
 * the DM edit it over the 2D map: draw/erase walls, mark doors, set elevation
 * rects, then save — POST /floorplan bumps the version, so every open 3D
 * viewer rebuilds within one poll. Works from empty: a DM can hand-trace a
 * map without ever using the LLM trace prompt.
 *
 * Relies on page globals from battlemap.html/battlemap.js: MAP_ID, CELL_PX,
 * GRID_COLS, GRID_ROWS, svgEl(). Hooked from battlemap.js: BMFP.onState(d)
 * on every poll, BMFP.redraw() on zoom.
 */
window.BMFP = (function () {
  'use strict';

  const SNAP = 0.5;            // wall/door endpoints snap to half cells
  const HIT_RADIUS = 0.35;     // cells — click tolerance for erase/door tools

  let plan = null;             // working copy {default_wall_height_ft, walls, doors, elevations}
  let version = null;          // server version the working copy is based on
  let dirty = false;
  let tool = null;             // 'wall' | 'door' | 'elev' | 'erase' | null
  let wallHeightFt = 10;
  let doorStates = {};         // door_key -> 0|1 (from the poll)
  let drag = null;             // active draw drag
  let loaded = false;

  const layer   = () => document.getElementById('floorplan-layer');
  const overlay = () => document.getElementById('fp-draw-overlay');

  const emptyPlan = () => ({ default_wall_height_ft: 10, walls: [], doors: [], elevations: [] });

  // ── load / save ────────────────────────────────────────────────────────────

  function load() {
    return fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`)
      .then(r => r.json())
      .then(d => {
        plan    = (d.ok && d.floorplan) ? d.floorplan : emptyPlan();
        version = d.version || null;
        dirty   = false;
        loaded  = true;
        wallHeightFt = plan.default_wall_height_ft || 10;
        const hEl = document.getElementById('fp-wall-height');
        if (hEl) hEl.value = wallHeightFt;
        redraw();
        updateStatus();
      })
      .catch(() => {});
  }

  function save() {
    if (!plan) return;
    plan.schema_version = 1;
    plan.format = 'sceneplay-floorplan';
    plan.grid = { cols: GRID_COLS, rows: GRID_ROWS };
    plan.default_wall_height_ft = wallHeightFt;
    const btn = document.getElementById('fp-save-btn');
    if (btn) btn.disabled = true;
    fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ floorplan: plan }),
    }).then(r => r.json())
      .then(d => {
        if (btn) btn.disabled = false;
        if (!d.ok) {
          alert('Floorplan rejected:\n' + (d.errors || ['save failed']).join('\n'));
          return;
        }
        // Re-fetch so the working copy matches the server's normalized
        // geometry (clamping, door-id assignment, rounding).
        load();
      })
      .catch(() => { if (btn) btn.disabled = false; alert('Save failed (network).'); });
  }

  function revert() {
    if (dirty && !confirm('Discard unsaved floorplan edits?')) return;
    load();
  }

  function markDirty() {
    dirty = true;
    redraw();
    updateStatus();
  }

  function updateStatus() {
    const el = document.getElementById('fp-status');
    if (!el || !plan) return;
    const n = plan.elevations.length;
    el.textContent =
      `${plan.walls.length} walls · ${plan.doors.length} doors` +
      (n ? ` · ${n} elevation${n !== 1 ? 's' : ''}` : '') +
      (version ? ` · v${version}` : ' · unsaved map') +
      (dirty ? '  (unsaved edits)' : '');
    el.style.color = dirty ? 'var(--ttrpg-accent)' : '';
  }

  // ── drawing the layer ──────────────────────────────────────────────────────

  function redraw() {
    const svg = layer();
    if (!svg || !plan) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const px = v => v * CELL_PX;

    plan.elevations.forEach((e, i) => {
      const up = e.floor_ft >= 0;
      const g = svgEl('g');
      g.appendChild(svgEl('rect', {
        x: px(e.x1), y: px(e.y1), width: px(e.x2 - e.x1), height: px(e.y2 - e.y1),
        fill: up ? '#4a9eff' : '#000000', 'fill-opacity': up ? '0.18' : '0.35',
        stroke: up ? '#4a9eff' : '#b06060', 'stroke-width': 2, 'stroke-dasharray': '6 4',
      }));
      const label = svgEl('text', {
        x: px(e.x1) + 6, y: px(e.y1) + 16,
        fill: up ? '#8fc3ff' : '#e09090', 'font-size': '12', 'font-weight': '700',
      });
      label.textContent = (e.floor_ft > 0 ? '+' : '') + e.floor_ft + ' ft' +
                          (e.label ? ' ' + e.label : '');
      g.appendChild(label);
      g.dataset.elevIdx = i;
      svg.appendChild(g);
    });

    plan.walls.forEach((w, i) => {
      const line = svgEl('line', {
        x1: px(w.x1), y1: px(w.y1), x2: px(w.x2), y2: px(w.y2),
        stroke: '#c9c4b4', 'stroke-width': 5, 'stroke-linecap': 'round',
        'stroke-opacity': '0.85',
      });
      line.dataset.wallIdx = i;
      svg.appendChild(line);
    });

    plan.doors.forEach((d, i) => {
      const isOpen = doorStates[d.id] !== undefined ? !!doorStates[d.id] : !!d.open;
      const line = svgEl('line', {
        x1: px(d.x1), y1: px(d.y1), x2: px(d.x2), y2: px(d.y2),
        stroke: isOpen ? '#4caf50' : '#e6a23c', 'stroke-width': 7,
        'stroke-linecap': 'round',
        'stroke-dasharray': isOpen ? '5 7' : 'none',
      });
      line.dataset.doorIdx = i;
      line.dataset.doorKey = d.id;
      // With no tool armed, a door is directly clickable to open/close it.
      if (tool === null) {
        line.style.pointerEvents = 'visibleStroke';
        line.style.cursor = 'pointer';
        const title = svgEl('title', {});
        title.textContent = (isOpen ? 'Open' : 'Closed') + ' door — click to toggle';
        line.appendChild(title);
        line.addEventListener('click', () => toggleDoor(d.id));
      }
      svg.appendChild(line);
    });
  }

  function toggleDoor(key) {
    if (dirty) { alert('Save or revert your floorplan edits first.'); return; }
    fetch(`/ttrpg/battlemap/${MAP_ID}/door/toggle`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ door_key: key }),
    }).then(r => r.json())
      .then(d => {
        if (d.ok) { doorStates[key] = d.is_open; redraw(); }
      })
      .catch(() => {});
  }

  // ── poll hook ──────────────────────────────────────────────────────────────

  function onState(d) {
    if (!loaded) return;
    const states = d.doors || {};
    const changed = JSON.stringify(states) !== JSON.stringify(doorStates);
    doorStates = states;
    // Someone else saved a newer floorplan (other DM tab, manage-page paste):
    // follow it unless this tab has unsaved edits worth protecting.
    if (!dirty && d.floorplan_version && d.floorplan_version !== version) {
      load();
      return;
    }
    if (changed && layerVisible()) redraw();
  }

  function layerVisible() {
    const svg = layer();
    return svg && svg.style.display !== 'none';
  }

  // ── panel / tools ──────────────────────────────────────────────────────────

  function togglePanel() {
    const panel = document.getElementById('fp-panel');
    if (!panel) return;
    const open = panel.style.display === 'block';
    if (open) { closePanel(); return; }
    panel.style.display = 'block';
    const btn = document.getElementById('fp-toggle-btn');
    if (btn) { btn.classList.add('btn-ttrpg'); btn.classList.remove('btn-outline-secondary'); }
    const svg = layer();
    if (svg) svg.style.display = 'block';
    if (!loaded) load(); else { redraw(); updateStatus(); }
  }

  function closePanel() {
    const panel = document.getElementById('fp-panel');
    if (panel) panel.style.display = 'none';
    const btn = document.getElementById('fp-toggle-btn');
    if (btn) { btn.classList.remove('btn-ttrpg'); btn.classList.add('btn-outline-secondary'); }
    setTool(null);
    // Keep the layer visible if there are unsaved edits, as a reminder.
    const svg = layer();
    if (svg && !dirty) svg.style.display = 'none';
  }

  function setTool(t) {
    tool = (tool === t) ? null : t;
    ['wall', 'door', 'elev', 'erase'].forEach(name => {
      const b = document.getElementById('fp-tool-' + name);
      if (!b) return;
      b.classList.toggle('btn-ttrpg', tool === name);
      b.classList.toggle('btn-outline-secondary', tool !== name);
    });
    const ov = overlay();
    if (ov) {
      ov.style.display = tool ? 'block' : 'none';
      ov.style.cursor = tool === 'erase' ? 'cell' : 'crosshair';
    }
    if (drag) { if (drag.previewEl) drag.previewEl.remove(); drag = null; }
    redraw();   // door clickability depends on tool === null
  }

  function setWallHeight(v) {
    wallHeightFt = Math.max(1, Math.min(100, parseInt(v) || 10));
  }

  // ── geometry helpers ───────────────────────────────────────────────────────

  function evtCell(e) {
    const rect = layer().getBoundingClientRect();
    return { x: (e.clientX - rect.left) / CELL_PX, y: (e.clientY - rect.top) / CELL_PX };
  }

  const snapHalf = v => Math.max(0, Math.round(v / SNAP) * SNAP);
  const snapInt  = v => Math.max(0, Math.round(v));

  function distToSeg(p, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const len2 = dx * dx + dy * dy;
    if (!len2) return Math.hypot(p.x - a.x, p.y - a.y);
    let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
  }

  function nearestSeg(list, p) {
    let best = null, bestD = HIT_RADIUS;
    list.forEach((s, i) => {
      const d = distToSeg(p, { x: s.x1, y: s.y1 }, { x: s.x2, y: s.y2 });
      if (d < bestD) { bestD = d; best = i; }
    });
    return best;
  }

  // ── whole-plan align (LLM traces often land offset / mis-scaled) ──────────
  // Applies fx to every x and fy to every y across walls, doors and elevation
  // rects. Coordinates may drift outside the grid while adjusting; the server
  // clamps on save, and the DM sees the overlay against the art the whole time.

  function _xformPlan(fx, fy) {
    if (!plan) return;
    const seg = s => {
      s.x1 = +fx(s.x1).toFixed(2); s.y1 = +fy(s.y1).toFixed(2);
      s.x2 = +fx(s.x2).toFixed(2); s.y2 = +fy(s.y2).toFixed(2);
    };
    plan.walls.forEach(seg);
    plan.doors.forEach(seg);
    plan.elevations.forEach(e => {
      seg(e);
      if (e.x1 > e.x2) { const t = e.x1; e.x1 = e.x2; e.x2 = t; }
      if (e.y1 > e.y2) { const t = e.y1; e.y1 = e.y2; e.y2 = t; }
    });
    markDirty();
  }

  function nudge(dx, dy) {
    _xformPlan(v => v + dx, v => v + dy);
  }

  function scalePlan(factor) {
    // Scale about the plan's own bounding-box center so it grows/shrinks in
    // place instead of sliding toward the grid origin.
    if (!plan) return;
    const xs = [], ys = [];
    plan.walls.concat(plan.doors, plan.elevations).forEach(s => {
      xs.push(s.x1, s.x2); ys.push(s.y1, s.y2);
    });
    if (!xs.length) return;
    const cx = (Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2;
    const cy = (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2;
    _xformPlan(v => cx + (v - cx) * factor, v => cy + (v - cy) * factor);
  }

  function nextDoorId() {
    const used = new Set(plan.doors.map(d => d.id));
    let n = 1;
    while (used.has('d' + n)) n++;
    return 'd' + n;
  }

  // ── overlay pointer handlers ───────────────────────────────────────────────

  function onDown(e) {
    if (!tool || !plan) return;
    e.preventDefault();
    const p = evtCell(e);

    if (tool === 'erase') { eraseAt(p); return; }
    if (tool === 'door')  { doorAt(p);  return; }

    if (tool === 'wall') {
      const start = { x: snapHalf(p.x), y: snapHalf(p.y) };
      const previewEl = svgEl('line', {
        x1: start.x * CELL_PX, y1: start.y * CELL_PX,
        x2: start.x * CELL_PX, y2: start.y * CELL_PX,
        stroke: 'var(--ttrpg-accent, #c9a84c)', 'stroke-width': 5, 'stroke-linecap': 'round',
      });
      layer().appendChild(previewEl);
      drag = { kind: 'wall', start, previewEl };
    } else if (tool === 'elev') {
      const start = { x: snapInt(p.x), y: snapInt(p.y) };
      const previewEl = svgEl('rect', {
        x: start.x * CELL_PX, y: start.y * CELL_PX, width: 0, height: 0,
        fill: '#4a9eff', 'fill-opacity': '0.2',
        stroke: '#4a9eff', 'stroke-width': 2, 'stroke-dasharray': '6 4',
      });
      layer().appendChild(previewEl);
      drag = { kind: 'elev', start, previewEl };
    }
  }

  function onMove(e) {
    if (!drag) return;
    const p = evtCell(e);
    if (drag.kind === 'wall') {
      let end = { x: snapHalf(p.x), y: snapHalf(p.y) };
      if (e.shiftKey) {   // axis lock to the dominant direction
        if (Math.abs(end.x - drag.start.x) >= Math.abs(end.y - drag.start.y)) end.y = drag.start.y;
        else end.x = drag.start.x;
      }
      drag.end = end;
      drag.previewEl.setAttribute('x2', end.x * CELL_PX);
      drag.previewEl.setAttribute('y2', end.y * CELL_PX);
    } else if (drag.kind === 'elev') {
      const end = { x: snapInt(p.x), y: snapInt(p.y) };
      drag.end = end;
      const x1 = Math.min(drag.start.x, end.x), y1 = Math.min(drag.start.y, end.y);
      drag.previewEl.setAttribute('x', x1 * CELL_PX);
      drag.previewEl.setAttribute('y', y1 * CELL_PX);
      drag.previewEl.setAttribute('width',  Math.abs(end.x - drag.start.x) * CELL_PX);
      drag.previewEl.setAttribute('height', Math.abs(end.y - drag.start.y) * CELL_PX);
    }
  }

  function onUp() {
    if (!drag) return;
    const d = drag;
    drag = null;
    d.previewEl.remove();
    if (!d.end) return;

    if (d.kind === 'wall') {
      if (d.start.x === d.end.x && d.start.y === d.end.y) return;
      const seg = { x1: d.start.x, y1: d.start.y, x2: d.end.x, y2: d.end.y };
      if (wallHeightFt !== (plan.default_wall_height_ft || 10)) seg.height_ft = wallHeightFt;
      plan.walls.push(seg);
      markDirty();
    } else if (d.kind === 'elev') {
      const x1 = Math.min(d.start.x, d.end.x), x2 = Math.max(d.start.x, d.end.x);
      const y1 = Math.min(d.start.y, d.end.y), y2 = Math.max(d.start.y, d.end.y);
      if (x1 === x2 || y1 === y2) return;
      const raw = prompt('Floor height in feet (negative = pit, positive = platform):', '-10');
      if (raw === null) return;
      const ft = parseInt(raw, 10);
      if (isNaN(ft) || !ft) return;
      plan.elevations.push({ x1, y1, x2, y2, floor_ft: Math.max(-50, Math.min(100, ft)) });
      markDirty();
    }
  }

  function eraseAt(p) {
    const wi = nearestSeg(plan.walls, p);
    const di = nearestSeg(plan.doors, p);
    // Prefer whichever is genuinely closer when both are in range.
    if (di !== null && (wi === null ||
        distToSeg(p, { x: plan.doors[di].x1, y: plan.doors[di].y1 }, { x: plan.doors[di].x2, y: plan.doors[di].y2 }) <=
        distToSeg(p, { x: plan.walls[wi].x1, y: plan.walls[wi].y1 }, { x: plan.walls[wi].x2, y: plan.walls[wi].y2 }))) {
      plan.doors.splice(di, 1);
      markDirty();
      return;
    }
    if (wi !== null) { plan.walls.splice(wi, 1); markDirty(); return; }
    const ei = plan.elevations.findIndex(e2 =>
      p.x >= e2.x1 && p.x < e2.x2 && p.y >= e2.y1 && p.y < e2.y2);
    if (ei !== -1) { plan.elevations.splice(ei, 1); markDirty(); }
  }

  function doorAt(p) {
    const di = nearestSeg(plan.doors, p);
    if (di !== null) {   // door -> wall
      const d = plan.doors.splice(di, 1)[0];
      const seg = { x1: d.x1, y1: d.y1, x2: d.x2, y2: d.y2 };
      plan.walls.push(seg);
      markDirty();
      return;
    }
    const wi = nearestSeg(plan.walls, p);
    if (wi !== null) {   // wall -> door
      const w = plan.walls.splice(wi, 1)[0];
      // no height_ft: doors inherit the wall height (3D fills shorter doors
      // with a lintel only when a height is explicitly set)
      plan.doors.push({ id: nextDoorId(), x1: w.x1, y1: w.y1, x2: w.x2, y2: w.y2,
                        open: false });
      markDirty();
    }
  }

  // ── init ───────────────────────────────────────────────────────────────────

  (function init() {
    const ov = overlay();
    if (!ov) return;   // not the DM page
    ov.addEventListener('pointerdown', onDown);
    ov.addEventListener('pointermove', onMove);
    ov.addEventListener('pointerup', onUp);
    ov.addEventListener('pointerleave', () => {
      if (drag) { drag.previewEl.remove(); drag = null; }
    });
    window.addEventListener('beforeunload', e => {
      if (dirty) { e.preventDefault(); e.returnValue = ''; }
    });
  })();

  return {
    onState, redraw, save, revert, setTool, setWallHeight,
    nudge, scalePlan,
    toggle: togglePanel, close: closePanel,
    isDirty: () => dirty,
  };
})();

// Template onclick shims (match the fx-panel naming convention)
function toggleFpPanel() { BMFP.toggle(); }
function closeFpPanel()  { BMFP.close(); }

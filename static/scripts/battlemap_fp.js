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

  const HIT_RADIUS = 0.35;     // cells — click tolerance for erase/door tools

  // Endpoint snap, author-selectable: 1 cell (5 ft), 0.5 (2.5 ft), or 0.2
  // (1 ft — fine geometry detail; character movement stays on 5-ft squares).
  const SNAPS = [1, 0.5, 0.2];
  let snap = 0.5;
  try {
    const s = parseFloat(localStorage.getItem('bmfp_snap'));
    if (SNAPS.indexOf(s) !== -1) snap = s;
  } catch (e) {}

  // Light fixture defaults per type — display colors/radii for the editor
  // glyphs; the real defaults live in battlemap3d.js/floorplan.py.
  const LIGHT_META = {
    torch:   { color: '#ff9a3c', radius_ft: 30 },
    brazier: { color: '#ff8830', radius_ft: 35 },
    lantern: { color: '#ffc36b', radius_ft: 30 },
    candle:  { color: '#ffb45e', radius_ft: 10 },
    glow:    { color: '#7fb8ff', radius_ft: 20 },
  };

  let plan = null;             // working copy {default_wall_height_ft, walls, doors, elevations, lights, zones}
  let version = null;          // server version the working copy is based on
  let dirty = false;
  let tool = null;             // 'wall' | 'door' | 'elev' | 'light' | 'zone' | 'select' | 'erase' | null
  let activeZone = -1;         // index into plan.zones the zone tool paints into
  let sel = null;              // {kind:'wall'|'door', idx} — select-tool target
  const ZONE_COLORS = ['#9b6ee8', '#4ec9b0', '#e8a33d', '#e86e9b', '#6e9be8',
                       '#a3c96e', '#c96e6e', '#6ec9c9'];
  let wallHeightFt = 10;
  let wallShow = false;        // new walls also render on players' 2D maps
  let elevFt = -10;            // height applied to new elevation shapes
  let lightType = 'torch';
  let lightColor = null;       // '#rrggbb' when custom; null = type default
  let lightRadius = null;      // ft when overridden; null = type default
  let propType = 'crate';
  let propRot = 0;             // degrees clockwise
  let propScale = 1;
  let propTexture = '';        // library slug; '' = the type's default look
  try {                        // remembered across sessions
    const saved = parseInt(localStorage.getItem('bmfp_elev_ft'), 10);
    if (!isNaN(saved) && saved) elevFt = Math.max(-50, Math.min(100, saved));
  } catch (e) {}
  let doorStates = {};         // door_key -> 0|1 (from the poll)
  let drag = null;             // active draw drag
  let loaded = false;
  let texLoaded = false;       // texture manifest fetched into the selects

  // ── undo / redo ────────────────────────────────────────────────────────────
  // Whole-plan JSON snapshots taken BEFORE each mutation; 50 deep. Cheap at
  // this scale (a big plan is ~100 KB) and immune to per-tool bookkeeping.

  const UNDO_MAX = 50;
  let undoStack = [], redoStack = [];

  function pushUndo() {
    if (!plan) return;
    const snap_ = JSON.stringify(plan);
    if (undoStack.length && undoStack[undoStack.length - 1] === snap_) return;
    undoStack.push(snap_);
    if (undoStack.length > UNDO_MAX) undoStack.shift();
    redoStack = [];
    updateUndoButtons();
  }

  function undo() {
    if (!undoStack.length || !plan) return;
    redoStack.push(JSON.stringify(plan));
    plan = JSON.parse(undoStack.pop());
    markDirty();
    updateUndoButtons();
  }

  function redo() {
    if (!redoStack.length || !plan) return;
    undoStack.push(JSON.stringify(plan));
    plan = JSON.parse(redoStack.pop());
    markDirty();
    updateUndoButtons();
  }

  function clearHistory() {
    undoStack = []; redoStack = [];
    updateUndoButtons();
  }

  function updateUndoButtons() {
    const u = document.getElementById('fp-undo-btn');
    const r = document.getElementById('fp-redo-btn');
    if (u) u.disabled = !undoStack.length;
    if (r) r.disabled = !redoStack.length;
  }

  const layer   = () => document.getElementById('floorplan-layer');
  const overlay = () => document.getElementById('fp-draw-overlay');

  const emptyPlan = () => ({ default_wall_height_ft: 10, walls: [], doors: [],
                             elevations: [], lights: [], props: [], zones: [] });

  // ── load / save ────────────────────────────────────────────────────────────

  function load() {
    return fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`)
      .then(r => r.json())
      .then(d => {
        plan    = (d.ok && d.floorplan) ? d.floorplan : emptyPlan();
        plan.lights = plan.lights || [];   // v1 plans predate these layers
        plan.props  = plan.props  || [];
        plan.zones  = plan.zones  || [];
        if (activeZone >= plan.zones.length) activeZone = plan.zones.length - 1;
        if (activeZone < 0 && plan.zones.length) activeZone = 0;
        sel = null;
        version = d.version || null;
        dirty   = false;
        loaded  = true;
        clearHistory();
        wallHeightFt = plan.default_wall_height_ft || 10;
        const hEl = document.getElementById('fp-wall-height');
        if (hEl) hEl.value = wallHeightFt;
        const sEl = document.getElementById('fp-wall-style');
        if (sEl) sEl.value = plan.wall_style || 'none';
        const eEl = document.getElementById('fp-elev-height');
        if (eEl) eEl.value = elevFt;     // remembered from last session
        redraw();
        updateStatus();
        renderZoneUI();
        renderSelUI();
      })
      .catch(() => {});
  }

  function save() {
    if (!plan) return;
    plan.schema_version = 2;
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
        if (window.BM3D && BM3D.setDraftFloorplan) BM3D.setDraftFloorplan(null);
        load();
      })
      .catch(() => { if (btn) btn.disabled = false; alert('Save failed (network).'); });
  }

  function revert() {
    if (dirty && !confirm('Discard unsaved floorplan edits?')) return;
    if (window.BM3D && BM3D.setDraftFloorplan) BM3D.setDraftFloorplan(null);
    load();
  }

  // Deep copy of the working plan for BM3D's draft preview (grid attached so
  // the viewer scales it like a saved plan).
  function getDraft() {
    if (!plan) return null;
    const draft = JSON.parse(JSON.stringify(plan));
    draft.grid = { cols: GRID_COLS, rows: GRID_ROWS };
    return draft;
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
    const nl = (plan.lights || []).length;
    const np = (plan.props || []).length;
    el.textContent =
      `${plan.walls.length} walls · ${plan.doors.length} doors` +
      (n ? ` · ${n} elevation${n !== 1 ? 's' : ''}` : '') +
      (nl ? ` · ${nl} light${nl !== 1 ? 's' : ''}` : '') +
      (np ? ` · ${np} prop${np !== 1 ? 's' : ''}` : '') +
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
      const stroke = up ? '#4a9eff' : '#b06060';
      const fillAttrs = {
        fill: up ? '#4a9eff' : '#000000', 'fill-opacity': up ? '0.18' : '0.35',
        stroke: stroke, 'stroke-width': 2, 'stroke-dasharray': '6 4',
      };
      let lx, ly;
      if (e.shape === 'circle') {
        g.appendChild(svgEl('circle', Object.assign({
          cx: px(e.cx), cy: px(e.cy), r: px(e.r) }, fillAttrs)));
        lx = px(e.cx) - px(e.r) * 0.5;
        ly = px(e.cy);
      } else {
        g.appendChild(svgEl('rect', Object.assign({
          x: px(e.x1), y: px(e.y1),
          width: px(e.x2 - e.x1), height: px(e.y2 - e.y1) }, fillAttrs)));
        lx = px(e.x1) + 6;
        ly = px(e.y1) + 16;
      }
      const label = svgEl('text', {
        x: lx, y: ly,
        fill: up ? '#8fc3ff' : '#e09090', 'font-size': '12', 'font-weight': '700',
      });
      label.textContent = (e.floor_ft > 0 ? '+' : '') + e.floor_ft + ' ft' +
                          (e.label ? ' ' + e.label : '');
      g.appendChild(label);
      g.dataset.elevIdx = i;
      svg.appendChild(g);
    });

    plan.walls.forEach((w, i) => {
      // player-visible walls read brighter in the editor so the DM can tell
      // which corrections the table can see
      const line = svgEl('line', {
        x1: px(w.x1), y1: px(w.y1), x2: px(w.x2), y2: px(w.y2),
        stroke: w.show ? '#f2ead0' : '#c9c4b4', 'stroke-width': w.show ? 6 : 5,
        'stroke-linecap': 'round', 'stroke-opacity': w.show ? '1' : '0.85',
      });
      line.dataset.wallIdx = i;
      svg.appendChild(line);
    });

    (plan.zones || []).forEach((zn, zi) => {
      const color = ZONE_COLORS[zi % ZONE_COLORS.length];
      const isActive = zi === activeZone;
      (zn.rects || []).forEach((r, ri) => {
        const rect = svgEl('rect', {
          x: px(r.x1), y: px(r.y1),
          width: px(r.x2 - r.x1), height: px(r.y2 - r.y1),
          fill: color, 'fill-opacity': isActive ? '0.10' : '0.05',
          stroke: color, 'stroke-width': isActive ? 2.5 : 1.5,
          'stroke-dasharray': '2 5',
        });
        svg.appendChild(rect);
        if (ri === 0) {
          const label = svgEl('text', {
            x: px(r.x1) + 5, y: px(r.y2) - 6,
            fill: color, 'font-size': '11', 'font-weight': '700', opacity: '0.85',
          });
          label.textContent = '⬔ ' + (zn.name || zn.id || ('zone ' + (zi + 1)));
          svg.appendChild(label);
        }
      });
    });

    // select-tool highlight under the segment lines / prop glyphs
    if (sel && plan[sel.kind + 's'] && plan[sel.kind + 's'][sel.idx]) {
      const s = plan[sel.kind + 's'][sel.idx];
      if (sel.kind === 'prop') {
        svg.appendChild(svgEl('circle', {
          cx: px(s.x), cy: px(s.y), r: 14 * (s.scale || 1),
          fill: '#3df0c8', 'fill-opacity': '0.25',
          stroke: '#3df0c8', 'stroke-width': 2.5,
        }));
      } else {
        svg.appendChild(svgEl('line', {
          x1: px(s.x1), y1: px(s.y1), x2: px(s.x2), y2: px(s.y2),
          stroke: '#3df0c8', 'stroke-width': 11, 'stroke-linecap': 'round',
          'stroke-opacity': '0.45',
        }));
      }
    }

    (plan.props || []).forEach((pr, i) => {
      const g = svgEl('g');
      const s = 9 * (pr.scale || 1);
      const box = svgEl('rect', {
        x: px(pr.x) - s, y: px(pr.y) - s, width: s * 2, height: s * 2,
        fill: '#a98d5f', 'fill-opacity': '0.85', stroke: '#3b3122',
        'stroke-width': 1.5, rx: 2,
        transform: `rotate(${pr.rot || 0} ${px(pr.x)} ${px(pr.y)})`,
      });
      g.appendChild(box);
      const label = svgEl('text', {
        x: px(pr.x), y: px(pr.y) + 3.5,
        fill: '#20180d', 'font-size': '10', 'font-weight': '700',
        'text-anchor': 'middle',
      });
      label.textContent = pr.type.slice(0, 2);
      g.appendChild(label);
      const title = svgEl('title', {});
      title.textContent = pr.type + (pr.scale && pr.scale !== 1 ? ` ×${pr.scale}` : '');
      g.appendChild(title);
      g.dataset.propIdx = i;
      svg.appendChild(g);
    });

    (plan.lights || []).forEach((lt, i) => {
      const meta = LIGHT_META[lt.type] || LIGHT_META.torch;
      const color = lt.color || meta.color;
      const rCells = (lt.radius_ft || meta.radius_ft) / 5;
      const g = svgEl('g');
      g.appendChild(svgEl('circle', {           // felt reach of the light
        cx: px(lt.x), cy: px(lt.y), r: px(rCells),
        fill: color, 'fill-opacity': '0.06',
        stroke: color, 'stroke-width': 1.5, 'stroke-dasharray': '4 6',
        'stroke-opacity': '0.6',
      }));
      g.appendChild(svgEl('circle', {           // the fixture itself
        cx: px(lt.x), cy: px(lt.y), r: 6,
        fill: color, stroke: '#000', 'stroke-width': 1.5,
      }));
      g.dataset.lightIdx = i;
      const title = svgEl('title', {});
      title.textContent = lt.type + (lt.radius_ft ? ` (${lt.radius_ft} ft)` : '');
      g.appendChild(title);
      svg.appendChild(g);
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
    // FX and Walls each arm a map-wide pointer overlay — with both open the
    // overlays fight over the same clicks, so opening one closes the other.
    const fxPanel = document.getElementById('fx-panel');
    if (fxPanel && fxPanel.style.display !== 'none' && fxPanel.style.display !== '' &&
        typeof closeFxPanel === 'function') closeFxPanel();
    panel.style.display = 'block';
    const btn = document.getElementById('fp-toggle-btn');
    if (btn) { btn.classList.add('btn-ttrpg'); btn.classList.remove('btn-outline-secondary'); }
    const svg = layer();
    if (svg) svg.style.display = 'block';
    if (!texLoaded) {
      texLoaded = true;
      fetch('/ttrpg/textures/manifest').then(r => r.json())
        .then(d => setTexOptions(d.textures || []))
        .catch(() => { texLoaded = false; });
    }
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
    if (tool !== 'select' && sel) { sel = null; renderSelUI(); }
    ['wall', 'rect', 'circle', 'door', 'elev', 'elevc', 'light', 'prop', 'zone',
     'select', 'erase'].forEach(name => {
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

  function setWallStyle(v) {
    if (!plan) return;
    pushUndo();
    if (v === 'none') delete plan.wall_style;
    else plan.wall_style = v;
    markDirty();
  }

  function setWallShow(v) {
    wallShow = !!v;
  }

  function setElevHeight(v) {
    const ft = parseInt(v, 10);
    if (isNaN(ft)) return;               // mid-typing (e.g. just "-") — keep last
    elevFt = Math.max(-50, Math.min(100, ft));
    try { localStorage.setItem('bmfp_elev_ft', String(elevFt)); } catch (e) {}
  }

  function setSnap(v) {
    const s = parseFloat(v);
    if (SNAPS.indexOf(s) === -1) return;
    snap = s;
    try { localStorage.setItem('bmfp_snap', String(s)); } catch (e) {}
  }

  function setLightType(t) {
    if (!LIGHT_META[t]) return;
    lightType = t;
    lightColor = null;                   // back to the new type's default
    lightRadius = null;
    const cEl = document.getElementById('fp-light-color');
    if (cEl) cEl.value = LIGHT_META[t].color;
    const rEl = document.getElementById('fp-light-radius');
    if (rEl) rEl.value = '';
  }

  function setLightColor(v) {
    lightColor = /^#[0-9a-fA-F]{6}$/.test(v) ? v.toLowerCase() : null;
  }

  function setLightRadius(v) {
    const ft = parseInt(v, 10);
    lightRadius = isNaN(ft) ? null : Math.max(5, Math.min(120, ft));
  }

  function setPropType(t)    { propType = t; }
  function setPropRot(v)     { const d = parseInt(v, 10); propRot = isNaN(d) ? 0 : ((d % 360) + 360) % 360; }
  function setPropScale(v)   { const s = parseFloat(v); propScale = (isNaN(s) || s <= 0) ? 1 : Math.max(0.25, Math.min(4, s)); }
  function setPropTexture(v) { propTexture = (v || '').trim(); }

  // ── zones (per-room material regions) ──────────────────────────────────────

  function nextZoneId() {
    const used = new Set((plan.zones || []).map(z => z.id));
    let n = 1;
    while (used.has('z' + n)) n++;
    return 'z' + n;
  }

  function newZone() {
    if (!plan) return;
    pushUndo();
    plan.zones = plan.zones || [];
    plan.zones.push({ id: nextZoneId(), rects: [] });
    activeZone = plan.zones.length - 1;
    markDirty();
    renderZoneUI();
    setTool('zone');   // straight into painting rects for the new zone
  }

  function deleteZone() {
    const zn = plan && plan.zones && plan.zones[activeZone];
    if (!zn) return;
    if (!confirm(`Delete zone "${zn.name || zn.id}"? Its surfaces fall back to the map defaults.`)) return;
    pushUndo();
    plan.zones.splice(activeZone, 1);
    activeZone = Math.min(activeZone, plan.zones.length - 1);
    markDirty();
    renderZoneUI();
  }

  function selectZone(i) {
    activeZone = parseInt(i, 10);
    renderZoneUI();
    redraw();
  }

  function setZoneField(field, value) {
    const zn = plan && plan.zones && plan.zones[activeZone];
    if (!zn) return;
    pushUndo();
    value = (value || '').trim();
    if (field === 'name') {
      if (value) zn.name = value.slice(0, 60); else delete zn.name;
    } else if (value && value !== 'none') {
      zn[field] = value;
    } else {
      delete zn[field];
    }
    markDirty();
    if (field === 'name') renderZoneUI();
  }

  function renderZoneUI() {
    const selEl = document.getElementById('fp-zone-sel');
    if (!selEl || !plan) return;
    const zones = plan.zones || [];
    selEl.innerHTML = '';
    zones.forEach((zn, i) => {
      const o = document.createElement('option');
      o.value = i;
      o.textContent = (zn.name || zn.id) + ` (${(zn.rects || []).length})`;
      selEl.appendChild(o);
    });
    selEl.disabled = !zones.length;
    if (zones.length) selEl.value = String(Math.max(0, activeZone));
    const zn = zones[activeZone];
    const nameEl = document.getElementById('fp-zone-name');
    if (nameEl) nameEl.value = (zn && zn.name) || '';
    ['floor_texture', 'wall_texture', 'wall_style'].forEach(f => {
      const el = document.getElementById('fp-zone-' + f);
      if (el) el.value = (zn && zn[f]) || (f === 'wall_style' ? 'none' : '');
    });
    const box = document.getElementById('fp-zone-fields');
    if (box) box.style.display = zn ? '' : 'none';
  }

  // ── select tool (per-segment inspector) ─────────────────────────────────────

  function selectAt(p) {
    const segDist = (list, i) =>
      distToSeg(p, { x: list[i].x1, y: list[i].y1 }, { x: list[i].x2, y: list[i].y2 });
    let best = null, bestD = Infinity;
    const wi = nearestSeg(plan.walls, p);
    if (wi !== null) { best = { kind: 'wall', idx: wi }; bestD = segDist(plan.walls, wi); }
    const di = nearestSeg(plan.doors, p);
    if (di !== null && segDist(plan.doors, di) <= bestD) {
      best = { kind: 'door', idx: di }; bestD = segDist(plan.doors, di);
    }
    (plan.props || []).forEach((pr, i) => {
      const d = Math.hypot(p.x - pr.x, p.y - pr.y);
      if (d <= Math.max(HIT_RADIUS, 0.35 * (pr.scale || 1)) && d < bestD) {
        best = { kind: 'prop', idx: i }; bestD = d;
      }
    });
    sel = best;
    renderSelUI();
    redraw();
  }

  function renderSelUI() {
    const box = document.getElementById('fp-sel-box');
    if (!box) return;
    const s = sel && plan && plan[sel.kind + 's'][sel.idx];
    box.style.display = s ? '' : 'none';
    if (!s) return;
    const isProp = sel.kind === 'prop';
    document.getElementById('fp-sel-what').textContent =
      isProp ? `Prop: ${s.type}`
             : sel.kind === 'door' ? `Door ${s.id || ''}` : `Wall #${sel.idx + 1}`;
    // walls/doors get the height row; props get the turn/size row
    document.getElementById('fp-sel-hb-row').style.display = isProp ? 'none' : '';
    document.getElementById('fp-sel-style-row').style.display = isProp ? 'none' : '';
    document.getElementById('fp-sel-prop-row').style.display = isProp ? '' : 'none';
    document.getElementById('fp-sel-texture').value = s.texture || '';
    if (isProp) {
      document.getElementById('fp-sel-rot').value = s.rot || 0;
      document.getElementById('fp-sel-scale').value = s.scale || 1;
      return;
    }
    document.getElementById('fp-sel-height').value = s.height_ft || '';
    document.getElementById('fp-sel-base').value = s.base_ft || '';
    document.getElementById('fp-sel-style').value = s.style || 'none';
    document.getElementById('fp-sel-show').checked = !!s.show;
    // base/style/show are wall-only concepts
    ['fp-sel-base', 'fp-sel-style'].forEach(id => {
      document.getElementById(id).disabled = sel.kind === 'door';
    });
    document.getElementById('fp-sel-show').disabled = sel.kind === 'door';
  }

  function applySel() {
    const s = sel && plan && plan[sel.kind + 's'][sel.idx];
    if (!s) return;
    pushUndo();
    const num = (id, lo, hi) => {
      const v = parseFloat(document.getElementById(id).value);
      return isNaN(v) ? null : Math.max(lo, Math.min(hi, v));
    };
    const tex = (document.getElementById('fp-sel-texture').value || '').trim();
    if (tex && tex !== 'none') s.texture = tex; else delete s.texture;
    if (sel.kind === 'prop') {
      const r = num('fp-sel-rot', 0, 359);
      if (r) s.rot = r; else delete s.rot;
      const sc = num('fp-sel-scale', 0.25, 4);
      if (sc !== null && sc !== 1) s.scale = sc; else delete s.scale;
      markDirty();
      return;
    }
    const h = num('fp-sel-height', 1, 100);
    if (h !== null) s.height_ft = h; else delete s.height_ft;
    if (sel.kind === 'wall') {
      const b = num('fp-sel-base', -50, 100);
      if (b) s.base_ft = b; else delete s.base_ft;
      const st = document.getElementById('fp-sel-style').value;
      if (st && st !== 'none') s.style = st; else delete s.style;
      if (document.getElementById('fp-sel-show').checked) s.show = true;
      else delete s.show;
    }
    markDirty();
  }

  function deleteSel() {
    const s = sel && plan && plan[sel.kind + 's'][sel.idx];
    if (!s) return;
    pushUndo();
    plan[sel.kind + 's'].splice(sel.idx, 1);
    sel = null;
    renderSelUI();
    markDirty();
  }

  // Fill every texture <select> in the panel from the library manifest —
  // called by the page once /ttrpg/textures/manifest has loaded.
  function setTexOptions(entries) {
    document.querySelectorAll('select.fp-tex-select').forEach(selEl => {
      const cur = selEl.value;
      // Empty = the surface's own default (walls/floors: sampled map art;
      // props: the type's builtin bitmap). Overridable per select.
      selEl.innerHTML = '<option value="">' +
        (selEl.dataset.emptyLabel || '(from map art)') + '</option>';
      const byCat = {};
      (entries || []).forEach(t => (byCat[t.category] = byCat[t.category] || []).push(t));
      Object.keys(byCat).sort().forEach(cat => {
        const og = document.createElement('optgroup');
        og.label = cat;
        byCat[cat].forEach(t => {
          const o = document.createElement('option');
          o.value = t.name;
          o.textContent = t.name;
          og.appendChild(o);
        });
        selEl.appendChild(og);
      });
      selEl.value = cur;
    });
  }

  // ── geometry helpers ───────────────────────────────────────────────────────

  function evtCell(e) {
    const rect = layer().getBoundingClientRect();
    return { x: (e.clientX - rect.left) / CELL_PX, y: (e.clientY - rect.top) / CELL_PX };
  }

  // +toFixed(2) kills float noise from 0.2 steps (3 * 0.2 = 0.6000000000000001)
  const snapTo = v => +(Math.max(0, Math.round(v / snap) * snap)).toFixed(2);

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
    pushUndo();
    const seg = s => {
      s.x1 = +fx(s.x1).toFixed(2); s.y1 = +fy(s.y1).toFixed(2);
      s.x2 = +fx(s.x2).toFixed(2); s.y2 = +fy(s.y2).toFixed(2);
    };
    plan.walls.forEach(seg);
    plan.doors.forEach(seg);
    plan.elevations.forEach(e => {
      if (e.shape === 'circle') {   // circles carry cx/cy/r, not corners
        e.cx = +fx(e.cx).toFixed(2); e.cy = +fy(e.cy).toFixed(2);
        return;
      }
      seg(e);
      if (e.x1 > e.x2) { const t = e.x1; e.x1 = e.x2; e.x2 = t; }
      if (e.y1 > e.y2) { const t = e.y1; e.y1 = e.y2; e.y2 = t; }
    });
    (plan.lights || []).forEach(lt => {
      lt.x = +fx(lt.x).toFixed(2); lt.y = +fy(lt.y).toFixed(2);
    });
    (plan.props || []).forEach(pr => {
      pr.x = +fx(pr.x).toFixed(2); pr.y = +fy(pr.y).toFixed(2);
    });
    (plan.zones || []).forEach(zn => (zn.rects || []).forEach(r => {
      seg(r);
      if (r.x1 > r.x2) { const t = r.x1; r.x1 = r.x2; r.x2 = t; }
      if (r.y1 > r.y2) { const t = r.y1; r.y1 = r.y2; r.y2 = t; }
    }));
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
      if (s.shape === 'circle') { xs.push(s.cx); ys.push(s.cy); return; }
      xs.push(s.x1, s.x2); ys.push(s.y1, s.y2);
    });
    (plan.lights || []).forEach(lt => { xs.push(lt.x); ys.push(lt.y); });
    if (!xs.length) return;
    const cx = (Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2;
    const cy = (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2;
    _xformPlan(v => cx + (v - cx) * factor, v => cy + (v - cy) * factor);
    plan.elevations.forEach(e => {   // circle radii scale with the plan
      if (e.shape === 'circle') e.r = +(e.r * factor).toFixed(2);
    });
    redraw();
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

    if (tool === 'select') { selectAt(p); return; }

    if (tool === 'zone') {
      if (!plan.zones || !plan.zones.length) { newZone(); }
      const start = { x: snapTo(p.x), y: snapTo(p.y) };
      const color = ZONE_COLORS[Math.max(0, activeZone) % ZONE_COLORS.length];
      const previewEl = svgEl('rect', {
        x: start.x * CELL_PX, y: start.y * CELL_PX, width: 0, height: 0,
        fill: color, 'fill-opacity': '0.12',
        stroke: color, 'stroke-width': 2, 'stroke-dasharray': '2 5',
      });
      layer().appendChild(previewEl);
      drag = { kind: 'zone', start, previewEl };
      return;
    }

    if (tool === 'prop') {
      pushUndo();
      const prop = { type: propType, x: snapTo(p.x), y: snapTo(p.y) };
      if (propRot) prop.rot = propRot;
      if (propScale !== 1) prop.scale = propScale;
      if (propTexture) prop.texture = propTexture;
      plan.props = plan.props || [];
      plan.props.push(prop);
      markDirty();
      return;
    }

    if (tool === 'light') {
      pushUndo();
      const light = { x: snapTo(p.x), y: snapTo(p.y), type: lightType };
      if (lightColor && lightColor !== LIGHT_META[lightType].color) light.color = lightColor;
      if (lightRadius && lightRadius !== LIGHT_META[lightType].radius_ft) {
        light.radius_ft = lightRadius;
      }
      plan.lights = plan.lights || [];
      plan.lights.push(light);
      markDirty();
      return;
    }

    if (tool === 'erase') {
      // Brush: erase at the press point, then keep erasing whatever the
      // pointer sweeps over until release. The cursor ring lives in the draw
      // OVERLAY (a div) because every removal redraws the SVG layer, which
      // would wipe a ring placed there.
      pushUndo();
      const ring = document.createElement('div');
      const rPx = HIT_RADIUS * CELL_PX;
      ring.style.cssText =
        'position:absolute;pointer-events:none;border:2px solid #e66;' +
        'border-radius:50%;box-shadow:0 0 6px rgba(230,102,102,.7);' +
        `width:${rPx * 2}px;height:${rPx * 2}px;` +
        `left:${p.x * CELL_PX - rPx}px;top:${p.y * CELL_PX - rPx}px;`;
      overlay().appendChild(ring);
      drag = { kind: 'erase', previewEl: ring };
      eraseAt(p);
      return;
    }
    if (tool === 'door')  { doorAt(p);  return; }

    if (tool === 'wall') {
      const start = { x: snapTo(p.x), y: snapTo(p.y) };
      const previewEl = svgEl('line', {
        x1: start.x * CELL_PX, y1: start.y * CELL_PX,
        x2: start.x * CELL_PX, y2: start.y * CELL_PX,
        stroke: 'var(--ttrpg-accent, #c9a84c)', 'stroke-width': 5, 'stroke-linecap': 'round',
      });
      layer().appendChild(previewEl);
      drag = { kind: 'wall', start, previewEl };
    } else if (tool === 'rect') {
      const start = { x: snapTo(p.x), y: snapTo(p.y) };
      const previewEl = svgEl('rect', {
        x: start.x * CELL_PX, y: start.y * CELL_PX, width: 0, height: 0,
        fill: 'none', stroke: 'var(--ttrpg-accent, #c9a84c)', 'stroke-width': 5,
      });
      layer().appendChild(previewEl);
      drag = { kind: 'rect', start, previewEl };
    } else if (tool === 'circle') {
      const start = { x: snapTo(p.x), y: snapTo(p.y) };   // center
      const previewEl = svgEl('circle', {
        cx: start.x * CELL_PX, cy: start.y * CELL_PX, r: 0,
        fill: 'none', stroke: 'var(--ttrpg-accent, #c9a84c)', 'stroke-width': 5,
      });
      layer().appendChild(previewEl);
      drag = { kind: 'circle', start, previewEl };
    } else if (tool === 'elev') {
      const start = { x: snapTo(p.x), y: snapTo(p.y) };
      const previewEl = svgEl('rect', {
        x: start.x * CELL_PX, y: start.y * CELL_PX, width: 0, height: 0,
        fill: '#4a9eff', 'fill-opacity': '0.2',
        stroke: '#4a9eff', 'stroke-width': 2, 'stroke-dasharray': '6 4',
      });
      layer().appendChild(previewEl);
      drag = { kind: 'elev', start, previewEl };
    } else if (tool === 'elevc') {
      const start = { x: snapTo(p.x), y: snapTo(p.y) };   // center
      const previewEl = svgEl('circle', {
        cx: start.x * CELL_PX, cy: start.y * CELL_PX, r: 0,
        fill: '#4a9eff', 'fill-opacity': '0.2',
        stroke: '#4a9eff', 'stroke-width': 2, 'stroke-dasharray': '6 4',
      });
      layer().appendChild(previewEl);
      drag = { kind: 'elevc', start, previewEl };
    }
  }

  function onMove(e) {
    if (!drag) return;
    const p = evtCell(e);
    if (drag.kind === 'erase') {
      const rPx = HIT_RADIUS * CELL_PX;
      drag.previewEl.style.left = (p.x * CELL_PX - rPx) + 'px';
      drag.previewEl.style.top  = (p.y * CELL_PX - rPx) + 'px';
      eraseAt(p);   // clears anything the brush touches along the sweep
      return;
    }
    if (drag.kind === 'wall') {
      let end = { x: snapTo(p.x), y: snapTo(p.y) };
      if (e.shiftKey) {   // axis lock to the dominant direction
        if (Math.abs(end.x - drag.start.x) >= Math.abs(end.y - drag.start.y)) end.y = drag.start.y;
        else end.x = drag.start.x;
      }
      drag.end = end;
      drag.previewEl.setAttribute('x2', end.x * CELL_PX);
      drag.previewEl.setAttribute('y2', end.y * CELL_PX);
    } else if (drag.kind === 'rect') {
      const end = { x: snapTo(p.x), y: snapTo(p.y) };
      drag.end = end;
      const x1 = Math.min(drag.start.x, end.x), y1 = Math.min(drag.start.y, end.y);
      drag.previewEl.setAttribute('x', x1 * CELL_PX);
      drag.previewEl.setAttribute('y', y1 * CELL_PX);
      drag.previewEl.setAttribute('width',  Math.abs(end.x - drag.start.x) * CELL_PX);
      drag.previewEl.setAttribute('height', Math.abs(end.y - drag.start.y) * CELL_PX);
    } else if (drag.kind === 'circle' || drag.kind === 'elevc') {
      const r = snapTo(Math.hypot(p.x - drag.start.x, p.y - drag.start.y));
      drag.r = r;
      drag.end = p;   // onUp requires an end point to commit any drag
      drag.previewEl.setAttribute('r', r * CELL_PX);
    } else if (drag.kind === 'elev' || drag.kind === 'zone') {
      const end = { x: snapTo(p.x), y: snapTo(p.y) };
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

    // walls from any shape tool carry the panel's height when it differs
    const pushWall = (x1, y1, x2, y2) => {
      const seg = { x1: +x1.toFixed(2), y1: +y1.toFixed(2),
                    x2: +x2.toFixed(2), y2: +y2.toFixed(2) };
      if (wallHeightFt !== (plan.default_wall_height_ft || 10)) seg.height_ft = wallHeightFt;
      if (wallShow) seg.show = true;   // players see it on the 2D map
      plan.walls.push(seg);
    };

    if (d.kind === 'wall') {
      if (d.start.x === d.end.x && d.start.y === d.end.y) return;
      pushUndo();
      pushWall(d.start.x, d.start.y, d.end.x, d.end.y);
      markDirty();
    } else if (d.kind === 'rect') {
      const x1 = Math.min(d.start.x, d.end.x), x2 = Math.max(d.start.x, d.end.x);
      const y1 = Math.min(d.start.y, d.end.y), y2 = Math.max(d.start.y, d.end.y);
      if (x1 === x2 || y1 === y2) return;
      pushUndo();
      pushWall(x1, y1, x2, y1); pushWall(x2, y1, x2, y2);
      pushWall(x2, y2, x1, y2); pushWall(x1, y2, x1, y1);
      markDirty();
    } else if (d.kind === 'circle') {
      const r = d.r || 0;
      if (r < snap) return;
      pushUndo();
      // ~12 segments per cell of radius reads smoothly without wall spam
      const n = Math.max(12, Math.min(48, Math.round(r * 12)));
      let px = d.start.x + r, py = d.start.y;
      for (let i = 1; i <= n; i++) {
        const a = (i / n) * Math.PI * 2;
        const nx = d.start.x + r * Math.cos(a), ny = d.start.y + r * Math.sin(a);
        pushWall(px, py, nx, ny);
        px = nx; py = ny;
      }
      markDirty();
    } else if (d.kind === 'elev') {
      const x1 = Math.min(d.start.x, d.end.x), x2 = Math.max(d.start.x, d.end.x);
      const y1 = Math.min(d.start.y, d.end.y), y2 = Math.max(d.start.y, d.end.y);
      if (x1 === x2 || y1 === y2 || !elevFt) return;
      pushUndo();
      plan.elevations.push({ x1, y1, x2, y2, floor_ft: elevFt });
      markDirty();
    } else if (d.kind === 'elevc') {
      if (!d.r || d.r < snap || !elevFt) return;
      pushUndo();
      plan.elevations.push({ shape: 'circle', cx: d.start.x, cy: d.start.y,
                             r: d.r, floor_ft: elevFt });
      markDirty();
    } else if (d.kind === 'zone') {
      const zn = plan.zones && plan.zones[activeZone];
      if (!zn) return;
      const x1 = Math.min(d.start.x, d.end.x), x2 = Math.max(d.start.x, d.end.x);
      const y1 = Math.min(d.start.y, d.end.y), y2 = Math.max(d.start.y, d.end.y);
      if (x1 === x2 || y1 === y2) return;
      if ((zn.rects || []).length >= 20) { alert('A zone holds at most 20 rects.'); return; }
      pushUndo();
      zn.rects.push({ x1, y1, x2, y2 });
      markDirty();
      renderZoneUI();
    }
  }

  // Removes the nearest wall/door (or covering elevation) within brush range.
  // Returns true when something was removed so the brush can keep clearing a
  // spot until it's empty.
  function eraseOne(p) {
    // Lights and props are points — check them before the segment hit-tests.
    const lights = plan.lights || [];
    for (let li = 0; li < lights.length; li++) {
      if (Math.hypot(p.x - lights[li].x, p.y - lights[li].y) <= HIT_RADIUS) {
        lights.splice(li, 1);
        markDirty();
        return true;
      }
    }
    const props = plan.props || [];
    for (let pi = 0; pi < props.length; pi++) {
      const r = Math.max(HIT_RADIUS, 0.35 * (props[pi].scale || 1));
      if (Math.hypot(p.x - props[pi].x, p.y - props[pi].y) <= r) {
        props.splice(pi, 1);
        markDirty();
        return true;
      }
    }
    const wi = nearestSeg(plan.walls, p);
    const di = nearestSeg(plan.doors, p);
    // Prefer whichever is genuinely closer when both are in range.
    if (di !== null && (wi === null ||
        distToSeg(p, { x: plan.doors[di].x1, y: plan.doors[di].y1 }, { x: plan.doors[di].x2, y: plan.doors[di].y2 }) <=
        distToSeg(p, { x: plan.walls[wi].x1, y: plan.walls[wi].y1 }, { x: plan.walls[wi].x2, y: plan.walls[wi].y2 }))) {
      plan.doors.splice(di, 1);
      markDirty();
      return true;
    }
    if (wi !== null) { plan.walls.splice(wi, 1); markDirty(); return true; }
    const ei = plan.elevations.findIndex(e2 => e2.shape === 'circle'
      ? Math.hypot(p.x - e2.cx, p.y - e2.cy) <= e2.r
      : (p.x >= e2.x1 && p.x < e2.x2 && p.y >= e2.y1 && p.y < e2.y2));
    if (ei !== -1) { plan.elevations.splice(ei, 1); markDirty(); return true; }
    return false;
  }

  function eraseAt(p) {
    let guard = 200;                       // plan caps make this unreachable
    while (guard-- > 0 && eraseOne(p)) {}  // clear EVERYTHING the brush touches
  }

  function doorAt(p) {
    const di = nearestSeg(plan.doors, p);
    if (di !== null) {   // door -> wall
      pushUndo();
      const d = plan.doors.splice(di, 1)[0];
      const seg = { x1: d.x1, y1: d.y1, x2: d.x2, y2: d.y2 };
      plan.walls.push(seg);
      markDirty();
      return;
    }
    const wi = nearestSeg(plan.walls, p);
    if (wi !== null) {   // wall -> door
      pushUndo();
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
    // Same floating-drag behavior as the FX / dice / notes panels
    // (makeDraggable comes from battlemap.js, which loads before this file).
    if (typeof makeDraggable === 'function') {
      makeDraggable(document.getElementById('fp-panel'),
                    document.getElementById('fp-drag-handle'));
    }
    const snapEl = document.getElementById('fp-snap');
    if (snapEl) snapEl.value = String(snap);   // restored from localStorage
    ov.addEventListener('pointerdown', onDown);
    ov.addEventListener('pointermove', onMove);
    ov.addEventListener('pointerup', onUp);
    ov.addEventListener('pointerleave', () => {
      if (drag) { drag.previewEl.remove(); drag = null; }
    });
    window.addEventListener('beforeunload', e => {
      if (dirty) { e.preventDefault(); e.returnValue = ''; }
    });
    // Ctrl+Z / Ctrl+Y (and Ctrl+Shift+Z) while the panel is open — never
    // while typing in an input, and never stealing the browser's undo there.
    document.addEventListener('keydown', e => {
      const panel = document.getElementById('fp-panel');
      if (!panel || panel.style.display !== 'block') return;
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
      else if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); redo(); }
    });
  })();

  return {
    onState, redraw, save, revert, setTool, setWallHeight, setWallStyle,
    setWallShow, setElevHeight, setSnap, setLightType, setLightColor,
    setLightRadius, setPropType, setPropRot, setPropScale, setPropTexture,
    undo, redo, nudge, scalePlan,
    newZone, deleteZone, selectZone, setZoneField,
    applySel, deleteSel, setTexOptions, getDraft,
    toggle: togglePanel, close: closePanel,
    isDirty: () => dirty,
  };
})();

// Template onclick shims (match the fx-panel naming convention)
function toggleFpPanel() { BMFP.toggle(); }
function closeFpPanel()  { BMFP.close(); }

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
  let elevRot = 0;             // degrees clockwise applied to new elevation rects
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
    syncShow2dUI();
  }

  function redo() {
    if (!redoStack.length || !plan) return;
    undoStack.push(JSON.stringify(plan));
    plan = JSON.parse(redoStack.pop());
    markDirty();
    updateUndoButtons();
    syncShow2dUI();
  }

  // ── Plan-level player 2D visibility (all walls+doors / all props) ──────────

  function setShow2d(which, on) {
    if (!plan) return;
    pushUndo();
    const key = which === 'props' ? 'show_props_2d' : 'show_walls_2d';
    if (on) plan[key] = true; else delete plan[key];
    markDirty();
  }

  function syncShow2dUI() {
    const w = document.getElementById('fp-show2d-walls');
    const p = document.getElementById('fp-show2d-props');
    if (w) w.checked = !!(plan && plan.show_walls_2d);
    if (p) p.checked = !!(plan && plan.show_props_2d);
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
        renderSkyUI();
        const eEl = document.getElementById('fp-elev-height');
        if (eEl) eEl.value = elevFt;     // remembered from last session
        redraw();
        updateStatus();
        renderZoneUI();
        renderSelUI();
        syncShow2dUI();
      })
      .catch(() => {});
  }

  // ── autosave ───────────────────────────────────────────────────────────────
  // Every edit (markDirty) schedules a save AUTOSAVE_MS later; edits made
  // while a save is in flight trigger one more save when it lands. The
  // working copy, selection and undo history are all kept across saves —
  // only the server's normalized plan is adopted, and only when nothing
  // changed underneath it. The manual Save button just saves right now.
  const AUTOSAVE_MS = 1200;
  let saveTimer = null;
  let saving = false;
  let editSeq = 0;             // bumped on every edit
  let saveError = '';          // last rejection/network message for the status line

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(save, AUTOSAVE_MS);
  }

  function serializePlan() {
    plan.schema_version = 2;
    plan.format = 'sceneplay-floorplan';
    plan.grid = { cols: GRID_COLS, rows: GRID_ROWS };
    plan.default_wall_height_ft = wallHeightFt;
    // A room that hasn't been painted yet (+ New room, then a pause) has no
    // areas; the server rejects such zones, so keep them local until they
    // have a rect instead of letting an autosave throw the new room away.
    const out = Object.assign({}, plan, {
      zones: (plan.zones || []).filter(z => (z.rects || []).length),
    });
    return JSON.stringify({ floorplan: out });
  }

  function save() {
    if (!plan || !dirty) return;
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    if (saving) return;          // the in-flight save re-runs when it lands
    const seq = editSeq;
    saving = true;
    updateStatus();
    fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: serializePlan(),
    }).then(r => r.json())
      .then(d => {
        saving = false;
        if (!d.ok) {
          saveError = 'Not saved: ' + (d.errors || ['save failed']).join('; ');
          updateStatus();
          return;
        }
        saveError = '';
        version = d.version || version;
        if (editSeq === seq) {
          // Adopt the server's normalized geometry (clamping, rounding) —
          // element order is preserved, so the selection and undo stacks
          // still point at the same things.
          if (d.floorplan) {
            const localZones = plan.zones || [];
            const activeId = localZones[activeZone] ? localZones[activeZone].id : null;
            const unpainted = localZones.filter(z => !(z.rects || []).length);
            plan = d.floorplan;
            plan.lights = plan.lights || [];
            plan.props  = plan.props  || [];
            plan.zones  = (plan.zones || []).concat(unpainted);   // still being drawn
            if (activeId !== null) {
              const ai = plan.zones.findIndex(z => z.id === activeId);
              activeZone = ai === -1 ? Math.min(activeZone, plan.zones.length - 1) : ai;
            }
            renderZoneUI();
          }
          dirty = false;
          // The 3D draft preview now matches the saved plan: release it so
          // the viewer follows the version bump like every other viewer.
          if (window.BM3D && BM3D.setDraftFloorplan) BM3D.setDraftFloorplan(null);
          redraw();
          renderSelUI();
        } else {
          save();                // edits landed mid-flight
        }
        updateStatus();
      })
      .catch(() => {
        saving = false;
        saveError = 'Save failed (network) — retrying';
        updateStatus();
        scheduleSave();
      });
  }

  function revert() {
    if (dirty && !confirm('Discard edits not yet autosaved?')) return;
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
    editSeq++;
    redraw();
    updateStatus();
    scheduleSave();
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
      (saveError ? `  · ${saveError}` : saving ? '  · saving…' : dirty ? '  · autosave pending' : '');
    el.style.color = saveError ? 'var(--bs-danger, #d9534f)' : dirty ? 'var(--ttrpg-accent)' : '';
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
        const attrs = Object.assign({
          x: px(e.x1), y: px(e.y1),
          width: px(e.x2 - e.x1), height: px(e.y2 - e.y1) }, fillAttrs);
        const ecx = px((e.x1 + e.x2) / 2), ecy = px((e.y1 + e.y2) / 2);
        if (e.rot) attrs.transform = `rotate(${e.rot} ${ecx} ${ecy})`;
        g.appendChild(svgEl('rect', attrs));
        // rotated rects label at the center (the corner may sit outside the
        // rotated outline); axis-aligned keep the tidy corner label
        lx = e.rot ? ecx - 14 : px(e.x1) + 6;
        ly = e.rot ? ecy + 4 : px(e.y1) + 16;
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
        // rotate handle: drag it to spin the prop (15° snaps); the prop
        // body itself drags to move
        const h = _propRotHandle(s);
        svg.appendChild(svgEl('line', {
          x1: px(s.x), y1: px(s.y), x2: px(h.x), y2: px(h.y),
          stroke: '#3df0c8', 'stroke-width': 1.5, 'stroke-dasharray': '3 3',
        }));
        const knob = svgEl('circle', {
          cx: px(h.x), cy: px(h.y), r: 6,
          fill: '#3df0c8', stroke: '#083f33', 'stroke-width': 2,
        });
        const title = svgEl('title', {});
        title.textContent = 'Drag to rotate (drag the prop itself to move it)';
        knob.appendChild(title);
        svg.appendChild(knob);
      } else if (sel.kind === 'light') {
        const ring = svgEl('circle', {
          cx: px(s.x), cy: px(s.y), r: 13,
          fill: '#3df0c8', 'fill-opacity': '0.25',
          stroke: '#3df0c8', 'stroke-width': 2.5,
        });
        const title = svgEl('title', {});
        title.textContent = 'Drag to move the light';
        ring.appendChild(title);
        svg.appendChild(ring);
      } else if (sel.kind === 'elevation') {
        if (s.shape === 'circle') {
          svg.appendChild(svgEl('circle', {
            cx: px(s.cx), cy: px(s.cy), r: px(s.r),
            fill: 'none', stroke: '#3df0c8', 'stroke-width': 3,
          }));
        } else {
          const ecx = px((s.x1 + s.x2) / 2), ecy = px((s.y1 + s.y2) / 2);
          const hl = svgEl('rect', {
            x: px(s.x1), y: px(s.y1),
            width: px(s.x2 - s.x1), height: px(s.y2 - s.y1),
            fill: 'none', stroke: '#3df0c8', 'stroke-width': 3,
          });
          if (s.rot) hl.setAttribute('transform', `rotate(${s.rot} ${ecx} ${ecy})`);
          svg.appendChild(hl);
          // rotate handle above the rect's top edge, turning with it —
          // same manipulation language as props
          const h = _elevRotHandle(s);
          svg.appendChild(svgEl('line', {
            x1: ecx, y1: ecy, x2: px(h.x), y2: px(h.y),
            stroke: '#3df0c8', 'stroke-width': 1.5, 'stroke-dasharray': '3 3',
          }));
          const knob = svgEl('circle', {
            cx: px(h.x), cy: px(h.y), r: 6,
            fill: '#3df0c8', stroke: '#083f33', 'stroke-width': 2,
          });
          const title = svgEl('title', {});
          title.textContent = 'Drag to rotate (drag the area itself to move it)';
          knob.appendChild(title);
          svg.appendChild(knob);
        }
      } else {
        svg.appendChild(svgEl('line', {
          x1: px(s.x1), y1: px(s.y1), x2: px(s.x2), y2: px(s.y2),
          stroke: '#3df0c8', 'stroke-width': 11, 'stroke-linecap': 'round',
          'stroke-opacity': '0.45',
        }));
        // endpoint knobs: drag one to reshape/rotate the segment; drag the
        // segment body to slide the whole wall/door
        [1, 2].forEach(n => {
          const knob = svgEl('circle', {
            cx: px(s['x' + n]), cy: px(s['y' + n]), r: 6,
            fill: '#3df0c8', stroke: '#083f33', 'stroke-width': 2,
          });
          const title = svgEl('title', {});
          title.textContent =
            'Drag to move this end (drag the segment itself to slide it)';
          knob.appendChild(title);
          svg.appendChild(knob);
        });
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
    const h = Math.max(1, Math.min(100, parseInt(v) || 10));
    if (h === wallHeightFt) return;
    wallHeightFt = h;
    if (plan) markDirty();       // default_wall_height_ft saves with the plan
  }

  function setWallStyle(v) {
    if (!plan) return;
    pushUndo();
    if (v === 'none') delete plan.wall_style;
    else plan.wall_style = v;
    markDirty();
  }

  // Map-wide sky dome: {time, weather}. Choosing a time creates it; "None"
  // removes it (weather alone means nothing without a time of day).
  function setSky(field, v) {
    if (!plan) return;
    pushUndo();
    const sky = Object.assign({ weather: 'clear' }, plan.sky || {});
    sky[field] = v;
    if (!sky.time) delete plan.sky; else plan.sky = { time: sky.time, weather: sky.weather || 'clear' };
    markDirty();
    renderSkyUI();
  }

  function renderSkyUI() {
    const t = document.getElementById('fp-sky-time');
    const w = document.getElementById('fp-sky-weather');
    if (t) t.value = (plan && plan.sky && plan.sky.time) || '';
    if (w) { w.value = (plan && plan.sky && plan.sky.weather) || 'clear'; w.disabled = !(plan && plan.sky); }
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

  function setElevRot(v) {
    const d = parseInt(v, 10);
    elevRot = isNaN(d) ? 0 : ((d % 360) + 360) % 360;
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
    if (tool !== 'zone') setTool('zone');   // straight into painting — setTool toggles, so don't flip it OFF
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

  // Remove ONE painted area from the active zone (the zone itself stays, even
  // with no areas, so it can be repainted). Before this the only way out of
  // a mis-painted second area was deleting the whole room.
  function deleteZoneRect(ri) {
    const zn = plan && plan.zones && plan.zones[activeZone];
    if (!zn || !zn.rects || !zn.rects[ri]) return;
    pushUndo();
    zn.rects.splice(ri, 1);
    markDirty();
    renderZoneUI();
  }

  // Erase-tool fallback: the zone area under the pointer (active zone first,
  // then any zone). Only called when nothing else was under the brush.
  function eraseZoneRectAt(p) {
    const zones = plan.zones || [];
    const order = activeZone >= 0 ? [activeZone, ...zones.map((_, i) => i).filter(i => i !== activeZone)]
                                  : zones.map((_, i) => i);
    for (const zi of order) {
      const rects = (zones[zi] && zones[zi].rects) || [];
      const ri = rects.findIndex(r => p.x >= r.x1 && p.x < r.x2 && p.y >= r.y1 && p.y < r.y2);
      if (ri !== -1) {
        pushUndo();
        rects.splice(ri, 1);
        activeZone = zi;
        markDirty();
        renderZoneUI();
        return true;
      }
    }
    return false;
  }

  function setZoneField(field, value) {
    const zn = plan && plan.zones && plan.zones[activeZone];
    if (!zn) return;
    pushUndo();
    value = (value || '').trim();
    if (field === 'name') {
      if (value) zn.name = value.slice(0, 60); else delete zn.name;
    } else if (field === 'ceiling_ft') {
      const n = parseFloat(value);
      if (isFinite(n) && n > 0) zn.ceiling_ft = Math.min(60, Math.max(7, n));
      else delete zn.ceiling_ft;
      renderZoneUI();               // show the clamped value
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
      const n = (zn.rects || []).length;
      o.textContent = (zn.name || zn.id) + ` — ${n} area${n === 1 ? '' : 's'}`;
      selEl.appendChild(o);
    });
    selEl.disabled = !zones.length;
    if (zones.length) selEl.value = String(Math.max(0, activeZone));
    const zn = zones[activeZone];
    const nameEl = document.getElementById('fp-zone-name');
    if (nameEl) nameEl.value = (zn && zn.name) || '';
    ['floor_texture', 'wall_texture', 'ceiling_texture', 'wall_style'].forEach(f => {
      const el = document.getElementById('fp-zone-' + f);
      if (el) el.value = (zn && zn[f]) || (f === 'wall_style' ? 'none' : '');
    });
    const cftEl = document.getElementById('fp-zone-ceiling_ft');
    if (cftEl) cftEl.value = (zn && zn.ceiling_ft) || '';
    refreshTexFaces();
    const box = document.getElementById('fp-zone-fields');
    if (box) box.style.display = zn ? '' : 'none';
    // one line per painted area with its own delete — a room is often two
    // or three rects, and a mis-drawn one must be removable on its own
    const list = document.getElementById('fp-zone-rects');
    if (list) {
      list.innerHTML = '';
      const rects = (zn && zn.rects) || [];
      if (zn && !rects.length) {
        list.textContent = 'No areas yet — use Paint and drag over this room\'s floor.';
      }
      rects.forEach((r, ri) => {
        const row = document.createElement('div');
        row.className = 'd-flex align-items-center gap-2';
        const txt = document.createElement('span');
        txt.className = 'flex-grow-1';
        txt.textContent = `Area ${ri + 1}: ${r.x2 - r.x1}×${r.y2 - r.y1} squares at (${r.x1}, ${r.y1})`;
        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'btn btn-sm btn-outline-danger py-0 px-1';
        del.title = 'Remove this area from the room';
        del.textContent = '\u2715';
        del.onclick = () => deleteZoneRect(ri);
        row.appendChild(txt);
        row.appendChild(del);
        list.appendChild(row);
      });
    }
  }

  // ── select tool (per-segment inspector + prop direct manipulation) ────────

  const ROT_HANDLE_PX = 26;   // screen px from the prop's center

  // The rotate handle sits "above" the prop and turns with it, so the
  // handle's direction IS the prop's facing.
  function _propRotHandle(pr) {
    const a = ((pr.rot || 0) - 90) * Math.PI / 180;
    return { x: pr.x + Math.cos(a) * ROT_HANDLE_PX / CELL_PX,
             y: pr.y + Math.sin(a) * ROT_HANDLE_PX / CELL_PX };
  }

  // Elevation-rect rotate handle: just past the midpoint of the rect's top
  // edge (in its rotated frame), so it clears the outline whatever the size.
  function _elevRotHandle(e) {
    const cx = (e.x1 + e.x2) / 2, cy = (e.y1 + e.y2) / 2;
    const a = ((e.rot || 0) - 90) * Math.PI / 180;
    const d = (cy - e.y1) + ROT_HANDLE_PX / CELL_PX;
    return { x: cx + Math.cos(a) * d, y: cy + Math.sin(a) * d };
  }

  // Commit a drag's pre-state to the undo stack on its FIRST real change —
  // a drag that never moves anything leaves no undo entry behind.
  function _dragCommit(d) {
    if (d.pushed) return;
    undoStack.push(d.snap);
    if (undoStack.length > UNDO_MAX) undoStack.shift();
    redoStack = [];
    updateUndoButtons();
    d.pushed = true;
  }

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
    // Lights: the fixture dot, not its reach. A click ON the dot wins over a
    // wall running through the same spot — sconces sit on walls, and the
    // wall is always the "nearer" segment otherwise.
    (plan.lights || []).forEach((lt, i) => {
      const d = Math.hypot(p.x - lt.x, p.y - lt.y);
      if (d <= HIT_RADIUS && (d < bestD || d <= HIT_RADIUS * 0.8)) {
        best = { kind: 'light', idx: i }; bestD = Math.min(bestD, d);
      }
    });
    // Elevations claim the click LAST — they cover whole areas, so anything
    // sitting on them (walls, props, lights) must stay selectable. Later
    // entries win, matching floorAt()'s last-wins stacking.
    if (!best) {
      (plan.elevations || []).forEach((ev, i) => {
        if (_elevContains(ev, p)) best = { kind: 'elevation', idx: i };
      });
    }
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
    const isLight = sel.kind === 'light';
    const isElev = sel.kind === 'elevation';
    document.getElementById('fp-sel-what').textContent =
      isProp ? `Prop: ${s.type}`
             : isLight ? `Light: ${s.type}`
             : isElev ? `Elevation: ${s.floor_ft < 0 ? 'pit' : 'platform'}` +
                        (s.shape === 'circle' ? ' ⬤' : '')
             : sel.kind === 'door' ? `Door ${s.id || ''}` : `Wall #${sel.idx + 1}`;
    // walls/doors get the height row; props the turn/size row; lights and
    // elevations their own rows (no texture). inline flex/none (NOT the d-flex
    // class: its !important would beat an inline display:none and the rows
    // would never hide)
    document.getElementById('fp-sel-hb-row').style.display = (isProp || isLight || isElev) ? 'none' : 'flex';
    document.getElementById('fp-sel-style-row').style.display = (isProp || isLight || isElev) ? 'none' : 'flex';
    document.getElementById('fp-sel-prop-row').style.display = isProp ? 'flex' : 'none';
    document.getElementById('fp-sel-tex-row').style.display = (isLight || isElev) ? 'none' : 'flex';
    document.getElementById('fp-sel-elev-row').style.display = isElev ? 'flex' : 'none';
    document.getElementById('fp-sel-light-row').style.display = isLight ? 'flex' : 'none';
    document.getElementById('fp-sel-light-row2').style.display = isLight ? 'flex' : 'none';
    document.getElementById('fp-sel-light-row3').style.display = isLight ? 'flex' : 'none';
    if (isElev) {
      document.getElementById('fp-sel-elev-ft').value = s.floor_ft;
      const rotEl = document.getElementById('fp-sel-elev-rot');
      rotEl.value = s.rot || 0;
      rotEl.disabled = s.shape === 'circle';   // circles have no orientation
      return;
    }
    if (isLight) {
      const meta = LIGHT_META[s.type] || LIGHT_META.torch;
      document.getElementById('fp-sel-light-type').value = s.type || 'torch';
      document.getElementById('fp-sel-light-color').value = s.color || meta.color;
      document.getElementById('fp-sel-light-radius').value = s.radius_ft || '';
      document.getElementById('fp-sel-light-radius').placeholder = meta.radius_ft;
      document.getElementById('fp-sel-light-height').value = s.height_ft ?? '';
      document.getElementById('fp-sel-light-intensity').value = s.intensity ?? '';
      document.getElementById('fp-sel-light-flicker').checked = s.flicker !== false;
      return;
    }
    document.getElementById('fp-sel-texture').value = s.texture || '';
    refreshTexFaces();
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
    if (sel.kind === 'elevation') {
      const ft = num('fp-sel-elev-ft', -50, 100);
      if (ft !== null && ft) s.floor_ft = ft;
      if (s.shape !== 'circle') {
        const r = num('fp-sel-elev-rot', 0, 359);
        if (r) s.rot = r; else delete s.rot;
      }
      markDirty();
      renderSelUI();
      return;
    }
    if (sel.kind === 'light') {
      const type = document.getElementById('fp-sel-light-type').value;
      if (LIGHT_META[type]) s.type = type;
      const meta = LIGHT_META[s.type] || LIGHT_META.torch;
      const color = (document.getElementById('fp-sel-light-color').value || '').toLowerCase();
      if (color && color !== meta.color) s.color = color; else delete s.color;
      const r = num('fp-sel-light-radius', 5, 120);
      if (r !== null && r !== meta.radius_ft) s.radius_ft = r; else delete s.radius_ft;
      const h = num('fp-sel-light-height', 0, 50);
      if (h !== null) s.height_ft = h; else delete s.height_ft;
      const it = num('fp-sel-light-intensity', 0.1, 3);
      if (it !== null && it !== 1) s.intensity = it; else delete s.intensity;
      if (document.getElementById('fp-sel-light-flicker').checked) delete s.flicker;
      else s.flicker = false;
      markDirty();
      renderSelUI();
      return;
    }
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
      buildTexPicker(selEl, entries || []);
    });
  }

  // ── texture picker: a dropdown that shows the bitmaps ─────────────────────
  // The <select> stays as the value holder (every onchange handler and
  // `.value` read in this file keeps working); it is hidden and a button
  // with the current texture's thumbnail + name stands in for it. The menu
  // is a fixed-position list (so the scrolling panel can't clip it) of
  // thumbnail + name rows grouped by category.
  let texMenu = null;        // the single open menu, if any
  const texByName = {};

  function texFace(btn, selEl) {
    const name = selEl.value || '';
    const t = texByName[name];
    const thumb = btn.querySelector('.fp-tex-thumb');
    const label = btn.querySelector('.fp-tex-name');
    thumb.style.backgroundImage = t ? `url("${t.url}")` : '';
    thumb.classList.toggle('fp-tex-none', !t);
    const emptyLabel = selEl.dataset.emptyLabel || '(from map art)';
    label.textContent = t ? t.name : (selEl.options[0] ? selEl.options[0].textContent : emptyLabel);
    btn.title = t ? `${t.name} (${t.category})` : emptyLabel;
  }

  function closeTexMenu() {
    if (texMenu) { texMenu.remove(); texMenu = null; }
  }

  function openTexMenu(btn, selEl, entries) {
    closeTexMenu();
    const menu = document.createElement('div');
    menu.className = 'fp-tex-menu';
    const addRow = (value, label, t) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'fp-tex-row' + (selEl.value === value ? ' active' : '');
      const th = document.createElement('span');
      th.className = 'fp-tex-thumb' + (t ? '' : ' fp-tex-none');
      if (t) th.style.backgroundImage = `url("${t.url}")`;
      const nm = document.createElement('span');
      nm.className = 'fp-tex-name';
      nm.textContent = label;
      row.appendChild(th);
      row.appendChild(nm);
      row.onclick = () => {
        selEl.value = value;
        selEl.dispatchEvent(new Event('change', { bubbles: true }));   // runs the inline onchange
        texFace(btn, selEl);
        closeTexMenu();
      };
      menu.appendChild(row);
    };
    addRow('', selEl.options[0] ? selEl.options[0].textContent : '(from map art)', null);
    const byCat = {};
    entries.forEach(t => (byCat[t.category] = byCat[t.category] || []).push(t));
    Object.keys(byCat).sort().forEach(cat => {
      const h = document.createElement('div');
      h.className = 'fp-tex-cat';
      h.textContent = cat;
      menu.appendChild(h);
      byCat[cat].forEach(t => addRow(t.name, t.name, t));
    });
    // fixed position under the button; flip above it when near the bottom
    const r = btn.getBoundingClientRect();
    const maxH = 260;
    menu.style.left = Math.max(4, Math.min(r.left, window.innerWidth - 240)) + 'px';
    if (r.bottom + maxH > window.innerHeight && r.top > maxH) {
      menu.style.bottom = (window.innerHeight - r.top + 2) + 'px';
    } else {
      menu.style.top = (r.bottom + 2) + 'px';
    }
    document.body.appendChild(menu);
    texMenu = menu;
    const active = menu.querySelector('.fp-tex-row.active');
    if (active) active.scrollIntoView({ block: 'center' });
    setTimeout(() => {
      const onDoc = e => { if (!menu.contains(e.target) && e.target !== btn) { closeTexMenu(); cleanup(); } };
      const onKey = e => { if (e.key === 'Escape') { closeTexMenu(); cleanup(); } };
      const cleanup = () => { document.removeEventListener('pointerdown', onDoc, true);
                              document.removeEventListener('keydown', onKey, true); };
      document.addEventListener('pointerdown', onDoc, true);
      document.addEventListener('keydown', onKey, true);
    }, 0);
  }

  function buildTexPicker(selEl, entries) {
    entries.forEach(t => { texByName[t.name] = t; });
    let btn = selEl.nextElementSibling;
    if (!btn || !btn.classList.contains('fp-tex-btn')) {
      btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'fp-tex-btn form-select form-select-sm';
      btn.innerHTML = '<span class="fp-tex-thumb"></span><span class="fp-tex-name"></span>';
      btn.onclick = e => { e.preventDefault(); texMenu ? closeTexMenu() : openTexMenu(btn, selEl, entries); };
      selEl.insertAdjacentElement('afterend', btn);
      selEl.classList.add('fp-tex-hidden');
    }
    btn.onclick = e => { e.preventDefault(); texMenu ? closeTexMenu() : openTexMenu(btn, selEl, entries); };
    texFace(btn, selEl);
  }

  // Called wherever this file sets a texture <select>'s value programmatically
  // (programmatic value changes fire no event the button could listen for).
  function refreshTexFaces() {
    document.querySelectorAll('select.fp-tex-select').forEach(selEl => {
      const btn = selEl.nextElementSibling;
      if (btn && btn.classList.contains('fp-tex-btn')) texFace(btn, selEl);
    });
  }

  // ── geometry helpers ───────────────────────────────────────────────────────

  function evtCell(e) {
    const rect = layer().getBoundingClientRect();
    // Clamped to the map: a drag that runs off the edge (or off the window —
    // see the pointer capture in init) finishes AT the edge instead of being
    // thrown away with the room half-drawn.
    const x = (e.clientX - rect.left) / CELL_PX, y = (e.clientY - rect.top) / CELL_PX;
    return { x: Math.max(0, Math.min(GRID_COLS, x)), y: Math.max(0, Math.min(GRID_ROWS, y)) };
  }

  // +toFixed(2) kills float noise from 0.2 steps (3 * 0.2 = 0.6000000000000001)
  const snapTo = v => +(Math.max(0, Math.round(v / snap) * snap)).toFixed(2);

  // Point-in-elevation test honoring the rect's optional rotation ("rot",
  // degrees clockwise about the center) — the point is inverse-rotated into
  // the rect's local frame. Mirrors battlemap3d.js floorAt().
  function _elevContains(e, p) {
    if (e.shape === 'circle') return Math.hypot(p.x - e.cx, p.y - e.cy) <= e.r;
    if (!e.rot) return p.x >= e.x1 && p.x < e.x2 && p.y >= e.y1 && p.y < e.y2;
    const cx = (e.x1 + e.x2) / 2, cy = (e.y1 + e.y2) / 2;
    const a = e.rot * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
    const lx = cx + (p.x - cx) * ca + (p.y - cy) * sa;
    const ly = cy - (p.x - cx) * sa + (p.y - cy) * ca;
    return lx >= e.x1 && lx < e.x2 && ly >= e.y1 && ly < e.y2;
  }

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

    if (tool === 'select') {
      // A selected PROP is directly manipulable: grab its rotate handle to
      // spin it, or grab the prop itself to drag it somewhere else. The
      // pre-drag snapshot only enters the undo stack if something actually
      // changes, so a plain click stays a plain click.
      const selProp = sel && sel.kind === 'prop' && plan.props[sel.idx];
      if (selProp) {
        const h = _propRotHandle(selProp);
        if (Math.hypot(p.x - h.x, p.y - h.y) <= 14 / CELL_PX + 0.1) {
          drag = { kind: 'selrotate', idx: sel.idx,
                   snap: JSON.stringify(plan), pushed: false };
          return;
        }
      }
      // A selected ELEVATION RECT's rotate handle spins it (15° snaps),
      // checked before re-selecting so the knob keeps the click.
      const selElev = sel && sel.kind === 'elevation' && plan.elevations[sel.idx];
      if (selElev && selElev.shape !== 'circle') {
        const h = _elevRotHandle(selElev);
        if (Math.hypot(p.x - h.x, p.y - h.y) <= 14 / CELL_PX + 0.1) {
          drag = { kind: 'selelevrot', idx: sel.idx,
                   snap: JSON.stringify(plan), pushed: false };
          return;
        }
      }
      // A selected WALL/DOOR is directly manipulable too: grab an endpoint
      // knob to reshape/rotate it (checked BEFORE re-selecting, so a knob
      // near another segment doesn't steal the click).
      if (sel && (sel.kind === 'wall' || sel.kind === 'door')) {
        const sg = plan[sel.kind + 's'][sel.idx];
        if (sg) {
          const grabR = 12 / CELL_PX + 0.05;
          for (const n of [1, 2]) {
            if (Math.hypot(p.x - sg['x' + n], p.y - sg['y' + n]) <= grabR) {
              drag = { kind: 'selend', list: sel.kind + 's', idx: sel.idx,
                       end: n, snap: JSON.stringify(plan), pushed: false };
              return;
            }
          }
        }
      }
      selectAt(p);
      if (sel && (sel.kind === 'prop' || sel.kind === 'light')) {
        const pr = plan[sel.kind + 's'][sel.idx];
        drag = { kind: 'selmove', list: sel.kind + 's', idx: sel.idx,
                 snap: JSON.stringify(plan), pushed: false,
                 offX: pr.x - p.x, offY: pr.y - p.y,
                 last: pr.x + ',' + pr.y };
      } else if (sel && (sel.kind === 'wall' || sel.kind === 'door')) {
        // body drag slides the whole segment (both endpoints together)
        const sg = plan[sel.kind + 's'][sel.idx];
        drag = { kind: 'selseg', list: sel.kind + 's', idx: sel.idx,
                 snap: JSON.stringify(plan), pushed: false,
                 grab: p, o: { x1: sg.x1, y1: sg.y1, x2: sg.x2, y2: sg.y2 },
                 lastDx: 0, lastDy: 0 };
      } else if (sel && sel.kind === 'elevation') {
        const ev = plan.elevations[sel.idx];
        if (ev.shape === 'circle') {
          drag = { kind: 'selcirc', idx: sel.idx,
                   snap: JSON.stringify(plan), pushed: false,
                   offX: ev.cx - p.x, offY: ev.cy - p.y,
                   last: ev.cx + ',' + ev.cy };
        } else {
          // same slide mechanics as walls — x1..y2 translate together, rot
          // rides along untouched
          drag = { kind: 'selseg', list: 'elevations', idx: sel.idx,
                   snap: JSON.stringify(plan), pushed: false,
                   grab: p, o: { x1: ev.x1, y1: ev.y1, x2: ev.x2, y2: ev.y2 },
                   lastDx: 0, lastDy: 0 };
        }
      }
      return;
    }

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
      eraseAt(p, true);
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
    if (drag.kind === 'selmove') {
      const pr = plan[drag.list || 'props'][drag.idx];
      const nx = snapTo(p.x + drag.offX), ny = snapTo(p.y + drag.offY);
      if (nx + ',' + ny === drag.last) return;   // redraw only on snap steps
      _dragCommit(drag);
      pr.x = nx; pr.y = ny;
      drag.last = nx + ',' + ny;
      markDirty();
      return;
    }
    if (drag.kind === 'selend') {
      const sg = plan[drag.list][drag.idx];
      const other = drag.end === 1 ? 2 : 1;
      const nx = snapTo(p.x), ny = snapTo(p.y);
      if (nx === sg['x' + drag.end] && ny === sg['y' + drag.end]) return;
      if (nx === sg['x' + other] && ny === sg['y' + other]) return;  // no zero-length
      _dragCommit(drag);
      sg['x' + drag.end] = nx; sg['y' + drag.end] = ny;
      markDirty();
      return;
    }
    if (drag.kind === 'selseg') {
      const sg = plan[drag.list][drag.idx];
      const o = drag.o;
      // Snap the DELTA (not each endpoint) so diagonals keep their exact
      // shape, then clamp so both endpoints stay on the grid.
      let dx = snapTo(o.x1 + (p.x - drag.grab.x)) - o.x1;
      let dy = snapTo(o.y1 + (p.y - drag.grab.y)) - o.y1;
      dx = Math.max(-Math.min(o.x1, o.x2),
                    Math.min(GRID_COLS - Math.max(o.x1, o.x2), dx));
      dy = Math.max(-Math.min(o.y1, o.y2),
                    Math.min(GRID_ROWS - Math.max(o.y1, o.y2), dy));
      if (dx === drag.lastDx && dy === drag.lastDy) return;
      _dragCommit(drag);
      sg.x1 = +(o.x1 + dx).toFixed(2); sg.y1 = +(o.y1 + dy).toFixed(2);
      sg.x2 = +(o.x2 + dx).toFixed(2); sg.y2 = +(o.y2 + dy).toFixed(2);
      drag.lastDx = dx; drag.lastDy = dy;
      markDirty();
      return;
    }
    if (drag.kind === 'selrotate') {
      const pr = plan.props[drag.idx];
      // handle sits "above" the prop at rot 0, so pointing the pointer in a
      // direction turns the prop's front that way; snapped to 15°
      const ang = Math.atan2(p.y - pr.y, p.x - pr.x) * 180 / Math.PI + 90;
      const rot = ((Math.round(ang / 15) * 15) % 360 + 360) % 360;
      if ((pr.rot || 0) === rot) return;
      _dragCommit(drag);
      if (rot) pr.rot = rot; else delete pr.rot;
      markDirty();
      renderSelUI();   // keep the inspector's Turn field live
      return;
    }
    if (drag.kind === 'selelevrot') {
      const ev = plan.elevations[drag.idx];
      const ecx = (ev.x1 + ev.x2) / 2, ecy = (ev.y1 + ev.y2) / 2;
      const ang = Math.atan2(p.y - ecy, p.x - ecx) * 180 / Math.PI + 90;
      const rot = ((Math.round(ang / 15) * 15) % 360 + 360) % 360;
      if ((ev.rot || 0) === rot) return;
      _dragCommit(drag);
      if (rot) ev.rot = rot; else delete ev.rot;
      markDirty();
      renderSelUI();
      return;
    }
    if (drag.kind === 'selcirc') {
      const ev = plan.elevations[drag.idx];
      const nx = snapTo(p.x + drag.offX), ny = snapTo(p.y + drag.offY);
      if (nx + ',' + ny === drag.last) return;
      _dragCommit(drag);
      ev.cx = nx; ev.cy = ny;
      drag.last = nx + ',' + ny;
      markDirty();
      return;
    }
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
      // live-preview the panel's angle about the rect's current center, so
      // the drawn footprint IS the final footprint
      if (drag.kind === 'elev' && elevRot) {
        const pcx = (x1 + Math.abs(end.x - drag.start.x) / 2) * CELL_PX;
        const pcy = (y1 + Math.abs(end.y - drag.start.y) / 2) * CELL_PX;
        drag.previewEl.setAttribute('transform', `rotate(${elevRot} ${pcx} ${pcy})`);
      }
    }
  }

  function onUp() {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (d.kind === 'selmove' || d.kind === 'selrotate' ||
        d.kind === 'selend' || d.kind === 'selseg' ||
        d.kind === 'selcirc' || d.kind === 'selelevrot') return;   // no preview el
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
      const ev = { x1, y1, x2, y2, floor_ft: elevFt };
      if (elevRot) ev.rot = elevRot;
      plan.elevations.push(ev);
      markDirty();
    } else if (d.kind === 'elevc') {
      if (!d.r || d.r < snap || !elevFt) return;
      pushUndo();
      plan.elevations.push({ shape: 'circle', cx: d.start.x, cy: d.start.y,
                             r: d.r, floor_ft: elevFt });
      markDirty();
    } else if (d.kind === 'zone') {
      const zn = plan.zones && plan.zones[activeZone];
      if (!zn) { alert('Press "+ New room" first, or pick a room in the list, then paint its floor.'); return; }
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
    const ei = plan.elevations.findIndex(e2 => _elevContains(e2, p));
    if (ei !== -1) { plan.elevations.splice(ei, 1); markDirty(); return true; }
    return false;
  }

  function eraseAt(p, allowZones) {
    let guard = 200;                       // plan caps make this unreachable
    let removed = false;
    while (guard-- > 0 && eraseOne(p)) removed = true;  // clear EVERYTHING the brush touches
    // A zone area only goes when the press landed on otherwise-empty floor
    // inside it (never during a sweep), so clearing walls in a room doesn't
    // also strip the room.
    if (!removed && allowZones) eraseZoneRectAt(p);
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
    // Pointer capture: once a drag starts, the overlay keeps getting move/up
    // events even when the pointer leaves it — past the map edge, over the
    // floating panel, or outside the browser window. Releasing anywhere
    // finishes the shape (coordinates clamped to the map in evtCell). The
    // old pointerleave handler threw the whole drag away, which lost a room
    // the moment the cursor slipped off the map.
    ov.addEventListener('pointerdown', e => {
      onDown(e);
      if (drag && ov.setPointerCapture) {
        try { ov.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events */ }
      }
    });
    ov.addEventListener('pointermove', onMove);
    ov.addEventListener('pointerup', onUp);
    // Only a genuine cancel (touch gesture taken over by the browser, device
    // disconnect) abandons an in-progress shape.
    ov.addEventListener('pointercancel', () => {
      if (drag) {
        if (drag.previewEl) drag.previewEl.remove();
        drag = null;
      }
    });
    // Leaving mid-debounce: fire the pending save with keepalive so it
    // completes after the tab closes (same pattern as the map notes).
    window.addEventListener('beforeunload', () => {
      if (!plan || !dirty) return;
      if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
      try {
        fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: serializePlan(), keepalive: true,
        });
      } catch (e) {}
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
    onState, redraw, save, revert, setTool, setWallHeight, setWallStyle, setSky,
    setWallShow, setShow2d, setElevHeight, setElevRot, setSnap, setLightType, setLightColor,
    setLightRadius, setPropType, setPropRot, setPropScale, setPropTexture,
    undo, redo, nudge, scalePlan,
    newZone, deleteZone, deleteZoneRect, selectZone, setZoneField,
    applySel, deleteSel, setTexOptions, getDraft,
    toggle: togglePanel, close: closePanel,
    isDirty: () => dirty,
  };
})();

// Template onclick shims (match the fx-panel naming convention)
function toggleFpPanel() { BMFP.toggle(); }
function closeFpPanel()  { BMFP.close(); }

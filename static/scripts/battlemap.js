/* static/scripts/battlemap.js
   Battlemap page logic, extracted from templates/ttrpg/battlemap.html.
   Page-specific values (MAP_ID, GRID_*, IS_DM, MAP_ROLLER_NAME, ...) are
   defined by a small inline <script> in the template BEFORE this file loads.
   DM-only behaviour is gated at runtime via IS_DM (the DM-only DOM simply
   doesn't exist for players). */
let activeDrag    = null;  // { tokenId, el, col, row, gridRect }
let currentTokens = {};    // token_id -> server data snapshot
let entityTokenMap = {};   // "monster-5" -> token_id
let activePan     = null;  // { startX, startY, scrollLeft, scrollTop }

// ── Utilities ─────────────────────────────────────────────────────────────────

function hpColor(pct) {
  return pct > 50 ? '#28a745' : pct > 20 ? '#ffc107' : '#dc3545';
}

function initials(name) {
  return name.split(' ').slice(0, 2).map(w => w[0] || '').join('').toUpperCase() || '?';
}

function clampCol(v) { return Math.max(0, Math.min(GRID_COLS - 1, v)); }
function clampRow(v) { return Math.max(0, Math.min(GRID_ROWS - 1, v)); }

// ── Token tooltip ─────────────────────────────────────────────────────────────

const _tt = document.getElementById('tok-tooltip');

function showTooltip(e, tok) {
  const typeColor = tok.entity_type === 'player' ? '#4a9eff' : '#cc3333';
  _tt.style.borderColor = typeColor;
  _tt.style.background  = `color-mix(in srgb, ${typeColor} 10%, var(--ttrpg-primary))`;

  const portrait = document.getElementById('tt-portrait');
  if (tok.image_url) {
    portrait.src = tok.image_url;
    portrait.style.borderColor = typeColor;
    portrait.style.display = 'block';
  } else {
    portrait.style.display = 'none';
  }

  const nameEl = document.getElementById('tt-name');
  nameEl.textContent   = tok.name;
  nameEl.style.color   = typeColor;
  document.getElementById('tt-hp').textContent   = `HP ${tok.hp_current} / ${tok.hp_max}`;
  document.getElementById('tt-hp-pct').textContent = tok.hp_pct + '%';

  const bar = document.getElementById('tt-hp-bar');
  bar.style.width      = tok.hp_pct + '%';
  bar.style.background = tok.hp_pct > 50 ? '#28a745' : tok.hp_pct > 20 ? '#ffc107' : '#dc3545';

  const statBits = [];
  if (tok.ac)    statBits.push(`AC ${tok.ac}`);
  if (tok.speed) statBits.push(`Speed: ${tok.speed}`);
  document.getElementById('tt-speed').textContent = statBits.join('  ·  ');

  const condEl = document.getElementById('tt-conditions');
  condEl.innerHTML = '';
  (tok.conditions || []).forEach(c => {
    const s = document.createElement('span');
    s.textContent  = c;
    s.style.cssText = 'background:rgba(201,168,76,.15);color:var(--ttrpg-accent);' +
                      'border:1px solid var(--ttrpg-accent);border-radius:4px;' +
                      'padding:1px 6px;font-size:.7rem;';
    condEl.appendChild(s);
  });

  const skillEl = document.getElementById('tt-skills');
  skillEl.innerHTML = '';
  (tok.skills || []).forEach(s => {
    const sp = document.createElement('span');
    const sign = s.bonus >= 0 ? '+' : '';
    sp.innerHTML = `${s.proficient ? '<span style="color:var(--ttrpg-accent);">&#9733;</span>' : ''}${s.name} <strong style="color:var(--ttrpg-text);">${sign}${s.bonus}</strong>&ensp;`;
    skillEl.appendChild(sp);
  });

  _positionTooltip(e);
  _tt.style.display = 'block';
}

function _positionTooltip(e) {
  const x = e.clientX + 16;
  const y = e.clientY + 16;
  const w = _tt.offsetWidth  || 200;
  const h = _tt.offsetHeight || 160;
  _tt.style.left = (x + w > window.innerWidth  ? e.clientX - w - 10 : x) + 'px';
  _tt.style.top  = (y + h > window.innerHeight ? e.clientY - h - 10 : y) + 'px';
}

function hideTooltip() { _tt.style.display = 'none'; }

// ── Pointer drag handlers ─────────────────────────────────────────────────────

function _ctrlOpenSheet(tok) {
  if (!tok) return;
  if (tok.entity_type === 'player') {
    if (IS_DM || tok.user_id === CURRENT_USER_ID) {
      // ?dice=1: coming from the battle map means mid-game — the sheet
      // opens with its dice roller already enabled.
      window.open(`/ttrpg/character/${tok.entity_id}?dice=1`, '_blank');
    }
  } else if (tok.entity_type === 'monster' && IS_DM) {
    window.open(`/ttrpg/battlemap/monster-redirect/${tok.entity_id}`, '_blank');
  }
}

// ── Movement radius (distance circle shown while dragging a token) ────────────
let _moveRing = null, _moveLabel = null, _moveCx = 0, _moveCy = 0;
function _showMoveRing(cx, cy) {
  _removeMoveRing();
  const grid = document.getElementById('map-grid');
  if (!grid) return;
  _moveCx = cx; _moveCy = cy;
  _moveRing = document.createElement('div');
  _moveRing.className = 'move-radius';
  grid.appendChild(_moveRing);
  _moveLabel = document.createElement('div');
  _moveLabel.className = 'move-radius-label';
  _moveLabel.style.left = cx + 'px';
  _moveLabel.style.top  = cy + 'px';
  _moveLabel.textContent = '0';
  grid.appendChild(_moveLabel);
}
function _updateMoveRing(cx, cy) {
  if (!_moveRing) return;
  const r = Math.hypot(cx - _moveCx, cy - _moveCy);
  const feet = Math.round((r / CELL_PX) * 5 * MOVE_SCALE);
  _moveRing.style.left   = (_moveCx - r) + 'px';
  _moveRing.style.top    = (_moveCy - r) + 'px';
  _moveRing.style.width  = (2 * r) + 'px';
  _moveRing.style.height = (2 * r) + 'px';
  _moveLabel.textContent = String(feet);
}
function _removeMoveRing() {
  if (_moveRing)  _moveRing.remove();
  if (_moveLabel) _moveLabel.remove();
  _moveRing = _moveLabel = null;
}

// GM-only: save the per-map feet-per-square scale (5 ft × scale per square).
function saveMoveScale(val) {
  MOVE_SCALE = Math.max(0.05, Math.min(20, parseFloat(val) || 1));
  fetch(`/ttrpg/battlemap/${MAP_ID}/movement-scale`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ movement_scale: MOVE_SCALE }),
  });
}

function attachDrag(el, tokenId) {
  // Mouse tooltip (unchanged)
  el.addEventListener('mouseenter', e => {
    if (!activeDrag) showTooltip(e, currentTokens[tokenId] || {});
  });
  el.addEventListener('mousemove', e => {
    if (!activeDrag) _positionTooltip(e);
  });
  el.addEventListener('mouseleave', hideTooltip);

  const _tok     = currentTokens[tokenId] || {};
  const _canMove = IS_DM ||
    (_tok.entity_type === 'player' && _tok.user_id === CURRENT_USER_ID);

  if (!_canMove) el.style.cursor = 'default';

  let _ctrlOnDown = false;
  let _startCol, _startRow;
  let _lastDown  = 0;
  let _lpTimer   = null;  // long-press tooltip timer (touch)
  let _downPos   = null;  // pointer coords at touchstart
  let _hasMoved  = false; // true once finger moves >8px

  el.addEventListener('pointerdown', e => {
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    hideTooltip();

    const now = Date.now();
    const isDbl = (now - _lastDown) < 300;
    _lastDown = now;
    // Double-click (mouse) or double-tap (touch) opens character sheet
    _ctrlOnDown = e.ctrlKey || isDbl;

    const gridRect = document.getElementById('map-grid').getBoundingClientRect();
    const tok = currentTokens[tokenId] || { col: 0, row: 0 };
    _startCol  = tok.col;
    _startRow  = tok.row;
    _hasMoved  = false;
    _downPos   = { clientX: e.clientX, clientY: e.clientY };

    activeDrag = { tokenId, el, col: tok.col, row: tok.row, gridRect };

    if (_canMove) {
      el.style.transition = 'none';
      el.style.zIndex     = '100';
      el.style.cursor     = 'grabbing';
      el.style.opacity    = '0.85';
      _showMoveRing((_startCol + 0.5) * CELL_PX, (_startRow + 0.5) * CELL_PX);
    }

    // Touch: show tooltip after 500ms hold without movement
    if (e.pointerType === 'touch') {
      clearTimeout(_lpTimer);
      _lpTimer = setTimeout(() => {
        if (!_hasMoved) {
          // Show tooltip above the thumb
          const ttPos = { clientX: _downPos.clientX, clientY: _downPos.clientY - 120 };
          showTooltip(ttPos, currentTokens[tokenId] || {});
          setTimeout(hideTooltip, 3000);
        }
      }, 500);
    }
  });

  el.addEventListener('pointermove', e => {
    // Track movement to cancel long-press and enforce drag threshold on touch
    if (e.pointerType === 'touch' && _downPos && !_hasMoved) {
      const dx = e.clientX - _downPos.clientX;
      const dy = e.clientY - _downPos.clientY;
      if (Math.sqrt(dx * dx + dy * dy) > 8) {
        _hasMoved = true;
        clearTimeout(_lpTimer);
        _lpTimer = null;
        hideTooltip();
      }
    }

    if (!activeDrag || activeDrag.tokenId !== tokenId || !_canMove) return;
    // Touch: don't move token until finger has clearly moved (prevents accidental moves)
    if (e.pointerType === 'touch' && !_hasMoved) return;

    const col = clampCol(Math.floor((e.clientX - activeDrag.gridRect.left) / CELL_PX));
    const row = clampRow(Math.floor((e.clientY - activeDrag.gridRect.top)  / CELL_PX));

    if (col !== activeDrag.col || row !== activeDrag.row) {
      activeDrag.col = col;
      activeDrag.row = row;
      el.style.transform = `translate(${col * CELL_PX}px,${row * CELL_PX}px)`;
      _updateMoveRing((col + 0.5) * CELL_PX, (row + 0.5) * CELL_PX);
    }
  });

  function endDrag() {
    clearTimeout(_lpTimer);
    _lpTimer = null;
    _removeMoveRing();
    if (!activeDrag || activeDrag.tokenId !== tokenId) return;
    const { col, row } = activeDrag;

    if (_canMove) {
      el.style.transition = '';
      el.style.zIndex     = '10';
      el.style.cursor     = '';
      el.style.opacity    = '';
    }

    activeDrag = null;

    // Ctrl+click or double-click: open sheet in new tab (works for everyone).
    // For enemies that's the monster card, which carries the session
    // instance's HP controls and a dice roller (monster-redirect passes the
    // instance id through).
    if (_ctrlOnDown && col === _startCol && row === _startRow) {
      _ctrlOpenSheet(currentTokens[tokenId]);
      return;
    }

    // Plain click (no drag) is deliberately inert: it used to pop the map
    // dice panel, which also fired on the first click of every double-click.
    // The map dice roller lives behind the toolbar "Dice" button now.

    if (!_canMove) return;

    // Commit position locally so next poll doesn't snap it back
    if (currentTokens[tokenId]) {
      currentTokens[tokenId].col = col;
      currentTokens[tokenId].row = row;
    }

    fetch(`/ttrpg/battlemap/${MAP_ID}/token/move`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ token_id: tokenId, col, row }),
    });
    // Mover-only footstep — only when the token actually changed cells, so a
    // click / double-click that lands on the same square stays silent.
    if (col !== _startCol || row !== _startRow) _sfx('move');
  }

  el.addEventListener('pointerup',     endDrag);
  el.addEventListener('pointercancel', endDrag);
}

// ── Buried-token rescue (players) ─────────────────────────────────────────────
// A player's token can end up visually under a fog cloud (z:12) or another
// creature, whose element swallows the pointerdown — leaving the player unable
// to grab their own character without DM help. Rather than lift the token's
// z-index (visual depth must hold), hit-test the whole element stack under the
// pointer in capture phase and reroute the press to the topmost token this
// player may move. Fog keeps blocking everything else (hidden enemies stay
// unclickable), and the DM is exempt: rerouting would hijack cloud
// selection/dragging, and the DM already has fog peek.
if (!IS_DM) {
  const _rescueGrid = document.getElementById('map-grid');
  const _isMyTokenEl = el => {
    const t = el && currentTokens[el.dataset.tokenId];
    return !!(t && t.entity_type === 'player' && t.user_id === CURRENT_USER_ID);
  };
  if (_rescueGrid) _rescueGrid.addEventListener('pointerdown', e => {
    const hit = e.target.closest ? e.target.closest('.map-token') : null;
    if (_isMyTokenEl(hit)) return;   // press already lands on my token
    const mine = document.elementsFromPoint(e.clientX, e.clientY)
      .map(n => (n.closest ? n.closest('.map-token') : null))
      .find(_isMyTokenEl);
    if (!mine) return;
    e.preventDefault();
    e.stopPropagation();
    // Re-dispatch on my token: its own pointerdown handler takes explicit
    // pointer capture, so the rest of the drag flows to it natively. The
    // synthetic event re-enters this listener with hit === mine → returns.
    mine.dispatchEvent(new PointerEvent(e.type, e));
  }, true);
}

// ── Token DOM ─────────────────────────────────────────────────────────────────

function createTokenEl(tok) {
  const span  = Math.max(1, tok.size_squares || 1);   // grid squares this token spans
  const sz    = span * CELL_PX - 6;
  const isMe  = !IS_DM && tok.entity_type === 'player' && tok.user_id === CURRENT_USER_ID;
  const border = isMe ? '#2ecc71' : tok.entity_type === 'player' ? '#4a9eff' : '#cc3333';
  const bg     = isMe ? '#0d2820' : tok.entity_type === 'player' ? '#0d2845' : '#2d0a0a';

  const el = document.createElement('div');
  el.className       = 'map-token tok-' + tok.entity_type + (tok.is_alive ? '' : ' token-dead') + (isMe ? ' token-mine' : '');
  el.id              = `tok-${tok.token_id}`;
  el.dataset.tokenId = tok.token_id;
  // Big tokens sit BEHIND smaller ones so adjacent creatures stay clickable.
  const zBase = span > 1 ? Math.max(1, 6 - span) : '';
  el.style.cssText   = `transform:translate(${tok.col * CELL_PX}px,${tok.row * CELL_PX}px);width:${span * CELL_PX}px;${zBase !== '' ? 'z-index:' + zBase + ';' : ''}`;

  const portraitInner = tok.image_url
    ? `<img src="${tok.image_url}" alt=""
            onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
       <span style="display:none;width:100%;height:100%;align-items:center;justify-content:center;">
         ${initials(tok.name)}
       </span>`
    : `<span>${initials(tok.name)}</span>`;

  const youArrow = isMe ? '<div class="token-you-arrow">YOU</div>' : '';

  el.innerHTML = `
    ${youArrow}
    <div class="token-portrait"
         style="width:${sz}px;height:${sz}px;border-color:${border};background:${bg};">
      ${portraitInner}
    </div>
    <div class="token-hp-bar">
      <div class="token-hp-fill tok-fill"
           style="width:${tok.hp_pct}%;background:${hpColor(tok.hp_pct)};"></div>
    </div>
    <div class="token-name">${tok.name}</div>
  `;

  attachDrag(el, tok.token_id);
  return el;
}

// ── Render / diff tokens ──────────────────────────────────────────────────────

function renderTokens(tokens) {
  const grid = document.getElementById('map-grid');
  const seen = new Set();

  for (const tok of tokens) {
    seen.add(tok.token_id);
    entityTokenMap[`${tok.entity_type}-${tok.entity_id}`] = tok.token_id;

    let el = document.getElementById(`tok-${tok.token_id}`);
    if (!el) {
      currentTokens[tok.token_id] = tok;
      el = createTokenEl(tok);
      grid.appendChild(el);
    } else {
      // Don't overwrite position or snapshot while this token is being dragged
      if (!activeDrag || activeDrag.tokenId !== tok.token_id) {
        currentTokens[tok.token_id] = tok;
        el.style.transform = `translate(${tok.col * CELL_PX}px,${tok.row * CELL_PX}px)`;
      }
      const fill = el.querySelector('.tok-fill');
      if (fill) {
        fill.style.width      = `${tok.hp_pct}%`;
        fill.style.background = hpColor(tok.hp_pct);
      }
      const isMe2 = !IS_DM && tok.entity_type === 'player' && tok.user_id === CURRENT_USER_ID;
      el.className = 'map-token tok-' + tok.entity_type + (tok.is_alive ? '' : ' token-dead') + (isMe2 ? ' token-mine' : '');
    }
  }

  // Remove tokens no longer on the map
  for (const [tid, old] of Object.entries(currentTokens)) {
    if (!seen.has(parseInt(tid))) {
      document.getElementById(`tok-${tid}`)?.remove();
      delete currentTokens[tid];
      delete entityTokenMap[`${old.entity_type}-${old.entity_id}`];
    }
  }

  if (IS_DM) updateSidebar(tokens);
}

// ── Player-visible floorplan (walls / doors / props on the 2D map) ───────────
// Two sources of visibility, rendered for EVERYONE on the flat map:
//  - per-wall "show" flags (the classic block-off-wrong-art tool);
//  - the plan-level show_walls_2d / show_props_2d switches, which reveal ALL
//    walls+doors and/or all props — the DM's "players get the blueprint" mode.
// Geometry re-fetches when the poll reports a new floorplan version; door
// open/closed states re-render from the regular 2-second poll.

let _fpvVersion = undefined;   // undefined = never synced; null = no floorplan
let _fpvWalls = [];
let _fpvDoors = [];            // shown only with show_walls_2d
let _fpvProps = [];            // shown only with show_props_2d
let _fpvDoorStates = {};       // door id -> open, from the poll

function _fpvRender() {
  const svg = document.getElementById('fp-visible-layer');
  if (!svg) return;
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  _fpvWalls.forEach(w => {
    // dark under-stroke + light top-stroke so the bar reads on any art
    svg.appendChild(svgEl('line', {
      x1: w.x1 * CELL_PX, y1: w.y1 * CELL_PX, x2: w.x2 * CELL_PX, y2: w.y2 * CELL_PX,
      stroke: '#14120e', 'stroke-width': 9, 'stroke-linecap': 'round', 'stroke-opacity': 0.85,
    }));
    svg.appendChild(svgEl('line', {
      x1: w.x1 * CELL_PX, y1: w.y1 * CELL_PX, x2: w.x2 * CELL_PX, y2: w.y2 * CELL_PX,
      stroke: '#d8d2bf', 'stroke-width': 5, 'stroke-linecap': 'round', 'stroke-opacity': 0.95,
    }));
  });
  _fpvDoors.forEach(d => {
    const isOpen = _fpvDoorStates[d.id] !== undefined
      ? !!_fpvDoorStates[d.id] : !!d.open;
    svg.appendChild(svgEl('line', {
      x1: d.x1 * CELL_PX, y1: d.y1 * CELL_PX, x2: d.x2 * CELL_PX, y2: d.y2 * CELL_PX,
      stroke: '#14120e', 'stroke-width': 9, 'stroke-linecap': 'round', 'stroke-opacity': 0.85,
    }));
    svg.appendChild(svgEl('line', {
      x1: d.x1 * CELL_PX, y1: d.y1 * CELL_PX, x2: d.x2 * CELL_PX, y2: d.y2 * CELL_PX,
      stroke: isOpen ? '#4caf50' : '#e6a23c', 'stroke-width': 5,
      'stroke-linecap': 'round', 'stroke-dasharray': isOpen ? '5 7' : 'none',
    }));
  });
  _fpvProps.forEach(pr => {
    const s = 9 * (pr.scale || 1);
    const cx = pr.x * CELL_PX, cy = pr.y * CELL_PX;
    const g = svgEl('g');
    g.appendChild(svgEl('rect', {
      x: cx - s, y: cy - s, width: s * 2, height: s * 2,
      fill: '#a98d5f', 'fill-opacity': '0.85', stroke: '#3b3122',
      'stroke-width': 1.5, rx: 2,
      transform: `rotate(${pr.rot || 0} ${cx} ${cy})`,
    }));
    const label = svgEl('text', {
      x: cx, y: cy + 3.5, fill: '#20180d', 'font-size': '10',
      'font-weight': '700', 'text-anchor': 'middle',
    });
    label.textContent = pr.type.slice(0, 2);
    g.appendChild(label);
    const title = svgEl('title', {});
    title.textContent = pr.type;
    g.appendChild(title);
    svg.appendChild(g);
  });
}

function _fpvSync(version) {
  if (version === undefined || version === _fpvVersion) return;
  _fpvVersion = version;
  if (!version) {
    _fpvWalls = []; _fpvDoors = []; _fpvProps = [];
    _fpvRender();
    return;
  }
  fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`)
    .then(r => r.json())
    .then(d => {
      const fp = (d || {}).floorplan || {};
      const allWalls = !!fp.show_walls_2d;
      _fpvWalls = (fp.walls || []).filter(w => allWalls || w.show);
      _fpvDoors = allWalls ? (fp.doors || []) : [];
      _fpvProps = fp.show_props_2d ? (fp.props || []) : [];
      _fpvRender();
    })
    .catch(() => { _fpvVersion = undefined; });   // retry on the next poll
}

// Door toggles don't bump the floorplan version — track states from the poll
// and re-render only when one actually flips (and only if doors are shown).
function _fpvDoorSync(states) {
  if (!states || !_fpvDoors.length) { _fpvDoorStates = states || {}; return; }
  const sig = _fpvDoors.map(d => states[d.id] ? '1' : '0').join('');
  const old = _fpvDoors.map(d => _fpvDoorStates[d.id] ? '1' : '0').join('');
  _fpvDoorStates = states;
  if (sig !== old) _fpvRender();
}
if (typeof FLOORPLAN_VERSION !== 'undefined') _fpvSync(FLOORPLAN_VERSION);

// ── Sidebar toggle ────────────────────────────────────────────────────────────

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const btn     = document.getElementById('sb-toggle');
  const collapsed = sidebar.classList.toggle('sb-collapsed');
  btn.innerHTML = collapsed ? '&#9654;' : '&#9664;';
}

// ── Sidebar button sync + HP controls ────────────────────────────────────────

function updateSidebar(tokens) {
  const onMap = new Set(tokens.map(t => `${t.entity_type}-${t.entity_id}`));
  const byEntity = {};
  tokens.forEach(t => { byEntity[`${t.entity_type}-${t.entity_id}`] = t; });

  document.querySelectorAll('.sidebar-entity').forEach(el => {
    const key        = `${el.dataset.entityType}-${el.dataset.entityId}`;
    const entityType = el.dataset.entityType;
    const entityId   = parseInt(el.dataset.entityId);
    const btn        = el.querySelector('.sidebar-btn');
    const hpRow      = el.querySelector('.sb-hp-row');
    if (!btn) return;

    if (onMap.has(key)) {
      btn.innerHTML = '&#10005;';
      btn.className = 'sidebar-btn btn btn-sm py-0 px-1 btn-outline-danger';
      btn.onclick   = () => removeTokenByEntity(entityType, entityId);
      if (hpRow) {
        hpRow.style.display = '';
        const tok = byEntity[key];
        if (tok) _sbSetHp(hpRow, tok.hp_current, tok.hp_max, tok.hp_pct);
      }
    } else {
      btn.innerHTML = '+';
      btn.className = 'sidebar-btn btn btn-sm py-0 px-1 btn-outline-secondary';
      btn.onclick   = () => placeToken(entityType, entityId);
      if (hpRow) hpRow.style.display = 'none';
    }
  });
}

function _sbSetHp(hpRow, cur, max, pct) {
  const span = hpRow.querySelector('.sb-hp');
  if (span) span.textContent = `${cur}/${max}`;
  const bar = hpRow.querySelector('.sb-bar');
  if (bar) { bar.style.width = pct + '%'; bar.style.background = hpColor(pct); }
}

// Collapsible sidebar sections. The title carries data-sb-section="<key>";
// its box is #sb-sec-<key>. The fold sticks per browser via localStorage —
// collapsed monsters stay collapsed across reloads and sessions.
function sbToggleSection(titleEl) {
  const key = titleEl.dataset.sbSection;
  const box = document.getElementById('sb-sec-' + key);
  if (!box) return;
  const hide = box.style.display !== 'none';
  box.style.display = hide ? 'none' : '';
  const caret = titleEl.querySelector('.sb-caret');
  if (caret) caret.innerHTML = hide ? '▸' : '▾';
  try { localStorage.setItem('sb-collapse-' + key, hide ? '1' : '0'); } catch (e) {}
}

// Restore each section's remembered fold once the sidebar exists.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-sb-section]').forEach(t => {
    let saved = null;
    try { saved = localStorage.getItem('sb-collapse-' + t.dataset.sbSection); } catch (e) {}
    if (saved === '1') sbToggleSection(t);   // starts open; one toggle folds it
  });
});

function sbAmt(btn) {
  return parseInt(btn.closest('.sb-hp-row').querySelector('.sb-amt').value) || 1;
}

function adjustSidebarHp(entityType, entityId, delta) {
  const url = entityType === 'monster'
    ? `/ttrpg/monsters/instance/${entityId}/hp`
    : `/ttrpg/character/${entityId}/hp-delta`;
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ delta }),
  }).then(r => r.json()).then(data => {
    if (!data.ok) return;
    if (delta < 0)      _sfx(data.hp_current <= 0 ? 'dead' : 'damage');
    else if (delta > 0) _sfx('heal');
    // Update sidebar HP display
    const hpRow = document.querySelector(
      `.sidebar-entity[data-entity-type="${entityType}"][data-entity-id="${entityId}"] .sb-hp-row`
    );
    if (hpRow) {
      const span = hpRow.querySelector('.sb-hp');
      const max  = span ? parseInt((span.textContent.split('/')[1]) || 0) : 0;
      _sbSetHp(hpRow, data.hp_current, max, data.hp_pct);
    }
    // Immediately reflect change on the map token
    const tok = Object.values(currentTokens).find(
      t => t.entity_type === entityType && t.entity_id === entityId
    );
    if (tok) {
      tok.hp_current = data.hp_current;
      tok.hp_pct     = data.hp_pct;
      const fill = document.querySelector(`#tok-${tok.token_id} .tok-fill`);
      if (fill) { fill.style.width = data.hp_pct + '%'; fill.style.background = hpColor(data.hp_pct); }
    }
  });
}

// ── Token place / remove (DM sidebar) ────────────────────────────────────────

function placeToken(entityType, entityId) {
  fetch(`/ttrpg/battlemap/${MAP_ID}/token/add`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ entity_type: entityType, entity_id: entityId }),
  }).then(r => r.json()).then(d => { if (d.ok) pollState(); });
}

function removeTokenByEntity(entityType, entityId) {
  const tokenId = entityTokenMap[`${entityType}-${entityId}`];
  if (!tokenId) return;
  fetch(`/ttrpg/battlemap/${MAP_ID}/token/remove`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ token_id: tokenId }),
  }).then(r => r.json()).then(d => { if (d.ok) pollState(); });
}

// ── Set this map live (DM) ──────────────────────────────────────────────────────
// Activate the current map without leaving the page; players auto-follow on their
// next state poll. The button swaps to a static "Active" badge on success.
function setMapActive() {
  const btn = document.getElementById('set-active-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Activating…'; }
  fetch(`/ttrpg/battlemap/${MAP_ID}/activate`, {
    method:  'POST',
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
  }).then(r => r.json()).then(d => {
    const el = document.getElementById('set-active-btn');
    if (d && d.ok) {
      if (el) el.outerHTML =
        '<span id="set-active-btn" class="btn btn-sm btn-success disabled"' +
        ' title="This map is live for players">● Active</span>';
    } else if (el) {
      el.disabled = false; el.textContent = 'Set Active';
      alert((d && d.error) || 'Could not set this map active.');
    }
  }).catch(() => {
    const el = document.getElementById('set-active-btn');
    if (el) { el.disabled = false; el.textContent = 'Set Active'; }
  });
}

// ── State poll ────────────────────────────────────────────────────────────────
// setTimeout chain (not setInterval) so consecutive failures can back the
// cadence off from 2s toward 30s instead of hammering an unreachable server.

let pollTimer = null;
let _pollFails = 0;

function _pollDelay() {
  return _pollFails === 0 ? 2000 : Math.min(30000, 2000 * Math.pow(2, _pollFails));
}

function pollState() {
  if (activeDrag || activeFxDrag) { _schedulePoll(); return; }
  fetch(`/ttrpg/battlemap/${MAP_ID}/state`)
    .then(r => r.json())
    .then(d => {
      _pollFails = 0;
      // Players auto-follow the DM to a newly activated map. DMs are left alone
      // so they can keep editing prep maps that aren't the live one.
      if (!IS_DM && d.active_map_id && d.active_map_id !== MAP_ID) {
        const _go = () => { window.location.href = `/ttrpg/battlemap/${d.active_map_id}/view`; };
        // Play the transition sting on this (already-enabled) page, then
        // navigate — the new page can't auto-play without its own gesture.
        if (window.SFX && SFX.isEnabled()) { _sfx('mapswitch'); setTimeout(_go, 450); }
        else _go();
        return;
      }
      // Character (re)assignment: if the set of characters this player may
      // roll as changed since page load, reload — that refreshes the
      // "Rolling as" roster, token drag permissions, and highlights, so the
      // DM can hand out characters mid-session with no re-login.
      if (!IS_DM && d.roller_sig !== null && d.roller_sig !== undefined
          && d.roller_sig !== _pageRollerSig) {
        location.reload();
        return;
      }
      _hpSfxDiff(d.tokens);   // everyone hears HP changes (incl. DM-applied)
      renderTokens(d.tokens);
      renderEffects(d.effects || []);
      // 3D mode rides the same poll: cached so BM3D can seat tokens instantly
      // on open, forwarded live while the viewer is loaded. The DM floorplan
      // editor (BMFP) tracks door states / external saves the same way.
      window._bmLastState = d;
      if (window.BM3D) BM3D.onState(d);
      if (window.BMFP) BMFP.onState(d);
      _fpvSync(d.floorplan_version);
      _fpvDoorSync(d.doors);
      _obsSync(d.obs);
    })
    .catch(() => { _pollFails++; })
    .finally(() => _schedulePoll());
}

function _schedulePoll() {
  if (pollTimer !== null) pollTimer = setTimeout(pollState, _pollDelay());
}

function startPolling() {
  if (pollTimer === null) { pollTimer = 1; pollState(); }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    clearTimeout(pollTimer);
    pollTimer = null;
  } else {
    startPolling();
  }
});

// ── Relay presence polling (DM only) ─────────────────────────────────────────
function pollRelayPresence() {
  fetch('/ttrpg/battlemap/relay-presence')
    .then(r => r.ok ? r.json() : { presence: {} })
    .then(data => {
      const presence = data.presence || {};
      document.querySelectorAll('.presence-dot[data-presence]').forEach(dot => {
        const name = dot.dataset.presence;
        const secsAgo = presence.hasOwnProperty(name) ? presence[name] : null;
        const online = secsAgo !== null && secsAgo < 90;
        dot.classList.toggle('online', online);
        dot.title = online
          ? `Online (${secsAgo < 5 ? 'just now' : Math.round(secsAgo) + 's ago'})`
          : 'Offline';
      });
    })
    .catch(() => {});
}
if (IS_DM) {   // presence display exists only in the DM sidebar
  setInterval(pollRelayPresence, 15000);
  setTimeout(pollRelayPresence, 3000); // initial poll shortly after page load
}

// ── Map pan + pinch-to-zoom (background touch/mouse drag) ────────────────────
(function() {
  const vp = document.getElementById('map-viewport');
  const activePointers = new Map(); // pointerId → {x, y}
  let pinch = null; // { dist, cellPx } — active pinch state

  vp.addEventListener('pointerdown', e => {
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (activePointers.size >= 2) {
      // Second finger: switch to pinch-to-zoom
      activePan = null;
      vp.style.cursor = '';
      const pts = [...activePointers.values()];
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      pinch = { dist, cellPx: CELL_PX };
      vp.setPointerCapture(e.pointerId);
      return;
    }

    // Single pointer: pan on background only
    if (e.button !== 0 && e.pointerType !== 'touch') return;
    if (e.target !== vp && e.target !== document.getElementById('map-grid') &&
        e.target !== document.getElementById('map-lines') &&
        e.target !== document.getElementById('map-bg')) return;
    activePan = { startX: e.clientX, startY: e.clientY,
                  scrollLeft: vp.scrollLeft, scrollTop: vp.scrollTop,
                  // Remembered so pointerup can tell a CLICK from a pan —
                  // dragging the map must not also steer the camera.
                  downX: e.clientX, downY: e.clientY };
    vp.style.cursor = 'grabbing';
    vp.setPointerCapture(e.pointerId);
  });

  // Clicking empty ground while the 3D view is pinned to a character turns
  // that character's head towards the spot. Background only: token clicks
  // keep doing what they always did.
  function maybeLookAt(e) {
    if (!OBS_ENABLED || !_obsViewChar || !activePan) return;
    if (Math.hypot(e.clientX - activePan.downX,
                   e.clientY - activePan.downY) > 6) return;   // that was a pan
    const grid = document.getElementById('map-grid');
    if (!grid) return;
    const r = grid.getBoundingClientRect();
    const col = clampCol(Math.floor((e.clientX - r.left) / CELL_PX));
    const row = clampRow(Math.floor((e.clientY - r.top) / CELL_PX));
    fetch('/ttrpg/obs/api/look-at', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ col, row }),
    })
      .then(r2 => r2.json())
      .then(d => { if (d && d.ok) _lookPing(col, row); })
      .catch(() => {});
  }

  // A ping on the clicked cell. Without it this command is invisible from
  // here — the camera it turns is in the OBS map source, on another screen —
  // so it read as doing nothing at all.
  function _lookPing(col, row) {
    const grid = document.getElementById('map-grid');
    if (!grid) return;
    const dot = document.createElement('div');
    dot.style.cssText =
      'position:absolute;pointer-events:none;z-index:60;border-radius:50%;' +
      'border:3px solid #7fd18a;box-shadow:0 0 12px rgba(127,209,138,.9);' +
      `left:${col * CELL_PX}px;top:${row * CELL_PX}px;` +
      `width:${CELL_PX}px;height:${CELL_PX}px;box-sizing:border-box;`;
    grid.appendChild(dot);
    dot.animate(
      [{ transform: 'scale(.4)', opacity: 1 },
       { transform: 'scale(1.9)', opacity: 0 }],
      { duration: 650, easing: 'ease-out' }
    ).onfinish = () => dot.remove();
  }

  vp.addEventListener('pointermove', e => {
    if (activePointers.has(e.pointerId)) {
      activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    }

    if (pinch && activePointers.size >= 2) {
      const pts = [...activePointers.values()];
      const newDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      if (newDist > 0) {
        // Zoom about the pinch midpoint: rescale, then re-scroll so the map
        // point between the fingers stays put. Without the scroll fix the
        // anchor is the map's top-left corner and the pinched spot drifts
        // off-screen. Use actual CELL_PX after setCellPx — it clamps.
        const oldPx = CELL_PX;
        setCellPx(Math.round(pinch.cellPx * newDist / pinch.dist));
        const scale = CELL_PX / oldPx;
        if (scale !== 1) {
          const rect = vp.getBoundingClientRect();
          const midX = (pts[0].x + pts[1].x) / 2 - rect.left;
          const midY = (pts[0].y + pts[1].y) / 2 - rect.top;
          vp.scrollLeft = (vp.scrollLeft + midX) * scale - midX;
          vp.scrollTop  = (vp.scrollTop  + midY) * scale - midY;
        }
      }
      return;
    }

    if (!activePan) return;
    vp.scrollLeft = activePan.scrollLeft - (e.clientX - activePan.startX);
    vp.scrollTop  = activePan.scrollTop  - (e.clientY - activePan.startY);
  });

  function endPan(e) {
    maybeLookAt(e);
    activePointers.delete(e.pointerId);
    if (activePointers.size < 2) pinch = null;
    if (activePointers.size === 0) {
      activePan = null;
      vp.style.cursor = '';
    }
  }

  vp.addEventListener('pointerup',     endPan);
  vp.addEventListener('pointercancel', endPan);
})();

// ── Effects ───────────────────────────────────────────────────────────────────

const effectsSvg  = document.getElementById('effects-layer');
const fogSvg      = document.getElementById('fog-layer');

// Soft fog edges: the visible black of every cloud is mirrored into this one
// blurred sub-group, so adjacent/overlapping boxes blend as a single union —
// per-rect fades would leave lighter seams where two boxes share an edge.
// The per-effect <g>s keep an invisible rect for hit-testing plus the DM-only
// outline and ✕ button, which must stay crisp, so they are NOT blurred.
const FOG_FADE_PX = 80;   // width of the fade-to-black at each fog edge
let fogShapesG = null;
if (fogSvg) {
  fogShapesG = svgEl('g');
  fogShapesG.id = 'fog-shapes';
  fogShapesG.style.pointerEvents = 'none';
  // A gaussian blur's visible transition spans ~3σ, so σ = fade/3 reads as a
  // FOG_FADE_PX-wide falloff centered on the box edge.
  fogShapesG.style.filter = `blur(${(FOG_FADE_PX / 3).toFixed(1)}px)`;
  fogSvg.appendChild(fogShapesG);
}
function _removeFogMirror(effectId) {
  document.getElementById(`fxm-${effectId}`)?.remove();
}
let cloudDrawMode  = false;
let cloudEraseMode = false;
let cloudPlacing   = null;   // { startX, startY, previewG, _minX, _minY, _wCells, _hCells }
let cloudErasing   = null;   // { previewG, cells: Set of 'x,y' strings }
const fxOverlay   = document.getElementById('fx-draw-overlay');
let currentEffects  = {};   // effect_id → data
let activeFxDrag    = null; // { effectId, g, origX, origY, startCX, startCY }
let fxSelectedId    = null;
let fxDeleteHandle  = null; // SVG <g> for the inline delete button

// Fog "peek" — DM-only see-through fog so the DM can view (and move) tokens
// hidden under the cloud-of-war. Players always see solid fog. Toggling off
// previews exactly what the players see.
let _fogPeek = IS_DM;   // DMs start able to see under the fog
function applyFogPeek() {
  if (fogSvg) fogSvg.style.opacity = _fogPeek ? '0.30' : '1';
  // While peeking, let pointer events pass through clouds to the tokens beneath
  // so the DM can drag hidden tokens. (Toggle off to select/move the clouds.)
  for (const eid in currentEffects) {
    if (currentEffects[eid].shape === 'cloud') {
      const g = document.getElementById(`fx-${eid}`);
      if (g) g.style.pointerEvents = (IS_DM && _fogPeek) ? 'none' : 'all';
    }
  }
  const btn = document.getElementById('fog-peek-btn');
  if (btn) {
    btn.style.color   = _fogPeek ? 'var(--ttrpg-accent)' : 'var(--sp-muted)';
    btn.style.opacity = _fogPeek ? '1' : '.55';
  }
}
function toggleFogPeek() { _fogPeek = !_fogPeek; applyFogPeek(); }
applyFogPeek();
let fxDrawing       = null; // active preview: { startX, startY, angle, size_ft, previewG }
let fxDrawMode      = false;

// Panel state
let fxShape       = 'circle';
let fxSizeFt      = 20;
let fxFillColor   = '#ff4400';
let fxBorderColor = '#ff8800';
let fxOpacity     = 35;
let fxLabel       = '';

const FX_PRESETS = [
  { label: 'Fire',       fill: '#ff4400', border: '#ff8800' },
  { label: 'Cold',       fill: '#0088ff', border: '#00ccff' },
  { label: 'Poison',     fill: '#00cc44', border: '#00ff66' },
  { label: 'Lightning',  fill: '#ffff00', border: '#ffcc00' },
  { label: 'Necrotic',   fill: '#9900ff', border: '#cc44ff' },
  { label: 'Radiant',    fill: '#ffffcc', border: '#ffff88' },
  { label: 'Psychic',    fill: '#ff44aa', border: '#ff88cc' },
  { label: 'Darkness',   fill: '#000033', border: '#0000cc' },
];

// ── SVG helpers ───────────────────────────────────────────────────────────────

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

const CONE_HALF_RAD = 26.57 * Math.PI / 180;  // D&D cone spread (width = length at far end)

function applyEffectGeometry(g, eff) {
  while (g.firstChild) g.removeChild(g.firstChild);

  const px   = eff.anchor_x * CELL_PX;
  const py   = eff.anchor_y * CELL_PX;
  const θ    = (eff.angle || 0) * Math.PI / 180;
  const dim  = (eff.size_ft / 5) * CELL_PX;  // primary dimension in px
  let shape, lx = px, ly = py;

  if (eff.shape === 'circle') {
    shape = svgEl('circle', { cx: px, cy: py, r: dim });

  } else if (eff.shape === 'square') {
    shape = svgEl('rect', { x: px - dim, y: py - dim, width: dim * 2, height: dim * 2 });

  } else if (eff.shape === 'cone') {
    const x1 = px + dim * Math.cos(θ - CONE_HALF_RAD);
    const y1 = py + dim * Math.sin(θ - CONE_HALF_RAD);
    const x2 = px + dim * Math.cos(θ + CONE_HALF_RAD);
    const y2 = py + dim * Math.sin(θ + CONE_HALF_RAD);
    shape = svgEl('path', {
      d: `M ${px.toFixed(1)} ${py.toFixed(1)} L ${x1.toFixed(1)} ${y1.toFixed(1)} A ${dim.toFixed(1)} ${dim.toFixed(1)} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)} Z`
    });
    lx = px + dim * 0.55 * Math.cos(θ);
    ly = py + dim * 0.55 * Math.sin(θ);

  } else if (eff.shape === 'line') {
    const hw = CELL_PX * 0.5;                         // half-width = 1 cell (5 ft)
    const nx = -Math.sin(θ), ny = Math.cos(θ);        // normal perpendicular
    const ex = dim * Math.cos(θ), ey = dim * Math.sin(θ);
    const pts = [
      `${(px + nx*hw).toFixed(1)},${(py + ny*hw).toFixed(1)}`,
      `${(px + ex + nx*hw).toFixed(1)},${(py + ey + ny*hw).toFixed(1)}`,
      `${(px + ex - nx*hw).toFixed(1)},${(py + ey - ny*hw).toFixed(1)}`,
      `${(px - nx*hw).toFixed(1)},${(py - ny*hw).toFixed(1)}`,
    ].join(' ');
    shape = svgEl('polygon', { points: pts });
    lx = px + (dim / 2) * Math.cos(θ);
    ly = py + (dim / 2) * Math.sin(θ);

  } else if (eff.shape === 'cloud') {
    const wCells = eff.size_ft / 5;
    const hCells = eff.angle > 0 ? eff.angle : wCells;
    const w = wCells * CELL_PX, h = hCells * CELL_PX;
    shape = svgEl('rect', { x: px, y: py, width: w, height: h });
    if (fogShapesG && eff.effect_id != null) {
      let m = document.getElementById(`fxm-${eff.effect_id}`);
      if (!m) {
        m = svgEl('rect');
        m.id = `fxm-${eff.effect_id}`;
        fogShapesG.appendChild(m);
      }
      m.setAttribute('x', px);
      m.setAttribute('y', py);
      m.setAttribute('width',  w);
      m.setAttribute('height', h);
      m.setAttribute('fill',         eff.fill_color || '#000000');
      m.setAttribute('fill-opacity', eff.fill_opacity != null ? eff.fill_opacity : 1);
    }
  }

  if (!shape) return;
  shape.setAttribute('fill',         eff.fill_color);
  shape.setAttribute('fill-opacity', eff.fill_opacity);
  if (eff.shape !== 'cloud') {
    shape.setAttribute('stroke',       eff.border_color);
    shape.setAttribute('stroke-width', '2');
  } else if (fogShapesG && eff.effect_id != null) {
    // The visible black comes from this cloud's blurred mirror rect; a solid
    // fill here would paint the hard edge right back on top of the fade. This
    // rect survives only as the hit-target (blocks player clicks on hidden
    // tokens) and, for the DM, a faint dashed outline to grab/select.
    shape.setAttribute('fill-opacity', '0');
    if (IS_DM) {
      shape.setAttribute('stroke',           '#c0c0c0');
      shape.setAttribute('stroke-width',     '1.5');
      shape.setAttribute('stroke-dasharray', '4 3');
    }
  } else {
    shape.setAttribute('stroke',       '#c0c0c0');
    shape.setAttribute('stroke-width', '1.5');
  }
  g.appendChild(shape);

  if (IS_DM && eff.shape === 'cloud') {
    const wCells = eff.size_ft / 5;
    const btnSize = Math.min(CELL_PX * 0.55, 22);
    const bx = px + wCells * CELL_PX - btnSize - 2;
    const by = py + 2;
    const bg = svgEl('rect', {
      x: bx, y: by, width: btnSize, height: btnSize,
      rx: 3, ry: 3,
      fill: '#c0c0c0', 'fill-opacity': '0.85',
    });
    const xt = svgEl('text', {
      x: bx + btnSize / 2, y: by + btnSize / 2 + 1,
      'text-anchor': 'middle', 'dominant-baseline': 'middle',
      'font-size': Math.round(btnSize * 0.65),
      fill: '#111', 'font-weight': 'bold', 'font-family': 'sans-serif',
    });
    xt.textContent = '✕';
    [bg, xt].forEach(el => {
      el.style.cursor = 'pointer';
      el.addEventListener('pointerdown', e => { e.stopPropagation(); e.preventDefault(); });
      el.addEventListener('pointerup', e => {
        e.stopPropagation();
        g.remove();
        _removeFogMirror(eff.effect_id);
        delete currentEffects[eff.effect_id];
        fetch(`/ttrpg/battlemap/${MAP_ID}/effect/${eff.effect_id}/delete`, { method: 'POST' });
      });
    });
    g.appendChild(bg);
    g.appendChild(xt);
  }

  if (eff.label && eff.shape !== 'cloud') {
    const txt = svgEl('text', {
      x: lx.toFixed(1), y: ly.toFixed(1),
      'text-anchor': 'middle', 'dominant-baseline': 'middle',
      fill: 'white', 'font-size': '11', 'font-weight': 'bold',
      stroke: 'black', 'stroke-width': '2.5', 'paint-order': 'stroke',
      'pointer-events': 'none',
    });
    txt.textContent = eff.label;
    g.appendChild(txt);
  }
}

// ── Inline delete handle ──────────────────────────────────────────────────────

function _removeFxHandle() {
  if (fxDeleteHandle) { fxDeleteHandle.remove(); fxDeleteHandle = null; }
}

function _showFxHandle(eff) {
  _removeFxHandle();
  const px = eff.anchor_x * CELL_PX;
  const py = eff.anchor_y * CELL_PX;

  const g = svgEl('g');
  g.style.cursor = 'pointer';
  g.style.pointerEvents = 'all';

  const bg = svgEl('circle', { cx: px, cy: py - 12, r: '10',
    fill: '#dc3545', stroke: '#fff', 'stroke-width': '1.5' });
  const txt = svgEl('text', {
    x: px, y: py - 12,
    'text-anchor': 'middle', 'dominant-baseline': 'middle',
    fill: 'white', 'font-size': '13', 'font-weight': 'bold',
    'pointer-events': 'none',
  });
  txt.textContent = '×';

  g.appendChild(bg);
  g.appendChild(txt);
  g.addEventListener('pointerdown', e => e.stopPropagation());
  g.addEventListener('click', e => { e.stopPropagation(); deleteFxSelected(); });

  effectsSvg.appendChild(g);
  fxDeleteHandle = g;
}

// ── Effect drag (move existing) ───────────────────────────────────────────────

function attachFxDrag(g, effectId) {
  g.addEventListener('pointerdown', e => {
    if (fxDrawMode) return;
    e.stopPropagation();
    e.preventDefault();
    g.setPointerCapture(e.pointerId);
    const eff = currentEffects[effectId];
    if (!eff) return;
    _removeFxHandle();
    activeFxDrag = {
      effectId, g,
      origX: eff.anchor_x, origY: eff.anchor_y,
      startCX: e.clientX, startCY: e.clientY,
    };
    g.style.cursor = 'grabbing';
    selectEffect(effectId);
  });

  g.addEventListener('pointermove', e => {
    if (!activeFxDrag || activeFxDrag.effectId !== effectId) return;
    const dx = (e.clientX - activeFxDrag.startCX) / CELL_PX;
    const dy = (e.clientY - activeFxDrag.startCY) / CELL_PX;
    const eff = currentEffects[effectId];
    if (eff) applyEffectGeometry(g, { ...eff, anchor_x: eff.anchor_x + dx, anchor_y: eff.anchor_y + dy });
  });

  function endFxDrag(e) {
    if (!activeFxDrag || activeFxDrag.effectId !== effectId) return;
    const dx = (e.clientX - activeFxDrag.startCX) / CELL_PX;
    const dy = (e.clientY - activeFxDrag.startCY) / CELL_PX;
    let newX = activeFxDrag.origX + dx;
    let newY = activeFxDrag.origY + dy;
    if (!e.shiftKey) { newX = Math.round(newX * 2) / 2; newY = Math.round(newY * 2) / 2; }
    currentEffects[effectId].anchor_x = newX;
    currentEffects[effectId].anchor_y = newY;
    applyEffectGeometry(g, currentEffects[effectId]);
    activeFxDrag = null;
    g.style.cursor = 'grab';
    if (fxSelectedId === effectId) _showFxHandle(currentEffects[effectId]);
    fetch(`/ttrpg/battlemap/${MAP_ID}/effect/${effectId}/update`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anchor_x: newX, anchor_y: newY }),
    });
  }
  g.addEventListener('pointerup',     endFxDrag);
  g.addEventListener('pointercancel', endFxDrag);
}

// ── Build / reconcile effects ─────────────────────────────────────────────────

function _layerForEff(eff) {
  return eff.shape === 'cloud' ? fogSvg : effectsSvg;
}

function buildEffectEl(eff) {
  const g = svgEl('g');
  g.id = `fx-${eff.effect_id}`;
  g.dataset.effectId = String(eff.effect_id);
  if (eff.shape === 'cloud') {
    // In DM peek mode, clouds don't capture clicks so tokens under them stay draggable.
    g.style.pointerEvents = (IS_DM && _fogPeek) ? 'none' : 'all';
  }
  if (IS_DM) {
    g.style.cursor = 'grab';
    attachFxDrag(g, eff.effect_id);
    g.addEventListener('click', e => {
      if (activeFxDrag) return;
      e.stopPropagation();
      selectEffect(eff.effect_id);
    });
  }
  applyEffectGeometry(g, eff);
  return g;
}

function renderEffects(effects) {
  const seen = new Set();
  for (const eff of effects) {
    seen.add(eff.effect_id);
    currentEffects[eff.effect_id] = eff;
    let g = document.getElementById(`fx-${eff.effect_id}`);
    if (!g) {
      g = buildEffectEl(eff);
      _layerForEff(eff).appendChild(g);
    } else if (!activeFxDrag || activeFxDrag.effectId !== eff.effect_id) {
      applyEffectGeometry(g, eff);
    }
  }
  for (const eid of Object.keys(currentEffects)) {
    if (!seen.has(parseInt(eid))) {
      document.getElementById(`fx-${eid}`)?.remove();
      _removeFogMirror(eid);
      delete currentEffects[eid];
    }
  }
}

// ── Draw mode (overlay) ───────────────────────────────────────────────────────

function _overlayGridPos(e) {
  const rect = document.getElementById('map-grid').getBoundingClientRect();
  let col = (e.clientX - rect.left) / CELL_PX;
  let row = (e.clientY - rect.top)  / CELL_PX;
  if (!e.shiftKey) { col = Math.round(col * 2) / 2; row = Math.round(row * 2) / 2; }
  return [col, row];
}

function _previewEffect(startX, startY, curX, curY) {
  const dx   = curX - startX;
  const dy   = curY - startY;
  const dist = Math.hypot(dx, dy);
  let angle = fxDrawing.angle, size_ft = fxDrawing.size_ft;

  if (fxShape === 'cone' || fxShape === 'line') {
    if (dist > 0.15) angle = Math.atan2(dy, dx) * 180 / Math.PI;
    size_ft = dist > 0 ? Math.max(5, Math.round(dist * 5 / 5) * 5) : fxSizeFt;
  } else if (dist > 0.3) {
    size_ft = Math.max(5, Math.round(dist * 5 / 5) * 5);
  }
  fxDrawing.angle   = angle;
  fxDrawing.size_ft = size_ft;
  applyEffectGeometry(fxDrawing.previewG, {
    shape: fxShape, anchor_x: startX, anchor_y: startY,
    size_ft, angle,
    fill_color: fxFillColor, fill_opacity: fxOpacity / 100,
    border_color: fxBorderColor, label: fxLabel,
  });
}

// ── Cloud-of-War helpers ──────────────────────────────────────────────────────

function _cloudGridPos(e) {
  const rect = document.getElementById('map-grid').getBoundingClientRect();
  return [
    Math.floor((e.clientX - rect.left) / CELL_PX),
    Math.floor((e.clientY - rect.top)  / CELL_PX),
  ];
}

function _updateCloudPreview(startX, startY, endX, endY) {
  if (!cloudPlacing) return;
  const g = cloudPlacing.previewG;
  while (g.firstChild) g.removeChild(g.firstChild);
  const minX    = Math.min(startX, endX);
  const minY    = Math.min(startY, endY);
  const wCells  = Math.max(1, Math.abs(endX - startX) + 1);
  const hCells  = Math.max(1, Math.abs(endY - startY) + 1);
  const r = svgEl('rect', {
    x: minX * CELL_PX, y: minY * CELL_PX,
    width: wCells * CELL_PX, height: hCells * CELL_PX,
    fill: '#000000', 'fill-opacity': '0.55', stroke: 'none',
  });
  g.appendChild(r);
  cloudPlacing._minX   = minX;
  cloudPlacing._minY   = minY;
  cloudPlacing._wCells = wCells;
  cloudPlacing._hCells = hCells;
}

function _applyCloudDrawMode() {
  const btn = document.getElementById('cloud-draw-btn');
  if (cloudDrawMode) {
    btn.textContent = '█ Paint: ON';
    btn.classList.replace('btn-outline-secondary', 'btn-warning');
    btn.style.color = '#000';
    if (fxOverlay) { fxOverlay.style.display = 'block'; fxOverlay.style.cursor = 'crosshair'; }
  } else {
    btn.textContent = '█ Paint: OFF';
    btn.classList.replace('btn-warning', 'btn-outline-secondary');
    btn.style.color = '';
    if (!cloudEraseMode) {
      if (fxOverlay) fxOverlay.style.display = 'none';
    }
    if (cloudPlacing) { cloudPlacing.previewG.remove(); cloudPlacing = null; }
  }
}

function toggleCloudDrawMode() {
  cloudDrawMode = !cloudDrawMode;
  if (cloudDrawMode) {
    if (fxDrawMode)     { fxDrawMode    = false; _applyDrawMode(); }
    if (cloudEraseMode) { cloudEraseMode = false; _applyCloudEraseMode(); }
  }
  _applyCloudDrawMode();
}

function _applyCloudEraseMode() {
  const btn = document.getElementById('cloud-erase-btn');
  if (cloudEraseMode) {
    btn.textContent = '◯ Erase: ON';
    btn.classList.replace('btn-outline-secondary', 'btn-info');
    if (fxOverlay) { fxOverlay.style.display = 'block'; fxOverlay.style.cursor = 'cell'; }
  } else {
    btn.textContent = '◯ Erase: OFF';
    btn.classList.replace('btn-info', 'btn-outline-secondary');
    if (!cloudDrawMode) {
      if (fxOverlay) fxOverlay.style.display = 'none';
    }
    if (fxOverlay) fxOverlay.style.cursor = 'crosshair';
    if (cloudErasing) { cloudErasing.previewG.remove(); cloudErasing = null; }
  }
}

function toggleCloudEraseMode() {
  cloudEraseMode = !cloudEraseMode;
  if (cloudEraseMode) {
    if (fxDrawMode)    { fxDrawMode    = false; _applyDrawMode(); }
    if (cloudDrawMode) { cloudDrawMode = false; _applyCloudDrawMode(); }
  }
  _applyCloudEraseMode();
}

// Find all cloud effects that overlap a given cell (col, row)
function _cloudsAtCell(col, row) {
  return Object.values(currentEffects).filter(eff => {
    if (eff.shape !== 'cloud') return false;
    const wCells = eff.size_ft / 5;
    const hCells = eff.angle > 0 ? eff.angle : wCells;
    return col >= eff.anchor_x && col < eff.anchor_x + wCells &&
           row >= eff.anchor_y && row < eff.anchor_y + hCells;
  });
}

// Delete all clouds touching (col, row) during an erase stroke
function _eraseCloudCells(col, row) {
  if (!cloudErasing) return;
  const key = `${col},${row}`;
  if (cloudErasing.erased.has(key)) return;
  cloudErasing.erased.add(key);

  // Visually flash the cell being erased
  const flash = svgEl('rect', {
    x: col * CELL_PX, y: row * CELL_PX,
    width: CELL_PX, height: CELL_PX,
    fill: '#ffffff', 'fill-opacity': '0.25', stroke: 'none',
  });
  cloudErasing.previewG.appendChild(flash);

  // Delete any cloud effect that covers this cell
  _cloudsAtCell(col, row).forEach(eff => {
    if (cloudErasing.erased.has(`id:${eff.effect_id}`)) return;
    cloudErasing.erased.add(`id:${eff.effect_id}`);
    // Optimistically remove from DOM so it feels instant
    document.getElementById(`fx-${eff.effect_id}`)?.remove();
    _removeFogMirror(eff.effect_id);
    delete currentEffects[eff.effect_id];
    fetch(`/ttrpg/battlemap/${MAP_ID}/effect/${eff.effect_id}/delete`, { method: 'POST' });
  });
}

function clearAllClouds() {
  if (!confirm('Remove all cloud-of-war blocks from this map?')) return;
  const ids = Object.values(currentEffects)
    .filter(e => e.shape === 'cloud')
    .map(e => e.effect_id);
  Promise.all(ids.map(id =>
    fetch(`/ttrpg/battlemap/${MAP_ID}/effect/${id}/delete`, { method: 'POST' })
  )).then(() => pollState());
}

if (fxOverlay) {
  fxOverlay.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    if (cloudEraseMode) {
      const [col, row] = _cloudGridPos(e);
      const previewG = svgEl('g');
      previewG.style.pointerEvents = 'none';
      fogSvg.appendChild(previewG);
      cloudErasing = { previewG, erased: new Set() };
      // Erase clouds under the initial click immediately
      _eraseCloudCells(col, row);
      e.preventDefault();
      return;
    }
    if (cloudDrawMode) {
      const [col, row] = _cloudGridPos(e);
      const previewG = svgEl('g');
      previewG.style.pointerEvents = 'none';
      fogSvg.appendChild(previewG);
      cloudPlacing = { startX: col, startY: row, previewG };
      _updateCloudPreview(col, row, col, row);
      e.preventDefault();
      return;
    }
    const [col, row] = _overlayGridPos(e);
    const previewG = svgEl('g');
    previewG.style.pointerEvents = 'none';
    effectsSvg.appendChild(previewG);
    fxDrawing = { startX: col, startY: row, angle: 0, size_ft: fxSizeFt, previewG };
    _previewEffect(col, row, col, row);
    e.preventDefault();
  });

  fxOverlay.addEventListener('mousemove', e => {
    if (cloudErasing) {
      const [col, row] = _cloudGridPos(e);
      _eraseCloudCells(col, row);
      return;
    }
    if (cloudPlacing) {
      const [col, row] = _cloudGridPos(e);
      _updateCloudPreview(cloudPlacing.startX, cloudPlacing.startY, col, row);
      return;
    }
    if (!fxDrawing) return;
    const [col, row] = _overlayGridPos(e);
    _previewEffect(fxDrawing.startX, fxDrawing.startY, col, row);
  });

  fxOverlay.addEventListener('mouseup', e => {
    if (cloudErasing) {
      cloudErasing.previewG.remove();
      cloudErasing = null;
      pollState();
      return;
    }
    if (cloudPlacing) {
      const cp = cloudPlacing;
      cloudPlacing = null;
      cp.previewG.remove();
      if (cp._wCells == null) return;
      fetch(`/ttrpg/battlemap/${MAP_ID}/effect/add`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          shape:        'cloud',
          anchor_x:     cp._minX,
          anchor_y:     cp._minY,
          size_ft:      cp._wCells * 5,
          angle:        cp._hCells,
          fill_color:   '#000000',
          fill_opacity: 1.0,
          border_color: '#000000',
          label:        '',
        }),
      }).then(r => r.json()).then(d => { if (d.ok) pollState(); });
      return;
    }
    if (!fxDrawing) return;
    const drawing = fxDrawing;
    fxDrawing = null;
    drawing.previewG.remove();
    fetch(`/ttrpg/battlemap/${MAP_ID}/effect/add`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        shape:        fxShape,
        anchor_x:     drawing.startX,
        anchor_y:     drawing.startY,
        size_ft:      drawing.size_ft,
        angle:        drawing.angle,
        fill_color:   fxFillColor,
        fill_opacity: fxOpacity / 100,
        border_color: fxBorderColor,
        label:        fxLabel,
      }),
    }).then(r => r.json()).then(d => { if (d.ok) pollState(); });
  });

  fxOverlay.addEventListener('mouseleave', () => {
    if (cloudErasing) { cloudErasing.previewG.remove(); cloudErasing = null; pollState(); }
    if (cloudPlacing) { cloudPlacing.previewG.remove(); cloudPlacing = null; }
    if (fxDrawing)    { fxDrawing.previewG.remove();    fxDrawing = null;    }
  });
}

// ── FX Panel controls ─────────────────────────────────────────────────────────

function toggleFxPanel() {
  const panel = document.getElementById('fx-panel');
  if (!panel) return;
  const open = panel.style.display !== 'none' && panel.style.display !== '';
  if (open) {
    closeFxPanel();
  } else {
    // FX and Walls each arm a map-wide pointer overlay — with both open the
    // overlays fight over the same clicks, so opening one closes the other.
    const fpPanel = document.getElementById('fp-panel');
    if (fpPanel && fpPanel.style.display === 'block' &&
        typeof closeFpPanel === 'function') closeFpPanel();
    panel.style.display = 'block';
    effectsSvg.style.pointerEvents = 'all';
    document.getElementById('fx-toggle-btn').classList.add('btn-ttrpg');
    document.getElementById('fx-toggle-btn').classList.remove('btn-outline-secondary');
    _buildPresets();
    updateFxCellLabel();
  }
}

function closeFxPanel() {
  const panel = document.getElementById('fx-panel');
  if (panel) panel.style.display = 'none';
  effectsSvg.style.pointerEvents = 'none';
  const btn = document.getElementById('fx-toggle-btn');
  if (btn) { btn.classList.remove('btn-ttrpg'); btn.classList.add('btn-outline-secondary'); }
  if (fxDrawMode)    { fxDrawMode    = false; _applyDrawMode(); }
  if (cloudDrawMode) { cloudDrawMode = false; _applyCloudDrawMode(); }
  if (cloudEraseMode){ cloudEraseMode = false; _applyCloudEraseMode(); }
  _removeFxHandle();
  fxSelectedId = null;
  const sel = document.getElementById('fx-selected');
  if (sel) sel.style.display = 'none';
}

function _buildPresets() {
  const c = document.getElementById('fx-presets');
  if (!c || c.children.length) return;
  FX_PRESETS.forEach(p => {
    const b = document.createElement('button');
    b.title = p.label;
    b.style.cssText = `width:22px;height:22px;border-radius:4px;background:${p.fill};border:2px solid ${p.border};cursor:pointer;padding:0;`;
    b.onclick = () => {
      fxFillColor = p.fill; fxBorderColor = p.border;
      document.getElementById('fx-fill-color').value   = p.fill;
      document.getElementById('fx-border-color').value = p.border;
    };
    c.appendChild(b);
  });
}

function setFxShape(shape) {
  fxShape = shape;
  document.querySelectorAll('.fx-shape-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.shape === shape);
  });
}

function updateFxCellLabel() {
  const cells = fxSizeFt / 5;
  document.getElementById('fx-cell-label').textContent = `= ${cells} cell${cells !== 1 ? 's' : ''}`;
}

function toggleFxDrawMode() {
  fxDrawMode = !fxDrawMode;
  if (fxDrawMode) {
    if (cloudDrawMode)  { cloudDrawMode  = false; _applyCloudDrawMode(); }
    if (cloudEraseMode) { cloudEraseMode = false; _applyCloudEraseMode(); }
  }
  _applyDrawMode();
}

function _applyDrawMode() {
  if (fxOverlay) fxOverlay.style.display = fxDrawMode ? 'block' : 'none';
  const btn = document.getElementById('fx-draw-btn');
  if (btn) {
    btn.textContent = `✏ Draw: ${fxDrawMode ? 'ON' : 'OFF'}`;
    btn.className   = fxDrawMode
      ? 'btn btn-sm btn-ttrpg flex-grow-1'
      : 'btn btn-sm btn-outline-secondary flex-grow-1';
  }
}

function selectEffect(effectId) {
  fxSelectedId = effectId;
  const eff  = currentEffects[effectId];
  const name = eff ? (eff.label || `${eff.shape} (${eff.size_ft})`) : '';
  const sel  = document.getElementById('fx-selected');
  if (sel) {
    document.getElementById('fx-selected-name').textContent = name;
    sel.style.display = 'block';
  }
  const panel = document.getElementById('fx-panel');
  if (panel && panel.style.display === 'none') toggleFxPanel();
  if (eff) _showFxHandle(eff);
}

function deleteFxSelected() {
  if (!fxSelectedId) return;
  const id = fxSelectedId;
  fxSelectedId = null;
  _removeFxHandle();
  const sel = document.getElementById('fx-selected');
  if (sel) sel.style.display = 'none';
  fetch(`/ttrpg/battlemap/${MAP_ID}/effect/${id}/delete`, { method: 'POST' })
    .then(() => pollState());
}

function clearAllEffects() {
  if (!confirm('Remove all effects from this map?')) return;
  fetch(`/ttrpg/battlemap/${MAP_ID}/effect/clear`, { method: 'POST' })
    .then(() => pollState());
}

// ── Draggable panel ───────────────────────────────────────────────────────────
function makeDraggable(panel, handle) {
  // Null-safe: some panels (e.g. the DM-only fx-panel) don't exist for players,
  // and a thrown error here would halt the rest of the script (incl. SFX setup).
  if (!panel || !handle) return;
  let startX, startY, startLeft, startTop;

  function onDown(clientX, clientY) {
    const rect = panel.getBoundingClientRect();
    // Snap to top/left coords so drag math is consistent
    panel.style.right  = 'auto';
    panel.style.bottom = 'auto';
    panel.style.left   = rect.left + 'px';
    panel.style.top    = rect.top  + 'px';
    startX    = clientX;
    startY    = clientY;
    startLeft = rect.left;
    startTop  = rect.top;
  }

  function onMove(clientX, clientY) {
    const dx = clientX - startX;
    const dy = clientY - startY;
    const maxLeft = window.innerWidth  - panel.offsetWidth  - 4;
    const maxTop  = window.innerHeight - panel.offsetHeight - 4;
    panel.style.left = Math.min(Math.max(0, startLeft + dx), maxLeft) + 'px';
    panel.style.top  = Math.min(Math.max(0, startTop  + dy), maxTop)  + 'px';
  }

  // Mouse
  handle.addEventListener('mousedown', function(e) {
    if (e.button !== 0 || e.target.closest('button')) return;
    e.preventDefault();
    onDown(e.clientX, e.clientY);
    function mv(e) { onMove(e.clientX, e.clientY); }
    function up() { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); }
    document.addEventListener('mousemove', mv);
    document.addEventListener('mouseup', up);
  });

  // Touch
  handle.addEventListener('touchstart', function(e) {
    if (e.target.closest('button')) return;
    const t = e.touches[0];
    onDown(t.clientX, t.clientY);
    function mv(e) { e.preventDefault(); const t = e.touches[0]; onMove(t.clientX, t.clientY); }
    function up() { handle.removeEventListener('touchmove', mv); handle.removeEventListener('touchend', up); }
    handle.addEventListener('touchmove', mv, { passive: false });
    handle.addEventListener('touchend', up);
  }, { passive: true });
}

// ── Map Dice Roller ───────────────────────────────────────────────────────────
// MAP_ROLLER_NAME comes from the inline page config in battlemap.html
let _mapDiceSel    = 20;
let _mapAdvMode    = 'normal';
let _mapLastRollId      = 0;
let _mapLastRelayRollId = 0;
let _mapDicePoll        = null;
let _mapSeenRolledAts   = new Set();
function _mapRollKey(ts) { return (ts || '').slice(0, 19).replace('T', ' '); }

function toggleMapDicePanel() {
  const p   = document.getElementById('dice-map-panel');
  const btn = document.getElementById('dice-map-toggle-btn');
  const open = p.style.display !== 'block';
  if (open) {
    p.style.display = 'block';
    btn.classList.replace('btn-outline-secondary', 'btn-ttrpg');
    mapSelectDie(20);
    mapSetAdvMode('normal');
    mapFetchFeed();
    _mapDicePoll = setInterval(mapPollFeed, 3500);
  } else {
    p.style.display = 'none';
    btn.classList.replace('btn-ttrpg', 'btn-outline-secondary');
    clearInterval(_mapDicePoll);
  }
}

function minimizeMapDicePanel() {
  const p = document.getElementById('dice-map-panel');
  const btn = document.getElementById('map-dice-minimize-btn');
  const min = p.classList.toggle('minimized');
  btn.textContent = min ? '+' : '−';
  btn.title = min ? 'Restore' : 'Minimize';
}

function mapSelectDie(s) {
  _mapDiceSel = s;
  document.querySelectorAll('.map-dice-btn').forEach(b => {
    const on = parseInt(b.dataset.sides) === s;
    b.classList.toggle('active', on);
    if (on) {
      b.style.setProperty('background',   'var(--ttrpg-accent)', 'important');
      b.style.setProperty('border-color', 'var(--ttrpg-accent)', 'important');
      b.style.setProperty('color',        'var(--sp-on-accent)', 'important');
    } else {
      b.style.removeProperty('background');
      b.style.removeProperty('border-color');
      b.style.removeProperty('color');
    }
  });
  mapSetAdvMode(_mapAdvMode);
}

function stepMapDiceCount(delta) {
  const el = document.getElementById('map-dice-count');
  el.value = Math.min(20, Math.max(1, (parseInt(el.value) || 1) + delta));
}

function mapSetAdvMode(mode) {
  _mapAdvMode = mode;
  const cfg = {
    'map-adv-normal': { mode: 'normal',       bg: 'var(--ttrpg-accent)', fg: 'var(--sp-on-accent)' },
    'map-adv-adv':    { mode: 'advantage',    bg: '#28a745',             fg: '#ffffff' },
    'map-adv-dis':    { mode: 'disadvantage', bg: '#dc3545',             fg: '#ffffff' },
  };
  Object.entries(cfg).forEach(([id, c]) => {
    const el = document.getElementById(id);
    if (!el) return;
    const on = _mapAdvMode === c.mode;
    el.classList.toggle('active', on);
    if (on) {
      el.style.setProperty('background',   c.bg,   'important');
      el.style.setProperty('border-color', c.bg,   'important');
      el.style.setProperty('color',        c.fg,   'important');
      el.style.setProperty('font-weight',  'bold', 'important');
    } else {
      el.style.removeProperty('background');
      el.style.removeProperty('border-color');
      el.style.removeProperty('color');
      el.style.removeProperty('font-weight');
    }
  });
}

function _mEsc(s) {
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Rolling-as character + Quick Reference ────────────────────────────────────
// A user can play several characters (and the DM can roll for anyone in the
// party), so the dice panel carries a "Rolling as" selector; the Quick
// Reference chips (skills / weapons / spells) always reflect that character.
const _pageRollerSig = ROLLER_CHARS.map(c => c.id).sort((a, b) => a - b).join(',');
let _mapRollerId = '';   // selected character_id as string; '' = plain DM roll

function _mapRollerChar() {
  return ROLLER_CHARS.find(c => String(c.id) === _mapRollerId) || null;
}

function mapInitRoller() {
  const row = document.getElementById('map-roller-row');
  const sel = document.getElementById('map-roller-sel');
  if (!row || !sel) return;
  sel.innerHTML = '';
  if (IS_DM) {
    const o = document.createElement('option');
    o.value = ''; o.textContent = MAP_ROLLER_NAME + ' (DM)';
    sel.appendChild(o);
  }
  ROLLER_CHARS.forEach(c => {
    const o = document.createElement('option');
    o.value = String(c.id); o.textContent = c.name;
    sel.appendChild(o);
  });
  let saved = null;
  try { saved = sessionStorage.getItem('bm_roller'); } catch (e) {}
  if (saved !== null && [...sel.options].some(o => o.value === saved)) sel.value = saved;
  else if (!IS_DM && ROLLER_CHARS.length) sel.value = String(ROLLER_CHARS[0].id);
  _mapRollerId = sel.value;
  // Only show the row when there is an actual choice to make. (The template
  // hides it with !important to beat Bootstrap's d-flex, so match that here.)
  if (sel.options.length > 1) row.style.removeProperty('display');
  else row.style.setProperty('display', 'none', 'important');
  mapRenderStatMods();
  mapRenderQuickRef();
}

function mapRollerChanged() {
  const sel = document.getElementById('map-roller-sel');
  _mapRollerId = sel.value;
  try { sessionStorage.setItem('bm_roller', sel.value); } catch (e) {}
  mapResetDice();       // fresh character, fresh roller: 1d20 +0, no label
  mapRenderStatMods();
  mapRenderQuickRef();
}

// Ability-mod buttons (STR/DEX/… + PROF) for the "Rolling as" character —
// same behaviour as the sheet's stat row: click loads the Mod box.
function mapRenderStatMods() {
  const host = document.getElementById('map-dice-statmods');
  if (!host) return;
  const c = _mapRollerChar();
  if (!c || !c.mods) { host.style.display = 'none'; host.innerHTML = ''; return; }
  const sign = n => (n >= 0 ? '+' : '') + n;
  const entries = ['STR','DEX','CON','INT','WIS','CHA']
    .map(k => [k, c.mods[k] || 0]).concat([['PROF', c.prof || 2]]);
  host.innerHTML = entries.map(([label, val]) =>
    `<button type="button" class="btn btn-sm btn-outline-secondary stat-mod-btn"
             data-mod="${val}" title="${label}: ${sign(val)}">${label}<br>
       <span style="font-size:.62rem;">${sign(val)}</span></button>`).join('');
  host.style.display = '';
}

document.getElementById('map-dice-statmods').addEventListener('click', e => {
  const btn = e.target.closest('[data-mod]');
  if (!btn) return;
  document.getElementById('map-dice-mod').value = parseInt(btn.dataset.mod, 10) || 0;
});

function mapRenderQuickRef() {
  const host = document.getElementById('map-dice-quickref');
  if (!host) return;
  const c = _mapRollerChar();
  const chip = (attrs, title, body) =>
    `<button type="button" class="qref-chip qref-click" title="${_mEsc(title)}" ${attrs}>${body}</button>`;
  const sign = n => (n >= 0 ? '+' : '') + n;
  const rows = [];
  if (c && c.skills.length) rows.push(['Skills', c.skills.map((s, i) =>
    chip(`data-qr="skill" data-i="${i}"`,
         `Roll ${s.name} check (d20 ${sign(s.bonus)})`,
         `${s.proficient ? '&#9733; ' : ''}${_mEsc(s.name)} <span class="qref-sub">${sign(s.bonus)}</span>`)).join('')]);
  if (c && c.weapons.length) rows.push(['Weapons', c.weapons.map((w, i) =>
    chip(`data-qr="weapon" data-i="${i}"`,
         w.dice ? `Roll ${w.name} damage — ${w.dice}${w.dmg_bonus ? '+' + w.dmg_bonus : ''} ${w.dmg_type}`
                : `Roll ${w.name} attack (d20 ${sign(w.atk_bonus)})`,
         `&#9876; ${_mEsc(w.name)} <span class="qref-sub">${w.dice
             ? _mEsc(w.dice + (w.dmg_bonus ? '+' + w.dmg_bonus : '') + ' ' + w.dmg_type)
             : sign(w.atk_bonus)}</span>`)).join('')]);
  if (c && c.spells.some(sp => sp.dice)) rows.push(['Spells', c.spells.map((sp, i) => sp.dice
    ? chip(`data-qr="spell" data-i="${i}"`,
           `Roll ${sp.name} damage (${sp.dice})`,
           `&#10039; ${_mEsc(sp.name)} <span class="qref-sub">${_mEsc(sp.dice)}</span>`)
    : '').join('')]);
  if (!rows.length) { host.style.display = 'none'; host.innerHTML = ''; return; }
  host.innerHTML =
    '<div class="qref-title">Quick Reference <span class="qref-hint">&mdash; click to load the roll</span></div>'
    + rows.map(([label, chips]) =>
        `<div class="qref-row"><span class="qref-label">${label}</span><div class="qref-chips">${chips}</div></div>`).join('');
  host.style.display = '';
}

// One delegated handler instead of per-chip inline JS (names stay escaped).
document.getElementById('map-dice-quickref').addEventListener('click', e => {
  const btn = e.target.closest('[data-qr]');
  const c = _mapRollerChar();
  if (!btn || !c) return;
  const i = parseInt(btn.dataset.i, 10);
  if (btn.dataset.qr === 'skill') {
    const s = c.skills[i]; mapQuickSet(s.bonus, s.name);
  } else if (btn.dataset.qr === 'weapon') {
    const w = c.weapons[i]; mapWeaponQuickRoll(w.dice, w.dmg_bonus, w.atk_bonus, w.name);
  } else if (btn.dataset.qr === 'spell') {
    const sp = c.spells[i]; mapQuickSetDamage(sp.dice, sp.name + ' damage');
  }
});

// Same semantics as the character sheet's quick-set helpers.
function mapQuickSet(modVal, label) {
  document.getElementById('map-dice-count').value = 1;
  document.getElementById('map-dice-mod').value   = modVal;
  document.getElementById('map-dice-label').value = label;
  mapSelectDie(20);
}

function mapQuickSetDamage(diceStr, label) {
  const m = (diceStr || '').match(/(\d+)\s*d\s*(\d+)/i);
  if (!m) return;
  document.getElementById('map-dice-count').value = parseInt(m[1], 10);
  mapSelectDie(parseInt(m[2], 10));
  document.getElementById('map-dice-mod').value   = 0;
  document.getElementById('map-dice-label').value = label;
}

function mapWeaponQuickRoll(diceStr, dmgBonus, atkBonus, name) {
  const m = (diceStr || '').match(/(\d+)\s*d\s*(\d+)/i);
  if (!m) { mapQuickSet(atkBonus || 0, (name || '') + ' attack'); return; }
  document.getElementById('map-dice-count').value = parseInt(m[1], 10);
  mapSelectDie(parseInt(m[2], 10));
  document.getElementById('map-dice-mod').value   = dmgBonus || 0;
  document.getElementById('map-dice-label').value = (name || '') + ' damage';
}

mapInitRoller();

function _mapDieHtml(val, sides, mode, idx, ki) {
  let cls = 'map-die-val';
  if (sides === 20 && val === 20) cls += ' nat20';
  else if (sides === 20 && val === 1) cls += ' nat1';
  if (mode !== 'normal' && idx === ki) cls += ' kept';
  const tick = (mode !== 'normal' && idx === ki) ? '&#10003;&thinsp;' : '';
  return `<span class="${cls}">${tick}${val}</span>`;
}

// ── SFX helpers ───────────────────────────────────────────────────────────────
// _sfx: never let a missing/broken sound module touch core map behaviour.
function _sfx(name) { try { if (window.SFX) SFX.play(name); } catch (e) {} }
// Crit/fumble fire only on a d20; this runs on the roller's own device only.
function _critFumble(d) {
  // Roll algebra lives in the shared DiceCore module (static/scripts/dice.js).
  return window.DiceCore ? DiceCore.critFumbleFromRecord(d) : null;
}

// Voice a roll's crit/fumble at most once per client. The roller hears it
// instantly via mapDoRoll; everyone else picks it up from the dice-feed poll.
let _lastSfxRollId = 0;
function _maybeRollSfx(d) {
  if (!d || typeof d.roll_id !== 'number' || d.roll_id <= _lastSfxRollId) return;
  _lastSfxRollId = d.roll_id;
  const cf = _critFumble(d);
  if (cf) _sfx(cf);
}

// HP-change SFX: diff incoming token HP against what we last knew, so every
// client hears damage/heal/death — including changes the DM applies to a
// player. The DM's own optimistic HP update makes their next poll a no-op,
// so the sidebar button isn't double-voiced.
function _hpSfxDiff(tokens) {
  for (const tok of tokens || []) {
    const prev = currentTokens[tok.token_id];
    if (!prev) continue;
    const a = prev.hp_current, b = tok.hp_current;
    if (typeof a !== 'number' || typeof b !== 'number' || a === b) continue;
    if (b < a) _sfx(b <= 0 ? 'dead' : 'damage');
    else       _sfx('heal');
  }
}

function mapDoRoll() {
  const count    = parseInt(document.getElementById('map-dice-count').value) || 1;
  const modifier = parseInt(document.getElementById('map-dice-mod').value)   || 0;
  const label    = document.getElementById('map-dice-label').value.trim();
  const rc       = _mapRollerChar();   // attribute to the "Rolling as" character
  fetch('/ttrpg/dice/roll', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      character_id: rc ? rc.id : null,
      char_name:    rc ? rc.name : MAP_ROLLER_NAME,
      count, sides: _mapDiceSel, modifier, label, adv_mode: _mapAdvMode,
    })
  }).then(r => r.json()).then(d => {
    if (!d.ok) return;
    _mapShowResult(d);
    _mapRenderEntry(d, true);
    _mapLastRollId = Math.max(_mapLastRollId, d.roll_id);
    _maybeRollSfx(d);   // crit/fumble — instant for the roller
  });
}

function _mapAdvLabel(mode) {
  if (mode === 'advantage')    return '<div style="color:#28a745;font-size:.7rem;font-weight:600;">&#9650; Advantage — keep highest</div>';
  if (mode === 'disadvantage') return '<div style="color:#fd7e14;font-size:.7rem;font-weight:600;">&#9660; Disadvantage — keep lowest</div>';
  return '';
}

function _mapShowResult(d) {
  const sides = parseInt((d.expression.match(/d(\d+)/) || ['','20'])[1]);
  let dh = '';
  if (d.adv_mode !== 'normal') {
    const ki = d.adv_mode === 'advantage' ? d.dice.indexOf(Math.max(...d.dice)) : d.dice.indexOf(Math.min(...d.dice));
    dh = d.dice.map((v,i) => _mapDieHtml(v, sides, d.adv_mode, i, ki)).join(' ');
  } else {
    dh = d.dice.map(v => _mapDieHtml(v, sides, 'normal', 0, 0)).join(' ');
  }
  const mod = d.modifier !== 0 ? ` ${d.modifier > 0 ? '+' : ''}${d.modifier}` : '';
  const lbl = d.label ? `<div style="color:color-mix(in srgb,var(--ttrpg-text) 70%,transparent);font-size:.7rem;">${_mEsc(d.label)}</div>` : '';
  document.getElementById('map-dice-result-inner').innerHTML =
    `${lbl}${_mapAdvLabel(d.adv_mode)}<div>${dh}${mod ? `<span style="color:color-mix(in srgb,var(--ttrpg-text) 70%,transparent);margin-left:3px;">${mod}</span>` : ''} <span style="opacity:.5;">&#8594;</span> <span style="color:var(--ttrpg-accent);font-weight:bold;font-size:1rem;">${d.total}</span></div>`;
  document.getElementById('map-dice-result').style.display = '';
}

function _mapRenderEntry(d, prepend) {
  const sides = parseInt((d.expression.match(/d(\d+)/) || ['','20'])[1]);
  let dh = '';
  if (d.adv_mode !== 'normal') {
    const ki = d.adv_mode === 'advantage' ? d.dice.indexOf(Math.max(...d.dice)) : d.dice.indexOf(Math.min(...d.dice));
    dh = d.dice.map((v,i) => _mapDieHtml(v, sides, d.adv_mode, i, ki)).join(' ');
  } else {
    dh = d.dice.map(v => _mapDieHtml(v, sides, 'normal', 0, 0)).join(' ');
  }
  const mod     = d.modifier !== 0 ? ` ${d.modifier >= 0 ? '+' : ''}${d.modifier}` : '';
  const modeTag = d.adv_mode !== 'normal'
    ? (d.adv_mode === 'advantage' ? ' <span style="color:#28a745;font-size:.65rem;">&#9650;</span>'
                                  : ' <span style="color:#fd7e14;font-size:.65rem;">&#9660;</span>') : '';
  const html = `<div class="map-feed-entry" data-rid="${d.roll_id}">
    <span style="color:var(--ttrpg-accent);font-weight:600;">${_mEsc(d.char_name)}</span>
    ${d.label ? `<span style="color:color-mix(in srgb,var(--ttrpg-text) 70%,transparent);"> — ${_mEsc(d.label)}</span>` : ''}
    <span style="color:var(--ttrpg-text);"> ${_mEsc(d.expression)}</span>${modeTag}
    <div>${dh}${mod ? `<span style="color:color-mix(in srgb,var(--ttrpg-text) 70%,transparent);">${mod}</span>` : ''} <span style="opacity:.4;">&#8594;</span> <span class="tot">${d.total}</span></div>
  </div>`;
  const feed  = document.getElementById('map-dice-feed');
  const empty = feed.querySelector('p.fx-label');
  if (empty) empty.remove();
  prepend ? feed.insertAdjacentHTML('afterbegin', html) : feed.insertAdjacentHTML('beforeend', html);
}

function _mapRenderRelayEntry(r, prepend) {
  if (document.querySelector(`[data-relay-rid="${r.id}"]`)) return;
  if (r.rolled_at && _mapSeenRolledAts.has(_mapRollKey(r.rolled_at))) return;
  if (r.rolled_at) _mapSeenRolledAts.add(_mapRollKey(r.rolled_at));
  const modMatch = r.breakdown.match(/([+-]\d+)$/);
  const modVal   = modMatch ? parseInt(modMatch[1]) : 0;
  const diceStr  = r.breakdown.replace(/[+-]\d+$/, '');
  const dice     = diceStr.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));
  if (!dice.length) dice.push(r.result - modVal || r.result);
  const exprMatch = r.roll_expr.match(/^(\S+)/);
  const expr      = exprMatch ? exprMatch[1] : r.roll_expr;
  const label     = r.roll_expr.slice(expr.length).trim();
  const sides     = parseInt((expr.match(/d(\d+)/) || ['','20'])[1]);
  const dh = dice.map(v => {
    let cls = 'map-die-val';
    if (sides === 20 && v === 20) cls += ' nat20';
    else if (sides === 20 && v === 1) cls += ' nat1';
    return `<span class="${cls}">${v}</span>`;
  }).join(' ');
  const mod  = modVal !== 0 ? ` ${modVal >= 0 ? '+' : ''}${modVal}` : '';
  const html = `<div class="map-feed-entry" data-relay-rid="${r.id}">
    <span style="color:var(--ttrpg-accent);font-weight:600;">&#127760; ${_mEsc(r.player_name)}</span>
    ${label ? `<span style="color:color-mix(in srgb,var(--ttrpg-text) 70%,transparent);"> — ${_mEsc(label)}</span>` : ''}
    <span style="color:var(--ttrpg-text);"> ${_mEsc(expr)}</span>
    <div>${dh}${mod ? `<span style="color:color-mix(in srgb,var(--ttrpg-text) 70%,transparent);">${mod}</span>` : ''} <span style="opacity:.4;">&#8594;</span> <span class="tot">${r.result}</span></div>
  </div>`;
  const feed  = document.getElementById('map-dice-feed');
  const empty = feed.querySelector('p.fx-label');
  if (empty) empty.remove();
  prepend ? feed.insertAdjacentHTML('afterbegin', html) : feed.insertAdjacentHTML('beforeend', html);
}

// The server returns the feed already ordered by roll TIME (newest first). Render
// it in that order rather than prepending by insertion id, so relay rolls that
// sync late land in their correct chronological place instead of jumping to top.
let _mapFeedSig = '';
function _mapRenderFeed(rolls) {
  const feed = document.getElementById('map-dice-feed');
  if (!feed) return;
  feed.innerHTML = '';
  if (!rolls.length) { feed.innerHTML = '<p class="fx-label">No rolls yet.</p>'; return; }
  rolls.forEach(d => _mapRenderEntry(d, false));
}

function mapFetchFeed() {
  fetch('/ttrpg/dice/feed').then(r => r.json()).then(rolls => {
    _mapRenderFeed(rolls);
    rolls.forEach(d => {
      _mapLastRollId  = Math.max(_mapLastRollId,  d.roll_id);
      _lastSfxRollId  = Math.max(_lastSfxRollId,  d.roll_id);  // don't voice backlog
    });
    _mapFeedSig = rolls.length + ':' + _mapLastRollId;
  });
}

let _feedFails = 0;
function mapPollFeed() {
  // Skip cycles after failures: effective cadence 3.5s → 7s → 14s → 28s cap,
  // so an unreachable server isn't hammered at full speed.
  if (_feedFails > 0 && (mapPollFeed._skip = (mapPollFeed._skip || 0) + 1) %
      Math.min(8, Math.pow(2, _feedFails)) !== 0) return;
  fetch('/ttrpg/dice/feed').then(r => r.json()).then(rolls => {
    _feedFails = 0;
    // crit/fumble is voiced by the dice roller itself (mapDoRoll); no feed echo.
    rolls.forEach(d => { _mapLastRollId = Math.max(_mapLastRollId, d.roll_id); });
    const sig = rolls.length + ':' + _mapLastRollId;
    if (sig !== _mapFeedSig) { _mapFeedSig = sig; _mapRenderFeed(rolls); }
  }).catch(() => { _feedFails++; });
}

function mapResetDice() {
  document.getElementById('map-dice-count').value = 1;
  document.getElementById('map-dice-mod').value   = 0;
  document.getElementById('map-dice-label').value = '';
  mapSelectDie(20);
  mapSetAdvMode('normal');
  document.getElementById('map-dice-result').style.display = 'none';
}

function clearMapDiceFeed() {
  document.getElementById('map-dice-feed').innerHTML = '<p class="fx-label">Feed cleared.</p>';
  document.getElementById('map-dice-result').style.display = 'none';
}

// Top-bar Clear Rolls (DM only). Unlike the panel's tidy-up above, this empties
// the feed on the SERVER: the rolls are shared, so they would otherwise stay on
// every player's map and on the stream overlay, and the next poll would put
// them back here too.
function clearRollFeed(btn) {
  if (!confirm('Clear the roll feed for everyone?\n\nThis removes the roll '
             + 'history from this map, every player\'s map and the stream '
             + 'overlay. It cannot be undone.')) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = 'Clearing…';
  fetch('/ttrpg/dice/clear', {method: 'POST',
                              headers: {'Content-Type': 'application/json'}})
    .then(r => r.json())
    .then(d => {
      btn.disabled = false;
      if (!d || !d.ok) { btn.innerHTML = orig; alert('Could not clear the rolls.'); return; }
      // Reset the poll's bookkeeping too, or the next cycle would see the same
      // signature it already had and skip the re-render.
      _mapLastRollId = 0;
      _mapFeedSig = '';
      clearMapDiceFeed();
      btn.innerHTML = '✓ Cleared';
      setTimeout(() => { btn.innerHTML = orig; }, 2000);
    })
    .catch(() => { btn.disabled = false; btn.innerHTML = orig;
                   alert('Could not reach the server.'); });
}

startPolling();
makeDraggable(document.getElementById('dice-map-panel'), document.getElementById('dice-drag-handle'));
makeDraggable(document.getElementById('fx-panel'), document.getElementById('fx-drag-handle'));
makeDraggable(document.getElementById('notes-map-panel'), document.getElementById('notes-drag-handle'));

// ── DM map notes ──────────────────────────────────────────────────────────────
// Per-map private notes. The panel exists only in the DM's DOM (Jinja-gated)
// and every endpoint is dm_required, so players can neither see nor fetch
// these. List view ↔ editor view inside one floating panel; Back auto-saves
// so a DM tabbing between notes mid-session can't lose an edit.
let _mapNotes     = [];     // last fetched list
let _mapNoteId    = null;   // note being edited (null = new, unsaved)
let _mapNoteClean = '';     // title\n\nbody snapshot at load, for dirty check
let _mapNoteGen   = 0;      // bumped on every editor (re)load — a slow save
                            // response must not touch a newer editing session

function toggleMapNotesPanel() {
  const p   = document.getElementById('notes-map-panel');
  const btn = document.getElementById('notes-toggle-btn');
  if (!p) return;
  const open = p.style.display !== 'block';
  if (open) {
    p.style.display = 'block';
    // Reopening always restores from minimized — a bare header strip
    // appearing on open reads as a broken panel.
    if (p.classList.contains('minimized')) minimizeMapNotesPanel();
    btn.classList.replace('btn-outline-secondary', 'btn-ttrpg');
    mapNotesShowList();
  } else {
    _mapNoteSaveIfDirty();
    p.style.display = 'none';
    btn.classList.replace('btn-ttrpg', 'btn-outline-secondary');
  }
}

function minimizeMapNotesPanel() {
  const p   = document.getElementById('notes-map-panel');
  const btn = document.getElementById('map-notes-minimize-btn');
  if (!p || !btn) return;
  const min = p.classList.toggle('minimized');
  btn.textContent = min ? '+' : '−';
  btn.title = min ? 'Restore' : 'Minimize';
}

function _mapNoteKey() {
  return document.getElementById('map-note-title').value + '\n\n' +
         document.getElementById('map-note-body').value;
}

function mapNotesShowList() {
  const pendingSave = _mapNoteSaveIfDirty();
  _mapNoteGen++;
  _mapNoteId = null;
  document.getElementById('map-notes-editor').style.display    = 'none';
  document.getElementById('map-notes-list-view').style.display = 'block';
  // Wait for the auto-save so the note we just left shows up in the list.
  Promise.resolve(pendingSave).then(() =>
    fetch(`/ttrpg/battlemap/${MAP_ID}/notes/list`)
      .then(r => r.json())
      .then(d => { if (d.ok) { _mapNotes = d.notes; _mapNotesRenderList(); } })
  ).catch(() => {});
}

function _mapNotesRenderList() {
  const host = document.getElementById('map-notes-list');
  if (!_mapNotes.length) {
    host.innerHTML = '<p class="fx-label mb-0">No notes yet for this map.</p>';
    return;
  }
  host.innerHTML = _mapNotes.map((n, i) => {
    const snip = (n.body || '').split('\n')[0].slice(0, 80);
    return `<div class="map-note-row" data-note-id="${n.note_id}"
                 style="display:flex;align-items:center;gap:6px;">
      <div style="flex:1;min-width:0;">
        <div class="mn-title">${_mEsc(n.title || 'Untitled')}</div>
        ${snip ? `<div class="mn-snip">${_mEsc(snip)}</div>` : ''}
        <div class="mn-when">${_mEsc(n.updated_at || '')}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:2px;flex-shrink:0;">
        <button class="fx-close-btn mn-move" data-dir="up" title="Move up"
                style="line-height:1;${i === 0 ? 'visibility:hidden;' : ''}">&#9650;</button>
        <button class="fx-close-btn mn-move" data-dir="down" title="Move down"
                style="line-height:1;${i === _mapNotes.length - 1 ? 'visibility:hidden;' : ''}">&#9660;</button>
      </div>
    </div>`;
  }).join('');
  host.querySelectorAll('.map-note-row').forEach(row => {
    row.addEventListener('click', () => _mapNoteOpen(parseInt(row.dataset.noteId)));
    row.querySelectorAll('.mn-move').forEach(btn =>
      btn.addEventListener('click', e => {
        e.stopPropagation();   // arrows must not open the note
        _mapNoteMove(parseInt(row.dataset.noteId), btn.dataset.dir);
      }));
  });
}

function _mapNoteMove(noteId, direction) {
  fetch(`/ttrpg/battlemap/${MAP_ID}/notes/${noteId}/reorder`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ direction }),
  }).then(r => r.json()).then(d => {
    if (d.ok) mapNotesShowList();
  }).catch(() => {});
}

function _mapNoteOpen(noteId) {
  const n = _mapNotes.find(x => x.note_id === noteId);
  if (!n) return;
  _mapNoteGen++;
  _mapNoteId = noteId;
  document.getElementById('map-note-title').value = n.title || '';
  document.getElementById('map-note-body').value  = n.body  || '';
  _mapNoteClean = _mapNoteKey();
  document.getElementById('map-note-status').textContent = '';
  document.getElementById('map-notes-list-view').style.display = 'none';
  document.getElementById('map-notes-editor').style.display    = 'block';
  document.getElementById('map-note-body').focus();
}

function mapNoteNew() {
  _mapNoteGen++;
  _mapNoteId = null;
  document.getElementById('map-note-title').value = '';
  document.getElementById('map-note-body').value  = '';
  _mapNoteClean = _mapNoteKey();
  document.getElementById('map-note-status').textContent = '';
  document.getElementById('map-notes-list-view').style.display = 'none';
  document.getElementById('map-notes-editor').style.display    = 'block';
  document.getElementById('map-note-title').focus();
}

function mapNoteSave() {
  const title = document.getElementById('map-note-title').value;
  const body  = document.getElementById('map-note-body').value;
  const status = document.getElementById('map-note-status');
  // A completely empty new note is a misclick, not a note.
  if (_mapNoteId == null && !title.trim() && !body.trim()) return;
  const url = _mapNoteId == null
    ? `/ttrpg/battlemap/${MAP_ID}/notes/add`
    : `/ttrpg/battlemap/${MAP_ID}/notes/${_mapNoteId}/update`;
  const gen = _mapNoteGen;
  // keepalive: lets a beforeunload-triggered save finish after the tab closes
  return fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, body }), keepalive: true,
  }).then(r => r.json()).then(d => {
    if (gen !== _mapNoteGen) return;   // editor moved on — don't touch its state
    if (!d.ok) { status.textContent = 'Save failed'; return; }
    if (_mapNoteId == null && d.note_id) _mapNoteId = d.note_id;
    _mapNoteClean = _mapNoteKey();
    status.textContent = 'Saved ✓';
    setTimeout(() => { if (status.textContent === 'Saved ✓') status.textContent = ''; }, 2000);
  }).catch(() => { if (gen === _mapNoteGen) status.textContent = 'Save failed'; });
}

function _mapNoteSaveIfDirty() {
  const ed = document.getElementById('map-notes-editor');
  if (!ed || ed.style.display === 'none') return null;
  return _mapNoteKey() !== _mapNoteClean ? mapNoteSave() : null;
}

function mapNoteDelete() {
  if (_mapNoteId == null) {   // never saved — just discard
    _mapNoteClean = _mapNoteKey();
    mapNotesShowList();
    return;
  }
  if (!confirm('Delete this note?')) return;
  const id = _mapNoteId;
  _mapNoteId = null;
  _mapNoteClean = _mapNoteKey();   // discard edits so Back doesn't resave
  fetch(`/ttrpg/battlemap/${MAP_ID}/notes/${id}/delete`, { method: 'POST' })
    .then(() => mapNotesShowList());
}

// A mid-session tab close shouldn't lose the note being typed.
window.addEventListener('beforeunload', _mapNoteSaveIfDirty);

// ── Volume ────────────────────────────────────────────────────────────────────
let _mapVolTimer = null;
function mapVolChange(val) {
  document.getElementById('map-vol-label').textContent = val;
  clearTimeout(_mapVolTimer);
  _mapVolTimer = setTimeout(() => {
    fetch('/set_volume', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({volume: parseInt(val)})
    });
  }, 120);
}

// ── OBS go-live ───────────────────────────────────────────────────────────────
// Click a party member to cut OBS to their camera. Optimistic highlight, then
// the 2 s state poll corrects from OBS's own event feed (_obsSync) — so a
// scene the DM switches inside OBS also lands here.

function obsStep(direction) {
  fetch('/ttrpg/obs/api/next', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ direction }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert(d.error || 'Could not step the camera rotation.'); return; }
      _obsSync({ connected: true, current_scene: d.current_scene });
    })
    .catch(() => {});
}

function obsJump(position) {
  fetch('/ttrpg/obs/api/next', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ position }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert(d.error || 'Could not switch.'); return; }
      _obsSync({ connected: true, current_scene: d.current_scene });
    })
    .catch(() => {});
}

// Step the stream's map through auto -> 2D -> 3D. A shot call during play, so
// it takes effect on its own — no page, no saving. The server picks the next
// mode so this stays right even if the DM changed it from the Broadcast page.
function obsToggleMapMode() {
  fetch('/ttrpg/obs/api/map-mode', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert(d.error || 'Could not switch the map view.'); return; }
      _obsPaintMapMode(d.mode);
      // Picking a mode releases the pinned character server-side, so drop the
      // lit eye button now rather than waiting for the next poll.
      if (d.unpinned) _obsClearViewButtons();
    })
    .catch(() => {});
}

function _obsPaintMapMode(mode) {
  const btn = document.getElementById('obs-mapmode-btn');
  if (!btn || !mode) return;
  btn.textContent = mode === 'auto' ? 'AUTO' : mode.toUpperCase();
  // Auto and 3D both get the live colour: in either one the stream can be in
  // the player's view, so a glance at the button says "not just the flat map".
  _obsLit(btn, mode === '3d' || mode === 'auto');
}

// Show the map through one character: 3D when the map has the geometry for
// it, otherwise a held close-up on them in 2D. The server decides which,
// because it is the thing that knows whether the map has a floorplan.
function obsViewPlayer(ev, btn) {
  ev.stopPropagation();
  fetch('/ttrpg/obs/api/view-player', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_id: btn.dataset.characterId }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert(d.error || 'Could not switch the view.'); return; }
      document.querySelectorAll('.obs-view-btn').forEach(b => {
        b.classList.remove('btn-outline-success');
        b.classList.add('btn-outline-secondary');
      });
      btn.classList.add('btn-outline-success');
      btn.classList.remove('btn-outline-secondary');
      _obsViewChar = d.character_id;
      // The AUTO/2D/3D button is deliberately NOT repainted: the pin is an
      // override for the moment and the configured mode has not changed.
    })
    .catch(() => {});
}

// The eye's sibling: mute this character's voice on the stream. Same
// optimistic-then-corrected shape — the 2s poll's muted_ids is the authority,
// so a mute made on the Broadcast page or by a scene policy lands here too.
function _obsPaintMapMute(btn, muted) {
  btn.dataset.muted = muted ? '1' : '0';
  btn.innerHTML = muted ? '&#128263;' : '&#128266;';
  btn.classList.toggle('btn-outline-danger', muted);
  btn.classList.toggle('btn-outline-secondary', !muted);
  btn.title = muted ? 'Muted on the stream — click to unmute'
                    : 'Mute this voice on the stream';
}

function obsMuteFromMap(ev, btn) {
  ev.stopPropagation();
  const want = btn.dataset.muted !== '1';
  fetch('/ttrpg/obs/api/mute', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_id: btn.dataset.characterId, muted: want }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert(d.error || 'Could not change the mute.'); return; }
      _obsPaintMapMute(btn, want);
    })
    .catch(() => {});
}

// Table-wide mutes from the strip — the same scopes the Broadcast page's
// three buttons post. No optimistic paint: the server's answer carries the
// full muted set, so every row's speaker icon repaints from it right away
// (and the 2s poll keeps it honest after that).
function obsMapMuteAll(scope, muted) {
  fetch('/ttrpg/obs/api/mute', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ all: scope, muted }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert((d && d.error) || 'Could not change the mutes.'); return; }
      const ids = new Set((d.muted_ids || []).map(String));
      document.querySelectorAll('.obs-mapmute-btn').forEach(b =>
        _obsPaintMapMute(b, ids.has(String(b.dataset.characterId))));
    })
    .catch(() => {});
}

// Whole-table stat cards from the strip: pin everyone to their card, or
// release everyone to camera. Same endpoint the Broadcast page's per-player
// checkboxes use, with the 'all' scope. The tile swap happens server-side.
function obsMapCardAll(on) {
  fetch('/ttrpg/obs/api/card-override', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ all: true, show_card: on }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert((d && d.error) || 'Could not change the stat cards.'); return; }
      const onBtn = document.getElementById('obs-cardon-btn');
      const offBtn = document.getElementById('obs-cardoff-btn');
      if (onBtn) _obsLit(onBtn, on);
      if (offBtn) _obsLit(offBtn, !on);
    })
    .catch(() => {});
}

// Cut OBS to one of the ScenePlay scenes. Optimistic-then-corrected, same as
// obsViewPlayer: the 2s poll is the authority, this just avoids a dead-feeling
// button while the request is in flight.
function obsCut(key, btn) {
  fetch('/ttrpg/obs/api/cut/' + encodeURIComponent(key), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      // The pin is released even when the cut itself failed (OBS offline), so
      // drop the eye highlight on that response too rather than only on 200.
      if (d && d.unpinned) _obsClearViewButtons();
      if (!ok || !d.ok) { alert(d.error || 'Could not cut to that scene.'); return; }
      document.querySelectorAll('.obs-cut-btn').forEach(b => _obsLit(b, b === btn));
    })
    .catch(() => {});
}

// Kept so an already-loaded page (or the M hotkey) still works.
function obsCutMap(btn) { obsCut('map', btn); }

// ── Closeup picker ────────────────────────────────────────────────────────────
// Counting tiles to work out whose number key to press is the wrong thing to be
// doing while someone is mid-sentence. This lists the people on the feed by
// name — character AND the real person — and cuts the closeup on click.
//
// Refetched on every open rather than rendered with the page: who is on the
// group feed changes from the Broadcast page mid-session, and a stale list
// would offer a closeup that lands on the wrong face.

const _CLOSEUP_DOT = {live: '#28a745', ready: '#b8a24a',
                      stale: '#c0392b', nofeed: '#555'};
const _CLOSEUP_TITLE = {
  live: 'Camera feed set, player online',
  ready: 'Camera feed set',
  stale: 'Camera feed set, but the player looks offline',
  nofeed: 'No camera feed yet — their stat card is on screen',
};

function obsToggleCloseups(ev) {
  if (ev) ev.stopPropagation();
  const pop = document.getElementById('obs-closeup-pop');
  if (!pop) return;
  if (pop.style.display === 'block') { obsCloseCloseups(); return; }

  // Anchor beside the strip button, then nudge back on screen if the button
  // sits low enough that a full list would run off the bottom.
  const btn = document.getElementById('obs-closeup-btn');
  const r = btn.getBoundingClientRect();
  pop.style.display = 'block';
  pop.style.left = Math.round(r.right + 8) + 'px';
  pop.style.top = Math.round(
    Math.max(8, Math.min(r.top, window.innerHeight - pop.offsetHeight - 8))) + 'px';

  const list = document.getElementById('obs-closeup-list');
  list.innerHTML = '<div style="color:var(--sp-muted,#8a8371);font-size:.72rem;">Loading…</div>';
  fetch('/ttrpg/obs/api/closeups')
    .then(r2 => r2.json())
    .then(d => _obsRenderCloseups(d && d.ok ? d.rows : []))
    .catch(() => { list.innerHTML =
      '<div style="color:#c0392b;font-size:.72rem;">Could not reach the server.</div>'; });
}

function obsCloseCloseups() {
  const pop = document.getElementById('obs-closeup-pop');
  if (pop) pop.style.display = 'none';
}

function _obsRenderCloseups(rows) {
  const list = document.getElementById('obs-closeup-list');
  if (!rows.length) {
    list.innerHTML = '<div style="color:var(--sp-muted,#8a8371);font-size:.72rem;">'
      + 'Nobody is on the group feed. Tick players on the Broadcast page.</div>';
    return;
  }
  list.innerHTML = '';
  rows.forEach(r => {
    const row = document.createElement('div');
    row.style = 'display:flex;align-items:center;gap:7px;padding:5px 6px;'
      + 'border-radius:6px;cursor:pointer;margin-bottom:2px;'
      + (r.featured ? 'background:rgba(201,168,76,.18);' : '');
    row.onmouseenter = () => { if (!r.featured) row.style.background = 'rgba(255,255,255,.06)'; };
    row.onmouseleave = () => { row.style.background = r.featured ? 'rgba(201,168,76,.18)' : 'transparent'; };
    row.title = _CLOSEUP_TITLE[r.feed] || '';
    row.onclick = () => obsCloseupTo(r.character_id);

    const dot = document.createElement('span');
    dot.style = 'width:8px;height:8px;border-radius:50%;flex:0 0 auto;background:'
      + (_CLOSEUP_DOT[r.feed] || '#555') + ';';

    const names = document.createElement('div');
    names.style = 'min-width:0;flex:1;';
    const who = document.createElement('div');
    who.textContent = r.name;
    who.style = 'color:var(--ttrpg-text,#e8e2d0);font-size:.78rem;line-height:1.2;'
      + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
      + (r.featured ? 'font-weight:700;' : '');
    const player = document.createElement('div');
    // Showing a stat card instead of a camera is worth saying here: it changes
    // what the closeup will actually look like on stream.
    player.textContent = (r.player || '—')
      + (r.showing === 'card' ? ' · stat card' : '');
    player.style = 'color:var(--sp-muted,#8a8371);font-size:.66rem;line-height:1.2;'
      + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    names.appendChild(who);
    names.appendChild(player);

    const key = document.createElement('span');
    key.textContent = r.pos <= 9 ? r.pos : '';
    key.title = r.pos <= 9 ? 'Number key ' + r.pos : '';
    key.style = 'color:var(--sp-muted,#8a8371);font-size:.62rem;flex:0 0 auto;';

    row.appendChild(dot);
    row.appendChild(names);
    row.appendChild(key);
    list.appendChild(row);
  });
}

function obsCloseupTo(characterId) {
  obsCloseCloseups();
  fetch('/ttrpg/obs/api/switch', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({character_id: characterId}),
  })
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok || !d.ok) { alert(d.error || 'Could not cut that closeup.'); return; }
      _obsSync({connected: true, current_scene: d.scene});
    })
    .catch(() => {});
}

// Click-away and Escape close it, like the other transient menus.
document.addEventListener('click', ev => {
  const pop = document.getElementById('obs-closeup-pop');
  if (!pop || pop.style.display !== 'block') return;
  if (!pop.contains(ev.target) && ev.target.id !== 'obs-closeup-btn') obsCloseCloseups();
});
document.addEventListener('keydown', ev => {
  if (ev.key === 'Escape') obsCloseCloseups();
});

function obsGroupShot() {
  fetch('/ttrpg/obs/api/group', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert(d.error || 'No group scene is set.'); return; }
      _obsSync({ connected: true, current_scene: d.current_scene });
    })
    .catch(() => {});
}

// Camera hotkeys for live play: hunting for a small sidebar button mid-combat
// is slow. Only bound when OBS is on and the user is the DM; suppressed while
// typing, and while the 3D viewer is open (it owns WASD and its own keys).
(function () {
  if (typeof OBS_ENABLED === 'undefined' || !OBS_ENABLED) return;
  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (window.BM3D && BM3D.isOpen()) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' ||
              t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (e.key >= '1' && e.key <= '9') { e.preventDefault(); obsJump(parseInt(e.key)); }
    else if (e.key === '0' || e.key.toLowerCase() === 'g') { e.preventDefault(); obsGroupShot(); }
    else if (e.key.toLowerCase() === 'v') { e.preventDefault(); obsToggleMapMode(); }
    else if (e.key.toLowerCase() === 'm') { e.preventDefault(); obsCutMap(document.getElementById('obs-cutmap-btn')); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); obsStep(1); }
    else if (e.key === 'ArrowLeft')  { e.preventDefault(); obsStep(-1); }
  });
})();

function _obsSync(obs) {
  const btns = document.querySelectorAll('.obs-view-btn');
  if (!btns.length) return;
  if (!obs) return;                       // OBS disabled server-side
  // The authority for "is a character pinned" — obsViewPlayer sets it
  // optimistically, this corrects it (including a pin made from another tab).
  _obsViewChar = obs.view_char || null;
  const onMap = !!obs.current_scene && obs.current_scene === obs.map_scene;
  btns.forEach(b => {
    // Lit only when this character is BOTH the pinned viewpoint and the map
    // is what OBS is actually showing — being pinned while the stream is on
    // the party scene is not "on screen".
    const live = onMap && String(obs.view_char || '') === b.dataset.characterId;
    b.classList.toggle('btn-outline-success', live);
    b.classList.toggle('btn-outline-secondary', !live);
    b.classList.toggle('obs-offline', !obs.connected);
    b.title = !obs.connected ? 'OBS is not connected'
            : live ? 'The map is being shown through this character now'
            : 'Show the map through this character (3D if the map supports it)';
  });
  // Speaker buttons follow the persisted mute set, wherever it was changed —
  // Broadcast page, a scene's audio policy, or another tab of this page.
  if (obs.muted_ids) {
    const muted = new Set(obs.muted_ids.map(String));
    document.querySelectorAll('.obs-mapmute-btn').forEach(b => {
      _obsPaintMapMute(b, muted.has(String(b.dataset.characterId)));
    });
  }
  _obsPaintMapMode(obs.map_mode);
  // Light whichever cut button matches the scene OBS is actually on, so the
  // strip reflects the rig even when the DM switched scenes inside OBS.
  const scenes = obs.cut_scenes || {};
  document.querySelectorAll('.obs-cut-btn').forEach(b => {
    _obsLit(b, !!obs.current_scene && obs.current_scene === scenes[b.dataset.cut]);
    b.classList.toggle('obs-offline', !obs.connected);
  });
  const mode = document.getElementById('obs-mapmode-btn');
  if (mode) mode.classList.toggle('obs-offline', !obs.connected);
  // Whole-table card buttons: lit when EVERY tile is pinned (ON) or NONE is
  // (OFF); a mixed table lights neither, since neither button describes it.
  if (obs.cards !== undefined) {
    _obsLit(document.getElementById('obs-cardon-btn'), obs.cards === 'all');
    _obsLit(document.getElementById('obs-cardoff-btn'), obs.cards === 'none');
    ['obs-cardon-btn', 'obs-cardoff-btn'].forEach(id => {
      const b = document.getElementById(id);
      if (b) b.classList.toggle('obs-offline', !obs.connected);
    });
  }
  // Auto-camera watch: the poll is the authority, wherever it was toggled.
  if (obs.auto_cam !== undefined) {
    const ac = document.getElementById('obs-autocam-btn');
    if (ac) {
      ac.dataset.on = obs.auto_cam ? '1' : '0';
      _obsLit(ac, !!obs.auto_cam);
      ac.classList.toggle('obs-offline', !obs.connected);
    }
  }
}

// Auto cameras: dark feed -> stat card, light back -> camera. Optimistic
// paint; the 2s poll corrects it if the save failed or another tab flipped it.
function obsToggleAutoCam(btn) {
  const want = btn.dataset.on !== '1';
  fetch('/ttrpg/obs/api/auto-cam', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ on: want }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok || !d.ok) { alert((d && d.error) || 'Could not toggle auto cameras.'); return; }
      btn.dataset.on = d.on ? '1' : '0';
      _obsLit(btn, d.on);
    })
    .catch(() => {});
}

// Nothing is being viewed through any more — used by every action that
// releases the pin, so they can't drift on how they clear it.
// Whether the 3D view is currently pinned to a character. A background click
// on the map only steers the camera while it is — otherwise the DM's ordinary
// panning and deselect clicks would fire pointless requests.
let _obsViewChar = null;

function _obsClearViewButtons() {
  _obsViewChar = null;
  document.querySelectorAll('.obs-view-btn').forEach(b => {
    b.classList.remove('btn-outline-success');
    b.classList.add('btn-outline-secondary');
  });
}

// The control strip is styled inline, not with Bootstrap classes, so "this is
// on screen" has to be set on the element rather than toggled as a class.
function _obsLit(btn, live) {
  if (!btn) return;
  // Live is signalled by the border ring plus a faint green face tint. The
  // label keeps the theme's accent colour in BOTH states: a hard-coded dark
  // label (an earlier fix for green-on-cream in daylight) vanished on the
  // dark themes, where the face is near-black — the accent token already
  // contrasts with the face on every theme.
  btn.style.borderColor = live ? '#2f7d38' : '#555';
  btn.style.color = 'var(--ttrpg-accent)';
  btn.style.fontWeight = live ? '900' : '';
  btn.style.boxShadow = live ? '0 0 0 2px #3fa14a, inset 0 0 0 100px rgba(63,161,74,.22)' : '';
}

// ── Campaign Scenes ───────────────────────────────────────────────────────────
function mapActivateScene(btn) {
  const sceneId   = btn.dataset.sceneId;
  const sceneName = btn.dataset.sceneName;
  fetch(`/activatescenes/?id=${sceneId}`)
    .then(() => {
      document.querySelectorAll('.map-scene-btn').forEach(b => {
        b.style.borderColor = '#444';
        b.style.color = 'var(--ttrpg-text)';
      });
      btn.style.borderColor = 'var(--ttrpg-accent)';
      btn.style.color = 'var(--ttrpg-accent)';
      const nameEl = document.getElementById('map-active-scene-name');
      const banner = document.getElementById('map-active-scene-banner');
      if (nameEl) nameEl.textContent = sceneName;
      if (banner) banner.style.display = '';
    });
}

// All Stop — mirror the ScenePlay home screen: stop the media queue, then clear
// the active scene. Chained so the queue is killed before the scene is cleared.
function mapAllStop() {
  fetch('/killqueue', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '' })
    .catch(() => {})
    .finally(() => { fetch('/activatescenes/?id=-1').catch(() => {}); });
  // Reset the scene UI: nothing highlighted, banner hidden.
  document.querySelectorAll('.map-scene-btn').forEach(b => {
    b.style.borderColor = '#444';
    b.style.color = 'var(--ttrpg-text)';
  });
  const banner = document.getElementById('map-active-scene-banner');
  if (banner) banner.style.display = 'none';
}

// ── Now playing (Scenes sidebar) ──────────────────────────────────────────────
// Polled from the server so the active scene + current song/video PERSIST
// across page loads and track changes made from any screen (home bar, another
// DM tab). The click handlers above still update instantly; the poll corrects.
function mapRefreshNowPlaying() {
  const banner = document.getElementById('map-active-scene-banner');
  const npBox  = document.getElementById('map-np');
  if (!banner && !npBox) return;   // no scenes sidebar on this view
  fetch('/api/nowplaying')
    .then(r => r.json())
    .then(np => {
      if (banner) {
        const nameEl = document.getElementById('map-active-scene-name');
        if (np.scene) {
          if (nameEl) nameEl.textContent = np.scene.name;
          banner.style.display = '';
        } else {
          banner.style.display = 'none';
        }
        // Re-highlight the active scene's button (matched by id, so it also
        // lights up on a fresh page load).
        document.querySelectorAll('.map-scene-btn').forEach(b => {
          const on = np.scene && parseInt(b.dataset.sceneId) === np.scene.id;
          b.style.borderColor = on ? 'var(--ttrpg-accent)' : '#444';
          b.style.color       = on ? 'var(--ttrpg-accent)' : 'var(--ttrpg-text)';
        });
      }
      if (npBox) {
        // textContent — titles come from YouTube metadata. Each pill hides
        // individually (an empty bordered pill would render as a stray blob).
        const s = document.getElementById('map-np-song');
        const v = document.getElementById('map-np-video');
        s.textContent = np.song  ? '♫ ' + np.song.name  : '';
        v.textContent = np.video ? '▶ ' + np.video.name : '';
        s.style.display = np.song  ? '' : 'none';
        v.style.display = np.video ? '' : 'none';
        npBox.style.display = (np.song || np.video) ? '' : 'none';
      }
    })
    .catch(() => {});   // server restarting — keep last shown values
}
mapRefreshNowPlaying();
setInterval(mapRefreshNowPlaying, 4000);

// ── Grid cell size ─────────────────────────────────────────────────────────────

function setCellPx(val) {
  val = Math.max(32, Math.min(128, val));
  CELL_PX = val;

  const grid  = document.getElementById('map-grid');
  const lines = document.getElementById('map-lines');
  grid.style.width  = (GRID_COLS * CELL_PX) + 'px';
  grid.style.height = (GRID_ROWS * CELL_PX) + 'px';
  lines.style.backgroundSize = CELL_PX + 'px ' + CELL_PX + 'px';

  for (const [tid, tok] of Object.entries(currentTokens)) {
    const el = document.getElementById('tok-' + tid);
    if (!el) continue;
    const span = Math.max(1, tok.size_squares || 1);
    el.style.transform = `translate(${tok.col * CELL_PX}px,${tok.row * CELL_PX}px)`;
    el.style.width     = (span * CELL_PX) + 'px';
    const portrait = el.querySelector('.token-portrait');
    if (portrait) {
      const sz = span * CELL_PX - 6;
      portrait.style.width  = sz + 'px';
      portrait.style.height = sz + 'px';
    }
  }

  for (const eff of Object.values(currentEffects)) {
    const g = document.getElementById('fx-' + eff.effect_id);
    if (g) applyEffectGeometry(g, eff);
  }

  const label = document.getElementById('cell-px-label');
  if (label)  label.textContent = val + 'px';

  if (window.BMFP) BMFP.redraw();   // floorplan layer is drawn in px, not %
  _fpvRender();                     // ditto for the player-visible walls

  try { localStorage.setItem('bm_cell_px_' + MAP_ID, val); } catch(e) {}
}

// ── Fullscreen toggle (iPad-friendly: webkit prefix on older iPadOS) ─────────
function toggleFullscreen() {
  const doc = document, el = doc.documentElement;
  if (doc.fullscreenElement || doc.webkitFullscreenElement) {
    (doc.exitFullscreen || doc.webkitExitFullscreen).call(doc);
  } else {
    (el.requestFullscreen || el.webkitRequestFullscreen).call(el);
  }
}
(function () {
  const btn = document.getElementById('fullscreen-btn');
  if (!btn) return;
  const el = document.documentElement;
  if (!el.requestFullscreen && !el.webkitRequestFullscreen) {
    btn.style.display = 'none';               // iPhone: element fullscreen unsupported
    return;
  }
  ['fullscreenchange', 'webkitfullscreenchange'].forEach(ev =>
    document.addEventListener(ev, () => {
      const fs = !!(document.fullscreenElement || document.webkitFullscreenElement);
      btn.title = fs ? 'Exit full screen' : 'Full screen';
      btn.style.color = fs ? '#7bc77b' : '';
    }));
})();

function adjustCellPx(delta) {
  // Anchor button zoom on the viewport center (same drift fix as pinch).
  const vp = document.getElementById('map-viewport');
  const oldPx = CELL_PX;
  setCellPx(CELL_PX + delta);
  const scale = CELL_PX / oldPx;
  if (vp && scale !== 1) {
    const cx = vp.clientWidth / 2, cy = vp.clientHeight / 2;
    vp.scrollLeft = (vp.scrollLeft + cx) * scale - cx;
    vp.scrollTop  = (vp.scrollTop  + cy) * scale - cy;
  }
}

// Restore saved grid size on load
(function () {
  try {
    const saved = localStorage.getItem('bm_cell_px_' + MAP_ID);
    if (saved) setCellPx(parseInt(saved));
  } catch(e) {}
})();


// ── Sky & weather from the strip ─────────────────────────────────────────────
// Two dropdown modals (never a numbered prompt), then a floorplan save with
// only the "sky" key changed. The floorplan version bump makes every open 3D
// view rebuild on its next poll. Refuses while the floorplan editor holds
// unsaved edits — the save would silently discard them.
function bmSkyPick() {
  if (window.BMFP && BMFP.isDirty && BMFP.isDirty()) {
    alert('Save or revert the floorplan editor first — the sky is stored in the floorplan.');
    return;
  }
  const TIMES = [
    { value: '', label: 'None (dark void)' }, { value: 'night', label: 'Night — stars' },
    { value: 'morning', label: 'Morning' }, { value: 'afternoon', label: 'Afternoon' },
    { value: 'evening', label: 'Evening' }];
  const WEATHER = [
    { value: 'clear', label: 'Sunny / clear' }, { value: 'cloudy', label: 'Cloudy' },
    { value: 'rain', label: 'Rain' }, { value: 'snow', label: 'Snow' },
    { value: 'storm', label: 'Storm (rain + lightning)' }];
  fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`).then(r => r.json()).then(async d => {
    const plan = (d && d.floorplan) || {
      format: 'sceneplay-floorplan', schema_version: 2,
      walls: [], doors: [], elevations: [] };
    const cur = plan.sky || {};
    // Put the current choice first so OK with no change is a no-op.
    const order = (list, v) => list.slice().sort((a, b) => (a.value === v ? -1 : 0) - (b.value === v ? -1 : 0));
    const time = await spPickOption('Sky', 'Time of day for the 3D sky and its lighting.',
                                    'Time', order(TIMES, cur.time || ''), 'Next');
    if (time === null) return;
    let weather = 'clear';
    if (time) {
      weather = await spPickOption('Weather', 'Clear, overcast, or precipitation. Rain and snow stay out of roofed rooms.',
                                   'Weather', order(WEATHER, cur.weather || 'clear'), 'Apply');
      if (weather === null) return;
    }
    if ((cur.time || '') === time && (cur.weather || 'clear') === weather) return;
    if (time) plan.sky = { time, weather }; else delete plan.sky;
    return fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ floorplan: plan }),
    }).then(r => r.json().then(j => ({ ok: r.ok, j })))
      .then(({ ok, j }) => {
        if (!ok || !j.ok) { alert((j && (j.errors || []).join('\n')) || 'Could not save the sky.'); return; }
        _bmPaintSky(time, weather);
      });
  }).catch(() => alert('Could not load the floorplan.'));
}

function _bmPaintSky(time, weather) {
  const b = document.getElementById('bm-sky-btn');
  if (!b) return;
  const ICON = { clear: '\u2600', cloudy: '\u2601', rain: '\u{1F327}', snow: '\u2744', storm: '\u26C8' };
  b.textContent = time ? ((ICON[weather] || '') + ' ' + time.slice(0, 3).toUpperCase()) : 'SKY';
  b.style.borderColor = time ? '#2f7d38' : '#555';
}

// Paint the strip button with the saved sky on load (DM pages only).
document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('bm-sky-btn') || typeof MAP_ID === 'undefined') return;
  fetch(`/ttrpg/battlemap/${MAP_ID}/floorplan`).then(r => r.json())
    .then(d => { const s = (d && d.floorplan && d.floorplan.sky) || {}; _bmPaintSky(s.time || '', s.weather || 'clear'); })
    .catch(() => {});
});

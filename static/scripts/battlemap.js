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

  document.getElementById('tt-speed').textContent =
    tok.speed ? `Speed: ${tok.speed} ft.` : '';

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
      window.open(`/ttrpg/character/${tok.entity_id}`, '_blank');
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
  _moveLabel.textContent = '0 ft';
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
  _moveLabel.textContent = feet + ' ft';
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

    // Ctrl+click or double-click: open sheet in new tab (works for everyone)
    if (_ctrlOnDown && col === _startCol && row === _startRow) {
      _ctrlOpenSheet(currentTokens[tokenId]);
      return;
    }

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
      _hpSfxDiff(d.tokens);   // everyone hears HP changes (incl. DM-applied)
      renderTokens(d.tokens);
      renderEffects(d.effects || []);
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
                  scrollLeft: vp.scrollLeft, scrollTop: vp.scrollTop };
    vp.style.cursor = 'grabbing';
    vp.setPointerCapture(e.pointerId);
  });

  vp.addEventListener('pointermove', e => {
    if (activePointers.has(e.pointerId)) {
      activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    }

    if (pinch && activePointers.size >= 2) {
      const pts = [...activePointers.values()];
      const newDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      if (newDist > 0) setCellPx(Math.round(pinch.cellPx * newDist / pinch.dist));
      return;
    }

    if (!activePan) return;
    vp.scrollLeft = activePan.scrollLeft - (e.clientX - activePan.startX);
    vp.scrollTop  = activePan.scrollTop  - (e.clientY - activePan.startY);
  });

  function endPan(e) {
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
    shape = svgEl('rect', {
      x: px, y: py,
      width:  wCells * CELL_PX,
      height: hCells * CELL_PX,
    });
  }

  if (!shape) return;
  shape.setAttribute('fill',         eff.fill_color);
  shape.setAttribute('fill-opacity', eff.fill_opacity);
  if (eff.shape !== 'cloud') {
    shape.setAttribute('stroke',       eff.border_color);
    shape.setAttribute('stroke-width', '2');
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
  const name = eff ? (eff.label || `${eff.shape} (${eff.size_ft}ft)`) : '';
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
function _sfx(name) { try { console.log('[SFX]', name, 'enabled=' + (window.SFX && SFX.isEnabled())); if (window.SFX) SFX.play(name); } catch (e) { console.warn('[SFX]', name, e); } }
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
  fetch('/ttrpg/dice/roll', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      character_id: null, char_name: MAP_ROLLER_NAME,
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

startPolling();
makeDraggable(document.getElementById('dice-map-panel'), document.getElementById('dice-drag-handle'));
makeDraggable(document.getElementById('fx-panel'), document.getElementById('fx-drag-handle'));

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

  try { localStorage.setItem('bm_cell_px_' + MAP_ID, val); } catch(e) {}
}

function adjustCellPx(delta) { setCellPx(CELL_PX + delta); }

// Restore saved grid size on load
(function () {
  try {
    const saved = localStorage.getItem('bm_cell_px_' + MAP_ID);
    if (saved) setCellPx(parseInt(saved));
  } catch(e) {}
})();

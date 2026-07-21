/* static/scripts/character_sheet.js
   Character-sheet page logic, extracted from templates/ttrpg/character_sheet.html.
   Page data (CHAR_ID, CHAR_NAME, DEX_MOD, ARMOR_LIST, _refUrls, _llmChar,
   _pasteUploadUrl, ...) is defined by an inline <script> in the template
   BEFORE this file loads. */
// Safe SFX trigger — never let a missing/broken sound module touch sheet logic.
function _sfx(name) { try { if (window.SFX) SFX.play(name); } catch (e) {} }

// ── Tab persistence across reloads ────────────────────────────
const TAB_KEY = `sheet_tab_${CHAR_ID}`;
function reloadKeepTab() {
  const active = document.querySelector('#sheetTabs .nav-link.active');
  if (active) sessionStorage.setItem(TAB_KEY, active.dataset.bsTarget);
  location.reload();
}
(function restoreTab() {
  const saved = sessionStorage.getItem(TAB_KEY);
  if (!saved) return;
  sessionStorage.removeItem(TAB_KEY);
  const btn = document.querySelector(`#sheetTabs [data-bs-target="${saved}"]`);
  if (btn) bootstrap.Tab.getOrCreateInstance(btn).show();
})();

// ── Inline edit helpers ───────────────────────────────────────
function editToggle(type, id) {
  const view = document.getElementById(type + '-view-' + id);
  const form = document.getElementById(type + '-edit-' + id);
  const editing = form.style.display !== 'none';
  view.style.display = editing ? '' : 'none';
  form.style.display = editing ? 'none' : '';
}

function saveResource(id) {
  fetch(`/ttrpg/resource/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      resource_name: document.getElementById('res-name-' + id).value.trim(),
      current_val:   document.getElementById('res-cur-edit-' + id).value,
      max_val:       document.getElementById('res-max-edit-' + id).value
    })
  }).then(r => r.json()).then(d => { if (d.ok) reloadKeepTab(); });
}

function saveSkill(id) {
  fetch(`/ttrpg/skill/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      skill_name: document.getElementById('skill-name-' + id).value.trim(),
      bonus:      document.getElementById('skill-bonus-' + id).value,
      proficient: document.getElementById('skill-prof-' + id).checked ? 1 : 0
    })
  }).then(r => r.json()).then(d => { if (d.ok) reloadKeepTab(); });
}

function saveItem(id) {
  fetch(`/ttrpg/inventory/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      item_name: document.getElementById('item-name-' + id).value.trim(),
      quantity:  document.getElementById('item-qty-' + id).value,
      notes:     document.getElementById('item-notes-' + id).value,
      equipped:  document.getElementById('item-equip-' + id).checked ? 1 : 0
    })
  }).then(r => r.json()).then(d => { if (d.ok) reloadKeepTab(); });
}

function saveNote(id) {
  fetch(`/ttrpg/note/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({note_text: document.getElementById('note-text-edit-' + id).value.trim()})
  }).then(r => r.json()).then(d => { if (d.ok) reloadKeepTab(); });
}

function saveFeat(id) {
  fetch(`/ttrpg/feat/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      feat_name:   document.getElementById('feat-name-' + id).value.trim(),
      description: document.getElementById('feat-desc-' + id).value.trim()
    })
  }).then(r => r.json()).then(d => { if (d.ok) reloadKeepTab(); });
}

document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
  new bootstrap.Tooltip(el, {trigger: 'hover focus'});
});

function _escH(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
document.querySelectorAll('.spell-chip').forEach(el => {
  const d = el.dataset;
  const rows = [];
  const lvl = _escH(d.slevel) + (d.sschool ? ' &bull; ' + _escH(d.sschool) : '');
  rows.push('<b>' + lvl + '</b>');
  const castParts = [];
  if (d.scast) castParts.push('&#9200; ' + _escH(d.scast));
  if (d.srange) castParts.push('Range: ' + _escH(d.srange));
  if (castParts.length) rows.push(castParts.join(' &bull; '));
  if (d.sdur) {
    let durLine = '&#9203; ' + _escH(d.sdur);
    if (d.sconc === '1') durLine += ' <em>(Conc)</em>';
    if (d.sritual === '1') durLine += ' <em>[Ritual]</em>';
    rows.push(durLine);
  }
  if (d.scomp) rows.push('<small style="opacity:.8">' + _escH(d.scomp) + '</small>');
  if (d.sdesc) rows.push('<small>' + _escH(d.sdesc) + (d.sdescLong === '1' ? '&hellip;' : '') + '</small>');
  new bootstrap.Popover(el, {
    html: true,
    title: _escH(d.sname),
    content: rows.join('<br>'),
    trigger: 'hover focus',
    container: 'body',
    customClass: 'spell-popover',
    placement: 'bottom',
  });
});

// ── HP controls ──────────────────────────────────────────────
function hpAmount() {
  return parseInt(document.getElementById('hp_amount').value) || 1;
}

function applyHpDelta(delta) {
  fetch(`/ttrpg/character/${CHAR_ID}/hp-delta`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({delta})
  }).then(r => r.json()).then(data => {
    if (!data.ok) return;
    // Voice the change on the device that applied it.
    if (delta < 0)      _sfx(data.hp_current <= 0 ? 'dead' : 'damage');
    else if (delta > 0) _sfx('heal');
    document.getElementById('hp_current_disp').textContent = data.hp_current;
    updateHpBar(data.hp_pct);
  });
}

function updateHpBar(pct) {
  const bar = document.getElementById('hp_bar');
  bar.style.width = pct + '%';
  bar.style.background = pct > 50 ? '#28a745' : pct > 20 ? '#ffc107' : '#dc3545';
  document.getElementById('hp_pct_disp').textContent = pct + '%';
}

function saveField(field, value, cb) {
  fetch(`/ttrpg/character/${CHAR_ID}/save-field`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({field, value})
  }).then(r => r.json()).then(data => { if (cb) cb(data); });
}

// ── Attribute steppers (−/+) ──────────────────────────────────
// which='score' adjusts the score by ±1; which='mod' adjusts the modifier by ±1
// (i.e. score by ±2). Updates both displayed values and saves (no reload).
function stepAttr(field, which, delta, btn) {
  const box = btn.closest('.attr-box');
  if (!box) return;
  const scoreEl = box.querySelector('.score');
  const modEl   = box.querySelector('.mod');
  let score = parseInt(scoreEl.textContent) || 10;
  if (which === 'mod') {
    score = (Math.floor((score - 10) / 2) + delta) * 2 + 10;
  } else {
    score = score + delta;
  }
  score = Math.max(1, Math.min(30, score));
  const m = Math.floor((score - 10) / 2);
  scoreEl.textContent = score;
  modEl.textContent   = (m >= 0 ? '+' : '') + m;
  saveField(field, score);   // persist; no page reload
}

// ── Attribute inline edit ─────────────────────────────────────
function startAttrEdit(el, isMod) {
  if (el.querySelector('input')) return; // already editing
  const field = el.dataset.field;
  const orig  = el.textContent.trim();
  // For modifier, strip the sign so the input shows a plain integer
  const current = isMod ? parseInt(orig) : parseInt(orig);

  const input = document.createElement('input');
  input.type  = 'number';
  input.value = current;
  input.min   = isMod ? -5 : 1;
  input.max   = isMod ? 10 : 30;
  input.style.cssText = [
    'width:52px', 'text-align:center', 'font-size:inherit', 'font-weight:inherit',
    'background:var(--sp-input-bg)', 'color:var(--sp-text)',
    'border:1px solid var(--ttrpg-accent)', 'border-radius:3px', 'padding:1px 2px'
  ].join(';');

  el.textContent = '';
  el.appendChild(input);
  input.focus();
  input.select();

  let committed = false;
  function commit() {
    if (committed) return;
    committed = true;
    const val = parseInt(input.value);
    if (isNaN(val)) { el.textContent = orig; return; }
    // If editing the modifier, back-calculate the score: score = mod * 2 + 10
    const scoreVal = isMod ? (val * 2 + 10) : val;
    el.textContent = orig; // restore text while saving
    saveField(field, scoreVal, () => reloadKeepTab());
  }

  input.addEventListener('blur',    () => commit());
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { committed = true; el.textContent = orig; }
  });
}

// ── Resources ────────────────────────────────────────────────
function addResource() {
  const name = document.getElementById('new_res_name').value.trim();
  if (!name) return;
  fetch(`/ttrpg/character/${CHAR_ID}/resources`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({resource_name: name,
                          current_val: document.getElementById('new_res_cur').value,
                          max_val: document.getElementById('new_res_max').value})
  }).then(() => reloadKeepTab());
}

function deltaResource(id, delta) {
  fetch(`/ttrpg/resource/${id}/delta`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({delta})
  }).then(r => r.json()).then(data => {
    if (!data.ok) return;
    document.getElementById('res-cur-' + id).textContent = data.current_val;
    // Refresh pips
    const pips = document.querySelectorAll(`#res-pips-${id} .res-pip`);
    pips.forEach((pip, i) => {
      pip.style.background = i < data.current_val ? 'var(--ttrpg-accent)' : 'transparent';
    });
  });
}

function deleteResource(id) {
  if (!confirm('Remove this resource?')) return;
  fetch(`/ttrpg/resource/${id}`, {method:'DELETE'}).then(() => {
    document.getElementById('res-'+id).remove();
  });
}

// ── Skills ───────────────────────────────────────────────────
function addSkill() {
  const name = document.getElementById('new_skill_name').value.trim();
  if (!name) return;
  fetch(`/ttrpg/character/${CHAR_ID}/skills`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({skill_name: name,
                          bonus: document.getElementById('new_skill_bonus').value,
                          proficient: document.getElementById('new_skill_prof').checked ? 1 : 0})
  }).then(() => reloadKeepTab());
}

function deleteSkill(id) {
  if (!confirm('Remove this skill?')) return;
  fetch(`/ttrpg/skill/${id}`, {method:'DELETE'}).then(() => {
    document.getElementById('skill-'+id).remove();
  });
}

// ── Inventory ────────────────────────────────────────────────
function addItem() {
  const name = document.getElementById('new_item_name').value.trim();
  if (!name) return;
  fetch(`/ttrpg/character/${CHAR_ID}/inventory`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      item_name: name,
      quantity:  document.getElementById('new_item_qty').value,
      weight:    document.getElementById('new_item_weight').value,
      notes:     document.getElementById('new_item_notes').value,
    })
  }).then(() => reloadKeepTab());
}

let _equipSearchTimer = null;
let _equipResults = [];
function equipSearch(q) {
  clearTimeout(_equipSearchTimer);
  const box = document.getElementById('equip-suggestions');
  if (!box) return;
  _equipSearchTimer = setTimeout(() => {
    // Mundane equipment AND magic items in one dropdown; magic entries carry a
    // tag and their rarity/attunement line rides into the item's notes on pick.
    Promise.all([
      fetch(`/ttrpg/reference/equipment/search?q=${encodeURIComponent(q)}`)
        .then(r => r.json()).catch(() => []),
      fetch(`/ttrpg/reference/lookup/magicitems?q=${encodeURIComponent(q)}&limit=10`)
        .then(r => r.json()).catch(() => []),
    ]).then(([equip, magic]) => {
        const results = [
          ...equip,
          ...magic.map(m => ({name: m.name, category: '✦ ' + (m.sub || 'Magic Item'),
                              description: m.desc || '', magicSub: m.sub || '', magic: true})),
        ];
        if (!results.length) { box.style.display = 'none'; return; }
        _equipResults = results;
        box.innerHTML = results.map((it, i) => `
          <div data-idx="${i}"
               style="padding:7px 10px;cursor:pointer;border-bottom:1px solid var(--sp-border);"
               onmouseenter="this.style.background='color-mix(in srgb,var(--sp-accent) 10%,transparent)'"
               onmouseleave="this.style.background=''">
            <div style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</div>
            <div style="font-size:.7rem;color:var(--sp-muted);">
              ${it.category ? _escH(it.category) : ''}
              ${it.subcategory ? ' &rsaquo; ' + _escH(it.subcategory) : ''}
              ${it.weight ? ' &mdash; ' + it.weight + ' lb' : ''}
              ${it.cost  ? ' &bull; ' + _escH(it.cost) : ''}
            </div>
            ${it.description ? `<div style="font-size:.68rem;color:var(--sp-muted);margin-top:2px;
                                            white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
                                            max-width:360px;">${_escH(it.description.slice(0,120))}${it.description.length > 120 ? '…' : ''}</div>` : ''}
          </div>`).join('');
        box.querySelectorAll('[data-idx]').forEach(el =>
          el.addEventListener('click', () => equipPick(_equipResults[parseInt(el.dataset.idx)])));
        box.style.display = 'block';
      });
  }, 150);
}

function equipPick(it) {
  document.getElementById('new_item_name').value   = it.name;
  document.getElementById('new_item_weight').value = it.weight || '';
  document.getElementById('equip-suggestions').style.display = 'none';

  // Magic items: carry rarity/attunement + description into the notes field so
  // the item's text lives on the sheet (and rides to the relay with it).
  if (it.magic) {
    const notes = [it.magicSub, (it.description || '').slice(0, 240)
                   + ((it.description || '').length > 240 ? '…' : '')]
      .filter(Boolean).join(' — ');
    document.getElementById('new_item_notes').value = notes;
  }

  // Show detail preview card
  document.getElementById('equip-prev-name').textContent = it.name;
  const catEl = document.getElementById('equip-prev-cat');
  catEl.textContent = [it.category, it.subcategory].filter(Boolean).join(' › ');
  catEl.style.display = catEl.textContent ? '' : 'none';

  const meta = [];
  if (it.weight) meta.push('⚖ ' + it.weight + ' lb');
  if (it.cost)   meta.push('💰 ' + it.cost);
  document.getElementById('equip-prev-meta').textContent = meta.join('  •  ');
  document.getElementById('equip-prev-desc').textContent = it.description || '';
  document.getElementById('equip-preview').style.display = '';
}

function clearEquipPick() {
  document.getElementById('new_item_name').value   = '';
  document.getElementById('new_item_weight').value = '';
  document.getElementById('equip-preview').style.display = 'none';
}

document.addEventListener('click', e => {
  const box = document.getElementById('equip-suggestions');
  if (box && !e.target.closest('#equip-suggestions') && e.target.id !== 'new_item_name')
    box.style.display = 'none';
});

function deleteItem(id) {
  if (!confirm('Remove item?')) return;
  fetch(`/ttrpg/inventory/${id}`, {method:'DELETE'}).then(() => {
    document.getElementById('item-'+id).remove();
  });
}

// ── Notes ─────────────────────────────────────────────────────
function addNote() {
  const text = document.getElementById('new_note_text').value.trim();
  if (!text) return;
  fetch(`/ttrpg/character/${CHAR_ID}/notes`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({note_text: text})
  }).then(r => r.json()).then(data => {
    if (data.ok) reloadKeepTab();
  });
}

function deleteNote(id) {
  if (!confirm('Delete note?')) return;
  fetch(`/ttrpg/note/${id}`, {method:'DELETE'}).then(() => {
    document.getElementById('note-'+id).remove();
  });
}

// ── Feats ─────────────────────────────────────────────────────
let _featSearchTimer = null;
let _featResults = [];
function featLibSearch(q) {
  clearTimeout(_featSearchTimer);
  const box = document.getElementById('feat-suggestions');
  // no minimum length: an empty query (a click) shows the full list, typing narrows it
  _featSearchTimer = setTimeout(() => {
    fetch(`/ttrpg/reference/feats/search?q=${encodeURIComponent(q)}`)
      .then(r => r.json()).then(results => {
        if (!results.length) { box.style.display = 'none'; return; }
        _featResults = results;
        box.innerHTML = results.map((f, i) => `
          <div data-idx="${i}"
               style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--sp-border);"
               onmouseenter="this.style.background='color-mix(in srgb, var(--sp-accent) 10%, transparent)'"
               onmouseleave="this.style.background=''">
            <div style="color:var(--ttrpg-accent);font-weight:600;">${f.name}</div>
            ${f.prerequisites ? `<div style="font-size:.7rem;color:var(--sp-muted);">Req: ${f.prerequisites}</div>` : ''}
          </div>`).join('');
        box.querySelectorAll('[data-idx]').forEach(el =>
          el.addEventListener('click', () => {
            const f = _featResults[parseInt(el.dataset.idx)];
            featLibPick(f.name, f.description);
          }));
        box.style.display = 'block';
      });
  }, 220);
}
function featLibPick(name, desc) {
  document.getElementById('new_feat_name').value = name;
  document.getElementById('new_feat_desc').value = desc;
  document.getElementById('feat-suggestions').style.display = 'none';
  addFeat();
}
document.addEventListener('click', e => {
  if (!e.target.closest('#feat-suggestions') && e.target.id !== 'new_feat_name')
    document.getElementById('feat-suggestions').style.display = 'none';
});

function addFeat() {
  const name = document.getElementById('new_feat_name').value.trim();
  if (!name) return;
  fetch(`/ttrpg/character/${CHAR_ID}/feats`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({feat_name: name,
                          description: document.getElementById('new_feat_desc').value.trim()})
  }).then(() => reloadKeepTab());
}

function deleteFeat(id) {
  if (!confirm('Remove this feat?')) return;
  fetch(`/ttrpg/feat/${id}`, {method: 'DELETE'}).then(() => {
    document.getElementById('feat-' + id).remove();
  });
}

// ── Conditions ───────────────────────────────────────────────
function toggleCharCondPanel() {
  const el = document.getElementById('char-cond-panel');
  el.style.setProperty('display', el.style.display === 'none' ? 'flex' : 'none', 'important');
}

function charAddCondition(condition) {
  fetch(`/ttrpg/character/${CHAR_ID}/condition`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action:'add', condition})
  }).then(() => reloadKeepTab());
}

function charRemoveCondition(condition) {
  fetch(`/ttrpg/character/${CHAR_ID}/condition`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action:'remove', condition})
  }).then(() => reloadKeepTab());
}

// ── Weapons ───────────────────────────────────────────────────
let _weapSearchTimer = null;
let _weapResults = [];
function weapLibSearch(q) {
  clearTimeout(_weapSearchTimer);
  const box = document.getElementById('weap-suggestions');
  // no minimum length: an empty query (a click) shows the full list, typing narrows it
  _weapSearchTimer = setTimeout(() => {
    fetch(`/ttrpg/reference/weapons/search?q=${encodeURIComponent(q)}`)
      .then(r => r.json()).then(results => {
        if (!results.length) { box.style.display = 'none'; return; }
        _weapResults = results;
        box.innerHTML = results.map((w, i) => `
          <div data-idx="${i}"
               style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--sp-border);"
               onmouseenter="this.style.background='color-mix(in srgb, var(--sp-accent) 10%, transparent)'"
               onmouseleave="this.style.background=''">
            <div style="color:var(--ttrpg-accent);font-weight:600;">${w.name}</div>
            <div style="font-size:.7rem;color:var(--sp-muted);">
              ${w.weapon_category} ${w.weapon_range}
              ${w.damage_dice ? '&mdash; ' + w.damage_dice + ' ' + w.damage_type : ''}
              ${w.properties ? '&bull; ' + w.properties : ''}
            </div>
          </div>`).join('');
        box.querySelectorAll('[data-idx]').forEach(el =>
          el.addEventListener('click', () => weapLibPick(_weapResults[parseInt(el.dataset.idx)])));
        box.style.display = 'block';
      });
  }, 220);
}

function weapLibPick(w) {
  document.getElementById('new_weap_name').value         = w.name;
  document.getElementById('new_weap_lib_id').value       = w.weapon_lib_id;
  document.getElementById('new_weap_category').value     = w.weapon_category;
  document.getElementById('new_weap_range').value        = w.weapon_range;
  document.getElementById('new_weap_damage_dice').value  = w.damage_dice;
  document.getElementById('new_weap_damage_type').value  = w.damage_type;
  document.getElementById('new_weap_2h_dice').value      = w.two_handed_damage_dice;
  document.getElementById('new_weap_2h_type').value      = w.two_handed_damage_type;
  document.getElementById('new_weap_range_normal').value = w.range_normal;
  document.getElementById('new_weap_range_long').value   = w.range_long;
  document.getElementById('new_weap_properties').value   = w.properties;
  document.getElementById('new_weap_notes').value        = w.notes || '';
  document.getElementById('weap-suggestions').style.display = 'none';
  addWeaponToChar();
}

document.addEventListener('click', e => {
  if (!e.target.closest('#weap-suggestions') && e.target.id !== 'new_weap_name')
    document.getElementById('weap-suggestions').style.display = 'none';
});

function addWeaponToChar() {
  const name = document.getElementById('new_weap_name').value.trim();
  if (!name) return;
  fetch(`/ttrpg/character/${CHAR_ID}/weapons`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      weapon_name:            name,
      weapon_lib_id:          document.getElementById('new_weap_lib_id').value || null,
      weapon_category:        document.getElementById('new_weap_category').value,
      weapon_range:           document.getElementById('new_weap_range').value,
      damage_dice:            document.getElementById('new_weap_damage_dice').value,
      damage_type:            document.getElementById('new_weap_damage_type').value,
      two_handed_damage_dice: document.getElementById('new_weap_2h_dice').value,
      two_handed_damage_type: document.getElementById('new_weap_2h_type').value,
      range_normal:           parseInt(document.getElementById('new_weap_range_normal').value) || 0,
      range_long:             parseInt(document.getElementById('new_weap_range_long').value)   || 0,
      properties:             document.getElementById('new_weap_properties').value,
      notes:                  document.getElementById('new_weap_notes').value,
      attack_bonus: 0, damage_bonus: 0, equipped: 0,
    })
  }).then(() => reloadKeepTab());
}

function toggleCustomWeapForm() {
  const f = document.getElementById('custom-weap-form');
  f.style.display = f.style.display === 'none' ? '' : 'none';
  if (f.style.display !== 'none') document.getElementById('cw_name').focus();
}

function addCustomWeapon() {
  const name = document.getElementById('cw_name').value.trim();
  if (!name) { document.getElementById('cw_name').focus(); return; }
  fetch(`/ttrpg/character/${CHAR_ID}/weapons`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      weapon_name:            name,
      weapon_lib_id:          null,
      weapon_category:        document.getElementById('cw_category').value,
      weapon_range:           document.getElementById('cw_range').value,
      damage_dice:            document.getElementById('cw_dmg_dice').value,
      damage_type:            document.getElementById('cw_dmg_type').value,
      two_handed_damage_dice: document.getElementById('cw_2h_dice').value,
      two_handed_damage_type: document.getElementById('cw_2h_type').value,
      range_normal:           parseInt(document.getElementById('cw_range_normal').value) || 0,
      range_long:             parseInt(document.getElementById('cw_range_long').value)   || 0,
      properties:             document.getElementById('cw_properties').value,
      notes:                  document.getElementById('cw_notes').value,
      attack_bonus:           parseInt(document.getElementById('cw_atk_bonus').value)    || 0,
      damage_bonus:           parseInt(document.getElementById('cw_dmg_bonus').value)    || 0,
      equipped: 0,
    })
  }).then(() => reloadKeepTab());
}

function toggleWeapEquip(id, current) {
  fetch(`/ttrpg/char-weapon/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({equipped: current ? 0 : 1})
  }).then(() => reloadKeepTab());
}

function toggleWeapEdit(id) {
  const p = document.getElementById('weap-edit-' + id);
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
}

function saveWeapEntry(id) {
  fetch(`/ttrpg/char-weapon/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      attack_bonus: document.getElementById('weap-atk-'   + id).value,
      damage_bonus: document.getElementById('weap-dmg-'   + id).value,
      notes:        document.getElementById('weap-notes-' + id).value,
    })
  }).then(r => r.json()).then(d => { if (d.ok) reloadKeepTab(); });
}

function deleteWeapEntry(id) {
  if (!confirm('Remove this weapon from the character?')) return;
  fetch(`/ttrpg/char-weapon/${id}`, {method: 'DELETE'})
    .then(() => document.getElementById('char-weapon-' + id).remove());
}

// ── Armor & Shields ───────────────────────────────────────────
// DEX_MOD / ARMOR_LIST come from the inline page config in character_sheet.html

function calcSuggestedAC() {
  let bodyAC = null;
  let shieldBonus = 0;
  ARMOR_LIST.forEach(a => {
    if (!a.equipped) return;
    const base = a.armor_class_base + a.ac_bonus;
    if (a.armor_category === 'Shield') {
      shieldBonus += base;
    } else {
      let ac = base;
      if (a.dex_bonus) {
        let dex = DEX_MOD;
        if (a.max_dex_bonus !== null) dex = Math.min(dex, a.max_dex_bonus);
        ac += dex;
      }
      bodyAC = ac;
    }
  });
  const lbl = document.getElementById('ac-suggest-label');
  if (!lbl) return;
  if (bodyAC !== null) {
    lbl.textContent = `Suggested AC: ${bodyAC + shieldBonus}`;
    lbl.style.color = 'var(--ttrpg-accent)';
  } else {
    lbl.textContent = '';
  }
}
calcSuggestedAC();

// Library search typeahead
let _armorSearchTimer = null;
let _armorResults = [];
function armorLibSearch(q) {
  clearTimeout(_armorSearchTimer);
  const box = document.getElementById('armor-suggestions');
  // no minimum length: an empty query (a click) shows the full list, typing narrows it
  _armorSearchTimer = setTimeout(() => {
    fetch(`/ttrpg/reference/armor/search?q=${encodeURIComponent(q)}`)
      .then(r => r.json()).then(results => {
        if (!results.length) { box.style.display = 'none'; return; }
        _armorResults = results;
        box.innerHTML = results.map((a, i) => `
          <div data-idx="${i}"
               style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--sp-border);"
               onmouseenter="this.style.background='color-mix(in srgb, var(--sp-accent) 10%, transparent)'"
               onmouseleave="this.style.background=''">
            <div style="color:var(--ttrpg-accent);font-weight:600;">${a.name}</div>
            <div style="font-size:.7rem;color:var(--sp-muted);">
              ${a.armor_category}
              — AC ${a.armor_category === 'Shield' ? '+' : ''}${a.armor_class_base}
              ${a.dex_bonus ? '+ DEX' + (a.max_dex_bonus !== null ? ` (max ${a.max_dex_bonus})` : '') : ''}
              &bull; ${a.cost || '—'}
            </div>
          </div>`).join('');
        box.querySelectorAll('[data-idx]').forEach(el =>
          el.addEventListener('click', () => armorLibPick(_armorResults[parseInt(el.dataset.idx)])));
        box.style.display = 'block';
      });
  }, 220);
}

function armorLibPick(a) {
  document.getElementById('new_armor_name').value       = a.name;
  document.getElementById('new_armor_lib_id').value     = a.armor_lib_id;
  document.getElementById('new_armor_category').value   = a.armor_category;
  document.getElementById('new_armor_class_base').value = a.armor_class_base;
  document.getElementById('new_armor_dex_bonus').value  = a.dex_bonus;
  document.getElementById('new_armor_max_dex').value    = a.max_dex_bonus !== null ? a.max_dex_bonus : '';
  document.getElementById('new_armor_notes').value      = a.notes || '';
  document.getElementById('armor-suggestions').style.display = 'none';
  addArmorToChar();
}

document.addEventListener('click', e => {
  if (!e.target.closest('#armor-suggestions') && e.target.id !== 'new_armor_name')
    document.getElementById('armor-suggestions').style.display = 'none';
});

function addArmorToChar() {
  const name = document.getElementById('new_armor_name').value.trim();
  if (!name) return;
  const maxDexRaw = document.getElementById('new_armor_max_dex').value;
  fetch(`/ttrpg/character/${CHAR_ID}/armor`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      armor_name:       name,
      armor_lib_id:     document.getElementById('new_armor_lib_id').value || null,
      armor_category:   document.getElementById('new_armor_category').value,
      armor_class_base: parseInt(document.getElementById('new_armor_class_base').value) || 0,
      dex_bonus:        parseInt(document.getElementById('new_armor_dex_bonus').value) || 0,
      max_dex_bonus:    maxDexRaw === '' ? null : parseInt(maxDexRaw),
      notes:            document.getElementById('new_armor_notes').value,
      ac_bonus: 0, equipped: 0,
    })
  }).then(() => reloadKeepTab());
}

function toggleArmorEquip(id, currentEquipped) {
  const newVal = currentEquipped ? 0 : 1;
  fetch(`/ttrpg/char-armor/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({equipped: newVal})
  }).then(() => reloadKeepTab());
}

function toggleArmorEdit(id) {
  const panel = document.getElementById('armor-edit-' + id);
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

function saveArmorEntry(id) {
  fetch(`/ttrpg/char-armor/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      ac_bonus: document.getElementById('armor-bonus-' + id).value,
      notes:    document.getElementById('armor-notes-' + id).value,
    })
  }).then(r => r.json()).then(d => { if (d.ok) reloadKeepTab(); });
}

function deleteArmorEntry(id) {
  if (!confirm('Remove this armor from the character?')) return;
  fetch(`/ttrpg/char-armor/${id}`, {method: 'DELETE'})
    .then(() => document.getElementById('char-armor-' + id).remove());
}

// ── Spells ────────────────────────────────────────────────────
let _spellSearchTimer = null;
let _spellResults = [];
function spellLibSearch(q) {
  clearTimeout(_spellSearchTimer);
  const box = document.getElementById('spell-suggestions');
  // no minimum length: an empty query (a click) shows the full list, typing narrows it
  _spellSearchTimer = setTimeout(() => {
    fetch(`/ttrpg/reference/spells/search?q=${encodeURIComponent(q)}&limit=500`)
      .then(r => r.json()).then(results => {
        if (!results.length) { box.style.display = 'none'; return; }
        _spellResults = results;
        box.innerHTML = results.map((s, i) => {
          const lvlLabel = s.level === 0 ? 'Cantrip' : `Level ${s.level}`;
          return `<div data-idx="${i}"
               style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--sp-border);"
               onmouseenter="this.style.background='color-mix(in srgb, var(--sp-accent) 10%, transparent)'"
               onmouseleave="this.style.background=''">
            <div style="color:var(--ttrpg-accent);font-weight:600;">${s.name}</div>
            <div style="font-size:.7rem;color:var(--sp-muted);">
              ${lvlLabel}${s.school ? ' &bull; ' + s.school : ''}
              ${s.classes_text ? ' &mdash; ' + s.classes_text : ''}
            </div>
          </div>`;
        }).join('');
        box.querySelectorAll('[data-idx]').forEach(el =>
          el.addEventListener('click', () => spellLibPick(_spellResults[parseInt(el.dataset.idx)])));
        box.style.display = 'block';
      });
  }, 220);
}

function spellLibPick(s) {
  document.getElementById('new_spell_name').value  = s.name;
  document.getElementById('new_spell_lib_id').value = s.spell_lib_id;
  document.getElementById('new_spell_level').value  = s.level;
  document.getElementById('new_spell_school').value = s.school;
  document.getElementById('spell-suggestions').style.display = 'none';
  addSpellToChar();
}

document.addEventListener('click', e => {
  if (!e.target.closest('#spell-suggestions') && e.target.id !== 'new_spell_name')
    if (document.getElementById('spell-suggestions'))
      document.getElementById('spell-suggestions').style.display = 'none';
});

function addSpellToChar() {
  const name = document.getElementById('new_spell_name').value.trim();
  if (!name) return;
  fetch(`/ttrpg/character/${CHAR_ID}/spells`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      spell_name:  name,
      spell_lib_id: document.getElementById('new_spell_lib_id').value || null,
      spell_level:  parseInt(document.getElementById('new_spell_level').value) || 0,
      school:       document.getElementById('new_spell_school').value,
      prepared: 0, notes: '',
    })
  }).then(() => reloadKeepTab());
}

function toggleCustomSpellForm() {
  const f = document.getElementById('custom-spell-form');
  f.style.display = f.style.display === 'none' ? '' : 'none';
  if (f.style.display !== 'none') document.getElementById('cs_name').focus();
}

function addCustomSpell() {
  const name = document.getElementById('cs_name').value.trim();
  if (!name) { document.getElementById('cs_name').focus(); return; }
  fetch(`/ttrpg/character/${CHAR_ID}/spells`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      spell_name:  name,
      spell_lib_id: null,
      spell_level:  parseInt(document.getElementById('cs_level').value) || 0,
      school:       document.getElementById('cs_school').value,
      prepared:     document.getElementById('cs_prepared').checked ? 1 : 0,
      notes:        document.getElementById('cs_notes').value.trim(),
    })
  }).then(() => reloadKeepTab());
}

function toggleSpellDesc(id) {
  const el = document.getElementById('spell-desc-' + id);
  if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
}

function toggleSpellPrepared(id, current) {
  fetch(`/ttrpg/char-spell/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({prepared: current ? 0 : 1})
  }).then(() => reloadKeepTab());
}

function toggleSpellEdit(id) {
  const p = document.getElementById('spell-edit-' + id);
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
}

function saveSpellEntry(id) {
  fetch(`/ttrpg/char-spell/${id}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      notes: document.getElementById('spell-notes-' + id).value,
    })
  }).then(r => r.json()).then(d => { if (d.ok) reloadKeepTab(); });
}

function deleteCharSpell(id) {
  if (!confirm('Remove this spell from the character?')) return;
  fetch(`/ttrpg/char-spell/${id}`, {method: 'DELETE'})
    .then(() => document.getElementById('char-spell-' + id).remove());
}

// ── Skills library search (autofill) ─────────────────────────
// ── Dice Roller ──────────────────────────────────────────────
let _diceSelected = 20;
let _advMode      = 'normal';
let _diceLastId   = 0;
let _dicePollTimer = null;
let _relayLastRollId = 0;
let _seenRolledAts = new Set();
function _rollKey(ts) { return (ts || '').slice(0, 19).replace('T', ' '); }

function toggleDicePanel() {
  const p = document.getElementById('dice-panel');
  const open = p.style.display === 'none';
  p.style.display = open ? '' : 'none';
  if (open) { selectDie(20); setAdvMode('normal'); startDicePoll(); fetchDiceFeed(); }
  else       { stopDicePoll(); }
}

function stepDiceCount(delta) {
  const el = document.getElementById('dice-count');
  el.value = Math.min(20, Math.max(1, (parseInt(el.value) || 1) + delta));
}

function selectDie(s) {
  _diceSelected = s;
  document.querySelectorAll('.dice-btn').forEach(b => {
    const active = parseInt(b.dataset.sides) === s;
    b.classList.toggle('active', active);
    if (active) {
      b.style.setProperty('background',   'var(--ttrpg-accent)', 'important');
      b.style.setProperty('border-color', 'var(--ttrpg-accent)', 'important');
      b.style.setProperty('color',        'var(--sp-on-accent)', 'important');
    } else {
      b.style.removeProperty('background');
      b.style.removeProperty('border-color');
      b.style.removeProperty('color');
    }
  });
  setAdvMode(_advMode);
}

function setAdvMode(mode) {
  _advMode = mode;
  const cfg = {
    'adv-normal': { mode: 'normal',       bg: 'var(--ttrpg-accent)', fg: 'var(--sp-on-accent)' },
    'adv-adv':    { mode: 'advantage',    bg: '#28a745',             fg: '#ffffff' },
    'adv-dis':    { mode: 'disadvantage', bg: '#dc3545',             fg: '#ffffff' },
  };
  Object.entries(cfg).forEach(([id, c]) => {
    const el = document.getElementById(id);
    if (!el) return;
    const on = _advMode === c.mode;
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

function setMod(val) {
  document.getElementById('dice-modifier').value = val;
}

// Quick reference: click a skill/weapon chip to load it into the roller (d20 + mod + label).
function diceQuickSet(modVal, label) {
  document.getElementById('dice-modifier').value = modVal;
  document.getElementById('dice-label').value    = label;
  selectDie(20);
}

// Load a spell's damage dice into the roller (count + die, e.g. 8d6).
function diceQuickSetDamage(diceStr, label) {
  const m = (diceStr || '').match(/(\d+)\s*d\s*(\d+)/i);
  if (!m) return;
  document.getElementById('dice-count').value    = parseInt(m[1], 10);
  selectDie(parseInt(m[2], 10));
  document.getElementById('dice-modifier').value = 0;
  document.getElementById('dice-label').value    = label;
}

// Load a weapon's damage dice into the roller (count + die + damage bonus,
// e.g. 2d6 +3). Falls back to a d20 attack roll when it has no damage dice.
function weaponQuickRoll(diceStr, dmgBonus, atkBonus, name) {
  const m = (diceStr || '').match(/(\d+)\s*d\s*(\d+)/i);
  if (!m) { diceQuickSet(atkBonus || 0, (name || '') + ' attack'); return; }
  document.getElementById('dice-count').value    = parseInt(m[1], 10);
  selectDie(parseInt(m[2], 10));
  document.getElementById('dice-modifier').value = dmgBonus || 0;
  document.getElementById('dice-label').value    = (name || '') + ' damage';
}

// ── Crit / fumble SFX ─────────────────────────────────────────
// Fire only on a d20. For advantage/disadvantage, judge the KEPT die.
function _critFumble(d) {
  // Roll algebra lives in the shared DiceCore module (static/scripts/dice.js).
  return window.DiceCore ? DiceCore.critFumbleFromRecord(d) : null;
}

// Voice a roll's crit/fumble at most once per client. The roller hears it
// instantly via doRoll; the dice-feed poll covers everyone else's rolls.
let _lastSfxRollId = 0;
function _maybeRollSfx(d) {
  if (!d || typeof d.roll_id !== 'number' || d.roll_id <= _lastSfxRollId) return;
  _lastSfxRollId = d.roll_id;
  const cf = _critFumble(d);
  if (cf) _sfx(cf);
}

function doRoll() {
  const count    = parseInt(document.getElementById('dice-count').value)    || 1;
  const modifier = parseInt(document.getElementById('dice-modifier').value) || 0;
  const label    = document.getElementById('dice-label').value.trim();

  fetch('/ttrpg/dice/roll', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      character_id: CHAR_ID,
      char_name:    CHAR_NAME,
      count, sides: _diceSelected,
      modifier, label, adv_mode: _advMode,
    })
  }).then(r => r.json()).then(d => {
    if (!d.ok) return;
    showLocalResult(d);
    renderFeedEntry(d, true);
    _diceLastId = Math.max(_diceLastId, d.roll_id);
    _maybeRollSfx(d);   // crit/fumble — instant for the roller
  });
}

function _dieHtml(val, sides, mode, idx, keptIdx) {
  let natCls = '';
  if (sides === 20 && val === 20) natCls = ' nat20';
  else if (sides === 20 && val === 1) natCls = ' nat1';

  if (mode === 'normal') {
    return `<span class="die-val${natCls}">${val}</span>`;
  }

  const isKept = idx === keptIdx;
  if (isKept) {
    const bg  = mode === 'advantage' ? '#0d2e0d' : '#2e1a00';
    const bdr = mode === 'advantage' ? '#28a745' : '#fd7e14';
    const col = mode === 'advantage' ? '#7deb7d' : '#ffc46e';
    return `<span class="die-val${natCls}" style="background:${bg};border-color:${bdr};color:${col};font-weight:bold;">&#10003;&thinsp;${val}</span>`;
  } else {
    return `<span class="die-val${natCls}">${val}</span>`;
  }
}

function _advLabel(mode) {
  if (mode === 'advantage')    return '<span style="color:#28a745;font-weight:600;font-size:.75rem;">&#9650; Advantage — keep highest &nbsp;</span>';
  if (mode === 'disadvantage') return '<span style="color:#fd7e14;font-weight:600;font-size:.75rem;">&#9660; Disadvantage — keep lowest &nbsp;</span>';
  return '';
}

function showLocalResult(d) {
  const sides = parseInt(d.expression.match(/d(\d+)/)[1]);
  let diceHtml = '';

  if (d.adv_mode !== 'normal') {
    const keptIdx = d.adv_mode === 'advantage'
      ? d.dice.indexOf(Math.max(...d.dice))
      : d.dice.indexOf(Math.min(...d.dice));
    diceHtml = d.dice.map((v, i) => _dieHtml(v, 20, d.adv_mode, i, keptIdx)).join(' ');
  } else {
    diceHtml = d.dice.map(v => _dieHtml(v, sides, 'normal', 0, 0)).join(' ');
  }

  const modStr    = d.modifier !== 0 ? ` ${d.modifier > 0 ? '+' : ''}${d.modifier}` : '';
  const labelHtml = d.label ? `<div style="color:var(--sp-muted);font-size:.78rem;margin-bottom:2px;">${_escH(d.label)}</div>` : '';
  const modeHtml  = _advLabel(d.adv_mode);

  document.getElementById('dice-result-inner').innerHTML =
    `${labelHtml}<div>${modeHtml}${diceHtml}` +
    `${modStr ? `<span style="color:var(--sp-muted);margin-left:4px;">${modStr}</span>` : ''}` +
    ` <span style="margin:0 3px;opacity:.6;">&#8594;</span><span class="tot">${d.total}</span></div>`;
  document.getElementById('dice-result').style.display = '';
}

function renderFeedEntry(d, prepend) {
  const sides = parseInt((d.expression.match(/d(\d+)/) || ['','20'])[1]);
  let diceHtml = '';

  if (d.adv_mode !== 'normal') {
    const keptIdx = d.adv_mode === 'advantage'
      ? d.dice.indexOf(Math.max(...d.dice))
      : d.dice.indexOf(Math.min(...d.dice));
    diceHtml = d.dice.map((v, i) => _dieHtml(v, 20, d.adv_mode, i, keptIdx)).join(' ');
  } else {
    diceHtml = d.dice.map(v => _dieHtml(v, sides, 'normal', 0, 0)).join(' ');
  }

  const modStr    = d.modifier !== 0 ? ` ${d.modifier >= 0 ? '+' : ''}${d.modifier}` : '';
  const modeTag   = d.adv_mode !== 'normal'
    ? (d.adv_mode === 'advantage'
        ? ' <span style="color:#28a745;font-size:.68rem;">&#9650;Adv</span>'
        : ' <span style="color:#fd7e14;font-size:.68rem;">&#9660;Disadv</span>')
    : '';
  const html = `<div class="feed-entry" data-rid="${d.roll_id}">
    <span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(d.char_name)}</span>
    ${d.label ? `<span style="color:var(--sp-muted);"> — ${_escH(d.label)}</span>` : ''}
    <span class="expr"> ${_escH(d.expression)}</span>${modeTag}
    <div>${diceHtml}${modStr ? `<span style="color:var(--sp-muted);">${modStr}</span>` : ''} <span style="opacity:.6;">&#8594;</span> <span class="tot">${d.total}</span></div>
  </div>`;
  const list = document.getElementById('dice-feed-list');
  const empty = list.querySelector('p.text-muted');
  if (empty) empty.remove();
  if (prepend) {
    list.insertAdjacentHTML('afterbegin', html);
  } else {
    list.insertAdjacentHTML('beforeend', html);
  }
}

function renderRelayFeedEntry(r, prepend) {
  if (r.rolled_at && _seenRolledAts.has(_rollKey(r.rolled_at))) return;
  if (r.rolled_at) _seenRolledAts.add(_rollKey(r.rolled_at));
  const html = `<div class="feed-entry" data-relay-rid="${r.id}">
    <span style="color:var(--ttrpg-accent);font-weight:600;">&#127760; ${_escH(r.player_name)}</span>
    <span class="expr"> ${_escH(r.roll_expr)}</span>
    <div><span style="opacity:.6;">&#8594;</span> <span class="tot">${r.result}</span></div>
  </div>`;
  const list = document.getElementById('dice-feed-list');
  const empty = list.querySelector('p.text-muted');
  if (empty) empty.remove();
  if (prepend) list.insertAdjacentHTML('afterbegin', html);
  else         list.insertAdjacentHTML('beforeend', html);
}

// Server returns the feed ordered by roll TIME (newest first). Render in that
// order rather than prepending by insertion id, so late-synced relay rolls land
// in their correct chronological place instead of jumping to the top.
let _diceFeedSig = '';
function _renderDiceFeed(rolls) {
  const list = document.getElementById('dice-feed-list');
  if (!list) return;
  list.innerHTML = '';
  if (!rolls.length) { list.innerHTML = '<p class="small text-muted">No rolls yet.</p>'; return; }
  rolls.forEach(d => renderFeedEntry(d, false));
}

function fetchDiceFeed() {
  fetch('/ttrpg/dice/feed')
    .then(r => r.json()).then(rolls => {
      _renderDiceFeed(rolls);
      rolls.forEach(d => {
        _diceLastId    = Math.max(_diceLastId,    d.roll_id);
        _lastSfxRollId = Math.max(_lastSfxRollId, d.roll_id);  // don't voice backlog
      });
      _diceFeedSig = rolls.length + ':' + _diceLastId;
    });
}

function pollDiceFeed() {
  fetch('/ttrpg/dice/feed')
    .then(r => r.json()).then(rolls => {
      // crit/fumble is voiced by the dice roller itself (doRoll); no feed echo.
      rolls.forEach(d => { _diceLastId = Math.max(_diceLastId, d.roll_id); });
      const sig = rolls.length + ':' + _diceLastId;
      if (sig !== _diceFeedSig) { _diceFeedSig = sig; _renderDiceFeed(rolls); }
    });
}

function startDicePoll() {
  stopDicePoll();
  _dicePollTimer = setInterval(pollDiceFeed, 3500);
}
function stopDicePoll() {
  if (_dicePollTimer) { clearInterval(_dicePollTimer); _dicePollTimer = null; }
}

function resetDice() {
  document.getElementById('dice-count').value    = 1;
  document.getElementById('dice-modifier').value = 0;
  document.getElementById('dice-label').value    = '';
  selectDie(20);
  setAdvMode('normal');
  document.getElementById('dice-result').style.display = 'none';
}

function clearDiceFeed() {
  if (!confirm('Clear your local roll feed view?')) return;
  document.getElementById('dice-feed-list').innerHTML = '<p class="small text-muted">Feed cleared.</p>';
  document.getElementById('dice-result').style.display = 'none';
}

let _skillLibSearchTimer = null;
let _skillLibResults = [];
function skillLibSearch(q) {
  clearTimeout(_skillLibSearchTimer);
  const box = document.getElementById('skill-lib-suggestions');
  if (!box) return;
  _skillLibSearchTimer = setTimeout(() => {
    fetch(`/ttrpg/reference/skills/search?q=${encodeURIComponent(q)}`)
      .then(r => r.json()).then(results => {
        if (!results.length) { box.style.display = 'none'; return; }
        _skillLibResults = results;
        box.innerHTML = results.map((s, i) => `
          <div data-idx="${i}"
               style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--sp-border);"
               onmouseenter="this.style.background='color-mix(in srgb, var(--sp-accent) 10%, transparent)'"
               onmouseleave="this.style.background=''">
            <div style="color:var(--ttrpg-accent);font-weight:600;">${s.name}
              ${s.ability_score ? `<span style="font-size:.72rem;font-weight:normal;color:var(--sp-muted);margin-left:6px;">${s.ability_score}</span>` : ''}
            </div>
          </div>`).join('');
        box.querySelectorAll('[data-idx]').forEach(el =>
          el.addEventListener('click', () => skillLibPick(_skillLibResults[parseInt(el.dataset.idx)])));
        box.style.display = 'block';
      });
  }, 150);
}

function skillLibPick(s) {
  document.getElementById('new_skill_name').value = s.name;
  document.getElementById('skill-lib-suggestions').style.display = 'none';
  addSkill();
}

document.addEventListener('click', e => {
  const box = document.getElementById('skill-lib-suggestions');
  if (box && !e.target.closest('#skill-lib-suggestions') && e.target.id !== 'new_skill_name')
    box.style.display = 'none';
});

// ── Reference tab ─────────────────────────────────────────────────────────────

// _refUrls comes from the inline page config in character_sheet.html
const _refTimers = {};

function refToggle(key) {
  const body  = document.getElementById('ref-body-' + key);
  const arrow = document.getElementById('ref-arrow-' + key);
  const open  = body.style.display !== 'none';
  body.style.display  = open ? 'none' : '';
  arrow.textContent   = open ? '▼' : '▲';
  if (!open) {
    const inp = document.getElementById('ref-q-' + key);
    inp.focus();
    if (!inp.value) refSearch(key, '');
  }
}

function refSearch(key, q) {
  clearTimeout(_refTimers[key]);
  _refTimers[key] = setTimeout(() => {
    const url = _refUrls[key] + '?q=' + encodeURIComponent(q) + '&limit=15';
    fetch(url)
      .then(r => r.json())
      .then(items => {
        const box = document.getElementById('ref-results-' + key);
        if (!items.length) { box.innerHTML = '<span class="text-muted">No results.</span>'; return; }
        box.innerHTML = items.map(it => _refCard(key, it)).join('');
      })
      .catch(() => {});
  }, 250);
}

function _escH(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function _trunc(s, n) { s = s || ''; return s.length > n ? s.slice(0, n) + '…' : s; }

function _refCard(key, it) {
  const base = 'margin-bottom:6px;padding:7px 10px;border-radius:5px;border:1px solid var(--sp-border);background:var(--sp-surface);';
  switch (key) {
    case 'spells': {
      const lvl  = it.level === 0 ? 'Cantrip' : 'Level ' + it.level;
      const conc = it.concentration ? ' ◎ Conc.' : '';
      const rit  = it.ritual ? ' ✦ Ritual' : '';
      return `<div style="${base}">
        <div><span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</span>
          <span class="text-muted ms-2" style="font-size:.75rem;">${_escH(lvl)} · ${_escH(it.school)}${conc}${rit}</span></div>
        <div class="text-muted mt-1" style="font-size:.75rem;">
          <span>⏱ ${_escH(it.casting_time)}</span> &nbsp;
          <span>↔ ${_escH(it.range_text)}</span> &nbsp;
          <span>⧗ ${_escH(it.duration)}</span>
        </div>
        ${it.description ? `<div class="mt-1" style="font-size:.75rem;color:var(--sp-text);">${_escH(_trunc(it.description, 140))}</div>` : ''}
      </div>`;
    }
    case 'weapons': {
      const dmg = it.damage_dice ? it.damage_dice + (it.damage_type ? ' ' + it.damage_type : '') : '—';
      const rng = it.weapon_range === 'Ranged' && it.range_normal ? ` · ${it.range_normal}/${it.range_long} ft` : '';
      return `<div style="${base}">
        <div><span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</span>
          <span class="text-muted ms-2" style="font-size:.75rem;">${_escH(it.weapon_category)} ${_escH(it.weapon_range)}${rng}</span></div>
        <div class="text-muted" style="font-size:.75rem;">
          <span>⚔ ${_escH(dmg)}</span>
          ${it.cost ? ` &nbsp; 💰 ${_escH(it.cost)}` : ''}
          ${it.weight ? ` &nbsp; ⚖ ${it.weight} lb` : ''}
        </div>
        ${it.properties ? `<div style="font-size:.7rem;color:var(--sp-muted);">${_escH(it.properties)}</div>` : ''}
        ${it.notes ? `<div class="mt-1" style="font-size:.75rem;color:var(--sp-text);white-space:pre-wrap;">${_escH(_trunc(it.notes, 400))}</div>` : ''}
      </div>`;
    }
    case 'armor': {
      const acStr = it.armor_class_base
        ? it.armor_class_base + (it.dex_bonus ? (it.max_dex_bonus !== null ? ` + DEX (max ${it.max_dex_bonus})` : ' + DEX') : '') + ' AC'
        : '—';
      const stlth = it.stealth_disadvantage ? ' · ⚠ Stealth disadv.' : '';
      return `<div style="${base}">
        <div><span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</span>
          <span class="text-muted ms-2" style="font-size:.75rem;">${_escH(it.armor_category)}</span></div>
        <div class="text-muted" style="font-size:.75rem;">
          <span>🛡 ${_escH(acStr)}${stlth}</span>
          ${it.str_minimum ? ` &nbsp; STR ${it.str_minimum}+` : ''}
          ${it.cost ? ` &nbsp; 💰 ${_escH(it.cost)}` : ''}
        </div>
        ${it.notes ? `<div class="mt-1" style="font-size:.75rem;color:var(--sp-text);white-space:pre-wrap;">${_escH(_trunc(it.notes, 400))}</div>` : ''}
      </div>`;
    }
    case 'equipment': {
      return `<div style="${base}">
        <div><span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</span>
          ${it.category ? `<span class="text-muted ms-2" style="font-size:.75rem;">${_escH(it.category)}${it.subcategory ? ' › ' + it.subcategory : ''}</span>` : ''}
        </div>
        <div class="text-muted" style="font-size:.75rem;">
          ${it.cost ? `💰 ${_escH(it.cost)}` : ''}
          ${it.weight ? ` &nbsp; ⚖ ${it.weight} lb` : ''}
        </div>
        ${it.description ? `<div style="font-size:.75rem;color:var(--sp-text);">${_escH(_trunc(it.description, 120))}</div>` : ''}
      </div>`;
    }
    case 'feats': {
      return `<div style="${base}">
        <div style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</div>
        ${it.prerequisites ? `<div class="text-muted fst-italic" style="font-size:.75rem;">Req: ${_escH(it.prerequisites)}</div>` : ''}
        ${it.description ? `<div style="font-size:.75rem;color:var(--sp-text);">${_escH(_trunc(it.description, 160))}</div>` : ''}
      </div>`;
    }
    case 'skills': {
      return `<div style="${base}">
        <div><span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</span>
          ${it.ability_score ? `<span class="text-muted ms-2" style="font-size:.75rem;">(${_escH(it.ability_score)})</span>` : ''}
        </div>
        ${it.description ? `<div style="font-size:.75rem;color:var(--sp-text);">${_escH(_trunc(it.description, 140))}</div>` : ''}
      </div>`;
    }
    case 'races': {
      const traits = (it.traits_text || '').split('\n').filter(Boolean).slice(0, 4);
      return `<div style="${base}">
        <div><span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</span>
          ${it.size ? `<span class="text-muted ms-2" style="font-size:.75rem;">${_escH(it.size)} · ${it.speed}</span>` : ''}
        </div>
        ${it.ability_bonuses ? `<div style="font-size:.75rem;color:var(--ttrpg-accent);">${_escH(it.ability_bonuses)}</div>` : ''}
        ${traits.length ? `<div style="font-size:.7rem;color:var(--sp-muted);">${traits.map(t => _escH(t)).join(' · ')}</div>` : ''}
      </div>`;
    }
    case 'classes': {
      const spellBadge = it.spellcasting_ability
        ? `<span style="font-size:.68rem;padding:1px 5px;border-radius:6px;background:color-mix(in srgb,#7c5cbf 15%,transparent);border:1px solid #7c5cbf;color:#4b2b8c;">${_escH(it.spellcasting_ability)}</span>`
        : '';
      const subs = (it.subclasses || '').split(',').filter(Boolean).slice(0, 4);
      return `<div style="${base}">
        <div class="d-flex align-items-center gap-2">
          <span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</span>
          <span style="font-size:.75rem;padding:1px 6px;border-radius:8px;border:1px solid var(--sp-border);color:var(--ttrpg-accent);">d${it.hit_die}</span>
          ${spellBadge}
        </div>
        ${it.saving_throws ? `<div class="text-muted" style="font-size:.75rem;">Saves: ${_escH(it.saving_throws)}</div>` : ''}
        ${it.skill_choices ? `<div style="font-size:.73rem;color:var(--sp-text);">${_escH(_trunc(it.skill_choices, 100))}</div>` : ''}
        ${subs.length ? `<div style="font-size:.7rem;color:var(--sp-muted);">${subs.map(s => _escH(s.trim())).join(' · ')}</div>` : ''}
      </div>`;
    }
    default: {
      // Generic name/sub/desc card — conditions, magic items, class features,
      // subclasses, traits, weapon properties, rules (the /lookup/<cat> shape).
      if (!it.name) return '';
      return `<div style="${base}">
        <div><span style="color:var(--ttrpg-accent);font-weight:600;">${_escH(it.name)}</span>
          ${it.sub ? `<span class="text-muted ms-2" style="font-size:.75rem;">${_escH(it.sub)}</span>` : ''}</div>
        ${it.desc ? `<div class="mt-1" style="font-size:.75rem;color:var(--sp-text);white-space:pre-wrap;">${_escH(_trunc(it.desc, 600))}</div>` : ''}
      </div>`;
    }
  }
}

// ── Suggest resources from the synced class level tables ─────────────────────

function suggestResources() {
  const msg = document.getElementById('suggest-res-msg');
  if (msg) msg.textContent = '…';
  fetch(`/ttrpg/character/${CHAR_ID}/suggest-resources`, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.ok && d.added && d.added.length) {
        location.reload();               // new resource rows need server render
      } else if (msg) {
        msg.textContent = d.message || d.error || 'Nothing added.';
      }
    })
    .catch(() => { if (msg) msg.textContent = 'Request failed.'; });
}

// ── LLM prompt / portrait paste (formerly the second inline script) ──────────
// ── LLM Prompt ────────────────────────────────────────────────────────────────


let _llmCompressedDataUrl = null;

function _sgn(n) { return (n >= 0 ? '+' : '') + n; }
function _modStr(score) { return _sgn(Math.floor((score - 10) / 2)); }

function _buildPrompt(c) {
  const lines = [];

  // Opening request
  lines.push('Please generate a close-up portrait of the following fantasy TTRPG character.\n');

  // Core identity — the most visually relevant facts first. Genre skins
  // (archetype/species) replace the 5e labels when the character has a genre.
  const inGenre = !!c.archetype;
  const dispRace  = inGenre ? (c.species || c.race) : c.race;
  const dispClass = inGenre ? c.archetype : c.char_class;
  const identity = [];
  if (c.race)       identity.push(dispRace);
  if (c.char_class) identity.push((!inGenre && c.subclass ? c.subclass + ' ' : '') + dispClass + ' (Level ' + c.level + ')');
  if (c.background) identity.push(c.background + ' background');
  lines.push('CHARACTER: ' + c.name + (identity.length ? ', a ' + identity.join(', ') : '') + '.');
  if (inGenre && c.genre_label) lines.push('SETTING: ' + c.genre_label + ' — not medieval fantasy.');
  lines.push('');

  // Personality note (from the randomizer or hand-written) — pull it out of
  // the notes so it shapes expression and mood explicitly
  const personalityNotes = c.notes.filter(n => /^\s*Personality\s*:/i.test(n));
  if (personalityNotes.length) {
    lines.push('PERSONALITY (let this shape expression, bearing, and mood):');
    personalityNotes.forEach(n =>
      n.split('\n').forEach(l => { if (l.trim()) lines.push('- ' + l.trim()); }));
    lines.push('');
  }

  // Stat-driven appearance hints — randomized wording from shared pools
  const presence = portraitPresenceLines({
    str: c.str_val, dex: c.dex_val, con: c.con_val,
    int: c.int_val, wis: c.wis_val, cha: c.cha_val,
  });
  if (presence.length) {
    lines.push('PHYSICAL PRESENCE:');
    presence.forEach(l => lines.push(l));
    lines.push('');
  }

  // Equipped armor — what they are wearing
  const wornArmor = c.armor.filter(a => a.equipped);
  if (wornArmor.length) {
    lines.push('WEARING:');
    wornArmor.forEach(a => {
      let desc = '- ' + a.name;
      if (a.notes) desc += ' (' + a.notes + ')';
      lines.push(desc);
    });
    lines.push('');
  }

  // Equipped weapons — what they are holding / at their side
  const readyWeapons = c.weapons.filter(w => w.equipped);
  if (readyWeapons.length) {
    lines.push('CARRYING / WIELDING:');
    readyWeapons.forEach(w => {
      let desc = '- ' + w.name;
      if (w.damage.trim()) desc += ' (' + w.damage.trim() + ')';
      if (w.properties) desc += ' — ' + w.properties;
      if (w.notes) desc += ' [' + w.notes + ']';
      lines.push(desc);
    });
    lines.push('');
  }

  // Feats that hint at fighting style or appearance
  if (c.feats.length) {
    lines.push('NOTABLE ABILITIES (may influence pose/style):');
    c.feats.forEach(f => lines.push('- ' + f.name));
    lines.push('');
  }

  // Spells — hint at magical nature
  const preparedSpells = c.spells.filter(s => s.prepared);
  if (preparedSpells.length) {
    lines.push('MAGIC (suggest arcane/divine visual elements):');
    preparedSpells.slice(0, 5).forEach(s => {
      const lbl = s.level === 0 ? 'Cantrip' : 'Level ' + s.level;
      lines.push('- ' + s.name + ' (' + lbl + (s.school ? ', ' + s.school : '') + ')');
    });
    lines.push('');
  }

  // Character notes — may contain appearance descriptions
  if (c.notes.length) {
    lines.push('CHARACTER NOTES (may contain appearance details):');
    c.notes.forEach(n => lines.push(n));
    lines.push('');
  }

  // Style guidance — shared composition block (portrait orientation, centered
  // face) with the genre pack's art direction when the character has one
  portraitStyleLines(!!c.portrait_url, c.genre_art).forEach(l => lines.push(l));
  lines.push('');

  lines.push('Generate a vivid, detailed close-up portrait that captures the face, personality, and power of ' + c.name + '.');

  return lines.join('\n');
}

async function _compressPortrait(imgEl, maxBytes) {
  return new Promise(resolve => {
    const canvas = document.createElement('canvas');
    let w = imgEl.naturalWidth || imgEl.width;
    let h = imgEl.naturalHeight || imgEl.height;
    const MAX_DIM = 1024;
    if (w > MAX_DIM || h > MAX_DIM) {
      const s = Math.min(MAX_DIM / w, MAX_DIM / h);
      w = Math.round(w * s);
      h = Math.round(h * s);
    }
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').drawImage(imgEl, 0, 0, w, h);

    let lo = 0.1, hi = 0.92, best = '';
    for (let i = 0; i < 10; i++) {
      const q = (lo + hi) / 2;
      const url = canvas.toDataURL('image/jpeg', q);
      const bytes = Math.round((url.length - 'data:image/jpeg;base64,'.length) * 3 / 4);
      if (bytes <= maxBytes) { best = url; lo = q; }
      else                   { hi = q; }
    }
    resolve(best || canvas.toDataURL('image/jpeg', 0.1));
  });
}

async function openLlmPrompt() {
  document.getElementById('llm-prompt-text').value = _buildPrompt(_llmChar);

  const imgEl = document.getElementById('llm-img-preview');
  if (imgEl && _llmChar.portrait_url) {
    if (!_llmCompressedDataUrl) {
      const sizeEl = document.getElementById('llm-img-size');
      if (sizeEl) sizeEl.textContent = '(compressing…)';
      _llmCompressedDataUrl = await _compressPortrait(imgEl, 900 * 1024);
      if (sizeEl) {
        const kb = Math.round((_llmCompressedDataUrl.length - 'data:image/jpeg;base64,'.length) * 3 / 4 / 1024);
        sizeEl.textContent = kb + ' KB';
      }
    }
    imgEl.src = _llmCompressedDataUrl;
  }

  new bootstrap.Modal(document.getElementById('llmPromptModal')).show();
}

function copyLlmPrompt() {
  const ta = document.getElementById('llm-prompt-text');
  const fb = document.getElementById('llm-copy-feedback');
  function showFb() { fb.style.display = ''; setTimeout(() => { fb.style.display = 'none'; }, 2000); }
  if (navigator.clipboard) {
    navigator.clipboard.writeText(ta.value).then(showFb).catch(() => _fallbackCopy(ta, showFb));
  } else {
    _fallbackCopy(ta, showFb);
  }
}

function _fallbackCopy(ta, onDone) {
  ta.removeAttribute('readonly');
  ta.select();
  ta.setSelectionRange(0, 99999);
  try { document.execCommand('copy'); onDone(); } catch(e) {}
  ta.setAttribute('readonly', '');
  window.getSelection().removeAllRanges();
}

function downloadLlmImage() {
  if (!_llmCompressedDataUrl) return;
  const a = document.createElement('a');
  a.href = _llmCompressedDataUrl;
  a.download = (_llmChar.name.replace(/\s+/g, '_') || 'character') + '_portrait.jpg';
  a.click();
}

// ── Portrait paste ────────────────────────────────────────────────────────────
// _pasteUploadUrl comes from the inline page config (null when not editable)

function _uploadPortraitBlob(blob) {
  const btn = document.getElementById('paste-portrait-btn');
  if (btn) btn.textContent = 'Uploading…';
  const fd = new FormData();
  fd.append('portrait', blob, 'pasted.png');
  fetch(_pasteUploadUrl, { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        const img = document.getElementById('portrait-img');
        if (img && img.tagName === 'IMG') {
          img.src = data.url + '?t=' + Date.now();
        } else {
          location.reload();
        }
        _llmCompressedDataUrl = null;
      }
      if (btn) { btn.innerHTML = '&#128203; Paste Portrait'; btn.disabled = false; }
    })
    .catch(() => {
      if (btn) { btn.innerHTML = '&#128203; Paste Portrait'; btn.disabled = false; }
    });
}

async function activatePastePortrait() {
  const btn = document.getElementById('paste-portrait-btn');
  btn.disabled = true;
  btn.textContent = 'Reading clipboard…';

  // Modern clipboard API — works on mobile with a single tap
  if (navigator.clipboard && navigator.clipboard.read) {
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const imageType = item.types.find(t => t.startsWith('image/'));
        if (imageType) {
          const blob = await item.getType(imageType);
          _uploadPortraitBlob(blob);
          return;
        }
      }
      // Clipboard had no image
      btn.textContent = 'No image in clipboard';
      setTimeout(() => { btn.innerHTML = '&#128203; Paste Portrait'; btn.disabled = false; }, 2000);
      return;
    } catch(err) {
      // Permission denied or API unavailable — fall through to keyboard hint
    }
  }

  // Fallback: listen for a Ctrl+V / long-press paste event
  btn.textContent = 'Now paste (Ctrl+V)…';
  btn.disabled = false;
  btn.style.borderColor = 'var(--ttrpg-accent)';
  btn.style.color = 'var(--ttrpg-accent)';
  const reset = () => { btn.innerHTML = '&#128203; Paste Portrait'; btn.style.borderColor = ''; btn.style.color = ''; };
  const tid = setTimeout(reset, 15000);
  document.addEventListener('paste', function handler(e) {
    clearTimeout(tid);
    document.removeEventListener('paste', handler);
    reset();
    const item = Array.from(e.clipboardData.items).find(i => i.type.startsWith('image/'));
    if (item) { e.preventDefault(); _uploadPortraitBlob(item.getAsFile()); }
  }, { once: true });
}

// ── Arriving from the battle map (?dice=1): open the dice roller ─────────────
// Mid-game sheet visits want the roller immediately — the map's token
// double-click adds the flag so nobody has to find the 🎲 button first.
(function () {
  if (new URLSearchParams(location.search).get('dice') !== '1') return;
  const p = document.getElementById('dice-panel');
  if (!p || p.style.display !== 'none') return;
  toggleDicePanel();
  p.scrollIntoView({ behavior: 'smooth', block: 'center' });
})();

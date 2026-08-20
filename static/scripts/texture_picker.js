/* texture_picker.js — the 3D texture library modal (DM pages only).
 *
 * One overlay, three tabs:
 *   Library     — tiled previews grouped by category; click picks (when opened
 *                 with a pick callback), ✕ deletes user textures.
 *   Upload      — name/category/scale + file (or clipboard via pasteImageNear).
 *   AI Generate — builds a seamless-tileable texture prompt for the copy-paste
 *                 AI workflow, then saves the pasted result into the library.
 *
 * Server API: routes/textures.py. No framework — plain DOM, ttrpg CSS vars.
 * Usage: TexturePicker.open() to manage, TexturePicker.open({pick: fn}) to
 * choose a texture (fn gets the slug).
 */
window.TexturePicker = (function () {
  'use strict';

  const CATEGORIES = ['stone', 'brick', 'wood', 'floor', 'plaster', 'metal',
                      'ground', 'other'];
  let root = null, manifest = null, pickCb = null;

  function fetchManifest() {
    return fetch('/ttrpg/textures/manifest')
      .then(r => r.json())
      .then(d => (manifest = d.textures || []))
      .catch(() => (manifest = []));
  }

  // ── DOM scaffolding ─────────────────────────────────────────────────────────

  function build() {
    if (root) return root;
    root = document.createElement('div');
    root.id = 'texpick-overlay';
    root.style.cssText =
      'position:fixed;inset:0;z-index:2500;display:none;' +
      'background:rgba(0,0,0,.55);overflow-y:auto;padding:4vh 12px;';
    root.innerHTML = `
      <div style="max-width:760px;margin:0 auto;background:var(--ttrpg-primary,#1a1c22);
                  border:1px solid var(--ttrpg-accent,#c9a84c);border-radius:10px;
                  color:var(--ttrpg-text,#e8e6e3);">
        <div class="d-flex align-items-center gap-2 p-3"
             style="border-bottom:1px solid var(--sp-border,#444);">
          <strong style="color:var(--ttrpg-accent,#c9a84c);">&#129521; Texture Library</strong>
          <span id="texpick-mode-hint" class="small text-muted"></span>
          <button class="btn-close btn-close-white ms-auto" id="texpick-close"></button>
        </div>
        <div class="d-flex gap-1 px-3 pt-2">
          <button class="btn btn-sm btn-ttrpg" data-tab="lib">Library</button>
          <button class="btn btn-sm btn-outline-secondary" data-tab="up">Upload</button>
          <button class="btn btn-sm btn-outline-secondary" data-tab="ai">&#10024; AI Generate</button>
        </div>
        <div class="p-3">
          <div id="texpick-tab-lib"></div>
          <div id="texpick-tab-up" style="display:none;">
            <div class="row g-2 mb-2">
              <div class="col-5"><input id="texup-name" class="form-control form-control-sm"
                   placeholder="name (a-z 0-9 _ -)"></div>
              <div class="col-4"><select id="texup-cat" class="form-select form-select-sm"></select></div>
              <div class="col-3"><div class="input-group input-group-sm">
                <input id="texup-tile" type="number" class="form-control" value="5" min="1" max="50"
                       title="How many feet one tile of this texture covers in the world">
                <span class="input-group-text">ft</span></div></div>
            </div>
            <div class="d-flex gap-2 align-items-center mb-2">
              <input type="file" id="texup-file" accept="image/*" class="form-control form-control-sm">
              <button class="btn btn-sm btn-outline-secondary text-nowrap"
                      onclick="pasteImageNear(this)" title="Paste an image from the clipboard">
                &#128203; Paste</button>
            </div>
            <button class="btn btn-sm btn-ttrpg" id="texup-save">Add to library</button>
            <span id="texup-status" class="small ms-2"></span>
          </div>
          <div id="texpick-tab-ai" style="display:none;">
            <div class="small text-muted mb-2">
              Describe the surface, copy the prompt into an image AI
              (ChatGPT, Midjourney&hellip;), then copy the generated image and
              paste it back here — it lands in the library, ready to use on
              walls, doors, and floors.
            </div>
            <div class="row g-2 mb-2">
              <div class="col-12"><input id="texai-desc" class="form-control form-control-sm"
                   placeholder="e.g. mossy dungeon stone with hairline cracks"></div>
              <div class="col-5"><input id="texai-name" class="form-control form-control-sm"
                   placeholder="name (a-z 0-9 _ -)"></div>
              <div class="col-4"><select id="texai-cat" class="form-select form-select-sm"></select></div>
              <div class="col-3"><div class="input-group input-group-sm">
                <input id="texai-tile" type="number" class="form-control" value="5" min="1" max="50"
                       title="How many feet one tile covers in the world — also steers the prompt's scale hints">
                <span class="input-group-text">ft</span></div></div>
            </div>
            <div class="d-flex gap-2 mb-2">
              <button class="btn btn-sm btn-ttrpg" id="texai-copy">&#128203; Copy Prompt</button>
              <button class="btn btn-sm btn-outline-secondary" id="texai-paste"
                      title="Copy the AI's finished image, then click here">
                &#128444; Paste result &rarr; save</button>
              <span id="texai-status" class="small align-self-center"></span>
            </div>
            <textarea id="texai-prompt" class="form-control" readonly
                      style="font-family:monospace;font-size:.75rem;min-height:170px;
                             background:var(--ttrpg-surface,#232630);color:inherit;"></textarea>
          </div>
        </div>
      </div>`;
    document.body.appendChild(root);

    root.querySelector('#texpick-close').addEventListener('click', close);
    root.addEventListener('click', e => { if (e.target === root) close(); });
    root.querySelectorAll('[data-tab]').forEach(btn => {
      btn.addEventListener('click', () => showTab(btn.dataset.tab));
    });
    ['texup-cat', 'texai-cat'].forEach(id => {
      const sel = root.querySelector('#' + id);
      CATEGORIES.forEach(c => {
        const o = document.createElement('option');
        o.value = c; o.textContent = c;
        sel.appendChild(o);
      });
    });
    root.querySelector('#texup-save').addEventListener('click', saveUpload);
    root.querySelector('#texai-copy').addEventListener('click', copyAiPrompt);
    root.querySelector('#texai-paste').addEventListener('click', pasteAiResult);
    return root;
  }

  function showTab(which) {
    ['lib', 'up', 'ai'].forEach(t => {
      root.querySelector('#texpick-tab-' + t).style.display =
        t === which ? '' : 'none';
    });
    root.querySelectorAll('[data-tab]').forEach(btn => {
      const on = btn.dataset.tab === which;
      btn.classList.toggle('btn-ttrpg', on);
      btn.classList.toggle('btn-outline-secondary', !on);
    });
  }

  // ── Library grid ────────────────────────────────────────────────────────────

  function renderLibrary() {
    const box = root.querySelector('#texpick-tab-lib');
    box.innerHTML = '';
    if (!manifest || !manifest.length) {
      box.innerHTML = '<div class="text-muted small">No textures yet.</div>';
      return;
    }
    const byCat = {};
    manifest.forEach(t => (byCat[t.category] = byCat[t.category] || []).push(t));
    Object.keys(byCat).sort().forEach(cat => {
      const h = document.createElement('div');
      h.className = 'small text-muted mt-2 mb-1';
      h.style.cssText = 'letter-spacing:.06em;text-transform:uppercase;';
      h.textContent = cat;
      box.appendChild(h);
      const grid = document.createElement('div');
      grid.style.cssText =
        'display:grid;grid-template-columns:repeat(auto-fill,minmax(108px,1fr));gap:8px;';
      byCat[cat].forEach(t => grid.appendChild(tile(t)));
      box.appendChild(grid);
    });
  }

  function tile(t) {
    const el = document.createElement('div');
    el.style.cssText =
      'position:relative;border:1px solid var(--sp-border,#444);border-radius:6px;' +
      'overflow:hidden;' + (pickCb ? 'cursor:pointer;' : '');
    // 50% background-size = the texture tiled 2×2, so seams show immediately
    el.innerHTML = `
      <div style="padding-top:75%;background-image:url('${t.url}');
                  background-size:50% 50%;"></div>
      <div class="small px-1 py-1 d-flex align-items-center" style="gap:4px;">
        <span class="text-truncate" title="${t.name} — tiles every ${t.tile_ft} ft">${t.name}</span>
        <span class="text-muted ms-auto" style="font-size:.65rem;">${t.tile_ft}ft</span>
      </div>`;
    if (pickCb) {
      el.addEventListener('click', () => { const cb = pickCb; close(); cb(t.name); });
      el.title = 'Use "' + t.name + '"';
    }
    if (t.source !== 'builtin') {
      const del = document.createElement('button');
      del.textContent = '✕';
      del.title = 'Delete from library';
      del.style.cssText =
        'position:absolute;top:2px;right:2px;border:none;border-radius:4px;' +
        'background:rgba(0,0,0,.6);color:#e88;font-size:.7rem;line-height:1;' +
        'padding:3px 5px;cursor:pointer;';
      del.addEventListener('click', e => {
        e.stopPropagation();
        if (!confirm(`Delete texture "${t.name}"? Floorplans that reference it fall back to art-sampled surfaces.`)) return;
        fetch(`/ttrpg/textures/${t.name}/delete`, { method: 'POST' })
          .then(r => r.json())
          .then(d => { if (d.ok) refresh(); else alert(d.error || 'Delete failed'); })
          .catch(() => alert('Delete failed (network)'));
      });
      el.appendChild(del);
    }
    return el;
  }

  function refresh() {
    return fetchManifest().then(renderLibrary);
  }

  // ── Upload tab ──────────────────────────────────────────────────────────────

  function saveUpload() {
    const file = root.querySelector('#texup-file').files[0];
    const status = root.querySelector('#texup-status');
    if (!file) { status.textContent = 'Choose or paste an image first.'; return; }
    const fd = new FormData();
    fd.append('image', file);
    fd.append('name', root.querySelector('#texup-name').value);
    fd.append('category', root.querySelector('#texup-cat').value);
    fd.append('tile_ft', root.querySelector('#texup-tile').value);
    status.textContent = 'Saving…';
    fetch('/ttrpg/textures/upload', { method: 'POST', body: fd })
      .then(r => r.json())
      .then(d => {
        if (!d.ok) { status.textContent = d.error || 'Rejected'; return; }
        status.textContent = '✓ Added "' + d.name + '"';
        root.querySelector('#texup-name').value = '';
        root.querySelector('#texup-file').value = '';
        refresh().then(() => showTab('lib'));
      })
      .catch(() => { status.textContent = 'Save failed (network)'; });
  }

  // ── AI Generate tab ─────────────────────────────────────────────────────────

  function aiPromptText() {
    const desc = root.querySelector('#texai-desc').value.trim() ||
                 'weathered gray dungeon stone';
    const tile = parseInt(root.querySelector('#texai-tile').value, 10) || 5;
    return [
      'Please generate a SEAMLESSLY TILEABLE material texture image.',
      '',
      '## SUBJECT',
      desc + ' — a flat material surface, viewed perfectly straight-on.',
      '',
      '## TECHNICAL REQUIREMENTS (CRITICAL)',
      '- SEAMLESS TILING: every edge must wrap perfectly to the opposite edge — no visible seam when the image repeats side by side.',
      '- Perfectly flat, even, diffuse lighting: NO shadows, NO vignette, NO hotspots from a light source, NO depth of field.',
      '- Straight-on orthographic view: no perspective, no horizon, no camera angle.',
      `- Uniform scale: the image covers about ${tile} feet × ${tile} feet of the surface, so size features accordingly (a brick is ~8 inches, a floorboard ~6 inches wide).`,
      '- No text, letters, watermarks, borders, frames, or objects — surface material only.',
      '- Square image, 1024×1024 pixels.',
      '',
      'This image will be used as a repeating material texture on 3D walls and floors in a game engine.',
    ].join('\n');
  }

  function copyAiPrompt() {
    const txt = aiPromptText();
    root.querySelector('#texai-prompt').value = txt;
    const status = root.querySelector('#texai-status');
    (navigator.clipboard && navigator.clipboard.writeText
      ? navigator.clipboard.writeText(txt)
      : Promise.reject())
      .then(() => { status.textContent = '✓ Prompt copied'; })
      .catch(() => { status.textContent = 'Copy the text below manually.'; });
  }

  function pasteAiResult() {
    const status = root.querySelector('#texai-status');
    const meta = () => {
      const fd = new FormData();
      fd.append('name', root.querySelector('#texai-name').value);
      fd.append('category', root.querySelector('#texai-cat').value);
      fd.append('tile_ft', root.querySelector('#texai-tile').value);
      fd.append('source', 'ai');
      return fd;
    };
    const send = blob => {
      const fd = meta();
      fd.append('ext', ((blob.type || 'image/png').split('/')[1] || 'png').replace('jpeg', 'jpg'));
      fd.append('image', blob, 'pasted');
      status.textContent = 'Saving…';
      fetch('/ttrpg/textures/paste', { method: 'POST', body: fd })
        .then(r => r.json())
        .then(d => {
          if (!d.ok) { status.textContent = d.error || 'Rejected'; return; }
          status.textContent = '✓ Added "' + d.name + '"';
          refresh().then(() => showTab('lib'));
        })
        .catch(() => { status.textContent = 'Save failed (network)'; });
    };
    if (!root.querySelector('#texai-name').value.trim()) {
      status.textContent = 'Give it a name first.';
      return;
    }
    if (navigator.clipboard && navigator.clipboard.read) {
      navigator.clipboard.read().then(items => {
        for (const item of items) {
          const t = item.types.find(x => x.startsWith('image/'));
          if (t) { item.getType(t).then(send); return; }
        }
        status.textContent = 'No image in the clipboard.';
      }).catch(() => { status.textContent = 'Clipboard blocked — press Ctrl+V here.'; armCtrlV(send, status); });
    } else {
      status.textContent = 'Press Ctrl+V…';
      armCtrlV(send, status);
    }
  }

  function armCtrlV(send, status) {
    document.addEventListener('paste', function handler(e) {
      const item = Array.from(e.clipboardData.items)
        .find(i => i.type.startsWith('image/'));
      if (item) { e.preventDefault(); send(item.getAsFile()); }
      else status.textContent = 'No image in the clipboard.';
    }, { once: true });
  }

  // ── public ──────────────────────────────────────────────────────────────────

  function open(opts) {
    pickCb = (opts && opts.pick) || null;
    build();
    root.querySelector('#texpick-mode-hint').textContent =
      pickCb ? '— click a texture to use it' : '';
    root.style.display = 'block';
    showTab('lib');
    refresh();
  }

  function close() {
    if (root) root.style.display = 'none';
    pickCb = null;
  }

  return { open: open, close: close };
})();

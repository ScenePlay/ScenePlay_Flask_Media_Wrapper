// Shared "Choose existing" picker: reuse a picture or video already on this
// box instead of uploading a copy. One Bootstrap modal, a grid of thumbnails
// with the owning record's name, a filter box. The caller receives the item
// and decides what to store — for filename columns use spAssetRef() to turn
// it into a shared reference (see shared_assets.py); for URL columns use
// item.url directly. Feed: /utilities/assets/api/list (assets_inventory).
(function () {
  let cache = null;

  function load() {
    if (cache) return Promise.resolve(cache);
    return fetch('/utilities/assets/api/list').then(r => r.json())
      .then(d => { cache = (d && d.items) || []; return cache; });
  }

  function modal() {
    let m = document.getElementById('spAssetPicker');
    if (m) return m;
    m = document.createElement('div');
    m.id = 'spAssetPicker'; m.className = 'modal fade'; m.tabIndex = -1;
    m.innerHTML =
      '<div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content">' +
      '<div class="modal-header"><h5 class="modal-title">Choose an existing file</h5>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>' +
      '<div class="modal-body">' +
      '<div class="d-flex gap-2 align-items-center mb-2 flex-wrap">' +
      '<input type="search" class="form-control form-control-sm sp-ap-filter" placeholder="Filter by name, folder or file…" style="max-width:320px;">' +
      '<select class="form-select form-select-sm sp-ap-folder" style="max-width:220px;"></select>' +
      '<span class="small text-muted sp-ap-count"></span></div>' +
      '<div class="sp-ap-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;"></div>' +
      '</div>' +
      '<div class="modal-footer"><span class="small text-muted me-auto">Nothing is copied — the record points at the existing file.</span>' +
      '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button></div>' +
      '</div></div>';
    document.body.appendChild(m);
    return m;
  }

  function card(it) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'sp-ap-card btn p-1 text-start';
    el.style.cssText = 'border:1px solid var(--sp-border,#ccc);border-radius:6px;background:var(--sp-surface,#fff);';
    const thumb = it.type === 'video'
      ? (it.thumb ? `<img src="${it.thumb}" alt="" loading="lazy" style="width:100%;height:96px;object-fit:cover;border-radius:4px;background:#222;">`
                  : `<video src="${it.url}" muted preload="metadata" style="width:100%;height:96px;object-fit:cover;border-radius:4px;background:#222;"></video>`)
      : `<img src="${it.url}" alt="" loading="lazy" style="width:100%;height:96px;object-fit:cover;border-radius:4px;background:#222;">`;
    el.innerHTML = thumb +
      `<div class="small fw-semibold text-truncate mt-1" title="${esc(it.name)}">${esc(it.name)}</div>` +
      `<div class="text-muted text-truncate" style="font-size:.7rem;" title="${esc(it.file)}">${esc(it.sub)}${it.type === 'video' ? ' · video' : ''} · ${esc(it.size_h || '')}</div>`;
    return el;
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  // opts: {kinds: ['image','video'], onPick(item), title}
  window.spPickAsset = function (opts) {
    opts = opts || {};
    const kinds = opts.kinds || ['image'];
    const m = modal();
    m.querySelector('.modal-title').textContent = opts.title ||
      (kinds.length === 1 ? (kinds[0] === 'video' ? 'Choose an existing video' : 'Choose an existing picture')
                          : 'Choose an existing picture or video');
    const grid = m.querySelector('.sp-ap-grid'), filt = m.querySelector('.sp-ap-filter'),
          fsel = m.querySelector('.sp-ap-folder'), count = m.querySelector('.sp-ap-count');
    filt.value = '';
    const inst = bootstrap.Modal.getOrCreateInstance(m);
    grid.innerHTML = '<div class="text-muted small">Loading…</div>';
    inst.show();
    load().then(all => {
      const items = all.filter(it => kinds.includes(it.type));
      const subs = [...new Set(items.map(it => it.sub.split(' · ')[0]))];
      fsel.innerHTML = '<option value="">All folders</option>' + subs.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
      const render = () => {
        const q = filt.value.trim().toLowerCase(), f = fsel.value;
        grid.innerHTML = '';
        let n = 0;
        items.forEach(it => {
          if (f && !it.sub.startsWith(f)) return;
          if (q && !(it.name + ' ' + it.file + ' ' + it.sub).toLowerCase().includes(q)) return;
          const c = card(it);
          c.onclick = () => { inst.hide(); if (opts.onPick) opts.onPick(it); };
          grid.appendChild(c); n++;
        });
        count.textContent = n + ' of ' + items.length;
        if (!n) grid.innerHTML = '<div class="text-muted small">Nothing matches.</div>';
      };
      filt.oninput = render; fsel.onchange = render; render();
    }).catch(() => { grid.innerHTML = '<div class="text-danger small">Could not load the asset list.</div>'; });
  };

  // The value to store in a filename column whose files live in
  // static/uploads/<targetFolder>/ — mirrors shared_assets.picture_ref/video_ref.
  window.spAssetRef = function (item, targetFolder) {
    if (item.source === 'library') return '../../../assets/media/video/' + item.id + '.' + item.ext;
    return item.folder === targetFolder ? item.file : '../' + item.folder + '/' + item.file;
  };

  // Show what was chosen next to a control: sets a preview <img>/<video>
  // and a caption. previewEl may be an <img>, <video>, or a container.
  window.spAssetPreview = function (container, item) {
    if (!container) return;
    container.style.display = '';
    container.innerHTML = (item.type === 'video'
      ? `<video src="${item.url}" muted loop autoplay playsinline style="height:48px;border-radius:4px;"></video>`
      : `<img src="${item.url}" alt="" style="height:48px;border-radius:4px;">`) +
      `<span class="small text-muted ms-1">reusing: ${esc(item.name)}</span>`;
  };
})();

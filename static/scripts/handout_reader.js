/* Page-turning PDF reader for Utilities → Handouts (templates/handout_read.html).
 *
 * pdf.js renders pages to canvases on demand; StPageFlip (page-flip.browser.js,
 * MIT — the global `St`) does the book: soft pages that bend along the fold as
 * they turn, corner-drag, two-page spread on wide screens and a single page in
 * portrait. The book is one <div> per PDF page, all created empty up front so
 * the library knows the page count; a page's canvas is rendered only when it
 * comes within a few pages of the one being read, and re-rendered when the
 * book is re-laid-out at a very different size. Progress (page + count) is
 * posted back, debounced.
 *
 * The spread/single toggle (S) rebuilds the whole book: page-flip can't change
 * orientation rules after construction, so single-page mode is a fresh
 * instance whose minWidth is wider than any screen — that pins its stretch
 * layout to one portrait page at every window size. The preference is
 * per-browser (localStorage), not per-handout.
 *
 * Zoom (+/− buttons, ctrl+wheel, pinch) is a CSS transform on the wrapper —
 * live scaling stays cheap — and once it settles, the visible pages are
 * re-rendered at the zoomed resolution so text is sharp, not upscaled.
 * While zoomed, dragging (mouse or one finger) pans instead of folding the
 * page corner: capture-phase listeners on the stage stop the events before
 * page-flip's own mouse/touch handlers see them. Page turns still work from
 * the buttons, keys, and the page box. */
export class HandoutReader {
  constructor(pdfjsLib, opts) {
    this.pdfjs = pdfjsLib;
    this.opts = opts;
    this.pdf = null;
    this.numPages = 0;
    this.startPage = Math.max(1, parseInt(opts.startPage, 10) || 1);
    this.page = this.startPage;
    this.baseSize = null;              // page 1 in PDF points
    this.rendered = new Map();         // pageNum -> css width the canvas was rendered for
    this.pending = new Set();
    this.flip = null;
    this.single = false;               // force one page even on wide screens
    try { this.single = localStorage.getItem('sp_handout_single') === '1'; } catch (e) { /* private mode */ }
    this.zoom = 1;                     // 1 = fitted; pan offsets in stage px
    this.tx = 0;
    this.ty = 0;
    this.maxZoom = 4;
    this.$ = (id) => document.getElementById(id);
    this.stage = this.$('stage');
    this.book = this.$('book');
    this.wrap = this.$('bookWrap');   // we size this; page-flip owns #book (sets it to 100%)
    this._bind();
    this._open();
  }

  /* ---------- open + build the book ---------- */
  async _open() {
    try {
      this.pdf = await this.pdfjs.getDocument({ url: this.opts.url }).promise;
    } catch (e) {
      this.$('loading').textContent = 'Could not open this PDF (' + (e && e.message ? e.message : e) + ')';
      return;
    }
    this.numPages = this.pdf.numPages;
    this.$('pageCount').textContent = this.numPages;
    this.$('pageInput').max = this.numPages;
    const first = await this.pdf.getPage(1);
    const vp = first.getViewport({ scale: 1 });
    this.baseSize = { w: vp.width, h: vp.height };
    this.page = Math.min(this.startPage, this.numPages);
    this._buildBook();
  }

  /* Build (or rebuild, on the spread/single toggle) the page divs and the
   * page-flip instance. flip.destroy() removes #book itself, so a rebuild
   * recreates it from scratch inside the wrapper. */
  _buildBook() {
    this._resetZoom();                   // the layout is about to change size
    if (this.flip) { this.flip.destroy(); this.flip = null; this.book = null; }
    if (this.book) this.book.remove();   // the template's placeholder, first time through
    this.rendered.clear();
    this.pending.clear();
    this.book = document.createElement('div');
    this.book.id = 'book';
    this.wrap.appendChild(this.book);
    for (let n = 1; n <= this.numPages; n++) {
      const d = document.createElement('div');
      d.className = 'page';
      d.dataset.page = n;
      // a stiff cover front and back, bendable paper between
      d.dataset.density = (n === 1 || n === this.numPages) ? 'hard' : 'soft';
      this.book.appendChild(d);
    }
    this._sizeWrapper();
    this.flip = new St.PageFlip(this.book, {
      width: this.baseSize.w, height: this.baseSize.h,
      // page-flip drops to a single (portrait) page when the book is narrower
      // than 2 × minWidth — two 340 px pages is the floor for readable text.
      // Single mode pins that: a minWidth no screen reaches keeps every
      // relayout in the one-page branch.
      size: 'stretch', minWidth: this.single ? 20000 : 340, maxWidth: 4000, minHeight: 160, maxHeight: 6000,
      showCover: true, usePortrait: true, autoSize: true,
      flippingTime: 900, maxShadowOpacity: 0.55, drawShadow: true,
      mobileScrollSupport: false, swipeDistance: 30, showPageCorners: true,
      startPage: this.page - 1,
    });
    this.flip.on('flip', (e) => {
      this.page = e.data + 1;
      this._updateBar();
      this._renderAround(this.page);
      this._post({ page: this.page });
    });
    this.flip.on('changeOrientation', () => { this._sizeWrapper(); this._renderAround(this.page, true); });
    this.flip.on('init', () => {
      this.$('loading').classList.add('done');
      this._updateBar();
      this._renderAround(this.page, true);
      this._post({ page_count: this.numPages, page: this.page });
    });
    this.flip.loadFromHTML(this.book.querySelectorAll('.page'));
  }

  /* The book stretches to its wrapper's width; pick that width so the spread
   * (or the single portrait page) also fits the stage's height. */
  _sizeWrapper() {
    if (!this.baseSize) return;
    const pad = 28;
    const sw = this.stage.clientWidth - pad, sh = this.stage.clientHeight - pad;
    const ratio = this.baseSize.w / this.baseSize.h;
    const portrait = this.single || (this.flip ? this.flip.getOrientation() === 'portrait' : sw < sh);
    const across = portrait ? 1 : 2;
    const w = Math.min(sw, sh * ratio * across);
    this.wrap.style.width = Math.max(120, Math.floor(w)) + 'px';
  }

  /* ---------- lazy page rendering ---------- */
  _renderAround(p, force) {
    const want = [p, p + 1, p - 1, p + 2, p + 3, p - 2, p - 3];
    want.forEach((n) => { if (n >= 1 && n <= this.numPages) this._render(n, force); });
  }

  /* The page numbers on screen right now — only these earn the zoomed-up
   * render resolution; neighbours prefetch at the fitted size. */
  _visiblePages() {
    if (!this.flip) return [this.page];
    const idx = this.flip.getCurrentPageIndex();
    if (this.flip.getOrientation() === 'portrait') return [idx + 1];
    const out = [idx + 1];
    if (idx > 0 && idx + 2 <= this.numPages) out.push(idx + 2);
    return out;
  }

  async _render(n, force) {
    const el = this.book.querySelector('.page[data-page="' + n + '"]');
    if (!el || this.pending.has(n)) return;
    // measure the laid-out book, not the page element: offscreen pages are
    // display:none and page-flip rewrites #book's style width during layout.
    // offsetWidth ignores the zoom transform — the zoom factor is applied
    // explicitly, and only to the pages actually on screen
    const portrait = this.flip && this.flip.getOrientation() === 'portrait';
    let cssW = this.book.offsetWidth / (portrait ? 1 : 2);
    if (!cssW) return;
    if (this._visiblePages().indexOf(n) !== -1) cssW *= this.zoom;
    const have = this.rendered.get(n);
    // re-render only when the page grew a lot (a blurry upscale) or shrank to
    // a fraction (wasted memory) — small relayouts just scale the canvas
    if (have && !force && cssW <= have * 1.25 && cssW >= have * 0.6) return;
    if (have && force && Math.abs(cssW - have) < 2) return;
    this.pending.add(n);
    try {
      const page = await this.pdf.getPage(n);
      let dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      const scale = cssW / this.baseSize.w;
      const vp = page.getViewport({ scale });
      // deep zoom on a big monitor could ask for an absurd canvas — cap the
      // backing store around 4k on either axis and let CSS stretch the rest
      dpr = Math.min(dpr, 4096 / vp.width, 4600 / vp.height);
      if (dpr <= 0) return;
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(vp.width * dpr);
      canvas.height = Math.round(vp.height * dpr);
      const ctx = canvas.getContext('2d', { alpha: false });
      ctx.fillStyle = '#f4efe4';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      await page.render({ canvasContext: ctx, viewport: vp }).promise;
      el.innerHTML = '';
      el.appendChild(canvas);
      this.rendered.set(n, cssW);
    } catch (e) {
      console.warn('page render failed', n, e);
    } finally {
      this.pending.delete(n);
    }
  }

  /* ---------- navigation ---------- */
  next() { if (this.flip) this.flip.flipNext(); }
  prev() { if (this.flip) this.flip.flipPrev(); }

  toggleSingle() {
    if (!this.flip) return;
    this.single = !this.single;
    try { localStorage.setItem('sp_handout_single', this.single ? '1' : '0'); } catch (e) { /* private mode */ }
    this._updateSingleBtn();
    this._buildBook();
    this._toast(this.single ? 'Single page' : 'Two-page spread');
  }

  _updateSingleBtn() {
    const b = this.$('btnSingle');
    // the button shows what it switches to
    b.innerHTML = this.single ? '&#9647;&#9647;' : '&#9647;';
    b.title = this.single ? 'Two-page spread (S)' : 'Single page (S)';
  }

  /* ---------- zoom + pan ---------- */
  /* Change zoom keeping the point under (cx, cy) — client coords — still.
   * With transform-origin at the wrapper's centre (which flex keeps on the
   * stage's centre), a content point u maps to centre + u·zoom + (tx, ty). */
  _setZoom(z, cx, cy) {
    z = Math.max(1, Math.min(this.maxZoom, z));
    const r = this.stage.getBoundingClientRect();
    if (cx === undefined) { cx = r.left + r.width / 2; cy = r.top + r.height / 2; }
    const sx = cx - (r.left + r.width / 2), sy = cy - (r.top + r.height / 2);
    const ux = (sx - this.tx) / this.zoom, uy = (sy - this.ty) / this.zoom;
    this.zoom = z;
    this.tx = sx - ux * z;
    this.ty = sy - uy * z;
    this._applyZoom();
  }

  _resetZoom() {
    this.zoom = 1;
    this.tx = this.ty = 0;
    clearTimeout(this._zoomT);
    if (this.wrap) this.wrap.style.transform = '';
    this.stage.classList.remove('zoomed');
    this._updateZoomUI();
  }

  _applyZoom() {
    if (this.zoom <= 1) {
      this._resetZoom();
      // fall through to the settle re-render so a zoomed canvas shrinks back
    } else {
      const mx = Math.max(0, (this.wrap.offsetWidth * this.zoom - this.stage.clientWidth) / 2);
      const my = Math.max(0, (this.wrap.offsetHeight * this.zoom - this.stage.clientHeight) / 2);
      this.tx = Math.max(-mx, Math.min(mx, this.tx));
      this.ty = Math.max(-my, Math.min(my, this.ty));
      this.wrap.style.transform = 'translate(' + this.tx + 'px, ' + this.ty + 'px) scale(' + this.zoom + ')';
      this.stage.classList.add('zoomed');
      this._updateZoomUI();
    }
    // once the gesture settles, redraw the visible pages at this resolution
    clearTimeout(this._zoomT);
    this._zoomT = setTimeout(() => this._renderAround(this.page, true), 350);
  }

  _updateZoomUI() {
    const pct = this.$('btnZoomReset');
    if (!pct) return;
    pct.textContent = Math.round(this.zoom * 100) + '%';
    this.$('btnZoomOut').disabled = this.zoom <= 1;
    this.$('btnZoomIn').disabled = this.zoom >= this.maxZoom;
  }

  goto(n) {
    if (!this.flip) return;
    n = Math.max(1, Math.min(this.numPages, parseInt(n, 10) || 1));
    const cur = this.flip.getCurrentPageIndex() + 1;
    if (n === cur) return;
    // a neighbouring spread animates; anything further jumps
    if (Math.abs(n - cur) <= 2) this.flip.flip(n - 1);
    else this.flip.turnToPage(n - 1);
    this.page = n;
    this._updateBar();
    this._renderAround(n);
    this._post({ page: n });
  }

  _updateBar() {
    if (!this.flip) return;
    const idx = this.flip.getCurrentPageIndex();
    const portrait = this.flip.getOrientation() === 'portrait';
    this.$('pageInput').value = idx + 1;
    this.$('btnPrev').disabled = this.$('btnFirst').disabled = idx <= 0;
    const lastShown = portrait ? idx : Math.min(this.numPages - 1, idx + 1);
    this.$('btnNext').disabled = this.$('btnLast').disabled = lastShown >= this.numPages - 1;
    const label = (!portrait && idx > 0 && idx + 1 < this.numPages) ? (idx + 1) + '–' + (idx + 2) : String(idx + 1);
    document.title = label + ' / ' + this.numPages + ' — ' + document.title.replace(/^.*? — /, '');
  }

  _toast(msg) {
    const t = this.$('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(this._toastT);
    this._toastT = setTimeout(() => t.classList.remove('show'), 1200);
  }

  _post(data) {
    this._postBuf = Object.assign(this._postBuf || {}, data);
    clearTimeout(this._postT);
    this._postT = setTimeout(() => {
      const body = JSON.stringify(this._postBuf);
      this._postBuf = null;
      fetch(this.opts.progressUrl, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true,
      }).catch(() => {});
    }, 600);
  }

  _bind() {
    this.$('btnNext').onclick = () => this.next();
    this.$('btnPrev').onclick = () => this.prev();
    this.$('btnFirst').onclick = () => this.goto(1);
    this.$('btnLast').onclick = () => this.goto(this.numPages);
    this.$('btnFull').onclick = () => this._fullscreen();
    this.$('btnSingle').onclick = () => this.toggleSingle();
    this._updateSingleBtn();
    this.$('btnZoomIn').onclick = () => this._setZoom(this.zoom * 1.25);
    this.$('btnZoomOut').onclick = () => this._setZoom(this.zoom / 1.25);
    this.$('btnZoomReset').onclick = () => this._setZoom(1);
    this._updateZoomUI();
    const input = this.$('pageInput');
    input.addEventListener('change', () => this.goto(input.value));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); e.stopPropagation(); });

    document.addEventListener('keydown', (e) => {
      if (e.target === input) return;
      switch (e.key) {
        case 'ArrowRight': case 'PageDown': case ' ': case 'ArrowDown': e.preventDefault(); this.next(); break;
        case 'ArrowLeft': case 'PageUp': case 'ArrowUp': case 'Backspace': e.preventDefault(); this.prev(); break;
        case 'Home': e.preventDefault(); this.goto(1); break;
        case 'End': e.preventDefault(); this.goto(this.numPages); break;
        case 'f': case 'F': this._fullscreen(); break;
        case 's': case 'S': this.toggleSingle(); break;
        case 'g': case 'G': input.focus(); input.select(); break;
        case '+': case '=': this._setZoom(this.zoom * 1.25); break;
        case '-': case '_': this._setZoom(this.zoom / 1.25); break;
        case '0': this._setZoom(1); break;
      }
    });
    // wheel: ctrl+wheel (incl. trackpad pinch) zooms at the cursor; a plain
    // wheel pans while zoomed, otherwise one notch = one page turn (the
    // library ignores a flip already in progress)
    this.stage.addEventListener('wheel', (e) => {
      if (e.ctrlKey) {
        e.preventDefault();
        this._setZoom(this.zoom * Math.exp(-e.deltaY * 0.0022), e.clientX, e.clientY);
        return;
      }
      if (this.zoom > 1) {
        e.preventDefault();
        this.tx -= e.deltaX;
        this.ty -= e.deltaY;
        this._applyZoom();
        return;
      }
      if (Math.abs(e.deltaY) < 10 && Math.abs(e.deltaX) < 10) return;
      e.preventDefault();
      if ((e.deltaY || e.deltaX) > 0) this.next(); else this.prev();
    }, { passive: false });

    // While zoomed a drag pans; capture phase so page-flip's own handlers
    // (fold drag, swipe) never see the gesture. A two-finger pinch always
    // wins, even from the fitted view.
    this.stage.addEventListener('mousedown', (e) => {
      if (this.zoom <= 1 || e.button !== 0) return;
      e.stopPropagation();
      e.preventDefault();
      const s = { x: e.clientX, y: e.clientY, tx0: this.tx, ty0: this.ty };
      this.stage.classList.add('panning');
      const mv = (ev) => {
        this.tx = s.tx0 + ev.clientX - s.x;
        this.ty = s.ty0 + ev.clientY - s.y;
        this._applyZoom();
      };
      const up = () => {
        this.stage.classList.remove('panning');
        document.removeEventListener('mousemove', mv);
        document.removeEventListener('mouseup', up);
      };
      document.addEventListener('mousemove', mv);
      document.addEventListener('mouseup', up);
    }, true);

    const dist = (a, b) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    let touch = null;   // {pinch, d0, z0} or {pan fields}
    const startPan = (t) => { touch = { x: t.clientX, y: t.clientY, tx0: this.tx, ty0: this.ty }; };
    this.stage.addEventListener('touchstart', (e) => {
      if (e.touches.length === 2) {
        touch = { pinch: true, d0: dist(e.touches[0], e.touches[1]), z0: this.zoom };
      } else if (this.zoom > 1 && e.touches.length === 1) {
        startPan(e.touches[0]);
      } else {
        touch = null;
        return;                          // fitted single touch: page-flip's swipe
      }
      e.stopPropagation();
      e.preventDefault();
    }, { capture: true, passive: false });
    this.stage.addEventListener('touchmove', (e) => {
      if (!touch) return;
      e.stopPropagation();
      e.preventDefault();
      if (touch.pinch && e.touches.length >= 2) {
        const a = e.touches[0], b = e.touches[1];
        this._setZoom(touch.z0 * dist(a, b) / touch.d0,
                      (a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
      } else if (!touch.pinch) {
        this.tx = touch.tx0 + e.touches[0].clientX - touch.x;
        this.ty = touch.ty0 + e.touches[0].clientY - touch.y;
        this._applyZoom();
      }
    }, { capture: true, passive: false });
    const touchDone = (e) => {
      if (!touch) return;
      e.stopPropagation();
      if (e.touches.length === 1 && this.zoom > 1) startPan(e.touches[0]);
      else if (e.touches.length === 0) touch = null;
    };
    this.stage.addEventListener('touchend', touchDone, true);
    this.stage.addEventListener('touchcancel', touchDone, true);

    let rt = null;
    const relayout = () => {
      clearTimeout(rt);
      rt = setTimeout(() => {
        if (!this.flip) return;
        this._sizeWrapper();
        this.flip.update();
        if (this.zoom > 1) this._applyZoom();   // re-clamp the pan to the new size
        this._renderAround(this.page);
      }, 150);
    };
    window.addEventListener('resize', relayout);

    // fullscreen: hide the bar after a moment of stillness, bring it back on movement
    const bar = this.$('bar');
    let hideT = null;
    const arm = () => {
      bar.classList.remove('hidden');
      clearTimeout(hideT);
      if (document.fullscreenElement) hideT = setTimeout(() => bar.classList.add('hidden'), 2000);
    };
    document.addEventListener('mousemove', arm);
    document.addEventListener('fullscreenchange', () => {
      document.body.classList.toggle('chromeless', !!document.fullscreenElement);
      arm();
      relayout();
    });
  }

  _fullscreen() {
    if (document.fullscreenElement) { document.exitFullscreen && document.exitFullscreen(); return; }
    const el = document.documentElement;
    if (el.requestFullscreen) el.requestFullscreen().catch(() => this._toast('Fullscreen not available'));
  }
}

/* Page-turning PDF reader for Utilities → Handouts (templates/handout_read.html).
 *
 * pdf.js renders pages to canvases on demand; StPageFlip (page-flip.browser.js,
 * MIT — the global `St`) does the book: soft pages that bend along the fold as
 * they turn, corner-drag, two-page spread on wide screens and a single page in
 * portrait. The book is one <div> per PDF page, all created empty up front so
 * the library knows the page count; a page's canvas is rendered only when it
 * comes within a few pages of the one being read, and re-rendered when the
 * book is re-laid-out at a very different size. Progress (page + count) is
 * posted back, debounced. */
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
      // than 2 × minWidth — two 340 px pages is the floor for readable text
      size: 'stretch', minWidth: 340, maxWidth: 4000, minHeight: 160, maxHeight: 6000,
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
    const portrait = this.flip ? this.flip.getOrientation() === 'portrait' : sw < sh;
    const across = portrait ? 1 : 2;
    const w = Math.min(sw, sh * ratio * across);
    this.wrap.style.width = Math.max(120, Math.floor(w)) + 'px';
  }

  /* ---------- lazy page rendering ---------- */
  _renderAround(p, force) {
    const want = [p, p + 1, p - 1, p + 2, p + 3, p - 2, p - 3];
    want.forEach((n) => { if (n >= 1 && n <= this.numPages) this._render(n, force); });
  }

  async _render(n, force) {
    const el = this.book.querySelector('.page[data-page="' + n + '"]');
    if (!el || this.pending.has(n)) return;
    // measure the laid-out book, not the page element: offscreen pages are
    // display:none and page-flip rewrites #book's style width during layout
    const portrait = this.flip && this.flip.getOrientation() === 'portrait';
    const cssW = this.book.getBoundingClientRect().width / (portrait ? 1 : 2);
    if (!cssW) return;
    const have = this.rendered.get(n);
    // re-render only when the page grew a lot (a blurry upscale) or shrank to
    // a fraction (wasted memory) — small relayouts just scale the canvas
    if (have && !force && cssW <= have * 1.25 && cssW >= have * 0.6) return;
    if (have && force && Math.abs(cssW - have) < 2) return;
    this.pending.add(n);
    try {
      const page = await this.pdf.getPage(n);
      const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      const scale = cssW / this.baseSize.w;
      const vp = page.getViewport({ scale });
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
        case 'g': case 'G': input.focus(); input.select(); break;
      }
    });
    // mouse wheel: one notch = one turn (the library ignores a flip already in progress)
    this.stage.addEventListener('wheel', (e) => {
      if (Math.abs(e.deltaY) < 10 && Math.abs(e.deltaX) < 10) return;
      e.preventDefault();
      if ((e.deltaY || e.deltaX) > 0) this.next(); else this.prev();
    }, { passive: false });

    let rt = null;
    const relayout = () => {
      clearTimeout(rt);
      rt = setTimeout(() => {
        if (!this.flip) return;
        this._sizeWrapper();
        this.flip.update();
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

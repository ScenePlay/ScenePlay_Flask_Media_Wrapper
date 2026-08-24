// Shared Gemini one-click helpers for image flows outside the battle-map
// pages (portraits, monster/homebrew token icons). The heavy lifting is the
// server's /ttrpg/ai/image-generate endpoint (key never reaches the
// browser); this file just turns the response into a Blob and gates the
// buttons on whether a key is configured.
//
// Usage:
//   aiConfigured().then(on => { if (on) show the ✨ buttons; });
//   aiImageBlob(promptText).then(blob => ...save via the flow's own path...);

let _aiStatusPromise = null;

function aiStatus() {
  if (!_aiStatusPromise) {
    _aiStatusPromise = fetch('/ttrpg/ai/status')
      .then(r => r.json())
      .catch(() => ({ ok: false }));
  }
  return _aiStatusPromise;
}

function aiConfigured() {
  return aiStatus().then(d =>
    !!(d.ok && (d.image_ready !== undefined ? d.image_ready : d.configured)));
}

// 'Runware' or 'Gemini' — whichever paints images right now.
function aiImageProviderName(d) {
  return d && d.image_provider === 'runware' ? 'Runware' : 'Gemini';
}

// Short display form of a model id: 'runware:400@3' → '400@3',
// 'gemini-3.1-flash-image' → '3.1-flash-image'.
function aiShortModel(id) {
  return String(id || '').replace(/^runware:/, '').replace(/^gemini-/, '');
}

// Rewrite a ✨ button's label/tooltip to name the ACTIVE image provider AND
// the model it will run — with Runware selected, a button still reading
// "Generate with Gemini" made it look like the setting hadn't taken.
function aiBrandImageButton(el) {
  if (!el) return;
  aiStatus().then(d => {
    const name = aiImageProviderName(d);
    el.innerHTML = el.innerHTML.replace(/Gemini/g, name)
      + (d.image_model ? ' <small>(' + aiShortModel(d.image_model) + ')</small>' : '');
    if (el.title) {
      el.title = el.title.replace(/Gemini/g, name)
        + (d.image_model ? ' — model: ' + d.image_model : '');
    }
  });
}

// {ok, ext, image_b64} (the shape every AI image endpoint returns) → Blob.
function aiResponseToBlob(d) {
  if (!d || !d.ok) throw new Error((d && d.error) || 'Gemini generation failed');
  const bin = atob(d.image_b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const mime = d.ext === 'jpg' ? 'image/jpeg' : 'image/' + (d.ext || 'png');
  return new Blob([bytes], { type: mime });
}

function aiImageBlob(promptText, model) {
  return fetch('/ttrpg/ai/image-generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt_text: promptText, model: model || undefined }),
  }).then(r => r.json()).then(aiResponseToBlob);
}

// ── Preview before save ───────────────────────────────────────────────────────
// Every AI image flow shows the result here before anything is saved:
// "Use this image" resolves 'use', "Regenerate" resolves 'regen', Discard /
// close / Esc resolve 'discard'. One modal, injected on first use.
function aiPreviewImage(blob, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    let modal = document.getElementById('aiPreviewModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'aiPreviewModal';
      modal.className = 'modal fade';
      modal.tabIndex = -1;
      modal.innerHTML =
        '<div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable"><div class="modal-content">'
        + '<div class="modal-header"><h5 class="modal-title"></h5>'
        + '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>'
        + '<div class="modal-body text-center">'
        + '<img class="ai-preview-img" alt="Generated image" style="max-width:100%;max-height:70vh;border-radius:6px;">'
        + '<p class="ai-preview-note small text-muted mt-2 mb-0"></p></div>'
        + '<div class="modal-footer">'
        + '<button type="button" class="btn btn-outline-secondary ai-preview-discard">Discard</button>'
        + '<button type="button" class="btn btn-outline-primary ai-preview-regen">&#10024; Regenerate</button>'
        + '<button type="button" class="btn btn-primary ai-preview-use">Use this image</button>'
        + '</div></div></div>';
      document.body.appendChild(modal);
    }
    const url = URL.createObjectURL(blob);
    modal.querySelector('.modal-title').textContent = opts.title || 'Generated image';
    modal.querySelector('.ai-preview-note').textContent = opts.note || 'Nothing is saved until you choose "Use this image".';
    modal.querySelector('.ai-preview-img').src = url;
    modal.querySelector('.ai-preview-use').textContent = opts.useLabel || 'Use this image';
    const inst = bootstrap.Modal.getOrCreateInstance(modal, { backdrop: 'static' });
    let choice = 'discard';
    const pick = c => { choice = c; inst.hide(); };
    modal.querySelector('.ai-preview-use').onclick = () => pick('use');
    modal.querySelector('.ai-preview-regen').onclick = () => pick('regen');
    modal.querySelector('.ai-preview-discard').onclick = () => pick('discard');
    modal.addEventListener('hidden.bs.modal', () => {
      URL.revokeObjectURL(url);
      resolve(choice);
    }, { once: true });
    inst.show();
  });
}

// generate → preview → (regenerate…) → the accepted Blob, or null if the
// user discarded it. `generate` is an async function returning a Blob;
// opts.onRegenerate runs before each retry (pages use it for "Painting…").
async function aiImageWithPreview(generate, opts) {
  opts = opts || {};
  for (;;) {
    const blob = await generate();
    const choice = await aiPreviewImage(blob, opts);
    if (choice === 'use') return blob;
    if (choice !== 'regen') return null;
    if (opts.onRegenerate) opts.onRegenerate();
  }
}

// Drop a generated blob into a form's <input type="file"> so the normal
// form submit saves it — the paste_image.js trick, for pages where the
// entity has no id yet (new character / new homebrew monster).
function aiBlobToFileInput(blob, input, filename) {
  const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
  const dt = new DataTransfer();
  dt.items.add(new File([blob], (filename || 'gemini') + '.' + ext,
                        { type: blob.type }));
  input.files = dt.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

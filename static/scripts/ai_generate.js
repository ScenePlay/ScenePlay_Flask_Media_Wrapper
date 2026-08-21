// Shared Gemini one-click helpers for image flows outside the battle-map
// pages (portraits, monster/homebrew token icons). The heavy lifting is the
// server's /ttrpg/ai/image-generate endpoint (key never reaches the
// browser); this file just turns the response into a Blob and gates the
// buttons on whether a key is configured.
//
// Usage:
//   aiConfigured().then(on => { if (on) show the ✨ buttons; });
//   aiImageBlob(promptText).then(blob => ...save via the flow's own path...);

let _aiConfiguredPromise = null;

function aiConfigured() {
  if (!_aiConfiguredPromise) {
    _aiConfiguredPromise = fetch('/ttrpg/ai/status')
      .then(r => r.json())
      .then(d => !!(d.ok && d.configured))
      .catch(() => false);
  }
  return _aiConfiguredPromise;
}

function aiImageBlob(promptText, model) {
  return fetch('/ttrpg/ai/image-generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt_text: promptText, model: model || undefined }),
  }).then(r => r.json())
    .then(d => {
      if (!d.ok) throw new Error(d.error || 'Gemini generation failed');
      const bin = atob(d.image_b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const mime = d.ext === 'jpg' ? 'image/jpeg' : 'image/' + (d.ext || 'png');
      return new Blob([bytes], { type: mime });
    });
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

// Clipboard → file-input bridge, shared by every image-accepting form.
//
// Usage: put a button in the SAME container as the <input type="file"> and
// call pasteImageNear(this). Reads an image off the clipboard (or, where the
// async Clipboard API is unavailable/denied — e.g. Firefox — arms a one-shot
// Ctrl+V listener), drops it into the input via DataTransfer, and fires
// 'change' so existing preview/upload handlers run untouched.
async function pasteImageNear(btn) {
  const scope = btn.parentElement;
  const input = scope && scope.querySelector('input[type="file"]');
  if (!input) return;
  const orig = btn.innerHTML;
  const done = (msg, ok) => {
    btn.innerHTML = msg;
    btn.disabled = false;
    setTimeout(() => { btn.innerHTML = orig; }, ok ? 1200 : 2500);
  };
  const apply = (blob) => {
    const ext = ((blob.type || 'image/png').split('/')[1] || 'png').replace('jpeg', 'jpg');
    const dt = new DataTransfer();
    dt.items.add(new File([blob], 'pasted.' + ext, { type: blob.type || 'image/png' }));
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    done('&#10003; Pasted', true);
  };

  btn.disabled = true;
  if (navigator.clipboard && navigator.clipboard.read) {
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const t = item.types.find(x => x.startsWith('image/'));
        if (t) { apply(await item.getType(t)); return; }
      }
      done('No image in clipboard', false);
      return;
    } catch (e) { /* permission denied — fall back to keyboard paste */ }
  }

  // Fallback: user presses Ctrl+V while we listen once
  btn.disabled = false;
  btn.innerHTML = 'Now press Ctrl+V…';
  const tid = setTimeout(() => { btn.innerHTML = orig; }, 15000);
  document.addEventListener('paste', function handler(e) {
    clearTimeout(tid);
    const item = Array.from(e.clipboardData.items).find(i => i.type.startsWith('image/'));
    if (item) { e.preventDefault(); apply(item.getAsFile()); }
    else done('No image in clipboard', false);
  }, { once: true });
}

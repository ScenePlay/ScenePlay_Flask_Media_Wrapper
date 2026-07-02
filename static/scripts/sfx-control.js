/* static/scripts/sfx-control.js
   Wires the static #sfx-ctrl pill (toggle + volume slider) to the SFX module.
   Shared by the battlemap and character-sheet pages — include AFTER sfx.js and
   after the #sfx-ctrl element exists in the DOM. */
// ── SFX control: wire the static #sfx-ctrl element ────────────────────────────
(function () {
  const toggle = document.getElementById('sfx-toggle');
  const slider = document.getElementById('sfx-vol');
  if (!toggle || !slider) return;

  if (!window.SFX) {   // sfx.js failed to load — tell the user instead of hiding
    toggle.innerHTML = '&#9888; Sound unavailable';
    toggle.style.color = '#e06666';
    return;
  }

  slider.value = Math.round(SFX.getVolume() * 100);

  function syncUI() {
    if (!SFX.hasTone()) { toggle.innerHTML = '&#9888; Tone.js not loaded'; toggle.style.color = '#e06666'; return; }
    let icon, text, color;
    if (!SFX.isEnabled())   { icon = '&#128264;'; text = 'Sound: tap to start'; color = '#c9a84c'; }
    else if (SFX.isMuted()) { icon = '&#128263;'; text = 'Sound: MUTED';        color = '#e06666'; }
    else                    { icon = '&#128266;'; text = 'Sound: ON';           color = '#7bc77b'; }
    toggle.innerHTML = icon + ' ' + text;
    toggle.style.color = color;
    slider.style.opacity = (SFX.isEnabled() && !SFX.isMuted()) ? '1' : '.5';
  }

  // Sound is enabled ONLY by interacting with the pill, so clicking the other
  // toolbar buttons next to it no longer toggles sound. (Browsers still require
  // a user gesture — the pill's own click below satisfies that.)
  toggle.addEventListener('click', async () => {
    const wasOn = SFX.isEnabled();
    const ok = await SFX.enable();
    if (!ok) {   // surface WHY, instead of doing nothing
      toggle.innerHTML = '&#9888; ' + (SFX.lastError() || 'audio failed');
      toggle.style.color = '#e06666';
      return;
    }
    if (wasOn) SFX.mute(!SFX.isMuted());   // first click only enables; later clicks toggle mute
    syncUI();
  });
  slider.addEventListener('input', () => SFX.setVolume(slider.value / 100));
  syncUI();
})();

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
    // Sound is ON by default — before the browser lets audio actually start
    // (it needs one user gesture anywhere on the page) the pill already
    // reads ON, amber until the audio context is truly running.
    if (SFX.isMuted())           { icon = '&#128263;'; text = 'Sound: MUTED'; color = '#e06666'; }
    else if (!SFX.isEnabled())   { icon = '&#128266;'; text = 'Sound: ON';    color = '#c9a84c'; }
    else                         { icon = '&#128266;'; text = 'Sound: ON';    color = '#7bc77b'; }
    toggle.innerHTML = icon + ' ' + text;
    toggle.style.color = color;
    slider.style.opacity = SFX.isMuted() ? '.5' : '1';
  }

  // Auto-start: browsers demand ONE user gesture before audio may play, but
  // it can be ANY gesture — so the first click/keypress anywhere arms the
  // audio context and sound is simply on, no dedicated tap on the pill
  // needed. A user who muted (persisted) stays muted; unmuting re-enables.
  function autoStart() {
    document.removeEventListener('pointerdown', autoStart, true);
    document.removeEventListener('keydown', autoStart, true);
    if (SFX.isMuted() || SFX.isEnabled()) return;
    SFX.enable().then(syncUI).catch(() => {});
  }
  document.addEventListener('pointerdown', autoStart, true);
  document.addEventListener('keydown', autoStart, true);

  // The pill toggles MUTE (sound is on by default; tap = turn off).
  toggle.addEventListener('click', async () => {
    const ok = await SFX.enable();
    if (!ok) {   // surface WHY, instead of doing nothing
      toggle.innerHTML = '&#9888; ' + (SFX.lastError() || 'audio failed');
      toggle.style.color = '#e06666';
      return;
    }
    SFX.mute(!SFX.isMuted());
    syncUI();
  });
  slider.addEventListener('input', () => SFX.setVolume(slider.value / 100));
  syncUI();
})();

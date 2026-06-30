/* static/scripts/sfx.js
   ScenePlay sound-effects module — in-browser Tone.js synthesis.
   Shared by the local battlemap and (ported later) the relay portal.

   Requires Tone.js to be loaded first (CDN <script> tag).

   Each event (crit/fumble/move/damage/heal/dead/mapswitch) offers several
   VARIANTS with different envelopes/characters. The audition page lets you
   hear them and pick one; the chosen variant is persisted per-browser and
   is what SFX.play(event) fires.

   Usage:
     await SFX.enable();              // MUST be called from a user gesture
     SFX.play('crit');               // plays the SELECTED variant for the event
     SFX.playVariant('crit','peal'); // audition a specific variant
     SFX.select('crit','peal');      // choose + persist a variant for play()
     SFX.events();                   // ['crit','fumble',...]
     SFX.variants('crit');           // [{id,label,env}, ...]
     SFX.getSelected('crit');        // currently-chosen variant id
     SFX.setVolume(0.8); SFX.mute(true);

   Design: one shared limiter + light reverb; voices built once on enable()
   and reused. play() is a no-op until enabled and is wrapped so a bad sound
   can never throw into the host app.
*/
window.SFX = (function () {
  'use strict';

  const LS_VOL  = 'sceneplay_sfx_volume';
  const LS_MUTE = 'sceneplay_sfx_muted';
  const LS_SEL  = 'sceneplay_sfx_selected';

  let started = false;
  let bus = null;          // { limiter, master, reverb }
  let v   = null;          // reusable voices
  let _volume = 0.8;
  let _muted  = false;
  let _selected = {};      // event -> chosen variant id
  let _lastError = '';     // why enable() last failed (for on-screen diagnostics)

  // Restore persisted prefs
  try {
    const sv = localStorage.getItem(LS_VOL);
    if (sv !== null) _volume = Math.max(0, Math.min(1, parseFloat(sv) || 0));
    _muted = localStorage.getItem(LS_MUTE) === '1';
    _selected = JSON.parse(localStorage.getItem(LS_SEL) || '{}') || {};
  } catch (e) { _selected = {}; }

  const _hasTone    = () => typeof Tone !== 'undefined';
  const _masterGain = () => (_muted ? 0 : _volume);

  function _buildBus() {
    const limiter = new Tone.Limiter(-2).toDestination();
    const master  = new Tone.Gain(_masterGain()).connect(limiter);
    const reverb  = new Tone.Freeverb({ roomSize: 0.7, dampening: 3000, wet: 1 }).connect(master);
    return { limiter, master, reverb };
  }

  // Route a source node to both the dry master and the reverb send.
  function _route(node, gain, revAmt) {
    const dry  = new Tone.Gain(gain).connect(bus.master);
    const send = new Tone.Gain(revAmt).connect(bus.reverb);
    node.connect(dry);
    node.connect(send);
  }

  function _buildVoices() {
    // Brass — saw FM (crit fanfare/stab)
    const brass = new Tone.PolySynth(Tone.FMSynth, {
      maxPolyphony: 8, harmonicity: 1, modulationIndex: 5,
      oscillator: { type: 'sawtooth' },
      envelope: { attack: 0.02, decay: 0.1, sustain: 0.7, release: 0.25 },
      modulation: { type: 'square' },
      modulationEnvelope: { attack: 0.02, decay: 0.1, sustain: 0.5, release: 0.2 }
    });
    const brassFilt = new Tone.Filter(3000, 'lowpass');
    brass.connect(brassFilt); _route(brassFilt, 0.5, 0.25);

    // Reed/crumhorn — square FM (fumble, dirge)
    const reed = new Tone.PolySynth(Tone.FMSynth, {
      maxPolyphony: 4, harmonicity: 1, modulationIndex: 2.4,
      oscillator: { type: 'square' },
      envelope: { attack: 0.03, decay: 0.06, sustain: 0.8, release: 0.18 },
      modulation: { type: 'square' },
      modulationEnvelope: { attack: 0.03, decay: 0.12, sustain: 0.6, release: 0.18 }
    });
    const reedFilt = new Tone.Filter(2000, 'lowpass');
    reed.connect(reedFilt); _route(reedFilt, 0.4, 0.2);

    // Bell — inharmonic FM (crit peal, heal chime, dead knell/gong)
    const bell = new Tone.PolySynth(Tone.FMSynth, {
      maxPolyphony: 6, harmonicity: 3.01, modulationIndex: 6,
      oscillator: { type: 'sine' },
      envelope: { attack: 0.004, decay: 1.4, sustain: 0, release: 1.2 },
      modulation: { type: 'sine' },
      modulationEnvelope: { attack: 0.004, decay: 0.5, sustain: 0, release: 0.6 }
    });
    _route(bell, 0.35, 0.4);

    // Harp/pluck — triangle FM (heal shimmer, map gliss, move tick)
    const harp = new Tone.PolySynth(Tone.FMSynth, {
      maxPolyphony: 8, harmonicity: 2, modulationIndex: 3,
      oscillator: { type: 'triangle' },
      envelope: { attack: 0.003, decay: 0.6, sustain: 0, release: 0.5 },
      modulation: { type: 'sine' },
      modulationEnvelope: { attack: 0.003, decay: 0.1, sustain: 0, release: 0.1 }
    });
    _route(harp, 0.3, 0.3);

    // Pad — AM swell (heal swell). SLOW attack: the clearest envelope demo.
    const pad = new Tone.PolySynth(Tone.AMSynth, {
      maxPolyphony: 5, harmonicity: 1.5,
      oscillator: { type: 'sine' },
      envelope: { attack: 0.5, decay: 0.4, sustain: 0.8, release: 0.9 },
      modulation: { type: 'triangle' },
      modulationEnvelope: { attack: 0.5, decay: 0.3, sustain: 0.6, release: 0.7 }
    });
    const padFilt = new Tone.Filter(1400, 'lowpass');
    pad.connect(padFilt); _route(padFilt, 0.3, 0.4);

    // Footstep — a POOL of brown-noise voices. A single monophonic NoiseSynth
    // can't take the 4-in-a-row sequence (or rapid repeated moves): the later
    // scheduled hits choke and the voice gets stuck ("plays once then stops").
    // Round-robining a small pool gives each hit its own clean voice.
    const step = [];
    for (let i = 0; i < 4; i++) {
      const n = new Tone.NoiseSynth({
        noise: { type: 'brown' },
        envelope: { attack: 0.004, decay: 0.08, sustain: 0, release: 0.05 }
      });
      const f = new Tone.Filter(900, 'lowpass');
      n.connect(f); _route(f, 0.45, 0.08);
      step.push(n);
    }

    // General white noise w/ automatable filter (whoosh, riser, crunch)
    const noise = new Tone.NoiseSynth({
      noise: { type: 'white' },
      envelope: { attack: 0.008, decay: 0.06, sustain: 0.5, release: 0.1 }
    });
    const noiseFilt = new Tone.Filter(2000, 'lowpass');
    noise.connect(noiseFilt); _route(noiseFilt, 0.3, 0.25);

    // Membrane drum (damage thud/impact, fumble dud)
    const thud = new Tone.MembraneSynth({
      pitchDecay: 0.06, octaves: 4,
      oscillator: { type: 'sine' },
      envelope: { attack: 0.002, decay: 0.22, sustain: 0, release: 0.1 }
    });
    _route(thud, 0.5, 0.12);

    return { brass, reed, bell, harp, pad, step, noise, noiseFilt, thud };
  }

  // Sweep helper for the white-noise filter (used by whoosh / riser).
  function _sweep(from, to, dur) {
    const t = Tone.now();
    v.noiseFilt.frequency.cancelScheduledValues(t);
    v.noiseFilt.frequency.setValueAtTime(from, t);
    v.noiseFilt.frequency.exponentialRampToValueAtTime(to, t + dur);
    return t;
  }

  // ── Variant registry: event -> { id: {label, env, play} } ────────────
  // `env` is a plain-language note about the envelope, shown in the
  // audition UI to help build intuition for attack/decay/release.
  const VARIANTS = {
    crit: {
      fanfare: { label: 'Fanfare', env: 'sharp attack · 0.18s notes · rising arpeggio', play() {
        const t = Tone.now();
        ['G4','C5','E5','G5'].forEach((n,i)=>v.brass.triggerAttackRelease(n,0.18,t+i*0.09,0.8));
        v.brass.triggerAttackRelease('C6',0.5,t+0.36,0.9);
      }},
      stab: { label: 'Power stab', env: 'instant attack · stacked chord · short', play() {
        const t = Tone.now();
        ['C4','G4','C5','E5'].forEach(n=>v.brass.triggerAttackRelease(n,0.22,t,0.7));
        v.brass.triggerAttackRelease('G5',0.45,t+0.14,0.85);
      }},
      peal: { label: 'Bell peal', env: 'sharp attack · long ring · rising bells', play() {
        const t = Tone.now();
        ['C5','E5','G5','C6'].forEach((n,i)=>v.bell.triggerAttackRelease(n,0.9,t+i*0.07,0.55));
      }},
    },
    fumble: {
      trombone: { label: 'Sad trombone', env: 'medium attack · falling pitch · low', play() {
        const t = Tone.now();
        ['E2','Eb2','D2','Db2'].forEach((n,i)=>v.reed.triggerAttackRelease(n,0.22,t+i*0.12,0.7));
        v.reed.triggerAttackRelease('A1',0.6,t+0.5,0.7);
      }},
      squeak: { label: 'Comic squeak', env: 'fast attack · short · two-note down-slip', play() {
        const t = Tone.now();
        ['A4','F4'].forEach((n,i)=>v.reed.triggerAttackRelease(n,0.12,t+i*0.1,0.6));
      }},
      dud: { label: 'Dud', env: 'instant · no tail · muffled drum + reed', play() {
        const t = Tone.now();
        v.thud.triggerAttackRelease('G1',0.18,t,0.6);
        v.reed.triggerAttackRelease('D2',0.16,t+0.04,0.45);
      }},
    },
    move: {
      step: { label: 'Footstep', env: 'four steps in a row · dry (brown noise)', play() {
        const t = Tone.now();
        // Four footfalls in a walking cadence, alternating velocity for a
        // natural left/right feel. Each hit uses a separate pooled voice so
        // no single monophonic synth is retriggered mid-sound.
        [0.6, 0.5, 0.6, 0.5].forEach((vel, i) =>
          v.step[i % v.step.length].triggerAttackRelease(0.08, t + i * 0.24, vel));
      }},
      whoosh: { label: 'Cloth whoosh', env: 'soft burst · filter closes (sweep down)', play() {
        const t = _sweep(2200, 500, 0.18);
        v.noise.triggerAttackRelease(0.16, t, 0.25);
      }},
      tick: { label: 'Soft tick', env: 'instant · ultra-short · pitched click', play() {
        v.harp.triggerAttackRelease('C6', 0.05, Tone.now(), 0.4);
      }},
    },
    damage: {
      thud: { label: 'Thud', env: 'instant attack · 0.2s decay · low drum', play() {
        v.thud.triggerAttackRelease('C2', 0.2, Tone.now(), 0.5);
      }},
      crunch: { label: 'Crunch', env: 'instant · drum + noise burst', play() {
        const t = _sweep(1800, 1800, 0.01);
        v.thud.triggerAttackRelease('C2', 0.18, t, 0.5);
        v.noise.triggerAttackRelease(0.08, t, 0.3);
      }},
      impact: { label: 'Sub impact', env: 'instant · pitch-drop · deep', play() {
        v.thud.triggerAttackRelease('G1', 0.3, Tone.now(), 0.7);
      }},
    },
    heal: {
      chime: { label: 'Chime', env: 'sharp attack · long ring · two rising bells', play() {
        const t = Tone.now();
        v.bell.triggerAttackRelease('C5', 0.6, t, 0.5);
        v.bell.triggerAttackRelease('G5', 0.8, t + 0.12, 0.45);
      }},
      shimmer: { label: 'Shimmer', env: 'sharp attack · quick sparkly harp run', play() {
        const t = Tone.now();
        ['C5','E5','G5','B5','D6'].forEach((n,i)=>v.harp.triggerAttackRelease(n,0.4,t+i*0.05,0.4));
      }},
      swell: { label: 'Warm swell', env: 'SLOW attack · soft pad rising', play() {
        const t = Tone.now();
        v.pad.triggerAttackRelease('C4', 1.2, t, 0.4);
        v.pad.triggerAttackRelease('G4', 1.2, t + 0.05, 0.4);
        v.pad.triggerAttackRelease('C5', 1.3, t + 0.1, 0.35);
      }},
    },
    dead: {
      knell: { label: 'Knell', env: 'sharp attack · VERY long release (5s) · low bell', play() {
        v.bell.triggerAttackRelease('C3', 5.0, Tone.now(), 1.0);
      }},
      gong: { label: 'Deep gong', env: 'sharp attack · long · very low', play() {
        v.bell.triggerAttackRelease('C2', 4.0, Tone.now(), 0.9);
      }},
      dirge: { label: 'Dirge', env: 'medium attack · three falling notes · somber', play() {
        const t = Tone.now();
        ['G3','Eb3','C3'].forEach((n,i)=>v.reed.triggerAttackRelease(n,0.7,t+i*0.32,0.6));
      }},
    },
    mapswitch: {
      riser: { label: 'Riser', env: 'held noise · filter opens upward · airy', play() {
        const t = _sweep(400, 4000, 0.22);
        v.noise.triggerAttackRelease(0.24, t, 0.4);
      }},
      gliss: { label: 'Harp gliss', env: 'fast attack · rising harp run', play() {
        const t = Tone.now();
        ['C4','E4','G4','C5','E5','G5'].forEach((n,i)=>v.harp.triggerAttackRelease(n,0.5,t+i*0.045,0.4));
      }},
      chimeup: { label: 'Whoosh + ding', env: 'noise sweep up + bell accent', play() {
        const t = _sweep(500, 3500, 0.2);
        v.noise.triggerAttackRelease(0.2, t, 0.3);
        v.bell.triggerAttackRelease('C6', 0.6, t + 0.2, 0.5);
      }},
    },
  };

  const _firstId = (event) => Object.keys(VARIANTS[event] || {})[0];

  // ── public API ───────────────────────────────────────────────────────
  async function enable() {
    if (started) return true;
    if (!_hasTone()) { _lastError = 'Tone.js not loaded'; console.warn('SFX: ' + _lastError); return false; }
    try {
      await Tone.start();          // requires a user gesture
      bus = _buildBus();
      v   = _buildVoices();
      started = true;
      _lastError = '';
      return true;
    } catch (e) {
      _lastError = (e && e.message) ? e.message : String(e);
      console.warn('SFX enable failed:', _lastError);
      return false;
    }
  }

  function _run(fn) { if (fn) { try { fn(); } catch (e) {} } }

  // Play the chosen variant for an event (what the app calls).
  function play(event) {
    if (!started || _muted) return;
    const set = VARIANTS[event];
    if (!set) return;
    const id = (_selected[event] && set[_selected[event]]) ? _selected[event] : _firstId(event);
    _run(set[id] && set[id].play);
  }

  // Audition one specific variant (used by the chooser page).
  function playVariant(event, id) {
    if (!started || _muted) return;
    const set = VARIANTS[event];
    _run(set && set[id] && set[id].play);
  }

  function select(event, id) {
    if (!VARIANTS[event] || !VARIANTS[event][id]) return;
    _selected[event] = id;
    try { localStorage.setItem(LS_SEL, JSON.stringify(_selected)); } catch (e) {}
  }

  function getSelected(event) {
    return (_selected[event] && VARIANTS[event] && VARIANTS[event][_selected[event]])
      ? _selected[event] : _firstId(event);
  }

  function events() { return Object.keys(VARIANTS); }

  function variants(event) {
    const set = VARIANTS[event] || {};
    return Object.keys(set).map(id => ({ id, label: set[id].label, env: set[id].env }));
  }

  // Friendly headings shown for each event in the chooser.
  const _CHOOSER_LABELS = {
    crit: 'Crit (nat 20)', fumble: 'Fumble (nat 1)', move: 'Move',
    damage: 'Damage', heal: 'Heal', dead: 'Down (0 HP)', mapswitch: 'Map switch',
  };

  // Render an interactive per-event variant chooser into `container`. Builds
  // plain DOM with `sfx-*` class names; clicking a variant selects it
  // (persisted) and auditions it. `opts.labels` overrides the headings.
  function buildChooser(container, opts) {
    if (!container) return;
    const labels = (opts && opts.labels) || _CHOOSER_LABELS;
    container.innerHTML = '';
    events().forEach(event => {
      const sec = document.createElement('div');
      sec.className = 'sfx-event';
      const title = document.createElement('div');
      title.className = 'sfx-event-title';
      title.textContent = labels[event] || event;
      sec.appendChild(title);
      const grid = document.createElement('div');
      grid.className = 'sfx-variants';
      variants(event).forEach(({ id, label, env }) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'sfx-vbtn' + (getSelected(event) === id ? ' sel' : '');
        b.dataset.event = event;
        b.dataset.id = id;
        const nm = document.createElement('span');
        nm.className = 'sfx-vbtn-nm'; nm.textContent = label;
        const en = document.createElement('span');
        en.className = 'sfx-vbtn-env'; en.textContent = env;
        b.appendChild(nm); b.appendChild(en);
        b.addEventListener('click', async () => {
          await enable();            // audition needs audio running
          select(event, id);
          playVariant(event, id);
          grid.querySelectorAll('.sfx-vbtn').forEach(x =>
            x.classList.toggle('sel', x.dataset.id === id));
        });
        grid.appendChild(b);
      });
      sec.appendChild(grid);
      container.appendChild(sec);
    });
  }

  // Self-contained pop-over chooser: a dark overlay holding buildChooser, with
  // its own injected styles so it looks identical on every page (battlemap,
  // character sheet, relay portal). Wire each page's "⚙ Sounds" pill button to
  // call this. Built once, then reused.
  let _overlay = null;
  function _closeChooser() { if (_overlay) _overlay.style.display = 'none'; }
  function openChooser(opts) {
    // Opens regardless of audio state — pick sounds before enabling them;
    // auditioning a variant starts audio on that click. The overlay's critical
    // layout is set INLINE (not via the injected <style>) so it can't fail to
    // appear on the very first open, before the stylesheet has applied.
    if (!_overlay) {
      const css = document.createElement('style');
      css.textContent =
        '.sfx-panel{background:#1c1a14;color:#e8dcc0;border:1px solid #3a3420;border-radius:10px;' +
        'width:100%;max-width:600px;max-height:85vh;overflow:auto;box-shadow:0 10px 34px rgba(0,0,0,.6);' +
        'font-family:system-ui,sans-serif;}' +
        '.sfx-phead{display:flex;align-items:center;justify-content:space-between;gap:12px;' +
        'padding:13px 18px;border-bottom:1px solid #3a3420;position:sticky;top:0;background:#1c1a14;}' +
        '.sfx-phead h3{margin:0;font-size:16px;color:#c9a84c;letter-spacing:.04em;}' +
        '.sfx-pclose{background:none;border:none;color:#c9a84c;font-size:24px;line-height:1;cursor:pointer;}' +
        '.sfx-pbody{padding:16px 18px;}' +
        '.sfx-pbody .sfx-hint{font-size:12px;color:#8a7a5a;font-style:italic;margin-bottom:14px;}' +
        '.sfx-event{margin-bottom:16px;}' +
        '.sfx-event-title{font-size:11px;letter-spacing:.14em;text-transform:uppercase;' +
        'color:#c9a84c;font-weight:700;margin-bottom:7px;}' +
        '.sfx-variants{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}' +
        '@media(max-width:520px){.sfx-variants{grid-template-columns:1fr;}}' +
        '.sfx-vbtn{text-align:left;padding:9px 10px;border-radius:6px;cursor:pointer;background:#26231a;' +
        'border:1px solid #3a3420;color:#e8dcc0;transition:border-color .15s,background .15s;}' +
        '.sfx-vbtn:hover{border-color:#6a5820;}' +
        '.sfx-vbtn.sel{border-color:#c9a84c;background:#2a2510;}' +
        '.sfx-vbtn-nm{display:block;font-size:14px;color:#f0d890;font-weight:600;margin-bottom:2px;}' +
        '.sfx-vbtn-env{display:block;font-size:10.5px;color:#8a7a5a;font-style:italic;line-height:1.35;}';
      document.head.appendChild(css);
      _overlay = document.createElement('div');
      _overlay.style.cssText =
        'position:fixed;inset:0;z-index:100000;display:none;align-items:center;' +
        'justify-content:center;background:rgba(0,0,0,.62);padding:20px;';
      _overlay.innerHTML =
        '<div class="sfx-panel"><div class="sfx-phead"><h3>&#128266; Sound Effects</h3>' +
        '<button type="button" class="sfx-pclose" aria-label="Close">&times;</button></div>' +
        '<div class="sfx-pbody"><div class="sfx-hint"></div><div class="sfx-host"></div></div></div>';
      document.body.appendChild(_overlay);
      _overlay.addEventListener('click', e => { if (e.target === _overlay) _closeChooser(); });
      _overlay.querySelector('.sfx-pclose').addEventListener('click', _closeChooser);
      document.addEventListener('keydown', e => { if (e.key === 'Escape') _closeChooser(); });
    }
    _overlay.querySelector('.sfx-hint').textContent =
      (opts && opts.hint) || 'Tap a variant to hear it and pick it. Saved on this device.';
    buildChooser(_overlay.querySelector('.sfx-host'), opts);
    _overlay.style.display = 'flex';
  }

  function setVolume(x) {
    _volume = Math.max(0, Math.min(1, x));
    try { localStorage.setItem(LS_VOL, String(_volume)); } catch (e) {}
    if (bus) bus.master.gain.rampTo(_masterGain(), 0.05);
  }

  function mute(on) {
    _muted = !!on;
    try { localStorage.setItem(LS_MUTE, _muted ? '1' : '0'); } catch (e) {}
    if (bus) bus.master.gain.rampTo(_masterGain(), 0.05);
  }

  return {
    enable, play, playVariant, select, getSelected, events, variants,
    buildChooser, openChooser, setVolume, mute,
    isEnabled: () => started,
    isMuted:   () => _muted,
    getVolume: () => _volume,
    hasTone:   () => _hasTone(),
    lastError: () => _lastError,
  };
})();

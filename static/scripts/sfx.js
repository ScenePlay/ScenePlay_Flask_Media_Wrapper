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
    // Brass — saw FM through a gentle vibrato: a section of players is never
    // perfectly steady, and that slow shimmer is most of what reads as "brass"
    // rather than "buzzer". (crit fanfare/stab)
    const brass = new Tone.PolySynth(Tone.FMSynth, {
      maxPolyphony: 8, harmonicity: 1, modulationIndex: 5,
      oscillator: { type: 'sawtooth' },
      envelope: { attack: 0.025, decay: 0.1, sustain: 0.7, release: 0.3 },
      modulation: { type: 'square' },
      modulationEnvelope: { attack: 0.02, decay: 0.1, sustain: 0.5, release: 0.2 }
    });
    const brassVib  = new Tone.Vibrato({ frequency: 5.2, depth: 0.06 });
    const brassFilt = new Tone.Filter(3000, 'lowpass');
    brass.connect(brassVib); brassVib.connect(brassFilt); _route(brassFilt, 0.5, 0.25);

    // Slide — MONO brassy FM used for anything with continuous pitch motion
    // (sad-trombone droop, comic up-slip, whoosh body). Mono matters: glides
    // are scheduled directly on its frequency signal.
    const slide = new Tone.FMSynth({
      harmonicity: 1, modulationIndex: 3.5,
      oscillator: { type: 'sawtooth' },
      envelope: { attack: 0.05, decay: 0.05, sustain: 0.85, release: 0.25 },
      modulation: { type: 'square' },
      modulationEnvelope: { attack: 0.05, decay: 0.1, sustain: 0.6, release: 0.2 }
    });
    const slideFilt = new Tone.Filter(1800, 'lowpass');
    slide.connect(slideFilt); _route(slideFilt, 0.42, 0.22);

    // Reed/crumhorn — square FM (fumble blat, dirge)
    const reed = new Tone.PolySynth(Tone.FMSynth, {
      maxPolyphony: 4, harmonicity: 1, modulationIndex: 2.4,
      oscillator: { type: 'square' },
      envelope: { attack: 0.03, decay: 0.06, sustain: 0.8, release: 0.18 },
      modulation: { type: 'square' },
      modulationEnvelope: { attack: 0.03, decay: 0.12, sustain: 0.6, release: 0.18 }
    });
    const reedFilt = new Tone.Filter(2000, 'lowpass');
    reed.connect(reedFilt); _route(reedFilt, 0.4, 0.2);

    // Bell — inharmonic FM. Longer modulation decay = the strike "blooms"
    // before it rings, like a real bell. (crit peal, heal chime, knell)
    const bell = new Tone.PolySynth(Tone.FMSynth, {
      maxPolyphony: 8, harmonicity: 3.01, modulationIndex: 7,
      oscillator: { type: 'sine' },
      envelope: { attack: 0.004, decay: 1.6, sustain: 0, release: 1.4 },
      modulation: { type: 'sine' },
      modulationEnvelope: { attack: 0.004, decay: 0.9, sustain: 0, release: 0.7 }
    });
    _route(bell, 0.35, 0.4);

    // Big drum — a great skin drum (deep membrane, long ring) for the tribal
    // death-drum. Slower pitch decay + more octaves than the damage thud =
    // ceremonial war drum rather than a punch.
    const drum = new Tone.MembraneSynth({
      pitchDecay: 0.09, octaves: 2.5,
      oscillator: { type: 'sine' },
      envelope: { attack: 0.002, decay: 0.65, sustain: 0, release: 0.35 }
    });
    _route(drum, 0.5, 0.2);

    // Shing — bright short metal: the "blade" accent layered into crit hits.
    const shing = new Tone.MetalSynth({
      harmonicity: 5.1, modulationIndex: 22, resonance: 4500, octaves: 1.5,
      envelope: { attack: 0.001, decay: 0.45, release: 0.12 }
    });
    _route(shing, 0.22, 0.3);

    // Harp — POOL of Karplus-Strong plucked strings (PluckSynth is mono and
    // physically modeled; a run of real plucks beats FM approximations).
    const pluck = [];
    for (let i = 0; i < 3; i++) {
      const p = new Tone.PluckSynth({ attackNoise: 0.9, dampening: 3800, resonance: 0.92 });
      _route(p, 0.55, 0.35);
      pluck.push(p);
    }

    // Pad — AM swell; padFilt is exposed so the heal-swell can open it slowly
    // (a filter bloom under a chord is what makes a swell feel like sunrise).
    const pad = new Tone.PolySynth(Tone.AMSynth, {
      maxPolyphony: 5, harmonicity: 1.5,
      oscillator: { type: 'sine' },
      envelope: { attack: 0.5, decay: 0.4, sustain: 0.8, release: 0.9 },
      modulation: { type: 'triangle' },
      modulationEnvelope: { attack: 0.5, decay: 0.3, sustain: 0.6, release: 0.7 }
    });
    const padFilt = new Tone.Filter(1400, 'lowpass');
    pad.connect(padFilt); _route(padFilt, 0.3, 0.4);

    // Footsteps — pool of brown-noise voices (mono NoiseSynth chokes on rapid
    // retriggers), with DIFFERENT filter cutoffs per voice: alternating heavy/
    // light footfalls instead of four identical thumps.
    const step = [];
    [700, 1000, 780, 1100].forEach(cut => {
      const n = new Tone.NoiseSynth({
        noise: { type: 'brown' },
        envelope: { attack: 0.004, decay: 0.08, sustain: 0, release: 0.05 }
      });
      const f = new Tone.Filter(cut, 'lowpass');
      n.connect(f); _route(f, 0.45, 0.08);
      step.push(n);
    });

    // General white noise w/ automatable filter (whoosh, riser, deflate)
    const noise = new Tone.NoiseSynth({
      noise: { type: 'white' },
      envelope: { attack: 0.008, decay: 0.06, sustain: 0.5, release: 0.1 }
    });
    const noiseFilt = new Tone.Filter(2000, 'lowpass');
    noise.connect(noiseFilt); _route(noiseFilt, 0.3, 0.25);

    // Snap — pool of ultra-short highpassed white noise: the TRANSIENT layer.
    // Impacts read as "a hit" because of the first 30ms of snap, not the boom.
    const snap = [];
    for (let i = 0; i < 2; i++) {
      const s = new Tone.NoiseSynth({
        noise: { type: 'white' },
        envelope: { attack: 0.001, decay: 0.04, sustain: 0, release: 0.02 }
      });
      const f = new Tone.Filter(3800, 'highpass');
      s.connect(f); _route(f, 0.4, 0.05);
      snap.push(s);
    }

    // Membrane drum — the BODY layer of impacts (and timpani under fanfares)
    const thud = new Tone.MembraneSynth({
      pitchDecay: 0.06, octaves: 4,
      oscillator: { type: 'sine' },
      envelope: { attack: 0.002, decay: 0.22, sustain: 0, release: 0.1 }
    });
    _route(thud, 0.5, 0.12);

    // Sub — mono sine for drones under death sounds and cinematic pitch-drops
    const sub = new Tone.Synth({
      oscillator: { type: 'sine' },
      envelope: { attack: 0.01, decay: 0.05, sustain: 0.9, release: 0.5 }
    });
    _route(sub, 0.5, 0.1);

    return { brass, slide, reed, bell, drum, shing, pluck, pad, padFilt,
             step, noise, noiseFilt, snap, thud, sub };
  }

  // Schedule a pitch glide on a mono voice: attack at the first point, ramp
  // through the rest, release at the end. pts = [[note, holdSeconds], ...].
  // The held-note micro-droop and the final slide are what discrete notes
  // can't do — this is the engine behind the sad trombone.
  function _glide(voice, pts, vel, dropRatio) {
    const t = Tone.now();
    const F = n => Tone.Frequency(n).toFrequency();
    voice.frequency.cancelScheduledValues(t);
    // A release scheduled by a PREVIOUS glide would choke this retrigger
    // (mono voice) — wipe pending envelope events before attacking again.
    try { voice.envelope.cancel(t); } catch (e) {}
    voice.triggerAttack(pts[0][0], t, vel);
    let at = t;
    pts.forEach(([n, hold], i) => {
      const hz = F(n);
      voice.frequency.setValueAtTime(hz, at);
      // droop each held note slightly flat — the "wah" in wah-wah-wah
      const sag = (i === pts.length - 1 && dropRatio) ? dropRatio : 0.972;
      voice.frequency.exponentialRampToValueAtTime(hz * sag, at + hold * 0.92);
      at += hold;
    });
    voice.triggerRelease(at);
    return at - t;   // total length, for layering follow-ups
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
      fanfare: { label: 'Fanfare', env: 'crescendo arpeggio · chord landing · timpani + sub root', play() {
        const t = Tone.now();
        // Rising three-note pickup that CRESCENDOS into the landing…
        ['G4','C5','E5'].forEach((n,i)=>v.brass.triggerAttackRelease(n,0.16,t+i*0.09,0.5+i*0.09));
        // …then lands on a full chord (notes staggered 8ms — a section, not a
        // keyboard), grounded by a timpani hit and a sub root.
        const land = t + 0.28;
        ['C5','E5','G5'].forEach((n,i)=>v.brass.triggerAttackRelease(n,0.55,land+i*0.008,0.75));
        v.brass.triggerAttackRelease('C6',0.6,land+0.016,0.9);
        v.thud.triggerAttackRelease('C2',0.3,land,0.6);
        v.sub.triggerAttackRelease('C2',0.5,land,0.5);
      }},
      stab: { label: 'Power stab', env: 'chord punch + blade shing + drum — a landed blow', play() {
        const t = Tone.now();
        // Three layers on the same instant: chord (body), metal shing
        // (transient edge), drum (weight). Reads as steel meeting its mark.
        ['C4','G4','C5'].forEach(n=>v.brass.triggerAttackRelease(n,0.28,t,0.7));
        v.shing.triggerAttackRelease('E5',0.3,t,0.55);
        v.thud.triggerAttackRelease('G1',0.22,t,0.65);
        v.brass.triggerAttackRelease('G5',0.5,t+0.12,0.85);
      }},
      peal: { label: 'Bell peal', env: 'overlapping bells · double-struck top · high sparkle', play() {
        const t = Tone.now();
        ['C5','E5','G5'].forEach((n,i)=>v.bell.triggerAttackRelease(n,1.0,t+i*0.09,0.5));
        // real bells get struck twice — once firm, once softer as they ring
        v.bell.triggerAttackRelease('C6',1.2,t+0.27,0.6);
        v.bell.triggerAttackRelease('C6',1.0,t+0.55,0.3);
        v.bell.triggerAttackRelease('E6',0.8,t+0.62,0.22);   // faint sparkle
      }},
    },
    fumble: {
      trombone: { label: 'Sad trombone', env: 'true slide — three drooping wahs, long final fall', play() {
        // A real trombone SLIDES — each "wah" sags flat as it holds, and the
        // last one falls continuously past a fifth. Glides, not steps.
        _glide(v.slide, [['Eb3',0.3],['D3',0.3],['Db3',0.3],['C3',0.9]], 0.7, 0.62);
      }},
      squeak: { label: 'Comic squeak', env: 'up-slip glide… then the splat — a pratfall', play() {
        const t = Tone.now();
        // The slip: a fast rising glide (losing your footing)…
        _glide(v.slide, [['A4',0.09],['E5',0.07]], 0.5);
        // …the beat of airtime… the splat (drum body + snap transient).
        v.thud.triggerAttackRelease('G1',0.22,t+0.3,0.7);
        v.snap[0].triggerAttackRelease(0.05,t+0.3,0.5);
      }},
      dud: { label: 'Dud', env: 'muffled thump + deflating air leak', play() {
        const t = Tone.now();
        v.thud.triggerAttackRelease('G1',0.18,t,0.6);
        v.reed.triggerAttackRelease('D2',0.14,t+0.03,0.4);
        // the deflate: bandpassed air leaking out downward
        v.noiseFilt.frequency.cancelScheduledValues(t);
        v.noiseFilt.frequency.setValueAtTime(1400,t+0.12);
        v.noiseFilt.frequency.exponentialRampToValueAtTime(280,t+0.5);
        v.noise.triggerAttackRelease(0.34,t+0.12,0.22);
      }},
    },
    move: {
      step: { label: 'Footstep', env: 'four steps · uneven gait · heavy/light alternation', play() {
        const t = Tone.now();
        // Each pooled voice has its own filter cutoff (heavy L / light R),
        // and the timing is slightly uneven — a walk, not a metronome.
        const gait = [[0,0.6],[0.26,0.42],[0.50,0.55],[0.78,0.4]];
        gait.forEach(([dt,vel],i)=>v.step[i].triggerAttackRelease(0.08,t+dt,vel));
      }},
      whoosh: { label: 'Cloth whoosh', env: 'air sweep down + faint pitch body underneath', play() {
        const t = _sweep(2600, 420, 0.2);
        v.noise.triggerAttackRelease(0.18, t, 0.25);
        // barely-audible falling tone under the air gives the whoosh direction
        _glide(v.slide, [['G3',0.1],['C3',0.08]], 0.12);
      }},
      tick: { label: 'Soft tick', env: 'single real string pluck · minimal', play() {
        v.pluck[0].triggerAttack('C6', Tone.now());
      }},
    },
    damage: {
      thud: { label: 'Thud', env: 'snap transient + drum body — layered like real foley', play() {
        const t = Tone.now();
        v.snap[0].triggerAttackRelease(0.04, t, 0.5);   // the "hit" edge
        v.thud.triggerAttackRelease('C2', 0.2, t, 0.55); // the weight behind it
      }},
      crunch: { label: 'Crunch', env: 'three cracking bursts down a closing filter + body', play() {
        const t = Tone.now();
        v.thud.triggerAttackRelease('C2',0.18,t,0.5);
        // bone-crunch: rapid noise cracks, each duller than the last
        v.noiseFilt.frequency.cancelScheduledValues(t);
        v.noiseFilt.frequency.setValueAtTime(3200,t);
        v.noiseFilt.frequency.exponentialRampToValueAtTime(700,t+0.16);
        [0,0.05,0.11].forEach((dt,i)=>v.noise.triggerAttackRelease(0.03,t+dt,0.4-i*0.08));
        v.snap[1].triggerAttackRelease(0.04,t,0.45);
      }},
      impact: { label: 'Sub impact', env: 'cinematic pitch-DROP into the chest + drum', play() {
        const t = Tone.now();
        // the drop: a sub tone falling G2 -> C1 in a quarter second
        v.sub.frequency.cancelScheduledValues(t);
        try { v.sub.envelope.cancel(t); } catch (e) {}   // mono retrigger safety
        v.sub.triggerAttack('G2', t, 0.8);
        v.sub.frequency.setValueAtTime(Tone.Frequency('G2').toFrequency(), t);
        v.sub.frequency.exponentialRampToValueAtTime(Tone.Frequency('C1').toFrequency(), t+0.24);
        v.sub.triggerRelease(t+0.32);
        v.thud.triggerAttackRelease('G1',0.26,t,0.7);
      }},
    },
    heal: {
      chime: { label: 'Chime', env: 'two rising bells over a warm pad cushion', play() {
        const t = Tone.now();
        v.pad.triggerAttackRelease('E4', 0.9, t, 0.25);   // warmth underneath
        v.bell.triggerAttackRelease('C5', 0.7, t, 0.5);
        v.bell.triggerAttackRelease('G5', 0.9, t + 0.13, 0.45);
      }},
      shimmer: { label: 'Shimmer', env: 'real plucked-string run + bell sparkle on top', play() {
        const t = Tone.now();
        ['C5','E5','G5','B5','D6'].forEach((n,i)=>
          v.pluck[i % v.pluck.length].triggerAttack(n, t + i*0.055));
        v.bell.triggerAttackRelease('E6', 0.7, t + 0.3, 0.3);  // fairy-dust top
      }},
      swell: { label: 'Warm swell', env: 'chord blooms as the filter slowly OPENS — sunrise', play() {
        const t = Tone.now();
        // the filter opening is the sunrise; the chord alone is just organ
        v.padFilt.frequency.cancelScheduledValues(t);
        v.padFilt.frequency.setValueAtTime(500, t);
        v.padFilt.frequency.exponentialRampToValueAtTime(2600, t + 1.1);
        v.pad.triggerAttackRelease('C4', 1.2, t, 0.4);
        v.pad.triggerAttackRelease('G4', 1.2, t + 0.05, 0.4);
        v.pad.triggerAttackRelease('E5', 1.3, t + 0.1, 0.3);
      }},
    },
    dead: {
      knell: { label: 'Knell', env: 'church bell struck twice over a fading sub drone', play() {
        const t = Tone.now();
        v.sub.triggerAttackRelease('C2', 3.5, t, 0.45);        // the dread under it
        v.bell.triggerAttackRelease('C3', 4.0, t, 0.95);
        v.bell.triggerAttackRelease('C3', 3.0, t + 1.15, 0.5); // second, softer toll
      }},
      gong: { label: 'Tribal drum', env: 'deep war drum · a slowing, fading heartbeat', play() {
        const t = Tone.now();
        // A dying heartbeat on a great skin drum: each strike later and
        // softer than the last. Skin-slap layer (pooled noise) on each hit.
        [[0, 0.9], [0.5, 0.68], [1.08, 0.48], [1.8, 0.3]].forEach(([dt, vel], i) => {
          v.drum.triggerAttackRelease('G1', 0.4, t + dt, vel);
          v.step[i % v.step.length].triggerAttackRelease(0.05, t + dt, vel * 0.45);
        });
      }},
      dirge: { label: 'Dirge', env: 'three falling reeds over a held low drone', play() {
        const t = Tone.now();
        v.sub.triggerAttackRelease('C2', 1.9, t, 0.3);
        ['G3','Eb3','C3'].forEach((n,i)=>v.reed.triggerAttackRelease(n,0.7,t+i*0.34,0.6));
      }},
    },
    mapswitch: {
      riser: { label: 'Riser', env: 'air sweep + rushing pluck climb + arrival bell', play() {
        const t = _sweep(400, 4200, 0.3);
        v.noise.triggerAttackRelease(0.28, t, 0.32);
        // pluck run rushes upward THROUGH the sweep, arrival ding on top
        ['C4','E4','G4','C5','E5','G5'].forEach((n,i)=>
          v.pluck[i % v.pluck.length].triggerAttack(n, t + i*0.045));
        v.bell.triggerAttackRelease('C6', 0.7, t + 0.32, 0.45);
      }},
      gliss: { label: 'Harp gliss', env: 'real plucked-string climb · gentle bell top', play() {
        const t = Tone.now();
        ['C4','E4','G4','C5','E5','G5','C6'].forEach((n,i)=>
          v.pluck[i % v.pluck.length].triggerAttack(n, t + i*0.05));
        v.bell.triggerAttackRelease('E6', 0.6, t + 0.4, 0.25);
      }},
      chimeup: { label: 'Whoosh + ding', env: 'air sweep up · two-note arrival chime', play() {
        const t = _sweep(500, 3600, 0.2);
        v.noise.triggerAttackRelease(0.2, t, 0.3);
        v.bell.triggerAttackRelease('C6', 0.7, t + 0.21, 0.5);
        v.bell.triggerAttackRelease('G6', 0.6, t + 0.29, 0.28);
      }},
    },
  };

  // Default variant per event — what plays when the user hasn't picked one
  // in the ⚙ Sounds chooser. Complete on purpose: every event's table default
  // is explicit here, immune to registry reordering.
  const _DEFAULTS = {
    crit:      'fanfare',
    fumble:    'dud',
    move:      'step',
    damage:    'crunch',
    heal:      'swell',
    dead:      'knell',
    mapswitch: 'chimeup',
  };

  const _firstId = (event) => {
    const set = VARIANTS[event] || {};
    const d = _DEFAULTS[event];
    return (d && set[d]) ? d : Object.keys(set)[0];
  };

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
      // Themed via the page's --sp-* palette (both local and relay define these),
      // with the original dark values as fallbacks so it still looks right if a
      // page has no theme vars.
      css.textContent =
        '.sfx-panel{background:var(--sp-surface,#1c1a14);color:var(--sp-text,#e8dcc0);' +
        'border:1px solid var(--sp-border,#3a3420);border-radius:10px;' +
        'width:100%;max-width:600px;max-height:85vh;overflow:auto;box-shadow:0 10px 34px rgba(0,0,0,.5);' +
        'font-family:system-ui,sans-serif;}' +
        '.sfx-phead{display:flex;align-items:center;justify-content:space-between;gap:12px;' +
        'padding:13px 18px;border-bottom:1px solid var(--sp-border,#3a3420);position:sticky;top:0;' +
        'background:var(--sp-surface,#1c1a14);}' +
        '.sfx-phead h3{margin:0;font-size:16px;color:var(--sp-accent,#c9a84c);letter-spacing:.04em;}' +
        '.sfx-pclose{background:none;border:none;color:var(--sp-accent,#c9a84c);font-size:24px;line-height:1;cursor:pointer;}' +
        '.sfx-pbody{padding:16px 18px;}' +
        '.sfx-pbody .sfx-hint{font-size:12px;color:var(--sp-muted,#8a7a5a);font-style:italic;margin-bottom:14px;}' +
        '.sfx-event{margin-bottom:16px;}' +
        '.sfx-event-title{font-size:11px;letter-spacing:.14em;text-transform:uppercase;' +
        'color:var(--sp-accent,#c9a84c);font-weight:700;margin-bottom:7px;}' +
        '.sfx-variants{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}' +
        '@media(max-width:520px){.sfx-variants{grid-template-columns:1fr;}}' +
        '.sfx-vbtn{text-align:left;padding:9px 10px;border-radius:6px;cursor:pointer;' +
        'background:var(--sp-bg,#26231a);border:1px solid var(--sp-border,#3a3420);color:var(--sp-text,#e8dcc0);' +
        'transition:border-color .15s,background .15s;}' +
        '.sfx-vbtn:hover{border-color:var(--sp-accent,#6a5820);}' +
        '.sfx-vbtn.sel{border-color:var(--sp-accent,#c9a84c);background:var(--sp-accent-glow,#2a2510);}' +
        '.sfx-vbtn-nm{display:block;font-size:14px;color:var(--sp-text,#f0d890);font-weight:600;margin-bottom:2px;}' +
        '.sfx-vbtn-env{display:block;font-size:10.5px;color:var(--sp-muted,#8a7a5a);font-style:italic;line-height:1.35;}';
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

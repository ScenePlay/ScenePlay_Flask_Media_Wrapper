/* static/scripts/dice.js
   Shared dice-roll core — the single home for roll algebra that previously
   existed four times (portal doRoll + fdDoRoll, battlemap, character sheet).

   Source of truth lives in the LOCAL repo (static/scripts/dice.js); it is
   copied into the relay portal by scripts/sync_shared_assets.sh. Pure logic
   only — no DOM, no fetch — so each UI keeps its own rendering. ONE
   exception: renderQuickLabels(), so the quick-label set stays identical
   across every roller (sheet, battlemap, portal) by editing QUICK_LABELS.

   API:
     DiceCore.QUICK_LABELS              -> ['Initiative', 'Attack', ...]
     DiceCore.renderQuickLabels(container, input, btnClass)
         -> fills `container` with one button per label; clicking puts the
            label text into `input`. btnClass styles per-app.
     DiceCore.roll(count, sides, modifier, mode)
         -> { rolls, keptRolls, droppedRolls, total, sides, count, modifier, mode }
            mode: 'normal' | 'advantage' | 'disadvantage' (adv/dis apply to d20
            only; anything else is coerced to normal). For adv/dis the kept die
            is always FIRST in `rolls`.
     DiceCore.expr(result, label)        -> "2d20+3 [advantage] Attack"
     DiceCore.breakdown(result)          -> "14, 7+3"
     DiceCore.critFumble(result)         -> 'crit' | 'fumble' | null
     DiceCore.critFumbleFromRecord(rec)  -> same, from a server/feed roll record
                                            ({expression|roll_expr, adv_mode, dice[]})
     DiceCore.rand(sides)                -> 1..sides

   Game systems (mirrors dice_systems.py in the local repo — keep in step):
     DiceCore.SYSTEMS                    -> { dnd5e: {...}, dcc: {...} }
     DiceCore.setSystem(game) / getSystem()
         -> game = { id, name, settings } as served by /ttrpg/dice/system and
            the portal's session_state.game. Default: D&D 5e.
     DiceCore.statMod(systemId, score)   -> stat modifier under that system
     DiceCore.difficulty(kind, floor, oppMod, mobMode, base) -> DCC target #
     DiceCore.rankDamage(rank)           -> 'plus 1d4' style text (Table 37)
     DiceCore.evaluate(systemId, sides, natural, total, rollType, difficulty,
                       floor, rank) -> { degree, ok, margin, text }
     DiceCore.annotateLabel(label, outcome, difficulty) -> "Attack vs 17 → Hit"
     DiceCore.mountSystemPanel(container, opts)
         -> plain-language controls for the current system (what are you
            rolling, target number, untrained, crit damage, rank-up). Returns
            { getContext(), refresh(game), reset() }. getContext() gives the
            fields to send with / evaluate a roll:
            { roll_type, difficulty, floor, rank, untrained, crit }.
            opts.collapsible: true adds a fold caret to the panel header so a
            crawler can tuck the target-number helper away (remembered per
            browser in localStorage).
     DiceCore.parseDice(text)            -> { count, sides, mod } | null
                                            ("2d4+2 healing" -> 2, 4, 2)
     DiceCore.hotlistPreset(item)        -> what a Hotlist chip loads into a
                                            roller: { label, count?, sides?,
                                            mod?, rollType? }. Items whose
                                            notes name dice ("2d6 fire") load
                                            those as a damage roll; anything
                                            else just labels the roll.
     DiceCore.collapseText(info, nowSec) -> { text, state } for the DCC
                                            level-collapse banner (info =
                                            {floor, at, note} from settings)
     DiceCore.bindCollapsibles(root, prefix)
         -> every `.qref-row[data-qref]` (and `.sp-collapsible[data-qref]`)
            under `root` gets a fold toggle on its label; state persists in
            localStorage under `sp.dice.collapse.<prefix>.<key>`. Re-run after
            re-rendering the rows — safe to call repeatedly.
*/
window.DiceCore = (function () {
  'use strict';

  const rand = sides => Math.floor(Math.random() * sides) + 1;

  function roll(count, sides, modifier, mode) {
    count    = Math.max(1, Math.min(20, parseInt(count, 10) || 1));
    modifier = parseInt(modifier, 10) || 0;
    let rolls, keptRolls, droppedRolls;
    if (sides === 20 && (mode === 'advantage' || mode === 'disadvantage')) {
      const r1 = rand(20), r2 = rand(20);
      const hi = Math.max(r1, r2), lo = Math.min(r1, r2);
      keptRolls    = [mode === 'advantage' ? hi : lo];
      droppedRolls = [mode === 'advantage' ? lo : hi];
      rolls        = [keptRolls[0], droppedRolls[0]];   // kept die first
    } else {
      mode = 'normal';
      rolls = Array.from({ length: count }, () => rand(sides));
      keptRolls = rolls.slice();
      droppedRolls = [];
    }
    const total = keptRolls.reduce((a, b) => a + b, 0) + modifier;
    return { rolls, keptRolls, droppedRolls, total, sides, count, modifier, mode };
  }

  function _modTag(modifier) {
    return modifier !== 0 ? (modifier > 0 ? '+' : '') + modifier : '';
  }

  function expr(r, label) {
    // A URL is never a meaningful roll label. Phone browsers autofill the
    // portal's address into the bare label input, and every roll then read
    // "d20 http://<the server's ip>" in the feed — drop URL-shaped labels.
    if (label && /^https?:\/\/\S*$/i.test(String(label).trim())) label = '';
    const modeTag = r.mode !== 'normal' ? ` [${r.mode}]` : '';
    const countTag = (r.count > 1 || r.mode !== 'normal') ? r.count : '';
    return `${countTag}d${r.sides}${_modTag(r.modifier)}${modeTag}${label ? ' ' + label : ''}`;
  }

  function breakdown(r) {
    return r.rolls.join(', ') + _modTag(r.modifier);
  }

  // d20 only; adv/dis judged on the kept die.
  function critFumble(r) {
    if (r.sides !== 20 || r.keptRolls.length !== 1) return null;
    if (r.keptRolls[0] === 20) return 'crit';
    if (r.keptRolls[0] === 1)  return 'fumble';
    return null;
  }

  // Same decision from a server/feed roll record:
  // { expression|roll_expr, adv_mode?, dice: [..] }
  function critFumbleFromRecord(rec) {
    const e = rec.expression || rec.roll_expr || '';
    const m = e.match(/d(\d+)/i);
    if (!m || parseInt(m[1], 10) !== 20) return null;
    const dice = rec.dice || [];
    if (!dice.length) return null;
    let val;
    if (rec.adv_mode === 'advantage')         val = Math.max.apply(null, dice);
    else if (rec.adv_mode === 'disadvantage') val = Math.min.apply(null, dice);
    else                                      val = dice.length === 1 ? dice[0] : null;
    if (val === 20) return 'crit';
    if (val === 1)  return 'fumble';
    return null;
  }

  // ── Game systems ──────────────────────────────────────────────────────────
  // Mirrors dice_systems.py (the server evaluates local rolls; the portal
  // rolls client-side with this copy). `quick` entries with dice are one-tap
  // presets; plain strings only fill the label box.
  const SYSTEMS = {
    dnd5e: {
      id: 'dnd5e', name: 'D&D 5e',
      // d20 rolls set the die; Damage leaves whatever dice are chosen.
      quick: [{ label: 'Initiative', sides: 20, count: 1 }, { label: 'Attack', sides: 20, count: 1 }, { label: 'Damage', rollType: 'damage' },
              { label: 'Saving Throw', sides: 20, count: 1 }, { label: 'Perception', sides: 20, count: 1 },
              { label: 'Stealth', sides: 20, count: 1 }, { label: 'Insight', sides: 20, count: 1 }],
      rollTypes: [['check', 'Ability / Skill Check'], ['attack', 'Attack'],
                  ['save', 'Saving Throw'], ['damage', 'Damage'],
                  ['other', 'Something else']],
    },
    dcc: {
      id: 'dcc', name: 'Dungeon Crawler Carl',
      // Each chip picks the dice AND tells the panel what kind of roll it is.
      quick: [
        { label: 'Skill Check', sides: 20, count: 1, rollType: 'check' },
        { label: 'Attack',      sides: 20, count: 1, rollType: 'attack' },
        { label: 'Evade',       sides: 20, count: 1, rollType: 'evade' },
        { label: 'Stat Check',  sides: 20, count: 1, rollType: 'stat' },
        { label: 'Damage',      rollType: 'damage' },
        { label: 'Rank-Up',     sides: 20, count: 1, rollType: 'rankup' },
        { label: 'Help (trained)',   count: 1, sides: 6, rollType: 'other' },
        { label: 'Help (untrained)', count: 1, sides: 2, rollType: 'other' },
        { label: 'Intervene',        count: 1, sides: 6, rollType: 'other' },
        { label: 'Call a Play (keep highest)', count: 2, sides: 6, rollType: 'other' },
        { label: 'Scatter direction', count: 1, sides: 8, rollType: 'other' },
      ],
      rollTypes: [['check', 'Skill Check'], ['attack', 'Attack'],
                  ['evade', 'Evade (dodge an attack)'],
                  ['stat', 'Stat Check (resist something)'],
                  ['damage', 'Damage'], ['rankup', 'Skill Rank-Up Check'],
                  ['other', 'Something else']],
    },
  };
  const DEFAULT_SYSTEM = 'dnd5e';
  let _game = { id: DEFAULT_SYSTEM, name: SYSTEMS.dnd5e.name, settings: {} };

  function setSystem(game) {
    const id = game && SYSTEMS[game.id] ? game.id : DEFAULT_SYSTEM;
    _game = { id, name: SYSTEMS[id].name, settings: (game && game.settings) || {} };
    return _game;
  }
  function getSystem() { return _game; }

  // Table 2 (p.57): DCC stat modifiers are NOT (score-10)/2.
  const _DCC_MOD_TABLE = [[1, 1], [3, 2], [6, 3], [10, 4], [20, 5], [50, 6],
                          [100, 7], [150, 8], [200, 9], [300, 10]];
  function statMod(systemId, score) {
    score = parseInt(score, 10);
    if (isNaN(score)) score = systemId === 'dcc' ? 3 : 10;
    if (systemId === 'dcc') {
      let mod = 1;
      _DCC_MOD_TABLE.forEach(([floorScore, m]) => { if (score >= floorScore) mod = m; });
      return mod;
    }
    return Math.floor((score - 10) / 2);
  }

  // Difficulty (p.59-60): unopposed 10+2F, opposed 10+mod+F, stat 10+F,
  // mob = printed number + F, number = as typed. Mob Adv/Disadv = ±5.
  function difficulty(kind, floor, oppMod, mobMode, base) {
    floor = Math.max(0, parseInt(floor, 10) || 0);
    oppMod = parseInt(oppMod, 10) || 0;
    base = parseInt(base, 10) || 0;
    let d;
    if (kind === 'unopposed')     d = 10 + floor * 2;
    else if (kind === 'opposed')  d = 10 + oppMod + floor;
    else if (kind === 'stat')     d = 10 + floor;
    else if (kind === 'mob')      d = base + floor;
    else                          d = base;
    if (mobMode === 'advantage')         d += 5;
    else if (mobMode === 'disadvantage') d -= 5;
    return d;
  }

  // Table 37 (p.176): bonus damage per Skill Rank, as words.
  function rankDamage(rank) {
    const r = Math.max(0, parseInt(rank, 10) || 0);
    if (r === 0)  return 'no bonus';
    if (r === 1)  return '+1';
    if (r <= 3)   return '+1d2';
    if (r <= 5)   return '+1d4';
    if (r <= 7)   return '+1d6';
    if (r <= 9)   return '+1d8';
    if (r <= 11)  return '+1d10';
    if (r <= 13)  return '+1d12';
    if (r <= 15)  return '+1d8 and +1d6';
    if (r <= 17)  return '+2d8';
    if (r <= 19)  return '+1d10 and +1d8';
    return '+2d10';
  }

  function _degree(natural, margin) {
    if (natural === 20) return 'crit';
    if (natural === 1)  return 'crit_fail';
    if (margin >= 10)   return 'amazing';
    if (margin >= 0)    return 'success';
    if (margin >= -2)   return 'near_miss';
    if (margin >= -9)   return 'fail';
    return 'major_fail';
  }

  const _DCC_TEXT = {
    check: {
      crit:       'Critical Hit — the best possible result',
      amazing:    'Amazing Success',
      success:    'Success',
      near_miss:  'Near Miss — an ally may Intervene (1d6)',
      fail:       'Fail',
      major_fail: 'Major Fail — expect a consequence',
      crit_fail:  'Critical Fail!',
    },
    attack: {
      crit:       'CRITICAL HIT — roll DOUBLE base damage dice',
      amazing:    'Amazing Success — hit, +{F} bonus damage',
      success:    'Hit',
      near_miss:  'Near Miss — an ally may Intervene (1d6)',
      fail:       'Miss',
      major_fail: 'Major Fail — miss, plus a consequence (dropped weapon, lost footing…)',
      crit_fail:  'Critical Fail — worst outcome (hit an ally, break a weapon…)',
    },
    evade: {
      crit:       'Evaded! Advantage on your next attack vs this Mob',
      amazing:    'Evaded with style — Advantage on your next attack vs this Mob',
      success:    'Evaded',
      near_miss:  'Near Miss — you are hit; an ally may Intervene (1d6)',
      fail:       'Hit',
      major_fail: 'Major Fail — hit, +{F} extra damage, Minor Injury after combat',
      crit_fail:  'Critical Fail — DOUBLE damage, Major Injury after combat',
    },
  };
  _DCC_TEXT.stat = _DCC_TEXT.check;

  // What a finished roll means. natural = the kept d20 (or null).
  function evaluate(systemId, sides, natural, total, rollType, diff, floor, rank) {
    const out = { degree: null, ok: null, margin: null, text: '' };
    diff = (diff === null || diff === undefined || diff === '') ? null : parseInt(diff, 10);
    if (diff !== null && isNaN(diff)) diff = null;
    floor = Math.max(0, parseInt(floor, 10) || 0);
    const isD20 = sides === 20 && natural !== null && natural !== undefined;

    if (systemId === 'dcc') {
      if (rollType === 'rankup' && isD20) {
        rank = parseInt(rank, 10);
        if (isNaN(rank)) return out;
        const ok = natural >= rank;
        out.degree = ok ? 'success' : 'fail'; out.ok = ok; out.margin = natural - rank;
        out.text = ok ? `Rank up! Skill goes to Rank ${Math.min(rank + 1, 15)}`
                      : `No rank-up (needed ${rank}+ on the die)`;
        return out;
      }
      if (!isD20 || diff === null) {
        if (isD20 && natural === 20) { out.degree = 'crit'; out.ok = true; out.text = 'Natural 20 — Critical Hit!'; }
        else if (isD20 && natural === 1) { out.degree = 'crit_fail'; out.ok = false; out.text = 'Natural 1 — Critical Fail!'; }
        return out;
      }
      const margin = total - diff;
      const deg = _degree(natural, margin);
      const texts = _DCC_TEXT[rollType] || _DCC_TEXT.check;
      out.degree = deg; out.margin = margin;
      out.ok = deg === 'crit' || deg === 'amazing' || deg === 'success';
      out.text = texts[deg].replace('{F}', String(floor));
      return out;
    }

    if (!isD20) return out;
    if (natural === 20)     { out.degree = 'crit'; out.ok = true; out.text = 'Natural 20!'; }
    else if (natural === 1) { out.degree = 'crit_fail'; out.ok = false; out.text = 'Natural 1!'; }
    if (diff !== null) {
      const margin = total - diff;
      const ok = (natural !== 1 && natural !== 20) ? margin >= 0 : out.ok;
      out.margin = margin; out.ok = ok;
      const word = ok ? 'Success' : 'Fail';
      out.text = out.text ? out.text + ' — ' + word : word;
      out.degree = out.degree || (ok ? 'success' : 'fail');
    }
    return out;
  }

  function annotateLabel(label, outcome, diff) {
    label = (label || '').trim();
    if (!outcome || !outcome.text) return label;
    const vs = (diff === null || diff === undefined || diff === '') ? '' : ` vs ${diff}`;
    const head = label ? label + vs : vs.trim();
    return head ? `${head} → ${outcome.text}` : outcome.text;
  }

  // Quick-label chips for the CURRENT system. Highest-frequency roll types
  // only. Presets (DCC Help/Intervene/…) also set the dice when the roller
  // passes an applyPreset({count, sides}) callback.
  function renderQuickLabels(container, input, btnClass, applyPreset) {
    container.innerHTML = '';
    SYSTEMS[_game.id].quick.forEach(q => {
      const preset = typeof q === 'object' ? q : null;
      const name = preset ? preset.label : q;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = btnClass;
      b.style.cssText = 'font-size:.72rem;padding:2px 8px;';
      b.textContent = name;
      if (preset && preset.sides) b.title = `Sets the dice to ${preset.count || 1}d${preset.sides}`;
      b.onclick = () => {
        input.value = name;
        if (preset && applyPreset) applyPreset(preset);
      };
      container.appendChild(b);
    });
  }
  // Kept for older callers: the 5e list.
  const QUICK_LABELS = SYSTEMS.dnd5e.quick.slice();

  // "2d6", "2d4+2 healing", "1d8 -1" -> { count, sides, mod }; null when the
  // text names no dice.
  function parseDice(text) {
    const m = String(text || '').match(/(\d+)\s*d\s*(\d+)\s*([+-]\s*\d+)?/i);
    if (!m) return null;
    return { count: parseInt(m[1], 10), sides: parseInt(m[2], 10),
             mod: m[3] ? parseInt(m[3].replace(/\s+/g, ''), 10) : 0 };
  }

  // A crawler's 10-slot Hotlist in the roller: the item's notes are the only
  // free text it has, so dice written there ("2d6 fire", "heals 2d4+2") make
  // the chip load a damage roll; a plain item just labels the next roll so the
  // feed shows what was used.
  function hotlistPreset(item) {
    item = item || {};
    const name = String(item.name || item.item_name || 'Item');
    const d = parseDice(item.notes);
    if (!d) return { label: name };
    return { label: name, count: d.count, sides: d.sides, mod: d.mod, rollType: 'damage' };
  }

  // ── DCC level collapse banner ────────────────────────────────────────────
  // info = {floor, at (epoch s, 0 = none), note} from the session settings.
  // Returns { text, state } — state: 'none' | 'note' | 'countdown' | 'warn'
  // (under 5 min) | 'down' (time's up). One formatter so the local map, the
  // portal and the OBS source (which carries a copy) read identically.
  function collapseText(info, nowSec) {
    if (!info) return { text: '', state: 'none' };
    const at = parseInt(info.at, 10) || 0, note = String(info.note || '').trim();
    if (!at) return note ? { text: '\u23F1 Level collapse \u2014 ' + note, state: 'note' } : { text: '', state: 'none' };
    const now = nowSec != null ? nowSec : Math.floor(Date.now() / 1000);
    const rem = at - now;
    if (rem <= 0) return { text: '\uD83D\uDCA5 LEVEL COLLAPSED' + (note ? ' \u2014 ' + note : ''), state: 'down' };
    const days = Math.floor(rem / 86400), h = Math.floor((rem % 86400) / 3600),
          m = Math.floor((rem % 3600) / 60), sec = rem % 60;
    const pad = n => (n < 10 ? '0' : '') + n;
    // "2d 03:14:05" past a day, "1:02:05" under one, "7:30" under an hour
    const clock = days ? days + 'd ' + pad(h) + ':' + pad(m) + ':' + pad(sec)
                : (h ? h + ':' + pad(m) : String(m)) + ':' + pad(sec);
    return { text: '\u26A0 LEVEL COLLAPSE IN ' + clock + (note ? ' \u2014 ' + note : ''),
             state: rem < 300 ? 'warn' : 'countdown' };
  }

  // ── Collapsible sections ─────────────────────────────────────────────────
  // The DCC roller grew tall (target-number helper + Skills/Weapons/Hotlist
  // rows). Any `.qref-row[data-qref]` gets a fold toggle on its label; the
  // choice sticks per browser so a phone at the table stays tidy.
  const _COLLAPSE_NS = 'sp.dice.collapse.';
  function _collapseGet(key) {
    try { return localStorage.getItem(_COLLAPSE_NS + key) === '1'; } catch (e) { return false; }
  }
  function _collapseSet(key, on) {
    try { localStorage.setItem(_COLLAPSE_NS + key, on ? '1' : '0'); } catch (e) { /* private mode */ }
  }
  function _ensureCollapseCss() {
    if (document.getElementById('sp-dice-collapse-css')) return;
    const st = document.createElement('style');
    st.id = 'sp-dice-collapse-css';
    st.textContent =
      '.qref-row.sp-can-collapse .qref-label{cursor:pointer;user-select:none;white-space:nowrap;}' +
      '.qref-row.sp-can-collapse .qref-label::before{content:"\\25BE";display:inline-block;width:.9em;font-size:.8em;opacity:.7;}' +
      '.qref-row.sp-collapsed .qref-label::before{content:"\\25B8";}' +
      '.qref-row.sp-collapsed .qref-chips{display:none;}' +
      '.qref-row .sp-collapse-count{opacity:.6;margin-left:2px;}' +
      '.qref-row.sp-can-collapse .qref-label:hover{color:var(--ttrpg-accent,var(--accent,inherit));}' +
      '.qref-use{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;margin-left:-3px;padding:0 4px;border:1px solid var(--sp-border,var(--border,#888));border-left:none;border-radius:0 10px 10px 0;background:transparent;color:inherit;font-size:.68rem;line-height:1;cursor:pointer;opacity:.75;}' +
      '.qref-use:hover{opacity:1;color:var(--ttrpg-accent,var(--accent,inherit));border-color:var(--ttrpg-accent,var(--accent,inherit));}' +
      '.qref-chip.qref-has-use{border-top-right-radius:0;border-bottom-right-radius:0;}' +
      '.sp-syspanel-fold{background:none;border:none;color:inherit;cursor:pointer;padding:0 4px;font-size:.9em;line-height:1;opacity:.75;}' +
      '.sp-syspanel-fold:hover{opacity:1;}';
    document.head.appendChild(st);
  }
  function _applyCollapse(row, key, on) {
    row.classList.toggle('sp-collapsed', on);
    const lbl = row.querySelector('.qref-label');
    if (!lbl) return;
    let cnt = lbl.querySelector('.sp-collapse-count');
    if (on) {
      const n = row.querySelectorAll('.qref-chip').length;
      if (!cnt) { cnt = document.createElement('span'); cnt.className = 'sp-collapse-count'; lbl.appendChild(cnt); }
      cnt.textContent = n ? '(' + n + ')' : '';
    } else if (cnt) cnt.remove();
    lbl.setAttribute('aria-expanded', on ? 'false' : 'true');
    lbl.title = (on ? 'Show ' : 'Hide ') + (lbl.dataset.spName || 'section');
    void key;
  }
  function bindCollapsibles(root, prefix) {
    if (!root) return;
    _ensureCollapseCss();
    prefix = prefix ? prefix + '.' : '';
    root.querySelectorAll('.qref-row[data-qref]').forEach(row => {
      const key = prefix + row.dataset.qref;
      const lbl = row.querySelector('.qref-label');
      if (!lbl) return;
      if (!row.classList.contains('sp-can-collapse')) {
        row.classList.add('sp-can-collapse');
        lbl.dataset.spName = lbl.textContent.trim();
        lbl.setAttribute('role', 'button');
        lbl.tabIndex = 0;
        const toggle = () => { const on = !row.classList.contains('sp-collapsed'); _collapseSet(key, on); _applyCollapse(row, key, on); };
        lbl.addEventListener('click', toggle);
        lbl.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
      }
      _applyCollapse(row, key, _collapseGet(key));
    });
  }

  // ── System panel (DOM) ────────────────────────────────────────────────────
  // One shared UI so every roller explains the rules the same way. Written for
  // people who don't want to learn formulas: pick what you're rolling, say who
  // or what is in the way, and the panel works out the number to beat.
  //
  // opts: { btnClass, selectClass, inputClass, setDie(sides), setCount(n),
  //         getCount(), setMod(n), setAdv(mode), quickContainer, labelInput,
  //         onChange(ctx), getDamageDice() -> {count, sides, mod, label} | null
  //         (the ready weapon's damage, so the Damage chip loads real dice) }
  const _TARGET_KINDS = {
    unopposed: 'Nobody is in the way (10 + Floor × 2)',
    opposed:   'A Mob or person is resisting (10 + their Stat Mod + Floor)',
    stat:      'Stat Check (10 + Floor)',
    mob:       "Use the Mob's printed number (the part before +F)",
    number:    'I know the number',
    none:      'No target — just roll the dice',
  };
  const _DEFAULT_KIND = { check: 'unopposed', attack: 'mob', evade: 'mob', stat: 'stat' };
  const _PANEL_KEY = 'syspanel';   // localStorage key for the folded helper

  function mountSystemPanel(container, opts) {
    opts = opts || {};
    const state = { rollType: 'check', kind: null, oppMod: 4, base: 14,
                    mobMode: 'normal', number: 15, untrained: false, crit: false,
                    rank: 1, baseCount: null };
    const esc = t => String(t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const selCls = opts.selectClass || 'form-select form-select-sm';
    const inCls  = opts.inputClass  || 'form-control form-control-sm';
    const sel = (id, options, value, extra) =>
      `<select id="${id}" class="${selCls} sp-syspanel-in" ${extra || ''}>` +
      options.map(([v, t]) => `<option value="${v}"${String(v) === String(value) ? ' selected' : ''}>${esc(t)}</option>`).join('') +
      '</select>';
    const num = (id, value, min, max, w) =>
      `<input type="number" id="${id}" class="${inCls} sp-syspanel-in" value="${value}" min="${min}" max="${max}" style="width:${w || 70}px;">`;

    function floor() { return parseInt(_game.settings.floor, 10) || 0; }

    function currentDifficulty() {
      const rt = state.rollType;
      if (!['check', 'attack', 'evade', 'stat'].includes(rt)) return null;
      const kind = state.kind || _DEFAULT_KIND[rt];
      if (kind === 'none') return null;
      return difficulty(kind, floor(), state.oppMod, state.mobMode, kind === 'mob' ? state.base : state.number);
    }

    function render() {
      if (_game.id !== 'dcc') {   // 5e: the classic roller, nothing extra
        container.innerHTML = '';
        container.style.display = 'none';
        return;
      }
      container.style.display = '';
      const rt = state.rollType;
      const kind = state.kind || _DEFAULT_KIND[rt] || 'none';
      const isCheck = ['check', 'attack', 'evade', 'stat'].includes(rt);
      const folded = !!opts.collapsible && _collapseGet(_PANEL_KEY);
      if (opts.collapsible) _ensureCollapseCss();
      let h = `<div class="sp-syspanel" style="border:1px dashed var(--ttrpg-accent,#888);border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:.82rem;">`;
      h += `<div class="d-flex justify-content-between align-items-center${folded ? '' : ' mb-1'}" style="gap:8px;">` +
           `<strong>${opts.collapsible ? `<button type="button" class="sp-syspanel-fold" id="sp-fold" title="${folded ? 'Show' : 'Hide'} the target-number helper" aria-expanded="${folded ? 'false' : 'true'}">${folded ? '&#9656;' : '&#9662;'}</button>` : ''}${esc(_game.name)}</strong>` +
           `<span class="small" title="The DM sets the Floor on the session page">Floor <b>${floor()}</b></span></div>`;
      h += `<div class="sp-syspanel-body"${folded ? ' style="display:none;"' : ''}>`;
      h += `<label class="small mb-0">What are you rolling?</label>` +
           sel('sp-rt', SYSTEMS.dcc.rollTypes, rt);
      if (isCheck) {
        h += `<label class="small mb-0 mt-1">Who or what is in the way?</label>` +
             sel('sp-kind', Object.entries(_TARGET_KINDS), kind);
        if (kind === 'opposed') {
          h += `<div class="d-flex align-items-center gap-2 mt-1"><span class="small">Their Stat Mod</span>${num('sp-opp', state.oppMod, 0, 10)}</div>`;
        } else if (kind === 'mob') {
          h += `<div class="d-flex align-items-center gap-2 mt-1"><span class="small">Mob's number (e.g. the 14 in "14+F")</span>${num('sp-base', state.base, 0, 60)}</div>`;
        } else if (kind === 'number') {
          h += `<div class="d-flex align-items-center gap-2 mt-1"><span class="small">Number to beat</span>${num('sp-number', state.number, 1, 99)}</div>`;
        }
        if (kind === 'opposed' || kind === 'mob') {
          h += `<label class="small mb-0 mt-1">Does the Mob have an edge?</label>` +
               sel('sp-mobmode', [['normal', 'No — normal'], ['advantage', 'Mob has Advantage (+5 to beat)'], ['disadvantage', 'Mob has Disadvantage (−5 to beat)']], state.mobMode);
        }
        if (rt !== 'stat') {
          h += `<div class="form-check mt-1"><input class="form-check-input sp-syspanel-in" type="checkbox" id="sp-untrained"${state.untrained ? ' checked' : ''}>` +
               `<label class="form-check-label small" for="sp-untrained">I'm untrained in this (rolls with Disadvantage)</label></div>`;
        }
        const d = currentDifficulty();
        h += `<div class="mt-1" style="font-weight:600;">` +
             (d === null ? 'No target number — the roll will just show the total.'
                         : `Number to beat: <span style="color:var(--ttrpg-accent);font-size:1rem;">${d}</span> <span class="small fw-normal">(d20 + your mod; ties succeed)</span>`) +
             `</div>`;
      } else if (rt === 'damage') {
        h += `<div class="form-check mt-1"><input class="form-check-input sp-syspanel-in" type="checkbox" id="sp-crit"${state.crit ? ' checked' : ''}>` +
             `<label class="form-check-label small" for="sp-crit">Critical hit — double the dice</label></div>`;
        h += `<div class="d-flex align-items-center gap-2 mt-1"><span class="small">Skill Rank</span>${num('sp-rank', state.rank, 0, 20, 60)}` +
             `<span class="small">adds <b>${esc(rankDamage(state.rank))}</b> (roll that separately)</span></div>`;
      } else if (rt === 'rankup') {
        h += `<div class="d-flex align-items-center gap-2 mt-1"><span class="small">Current Rank of the skill</span>${num('sp-rank', state.rank, 1, 15, 60)}</div>` +
             `<div class="mt-1" style="font-weight:600;">Roll a d20 — you need <span style="color:var(--ttrpg-accent);">${state.rank}</span> or higher (no modifier).</div>`;
      } else {
        h += `<div class="small mt-1">Just roll — no rules applied.</div>`;
      }
      h += '</div></div>';
      container.innerHTML = h;
      container.querySelectorAll('.sp-syspanel-in').forEach(el => {
        el.addEventListener('change', onInput);
        if (el.type === 'number') el.addEventListener('input', onInput);
      });
      const fold = container.querySelector('#sp-fold');
      if (fold) fold.addEventListener('click', () => { _collapseSet(_PANEL_KEY, !_collapseGet(_PANEL_KEY)); render(); });
    }

    function onInput(ev) {
      const el = ev.target, id = el.id;
      const focusId = id, focusType = el.type;
      if (id === 'sp-rt') {
        state.rollType = el.value; state.kind = null;
        if (['check', 'attack', 'evade', 'stat', 'rankup'].includes(state.rollType)) {
          if (opts.setDie) opts.setDie(20);
          if (opts.setCount) opts.setCount(1);
        }
        if (state.rollType === 'rankup' && opts.setMod) opts.setMod(0);
        if (state.rollType !== 'damage' && state.crit) { state.crit = false; _uncrit(); }
        _applyUntrained();
      } else if (id === 'sp-kind')    state.kind = el.value;
      else if (id === 'sp-opp')       state.oppMod = parseInt(el.value, 10) || 0;
      else if (id === 'sp-base')      state.base = parseInt(el.value, 10) || 0;
      else if (id === 'sp-number')    state.number = parseInt(el.value, 10) || 0;
      else if (id === 'sp-mobmode')   state.mobMode = el.value;
      else if (id === 'sp-untrained') { state.untrained = el.checked; _applyUntrained(); }
      else if (id === 'sp-rank')      state.rank = parseInt(el.value, 10) || 0;
      else if (id === 'sp-crit') {
        state.crit = el.checked;
        if (opts.getCount && opts.setCount) {
          if (state.crit) { state.baseCount = opts.getCount(); opts.setCount(state.baseCount * 2); }
          else _uncrit();
        }
      }
      if (focusType === 'number') {   // re-render without stealing the cursor
        const n = container.querySelector('.sp-syspanel > div:last-child, .sp-syspanel');
        render();
        const again = document.getElementById(focusId);
        if (again) { again.focus(); }
        void n;
      } else render();
      if (opts.onChange) opts.onChange(getContext());
    }
    function _uncrit() {
      if (state.baseCount !== null && opts.setCount) opts.setCount(state.baseCount);
      state.baseCount = null;
    }
    function _applyUntrained() {
      if (!opts.setAdv) return;
      const isCheck = ['check', 'attack', 'evade'].includes(state.rollType);
      opts.setAdv(isCheck && state.untrained ? 'disadvantage' : 'normal');
    }

    function getContext() {
      if (_game.id !== 'dcc') return { roll_type: 'other', difficulty: null, floor: 0, rank: null, untrained: false, crit: false };
      return { roll_type: state.rollType, difficulty: currentDifficulty(), floor: floor(),
               rank: (state.rollType === 'rankup' || state.rollType === 'damage') ? state.rank : null,
               untrained: state.untrained, crit: state.crit };
    }
    function refresh(game) {
      const before = _game.id + ':' + JSON.stringify(_game.settings);
      if (game) setSystem(game);
      const after = _game.id + ':' + JSON.stringify(_game.settings);
      if (before !== after || !container.childElementCount) {
        render();
        if (opts.quickContainer && opts.labelInput) {
          renderQuickLabels(opts.quickContainer, opts.labelInput, opts.btnClass || 'btn btn-sm btn-outline-secondary', _applyPreset);
        }
      }
    }
    function reset() {
      Object.assign(state, { rollType: 'check', kind: null, mobMode: 'normal', untrained: false, crit: false, baseCount: null });
      render();
    }
    // Let a sheet's quick buttons (Evade, a skill chip…) pick the roll type.
    function setRollType(rt) {
      if (_game.id !== 'dcc') return;
      state.rollType = rt; state.kind = null;
      if (state.crit) { state.crit = false; _uncrit(); }
      render();
    }
    // A quick chip sets the dice it names and, under DCC, the roll type —
    // "Skill Check" means d20 + the check panel, "Damage" keeps your dice.
    function _applyPreset(p) {
      if (p.rollType === 'damage' && !p.sides) {
        // The ready weapon's damage dice (+ its damage bonus as the mod); a
        // bare fist (1d4 under DCC, 1d6 under 5e) when nothing is equipped.
        const w = opts.getDamageDice ? opts.getDamageDice() : null;
        // Say WHY it's a fist, so a weapon with blank dice gets fixed instead of
        // silently rolling 1d4 forever.
        const fallback = { count: 1, sides: _game.id === 'dcc' ? 4 : 6, mod: 0,
                           label: 'Unarmed damage — no dice on your equipped weapon (set them on the Weapons tab)' };
        p = Object.assign({}, p, w || fallback);
        if (p.mod !== null && p.mod !== undefined && opts.setMod) opts.setMod(p.mod);
        if (p.label && opts.labelInput) opts.labelInput.value = p.label;
      }
      if (p.count && opts.setCount) opts.setCount(p.count);
      if (p.sides && opts.setDie) opts.setDie(p.sides);
      if (p.rollType) setRollType(p.rollType);
    }
    render();
    if (opts.quickContainer && opts.labelInput) {
      renderQuickLabels(opts.quickContainer, opts.labelInput, opts.btnClass || 'btn btn-sm btn-outline-secondary', _applyPreset);
    }
    return { getContext, refresh, reset, setRollType, parseDice };
  }

  return { rand, roll, expr, breakdown, critFumble, critFumbleFromRecord,
           QUICK_LABELS, renderQuickLabels, parseDice, hotlistPreset, bindCollapsibles, collapseText,
           SYSTEMS, DEFAULT_SYSTEM, setSystem, getSystem, statMod, difficulty,
           rankDamage, evaluate, annotateLabel, mountSystemPanel };
})();

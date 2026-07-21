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

  // Quick-label chips shared by every roller. Highest-frequency generic roll
  // types only — per-character skills with real modifiers live in each UI's
  // quick-reference panel, so this list stays short enough to scan.
  const QUICK_LABELS = ['Initiative', 'Attack', 'Damage', 'Saving Throw',
                        'Perception', 'Stealth', 'Insight'];

  function renderQuickLabels(container, input, btnClass) {
    QUICK_LABELS.forEach(name => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = btnClass;
      b.style.cssText = 'font-size:.72rem;padding:2px 8px;';
      b.textContent = name;
      b.onclick = () => { input.value = name; };
      container.appendChild(b);
    });
  }

  return { rand, roll, expr, breakdown, critFumble, critFumbleFromRecord,
           QUICK_LABELS, renderQuickLabels };
})();

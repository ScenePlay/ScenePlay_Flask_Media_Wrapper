"""Game-system rules for the dice roller (pure Python, no Flask).

The DM picks a *game system* per session (tblSessions.game_system). Every
roller (character sheet, battle map, monster page, and the relay portal via
the mirrored logic in static/scripts/dice.js) then speaks that system's
language: which dice it offers, how a target number is worked out, and what a
roll RESULT means once the dice land.

Two systems ship:

  dnd5e  D&D 5e — the historical default. A roll is just dice + modifier; an
         optional DC turns the result into "Success"/"Fail".

  dcc    Dungeon Crawler Carl RPG (Renegade, Core Rulebook). Key differences
         from 5e that this module encodes (page refs are to the rulebook):
           - the GM never rolls a d20; Mobs carry static "to hit"/Evade
             numbers written as "14+F" (F = current Floor)  (p.55, p.267)
           - Difficulty formulas keyed to the Floor:
               Opposed    10 + antagonist's Stat Mod + F    (p.59)
               Unopposed  10 + F x 2
               Stat Check 10 + F
             Mob Advantage/Disadvantage = +5/-5 on that Difficulty (p.60)
           - degrees of success by margin (p.60-61, p.79-80): Natural 20 =
             Critical Hit, beat by 10+ = Amazing Success, 0-9 = Success,
             fail by 1-2 = Near Miss, 3-9 = Standard Fail, 10+ = Major Fail,
             Natural 1 = Critical Fail. Ties succeed.
           - Stat Modifier table is NOT (score-10)//2 (Table 2, p.57)
           - Skill Advancement Check: d20 >= current Rank -> +1 Rank (p.169)
           - Rank damage dice scale (Table 37, p.176)

`evaluate()` is the one function the roll endpoint calls; it returns a small
outcome dict whose `.text` is appended to the roll label so the shared feed
(and the relay) shows what the roll MEANT, not just its number.

Keep this file and DiceCore in static/scripts/dice.js in step — the portal
rolls client-side and re-implements the same tables there.
"""

DEFAULT_SYSTEM = 'dnd5e'

# What the roller shows for each system. `quick` entries with dice are one-tap
# presets (count/sides/mod); plain strings only fill the label box.
SYSTEMS = {
    'dnd5e': {
        'id': 'dnd5e',
        'name': 'D&D 5e',
        'dice': [4, 6, 8, 10, 12, 20, 100, 2],
        'quick': ['Initiative', 'Attack', 'Damage', 'Saving Throw',
                  'Perception', 'Stealth', 'Insight'],
        'roll_types': [('check', 'Ability / Skill Check'), ('attack', 'Attack'),
                       ('save', 'Saving Throw'), ('damage', 'Damage'),
                       ('other', 'Something else')],
        'settings': {},
    },
    'dcc': {
        'id': 'dcc',
        'name': 'Dungeon Crawler Carl',
        'dice': [20, 12, 10, 8, 6, 4, 2, 100],
        'quick': [
            {'label': 'Skill Check', 'count': 1, 'sides': 20, 'roll_type': 'check'},
            {'label': 'Attack', 'count': 1, 'sides': 20, 'roll_type': 'attack'},
            {'label': 'Evade', 'count': 1, 'sides': 20, 'roll_type': 'evade'},
            {'label': 'Stat Check', 'count': 1, 'sides': 20, 'roll_type': 'stat'},
            {'label': 'Damage', 'roll_type': 'damage'},
            {'label': 'Rank-Up', 'count': 1, 'sides': 20, 'roll_type': 'rankup'},
            {'label': 'Help (trained)',      'count': 1, 'sides': 6},
            {'label': 'Help (untrained)',    'count': 1, 'sides': 2},
            {'label': 'Intervene',           'count': 1, 'sides': 6},
            {'label': 'Call a Play (keep highest)', 'count': 2, 'sides': 6},
            {'label': 'Scatter direction',   'count': 1, 'sides': 8},
        ],
        'roll_types': [('check', 'Skill Check'), ('attack', 'Attack'),
                       ('evade', 'Evade (dodge an attack)'),
                       ('stat', 'Stat Check (resist something)'),
                       ('damage', 'Damage'), ('rankup', 'Skill Rank-Up Check'),
                       ('other', 'Something else')],
        # Per-session knobs the DM sets on the session page.
        'settings': {'floor': 3},
    },
}


def system(system_id):
    """The system dict for an id, falling back to the default (never None)."""
    return SYSTEMS.get(system_id) or SYSTEMS[DEFAULT_SYSTEM]


def normalize_settings(system_id, raw):
    """Coerce a stored/submitted settings dict to the system's known keys."""
    out = {}
    if system_id == 'dcc':
        try:
            out['floor'] = max(1, min(18, int((raw or {}).get('floor', 3))))
        except (TypeError, ValueError):
            out['floor'] = 3
    return out


# ── Dungeon Crawler Carl sheet vocabulary ────────────────────────────────────
# The five Core Stats (there is no Wisdom — Intelligence covers "wit and
# wisdom", p.56). Order matches the printed sheet.
DCC_STATS = ('str', 'int', 'con', 'dex', 'cha')
DCC_STAT_NAMES = {'str': 'Strength', 'int': 'Intelligence', 'con': 'Constitution',
                  'dex': 'Dexterity', 'cha': 'Charisma'}
DCC_SKILL_CATEGORIES = ('Attack', 'Spell', 'Utility', 'Passive')
DCC_HB_SLOTS = 10            # Health Bar slots (p.93); each is worth the Con Mod
DCC_HOTLIST_SLOTS = 10       # p.109
DCC_SIZES = ((2, 'Small (2)'), (3, 'Small-Medium (3)'), (4, 'Medium (4)'),
             (5, 'Large (5)'), (6, 'Huge (6)'))

# Table 11 (p.96) — the common Debuffs, in the words a player needs at the table.
DCC_DEBUFFS = {
    'Blinded':      'Roll all Skill Checks that need sight with Disadvantage. Until the end of next round.',
    'Blood Trail':  'Take 1d6+F at the end of each round (stacks). Until bandaged / First Aid.',
    'Burning':      'Take 1d6+F Fire at the end of each round. Until extinguished.',
    'Confused':     'Act randomly — the GM decides your target. Until the end of next round.',
    'Dying':        'At 0% Health. No Actions; must be healed to 10% or more to survive.',
    'Fatigued':     'Disadvantage on all Checks. Until you rest.',
    'Frightened':   "Can't move toward the source; Disadvantage while it is in sight.",
    'Poisoned':     'Take 1d4+F at the end of each round. Until cured.',
    'Prone':        'Attacks against you have Advantage; spend a Move to stand.',
    'Slowed':       'Move and Step are halved. Until the end of next round.',
    'Stunned':      'Lose your next Action. Until the end of next round.',
    'Weakened':     '−2 on Str-based Checks. Until the end of next round.',
    'Minor Injury': 'After combat — Disadvantage on one Stat until healed at a saferoom.',
    'Major Injury': 'After combat — lose the use of a limb or sense until magically healed.',
}


def dcc_defaults():
    """Fresh Dungeon Crawler Carl sheet bag (tblCharacters.dcc_json)."""
    return {
        'enh': {},              # Enhanced stat overrides {'str': 6, ...}; missing = same as base
        'dr': 0,                # Damage Resistance from armor (buffs added at the table)
        'dr_buffs': 0,
        'evade_buffs': 0,
        'move': 20, 'step': 10, 'size': 4,
        'popularity': 0, 'ai_favor': 1,
        'crawler_number': '', 'pronouns': '', 'floor_entered': '',
        'past_trauma': '', 'loose_ends': '', 'regrets': '',
        'stat_points': 0,       # unspent Stat points (3 per Level gained)
        'grind_hours': '',      # free text tracker
        'applied': [],          # library bonuses already applied ('race:Human')
    }


def dcc_bag(raw):
    """Parsed dcc_json with every default filled in (never raises)."""
    import json as _json
    out = dcc_defaults()
    try:
        data = _json.loads(raw or '{}') if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError):
        data = {}
    for k in out:
        if k in data:
            out[k] = data[k]
    if not isinstance(out['enh'], dict):
        out['enh'] = {}
    return out


def dcc_merge_fields(src, base=None):
    """Merge DCC sheet fields (keys `dcc_<name>` / `dcc_enh_<stat>`) from a
    form/JSON dict onto a dcc bag; unknown keys are ignored."""
    bag = dcc_bag(base)
    ints = ('dr', 'dr_buffs', 'evade_buffs', 'move', 'step', 'size',
            'popularity', 'ai_favor', 'stat_points')
    texts = ('crawler_number', 'pronouns', 'floor_entered', 'past_trauma',
             'loose_ends', 'regrets', 'grind_hours')
    for k in ints:
        if f'dcc_{k}' in src and src.get(f'dcc_{k}') not in (None, ''):
            try:
                bag[k] = int(src.get(f'dcc_{k}'))
            except (TypeError, ValueError):
                pass
    for k in texts:
        if f'dcc_{k}' in src:
            bag[k] = str(src.get(f'dcc_{k}') or '').strip()[:400]
    for st in DCC_STATS:
        key = f'dcc_enh_{st}'
        if key in src:
            v = src.get(key)
            if v in (None, ''):
                bag['enh'].pop(st, None)
            else:
                try:
                    bag['enh'][st] = int(v)
                except (TypeError, ValueError):
                    pass
    return bag


def dcc_damage_slots(damage, dr, con_mod):
    """Health Bar slots lost for a hit (p.93-94): subtract DR, then each
    full Con Mod of remaining damage costs one slot; leftovers are ignored."""
    try:
        damage, dr, con_mod = int(damage), int(dr or 0), int(con_mod or 1)
    except (TypeError, ValueError):
        return 0
    remaining = max(0, damage - max(0, dr))
    if con_mod <= 0 or remaining < con_mod:
        return 0
    return remaining // con_mod


# ── Stat modifiers ────────────────────────────────────────────────────────────

_DCC_MOD_TABLE = ((1, 1), (3, 2), (6, 3), (10, 4), (20, 5), (50, 6),
                  (100, 7), (150, 8), (200, 9), (300, 10))


def stat_mod(system_id, score):
    """Modifier for a raw Stat score under the given system."""
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 10 if system_id != 'dcc' else 3
    if system_id == 'dcc':
        mod = 1
        for floor_score, m in _DCC_MOD_TABLE:
            if score >= floor_score:
                mod = m
        return mod
    return (score - 10) // 2


# ── Difficulty ────────────────────────────────────────────────────────────────

def dcc_difficulty(kind, floor, opp_mod=0, mob_mode='normal', base=None):
    """Target number for a DCC Check.

    kind: 'unopposed' | 'opposed' | 'stat' | 'mob' | 'number'
      mob    -> the Mob's printed number (its to-hit or Evade, "14+F") + Floor
      number -> use `base` as-is
    mob_mode: Mob Advantage +5 / Disadvantage -5 on the Difficulty (p.60).
    """
    floor = max(0, int(floor or 0))
    opp_mod = int(opp_mod or 0)
    base = int(base or 0)
    if kind == 'unopposed':
        d = 10 + floor * 2
    elif kind == 'opposed':
        d = 10 + opp_mod + floor
    elif kind == 'stat':
        d = 10 + floor
    elif kind == 'mob':
        d = base + floor
    else:
        d = base
    if mob_mode == 'advantage':
        d += 5
    elif mob_mode == 'disadvantage':
        d -= 5
    return d


# ── Rank damage dice (Table 37) ───────────────────────────────────────────────

def rank_damage_die(rank):
    """Extra damage for a Skill Rank as (count, sides, flat) — Table 37."""
    r = max(0, int(rank or 0))
    if r == 0:
        return (0, 0, 0)
    if r == 1:
        return (0, 0, 1)
    if r <= 3:
        return (1, 2, 0)
    if r <= 5:
        return (1, 4, 0)
    if r <= 7:
        return (1, 6, 0)
    if r <= 9:
        return (1, 8, 0)
    if r <= 11:
        return (1, 10, 0)
    if r <= 13:
        return (1, 12, 0)
    if r <= 15:
        return (2, 7, 0)      # 1d8 & 1d6 — flagged specially by callers
    if r <= 17:
        return (2, 8, 0)
    if r <= 19:
        return (2, 9, 0)      # 1d10 & 1d8
    return (2, 10, 0)


# ── Outcome ───────────────────────────────────────────────────────────────────

def _degree(natural, margin):
    if natural == 20:
        return 'crit'
    if natural == 1:
        return 'crit_fail'
    if margin >= 10:
        return 'amazing'
    if margin >= 0:
        return 'success'
    if margin >= -2:
        return 'near_miss'
    if margin >= -9:
        return 'fail'
    return 'major_fail'


_DCC_TEXT = {
    'check': {
        'crit':       'Critical Hit — the best possible result',
        'amazing':    'Amazing Success',
        'success':    'Success',
        'near_miss':  'Near Miss — an ally may Intervene (1d6)',
        'fail':       'Fail',
        'major_fail': 'Major Fail — expect a consequence',
        'crit_fail':  'Critical Fail!',
    },
    'attack': {
        'crit':       'CRITICAL HIT — roll DOUBLE base damage dice',
        'amazing':    'Amazing Success — hit, +{F} bonus damage',
        'success':    'Hit',
        'near_miss':  'Near Miss — an ally may Intervene (1d6)',
        'fail':       'Miss',
        'major_fail': 'Major Fail — miss, plus a consequence (dropped weapon, lost footing…)',
        'crit_fail':  'Critical Fail — worst outcome (hit an ally, break a weapon…)',
    },
    'evade': {
        'crit':       'Evaded! Advantage on your next attack vs this Mob',
        'amazing':    'Evaded with style — Advantage on your next attack vs this Mob',
        'success':    'Evaded',
        'near_miss':  'Near Miss — you are hit; an ally may Intervene (1d6)',
        'fail':       'Hit',
        'major_fail': 'Major Fail — hit, +{F} extra damage, Minor Injury after combat',
        'crit_fail':  'Critical Fail — DOUBLE damage, Major Injury after combat',
    },
}
_DCC_TEXT['stat'] = _DCC_TEXT['check']


def evaluate(system_id, sides, natural, total, roll_type='check',
             difficulty=None, floor=0, rank=None):
    """What a finished roll means.

    natural: the kept die (d20) or None when not a single d20.
    Returns {'degree', 'ok', 'margin', 'text'}; `text` is '' when the system
    has nothing to add (e.g. a plain damage roll).
    """
    out = {'degree': None, 'ok': None, 'margin': None, 'text': ''}
    try:
        difficulty = int(difficulty) if difficulty not in (None, '') else None
    except (TypeError, ValueError):
        difficulty = None
    floor = max(0, int(floor or 0))
    is_d20 = (sides == 20 and natural is not None)

    if system_id == 'dcc':
        if roll_type == 'rankup' and is_d20:
            try:
                rank = int(rank)
            except (TypeError, ValueError):
                rank = None
            if rank is None:
                return out
            ok = natural >= rank
            out.update(degree='success' if ok else 'fail', ok=ok,
                       margin=natural - rank,
                       text=(f'Rank up! Skill goes to Rank {min(rank + 1, 15)}'
                             if ok else f'No rank-up (needed {rank}+ on the die)'))
            return out
        if not is_d20 or difficulty is None:
            if is_d20 and natural == 20:
                out.update(degree='crit', ok=True, text='Natural 20 — Critical Hit!')
            elif is_d20 and natural == 1:
                out.update(degree='crit_fail', ok=False, text='Natural 1 — Critical Fail!')
            return out
        margin = total - difficulty
        deg = _degree(natural, margin)
        texts = _DCC_TEXT.get(roll_type) or _DCC_TEXT['check']
        out.update(degree=deg, margin=margin,
                   ok=deg in ('crit', 'amazing', 'success'),
                   text=texts[deg].replace('{F}', str(floor)))
        return out

    # D&D 5e (and anything unknown): DC compare, natural 20/1 called out.
    if not is_d20:
        return out
    if natural == 20:
        out.update(degree='crit', ok=True, text='Natural 20!')
    elif natural == 1:
        out.update(degree='crit_fail', ok=False, text='Natural 1!')
    if difficulty is not None:
        margin = total - difficulty
        ok = margin >= 0 if natural not in (1, 20) else out['ok']
        out['margin'] = margin
        out['ok'] = ok
        word = 'Success' if ok else 'Fail'
        out['text'] = (out['text'] + ' — ' + word) if out['text'] else word
        out['degree'] = out['degree'] or ('success' if ok else 'fail')
    return out


def annotate_label(label, outcome, difficulty=None):
    """The label as it should read in the feed: 'Attack vs 17 → Hit'."""
    label = (label or '').strip()
    if not outcome or not outcome.get('text'):
        return label
    vs = f' vs {difficulty}' if difficulty not in (None, '') else ''
    head = f'{label}{vs}' if label else (vs.strip() if vs else '')
    return f'{head} → {outcome["text"]}' if head else outcome['text']

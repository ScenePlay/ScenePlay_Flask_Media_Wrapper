"""Random Dungeon Crawler Carl crawler (Chapter 3, Character Creation).

Follows the book's steps in order, using the "leave it to chance" options:
  1. Background skills — Tables 12–15 (two skills each from childhood,
     adolescence, career and hobby at Rank 1/1/3/2), no double-dipping.
  2. Combat — Unarmed Combat at Rank 3 plus the weapon from the starting kit
     (also Rank 3); every crawler knows the Heal spell.
  3. Stats — roll 1d6 per Stat, rerolling 1s (scores 2–6).
  5. Health Bar (10 slots of Con Mod) and Mana (= Intelligence) are derived
     by the sheet itself.
  9. Past Trauma / Loose End / Regret — Tables 22–24.
 10. Starting gear — one of the four example kits (p.115).

"Third Floor & Beyond" (p.115) on top of that: Level 10, +2d4 to the main
weapon skill and +1d4 to every other skill (Rank cap 10), 27 Stat points
spread across the five Stats, AI Favor 1d2 (+ the weapon's rating), Popularity
= Cha Mod × 2, and a Race + Class from the built-in library with their bonuses
applied (an Alien Race never gets an Earth Class).

Pure module: the only DB access is the optional race/class lookup passed in.
"""
import random

import dice_systems as ds
import dcc_library as lib

# ── Tables 12–15: human backgrounds (skill, stat) ─────────────────────────────
CHILDHOOD = {
    'Latchkey Kid':   ['Streetwise', 'Perception', 'Stealth'],
    'Crafty Kid':     ['Fabricate', 'Repair', 'Salvage'],
    'Excitable Kid':  ['Escape Artist', 'Endurance', 'Running'],
    'Gymnast':        ['Endurance', 'Jumping', 'Performance'],
    'Military Brat':  ['Deception', 'Streetwise', 'Tactics'],
    'MMO Kid':        ['Fabricate', 'Engineering', 'Tactics'],
    'Only Child':     ['Good First Impression', 'Investigation', 'Negotiation'],
    'Outdoor Kid':    ['Animal Handling', 'Climbing', 'Swimming'],
    'Problem Child':  ['Intimidate', 'Deception', 'Pugilism'],
    'Scamp':          ['Hide in Shadows', 'Jumping', 'Throwing'],
    "Teacher's Pet":  ['Catcher', 'Perception', 'Good First Impression'],
    'Wild Child':     ['Stealth', 'Survival', 'Running'],
}
ADOLESCENCE = {
    'Family Farm':        ['Animal Handling', 'Fabricate', 'Tracking'],
    'Drama Nerd':         ['Fabricate', 'Deception', 'Performance'],
    'Drop-Out':           ['Chopper Pilot', 'Streetwise', 'Survival'],
    'Greek Life':         ['Negotiation', 'Intimidate', 'Taunt'],
    'Influencer':         ['Negotiation', 'Persuasion', 'Performance'],
    'Jock':               ['Endurance', 'Jumping', 'Throwing'],
    'McJob':              ['Determine Value', 'Negotiation', 'Repair'],
    'Popular':            ['Good First Impression', 'Perception', 'Persuasion'],
    'Religious':          ['Catcher', 'First Aid', 'Persuasion'],
    'Student Government': ['Deception', 'Persuasion', 'Investigation'],
    'Nerd':               ['Investigation', 'Repair', 'Fabricate'],
    'Weirdo':             ['Streetwise', 'Intimidate', 'Fabricate'],
}
CAREER = {
    'Criminal':             ['Deception', 'Stealth', 'Streetwise'],
    'Service Industry':     ['Dagger', 'Endurance', 'Sleight of Hand'],
    'Small Business Owner': ['Determine Value', 'Negotiation', 'Perception'],
    'Medical':              ['Sleight of Hand', 'Detect Lies', 'First Aid'],
    'Law Enforcement':      ['Detect Lies', 'Handgun', 'Investigation'],
    'Gig Worker':           ['Driving', 'Escape Artist', 'Negotiation'],
    'Teacher':              ['Detect Lies', 'Perception', 'Performance'],
    'Office Drone':         ['Dumpster Diving', 'Endurance', 'Investigation'],
    'Entertainer':          ['Deception', 'Good First Impression', 'Performance'],
    'Unhoused':             ['Dumpster Diving', 'Streetwise', 'Survival'],
    'Middle Manager':       ['Deception', 'Intimidate', 'Negotiation'],
    'Military':             ['Handgun', 'Survival', 'Tactics'],
}
HOBBY = {
    'Collector':   ['Fabricate', 'Determine Value', 'Investigation'],
    'Cosplay':     ['Fabricate', 'Performance', 'Salvage'],
    'Drinker':     ['Deception', 'Intimidate', 'Streetwise'],
    'Gamer':       ['Aiming', 'Perception', 'Tactics'],
    'Gym Rat':     ['Running', 'Endurance', 'Swimming'],
    'Hunting':     ['Tracking', 'Shotgun', 'Stealth'],
    'Music':       ['Perception', 'Performance', 'Sleight of Hand'],
    'Motorsports': ['Driving', 'Repair', 'Salvage'],
    'Climber':     ['Climbing', 'Jumping', 'Endurance'],
    'Pop Culture': ['Determine Value', 'Investigation', 'Perception'],
    'Tinkering':   ['Engineering', 'Repair', 'Salvage'],
    'Travel':      ['Endurance', 'Negotiation', 'Streetwise'],
}
STAGES = [('childhood', CHILDHOOD, 1), ('adolescence', ADOLESCENCE, 1),
          ('career', CAREER, 3), ('hobby', HOBBY, 2)]

# ── Tables 22–24 ──────────────────────────────────────────────────────────────
PAST_TRAUMA = [
    'I was abused by someone I trusted.', 'I was in a terrible accident.', 'I witnessed a death.',
    'I was betrayed by a family member, friend, or lover.', 'I was abandoned by one or more parents.',
    'I have a fear of open spaces.', 'I have a fear of the dark or being alone.', 'My home burned down.',
    'I was falsely accused of a betrayal or crime.', 'I was deeply humiliated by a family member, friend, or lover.',
    'I let someone take the blame for something terrible that I did.', 'I have a fear of heights.',
]
LOOSE_ENDS = [
    'I never finished high school or my college degree.', 'I was about to open a restaurant or other business.',
    "I didn't finish writing my novel.", "A family member, friend, or lover recently died, but I couldn't say my goodbyes.",
    'I was on the verge of inventing or discovering something.', 'I made a promise that I might no longer be able to fulfill.',
    'My collection was almost complete.', 'I was about to perform for the first time when the collapse happened.',
    'I wanted to dump my partner, but…', 'I was just about to buy or finish renovating my home.',
    'I never sent that letter to a family member, friend, or loved one.', 'I never got to travel to my dream destination.',
]
REGRETS = [
    "I didn't ask them to marry me.", 'I turned down the perfect job.', "I stayed quiet when I shouldn't have.",
    'I chose my own safety when I should have leapt into action.', 'I never said goodbye.',
    'I spent way too much time on something pointless.', 'I did something illegal, immoral, and probably both.',
    'I lied to avoid an event important to those close to me.', 'I kept a secret that hurt someone badly.',
    "I didn't apologize for something terrible that I did.", 'I abandoned someone when they needed me the most.',
    'I trusted the wrong people.',
]

# ── Step 10 example kits (p.115): (combat background, weapon skill, items) ───
KITS = [
    ('Athlete',     'Club',      ['Jogging attire (worn)', 'Barbell (Club)', 'Headphones and music player', 'A 3-pack of condoms']),
    ('Gaming Geek', 'Longsword', ['T-shirt, hoodie and jeans (worn)', 'Boffer sword (Longsword, d4 base damage)', 'Game book or novel',
                                  'Pack of 12 googly eyes', 'A single Lego minifig']),
    ('Militant',    'Handgun',   ['Military fatigues (worn)', 'Handgun', '2 snack bars', 'Morale patch: "No Plan Survives First Contact"']),
    ('Outdoorsy',   'Bow',       ['Climate-appropriate clothes and an orange safety jacket (worn)', 'Bow and arrows', 'Lighter',
                                  'A duck call on a leather cord']),
]

STAT_KEYS = ['str', 'int', 'con', 'dex', 'cha']
FIRST_NAMES = ['Carl', 'Donut', 'Katia', 'Elle', 'Imani', 'Hekla', 'Li Jun', 'Zev', 'Bautista', 'Britney', 'Chris', 'Frank',
               'Louis', 'Gwen', 'Tsering', 'Eva', 'Prepotente', 'Samantha', 'Brandon', 'Florin', 'Juice Box', 'Quan', 'Lucia',
               'Odette', 'Ren', 'Marcus', 'Priya', 'Dmitri', 'Nadia', 'Tomas']
LAST_NAMES = ['Grimaldi', 'Ortiz', 'Nakamura', 'Okafor', 'Lindqvist', 'Bauer', 'Mbeki', 'Reyes', 'Kowalski', 'Haddad',
              'Fitzgerald', 'Ivanova', 'Park', 'Dubois', 'Castellano', 'Achebe', 'Moreau', 'Singh', 'Larsen', 'Whitaker']
EPITHETS = ['the Unlucky', 'of Deck 7', 'Two-Shoes', 'the Late', 'Bloodhound', 'Half-Pint', 'the Cautious', 'Sparkplug']


def _roll_stat(rng):
    """1d6, rerolling 1s (p.109 'Leaving it to chance')."""
    v = rng.randint(1, 6)
    while v == 1:
        v = rng.randint(1, 6)
    return v


def _skill_meta(name):
    meta = lib.SKILL_INDEX.get(name)
    return (meta[0], (meta[1] or '').lower()) if meta else ('Utility', '')


def _add_skill(skills, name, rank, source):
    """Add or raise a skill; duplicates just take the higher Rank (cap 10)."""
    for s in skills:
        if s['name'] == name:
            s['rank'] = min(10, max(s['rank'], rank))
            return False
    cat, stat = _skill_meta(name)
    skills.append({'name': name, 'rank': min(10, rank), 'category': cat, 'stat': stat, 'from': source})
    return True


def generate_crawler(floor='first', rng=None, races=None, classes=None):
    """Return the create-character form fields for a random crawler.

    floor:   'first' (fresh from the collapse, Level 1) or 'third' (Level 10,
             Race + Class chosen, Tutorial Floor loot).
    races / classes: iterables of library rows (name, description,
             ability_bonuses/proficiencies, traits_text/skill_choices, size,
             speed) — the DCC ones. None → no Race/Class.
    """
    rng = rng or random.Random()
    third = (floor == 'third')

    # Step 1 — backgrounds
    skills, story = [], []
    for stage, table, rank in STAGES:
        label = rng.choice(list(table))
        picks = rng.sample(table[label], 2)
        for name in picks:
            if not _add_skill(skills, name, rank, stage):
                # no double-dipping: take the third option instead when it's new
                third_opt = [n for n in table[label] if n not in picks][0]
                _add_skill(skills, third_opt, rank, stage)
        story.append(f'{stage.title()}: {label} ({", ".join(picks)})')

    # Step 2 / 10 — combat skills and the starting kit
    kit_name, weapon, items = rng.choice(KITS)
    _add_skill(skills, 'Unarmed Combat', 3, 'combat')
    _add_skill(skills, weapon, 3, 'combat')
    _add_skill(skills, 'Heal', 1, 'system')
    story.append(f'Combat background: {kit_name} — {weapon}')

    # Step 3 — stats
    stats = {k: _roll_stat(rng) for k in STAT_KEYS}

    level, race_row, class_row, applied_notes, stat_points_note = 1, None, None, [], ''
    ai_favor, popularity, loot_note = 1, 0, ''
    move, size = 20, 4

    if third:
        level = 10
        # Skill growth on the Tutorial Floors
        for s in skills:
            if s['name'] == weapon:
                s['rank'] = min(10, s['rank'] + rng.randint(1, 4) + rng.randint(1, 4))
            else:
                s['rank'] = min(10, s['rank'] + rng.randint(1, 4))
        # 27 Stat points, weighted toward two favourites
        favs = rng.sample(STAT_KEYS, 2)
        for _ in range(27):
            k = rng.choice(favs + favs + STAT_KEYS)
            stats[k] += 1
        stat_points_note = f'27 Tutorial-Floor Stat points spent (favouring {favs[0].upper()} and {favs[1].upper()})'
        # AI Favor 1d2 + the weapon's rating
        ai_favor = rng.randint(1, 2)
        wmeta = lib.SKILL_INDEX.get(weapon)
        if wmeta and 'AI Favor 2' in wmeta[2]:
            ai_favor += rng.randint(1, 2) + rng.randint(1, 2)
        elif wmeta and 'AI Favor 1' in wmeta[2]:
            ai_favor += rng.randint(1, 2)
        # Race, then a Class it may take (Alien Races never get Earth Classes)
        race_list = list(races or [])
        class_list = list(classes or [])
        if race_list:
            race_row = rng.choice(race_list)
            alien = (getattr(race_row, 'description', '') or '').startswith('Alien Race')
            allowed = [c for c in class_list
                       if not (alien and 'Earth Class' in (getattr(c, 'description', '') or ''))]
            if allowed:
                class_row = rng.choice(allowed)
        for kind, row in (('race', race_row), ('class', class_row)):
            if row is None:
                continue
            bonuses = lib.stat_bonuses(row.ability_bonuses if kind == 'race' else row.proficiencies)
            for k, n in bonuses.items():
                stats[k] = max(1, stats[k] + n)
            lines = (row.traits_text if kind == 'race' else row.skill_choices or '').split('\n')
            for n, sname in lib.skill_bonuses(lines):
                _add_skill(skills, sname, n, kind)
                for s in skills:
                    if s['name'] == sname and s['from'] != kind:
                        s['rank'] = min(10, s['rank'] + n)   # existing skill: add the bonus
            applied_notes.append(f'{kind.title()} bonuses applied: {row.name}')
        if race_row is not None:
            try:
                move = int(race_row.speed or 20)
            except (TypeError, ValueError):
                pass
            import re
            m = re.search(r'\((\d)\)', race_row.size or '')
            if m:
                size = int(m.group(1))
        popularity = ds.stat_mod('dcc', stats['cha']) * 2
        # Table 25 — Acquired Loot (kept as a note; the GM hands out the actual items)
        loot = rng.randint(1, 4)
        tiers = {1: 'Platinum Weapon/Spells, Gold Armor/Spells, Silver Item/Spells, Bronze Consumable',
                 2: 'Bronze Weapon/Spells, Platinum Armor/Spells, Gold Item/Spells, Silver Consumable',
                 3: 'Silver Weapon/Spells, Bronze Armor/Spells, Platinum Item/Spells, Gold Consumable',
                 4: 'Gold Weapon/Spells, Silver Armor/Spells, Bronze Item/Spells, Platinum Consumable'}
        loot_note = f'Table 25 loot roll {loot}: {tiers[loot]} (see p.116 — pick the actual items with your GM)'

    name = f'{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}'
    if third and rng.random() < 0.4:
        name += f' {rng.choice(EPITHETS)}'

    note_lines = ['DUNGEON CRAWLER CARL — random crawler'] + story
    if stat_points_note:
        note_lines.append(stat_points_note)
    note_lines += applied_notes
    if loot_note:
        note_lines.append(loot_note)
    note_lines.append('Skills: ' + ', '.join(f"{s['name']} R{s['rank']}" for s in skills))

    # Sort skills: attacks first, then by rank
    skills.sort(key=lambda s: ({'Attack': 0, 'Spell': 1, 'Utility': 2, 'Passive': 3}.get(s['category'], 4), -s['rank'], s['name']))

    return {
        'game_system': 'dcc',
        'name': name,
        'race': race_row.name if race_row is not None else 'Human',
        'char_class': class_row.name if class_row is not None else '',
        'level': level,
        'background': kit_name,
        'str_val': stats['str'], 'int_val': stats['int'], 'con_val': stats['con'],
        'dex_val': stats['dex'], 'cha_val': stats['cha'], 'wis_val': 10,
        'gold': rng.randint(0, 20) if not third else rng.randint(50, 400),
        'dcc_move': move, 'dcc_step': 10, 'dcc_size': size,
        'dcc_popularity': popularity, 'dcc_ai_favor': ai_favor, 'dcc_dr': 0,
        'dcc_crawler_number': str(rng.randint(100000, 9999999)),
        'dcc_past_trauma': rng.choice(PAST_TRAUMA),
        'dcc_loose_ends': rng.choice(LOOSE_ENDS),
        'dcc_regrets': rng.choice(REGRETS),
        'dcc_floor_entered': '3' if third else '1',
        'dcc_stat_points': 0,
        'skills': [{k: v for k, v in s.items() if k != 'from'} for s in skills],
        'items': items,
        'applied': ([f'race:{race_row.name}'] if race_row is not None else []) +
                   ([f'class:{class_row.name}'] if class_row is not None else []),
        'traits_note': '\n'.join(note_lines),
    }

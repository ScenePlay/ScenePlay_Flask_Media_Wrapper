"""Random homebrew entry generation: monsters, ships/vehicles, other assets.

Same philosophy as char_randgen: original content, genre packs supply the
flavor, and the numbers come from a simplified (original) benchmark curve
inspired by how 5e monsters scale with Challenge Rating — good enough to
drop straight into play and tweak by hand afterwards.

Distances in generated text are given in SQUARES (unit-free), matching the
app's convention that the map legend implies real distance.

Pure functions; `generate_homebrew(kind, genre, tier, rng)` needs no app
context or database.
"""
import random

# Standard 5e XP awards by CR (SRD table).
XP_BY_CR = {
    '1/4': 50, '1/2': 100, '1': 200, '2': 450, '3': 700, '4': 1100,
    '5': 1800, '6': 2300, '7': 2900, '8': 3900, '9': 5000, '10': 5900,
    '11': 7200, '12': 8400, '13': 10000, '14': 11500, '15': 13000,
    '16': 15000, '17': 18000, '18': 20000, '19': 22000, '20': 25000,
    '21': 33000, '22': 41000, '23': 50000, '24': 62000,
}

# Tier -> pool of CRs to roll from.
TIERS = {
    'minion':    ['1/4', '1/2', '1', '2'],
    'standard':  ['2', '3', '4', '5', '6'],
    'elite':     ['7', '8', '9', '10', '11'],
    'boss':      ['12', '13', '14', '15', '16', '17'],
    'legendary': ['18', '19', '20', '21', '22', '23', '24'],
}

ABILITIES = ['str_val', 'dex_val', 'con_val', 'int_val', 'wis_val', 'cha_val']


def _cr_num(cr):
    return {'1/4': 0.25, '1/2': 0.5}.get(cr) or float(cr)


# ── Per-genre flavor ───────────────────────────────────────────────────────────

GENRE_DATA = {
    'fantasy': {
        'monster_types': ['beast', 'undead', 'fiend', 'aberration', 'construct',
                          'plant', 'monstrosity', 'elemental'],
        'monster_first': ['Ash', 'Grave', 'Dusk', 'Iron', 'Blood', 'Thorn',
                          'Mire', 'Frost', 'Ember', 'Hollow', 'Storm', 'Bone'],
        'monster_second': ['fang Stalker', 'maw Brute', 'wing Shrike', 'hide Ravager',
                           'claw Lurker', 'back Crawler', 'eye Watcher', 'spine Fiend',
                           'howl Alpha', 'tail Horror'],
        'damage': ['fire', 'necrotic', 'poison', 'cold', 'lightning'],
        'languages': ['—', 'Common', 'Common, Draconic', 'Deep Speech', 'Abyssal'],
        'alignments': ['unaligned', 'chaotic evil', 'neutral evil', 'neutral', 'chaotic neutral'],
        'vehicle_type': 'vehicle — sailing ship',
        'vehicle_types': ['vehicle — sailing ship', 'vehicle — river barge',
                          'vehicle — war wagon', 'vehicle — airship'],
        'ship_first': ['Crimson', 'Wandering', 'Salt', 'Gilded', 'Storm',
                       'Iron', 'Silent', 'Sea', 'Wave', 'Last'],
        'ship_second': ['Gull', 'Serpent', 'Fortune', 'Maiden', 'Kraken',
                        'Widow', 'Arrow', 'Drake', 'Tempest', 'Promise'],
        'vehicle_speeds': ['6 (sail)', '4 (oars)', '8 (full sail)', '10 (airborne)'],
        'stations': ['ballista', 'mangonel', 'harpoon thrower'],
        'asset_names': [('Thundering', 'Trebuchet'), ('Merchant', 'Caravan'),
                        ('Ancient', 'Waystone'), ('Arcane', 'Beacon'),
                        ('Fortified', 'Watchtower'), ('Royal', 'Supply Wagon')],
        'asset_types': ['object — siege engine', 'object — caravan',
                        'object — structure', 'object — arcane device'],
    },
    'litrpg': {
        'monster_types': ['mob', 'elite mob', 'boss', 'construct', 'swarm', 'mimic'],
        'monster_first': ['Rusted', 'Glitched', 'Neon', 'Tunnel', 'Vault',
                          'Feral', 'Spawned', 'Cursed', 'Overgrown', 'Rabid'],
        'monster_second': ['Crawler MK-II', 'Floor Guardian', 'Loot Mimic', 'Stair Fiend',
                           'Warden Unit', 'Pit Shrieker', 'Hall Sentinel', 'Brood Mother'],
        'damage': ['fire', 'acid', 'lightning', 'psychic'],
        'languages': ['—', 'System Common', 'Dungeon Cant'],
        'alignments': ['unaligned', 'hostile (aggro on sight)', 'neutral (until provoked)'],
        'vehicle_type': 'vehicle — dungeon transport',
        'vehicle_types': ['vehicle — mine cart train', 'vehicle — floor tram',
                          'vehicle — cargo lift', 'vehicle — rail sled'],
        'ship_first': ['Rattling', 'Express', 'Doomed', 'Lucky', 'Rusty', 'Screaming'],
        'ship_second': ['Cartline', 'Descender', 'Loop', 'Special', 'Nine', 'Shortcut'],
        'vehicle_speeds': ['8 (rails)', '6 (tram)', '12 (freefall brake)'],
        'stations': ['mounted crossbow', 'flame nozzle', 'shock coil'],
        'asset_names': [('Glowing', 'Waypoint'), ('Sealed', 'Loot Vault'),
                        ('Grand', 'Vendor Stall'), ('Humming', 'Mana Well'),
                        ('Cracked', 'Spawner Node'), ('Golden', 'Stair Gate')],
        'asset_types': ['object — dungeon fixture', 'object — vendor stall',
                        'object — spawner', 'object — waypoint'],
    },
    'voidmarines': {
        'monster_types': ['xenoform', 'void horror', 'combat servitor', 'heretek construct',
                          'brood organism', 'corrupted machine'],
        'monster_first': ['Hull', 'Void', 'Plasma', 'Cryo', 'Rad', 'Vent',
                          'Breach', 'Static', 'Bulk', 'Wreck'],
        'monster_second': ['borer Swarm', 'stalker Prime', 'wraith Unit', 'maw Titan',
                           'hound Pack-Alpha', 'reaver Drone', 'shrike Queen', 'crawler Nest'],
        'damage': ['plasma', 'radiant', 'necrotic', 'acid'],
        'languages': ['—', 'Binary cant', 'Low Gothic', 'Xenos pheromones'],
        'alignments': ['hostile xenos', 'corrupted', 'rogue machine', 'unaligned'],
        'vehicle_type': 'vehicle — voidcraft',
        'vehicle_types': ['vehicle — dropship', 'vehicle — boarding pod',
                          'vehicle — gun cutter', 'vehicle — armored crawler'],
        'ship_first': ['Vengeful', 'Adamant', 'Grim', 'Unbroken', 'Blackened', 'Penitent'],
        'ship_second': ['Resolve', 'Hammer', 'Vigil', 'Sepulchre', 'Lance', 'Oath'],
        'vehicle_speeds': ['12 (thrusters)', '8 (tracked)', '20 (orbital drop)'],
        'stations': ['heavy bolt turret', 'lascannon mount', 'missile rack'],
        'asset_names': [('Forward', 'Command Bunker'), ('Sanctified', 'Supply Cache'),
                        ('Macro', 'Defense Battery'), ('Vox', 'Relay Mast'),
                        ('Promethium', 'Fuel Dump'), ('Aegis', 'Barricade Line')],
        'asset_types': ['object — fortification', 'object — supply cache',
                        'object — gun battery', 'object — comms relay'],
    },
    'wasteland': {
        'monster_types': ['mutant beast', 'rad horror', 'feral pack', 'scrap construct',
                          'swarm', 'wastes stalker'],
        'monster_first': ['Rad', 'Dust', 'Scrap', 'Gutter', 'Crater', 'Rust',
                          'Ash', 'Tar', 'Glass', 'Burn'],
        'monster_second': ['hound Alpha', 'roach Brood', 'vulture Flock', 'boar Bruiser',
                           'gecko Swarm', 'stalker Matriarch', 'crab Hulk', 'wurm Juvenile'],
        'damage': ['poison', 'acid', 'fire', 'necrotic'],
        'languages': ['—', 'Wastes pidgin', 'Old-world signs'],
        'alignments': ['feral', 'territorial', 'scavenging', 'unaligned'],
        'vehicle_type': 'vehicle — war rig',
        'vehicle_types': ['vehicle — war rig', 'vehicle — dune buggy',
                          'vehicle — armored hauler', 'vehicle — chopper bike'],
        'ship_first': ['Mad', 'Chrome', 'Last', 'Howling', 'Blistered', 'Redline'],
        'ship_second': ['Bertha', 'Salvation', 'Chance', 'Jackal', 'Fury', 'Runner'],
        'vehicle_speeds': ['16 (V8 roar)', '20 (nitro burst)', '10 (armored crawl)'],
        'stations': ['harpoon launcher', 'flamethrower rig', 'scrap cannon'],
        'asset_names': [('Fortified', 'Fuel Depot'), ('Rattling', 'Water Tanker'),
                        ('Sacred', 'Seed Vault'), ('Jury-Rigged', 'Rad Scrubber'),
                        ('Bartertown', 'Toll Gate'), ('Buried', 'Supply Cache')],
        'asset_types': ['object — depot', 'object — tanker', 'object — vault',
                        'object — toll gate'],
    },
    'spacefaring': {
        'monster_types': ['alien fauna', 'rogue drone', 'parasite colony', 'security mech',
                          'spaceborne organism', 'anomalous entity'],
        'monster_first': ['Void', 'Hull', 'Ion', 'Cryo', 'Nebula', 'Station',
                          'Reactor', 'Airlock', 'Solar', 'Drift'],
        'monster_second': ['leech Cluster', 'skimmer Pod', 'mantis Sentry', 'spore Bloom',
                           'ray Glider', 'crab Custodian', 'wisp Swarm', 'serpent Coil'],
        'damage': ['lightning', 'cold', 'radiant', 'acid'],
        'languages': ['—', 'Colony Standard', 'Machine code', 'Unknown signal patterns'],
        'alignments': ['non-hostile (curious)', 'territorial', 'malfunctioning', 'unaligned'],
        'vehicle_type': 'vehicle — spacecraft',
        'vehicle_types': ['vehicle — shuttle', 'vehicle — light freighter',
                          'vehicle — survey rover', 'vehicle — mining barge'],
        'ship_first': ['Star', 'Distant', 'Bright', 'Long', 'Quiet', 'First'],
        'ship_second': ['Horizon', 'Wanderer', 'Promise', 'Haul', 'Comet', 'Light'],
        'vehicle_speeds': ['14 (ion drive)', '10 (maneuvering thrusters)', '8 (surface treads)'],
        'stations': ['point-defense laser', 'grapple beam', 'survey sensor array'],
        'asset_names': [('Orbital', 'Relay Station'), ('Automated', 'Mining Rig'),
                        ('Colony', 'Life-Support Core'), ('Deep-Range', 'Sensor Buoy'),
                        ('Hydroponic', 'Farm Module'), ('Emergency', 'Escape Pod Bay')],
        'asset_types': ['object — station module', 'object — mining rig',
                        'object — infrastructure', 'object — beacon'],
    },
}

# ── Ability text templates (distances in squares — unit implied by the map) ───

MONSTER_TRAITS = [
    "Keen Senses. Advantage on Perception checks that rely on smell or vibration.",
    "Pack Tactics. Advantage on attack rolls when an ally is within 1 square of the target.",
    "{Dmg} Aura. A creature that starts its turn within 2 squares takes {aura}d6 {dmg} damage.",
    "Armored Hide. Bludgeoning damage from nonmagical attacks is halved.",
    "Ambusher. In the first round of combat, it has advantage on attacks against surprised targets.",
    "Regeneration. Regains {regen} HP at the start of its turn unless it took {dmg} damage.",
    "Unstoppable. Can't have its speed reduced and ignores difficult terrain.",
    "Camouflage. Advantage on Stealth checks in its home terrain.",
]

MONSTER_ATTACKS = [
    "Rend. Melee: +{atk} to hit, reach 1 square; {dice}d8+{mod} slashing damage.",
    "Crush. Melee: +{atk} to hit, reach 1 square; {dice}d10+{mod} bludgeoning damage, and the target is grappled (escape DC {dc}).",
    "{Dmg} Spit. Ranged: +{atk} to hit, range 6 squares; {dice}d6+{mod} {dmg} damage.",
    "{Dmg} Breath (Recharge 5–6). 3-square cone; DC {dc} DEX save, {breath}d6 {dmg} damage, half on success.",
]

VEHICLE_NOTES = [
    "Crew {crew}, passengers {pax}. Cargo capacity {cargo} tons.",
    "Ram. Melee: +{atk} to hit; {dice}d10 bludgeoning damage — double against structures and other vehicles.",
    "Weapon Station ({station}). Crewed attack: +{atk} to hit, range 12 squares; {dice}d10 damage.",
    "Damage Threshold {threshold}: attacks dealing less than {threshold} damage deal none.",
    "When reduced to half HP, its speed is halved; at 0 HP it is disabled, not destroyed.",
]

ASSET_NOTES = [
    "Sturdy construction: immune to poison and psychic damage.",
    "Damage Threshold {threshold}: attacks dealing less than {threshold} damage deal none.",
    "Occupies its full footprint; provides three-quarters cover to creatures behind it.",
    "Interact (DC {dc}): a creature within 1 square can operate/disable it with a successful check.",
    "If destroyed, its footprint becomes difficult terrain.",
]


def _stat_block_numbers(cr, rng):
    """Original benchmark curve, CR -> combat numbers."""
    n = _cr_num(cr)
    prof = max(2, min(9, 2 + int((n - 1) // 4)))
    ac = max(11, min(19, round(12 + n / 3) + rng.randint(-1, 1)))
    hp = max(5, int((15 + n * 15) * rng.uniform(0.8, 1.2)))
    atk = max(3, min(14, round(3 + n * 0.5)))
    dc = max(10, min(21, round(10 + n * 0.5)))
    return prof, ac, hp, atk, dc


def _fill(template, **kw):
    for k, v in kw.items():
        template = template.replace('{' + k + '}', str(v))
    return template


def generate_homebrew(kind='monster', genre='fantasy', tier='standard', rng=None):
    """Returns a dict of homebrew-form fields (+ 'kind' echo)."""
    rng = rng or random.Random()
    g = GENRE_DATA.get(genre) or GENRE_DATA['fantasy']
    if genre not in GENRE_DATA:
        genre = 'fantasy'
    if kind not in ('monster', 'vehicle', 'asset'):
        kind = 'monster'
    cr = rng.choice(TIERS.get(tier) or TIERS['standard'])
    n = _cr_num(cr)
    prof, ac, hp, atk, dc = _stat_block_numbers(cr, rng)
    dmg = rng.choice(g['damage'])
    dice = max(1, round(n / 3) + 1)

    out = {
        'kind': kind, 'genre': genre, 'cr': cr,
        'xp': XP_BY_CR.get(cr, 0), 'ac': ac, 'hp_max': hp,
    }

    if kind == 'monster':
        size = rng.choice(
            ['Small', 'Medium', 'Medium', 'Large'] if n < 5 else
            ['Medium', 'Large', 'Large', 'Huge'] if n < 12 else
            ['Large', 'Huge', 'Huge', 'Gargantuan'])
        primary = rng.choice(['str_val', 'dex_val', 'con_val'])
        stats = {a: rng.randint(6, 14) for a in ABILITIES}
        stats[primary] = min(30, 14 + int(n // 2) + rng.randint(0, 2))
        stats['con_val'] = max(stats['con_val'], 10 + int(n // 3))
        traits = rng.sample(MONSTER_TRAITS, 2)
        attacks = rng.sample(MONSTER_ATTACKS, 2)
        notes = [_fill(t, Dmg=dmg.capitalize(), dmg=dmg, atk=atk, dc=dc,
                       dice=dice, mod=prof, aura=max(1, dice - 1),
                       breath=dice + 2, regen=5 + int(n))
                 for t in traits + attacks]
        # Compound-style parts ('Ash'+'fang Stalker') join directly; full-word
        # parts ('Cursed'+'Hall Sentinel') get a space.
        first, second = rng.choice(g['monster_first']), rng.choice(g['monster_second'])
        out.update({
            'name': first + (' ' if second[:1].isupper() else '') + second,
            'monster_type': rng.choice(g['monster_types']),
            'size': size,
            'alignment': rng.choice(g['alignments']),
            'speed': str(rng.choice([4, 6, 6, 8])),
            'languages': rng.choice(g['languages']),
            'notes': '\n'.join(notes),
            **stats,
        })
    elif kind == 'vehicle':
        out['hp_max'] = int(out['hp_max'] * 1.5)          # vehicles run tanky
        crew = rng.choice([1, 2, 4, 8, 20, 40])
        notes = [
            _fill(VEHICLE_NOTES[0], crew=crew, pax=crew * rng.choice([1, 2, 4]),
                  cargo=rng.choice([1, 5, 10, 50, 100])),
            _fill(rng.choice(VEHICLE_NOTES[1:3]), atk=atk, dice=dice + 1,
                  station=rng.choice(g['stations'])),
            _fill(VEHICLE_NOTES[3], threshold=5 + int(n)),
            VEHICLE_NOTES[4],
        ]
        out.update({
            'name': 'The ' + rng.choice(g['ship_first']) + ' ' + rng.choice(g['ship_second']),
            'monster_type': rng.choice(g['vehicle_types']),
            'size': rng.choice(['Large', 'Huge', 'Gargantuan']),
            'alignment': 'unaligned',
            'speed': rng.choice(g['vehicle_speeds']),
            'languages': '—',
            'notes': '\n'.join(notes),
            'str_val': min(30, 16 + int(n)), 'dex_val': rng.randint(4, 10),
            'con_val': min(30, 14 + int(n)), 'int_val': 0, 'wis_val': 0, 'cha_val': 0,
        })
    else:  # asset
        first, second = rng.choice(g['asset_names'])
        notes = [
            _fill(rng.choice(ASSET_NOTES[:2]), threshold=3 + int(n // 2)),
            _fill(ASSET_NOTES[3], dc=dc),
            rng.choice([ASSET_NOTES[2], ASSET_NOTES[4]]),
        ]
        out.update({
            'name': first + ' ' + second,
            'monster_type': rng.choice(g['asset_types']),
            'size': rng.choice(['Medium', 'Large', 'Huge', 'Gargantuan']),
            'alignment': 'unaligned',
            'speed': '0',
            'languages': '—',
            'notes': '\n'.join(notes),
            'str_val': 0, 'dex_val': 0,
            'con_val': min(30, 12 + int(n)), 'int_val': 0, 'wis_val': 0, 'cha_val': 0,
        })
    return out

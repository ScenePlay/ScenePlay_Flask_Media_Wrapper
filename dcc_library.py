"""Built-in Dungeon Crawler Carl reference data (Skills, Races, Classes).

Seeded into the same library tables the 5e API sync fills
(tblSkillsLibrary / tblRacesLibrary / tblClassesLibrary) so the character
sheet pickers, the relay/portal library and Backup → Restore/Merge all treat
them like any other library row. Rows are keyed by `api_index` ('dcc:<slug>')
with `source='dcc'` and `game_system='dcc'`; the seed is insert-if-missing and
versioned (VERSION below, recorded in tblAppSettings.dcc_library_version), so
edits you make to a seeded row are never overwritten and a boot is a no-op
once the version has been applied. Deleting a seeded row keeps it gone until
the version is bumped or "Restore built-in DCC entries" is used.

Everything here is a MECHANICAL summary in our own words (stat, category,
ranges, damage dice, what a success does). The rulebook's descriptive text is
Renegade's — it is not copied.

Skills: (name, category, stat, description)
  category: Attack | Spell | Utility | Passive   (Passive = never rolled)
  stat:     STR | DEX | CON | INT | CHA | ''     (the Stat Mod the Check adds)
Races:  name, size, move, stats ("+5 DEX, -2 CON"), skills (list of "+N Name"),
        notes (other benefits, one per line), prereq
Classes: name, types ("Bard, Rogue"), earth (bool), stats, skills, notes, prereq
"""

VERSION = 3   # 2: PDF column-layout corrections; 3: item libraries (weapons/armor/gear/magic)

DCC_SOURCE = 'dcc'


def _slug(name):
    return ''.join(ch if ch.isalnum() else '-' for ch in name.lower()).strip('-')


def api_index(kind, name):
    return f'dcc:{kind}:{_slug(name)}'


# ── Skills ───────────────────────────────────────────────────────────────────
A, S, U, P = 'Attack', 'Spell', 'Utility', 'Passive'

SKILLS = [
    # Animal crawler & pet strikes
    ('Bite',            A, 'STR', 'Melee. 1d8 + Str Piercing. Needs an appendage to clamp onto.'),
    ('Slice Attack',    A, 'DEX', 'Melee (claws). 1d4 + Str Slashing. AI Favor 1.'),
    ('Back Claw',       A, 'STR', 'Melee. 1d6 + Str Slashing; Rank 15 adds Blood Trail.'),
    # Bashing / edged weapons
    ('Club',            A, 'STR', 'Melee. 1d6 + Str Bludgeoning.'),
    ('Axe',             A, 'STR', 'Melee. 1d6 + Str Slashing.'),
    ('Improvised Weapons', A, 'STR', 'Melee. 1d4 + Str Bludgeoning with any 1 lb–Str lb object. AI Favor 1.'),
    ('Dagger',          A, 'DEX', 'Melee. 1d4 + Str Piercing. AI Favor 1. Rank 5 ignores DR.'),
    ('Longsword',       A, 'STR', 'Melee, two hands. 1d8 + Str Slashing.'),
    ('Warhammer',       A, 'STR', 'Melee, two hands. 1d10 + Str Bludgeoning.'),
    ('Rapier',          A, 'DEX', 'Melee. 1d6 + Dex Piercing; Evade buffs at Rank 10 and 15.'),
    # Hand-to-hand
    ('Unarmed Combat',  A, 'STR', 'Melee. 1d4 + Str Bludgeoning. Every crawler starts with this. AI Favor 1. No Damage Effects.'),
    ('Pugilism',        A, 'DEX', 'Melee punches. 1d2 + Str Bludgeoning. May add Dirty Fighting, Iron Punch or Powerful Strike. AI Favor 2 without an Effect.'),
    ('Foot Soldier',    A, 'STR', 'Melee kicks. 1d4 + Str Bludgeoning. May add Powerful Strike or Smush. AI Favor 1 without an Effect.'),
    ('Noggin Nocker',   A, 'STR', 'Melee headbutt. 1d4 + Con Bludgeoning; you lose 1 Health Bar slot on a hit until Rank 5. May add Skullcracker or Powerful Strike.'),
    ("Wrasslin'",       A, 'STR', 'Melee grapple, two hands. 1d4 + Str Bludgeoning; target gains Held. May add Choke Out, Dirty Fighting or Toss.'),
    # Hand-to-hand Damage Effects (Passive add-ons)
    ('Choke Out',       P, '',    "Wrasslin' Damage Effect. ×2 total damage when the target is at 10% Health Bar or less (threshold rises with Rank)."),
    ('Iron Punch',      P, '',    'Pugilism Damage Effect. +1d2 base damage; Rank 10 can Stun instead of damage.'),
    ('Powerful Strike', P, '',    'Foot Soldier / Noggin Nocker / Pugilism Damage Effect. Multiply base damage dice by your Rank. Cooldown 30 hours.'),
    ('Dirty Fighting',  P, '',    "Pugilism / Wrasslin' Damage Effect. Target gains Woozy. Lose 1 Popularity on a Critical Fail."),
    ('Skullcracker',    P, '',    'Noggin Nocker Damage Effect. +1d4 base damage vs same-size targets; Stunned at Rank 10.'),
    ('Smush',           P, '',    'Foot Soldier Damage Effect. ×2 total damage vs targets at 20% Health Bar or less. Once per round.'),
    ('Toss',            P, '',    "Wrasslin' Damage Effect. +1d8 + Str Bludgeoning, ends Held, throws a smaller target 5 ft per 5 Ranks."),
    # Ranged
    ('Crossbow',        A, 'DEX', 'Ranged 50 ft, two hands, ammo, once per round. 1d8 Piercing.'),
    ('Bow',             A, 'DEX', 'Ranged 100 ft, two hands, ammo. 1d6 + Str Piercing.'),
    ('Handgun',         A, 'DEX', 'Ranged 150 ft, ammo; reload after a Major Fail. 1d8 Piercing.'),
    ('Javelin',         A, 'DEX', 'Ranged 40 ft. 1d8 + Str Piercing; Rank 10 ignores DR.'),
    ('Shotgun',         A, 'DEX', 'Ranged 30 ft, two hands, ammo; reload after a Major Fail. 1d10 Piercing; Rank 15 adds 5 ft Splash.'),
    ('Shuriken',        A, 'DEX', 'Ranged 30 ft. 1d4 + Str Piercing. AI Favor 1. Extra attacks at Rank 10/15.'),
    ('Slingshot',       A, 'DEX', 'Ranged 30 ft, two hands. 1d2 + Str Bludgeoning. AI Favor 2.'),
    # Reach
    ('Herding Weapons', A, 'STR', 'Reach 10 ft, two hands. 1d4 + Str Bludgeoning; can slide targets. AI Favor 1.'),
    ('Lance',           A, 'STR', 'Reach 10 ft, must be mounted. 1d12 + Str Piercing; bonus for mount movement.'),
    ('Polearm',         A, 'STR', 'Reach 10 ft, two hands. 1d8 + Str Piercing; grants Zone of Control ranks at 10/15.'),
    ('Quarterstaff',    A, 'STR', 'Reach 10 ft, two hands. 1d6 + Str Bludgeoning; Evade buffs at Rank 10/15.'),
    # Utility
    ('Acute Ears',      P, 'INT', 'Better hearing and more Mob info on your HUD minimap; higher Ranks stop Ambushes on your party.'),
    ('Aiming',          P, '',    'Ranged attacks only: add your Ranks to hit by rolling with Disadvantage; +1d4 damage on a hit.'),
    ('Alchemy',         U, 'INT', 'Craft potions and poisons (up to +5 bonus level; more at Rank 5+). See Crafting.'),
    ('Ambush',          U, 'INT', 'Int-Opposed. On Success gain a surprise Action before combat and attack with Advantage.'),
    ('Animal Handling', U, 'CHA', 'Int-Opposed. On Success the animal is friendly enough not to attack; higher Ranks speed up pet bonding.'),
    ('Arcane',          U, 'INT', 'Unopposed. Tell whether an item is magical; Rank 5 reads its Rank/bonus, Rank 10 imbues spells at an Arcanist Table.'),
    ('Attack of Opportunity', P, '', 'Interrupt. When a foe leaves a space next to you (not by Step), spend an Action to attack it. One-handed melee weapon, 5 ft.'),
    ('Backfire',        U, 'INT', 'Compensated Anarchist only. Unopposed. Neutralise (10 min) or take apart (1 hr) a trap without a Sapper\'s Table.'),
    ('Balance',         U, 'DEX', 'Unopposed. Keep your footing on tricky surfaces; Rank 5 ignores difficult terrain.'),
    ('Basic Science',   U, 'INT', 'Unopposed, 2-hour experiment. On Success you learn or confirm something.'),
    ('Bomb Surgeon',    U, 'INT', 'Unopposed, 1 hour. Take a bomb apart into a half-size bomb or parts.'),
    ('Calligraphy',     U, 'DEX', 'Unopposed. Documents that impress; Rank 10 crafts scrolls.'),
    ('Cartography',     U, 'INT', 'Unopposed. Work out where you are; higher Ranks help the party navigate.'),
    ('Cat-like Reflexes', U, 'DEX', 'Cat-based Races only. +10 ft Move; use instead of a Dexterity Stat Check.'),
    ('Catcher',         P, '',    'Interrupt. Take a direct hit meant for an adjacent ally (you may Step 10 ft first). No Evade against it.'),
    ('Cesta Punta',     U, 'DEX', 'Earth Hobby Potion only. Jai alai and throwing with the xistera at long range.'),
    ('Character Actor', P, 'CHA', 'Former Child Actor only. Each floor gain a random spread of a new Class\'s abilities. Rank rises only on descent.'),
    ('Chopper Pilot',   U, 'DEX', 'Unopposed. Stunts and chases on a motorcycle; Disadvantage to attack while piloting until Rank 10.'),
    ('Climbing',        U, 'STR', 'Unopposed, once per minute. Dangerous climbs; Disadvantage to attack while climbing until Rank 10.'),
    ('Cockroach',       U, 'CON', 'Limited (Race/Class/item). Once per scene, when dropped to 0% roll to stay at 10% instead.'),
    ('Cooking',         U, 'INT', 'Unopposed, 1 hour. Feed the party; Rank 10 gives the "You are full!" healing Buff.'),
    ('Deception',       U, 'CHA', 'Int-Opposed (Disadvantage vs Detect Lies). On Success they believe you.'),
    ('Detect Lies',     U, 'INT', 'Cha-Opposed (Disadvantage vs Deception). Sense whether someone is lying.'),
    ('Detect Trap',     U, 'INT', 'Unopposed (Disadvantage scanning a whole room or while moving). Sense a non-magic trap; Rank 5 finds magical ones.'),
    ('Determine Value', P, '',    'Magic-only advancement. Sort your Inventory by value; Rank 15 shows gold values.'),
    ('Diplomacy',       U, 'CHA', 'Int-Opposed vs the higher Int side. Get two parties talking.'),
    ('Dodge',           P, '',    '+1 Evade Buff (more at 5/10/15); Rank 15 Evades without spending an Action. Advances by Evading until Rank 5.'),
    ('Double Tap',      P, '',    'Declare at the start of a round and spend every Action on one target with one weapon: an Amazing first hit upgrades the second to a Critical.'),
    ('Driving',         U, 'DEX', 'Unopposed. Chases and stunts in a vehicle; Disadvantage to attack while driving until Rank 5.'),
    ('Dumpster Diving', U, 'INT', 'Unopposed, 1 hour per 50 ft square. Find something useful in the clutter.'),
    ('Endurance',       U, 'CON', 'Unopposed. Keep going while grinding or marching without the Fatigued Debuff.'),
    ('Engineering',     U, 'INT', 'Unopposed. Build mundane things with moving parts, fluids or chemicals from Misc. Junk.'),
    ('Escape Artist',   U, 'DEX', 'Unopposed (Str-Opposed to escape being Held). Slip bonds and holds.'),
    ('Escape Plan',     P, '',    'Magic-only advancement. Your HUD shows hidden doors and passages; higher Ranks reveal system signs and sigils.'),
    ('Explosives Handling', U, 'INT', 'Unopposed. Handle standard explosives safely; Rank 10 crafts them at a Sapper\'s Table.'),
    ('Fabricate',       U, 'INT', 'Unopposed. Make mundane items without moving parts from Misc. Junk.'),
    ('Find Crawler',    P, '',    'Magic-only advancement. Other crawlers within 1,000 ft show on your HUD (further at higher Ranks).'),
    ('Find Trap',       P, '',    'Traps within 5 ft appear on your HUD a second before triggering; earlier and further at higher Ranks.'),
    ('First Aid',       U, 'INT', 'Unopposed, once per patient per rest. Heal 1 Health Bar slot (+1 per higher degree of success); mends injuries at Rank 5+.'),
    ('Gear Head',       U, 'INT', 'Limited. Build high-performance engines and custom vehicles (needs an Engine Stand).'),
    ('Goblin Explosives', U, 'INT', 'Unopposed; Critical Fail on a natural 1–4. Handle unstable goblin explosives.'),
    ('Good First Impression', U, 'CHA', 'Int-Opposed vs a non-hostile Mob or NPC. On Success it approaches with wary curiosity instead of attacking.'),
    ('Hide in Shadows', U, 'DEX', 'Int-Opposed while still in deep shadow or cover. On Success you are invisible to Mobs and HUDs until you act.'),
    ('Improvised Explosive Device', U, 'INT', 'Craft bombs and traps without a Sapper\'s Table (needs an Explosives Handling Check to avoid mishaps).'),
    ('Incendiary Device Handling', U, 'INT', 'Unopposed. Handle incendiaries safely; Rank 10 crafts them.'),
    ('Infusion',        U, 'INT', 'Transfer a potion\'s effect onto consumable items (needs an Infusion Station).'),
    ('Intimidate',      U, 'STR', 'Cha-Opposed (Disadvantage once hostilities start). On Success the target is Staggered.'),
    ('Investigation',   U, 'INT', 'Unopposed, 10 minutes. Make sense of an area or puzzle; Look for Clues costs one Action.'),
    ('Iron Stomach',    U, 'CON', 'Unopposed. Eat a magic item; an Amazing Success grants permanent Intelligence.'),
    ('Jumping',         U, 'STR', 'Unopposed with a 10 ft run-up. Leap Rank + Str feet.'),
    ('Leadership',      U, 'CHA', 'Int-Opposed. Coordinate several parties in a Boss fight: Advantage on their first attack.'),
    ('Light on Your Feet', U, 'DEX', 'Animals only. Leap Rank ×2 feet with height Dex ×2; gliding at Rank 15.'),
    ('Lockpicking',     U, 'DEX', 'Unopposed (Disadvantage without tools), Floor number in minutes. Open the lock.'),
    ('Lore',            U, 'INT', 'Unopposed. Know a little about a neighbourhood, its Mobs or the locals.'),
    ('Negotiation',     U, 'CHA', 'Int-Opposed, 5 minutes. Move a price 10% in your favour (more at higher Ranks).'),
    ('Pathfinder',      P, '',    'Magic-only advancement. Your HUD map zooms out ×Rank; Rank 15 shows Mobs on it.'),
    ('Perception',      U, 'INT', 'Unopposed. Notice details others miss; also used for Look for Clues.'),
    ('Performance',     U, 'CHA', 'Unopposed (rivals add their Cha). Command the stage in your chosen specialty.'),
    ('Persuasion',      U, 'CHA', 'Int-Opposed, ~10 minutes of talk. They follow your suggestion if it is not too costly, dangerous or out of character.'),
    ('Regeneration',    P, '',    'Heal 1 Health Bar slot every round (every other round if your Rank is below your Con).'),
    ('Religion',        U, 'INT', 'Unopposed. Know a god and its followers\' practices.'),
    ('Repair',          U, 'INT', 'Unopposed, 2 hours. Fix damaged simple items; Rank 15 rebuilds destroyed ones.'),
    ('Riding',          U, 'DEX', 'Unopposed in action scenes (mount may panic). Stay in the saddle; Disadvantage to attack while riding until Rank 5.'),
    ('Ropework',        U, 'DEX', 'Unopposed. Knots and lassos; Rank 5 makes it a 10 ft Attack that Holds.'),
    ('Running',         U, 'DEX', 'Unopposed once per minute (+1 per 10 ft of Move). Sprints, races and chases; permanent Move buffs at higher Ranks.'),
    ('Salvage',         U, 'INT', 'Unopposed, 1 hour. Recover half the raw materials from deconstructed or failed crafts.'),
    ('Scutelliphily',   U, 'INT', 'Limited. Identify patches and their bonus; sew and craft enchanted patches at higher Ranks.'),
    ('Shield Block',    U, 'STR', 'Interrupt, needs a shield. Roll vs each physical attack; on Success take half damage before DR.'),
    ('Sleight of Hand', U, 'DEX', 'Int-Opposed. Palm hand-sized items unseen; pick pockets at Rank 5.'),
    ('Smithing',        U, 'STR', 'Craft mundane metal items, armour and weapons; bonus levels at Rank 5+.'),
    ('Stealth',         U, 'DEX', 'Int-Opposed, start out of sight. Move unseen or surprise a Mob (one free non-Attack Action).'),
    ('Streetwise',      U, 'CHA', 'Unopposed in populated areas. Rumours, contacts, fences and keeping a low profile.'),
    ('Survival',        U, 'CON', 'Unopposed while travelling harsh places. Avoid hunger and thirst effects.'),
    ('Swimming',        U, 'STR', 'Unopposed every 30 seconds when it matters. Fatigued after 1 minute or a Major Fail.'),
    ('Tactics',         U, 'INT', 'Unopposed, once per combat. Party gains +1 to Attack, Damage or Evade Checks (+1 per higher degree).'),
    ('Tattoo Artistry', U, 'DEX', 'Ink mundane tattoos; magical ones via Crafting at higher Ranks.'),
    ('Taunt',           U, 'CHA', 'Interrupt, Int-Opposed. Pull one Mob attack within 30 ft onto yourself (more on higher successes).'),
    ('Throwing',        U, 'STR', 'Throw up to Str lb up to Str ×10 ft. Unopposed to hit an area, Attack vs Evade to hit a foe; d8 scatter on a miss.'),
    ('Tracking',        U, 'INT', 'Unopposed. Find and follow tracks; re-check every 15 minutes.'),
    ('Trap Engineer',   U, 'INT', 'Craft traps at a Sapper\'s Table with a Trap Module.'),
    ('Zone of Control', P, '',    'Needs a Reach weapon. Once per round, Interrupt-attack (with Disadvantage until Rank 5) the first foe to move adjacent.'),
    # Spells (Spell skills; Mana = Intelligence). Attack spells roll vs Evade; Passive spells just happen.
    ('Air Buddy',       S, 'INT', 'Passive, Favored: Mage. 12 Mana. Launch yourself 10 × Int Mod feet; double-jump by casting twice.'),
    ('Astral Paw',      S, 'INT', 'Passive. 5 Mana, 5 min. A spectral hand that manipulates objects up to 30 ft away.'),
    ('Bang Bro',        S, 'INT', 'Passive. 12 Mana, until combat ends. Held weapon deals +2 Fire and Electric.'),
    ('Bad Faith',       S, 'CHA', 'Attack, Necrotic, Favored: Cleric. 26 Mana, 40 ft. 1d8 + Cha Necrotic; Splash at Rank 5.'),
    ('Clockwork Triplicate', S, 'INT', 'Passive. 10 Mana, 5 ft. Your pet or minion splits into three for 1 min per Rank.'),
    ('Confusing Fog',   S, 'INT', 'Passive. 6 Mana, 40 ft, 2 rounds. A 25 ft fog your party sees through; Mobs attack with Disadvantage.'),
    ('Drain Life',      S, 'INT', 'Attack, Necrotic. 14 Mana, 30 ft. 1d6 + Int Necrotic; heals you at Rank 5+.'),
    ('Earworm',         S, 'CHA', 'Attack, Sonic, Favored: Bard. 6 Mana, 30 ft, once per round. 1d6 + Cha Sonic.'),
    ('Dirt Clod',       S, 'INT', 'Attack, Bludgeoning. 1 Mana, 100 ft. 1d2 + Int. AI Favor 2.'),
    ('Fear',            S, 'INT', 'Attack, Mind Control. 3 Mana, 25 ft. A non-Boss Mob of half your level or less loses its Dex Mod or flees.'),
    ('Fire Fingers',    S, 'INT', 'Attack, Fire. 3 Mana, melee. 1d4 + Int Fire. AI Favor 1.'),
    ('Frost Scar',      S, 'INT', 'Attack, Ice. 2 Mana, melee. 1d4 + Int Ice; target cannot self-heal next round at Rank 5.'),
    ('Fireball',        S, 'INT', 'Attack, Fire, Area of Effect. 45 Mana, 80 ft, once per scene. 1d12 + Int Fire in a 10 ft Blast (rolled with Disadvantage).'),
    ('Grand Illusion',  S, 'INT', 'Int-Opposed. 7 Mana, 40 ft, 2 min, 15 min cooldown. Foes who see it believe it.'),
    ('Heal',            S, 'INT', 'Heal, Interrupt, Passive. 1 Mana, self only, Rank 1 maximum. Heal 2 Health Bar slots. Every crawler starts with it.'),
    ('Heal Self',       S, 'INT', 'Heal, Interrupt, Passive. 2 Mana, self only. Heal 1d4 slots (1d6 at Rank 5, 2d6 at Rank 10).'),
    ('Heal Others',     S, 'INT', 'Heal, Interrupt, Passive. 6 Mana, 30 ft, not yourself. Target heals 1d4 slots (more at higher Ranks; party burst at 15).'),
    ('Heal Critter',    S, 'INT', 'Heal, Interrupt, Passive. 8 Mana, 30 ft, pets and minions only. Heal to 100%.'),
    ('Hole',            S, 'INT', 'Passive. 12 Mana, 10 ft, 5 min. A 2 ft-wide hole, 1 inch deep per Rank, through a surface.'),
    ('Holy Aura',       S, 'CHA', 'Attack, Holy, Area of Effect, Favored: Cleric & Paladin. 7 Mana, 5 ft Burst, once per round. 1d4 + Cha Holy to enemies around you.'),
    ('Hot Stuff Aura',  S, 'INT', 'Passive, Area of Effect, Favored: Bard. 8 Mana, 5 ft Burst, 2 rounds. A shield of Cha Mod slots (2 each) for you and allies.'),
    ('Ice Blast',       S, 'INT', 'Attack, Ice. 9 Mana, 40 ft. 1d8 + Int Ice; pushes at Rank 10, cone at Rank 15.'),
    ('Icicles',         S, 'INT', 'Attack, Ice. 19 Mana, 60 ft. 1d12 + Int Ice; Armor-Piercing at Rank 15.'),
    ('Intimate Touches', S, 'CHA', 'Heal, Passive (not an Interrupt), Favored: Cleric & Paladin. 8 Mana, 5 ft. Heal Cha Mod slots; mends injuries at higher Ranks.'),
    ('Lightning Bolt',  S, 'INT', 'Attack, Electric. 15 Mana, 100 ft. 1d10 + Int Electric; Line at Rank 10, forks at Rank 15.'),
    ('Magic Missile',   S, 'INT', 'Attack, Force. 5 Mana, line of sight. 1d4 + Int Force. AI Favor 1. Variable Mana at Rank 5.'),
    ('Mind Tickle',     S, 'CHA', 'Attack, Psychic, Favored: Cleric. 2 Mana, 40 ft. 1d2 + Cha Psychic. AI Favor 2.'),
    ('Minion Army',     S, 'INT', 'Area of Effect, Mind Control. 50 Mana, 50 ft Burst, 5-minute cast, 5-hour cooldown. 1 in 50 Mobs (min 1) become allies.'),
    ("Nature's Breath", S, 'INT', 'Heal, Interrupt, Passive, Favored: Druid. 6 Mana, 5 ft. Heal a Rank damage die of slots (pets too).'),
    ('Oakhide',         S, 'INT', 'Passive, Favored: Druid. 5 Mana, self, 2 min, 10 min cooldown. +2 DR (+2 per upgrade).'),
    ("Paladin's Smite", S, 'CHA', 'Attack, Holy, Favored: Paladin. 11 Mana, 30 ft. 1d8 + Cha Holy; Take Down at Rank 10, Armor-Piercing at 15.'),
    ('Panty Dropper',   S, 'CHA', 'Mind Control, Int-Opposed, Favored: Bard. 10 Mana, 10 ft, 2 min. A non-Boss target stops fighting to pursue you.'),
    ('Ping',            S, 'INT', 'Passive, Area of Effect. 5 Mana, 1 mile Burst, 5 min cooldown. Locate all non-crawler Mobs around you.'),
    ('Protective Shell', S, 'INT', 'Interrupt, Passive, Area of Effect. No Mana, 10 ft Burst, 30-hour cooldown; must be imbued on worn gear. A shell pushes Mobs away and blocks one physical attack.'),
    ('Puddle Jumper',   S, 'INT', 'Passive. 20 Mana, line of sight, 10 s delay, 5-hour cooldown. Teleport you and up to 3 party members.'),
    ('Rise, Dead Minion!', S, 'INT', 'Attack, Favored: Necromancer. 10 Mana, 30 ft, 1 round. A skeleton attacks for 1d8 + Int Necrotic then collapses.'),
    ('Rootfoot',        S, 'INT', 'Attack, Favored: Druid. 5 Mana, 30 ft, 2 rounds. Roots Hold a target up to Size 4; escape vs the Spell\'s Rank.'),
    ('Second Chance',   S, 'INT', 'Passive. 10 Mana, 10 ft, 1 min. Raise a lower-level Mob as a temporary Undead Minion with half its slots.'),
    ('Shield',          S, 'INT', 'Interrupt, Passive. 8 Mana, self, 5 min. A force field with 2 Health Bar slots (Con Mod each) that absorbs non-magic damage first.'),
    ('Shock Treatment', S, 'INT', 'Attack, Electric. 2 Mana, 30 ft. 1d2 + Int Electric. AI Favor 2. Can Stun instead at Rank 5.'),
    ('Solsplash',       S, 'CON', 'Attack, Fire, Favored: Druid. 13 Mana, 30 ft. 1d8 + Con Fire; Splash at Rank 5+.'),
    ('Soul Collector',  S, 'INT', 'Attack, Necrotic. 4 Mana, 50 ft. 1d4 + Int Necrotic. AI Favor 1. Killing blows stack a damage bonus at Rank 5+.'),
    ('Thunderlash',     S, 'INT', 'Attack, Sonic. 12 Mana, 50 ft. 1d10 + Int Sonic; Armor-Piercing at Rank 10, cone at 15.'),
    ('Torch',           S, 'INT', 'Passive. 1 Mana, self, until a saferoom or the next floor. A light orb: 20 ft bright, 20 ft dim.'),
    ('Tripper',         S, 'INT', 'Passive, Area of Effect. No Mana, 30 ft Burst, 5-hour cooldown; imbued on worn gear. Sets off every movement/heat/weight trap in the area.'),
    ('Turn Undead',     S, 'CHA', 'Attack, Area of Effect, Cha-Opposed, Favored: Bard, Cleric & Paladin. 9 Mana, 10 ft Cone, 3 rounds, 5 min cooldown. Undead Mobs flee.'),
    ('Twinkle Toes',    S, 'INT', 'Passive. 2 Mana, 5 ft, Intelligence seconds. A pet or minion has Move ×2.'),
    ('Unnecessary Force', S, 'INT', 'Attack, Force. 13 Mana. 1d12 + Int Force; pushes the target at Rank 10+.'),
    ('Vine Porn',       S, 'CON', 'Attack, Piercing, Favored: Druid. 3 Mana, 20 ft. 1d4 + Con Piercing. AI Favor 1. Armor-Piercing at Rank 10.'),
    ('Wall of Fire',    S, 'INT', 'Passive, Fire. 15 Mana, 30 ft, 2 rounds. A 30 × 7 × 2 ft wall: 1d2 Fire per foot crossed plus Burned.'),
    ('Water Breathing', S, 'INT', 'Passive. 2 Mana, self, Intelligence ×3 seconds. Breathe underwater; others at Rank 5+.'),
    ("Wilbur's Slow-Build Fireblast", S, 'INT', 'Attack, Fire. 60 Mana, 50 ft. 1d8 + Int Fire plus Burned; can be held as a ring and grows while held.'),
    ('Wisp Armor',      S, 'INT', 'Passive. 5 Mana, self, 5 min, 5 min cooldown. Magic damage against you is reduced to Rank-1 base; immune to Mind Control.'),
    ('Web',             S, 'INT', 'Attack. 6 Mana, 20 ft Cone, 2 rounds. Everyone in the cone rolls Evade or is Held; escape vs the Spell\'s Rank.'),
]

SKILL_INDEX = {name: (cat, stat, desc) for name, cat, stat, desc in SKILLS}


# ── Races ─────────────────────────────────────────────────────────────────────
# stats: "+5 DEX, -3 STR"; skills: "+2 Climbing"; notes: other benefits.
RACES = [
    dict(name='Arachnid', size='Medium (4)', move=20, earth=True,
         stats='+5 DEX', skills=['+3 Web (Spell)', '+2 Climbing', '+2 Perception', '+2 Performance'],
         notes=['Web costs half Mana', 'Innate Climb Move equal to your Move, no Checks unless under duress',
                'Performance specialty: stringed instrument'], prereq=''),
    dict(name='Amazonian', size='Medium (4)', move=20, earth=True,
         stats='+6 STR, +3 DEX', skills=['+2 Bow', '+2 Endurance', '+2 Pugilism'],
         notes=['+2 DR', 'Each floor: a coupon for one free Weapon Training Guild session'],
         prereq='A Strength- or Dexterity-based Skill at Rank 5+'),
    dict(name='Cat', size='Small (2), Animal', move=20, earth=True,
         stats='+4 DEX, +2 CON, +1 CHA, -3 STR', skills=['+3 Cat-like Reflexes', '+2 Slice Attack'],
         notes=['Toxoplasma G.: once per day allies get Rank 5 Catcher (with +5 DR) for a round to protect you; they gain 1 AI Favor',
                'See in total darkness', 'Nine Lives: half damage from the first 9 attacks each day', 'Advantage on Cat-like Reflexes Checks',
                'Disadvantage on Charisma Checks with other felines (not Cat Girls/Boys)', 'Vulnerable to Dogs and Beasts (double damage)'],
         prereq='Only for crawlers who are already a Cat'),
    dict(name='Cat Girl/Cat Boy', size='Medium (4)', move=20, earth=True,
         stats='+3 DEX, +3 CHA, -2 CON',
         skills=['+2 Cat-like Reflexes', '+2 Good First Impression', '+2 Light on Your Feet', '+2 Slice Attack'],
         notes=['Slice Attacks may add Cha Mod to damage instead of Str'], prereq=''),
    dict(name='Changbi Demon', size='Medium (4)', move=20, earth=True,
         stats='+5 DEX, +3 STR, +3 CON, -2 CHA', skills=['+3 Ambush', '+3 Creepy Chains (Club)'],
         notes=['Creepy Chains: any chain is a Club weapon with 10 ft range; lengthen/shorten it 50% once per scene',
                'Foes who touch your bare skin take 1d4+F Acid', 'No need to breathe', 'Vulnerable to Holy damage', 'Cannot worship a deity'],
         prereq=''),
    dict(name='Changeling', size='Large (5)', move=20, earth=True,
         stats='+3 CHA, +2 INT', skills=['+2 Ambush', '+2 Deception', '+1 Escape Artist'],
         notes=['Advantage on Deception when no talking is needed', 'Shapeshift into any Race you have touched (Unopposed Deception Check); gain its non-stat, non-skill benefits',
                'Free access to organisations by impersonating other crawlers', "Can't touch mimic-type creatures"], prereq=''),
    dict(name='Crocodilian', size='Large (5)', move=20, earth=True,
         stats='+4 STR, +3 CON', skills=['+2 Pugilism', '+2 Powerful Strike'],
         notes=['+3 DR Buff', 'Advantage on Intimidate when physically menacing in person', '+1 to all Skill Checks for 1 hour after a full meal',
                'Disadvantage on Charisma Checks while Fatigued'], prereq=''),
    dict(name='Doppelgänger', size='Unchanged (changes when shifting)', move=20, earth=True,
         stats='+4 CON, +3 STR', skills=['+1 Deception', '+1 Endurance'],
         notes=['+2 DR', 'Lift by Constitution instead of Strength', 'Advantage on Escape Artist, even while Held or watched',
                'Once per scene incorporate a held weapon for +Con Mod damage (cannot be disarmed)',
                'Shape-change into any form of similar mass (costs 1 Health Bar slot; Unopposed Deception to copy something specific)'], prereq=''),
    dict(name='Dwarf, Classic', size='Medium (4)', move=20, earth=True,
         stats='+4 CON, +2 INT, -2 CHA', skills=['+3 crafting Skill (choose)', '+3 crafting Skill (choose another)', '+2 Endurance'],
         notes=['See in total darkness', 'All crafting Skills can reach Rank 20', 'Disadvantage on Charisma Checks with elves and fairies'], prereq=''),
    dict(name='Dwarf, Fathom', size='Medium (4)', move=20, earth=True,
         stats='+3 CON, +2 STR', skills=['+3 Engineering', '+2 Dumpster Diving', '+2 Salvage'],
         notes=['Advantage on d20 Checks involving earth, rock and dirt', 'A head-lizard casts a 15 ft cone of light (easily replaced)'], prereq=''),
    dict(name='Elf, High', size='Medium (4)', move=20, earth=True,
         stats='+4 INT, +4 DEX, +4 CHA', skills=['+2 Intimidate', '+1 Lore'],
         notes=['Intimidate may use your Cha Mod', 'Mana recovers twice as fast in a natural environment', 'Add 1d4 to Evade Checks',
                'Disadvantage on Charisma Checks with Dwarves, Rat-Kin or anyone smelly or dirty', 'Two Charisma-based Skills of your choice can reach Rank 20'], prereq=''),
    dict(name='Elf, City', size='Medium (4)', move=20, earth=True,
         stats='+6 split between INT, DEX and CHA', skills=['+3 Good First Impression', '+2 Negotiation', '+2 Streetwise'],
         notes=['Once per floor (Long Rest) reassign the split points between Int, Dex and Cha',
                'First Charisma Check in a new settlement has Advantage; an Amazing Success makes a permanent contact'], prereq=''),
    dict(name='Elf, Night', size='Medium (4)', move=20, earth=True,
         stats='+3 INT, +3 DEX', skills=['+3 Acute Ears', '+3 Hide in Shadows'],
         notes=['See in total darkness', 'Advantage on Hide in Shadows at night', 'Once per day a shadow Taunts (Rank = Floor) to pull attacks off you',
                'Hide in Shadows and one crafting Skill can reach Rank 20'], prereq=''),
    dict(name='Frost Maiden', size='Petite (3)', move=20, earth=True,
         stats='+2 CHA, +2 INT, +2 DEX', skills=['+2 Persuasion'],
         notes=['Melee attacks deal +1d4 Ice', 'Advantage on Int and Con Stat Checks', 'Your Game Guide becomes your Manager',
                'Flight for up to 1 minute per scene', 'Immune to mental infirmity'], prereq=''),
    dict(name='Human', size='Medium (4)', move=20, earth=True,
         stats='+2 STR, +2 INT, +2 CON, +2 DEX, +2 CHA', skills=[],
         notes=['At the end of each floor, one Skill Advancement Check (Rank 9 or less) with Advantage', 'Gain 1 AI Favor each time you level up',
                'When hit, spend 1 AI Favor for DR equal to your Con (as often as you have Favor)',
                'Once per day roll an untrained non-Passive Utility Skill as if Rank 2', 'Once per floor spend an Action to remove any one Debuff, even an Injury'],
         prereq=''),
    dict(name='Igneous', size='Large (5)', move=20, earth=True,
         stats='+6 CON, +4 STR, -2 INT, -2 CHA', skills=['+1 Endurance'],
         notes=['+3 DR Buff', 'Once per day double your Move for 20 seconds', 'Con Stat Check as an Action: 1d8+F Fire in a 5 ft Burst',
                'No Survival Checks in harsh heat; can breathe underwater', 'Immune to Fire, vulnerable to Ice', 'Can burrow',
                'Lose 1 Health Bar slot each time you open your Inventory (Hotlist is fine)', 'Disadvantage on Checks to conceal your presence or nature'], prereq=''),
    dict(name='Lajabless', size='Medium (4)', move=20, earth=True,
         stats='+5 INT by day / +5 STR by night', skills=['+3 Weapon Skill (choose)', '+2 Spell (choose)', '+2 Spell (choose another)'],
         notes=['Advantage on Ambush and Intimidate', 'Day: Strength halved, Spells cost half Mana', 'Night: Strength doubled, Spells cost double Mana'],
         prereq=''),
    dict(name='Obsidian Butterfly', size='Medium (4)', move=20, earth=True,
         stats='+3 DEX, +2 INT, -4 CON', skills=['+2 Intimidate', '+2 Slice Attack', '+2 Spell (choose)'],
         notes=['Four wings reach 15 ft to deliver touch/melee Spells', 'May use Cha Mod instead of Con Mod for Health Bar slots', 'Add 1d4 to Evade Checks',
                'Sixth Floor: choose Stronger Wings (flight 2 min/scene, +20 ft Move flying) or Ferocious Visage (Advantage to inspire fear or respect)'],
         prereq='Rank 5+ with any Edged Weapon'),
    dict(name='Primal', size='Unchanged', move=20, earth=True,
         stats='-1 STR, -1 INT, -1 CON, -1 DEX, -1 CHA', skills=[],
         notes=['Hard mode: keep your current Race\'s look, take -1 to every Stat', 'ALL Skills can be raised to Rank 20'], prereq=''),
    dict(name='Rat Hooligan', size='Petite (3)', move=20, earth=True,
         stats='+2 DEX, +1 CON', skills=['+2 Escape Plan', '+2 Stealth', '+1 Bite', '+1 Survival'],
         notes=['Advantage on Checks to resist hunger and thirst', 'Talk to house rats for minimal information indoors', 'May add Dex Mod to Bite damage instead of Str'],
         prereq=''),
    dict(name='Sasquatch', size='Large (5)', move=20, earth=True,
         stats='+6 STR, +6 CON, +2 DEX, -3 INT, -1 CHA', skills=['+3 Foot Soldier', '+3 Smush'],
         notes=['Smush can reach Rank 20'], prereq='Rank 5+ in Smush'),
    dict(name='Tetrakai', size='Medium (4)', move=20, earth=True,
         stats='+6 DEX, -2 CHA', skills=['+2 Pugilism', "+2 Wrasslin'", '+1 all Edged Weapon Skills'],
         notes=['Four Arms: hold four items (or two two-handed weapons)', 'Disadvantage on fine-manipulation Dexterity Skills'], prereq=''),
    dict(name='Tigran', size='Medium (4)', move=30, earth=True,
         stats='+3 DEX, +2 STR, -4 CHA', skills=['+2 Ambush', '+2 Cat-like Reflexes', '+2 Slice Attack'],
         notes=['See in total darkness', '+1 DR Buff', '+10 ft Move', 'Surprise Action melee attacks deal ×2 total damage'], prereq=''),
    # Alien races — no Earth Classes; gain Popularity in specific ways
    dict(name='Bune', size='Medium (4)', move=20, earth=False,
         stats='+3 INT, +2 DEX, -2 CON', skills=['+3 Determine Value', '+3 Fabricate', '+3 Negotiation'],
         notes=['At Level 50: +2 Dex and wings (500 ft flight per scene)', '+1 Popularity on a Critical Hit in combat'],
         prereq='3 or more Popularity'),
    dict(name='Grulke', size='Medium (4)', move=20, earth=False,
         stats='+3 DEX, +2 STR, -2 CHA', skills=['+3 Jumping or Light on Your Feet', '+2 Zone of Control', '+2 Reach Weapon Skill (choose)'],
         notes=['Tongue Lashing: ranged attack, Rank = Floor, Dex to hit, 1d8 + Str Bludgeoning, 30 ft', '+2 DR Grulke breastplate (Torso)',
                'Trolls have Advantage to Wrassle you (and lick you); +1 Popularity when they do or when you Amazing-hit a troll',
                '+1 Popularity when you Critical Hit a larger foe'],
         prereq='Rank 5+ in Jumping or Light on Your Feet'),
    dict(name='Caprid', size='Large (5)', move=20, earth=False,
         stats='+3 INT, +3 CHA, -2 STR', skills=['+3 Find Crawler', '+3 Investigation', '+3 Leadership'],
         notes=['Find Crawler and Persuasion can reach Rank 20', '+1 Popularity on a Critical Hit on a Charisma Skill Check or a non-combat Spell Check'],
         prereq=''),
    dict(name='Hobgoblin', size='Medium (4)', move=20, earth=False,
         stats='+1 DEX, -5 CHA', skills=['+3 all Trap-based and Explosive-based Skills', '+1 Regeneration'],
         notes=['Charisma is capped at 10', 'Free access to Hobgoblin Sapper Workshops',
                'End of each floor: one Explosive/Trap Skill Advancement Check with Advantage', 'Explosive and trap Skills can reach Rank 20',
                '+1 Popularity once per scene when a trap or explosive kills an enemy'],
         prereq='Rank 5+ in Explosives Handling and any Trap-based Skill'),
    dict(name='Pocket Kuma', size='Small (2), Animal', move=20, earth=False,
         stats='+5 DEX, +5 CHA, -4 STR, -4 CON', skills=['+2 Bite', '+2 Dodge', '+2 Slice Attack', '+1 Ambush'],
         notes=['Strength is capped at 10', 'Advantage on all Charisma Checks', 'See in total darkness', 'Take no damage from falling', 'Light on Your Feet can reach Rank 20',
                'Half damage with Strength-based melee weapons', 'Vulnerable to Bludgeoning', '+1 Popularity when you act in the Surprise Round or Critical Fail an Evade'],
         prereq=''),
    dict(name='Pterolykos', size='Medium (4)', move=20, earth=False,
         stats='+4 CHA, +2 DEX', skills=['+3 Bite', '+3 Performance', '+3 Tracking', '+1 Diplomacy'],
         notes=['Wings: flight for up to 50 seconds per scene', 'Disadvantage on Checks to hide emotion or presence (Deception, Stealth)',
                '+1 Popularity on a Critical Hit on a Charisma Skill Check'], prereq=''),
    dict(name='Skyfowl', size='Medium (4)', move=20, earth=False,
         stats='+3 DEX, +3 CHA, -1 STR, -1 CON', skills=['+2 Slice Attack', '+2 all Charisma-based Skills'],
         notes=['Advantage on Perception for things 10+ ft away', 'Flight for up to 3 minutes per scene (Cleric Classes: 10-second hops only)',
                '+1 Popularity on a Critical Hit on Leadership, Perception, Persuasion or Taunt'], prereq=''),
]


# ── Classes ───────────────────────────────────────────────────────────────────
CLASSES = [
    dict(name="Boring Ol' Arcanist", types='Arcanist', earth=False,
         stats='+3 INT, +2 DEX', skills=['+5 Arcane', '+3 Salvage', '+2 crafting Skill (choose)', '+1 crafting Skill (choose)'],
         notes=['Tier 1 Arcanist table', 'Arcane and one crafting Skill can reach Rank 20']),
    dict(name='Alchemist', types='Arcanist', earth=False,
         stats='+3 CON, +3 INT', skills=['+5 Alchemy', '+3 Infusion'],
         notes=['Immune to Poison', 'Tier 1 Alchemy table', 'End of each floor: +1 to Alchemy and Infusion Advancement Checks', 'Alchemy can reach Rank 20']),
    dict(name='Douchy Wizard School Wand-Maker', types='Arcanist', earth=True,
         stats='+5 INT, +1 STR, +1 DEX, -2 CHA', skills=['+5 Arcane', '+2 Lore', '+2 Negotiation', '+2 Salvage'],
         notes=['Tier 1 crafting table of your choice', 'Arcane can reach Rank 20', 'Silver Earth Box with an Earth Hobby Potion']),
    dict(name='Infernocrafter', types='Arcanist', earth=False,
         stats='+3 STR, +3 CON, +1 DEX', skills=['+5 Arcane', '+3 Smithing'],
         notes=['Resistance to Fire', 'Tier 1 Arcanist table', 'Tier 1 Smithing table', 'Arcane can reach Rank 20']),
    dict(name='Prison Tattoo Artist', types='Arcanist', earth=True,
         stats='+3 CON, +3 DEX, +2 INT', skills=['+5 Tattoo Artistry', '+3 Calligraphy', '+2 Dagger'],
         notes=['Tier 1 Tattoo chair', 'Tattoo Artistry can reach Rank 20', 'Silver Earth Box with an Earth Hobby Potion']),
    dict(name="Boring Ol' Barbarian", types='Barbarian', earth=False,
         stats='+6 STR, +5 CON', skills=['+3 Weapon Skill (choose)', '+2 Endurance', '+1 Intimidate'],
         notes=['Rage: melee attacks deal +1 damage per Health Bar slot you have lost', '+2 DR Buff']),
    dict(name='Feral Cat Berserker', types='Barbarian', earth=True,
         stats='+2 DEX, +2 STR, +2 CHA', skills=['+3 Slice Attack', '+3 Unarmed Combat', '+2 Dodge', '+1 Ambush'],
         notes=['Rage: melee attacks deal +1 damage per Health Bar slot lost', '+1 DR Buff', 'See in total darkness', 'Silver Earth Box'],
         prereq='Cat-based Races only (Cat, Cat Girl/Boy, Tigran)'),
    dict(name='Gladiator', types='Barbarian, Bard', earth=False,
         stats='+3 STR, +3 CON, +3 CHA', skills=['+2 Weapon Skill (choose)', '+2 Performance', '+2 Intimidate', '+1 Attack of Opportunity'],
         notes=['Rage: melee attacks deal +1 damage per Health Bar slot lost', '+1 DR Buff',
                'Once per combat after a kill: Unopposed Performance Check; Amazing Success = +1 Popularity', 'One Weapon Skill can reach Rank 20']),
    dict(name='Harii', types='Barbarian, Rogue', earth=True,
         stats='+1 STR, +1 DEX, +1 INT', skills=['+4 Ambush', '+4 Stealth', '+2 Weapon Skill (choose)'],
         notes=['Rage: melee attacks deal +1 damage per Health Bar slot lost', '+1 DR Buff', 'See in total darkness', 'Access to the Desperado Club', 'Silver Earth Box']),
    dict(name='Shieldmaiden', types='Barbarian, Fighter', earth=True,
         stats='+3 STR, +3 DEX, +3 CHA, -2 INT', skills=['+5 Shield Block', '+2 Weapon Skill (choose)'],
         notes=['Rage: melee attacks deal +1 damage per Health Bar slot lost', '+1 DR Buff', 'Add Str Mod a second time to melee damage against males',
                'One Weapon Skill can reach Rank 20', 'Silver Earth Box'], prereq='Female crawlers only'),
    dict(name='Artist Alley Mogul', types='Bard, Merchant', earth=True,
         stats='+5 DEX, +5 CHA', skills=['+2 Dodge', '+2 Negotiation', '+2 Pathfinder', '+2 Shield (Spell)'],
         notes=['25% store discount and +15% on sales', '10% interest on coins when descending a floor', 'Dodge can reach Rank 20', 'Silver Earth Box']),
    dict(name="Boring Ol' Bard", types='Bard', earth=False,
         stats='+3 CHA', skills=['+3 Performance', '+2 Diplomacy', '+2 Spell (choose)', '+1 Weapon Skill (choose)', '+1 Good First Impression', '+1 Lore'],
         notes=['Access to all membership clubs', 'Free room at all saferooms', 'May gain a Patron', 'Membership in the Dungeon Book of the Floor Club (all Spells)',
                '+1 Mana to cast Spells not Favored: Bard']),
    dict(name='Former Child Actor', types='Bard', earth=True,
         stats='+10 CHA', skills=['+3 Character Actor', '+2 Cockroach'],
         notes=['+1 to Skill Advancement Checks for Charisma Skills', 'Immune to Poison and disease', 'The Manager Benefit', 'Silver Earth Box'],
         prereq='Popularity 3+ and the "Cut!" achievement'),
    dict(name='NecroBard', types='Bard, Necromancer', earth=False,
         stats='+3 INT, +3 CON, +3 CHA, -2 STR', skills=['+4 Performance', '+3 Turn Undead (Spell)', '+3 Panty Dropper (Spell)'],
         notes=['Access to all membership clubs', 'Free room at all saferooms', '+1 Mana for Spells that are not Favored: Bard or Necrotic']),
    dict(name='Poet Laureate', types='Bard', earth=True,
         stats='+3 INT, +2 CHA', skills=['+5 Performance (written word)', '+2 Earworm (Spell)', '+2 Heal Others (Spell)', '+2 Shield (Spell)'],
         notes=['Earworm is cast as spoken-word poetry', 'Access to all membership clubs', '+1 Mana for Spells not Favored: Bard', 'Performance can reach Rank 20',
                'Must choose a Patron (GM offers two)', 'Silver Earth Box']),
    dict(name='Professional Roadie', types='Bard, Rogue', earth=True,
         stats='+8 split between STR, CON and CHA', skills=['+4 Performance (guitar)', '+3 Negotiation', '+1 Iron Stomach', '+1 Repair'],
         notes=['Advantage vs Poison and Shit-Faced effects', 'At the start of combat all your damage may be Sonic', 'Advantage on Repair Checks', 'Silver Earth Box']),
    dict(name='Spellbinder', types='Bard', earth=False,
         stats='+2 CHA, +2 INT', skills=['+2 Good First Impression', '+2 Lore', '+2 Performance', '+2 Hot Stuff Aura (Spell)', '+2 Panty Dropper (Spell)'],
         notes=['Add Cha Mod a second time on Cha Checks in hostile situations', 'Access to the Spellbook of the Floor club (Favored: Bard)',
                'Once per day hold everyone on the battlefield spellbound for a round (not Bosses)']),
    dict(name="Boring Ol' Cleric", types='Cleric', earth=False,
         stats='+4 CHA, +3 INT', skills=['+2 Weapon Skill (choose)', '+3 Religion', '+2 Heal Others (Spell)', '+2 Shield (Spell)', '+2 Turn Undead (Spell)'],
         notes=['Access to the Spell Book of the Level club (Favored: Cleric)', 'Access to Club Vanquisher', 'Must worship a deity',
                'Cannot choose a Cleric-type Class if you have Desperado Club access']),
    dict(name='Santero', types='Cleric', earth=False,
         stats='+3 STR, +3 CHA, +2 CON, -2 INT', skills=['+2 Weapon Skill (choose)', '+2 Religion', '+1 Endurance', '+2 Heal Others (Spell)', '+2 Shield (Spell)', '+2 Soul Collector (Spell)'],
         notes=['Hybrid Necromancer Cleric, tank/support', 'Access to the Dungeon Book of the Floor club (Favored: Cleric)', 'Access to Club Vanquisher', 'Must worship a deity',
                'Cannot choose if you have Desperado Club access']),
    dict(name='Black Inquisitor General', types='Cleric, Mage, Paladin', earth=False,
         stats='+3 STR, +3 INT, +1 CHA, -2 CON', skills=['+3 Weapon Skill (choose)', '+3 Find Trap', '+2 Trap Engineer', '+2 Spell (choose)', '+1 Religion'],
         notes=['See in total darkness', 'Access to all membership clubs', 'Must worship a deity']),
    dict(name="Boring Ol' Druid", types='Druid', earth=False,
         stats='+2 INT, +2 CON, +2 DEX', skills=["+3 Nature's Breath (Spell)", '+3 Spell (choose)', '+2 Spell (choose)', '+2 Survival'],
         notes=['Mana recovers twice as fast in a natural environment', 'Access to the Dungeon Book of the Floor club (Favored: Druid)']),
    dict(name='Herbalist', types='Arcanist, Druid', earth=False,
         stats='+2 CON, +2 INT', skills=['+2 Alchemy', '+2 Cooking', '+2 First Aid', '+2 Survival', "+2 Nature's Breath (Spell)", '+2 Dirt Clod (Spell)'],
         notes=['Mana recovers twice as fast in a natural environment']),
    dict(name='Physicker', types='Druid', earth=False,
         stats='+3 CON, +3 INT', skills=["+3 Nature's Breath (Spell)", '+3 Oakhide (Spell)', '+2 Rootfoot (Spell)', '+2 Solsplash (Spell)'],
         notes=['Double Mana regeneration outdoors', 'Once per day grant +1 DR to the party for a scene']),
    dict(name='Lifebringer', types='Druid', earth=False,
         stats='+2 CON, +1 INT', skills=['+2 First Aid', '+2 Pathfinder', '+2 Regeneration', '+2 Survival', "+2 Nature's Breath (Spell)"],
         notes=['+1 Rank in all Heal Spells', 'Once per day grant Regeneration at your Rank to the party within 30 ft for 10 minutes']),
    dict(name='Shepherd', types='Druid', earth=True,
         stats='+2 INT, +2 CHA, +2 CON', skills=['+3 Animal Handling', '+2 Pathfinder', "+2 Nature's Breath (Spell)", '+2 Drain Life (Spell)'],
         notes=['See twice as far as most creatures', 'Gain a friendly Pet; pets in your Herd get +2 DR', 'Mana recovers twice as fast in nature',
                'Melee weapons limited to Herding Weapons', 'Silver Earth Box']),
    dict(name="Boring Ol' Fighter", types='Fighter', earth=False,
         stats='+2 STR, +2 CON', skills=['+5 Weapon Skill (choose)', '+3 Dodge', '+2 to two of: Aiming, Attack of Opportunity, Catcher, Shield Block, Zone of Control'],
         notes=['Any Weapon Training Guild; a free training coupon each floor']),
    dict(name='Pit Fighter', types='Fighter', earth=True,
         stats='+3 DEX, +2 INT, +1 STR', skills=['+3 Attack of Opportunity', '+3 Dirty Fighting', '+2 Dodge', '+2 Improvised Weapons'],
         notes=['+2 DR Buff', 'Silver Earth Box']),
    dict(name='Shotgun Messenger', types='Fighter', earth=True,
         stats='+2 STR, +2 CON, +2 DEX, -2 CHA', skills=['+5 Ranged Weapon Skill (choose)', '+2 Aiming', '+2 Intimidate', '+1 all muscle-powered movement Skills'],
         notes=['Any Weapon Training Guild; a free training coupon each floor', 'Access to the Desperado Club', 'Silver Earth Box']),
    dict(name='Straight-to-DVD Action Hero', types='Fighter', earth=True,
         stats='+3 STR, +3 CON, +3 DEX, +3 CHA, -2 INT', skills=['+2 Unarmed Combat', '+1 Driving', '+1 Running', '+1 Performance'],
         notes=['Take no damage from falling', '+1 DR', 'The Manager Benefit', 'Silver Earth Box']),
    dict(name='Sword and Boarder', types='Fighter', earth=False,
         stats='+2 STR, +2 CON, +2 DEX, -2 INT', skills=['+5 Shield Block', '+3 Edged Weapon Skill (choose)', '+2 Attack of Opportunity', '+2 Catcher'],
         notes=['Access to the Desperado Club']),
    dict(name='Monster Truck Driver', types='Fighter', earth=True,
         stats='+4 CON, +2 DEX, -2 STR, -2 INT', skills=['+3 Gear Head', '+3 Driving', '+3 Pathfinder'],
         notes=['While moving, Health Bar slots gain 1/10 of your conveyance\'s Move', 'Slam charge: Rank = Floor, Dex to hit, 1d12 Bludgeoning line, then Fatigued (30-hour cooldown)',
                'Once per combat when you lose 2+ slots, 1d2: on a 1 the attacker loses a slot', 'Resistance to Force', 'Silver Earth Box'],
         prereq='Rank 5+ in Driving'),
    dict(name='Zulu Warrior', types='Fighter', earth=True,
         stats='+3 STR, +3 CON, +3 DEX', skills=['+3 Melee Weapon Skill (choose)', '+2 Attack of Opportunity', '+2 Endurance', '+2 Running'],
         notes=['+1 DR', 'One Weapon Skill can reach Rank 20', 'Silver Earth Box']),
    dict(name="Boring Ol' Mage", types='Mage', earth=False,
         stats='+5 INT, +5 CHA, -2 STR, -2 DEX', skills=['+3 Fire Spell (choose)', '+2 Force Spell (choose)', '+2 Sonic Spell (choose)', '+2 Passive Spell (choose)', '+2 Passive Spell (choose another)', '+2 Lore', '+1 Arcane'],
         notes=['-3 Ranks in all Strength Skills and all Dexterity Skills (min 1 if you have any)']),
    dict(name='Blizzardmancer', types='Mage', earth=False,
         stats='+4 INT, +3 DEX, -2 STR', skills=['+4 Ice Blast (Spell)', '+4 Frost Scar (Spell)', '+2 Aiming'],
         notes=['Resistance to Ice', 'Aiming works with single-target Ice Spells']),
    dict(name='Crisper', types='Mage', earth=False,
         stats='+3 INT, +2 DEX, -2 CON', skills=['+3 Wall of Fire (Spell)', '+3 Fire Fingers (Spell)', '+2 Fireball (Spell)', "+2 Wilbur's Slow-Build Fireblast (Spell)", '+2 Lore'],
         notes=['Resistance to Fire', 'No DR against Ice or water damage']),
    dict(name='Fire Spiritualist', types='Bard, Mage', earth=False,
         stats='+2 INT, +2 CHA', skills=['+2 Holy Aura (Spell)', '+2 Hot Stuff Aura (Spell)', '+2 Heal Others (Spell)', '+2 Intimate Touches (Spell)'],
         notes=['Heal Others can reach Rank 20', 'Ethereal Hug: once per day for a scene the party gets +1 DR, Rank 4 Regeneration, +1 to hit and +1d4 damage',
                'Vulnerable to Ice']),
    dict(name='Forsaken Aerialist', types='Mage', earth=False,
         stats='+5 INT, -2 CHA', skills=['+3 Drain Life (Spell)', '+3 Soul Collector (Spell)', '+1 Alchemy', '+1 Infusion', '+1 Tactics'],
         notes=['Double the duration of your Rank 5 and lower Spells', 'Your Spells can affect a creature without it noticing']),
    dict(name='Necromancer', types='Mage, Necromancer', earth=False,
         stats='+2 INT, +2 DEX, -2 CON, -2 CHA', skills=['+4 Soul Collector (Spell)', '+4 Rise, Dead Minion! (Spell)', '+2 Drain Life (Spell)', '+2 Second Chance (Spell)'],
         notes=['Once per rest question a corpse (Int questions)', 'Killing an undead Mob heals 1 slot (up to 5 per combat)']),
    dict(name='Elemental Monk', types='Mage, Monk', earth=False,
         stats='+2 INT, +2 DEX', skills=['+3 Unarmed Combat', '+1 Dirt Clod (Spell)', '+1 Fire Fingers (Spell)', '+1 Frost Scar (Spell)', '+1 all Electric, Fire and Ice Spells'],
         notes=['Advantage attacking elemental creatures', 'Can burrow', 'Can breathe underwater', 'Can fly']),
    dict(name="Boring Ol' Monk", types='Monk', earth=False,
         stats='+3 CON, +3 DEX, +1 STR', skills=['+3 Unarmed Combat', '+1 Foot Soldier', '+1 Iron Punch', '+1 Powerful Strike', '+1 Pugilism', '+1 Smush', '+1 all Dexterity-based Weapon Skills'],
         notes=['Unarmed Combat can reach Rank 20']),
    dict(name='Prizefighter', types='Bard, Monk', earth=True,
         stats='+5 CON, +2 STR, -2 INT, -2 CHA', skills=['+5 Pugilism', '+5 Iron Punch'],
         notes=['Floor number gold per Mob killed with Pugilism or Unarmed Combat', '+1 Popularity per such kill', 'Pugilism can reach Rank 20', 'Silver Earth Box'],
         prereq='Rank 5+ in Pugilism'),
    dict(name='Spirit Healer', types='Druid, Monk', earth=True,
         stats='+3 STR, +3 CON, +1 DEX', skills=['+3 Smush', '+3 Drain Life (Spell)', '+2 Heal Others (Spell)', '+2 Heal Self (Spell)'],
         notes=['Your healing on a single target heals +1 slot', 'Heal Others can reach Rank 20', 'Access to Club Vanquisher', 'Silver Earth Box']),
    dict(name='Street Monk', types='Fighter, Monk', earth=True,
         stats='+2 DEX, +1 STR, +1 CHA', skills=['+2 Dirty Fighting', '+2 Streetwise', '+2 Unarmed Combat', '+1 Pugilism', '+1 all Dexterity-based Weapon Skills'],
         notes=['+3 DR Buff', 'Silver Earth Box']),
    dict(name="Boring Ol' Paladin", types='Paladin', earth=False,
         stats='+2 CHA', skills=['+3 Weapon Skill (choose)', '+3 Protective Shell (Spell)', '+3 Heal Others (Spell)', '+3 Holy Aura (Spell)', '+2 Catcher or Shield Block'],
         notes=['Access to Club Vanquisher', 'Must worship a deity', 'Cannot choose if you have Desperado Club access']),
    dict(name='Sacred Paladin', types='Paladin', earth=False,
         stats='+3 STR, +2 CHA', skills=['+2 Catcher', '+2 Weapon Skill (choose)', '+2 Heal Others (Spell)', "+2 Paladin's Smite (Spell)", '+2 Turn Undead (Spell)'],
         notes=['Access to Club Vanquisher', 'Must worship a deity', 'Cannot choose if you have Desperado Club access']),
    dict(name='Cavalier', types='Fighter, Paladin', earth=False,
         stats='+2 STR, +2 CON', skills=['+2 Catcher', '+2 Riding', '+2 Lance', '+2 Shield (Spell)', "+2 Paladin's Smite (Spell)"],
         notes=['A bonded Mount one size bigger (Move 40, DR 10 barding, Trample) with a pet carrier', 'Redirect attacks between you and your Mount',
                'Playing to the Cameras when protecting someone under your code with Catcher', '+2 DR Buff', 'Access to the Dungeon Book of the Floor club (Cleric/Paladin Spells)',
                'Access to Club Vanquisher', 'Must worship a deity']),
    dict(name="Boring Ol' Rogue", types='Rogue', earth=False,
         stats='+1 INT, +1 DEX, +1 CHA', skills=['+3 Stealth', '+2 Dagger', '+2 Detect Trap', '+2 Dodge', '+2 Lockpicking', '+1 Ambush'],
         notes=['See in total darkness', 'Floor number gold per Mob killed with a melee weapon', 'Access to the Desperado Club', 'Cannot choose if you have Club Vanquisher access']),
    dict(name='Bomb Squad Tech', types='Rogue', earth=True,
         stats='+2 DEX, +1 CON, -2 INT', skills=['+3 Bomb Surgeon', '+3 Find Trap', '+2 all Explosive-based Skills'],
         notes=['+1 DR Buff', 'Limb Regeneration: a lost limb regrows in 12 days minus your Con Mod', 'Silver Earth Box'],
         prereq='The Boom! achievement'),
    dict(name='High Rise Grifter', types='Rogue', earth=True,
         stats='+1 INT, +1 CHA', skills=['+4 Deception', '+4 Stealth', '+2 Dagger', '+2 Escape Plan', '+1 Determine Value', '+1 Negotiation'],
         notes=['Access to the Desperado Club', 'Cannot choose if you have Club Vanquisher access', 'Silver Earth Box']),
    dict(name='Compensated Anarchist', types='Monk, Rogue', earth=True,
         stats='+5 CHA, +1 INT', skills=['+2 Backfire', '+2 Escape Plan', '+2 Find Trap', '+1 Bomb Surgeon', '+1 Hide in Shadows', '+1 Trap Engineer', '+1 Unarmed Combat', '+1 Fear (Spell)'],
         notes=['No Stat Mod bonus damage with Edged Weapons', '+3 Mana to cast damage-dealing Spells',
                'End of each floor: +1 to one trap-related and +1 to one bomb-related Skill Advancement Check',
                'Access to the Desperado Club', 'Access to the Naughty Boys Employment Agency', 'Silver Earth Box'],
         prereq='Popularity 3+ and Rank 5+ in Explosives Handling'),
    dict(name='Identity Thief', types='Rogue', earth=True,
         stats='+4 CHA, +3 DEX', skills=['+5 Deception', '+3 Dagger', '+2 Investigation'],
         notes=['Tier 3 Makeup Table', 'Access to the Desperado Club', 'Cannot choose if you have Club Vanquisher access', 'Silver Earth Box']),
    dict(name='Swashbuckler', types='Bard, Fighter, Rogue', earth=False,
         stats='+3 DEX, +3 CHA', skills=['+3 Rapier or Longsword', '+2 Balance', '+2 Dodge', '+1 Performance', '+1 Light on Your Feet'],
         notes=['Rapier or Longsword can reach Rank 20', 'Advantage on melee attacks from higher ground',
                'Once per combat after a kill: Unopposed Performance Check; Amazing Success = +1 Popularity']),
]


# ── Items ─────────────────────────────────────────────────────────────────────
# DCC has no shop list: weapons ARE the Attack Skills (base die + Stat, p.79),
# armor is Damage Resistance by Gear Slot (p.98, Table 25 p.116), and gear
# comes out of loot boxes (p.215–218) — so costs are blank except where the
# book prints a price. Anything that rolls carries its dice in the text so the
# sheet's Hotlist chips and rollers can pick them up.

_WEAPON_META = {   # name -> (category, range text, range ft)
    'Bite': ('Natural', 'Melee', 5), 'Slice Attack': ('Natural', 'Melee', 5), 'Back Claw': ('Natural', 'Melee', 5),
    'Unarmed Combat': ('Unarmed', 'Melee', 5), 'Pugilism': ('Unarmed', 'Melee', 5), 'Foot Soldier': ('Unarmed', 'Melee', 5),
    'Noggin Nocker': ('Unarmed', 'Melee', 5), "Wrasslin'": ('Unarmed', 'Melee', 5),
    'Crossbow': ('Ranged', 'Ranged', 50), 'Bow': ('Ranged', 'Ranged', 100), 'Handgun': ('Ranged', 'Ranged', 150),
    'Javelin': ('Ranged', 'Ranged', 40), 'Shotgun': ('Ranged', 'Ranged', 30), 'Shuriken': ('Ranged', 'Ranged', 30),
    'Slingshot': ('Ranged', 'Ranged', 30),
    'Herding Weapons': ('Reach', 'Reach', 10), 'Lance': ('Reach', 'Reach', 10), 'Polearm': ('Reach', 'Reach', 10),
    'Quarterstaff': ('Reach', 'Reach', 10),
}


def weapons():
    """One weapon per Attack Skill that names base damage dice."""
    import re as _re
    out = []
    for name, cat, stat, desc in SKILLS:
        if cat != 'Attack':
            continue
        m = _re.search(r'(\d+d\d+)(?: \+ (Str|Dex|Con))? (\w+)', desc)
        if not m:
            continue
        wcat, rng, ft = _WEAPON_META.get(name, ('Melee', 'Melee', 5))
        props = [f'+ {m.group(2)} Mod' if m.group(2) else 'No Stat Mod']
        if 'two hands' in desc.lower():
            props.append('Two-Handed')
        if 'ammo' in desc.lower():
            props.append('Ammo')
        if 'mounted' in desc.lower():
            props.append('Mounted')
        fav = _re.search(r'AI Favor (\d)', desc)
        if fav:
            props.append(f'AI Favor {fav.group(1)}')
        out.append(dict(
            api_index=api_index('weapon', name), name=name, weapon_category=wcat, weapon_range=rng,
            damage_dice=m.group(1), damage_type=m.group(3), two_handed_damage_dice='',
            two_handed_damage_type='', range_normal=ft, range_long=ft, weight=0, cost='',
            properties=', '.join(props), mastery='', notes=f'{name} Attack Skill: {desc}',
            image_url='', source=DCC_SOURCE, game_system='dcc'))
    return out


# (name, gear slot / category, DR, properties, notes)
ARMOR = [
    ('Bronze Armor (+1 DR)',   'Any Gear Slot', 1, '+1 DR',
     'Mundane armor of your choice, but awkward: hockey pads, a heavy winter coat, a trash-can lid shield (Table 25, p.116).'),
    ('Silver Armor (+2 DR)',   'Any Gear Slot', 2, '+2 DR, Anti-Piercing',
     'Silver-tier loot: +2 Damage Resistance with the Anti-Piercing Benefit (p.95).'),
    ('Gold Armor (+3 DR)',     'Any Gear Slot', 3, '+3 DR, Resistance to one uncommon damage type',
     'Gold-tier loot: +3 Damage Resistance plus Resistance to an uncommon damage type (Table 10, p.93).'),
    ('Platinum Armor (+4 DR)', 'Any Gear Slot', 4, '+4 DR, +5 Constitution, +3 Catcher or Taunt',
     'Platinum-tier loot: +4 Damage Resistance, +5 Constitution, and +3 to the Catcher or Taunt Skill.'),
    ('Random Piece of Armor (+1 DR)', 'Any Gear Slot', 1, '+1 DR',
     'Typical Bronze loot-box find (p.216).'),
    ('Looted Mob Armor',       'Any Gear Slot', 0, 'Lesser quality, lasts a day or two',
     'Armor pulled off a dead Mob: lesser quality than even mundane loot-box gear, but it might last a day or two in a pinch (p.215).'),
    ('Shield',                 'Hands/Holding', 0, 'Uses a Holding slot',
     'A Shield takes up one Hands/Holding slot; a two-handed weapon means you cannot hold one (p.98). Pairs with the Shield Block Skill.'),
]


def armor():
    return [dict(api_index=api_index('armor', n), name=n, armor_category=slot, armor_class_base=0,
                 dex_bonus=0, max_dex_bonus=None, str_minimum=0, stealth_disadvantage=0, weight=0,
                 cost='', properties=props, notes=notes, image_url='', source=DCC_SOURCE, game_system='dcc')
            for n, slot, dr, props, notes in ARMOR]


# (name, category, subcategory, cost, description). Dice live in the text.
EQUIPMENT = [
    # Healing & recovery
    ('Healing Potion',              'Consumable', 'Potion', '', 'Heals 5 Health Bar slots. Drink as an Action (or from the Hotlist without drinking); healing potions can also be consumed as an Interrupt. No more than one potion every other round or you get Potion Sickness (Poison, 15 s).'),
    ('Good Healing Potion',         'Consumable', 'Potion', '', 'Heals 6 Health Bar slots.'),
    ('Gold Standard Healing Potion','Consumable', 'Potion', '', 'Heals 7 Health Bar slots and mends one Minor Injury.'),
    ('Supreme Healing Potion',      'Consumable', 'Potion', '', 'Heals 8 Health Bar slots and mends one Minor or Major Injury; or deals 8d8 Holy damage to an undead Mob.'),
    ('Heal Severe Injury Potion',   'Consumable', 'Potion', '', 'Heals 9 Health Bar slots and mends all Injuries.'),
    ('Heal Pet Potion',             'Consumable', 'Potion', '', 'Heals a pet 5 Health Bar slots.'),
    ('Mana Potion',                 'Consumable', 'Potion', '', 'Full Mana restore.'),
    ('Good Mana Refill Potion',     'Consumable', 'Potion', '', 'Restores 15 Mana per round for 10 rounds.'),
    ('Potion of +1 Skill',          'Consumable', 'Potion', '', 'Permanent: choose a Skill and gain 1 Rank in it (Silver loot).'),
    ('Potion of +2 Skill',          'Consumable', 'Potion', '', 'Permanent: choose a Skill and gain 2 Ranks in it (Gold loot).'),
    ('Potion of +3 Skill',          'Consumable', 'Potion', '', 'Permanent: choose a Skill and gain 3 Ranks in it (Platinum loot).'),
    ('Bandages',                    'Consumable', 'Medical', '', 'Spend an Action to remove the Blood Trail Debuff. Loot boxes hold 1d6.'),
    ('Poison Antidote',             'Consumable', 'Medical', '', 'Cures the Poison Debuff.'),
    # Explosives (rollable)
    ('Stick of Basic Dynamite',     'Consumable', 'Explosive', '', '1d6 Bludgeoning damage, 0 ft Blast radius + 5 ft Splash.'),
    ('Stick of Good Goblin Dynamite','Consumable','Explosive', '', '2d6 Bludgeoning damage, 5 ft Blast radius + 5 ft Splash.'),
    # Scratchers (rollable)
    ('Medicine or Lube? Scratcher', 'Consumable', 'Scratcher', '', 'As an Action in combat, roll 1d2. On a 1, one target within 20 ft is covered in slippery lube (Staggered). On a 2, the target is affected by a Level 15 Heal Other Spell. Cooldown 30 minutes.'),
    ('Nebular Roulette Scratcher',  'Consumable', 'Scratcher', '', 'As an Action in combat, roll 1d6. On a 1 you take 2d12+F Electric damage; on 2–6 the target takes 2d12+F Electric damage.'),
    # Magic paper goods
    ('Spell Scroll',                'Consumable', 'Scroll', '', 'One-shot cast of a named Spell at a set Rank, no Mana. Written as "Scroll of Spell name (Rank X)". Turns to dust after use (p.99).'),
    ('Scroll of Upgrade',           'Consumable', 'Scroll', '', "Upgrades a crawler's signature weapon: roll d12 on Table 26 (p.117) for the name addition and Amazing Success effect."),
    ('Spellbook',                   'Consumable', 'Book', '', 'Read once to learn a single Spell at a predefined Rank (roll 1d6−1, minimum Rank 1), then it disappears (p.99).'),
    ('Magic Tome',                  'Consumable', 'Book', '', 'Learn a new, weak Spell (Bronze loot). Same rules as a Spellbook.'),
    ('Magic Paper',                 'Crafting',   'Scroll-writing', '', 'Special linen paper for writing Scrolls with the Calligraphy Skill (Rank 10+).'),
    # Mundane
    ('Torches (×10)',               'Mundane', 'Light', '', 'Bright light for 20 ft and dim light for another 20 ft; burns out in about an hour.'),
    ('Crawler Biscuits (×100)',     'Mundane', 'Food', '', 'Keeps crawlers fed. Among the most common loot-box finds.'),
    ('Rope (50 feet)',              'Mundane', 'Gear', '', '50 feet of rope (Bronze item option).'),
    ('Bicycle',                     'Mundane', 'Vehicle', '', 'Bronze item option. See Vehicles, p.72.'),
    ('Canoe and Paddle',            'Mundane', 'Vehicle', '', 'Bronze item option; the paddle counts as a Staff.'),
    ('Hang Glider',                 'Mundane', 'Vehicle', '', 'Bronze item option.'),
    ('Misc. Junk',                  'Mundane', 'Junk', 'Sells for 1 gold', 'Set dressing and assorted crap; spend one point of Misc. Junk to produce any innocuous item. Sells for a non-negotiable 1 gold each; some merchants sell it for 2 (p.98). Dead Mobs carry 1d6.'),
    ('Enhanced Pet Biscuit',        'Mundane', 'Pet', '', 'Lets a pet function as a crawler (p.99).'),
    ('Magical Pet Carrier',         'Mundane', 'Pet', '', 'Lets a pet take a time-out in your Inventory without dying (p.98).'),
    # Maps (Boss loot)
    ('Neighborhood Map',            'Loot', 'Map', '', "Boss drop: adds the Neighborhood and every Mob in it to your minimap (dots only). Grinding 5+ hours counts as 6 (p.215)."),
    ('Borough Field Guide',         'Loot', 'Map', '', 'Borough Boss drop: outlines the quadrants of a borough with Mob level range and type tooltips. Grinding 5+ hours counts as 7 (p.216).'),
    ('Gold',                        'Loot', 'Currency', '', 'All your gold fits in one Inventory slot. Loot boxes: Bronze 1d10, Silver 1d10×100, Gold 1d6×1000, Platinum 2d6×1000, Legendary 1d10×10,000. Mob drops per body: 2nd Floor 1d6, 3rd 2d4, 4th 2d6, 5th 2d8.'),
    # Crafting (the only printed prices)
    ('Crafting Table (tier 1)',     'Crafting', 'Table', '25,000 gold', 'Crafting, Sapper, Engineer, Alchemy, or Metal Working Table. A brand-new tier-1 Table costs 25,000 gold (p.221).'),
    ('Crafting Table Upgrade Coupon','Crafting','Coupon', '', 'Upgrades a Crafting Table one tier (buying the upgrade outright costs 250,000 gold, p.221).'),
    ('Personal Space Coupon',       'Crafting', 'Coupon', '', 'Exchange with a Bopca to expand the room types in your personal space (p.216).'),
]


def equipment():
    return [dict(api_index=api_index('equipment', n), name=n, category=cat, subcategory=sub, weight=0,
                 cost=cost, description=desc, source=DCC_SOURCE, game_system='dcc')
            for n, cat, sub, cost, desc in EQUIPMENT]


# Sample magical gear from the loot tables (p.216–218): (name, gear slot, box tier, description)
MAGIC_ITEMS = [
    ('Silver Ring of +2 to a Stat', 'Accessory', 'Silver', '+2 to one Stat of your choice.'),
    ('Golden Ring of +3 to a Stat', 'Accessory', 'Gold', '+3 to one Stat of your choice.'),
    ('Interesting Item of +4 to a Stat', 'Accessory', 'Platinum', 'An interesting item granting +4 to a Stat.'),
    ('Friendship Bracelet of [Race]kind', 'Accessory', 'Silver', 'Roll 1d10 for a Race (1–2 dwarven, 3–4 elven, 5–6 fairy, 7–8 orc, 9–10 skyfowl). Removes automatic hostility from Mobs and NPCs of that Race. Take it off or break it and they are automatically hostile for the rest of the Floor.'),
    ('Bitch-Ass Buckler', 'Hands/Holding', 'Silver', '+1 Shield Block Skill. +3 Damage Resistance.'),
    ('Bernie Boots', 'Feet', 'Silver', 'When you gain the Dying Debuff, you can still perform Move Actions and read HUD messages about moving in certain directions.'),
    ('Big Purple Plume', 'Accessory', 'Silver', '+2 Charisma.'),
    ('Enchanted Elbow Pads of the Elbow-Walking Turkeys', 'Arms', 'Gold', '+2 Damage Resistance. +2 Dexterity.'),
    ('Skullcap of Sucking', 'Head', 'Gold', '+1 Damage Resistance. Each time you roll a Critical Fail, gain 1 AI Favor.'),
    ('Tough Guy Tattoo', 'Accessory', 'Gold', '+3 Constitution. Add 10 to your 100% Health Bar slot.'),
    ('Selfie Stick of the Self-Mutilator', 'Hand/Holding', 'Platinum', 'You have 1 fewer Health Bar slot while holding this. When you enter combat with a Minor Injury gain 1 Popularity (2 for a Major Injury) and an equal number of extra Actions each round of the combat.'),
    ('Chesty Cheese Grater', 'Torso', 'Platinum', '+2 Damage Resistance. +5% Constitution. Damage Reflection 3:1 vs melee attacks (for every 3 Health Bar slots you lose, the attacker loses 1).'),
    ('Enchanted Leggings of Insanity', 'Legs', 'Platinum', '+1 Damage Resistance. +3 Escape Artist Skill. You may fit your body south of your wedding tackle into any sized opening.'),
    ('Enchanted Cloak of the Slippery Perv', 'Accessory', 'Legendary', '+6 Charisma. +3 Evade Buff when you accuse your attacker of wanting to "penetrate you" in a way you have never used previously.'),
    ('Enchanted Wand of Incontinence', 'Hand/Holding', 'Legendary', '+10% Constitution. Once per session, as an Action, a creature within 30 ft voids its bowels and gains the Fatigued Debuff.'),
    ('Hand Grips of Hella Holding', 'Hands/Holding', 'Legendary', '+10% Strength. +3 Damage Resistance. Nothing short of divine intervention can undo your grip.'),
]


def magic_items():
    return [dict(api_index=api_index('magic', n), name=n, category=f'Gear Slot: {slot}', rarity=f'{tier} box',
                 attunement=0, description=desc, image_url='', source=DCC_SOURCE, game_system='dcc')
            for n, slot, tier, desc in MAGIC_ITEMS]


# ── Seeding ───────────────────────────────────────────────────────────────────

def _skill_row(name, cat, stat, desc):
    return dict(api_index=api_index('skill', name), name=name, ability_score=stat,
                description=f'{cat}. {desc}', source=DCC_SOURCE, game_system='dcc')


def _race_row(r):
    traits = list(r['skills']) + list(r['notes'])
    desc = ('Earth Race' if r['earth'] else 'Alien Race (no Earth Classes)')
    if r.get('prereq'):
        desc += f". Prerequisite: {r['prereq']}"
    return dict(api_index=api_index('race', r['name']), name=r['name'], speed=r['move'],
                size=r['size'], ability_bonuses=r['stats'], traits_text='\n'.join(traits),
                languages='', description=desc, source=DCC_SOURCE, game_system='dcc')


def _class_row(c):
    desc = f"Class Type: {c['types']}" + ('. Earth Class (Silver Earth Box)' if c['earth'] else '')
    if c.get('prereq'):
        desc += f". Prerequisite: {c['prereq']}"
    desc += '\n' + '\n'.join(c['notes'])
    return dict(api_index=api_index('class', c['name']), name=c['name'], hit_die=0,
                saving_throws='', proficiencies=c['stats'], skill_choices='\n'.join(c['skills']),
                subclasses=c['types'], spellcasting_ability='', description=desc,
                source=DCC_SOURCE, game_system='dcc')


def rows():
    """(model_name, [row dicts]) for every seeded table."""
    return [
        ('tblSkillsLibrary',     [_skill_row(*s) for s in SKILLS]),
        ('tblRacesLibrary',      [_race_row(r) for r in RACES]),
        ('tblClassesLibrary',    [_class_row(c) for c in CLASSES]),
        ('tblWeaponsLibrary',    weapons()),
        ('tblArmorLibrary',      armor()),
        ('tblEquipmentLibrary',  equipment()),
        ('tblMagicItemsLibrary', magic_items()),
    ]


SETTING_KEY = 'dcc_library_version'


def seed(db, models, now, refresh=False):
    """Insert every built-in row that is missing (matched by api_index).
    With refresh=True (a VERSION bump at boot) existing built-in rows are also
    brought up to date with this file — built-in entries are ours to correct;
    a table's own variant belongs in a Custom (homebrew) row instead.
    Returns the number added or refreshed."""
    changed = 0
    for model_name, data in rows():
        model = getattr(models, model_name)
        have = {r.api_index: r for r in model.query.filter(model.api_index.like('dcc:%')).all()}
        for row in data:
            existing = have.get(row['api_index'])
            if existing is None:
                db.session.add(model(created_at=now, **row))
                changed += 1
            elif refresh:
                dirty = False
                for k, v in row.items():
                    if getattr(existing, k) != v:
                        setattr(existing, k, v)
                        dirty = True
                changed += 1 if dirty else 0
    db.session.commit()
    return changed


def seed_if_needed(db, models, now, get_setting, set_setting):
    """Boot hook: run seed() once per VERSION (recorded in tblAppSettings)."""
    try:
        current = int(get_setting(SETTING_KEY, 0) or 0)
    except (TypeError, ValueError):
        current = 0
    if current >= VERSION:
        return 0
    added = seed(db, models, now, refresh=current > 0)   # first seed inserts; later versions also correct
    set_setting(SETTING_KEY, str(VERSION))
    return added


def parse_bonus(text):
    """'+3 Salvage' -> (3, 'Salvage'); '+5 DEX' -> (5, 'DEX'); None if no leading number."""
    text = (text or '').strip()
    if not text or text[0] not in '+-':
        return None
    num = ''
    i = 0
    while i < len(text) and (text[i] in '+-' or text[i].isdigit()):
        num += text[i]
        i += 1
    try:
        n = int(num)
    except ValueError:
        return None
    return n, text[i:].strip()


STAT_KEYS = {'STR': 'str', 'INT': 'int', 'CON': 'con', 'DEX': 'dex', 'CHA': 'cha'}


def stat_bonuses(text):
    """'+5 DEX, +3 STR, -2 CHA' -> {'dex': 5, 'str': 3, 'cha': -2}. Split/choice
    bonuses ('+6 split between …', '+5 INT by day') are left to the player."""
    out = {}
    for part in (text or '').split(','):
        p = parse_bonus(part)
        if not p:
            continue
        n, key = p
        key = key.upper()
        if key in STAT_KEYS:
            out[STAT_KEYS[key]] = out.get(STAT_KEYS[key], 0) + n
    return out


def skill_bonuses(lines):
    """['+3 Salvage', '+2 Web (Spell)', '+2 crafting Skill (choose)'] ->
    [(3, 'Salvage'), (2, 'Web')] — choices and groups are skipped."""
    out = []
    for line in lines:
        p = parse_bonus(line)
        if not p:
            continue
        n, name = p
        name = name.replace('(Spell)', '').strip()
        low = name.lower()
        if '(' in name or any(w in low for w in ('choose', ' or ', 'all ', 'split', 'two of')):
            continue   # choices, groups and named variants ("Creepy Chains (Club)") are the player's call
        out.append((n, name))
    return out

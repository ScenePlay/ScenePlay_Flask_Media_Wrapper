"""Genre packs: re-flavor 5e-mechanics characters for other settings.

The mechanics (class, race, stats, HP, levels) stay pure 5e — a pack only
swaps the presentation layer: display names for classes/races, name
generation style, backgrounds with personality tables, and the art-direction
block of the AI portrait prompt. Plain D&D fantasy is the absence of a pack.

All flavor text is original ("inspired by", never copied — Dungeon Crawler
Carl, Warhammer, and Mad Max are someone else's IP).

Pack shape:
    label       -- shown in the genre dropdown
    class_skins -- 5e class name  -> genre archetype label
    race_skins  -- 5e race name   -> genre species/origin label
    names       -- pools + format hints for generate_genre_name()
    backgrounds -- {name: {traits[4], ideals[3], bonds[3], flaws[3]}}
    art_style   -- portrait-prompt art direction lines (no leading '- ')
"""

GENRE_PACKS = {

    # ── Dungeon Crawl (LitRPG) ─────────────────────────────────────────────────
    'litrpg': {
        'label': 'Dungeon Crawl (LitRPG)',
        'class_skins': {
            'Barbarian': 'Meat Grinder',
            'Bard':      'Hype Man',
            'Cleric':    'Loot Priest',
            'Druid':     'Beast Whisperer',
            'Fighter':   'Crawler Vanguard',
            'Monk':      'Fist-Build Specialist',
            'Paladin':   'Oathbound Tank',
            'Ranger':    'Floor Scout',
            'Rogue':     'Trap Monkey',
            'Sorcerer':  'Glass Cannon',
            'Warlock':   'Sponsor-Bound',
            'Wizard':    'System Mage',
        },
        'race_skins': {
            'Human':      'Baseline Human',
            'Dwarf':      'Stout Build',
            'Elf':        'Agility Build',
            'Gnome':      'Small-Frame Build',
            'Goliath':    'Titan Build',
            'Half-Elf':   'Hybrid Build',
            'Half-Orc':   'Bruiser Build',
            'Halfling':   'Lucky Build',
            'Orc':        'Rage Build',
            'Tiefling':   'Cursed Build',
            'Dragonborn': 'Scaled Build',
        },
        'names': {
            'style': 'epithet',   # "First 'Epithet' Last" (sometimes)
            'firsts': ['Doug', 'Sam', 'Katia', 'Marcus', 'Priya', 'Trevor',
                       'Jess', 'Hank', 'Maya', 'Ben', 'Carla', 'Steve',
                       'Nadia', 'Ray', 'Tina', 'Omar'],
            'lasts': ['Herrera', 'Kowalski', 'Chen', 'Okafor', 'Brooks',
                      'Ramirez', 'Nguyen', 'Miller', 'Park', 'Ivanov',
                      'Santos', 'Fletcher'],
            'epithets': ['Floor Grinder', 'Lootbag', 'Crit Machine', 'Pancake',
                         'Stairmaster', 'Two-Swords', 'Discount Hero',
                         'Patch Notes', 'Respawn', 'Tutorial Skipper'],
        },
        'backgrounds': {
            'Ex-Office Worker': {
                'traits': [
                    "I narrate loot drops like quarterly earnings reports.",
                    "I keep trying to schedule the party's dungeon runs in advance.",
                    "Deadlines don't scare me. I've survived performance reviews.",
                    "I stress-organize my inventory alphabetically mid-crisis.",
                ],
                'ideals': [
                    "Efficiency. Every floor has an optimal route. I will find it.",
                    "Solidarity. Nobody gets left behind like they left us up top.",
                    "Reinvention. The old me died in the elevator. Good riddance.",
                ],
                'bonds': [
                    "My old work rival is three floors ahead. Unacceptable.",
                    "I carry a coffee mug from the surface. It's load-bearing now.",
                    "My team lead sacrificed herself on floor two. I level up for her.",
                ],
                'flaws': [
                    "I read every item description out loud. Every one. Even fleeing.",
                    "I hoard consumables I'm 'saving for the right moment.'",
                    "I trust the System's patch notes more than my own party.",
                ],
            },
            'Retired Athlete': {
                'traits': [
                    "I treat every fight like the championship I never got.",
                    "Pre-dungeon stretching routine. Non-negotiable. Join me.",
                    "I trash-talk monsters by name and stat block.",
                    "I celebrate crits with a signature victory pose.",
                ],
                'ideals': [
                    "Discipline. Talent gets you to floor three. Training gets you out.",
                    "Team. I've carried squads before. Watch me do it again.",
                    "Legacy. They'll replay my highlight reel for centuries.",
                ],
                'bonds': [
                    "My old coach's voice is still in my head, and it's usually right.",
                    "A rookie crawler wears my merch. I cannot let them die.",
                    "My bad knee got fixed by a level-up. I owe this dungeon one.",
                ],
                'flaws': [
                    "I take every leaderboard placement personally.",
                    "I play through injuries I absolutely should not play through.",
                    "If there's a crowd watching, I showboat. Mid-boss-fight.",
                ],
            },
            'Conspiracy Blogger': {
                'traits': [
                    "I called this. I literally have a post from 2019 calling this.",
                    "I document everything — the System is definitely hiding stats.",
                    "I whisper theories about the dungeon AI to anyone who'll listen.",
                    "I read the terms and conditions on every System message.",
                ],
                'ideals': [
                    "Truth. Somebody built this dungeon, and I'll find out who.",
                    "Free Information. My guides are free. Knowledge wants out.",
                    "Vindication. Every floor proves I was never crazy.",
                ],
                'bonds': [
                    "My subscribers are still alive somewhere. I post for them.",
                    "An anonymous tip saved my life on floor one. I owe a stranger.",
                    "The System flagged my account. Now it's personal.",
                ],
                'flaws': [
                    "I see patterns in everything, including actual coincidences.",
                    "I'll poke the obviously suspicious lever. For content.",
                    "I don't trust NPCs. Or shopkeepers. Or my party. Or you.",
                ],
            },
            'Line Cook': {
                'traits': [
                    "I rate monster parts by braising potential.",
                    "Yelling 'behind!' when passing party members. Old habit.",
                    "I can improvise a meal from anything with a stat block.",
                    "Calm in a boss fight; the Friday rush was worse.",
                ],
                'ideals': [
                    "Craft. Even in hell's basement, plating matters.",
                    "Family Meal. A fed party is a party that survives.",
                    "Heat. If you can't take the kitchen, get off my floor.",
                ],
                'bonds': [
                    "My knife roll made it down here with me. It's family.",
                    "The dungeon's tavern NPC gave me a job when I was broke. Loyalty.",
                    "Someone in my party hasn't eaten a hot meal in weeks. Fixing that.",
                ],
                'flaws': [
                    "I will absolutely taste the suspicious glowing mushroom.",
                    "My temper has a smoke point, and it's low.",
                    "I fed a monster once because it looked hungry. It follows us now.",
                ],
            },
            'Rideshare Driver': {
                'traits': [
                    "I know every floor's shortcuts by day two.",
                    "I make small talk with monsters before fighting them.",
                    "Five stars. I maintain five stars in everything I do.",
                    "I've got snacks, water, and a phone charger. Somehow. Still.",
                ],
                'ideals': [
                    "The Route. There's always a faster way. Trust me.",
                    "Service. People in my care arrive alive. Ratings reflect this.",
                    "Hustle. Every side quest is surge pricing if you squint.",
                ],
                'bonds': [
                    "My last passenger never made it out of the parking garage. I did.",
                    "My car is down here somewhere, upgraded into something horrible.",
                    "A regular passenger is crawling this dungeon too. I'll find them.",
                ],
                'flaws': [
                    "I take detours. Scenic ones. During timed escapes.",
                    "I can't turn down a fare — or a quest — no matter how sketchy.",
                    "I rate everyone I meet out of five and adjust in real time.",
                ],
            },
            'Retail Survivor': {
                'traits': [
                    "Nothing a monster does is worse than a holiday sale crowd.",
                    "I refold and restock every shop I enter. Compulsively.",
                    "I have a customer-service voice for negotiating with bosses.",
                    "I know a scam markup when I see one, dungeon shop.",
                ],
                'ideals': [
                    "Patience. I have outlasted worse than you, lich king.",
                    "The Union. Crawlers have to stick together or we're all stock.",
                    "Fair Prices. The vendors down here are criminals. I'll haggle.",
                ],
                'bonds': [
                    "My shift crew got scattered across three floors. Regrouping.",
                    "The dungeon shopkeep slips me discounts. We have an understanding.",
                    "Someone shoplifted my only healing potion. It's not about the potion.",
                ],
                'flaws': [
                    "The customer-service smile comes out under stress. It unnerves people.",
                    "I cannot walk past a clearance bin, even a mimic-shaped one.",
                    "I've absorbed so much corporate policy I quote it as scripture.",
                ],
            },
        },
        'art_style': [
            'Vibrant LitRPG illustration with a streak of dark comedy',
            'Faint translucent holographic glow hinting at a game interface — abstract light shapes only, absolutely no readable text, numbers, icons, or UI panels',
            'Dungeon corridor backdrop lit by torchlight and neon loot-glow',
            'Practical scavenged gear mixed with one absurd piece of magical loot',
            'Determined expression with a hint of disbelief at the situation',
        ],
    },

    # ── Void Marines (grimdark sci-fi) ─────────────────────────────────────────
    'voidmarines': {
        'label': 'Void Marines (sci-fi)',
        'class_skins': {
            'Barbarian': 'Assault Breacher',
            'Bard':      'Vox Officer',
            'Cleric':    'Field Chaplain',
            'Druid':     'Xenobiologist',
            'Fighter':   'Tactical Marine',
            'Monk':      'CQC Specialist',
            'Paladin':   'Templar Knight',
            'Ranger':    'Recon Sniper',
            'Rogue':     'Infiltrator',
            'Sorcerer':  'Latent Psyker',
            'Warlock':   'Pact-AI Host',
            'Wizard':    'Tech-Adept',
        },
        'race_skins': {
            'Human':      'Terran',
            'Dwarf':      'Heavyworlder',
            'Elf':        'Voidborn',
            'Gnome':      'Station Rat',
            'Goliath':    'Juggernaut Clone',
            'Half-Elf':   'Spacer',
            'Half-Orc':   'Vat-Grown',
            'Halfling':   'Lowdecker',
            'Orc':        'Warform Clone',
            'Tiefling':   'Geneforged',
            'Dragonborn': 'Saurian Uplift',
        },
        'names': {
            'style': 'rank_callsign',   # "Sergeant Karrow 'Ironside'"
            'ranks': [(1, 'Recruit'), (3, 'Trooper'), (6, 'Corporal'),
                      (9, 'Sergeant'), (13, 'Lieutenant'), (17, 'Captain')],
            'lasts': ['Karrow', 'Voss', 'Drax', 'Herne', 'Malik', 'Stroud',
                      'Vex', 'Odan', 'Rusk', 'Tarn', 'Kade', 'Bram'],
            'callsigns': ['Ironside', 'Ghost', 'Havoc', 'Anchor', 'Ember',
                          'Static', 'Bulwark', 'Longshot', 'Warden', 'Grit',
                          'Halo', 'Breaker'],
        },
        'backgrounds': {
            'Hive-City Conscript': {
                'traits': [
                    "I eat fast and sleep armored; the hive taught me both.",
                    "Open sky still makes my trigger hand itch.",
                    "I stencil kill-tallies where regulations technically allow.",
                    "I'm calmer in a crowd of thousands than a room of three.",
                ],
                'ideals': [
                    "Ascension. The regiment lifted me out of the under-levels; I climb for those still down there.",
                    "Duty. The line holds because someone like me holds it.",
                    "Brotherhood. The squad is the only hive that matters now.",
                ],
                'bonds': [
                    "My conscription saved my block from a tithe. They fly my colors.",
                    "The recruiter who pulled me from the stacks died at Cordan Gate.",
                    "My sister is still in the under-hive. Every wage packet goes home.",
                ],
                'flaws': [
                    "I obey bad orders too long before I question them.",
                    "I hoard rations even at the victory feast.",
                    "Officers from the spires make my jaw clench. Visibly.",
                ],
            },
            'Noble Cadet': {
                'traits': [
                    "My armor is regulation. My armor's finish is not.",
                    "I quote academy doctrine chapter and verse, usually correctly.",
                    "I write condolence letters personally. All of them.",
                    "I duel with sidearm etiquette even in a knife fight.",
                ],
                'ideals': [
                    "Honor. My house's name goes where I go, including into the breach.",
                    "Command. Privilege means my body between the guns and theirs.",
                    "Merit. I refuse every door my name opens; I'll kick in my own.",
                ],
                'bonds': [
                    "My family bought my commission; I'm still paying for it my way.",
                    "My academy roommate serves the enemy fleet. We were friends. Are.",
                    "The family blade is mag-locked to my hip. It has never retreated.",
                ],
                'flaws': [
                    "I take casualties as personal accounting errors.",
                    "I cannot resist correcting a superior's tactics. Aloud.",
                    "Deep down I suspect I'm a name wearing armor, and it drives me.",
                ],
            },
            'Penal Legion Transfer': {
                'traits': [
                    "I volunteer for point. Habit from when it wasn't voluntary.",
                    "I count exits, guards, and cameras in every room. Old math.",
                    "Gallows humor. The gallows were literal.",
                    "I keep my sentence tattooed where I can see it.",
                ],
                'ideals': [
                    "Redemption. Every drop mission buys back a piece of my name.",
                    "Loyalty. The legion took me when the law was done with me.",
                    "Truth. I did it. Owning it is the only armor that never cracks.",
                ],
                'bonds': [
                    "The magistrate who sentenced me was right. I send her my medals.",
                    "Three of us survived the penal drop at Vask. We don't talk. We nod.",
                    "My victim's family doesn't know I'm alive. My pay says otherwise, anonymously.",
                ],
                'flaws': [
                    "I don't believe I deserve to make it home, and I fight like it.",
                    "Authority still smells like a cell door to me.",
                    "I confess to things I didn't do just to keep the record simple.",
                ],
            },
            'Void Station Orphan': {
                'traits': [
                    "I sleep strapped in, even planetside.",
                    "I can tell a ship's health by the hum in the deck plates.",
                    "Gravity is a luxury; I move like I don't trust it.",
                    "I stash tools, food, and air in every compartment I'm assigned.",
                ],
                'ideals': [
                    "The Manifest. Everyone aboard is everyone's responsibility.",
                    "Salvage. Nothing and no one is beyond reclamation.",
                    "The Hull. Keep the void out and the crew in. Everything else is noise.",
                ],
                'bonds': [
                    "The dock crew that raised me still holds my berth open.",
                    "I sealed a bulkhead with my best friend on the wrong side. Never again.",
                    "Somewhere a derelict holds my parents' last log entry. I'll find it.",
                ],
                'flaws': [
                    "Airlocks. I check them. Twice. Sometimes mid-conversation.",
                    "I value equipment over strangers, and it shows.",
                    "I don't ask for help; stations that beg get scrapped.",
                ],
            },
            'Decorated Veteran': {
                'traits': [
                    "I clean my rifle before my wounds. In that order.",
                    "New troopers get my rations and my war stories, like it or not.",
                    "I remember every name on both sides of the wire.",
                    "Medals stay in the footlocker; scars do the talking.",
                ],
                'ideals': [
                    "The Mission. Sentiment is a luxury purchased with other people's lives.",
                    "Stewardship. My job now is bringing the young ones home.",
                    "Peace. I've seen enough glory to know what it costs wholesale.",
                ],
                'bonds': [
                    "My old company's banner hangs in my quarters. Forty names on the back.",
                    "The enemy commander at Threx Ridge spared my squad. I owe a debt I hate.",
                    "My medal belongs to the trooper who actually did it. Finding her family.",
                ],
                'flaws': [
                    "I fight the last war in every new one.",
                    "Quiet nights are worse for me than bombardment.",
                    "I can't delegate the dangerous jobs. That's how you lose rookies.",
                ],
            },
            'Reclaimed Deserter': {
                'traits': [
                    "I flinch at retreat orders — both directions.",
                    "I know every unofficial route off every official map.",
                    "I keep my kit packed for a departure I no longer plan to make.",
                    "I watch the wavering ones; I know the look from mirrors.",
                ],
                'ideals': [
                    "Second Chances. I got one. I'm the proof they're worth issuing.",
                    "Conscience. I ran from a massacre, not a battle. I'd run again.",
                    "The Squad. I left an army once. I will not leave these people.",
                ],
                'bonds': [
                    "The chaplain who brought me back vouched with his own rank.",
                    "The village I refused to burn sends me harvest bread every year.",
                    "My old squadmates died in the push I fled. I carry their tags.",
                ],
                'flaws': [
                    "Part of me is always calculating the way out.",
                    "I overcompensate — volunteering for suicide details to prove myself.",
                    "I judge deserters with the fury of a man judging himself.",
                ],
            },
        },
        'art_style': [
            'Grimdark military science-fiction concept art',
            'Battle-scarred powered armor with chipped paint, purity seals, and service studs',
            'Harsh rim lighting from a starship interior or a burning battlefield',
            'Cables, servos, and venting vapor around the armor collar',
            'Grim, resolute expression of a veteran of void war',
        ],
    },

    # ── Wasteland (post-apocalyptic road war) ─────────────────────────────────
    'wasteland': {
        'label': 'Wasteland (road war)',
        'class_skins': {
            'Barbarian': 'War Boy',
            'Bard':      'Wasteland DJ',
            'Cleric':    'Cult Doc',
            'Druid':     'Dust Shaman',
            'Fighter':   'Road Warrior',
            'Monk':      'Pit Fighter',
            'Paladin':   'Convoy Guardian',
            'Ranger':    'Route Scout',
            'Rogue':     'Scavenger',
            'Sorcerer':  'Radtouched',
            'Warlock':   'Cargo Cultist',
            'Wizard':    'Scrap Tinkerer',
        },
        'race_skins': {
            'Human':      'Settler',
            'Dwarf':      'Bunker-Born',
            'Elf':        'Pureblood',
            'Gnome':      'Vault Tinker',
            'Goliath':    'Brute Mutant',
            'Half-Elf':   'Drifter',
            'Half-Orc':   'Mutant Bruiser',
            'Halfling':   'Tunnel Rat',
            'Orc':        'Feral Mutant',
            'Tiefling':   'Radborn',
            'Dragonborn': 'Scaleskin',
        },
        'names': {
            'style': 'handle',   # "Axle Rustveil", sometimes just "Axle"
            'firsts': ['Axle', 'Mags', 'Rust', 'Diesel', 'Sprocket', 'Gash',
                       'Nitro', 'Cinder', 'Blitz', 'Tarmac', 'Viper', 'Socket',
                       'Crank', 'Echo', 'Fuse', 'Grit'],
            'lasts': ['Rustveil', 'Blackfuel', 'Chromejaw', 'Dustrunner',
                      'Wreckage', 'Redline', 'Scrapiron', 'Ashfall',
                      'Gearlock', 'Roadburn'],
        },
        'backgrounds': {
            'Convoy Brat': {
                'traits': [
                    "I was born doing ninety; standing still feels like dying.",
                    "I can sleep through engine roar but wake at a fuel-line hiss.",
                    "Every rig in the convoy has a name and a personality. I did that.",
                    "I talk to vehicles more gently than to people.",
                ],
                'ideals': [
                    "The Convoy. We move together or we're just parts on the road.",
                    "Motion. Settlements are where hope goes to rust.",
                    "The Trade. Roads exist so people can keep their word across them.",
                ],
                'bonds': [
                    "My rig was my mother's; every weld tells a story.",
                    "The convoy that raised me runs the northern route. I fly their pennant.",
                    "A breakdown cost us my little brother to the dust. Never again.",
                ],
                'flaws': [
                    "I trust my mirrors more than my friends.",
                    "I'll strip parts off anything not actively being used. Or watched.",
                    "Roots terrify me; I sabotage every chance to settle.",
                ],
            },
            'Vault Exile': {
                'traits': [
                    "I still say 'topside' like it's a foreign country.",
                    "I ration everything, including good news.",
                    "Sunlight is a miracle and I stare like it.",
                    "I quote the Vault Manual in emergencies. It's never once applied.",
                ],
                'ideals': [
                    "The Open Sky. I was caged by the people who saved me. Never again.",
                    "Knowledge. The old world's mistakes are a manual, not a eulogy.",
                    "Shelter. Everyone deserves a door that locks from the inside.",
                ],
                'bonds': [
                    "They sealed the door behind me. Someone I love is still inside.",
                    "The overseer branded me a traitor for being right.",
                    "My vault suit is patched beyond recognition. It stays on.",
                ],
                'flaws': [
                    "Crowds under open sky make me hyperventilate.",
                    "I trust filtration readouts over my own senses.",
                    "I secretly believe surface people are temporary. Even these ones.",
                ],
            },
            'Raider Defector': {
                'traits': [
                    "I sit with my back to the engine block, never the door.",
                    "War paint comes off; the reflexes don't.",
                    "I appraise every stranger by ransom value first. Old habit. Mostly old.",
                    "I'm politest to the people I could hurt the worst.",
                ],
                'ideals': [
                    "Penance. Every settlement I guard is one I used to raid.",
                    "Strength. I still believe the strong rule; I just changed what strong means.",
                    "Mercy. Somebody showed me some once. It cracked me open.",
                ],
                'bonds': [
                    "The warlord I abandoned put a bounty on me. It's insultingly low.",
                    "I spared a farm family on my last raid. They took me in.",
                    "My old crew has my sister riding with them. Getting her out.",
                ],
                'flaws': [
                    "Violence is still my first language; everything else is translation.",
                    "I keep a trophy from the bad years. I can't explain why.",
                    "When the fuel runs low, the old math comes back.",
                ],
            },
            'Trade Post Merchant': {
                'traits': [
                    "Everything's for sale; the price just gets rude.",
                    "I weigh strangers like produce and I'm rarely off by much.",
                    "Ledger first, condolences after.",
                    "I know the exchange rate of caps, cogs, and clean water in every town.",
                ],
                'ideals': [
                    "Commerce. Trade is the only thing that ever rebuilt anything.",
                    "Reputation. My word clears customs at every gate in the dust.",
                    "Neutrality. I sell to all sides; it's the only honest politics left.",
                ],
                'bonds': [
                    "My trade post burned with a season's stock inside. The arsonist shops elsewhere now. I'll find where.",
                    "A caravan guard took a bolt for me over a crate of batteries.",
                    "My scales were my father's. They've never once lied.",
                ],
                'flaws': [
                    "I price friendships. Quietly, but I do.",
                    "I can't resist a margin, even on people I like.",
                    "Debt collectors from three territories know my aliases.",
                ],
            },
            'Water Farmer': {
                'traits': [
                    "I taste water like sommeliers tasted wine. This is a 'two-filter' town.",
                    "I check the sky first, exits second, people third.",
                    "Patience of a drip line. Fury of a flash flood.",
                    "I wash my hands with a ritual thoroughness that unsettles raiders.",
                ],
                'ideals': [
                    "The Well. Water is the one vote everyone casts daily.",
                    "Patience. Deserts bloom for those who plan in decades.",
                    "The Commons. Whoever owns the water owns the people. Nobody should.",
                ],
                'bonds': [
                    "My aquifer feeds three settlements. They don't know it's failing.",
                    "A cartel salted my family's well. I remember every face.",
                    "I owe my life to a stranger's canteen, half-full, left on a rock.",
                ],
                'flaws': [
                    "I hoard water even at a working tap.",
                    "I judge people instantly by how they treat a shared canteen.",
                    "I'd let a bad man die of thirst. I know because I have.",
                ],
            },
            'Arena Champion': {
                'traits': [
                    "I bow to opponents. The crowd taught me; the crowd can't unteach me.",
                    "I read a fighter's whole style from how they step off a truck.",
                    "Scars are my resume and I present them accordingly.",
                    "Before a fight I go quiet. The loud ones die in round one.",
                ],
                'ideals': [
                    "The Circle. Rules make violence mean something. Outside them it's just loss.",
                    "Glory. Roaring crowds are the only currency that never devalues.",
                    "Freedom. I fought my way out of a collar. Every match since is a choice.",
                ],
                'bonds': [
                    "The promoter who owned my contract still thinks he owns me.",
                    "I killed a friend in the circle. His family gets my winnings.",
                    "A kid in the stands copies my stance. I fight cleaner now.",
                ],
                'flaws': [
                    "I can't refuse a challenge issued in front of people.",
                    "I telegraph mercy; smart enemies exploit it.",
                    "Outside the arena, I keep waiting for a bell that isn't coming.",
                ],
            },
        },
        'art_style': [
            'Gritty post-apocalyptic concept art',
            'Dust-caked leathers, welded scrap armor, and road-worn goggles',
            'Desert glare with heat shimmer and blowing sand',
            'War-rig chrome, grease smears, and sun-bleached war paint',
            'The hardened squint of someone who survived the open roads',
        ],
    },

    # ── Spacefaring Society (optimistic space opera) ──────────────────────────
    'spacefaring': {
        'label': 'Spacefaring Society',
        'class_skins': {
            'Barbarian': 'Shock Trooper',
            'Bard':      'Diplomat-Envoy',
            'Cleric':    "Ship's Surgeon",
            'Druid':     'Terraform Ecologist',
            'Fighter':   'Fleet Security Officer',
            'Monk':      'Zero-G Specialist',
            'Paladin':   'Peacekeeper',
            'Ranger':    'Survey Scout',
            'Rogue':     'Smuggler',
            'Sorcerer':  'Esper',
            'Warlock':   'AI-Symbiont',
            'Wizard':    'Science Officer',
        },
        'race_skins': {
            'Human':      'Earther',
            'Dwarf':      'High-Grav Colonist',
            'Elf':        'Long-Haul Spacer',
            'Gnome':      'Ring-Station Native',
            'Goliath':    'Titan Colonist',
            'Half-Elf':   'Dual-World Citizen',
            'Half-Orc':   'Frontier Colonist',
            'Halfling':   'Asteroid Homesteader',
            'Orc':        'Exo-Labor Clone',
            'Tiefling':   'Gene-Modded Pioneer',
            'Dragonborn': 'Saurian Ally',
        },
        'names': {
            'style': 'rank_fullname',   # "Lieutenant Amara Okafor"
            'ranks': [(1, 'Ensign'), (5, 'Lieutenant'), (9, 'Lt. Commander'),
                      (13, 'Commander'), (17, 'Captain')],
            'firsts': ['Amara', 'Jax', 'Ilsa', 'Ravi', 'Zoe', 'Kenji', 'Lena',
                       'Marcus', 'Suri', 'Talia', 'Idris', 'Nova', 'Elias',
                       'Yuki', 'Dane', 'Priya'],
            'lasts': ['Okafor', 'Reyes', 'Tanaka', 'Volkov', 'Adeyemi',
                      'Lindqvist', 'Chandra', 'Moreau', 'Kessler', 'Osei',
                      'Halloran', 'Zhou'],
        },
        'backgrounds': {
            'Academy Graduate': {
                'traits': [
                    "I cite the regulation number before breaking it.",
                    "My bunk passes inspection. Yours could. Want help?",
                    "I still hum the academy anthem during pre-flight checks.",
                    "Simulations first, heroics second. Usually.",
                ],
                'ideals': [
                    "Service. The uniform means every colonist sleeps easier.",
                    "Excellence. Good enough gets people killed at 0.3c.",
                    "The Charter. We carry civilization outward, or we carry nothing.",
                ],
                'bonds': [
                    "My graduating class scattered across forty ships. We still sync birthdays.",
                    "My instructor failed me once to save my life. I know that now.",
                    "The cadet I tutored outranks me. I've never been prouder. Or saltier.",
                ],
                'flaws': [
                    "Improvisation feels like failure to me.",
                    "I salute problems that need hugging.",
                    "My class rank is engraved in my memory. Second. It was second.",
                ],
            },
            "Colony Founder's Kid": {
                'traits': [
                    "I compare every world's soil to home. Home loses politely.",
                    "First-generation problems: I fix things that aren't broken yet.",
                    "I name landmarks reflexively. That ridge is Fredo's Spine now.",
                    "I keep seeds in my luggage. Regulation-compliant seeds. Mostly.",
                ],
                'ideals': [
                    "Roots. Every world deserves someone who refuses to leave.",
                    "Legacy. My parents built a town from a cargo pod; I think bigger.",
                    "Hospitality. On the frontier, a closed airlock is a death sentence.",
                ],
                'bonds': [
                    "The colony bell was cast from our landing capsule. I'd die for that sound.",
                    "Mom's terraforming journals are half science, half love letters. I finish what she started.",
                    "The first grave on our world has my grandfather's name. He'd love where I'm going.",
                ],
                'flaws': [
                    "I take criticism of the colonies personally. Loudly.",
                    "I plant flags — figurative ones — on things that aren't mine to claim.",
                    "Homesickness hits me mid-mission like a hull breach.",
                ],
            },
            'Salvage Crew Veteran': {
                'traits': [
                    "I can tell a ship's story from its scorch patterns.",
                    "Nothing on my belt is new; everything on my belt works.",
                    "I talk to derelicts. Respectfully. They've earned it.",
                    "I estimate mass, value, and tow time of everything I see. Including you.",
                ],
                'ideals': [
                    "Reclamation. The void wastes nothing; neither do I.",
                    "The Crew Cut. Shares are sacred; skimming is spacing.",
                    "Memory. Every wreck was somebody's home. Log the names.",
                ],
                'bonds': [
                    "My first captain's beacon still pings from the Kuiper dark. Someday.",
                    "We found a cryo-pod, alive, in a hundred-year wreck. She's my sister now.",
                    "My cutting rig is paid off in three more hauls. She flies with me forever after.",
                ],
                'flaws': [
                    "I pocket souvenirs from every site. It's not stealing if it's drifting.",
                    "I'd board a red-flagged wreck for the right cargo manifest.",
                    "Insurance adjusters and I are not on speaking terms. Sector-wide.",
                ],
            },
            'First Contact Witness': {
                'traits': [
                    "I learn hello in every language, including the ones with no sound.",
                    "I keep a translation slate charged and a gift in my pocket. Always.",
                    "Silence doesn't rattle me; some species take a year to answer.",
                    "I document everything twice: once in data, once in wonder.",
                ],
                'ideals': [
                    "The Handshake. Meeting well matters more than meeting first.",
                    "Humility. We are somebody's strange lights in the sky too.",
                    "Wonder. The universe keeps introducing itself. Show up polite.",
                ],
                'bonds': [
                    "The being I met left a mark on my palm that translators can't parse. It glows near truth.",
                    "My contact partner stayed behind on the ring. Half my reports are letters to her.",
                    "The signal that started everything repeats every 47 days. So do my nightmares. Good ones.",
                ],
                'flaws': [
                    "I trust the profoundly alien faster than my own species.",
                    "Protocol bores me at exactly the wrong moments.",
                    "I've seen too much to small-talk; I open with the meaning of life.",
                ],
            },
            'Corporate Defector': {
                'traits': [
                    "I read contracts for sport and terms-of-service for threats.",
                    "My old employee ID lives in my boot. Evidence, not nostalgia.",
                    "I budget escape routes the way others budget rations.",
                    "Boardroom calm; I've delivered worse news to worse people.",
                ],
                'ideals': [
                    "Transparency. Sunlight is cheap in space; use it.",
                    "People Over Profit. I've read the actuarial tables that say otherwise. Burned them, too.",
                    "Accountability. Somebody signed the order. Somebodies answer.",
                ],
                'bonds': [
                    "The whistle I blew saved a station and cost me everything else.",
                    "My old team still inside feeds me tips at terrible risk.",
                    "The settlement money went to the victims' fund. All of it. I kept the guilt.",
                ],
                'flaws': [
                    "I see NDAs in every handshake.",
                    "I sabotage my own happiness right before quarterly reviews. Old rhythm.",
                    "Part of me still optimizes people like line items.",
                ],
            },
            'Generation Ship Descendant': {
                'traits': [
                    "I think in decades and pack for centuries.",
                    "Corridors feel like home; horizons feel like falling.",
                    "I maintain machines my great-grandparents calibrated, with their handwriting beside mine.",
                    "Every meal I make stretches for eight. Recipes remember the rationing.",
                ],
                'ideals': [
                    "The Voyage. Arrival isn't the point; deserving to arrive is.",
                    "Continuity. I am a link in a chain of hands. The chain holds.",
                    "The Manifest. Every soul aboard matters or the math of the journey fails.",
                ],
                'bonds': [
                    "My family tends Engine Three for six generations. It has our name on it, unofficially.",
                    "The ship arrived the year I was born. I'm the first free step of a 300-year walk.",
                    "Grandmother's voice is still in the ship's archive, reading the departure log. I visit.",
                ],
                'flaws': [
                    "Waste physically upsets me — I'll dig your apple core out of the recycler.",
                    "I defer to ship's protocol on worlds that have never heard it.",
                    "Open sky agoraphobia. Helmets help. Pretending it's a viewport helps more.",
                ],
            },
        },
        'art_style': [
            'Optimistic space-opera concept art, clean and cinematic',
            'Fitted flight suit or duty uniform with mission patches',
            'Cool starlight and console glow from an observation deck',
            'A sliver of planet or starfield visible behind them',
            'Confident, hopeful expression of a frontier explorer',
        ],
    },
}


def get_pack(genre):
    return GENRE_PACKS.get(genre or '')


def genre_labels():
    """[(key, label)] for the dropdown, fantasy first."""
    return [('fantasy', 'Fantasy (D&D)')] + \
           [(k, p['label']) for k, p in GENRE_PACKS.items()]


def genre_display(genre, char_class, race):
    """(archetype, species) display labels, or ('', '') for plain fantasy."""
    pack = get_pack(genre)
    if not pack:
        return '', ''
    return (pack['class_skins'].get(char_class, char_class),
            pack['race_skins'].get(race, race))


def _rank_for(ranks, level):
    title = ranks[0][1]
    for min_level, rank in ranks:
        if level >= min_level:
            title = rank
    return title


def generate_genre_name(genre, level, rng):
    """Genre-styled character name; level drives rank where the genre has them."""
    pack = get_pack(genre)
    if not pack:
        return None
    n = pack['names']
    style = n['style']
    if style == 'rank_callsign':
        return (f"{_rank_for(n['ranks'], level)} {rng.choice(n['lasts'])} "
                f"'{rng.choice(n['callsigns'])}'")
    if style == 'rank_fullname':
        return (f"{_rank_for(n['ranks'], level)} {rng.choice(n['firsts'])} "
                f"{rng.choice(n['lasts'])}")
    if style == 'epithet':
        first, last = rng.choice(n['firsts']), rng.choice(n['lasts'])
        if rng.random() < 0.4:
            return f"{first} '{rng.choice(n['epithets'])}' {last}"
        return f"{first} {last}"
    # 'handle': surname is optional flavor
    first = rng.choice(n['firsts'])
    if rng.random() < 0.6:
        return f"{first} {rng.choice(n['lasts'])}"
    return first


def client_data():
    """Display data for browser-side prompt builders: skins + art style."""
    return {
        key: {
            'label': pack['label'],
            'class_skins': pack['class_skins'],
            'race_skins': pack['race_skins'],
            'art_style': pack['art_style'],
        }
        for key, pack in GENRE_PACKS.items()
    }


# ── Map prompts: per-genre battlemap + travel-map generation data ─────────────
# Same idea as the character packs, applied to the battlemap Image Prompt
# modal. 'battle' environments are encounter-scale (5-ft squares); 'travel'
# environments are large-scale maps for tracking the party across long
# distances — each carries a sensible default for what one grid square
# represents. 'flavor' lines are cartographic art direction appended to the
# prompt. 'fantasy' is a full entry here (unlike GENRE_PACKS, where plain
# D&D is the absence of a pack) because maps always need environment lists.

MAP_PROMPTS = {
    'fantasy': {
        'label': 'Fantasy (D&D)',
        'battle_envs': [
            'Dungeon / Underground', 'Forest / Wilderness', 'Tavern / Inn',
            'Cave / Cavern', 'City Street / Town', 'Ocean / Ship Deck',
            'Mountain / Cliffside', 'Swamp / Marsh', 'Castle / Keep',
            'Ancient Ruins', 'Hell / Abyss', 'Celestial / Ethereal Plane',
        ],
        'travel_envs': [
            {'name': 'World / Continent Map',        'scale': '60 miles'},
            {'name': 'Kingdom / Region Map',         'scale': '6 miles'},
            {'name': 'Ocean / Nautical Chart',       'scale': '30 miles'},
            {'name': 'Wilderness Hex-Crawl Region',  'scale': '3 miles'},
            {'name': 'City & Surroundings Overview', 'scale': '1 mile'},
            {'name': 'Underdark Depths',             'scale': '6 miles'},
            {'name': 'Planar / Astral Sea Chart',    'scale': '100 miles'},
        ],
        'flavor': [
            'Hand-drawn fantasy cartography on aged parchment',
            'Inked coastlines, mountain ranges as tiny peaks, forests as clustered trees',
            'A compass rose and subtle rhumb lines where fitting',
            'Muted sepia base with colored accents for realms, roads, and sea routes',
        ],
    },
    'litrpg': {
        'label': 'Dungeon Crawl (LitRPG)',
        'battle_envs': [
            'Dungeon Floor — Stone Corridors', 'Boss Arena', 'Safe Room / Vendor Hub',
            'Trap Gauntlet', 'Neon-Lit Cavern', 'Collapsed Subway / Urban Ruins',
            'Mob Spawner Warrens', 'Stairwell Nexus Between Floors',
        ],
        'travel_envs': [
            {'name': 'Full Dungeon Floor Overview',      'scale': '500 feet'},
            {'name': 'Floor Hub & Tunnel Network',       'scale': '1000 feet'},
            {'name': 'Overrun City Overview',            'scale': '1 mile'},
            {'name': 'Post-System Continental Surface',  'scale': '60 miles'},
        ],
        'flavor': [
            "Dungeon-crawl auto-map aesthetic — crisp room outlines like an explorer's minimap",
            'A hint of game-interface styling: glowing waypoints and zone markers (abstract, no readable text)',
            'Vibrant torchlight-and-neon palette over dark stone',
        ],
    },
    'voidmarines': {
        'label': 'Void Marines (sci-fi)',
        'battle_envs': [
            'Starship Corridors / Boarding Action', 'Hangar Bay', 'Bridge / Command Deck',
            'Engine Room', 'Derelict Hulk Interior', 'Orbital Station Docking Ring',
            'Trench Line / Cratered Battlefield', 'Hive-City Alley',
        ],
        'travel_envs': [
            {'name': 'Star System Chart',          'scale': '1 AU'},
            {'name': 'Sector Starmap',             'scale': '5 light-years'},
            {'name': 'Planetary Assault Theater',  'scale': '25 miles'},
            {'name': 'Fleet Deployment Grid',      'scale': '10,000 km'},
        ],
        'flavor': [
            'Grimdark military starmap — near-black void with an etched grid and glowing unit markers',
            'Planets and stations as stark iconography; threat zones hatched in red',
            'Gothic-industrial chart framing, bone-white linework, ember accents (no readable text)',
        ],
    },
    'wasteland': {
        'label': 'Wasteland (road war)',
        'battle_envs': [
            'Ruined Highway Stretch', 'Scrap Fort / Compound', 'Canyon Ambush Pass',
            'Irradiated Crater', 'Fuel Depot', 'Dust-Storm Flats',
            'Collapsed Overpass Camp', 'Arena Pit',
        ],
        'travel_envs': [
            {'name': 'Wasteland Region Map',         'scale': '6 miles'},
            {'name': 'Trade Route Map',              'scale': '25 miles'},
            {'name': 'Continental Dead-Zone Map',    'scale': '100 miles'},
            {'name': 'City Ruin Overview',           'scale': '1 mile'},
        ],
        'flavor': [
            "Scavenger's road map — sun-bleached, oil-stained, hand-annotated look",
            'Highways as cracked arteries, settlements as scrap-metal icons, rad zones cross-hatched',
            'Faded ink over dust and rust tones (annotations abstract — no readable text)',
        ],
    },
    'spacefaring': {
        'label': 'Spacefaring Society',
        'battle_envs': [
            'Starship Deck Plan', 'Space Station Promenade', 'Colony Dome Interior',
            'Terraforming Outpost', 'Asteroid Mining Rig', 'Alien Ruin Site',
            'Shuttle Crash Site', 'Zero-G Cargo Hold',
        ],
        'travel_envs': [
            {'name': 'Star System Chart',          'scale': '1 AU'},
            {'name': 'Interstellar Route Map',     'scale': '1 light-year'},
            {'name': 'Planet Surface Survey Map',  'scale': '100 miles'},
            {'name': 'Orbital Traffic Chart',      'scale': '10,000 km'},
        ],
        'flavor': [
            'Clean, optimistic space-opera chart — deep blue void with luminous orbit lines',
            'Planets as beautiful detailed discs, stations and ships as crisp icons',
            'Soft holographic elegance without readable text or UI panels',
        ],
    },
}

# Travel maps: what one grid square can represent (the dropdown's option list;
# each travel_env above names its default).
TRAVEL_SCALES = [
    '500 feet', '1000 feet', '1 mile', '3 miles', '6 miles', '25 miles',
    '30 miles', '60 miles', '100 miles', '500 miles', '10,000 km',
    '1 AU', '1 light-year', '5 light-years',
]


def map_prompt_client_data():
    """MAP_PROMPTS + scale list for the battlemap manage page's JS."""
    return {'genres': MAP_PROMPTS, 'scales': TRAVEL_SCALES}


# ── Token icon prompts (homebrew monsters / ships / vehicles) ─────────────────
# Art direction for generating a TOKEN image — the picture on a homebrew
# entry that gets placed on a map. 'topdown' suits vehicles/ships/objects
# viewed from above on travel maps; portraits reuse the character packs'
# art_style. Both keyed like MAP_PROMPTS (fantasy included).

ICON_STYLES = {
    'fantasy': [
        'Rich painted-miniature style with crisp detail',
        'Weathered natural materials — wood, canvas, iron, rope, leather',
        'Colors that stand out against parchment-toned maps',
    ],
    'litrpg': [
        'Vibrant game-asset style with a subtle outline so it pops on dark dungeon floors',
        'A faint magical glow accent on key features',
        'Clean readable silhouette, like a high-end game sprite',
    ],
    'voidmarines': [
        'Grimdark military hardware — battle-scarred plating, gothic trim, purity seals',
        'Gunmetal and bone-white with ember engine accents',
        'Hard-edged silhouette readable against a black starfield',
    ],
    'wasteland': [
        'Welded scrap, rust streaks, sun-bleached paint, improvised armor plating',
        'Dust-caked wheels and hull details',
        'Warm desert palette that reads against cracked-earth maps',
    ],
    'spacefaring': [
        'Sleek clean hull design with luminous engine accents',
        'Believable hard-sci-fi surface detail; mission markings as shapes only (no readable text)',
        'Cool palette that reads against deep-blue space charts',
    ],
}

_FANTASY_PORTRAIT_STYLE = [
    'High quality digital fantasy RPG creature art',
    'Dramatic lighting that highlights form and texture',
    'Detailed textures on hide, scale, fur, or armor',
    'Epic fantasy illustration style',
]


def icon_prompt_client_data():
    """Per-genre art direction for the homebrew token-icon prompt builder:
    {key: {label, topdown: [...], portrait: [...]}}, fantasy first."""
    out = {}
    for key, m in MAP_PROMPTS.items():
        pack = GENRE_PACKS.get(key)
        out[key] = {
            'label': m['label'],
            'topdown': ICON_STYLES[key],
            'portrait': pack['art_style'] if pack else _FANTASY_PORTRAIT_STYLE,
        }
    return out

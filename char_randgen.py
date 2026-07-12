"""Random D&D 5e character generation (levels 1-20).

All content here is original or SRD-derived mechanics:
  - Stats: 4d6-drop-lowest, highest scores assigned to the class's key
    abilities, racial bonuses from tblRacesLibrary applied on top.
  - Leveling: ASIs counted from tblClassLevelsLibrary features_text,
    HP = max die at 1st + average die (rounded up) per level + CON mod/level,
    proficiency bonus straight from the class level table.
  - Names: per-race syllable assembly (original part lists, huge combination
    space, fully offline).
  - Personality/ideal/bond/flaw: original tables keyed by background, in the
    official format (the PHB's own tables are not open-licensed).

Pure functions take an explicit `rng` for testability; generate_character()
must run inside an app context (it reads the library tables).
"""
import random
import re

ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha']

# Which abilities matter most, per class: [primary, secondary, tertiary].
# The three highest rolls land here; the rest are shuffled.
CLASS_PRIORITIES = {
    'Barbarian': ['str', 'con', 'dex'],
    'Bard':      ['cha', 'dex', 'con'],
    'Cleric':    ['wis', 'con', 'str'],
    'Druid':     ['wis', 'con', 'dex'],
    'Fighter':   ['str', 'con', 'dex'],
    'Monk':      ['dex', 'wis', 'con'],
    'Paladin':   ['str', 'cha', 'con'],
    'Ranger':    ['dex', 'wis', 'con'],
    'Rogue':     ['dex', 'con', 'int'],
    'Sorcerer':  ['cha', 'con', 'dex'],
    'Warlock':   ['cha', 'con', 'dex'],
    'Wizard':    ['int', 'con', 'dex'],
}
DEFAULT_PRIORITY = ['str', 'con', 'dex']


def mod(score):
    return (score - 10) // 2


def roll_4d6_drop_lowest(rng):
    dice = sorted(rng.randint(1, 6) for _ in range(4))
    return sum(dice[1:])


def roll_stat_set(rng):
    """Six 4d6-drop-lowest rolls, sorted high to low."""
    return sorted((roll_4d6_drop_lowest(rng) for _ in range(6)), reverse=True)


def assign_stats(rolls, char_class, rng):
    """Map sorted rolls onto abilities: top three to the class priorities,
    the remaining three shuffled across whatever is left."""
    priority = CLASS_PRIORITIES.get(char_class, DEFAULT_PRIORITY)
    stats = {}
    for i, abil in enumerate(priority):
        stats[abil] = rolls[i]
    rest_abils = [a for a in ABILITIES if a not in priority]
    rest_rolls = list(rolls[3:])
    rng.shuffle(rest_rolls)
    for abil, roll in zip(rest_abils, rest_rolls):
        stats[abil] = roll
    return stats


_BONUS_RE = re.compile(r'([+-]\d+)\s*(STR|DEX|CON|INT|WIS|CHA)', re.IGNORECASE)


def apply_racial_bonuses(stats, ability_bonuses_text):
    """Apply bonuses like '+2 STR, +1 CHA' from tblRacesLibrary."""
    for amount, abil in _BONUS_RE.findall(ability_bonuses_text or ''):
        stats[abil.lower()] += int(amount)
    return stats


def apply_asis(stats, char_class, asi_count):
    """Spend Ability Score Improvements the standard way: +2 per ASI into the
    primary ability up to the cap of 20, then overflow down the priority list."""
    priority = CLASS_PRIORITIES.get(char_class, DEFAULT_PRIORITY)
    order = priority + [a for a in ABILITIES if a not in priority]
    for _ in range(asi_count * 2):          # each ASI = two +1 points
        for abil in order:
            if stats[abil] < 20:
                stats[abil] += 1
                break
    return stats


def hp_for(level, hit_die, con_mod):
    """Official average formula: max die at 1st, average (rounded up) after."""
    avg = hit_die // 2 + 1
    return max(1, hit_die + (level - 1) * avg + con_mod * level)


def prof_bonus_for(level):
    return 2 + (level - 1) // 4


# ── Names: original per-race syllable pools ────────────────────────────────────
# first = (starts, ends); last = (starts, ends). ~12-20 parts per slot gives
# tens of thousands of combinations per race.

NAME_PARTS = {
    'Dwarf': {
        'first': (['Thor', 'Bal', 'Dur', 'Grim', 'Kaz', 'Bron', 'Har', 'Mag',
                   'Thra', 'Dag', 'Von', 'Bor', 'Gral', 'Kil', 'Mor', 'Hel'],
                  ['in', 'ak', 'dur', 'gan', 'nar', 'din', 'grim', 'li',
                   'mund', 'rik', 'var', 'dek', 'brek', 'gra', 'run']),
        'last': (['Iron', 'Stone', 'Battle', 'Gold', 'Deep', 'Storm', 'Fire',
                  'Granite', 'Copper', 'Steel', 'Boulder', 'Ember'],
                 ['fist', 'beard', 'hammer', 'helm', 'forge', 'axe', 'shield',
                  'brow', 'breaker', 'delver', 'anvil', 'guard']),
    },
    'Elf': {
        'first': (['Ael', 'Syl', 'Thal', 'Eri', 'Lua', 'Fen', 'Cael', 'Ara',
                   'Ilya', 'Vael', 'Nai', 'Elo', 'Myth', 'Sera', 'Quel', 'Ash'],
                  ['ith', 'riel', 'wen', 'andra', 'ion', 'ara', 'ndil', 'thas',
                   'lia', 'vyn', 'nor', 'siel', 'phine', 'ryn', 'anis']),
        'last': (['Moon', 'Star', 'Silver', 'Dawn', 'Night', 'Wind', 'Leaf',
                  'Dusk', 'Sun', 'Mist', 'River', 'Frost'],
                 ['whisper', 'song', 'shade', 'runner', 'petal', 'shadow',
                  'brook', 'weaver', 'gazer', 'bloom', 'strider', 'light']),
    },
    'Halfling': {
        'first': (['Mer', 'Pip', 'Ros', 'Cor', 'Wil', 'Dai', 'Fin', 'Tan',
                   'Bel', 'Nor', 'Per', 'Lil', 'Sam', 'Tod', 'Vin', 'Mil'],
                  ['ric', 'pin', 'ette', 'do', 'la', 'bin', 'no', 'dle',
                   'ry', 'ver', 'kin', 'bee', 'dia', 'lo', 'nan']),
        'last': (['Green', 'Tea', 'Good', 'Under', 'Bramble', 'Honey', 'Warm',
                  'Apple', 'Tall', 'Quick', 'Merry', 'Puddle'],
                 ['bottle', 'leaf', 'barrel', 'hill', 'burrow', 'pot', 'foot',
                  'cheeks', 'fellow', 'step', 'brew', 'meadow']),
    },
    'Human': {
        'first': (['Al', 'Bran', 'Cass', 'Dor', 'El', 'Fal', 'Gar', 'Hen',
                   'Is', 'Jo', 'Kat', 'Leo', 'Mar', 'Ned', 'Ol', 'Ro',
                   'Sel', 'Tom', 'Vi', 'Wal'],
                  ['dric', 'na', 'ian', 'a', 'ric', 'en', 'iel', 'ett',
                   'ard', 'ora', 'as', 'ine', 'mund', 'issa', 'ton']),
        'last': (['Ash', 'Black', 'Cross', 'Fair', 'Grey', 'Hill', 'Long',
                  'North', 'Ridge', 'Strong', 'West', 'Wood'],
                 ['wood', 'well', 'man', 'field', 'water', 'brook', 'bridge',
                  'bourne', 'ley', 'stone', 'march', 'gate']),
    },
    'Dragonborn': {
        'first': (['Ar', 'Bala', 'Dra', 'Ghesh', 'Kriv', 'Med', 'Nala',
                   'Pand', 'Rho', 'Sham', 'Tor', 'Zed', 'Quar', 'Hesk'],
                  ['jhan', 'sar', 'gar', 'rash', 'din', 'axa', 'thra', 'osh',
                   'gek', 'ash', 'ir', 'aar', 'ideth', 'ann']),
        'last': (['Daar', 'Kerr', 'Myas', 'Norr', 'Ophin', 'Prex', 'Shes',
                  'Turn', 'Verth', 'Yarj', 'Clethin', 'Fenk'],
                 ['dendrian', 'hylon', 'tar', 'ixi', 'shaus', 'adar', 'uroth',
                  'ath', 'isath', 'erex', 'ionar', 'esh']),
    },
    'Gnome': {
        'first': (['Bim', 'Fon', 'Zib', 'Nack', 'Bod', 'Fizz', 'Jeb', 'Nam',
                   'Ori', 'Wiz', 'Tink', 'Glim', 'Pog', 'Ell'],
                  ['ble', 'kin', 'wick', 'bin', 'nock', 'della', 'doo', 'gen',
                   'pen', 'ver', 'wink', 'zle', 'nab', 'ryn']),
        'last': (['Copper', 'Tinker', 'Cog', 'Fiddle', 'Gadget', 'Whistle',
                  'Button', 'Nimble', 'Pepper', 'Quill'],
                 ['bang', 'spin', 'sprocket', 'gear', 'top', 'wick', 'snap',
                  'fizzle', 'bolt', 'spark']),
    },
    'Half-Orc': {
        'first': (['Gro', 'Thok', 'Kar', 'Mug', 'Ur', 'Sha', 'Dre', 'Hok',
                   'Rok', 'Zug', 'Bru', 'Gna', 'Yev', 'Ovak'],
                  ['mash', 'gar', 'tha', 'nak', 'zek', 'ur', 'gol', 'rag',
                   'ka', 'duk', 'th', 'osh', 'ren', 'ash']),
        'last': (['Skull', 'Iron', 'Blood', 'Stone', 'War', 'Bone', 'Grim',
                  'Ash', 'Thunder', 'Rage'],
                 ['splitter', 'jaw', 'fang', 'crusher', 'render', 'howl',
                  'tusk', 'maul', 'stride', 'born']),
    },
    'Goliath': {
        'first': (['Agh', 'Ea', 'Ila', 'Kav', 'Lo', 'Mano', 'Nau', 'Ork',
                   'Tha', 'Vau', 'Keo', 'Pao'],
                  ['thak', 'gath', 'ki', 'aki', 'lo', 'rai', 'nea', 'anu',
                   'vak', 'moa', 'tha', 'kea']),
        'last': (['Sky', 'Stone', 'Cloud', 'Peak', 'Frost', 'Thunder', 'Bear',
                  'Eagle', 'Rock', 'Gale'],
                 ['watcher', 'carrier', 'climber', 'singer', 'strider', 'born',
                  'caller', 'heart', 'breaker', 'runner']),
    },
    'Tiefling': {
        'first': (['Aka', 'Dam', 'Kai', 'Leu', 'Mal', 'Mor', 'Nem', 'Ori',
                   'Val', 'Xar', 'Zeph', 'Bel'],
                  ['menos', 'akos', 'ros', 'cis', 'thys', 'ari', 'eia', 'on',
                   'ius', 'ira', 'eth', 'izri']),
        'last': (['Hell', 'Night', 'Shadow', 'Flame', 'Dusk', 'Void', 'Star',
                  'Sin', 'Coal', 'Thorn'],
                 ['brand', 'walker', 'horn', 'whisper', 'bane', 'born', 'veil',
                  'mark', 'heart', 'ash']),
    },
}
NAME_PARTS['Orc'] = NAME_PARTS['Half-Orc']

# Tieflings sometimes take a "virtue" name instead of a lineage name.
TIEFLING_VIRTUE_NAMES = [
    'Ambition', 'Candor', 'Ember', 'Fable', 'Havoc', 'Lament', 'Mercy',
    'Penance', 'Quietus', 'Rapture', 'Solace', 'Tempest', 'Valor',
    'Whisper', 'Zeal',
]


def _assemble(parts, rng):
    starts, ends = parts
    return rng.choice(starts) + rng.choice(ends)


def generate_name(race, rng):
    """Race-flavored 'First Last' name. Half-Elves mix elven and human parts;
    unknown races fall back to the human pools."""
    race = (race or '').strip()
    if race == 'Half-Elf':
        first_pool = rng.choice([NAME_PARTS['Elf'], NAME_PARTS['Human']])
        last_pool = rng.choice([NAME_PARTS['Elf'], NAME_PARTS['Human']])
        return f"{_assemble(first_pool['first'], rng)} {_assemble(last_pool['last'], rng)}"
    pools = NAME_PARTS.get(race, NAME_PARTS['Human'])
    if race == 'Tiefling' and rng.random() < 0.4:
        first = rng.choice(TIEFLING_VIRTUE_NAMES)
    else:
        first = _assemble(pools['first'], rng)
    return f"{first} {_assemble(pools['last'], rng)}"


# ── Personality / ideal / bond / flaw (original tables, PHB format) ───────────

TRAIT_TABLES = {
    'Acolyte': {
        'traits': [
            "I quote scripture for every occasion, whether it fits or not.",
            "I see omens in everyday things — spilled salt, a crow's cry.",
            "Nothing shakes my calm; I've sat vigil through worse.",
            "I feel compelled to bless people, even mid-battle.",
            "I keep meticulous records of everything I witness.",
            "I'm fascinated by other faiths and ask endless questions.",
            "I fast on holy days, and I make sure everyone knows it.",
            "I speak to my deity aloud, as if they walk beside me.",
        ],
        'ideals': [
            "Faith. The divine has a plan; I am part of it.",
            "Charity. My hands exist to lift others up.",
            "Tradition. The old rites hold the world together.",
            "Truth. Falsehood is a stain on the soul.",
            "Redemption. No one is beyond saving — not even me.",
            "Duty. The temple's word outweighs my comfort.",
        ],
        'bonds': [
            "The shrine where I was raised must never fall to ruin.",
            "I owe my life to the priest who took me in as a foundling.",
            "A relic of my order was stolen; I will see it returned.",
            "My old congregation still prays for me. I can't fail them.",
            "I carry the ashes of my mentor to scatter in a holy place.",
            "A prophecy names someone like me. I must know if it's true.",
        ],
        'flaws': [
            "I judge nonbelievers more harshly than they deserve.",
            "I am helpless before a request made in my deity's name.",
            "My faith blinds me to obvious deceptions.",
            "I put the letter of doctrine above common sense.",
            "I secretly doubt, and it terrifies me.",
            "I believe suffering is deserved — even my friends'.",
        ],
    },
    'Charlatan': {
        'traits': [
            "I have a new name and backstory for every town.",
            "Flattery falls out of my mouth before I can stop it.",
            "I palm small objects out of habit, not need.",
            "I can't resist upstaging whoever holds the room.",
            "I always look like I belong — that's the whole trick.",
            "I keep a lucky coin that decides my hardest choices.",
            "I laugh loudest at my own jokes and mean it.",
            "I size up everyone I meet for what they want to hear.",
        ],
        'ideals': [
            "Freedom. Chains, contracts, and thrones — all cons.",
            "Cleverness. The sharpest mind in the room should win.",
            "Fairness. I only fleece those who deserve it.",
            "Ambition. One day the con will be big enough to retire on.",
            "Friendship. The crew matters more than the score.",
            "Honesty. One day I'll live a life that needs no mask.",
        ],
        'bonds': [
            "I fleeced the wrong noble and someone else hanged for it.",
            "An old partner knows my real name — and my real crime.",
            "Everything I steal goes to the orphanage that raised me.",
            "I'm chasing the grifter who taught me everything, and took everything.",
            "One mark saw through me and forgave me. I owe them.",
            "My forged papers say I'm nobility. Sometimes I believe it.",
        ],
        'flaws': [
            "I can't resist one more sweetening lie on a done deal.",
            "A pretty face makes me abandon a perfectly good plan.",
            "I run at the first sign the game is up — even from friends.",
            "I've told so many stories I've misplaced the true one.",
            "I gamble away windfalls before sunrise.",
            "Being ordinary frightens me more than being caught.",
        ],
    },
    'Criminal': {
        'traits': [
            "I sit facing the door, always.",
            "I case every room for exits and valuables without thinking.",
            "I speak softly; people lean in, and that's the point.",
            "I never part with my last coin, blade, or secret.",
            "Locks offend me personally.",
            "I'm generous with my crew and cold to everyone else.",
            "I keep my word — in my line, reputation is armor.",
            "Small kindnesses unsettle me more than threats.",
        ],
        'ideals': [
            "Loyalty. You don't sell out your own. Ever.",
            "Freedom. Laws are fences built by the rich.",
            "Discipline. Sloppy thieves are caught thieves.",
            "Mercy. I steal, but nobody bleeds on my jobs.",
            "Ambition. I'll run this city's underworld one day.",
            "Atonement. Every job now pays down an old debt.",
        ],
        'bonds': [
            "I took the fall for someone once. They owe me a life.",
            "My fence is the closest thing I have to family.",
            "There's a guard who let me go once. I never forgot.",
            "My last big score is buried where only I can find it.",
            "Someone I love doesn't know what I do. It must stay that way.",
            "The crew that betrayed me is still out there, spending my share.",
        ],
        'flaws': [
            "Unattended valuables end up in my pockets.",
            "I trust a plan more than I trust people.",
            "When crossed, I answer with interest.",
            "I owe a debt to someone no sane person borrows from.",
            "I assume everyone has an angle, because I do.",
            "Freedom means never staying — even when I should.",
        ],
    },
    'Entertainer': {
        'traits': [
            "Every scar of mine has three versions of its story.",
            "I hum while I work, fight, and sneak. Mostly sneak.",
            "I mimic accents and mannerisms without meaning to.",
            "Applause is my breakfast; silence is my nightmare.",
            "I rehearse dramatic one-liners for likely situations.",
            "I judge every tavern by its acoustics.",
            "I collect songs and stories the way others collect coin.",
            "I perform braver than I feel, until I feel it.",
        ],
        'ideals': [
            "Beauty. A perfect moment on stage outlives an empire.",
            "Joy. The world is dark; I am in the lantern business.",
            "Truth. Art says what the powerful won't allow spoken.",
            "Glory. My name will echo after my voice is gone.",
            "Generosity. Every show is free for those who can't pay.",
            "Craft. Talent is nothing without ten thousand hours.",
        ],
        'bonds': [
            "My instrument was my mother's; it's the only will she left.",
            "A rival stole my best work and grew famous on it.",
            "The troupe that raised me scattered; I'm gathering them back.",
            "I once played for a dying king; his last request drives me.",
            "There's one song I've never finished. It's for someone gone.",
            "A stagehand took a knife meant for me. I perform for two now.",
        ],
        'flaws': [
            "I'd walk into a dragon's mouth for a good audience.",
            "Critics live rent-free in my head; hecklers get worse.",
            "I embellish until the truth files a complaint.",
            "I fall in love with a face in every crowd.",
            "If I'm not the lead, I sulk like a storm cloud.",
            "I spend tomorrow's coin on tonight's spectacle.",
        ],
    },
    'Folk Hero': {
        'traits': [
            "I judge people by their hands, not their rings.",
            "If there's a plow stuck or a cart mired, I'm already pushing.",
            "I'm certain everything will work out — it always has, mostly.",
            "I use big words wrong with total confidence.",
            "Bullies make my knuckles itch.",
            "I blush at every retelling of my deed, then correct the details.",
            "I trust common folk fast and lords slow.",
            "I keep a memento from home in my boot for luck.",
        ],
        'ideals': [
            "Justice. The strong answering for the weak — that's order.",
            "Sincerity. I am exactly what I appear to be.",
            "Courage. Somebody has to go first. Might as well be me.",
            "Home. Everything I do is so they're safe back there.",
            "Change. Yesterday's tyrant proves nothing is permanent.",
            "Humility. The deed mattered; the statue doesn't.",
        ],
        'bonds': [
            "The village that named me a hero still sends me letters.",
            "The tyrant I embarrassed has a long memory and longer reach.",
            "My old plow horse is retired with friends. I visit.",
            "A child in my village wears a wooden sword because of me.",
            "The landlord I defied ruined my family; the ledger isn't settled.",
            "I promised my father I'd come home before harvest. Someday.",
        ],
        'flaws': [
            "I believe my own legend a little too much.",
            "I can't back down once folk are watching.",
            "Tyrants make me reckless when I should be careful.",
            "I secretly fear I got lucky once and never again.",
            "I overcommit to everyone who asks for help.",
            "Cities confuse me and I refuse to admit it.",
        ],
    },
    'Guild Artisan': {
        'traits': [
            "I appraise everything I touch out of pure reflex.",
            "Shoddy workmanship physically pains me.",
            "I talk shop with anyone, anywhere, at length.",
            "A firm handshake and an itemized invoice solve most things.",
            "I sign my work — all my work.",
            "I haggle for sport, then tip generously.",
            "I plan in checklists and mourn in inventory.",
            "I smell of my trade and consider it a credential.",
        ],
        'ideals': [
            "Mastery. The work is the worship.",
            "Community. Guild and town rise together or not at all.",
            "Honesty. My scales are true and so is my word.",
            "Innovation. Tradition is a floor, not a ceiling.",
            "Prosperity. Honest wealth shames no one.",
            "Legacy. My masterpiece will outlive my name.",
        ],
        'bonds': [
            "My workshop burned; I will learn if it was chance or spite.",
            "My apprentice ran off with my designs — and my trust.",
            "The guildhall holds my masterpiece as collateral.",
            "A noble wears my finest work and claims another made it.",
            "My master's dying wish was a commission I haven't finished.",
            "My tools were my grandmother's. They outrank my life.",
        ],
        'flaws': [
            "I undervalue anything I didn't make or vet.",
            "I delay everything in pursuit of perfect.",
            "Coin talks to me a little louder than conscience.",
            "I hold grudges at guild scale — decades, in writing.",
            "I can't watch an amateur work without seizing the tools.",
            "I measure people by their output. Including me. Especially me.",
        ],
    },
    'Hermit': {
        'traits': [
            "I forget others can't hear my inner monologue, so I share it.",
            "Crowds exhaust me; graveyards and libraries do not.",
            "I dispense proverbs like a cracked fountain — steadily.",
            "Long silences feel like conversation to me.",
            "I name plants, birds, and my walking stick.",
            "I eat like a sparrow, then astonish at feasts.",
            "News from ten years ago is 'recent' to me.",
            "I study strangers like texts in a language I half-remember.",
        ],
        'ideals': [
            "Enlightenment. The quiet holds answers the noise drowned.",
            "Balance. Every extreme is a door to ruin.",
            "Purpose. My seclusion prepared me for something. This, maybe.",
            "Compassion. Solitude taught me the weight of one kind word.",
            "Knowledge. I left to learn what no city could teach.",
            "Peace. I will not let the world make me loud again.",
        ],
        'bonds': [
            "My discovery in the wilderness must reach the right hands.",
            "The order that cast me out was wrong, and I can prove it.",
            "Someone visited my hermitage every winter. They stopped coming.",
            "I fled a life I ruined; its debts walked with me.",
            "A beast kept me company for seven years. I buried her on the hill.",
            "The vision that sent me into exile now calls me back out.",
        ],
        'flaws': [
            "I trust my own conclusions over any expert's.",
            "Small talk defeats me utterly.",
            "I judge the comfortable and coddled, aloud.",
            "Secrets fester in me; I hoard them like coin.",
            "I vanish when I'm needed most — old habit.",
            "I mistake isolation for wisdom more than I'd admit.",
        ],
    },
    'Noble': {
        'traits': [
            "My posture is impeccable even while sleeping in mud.",
            "I know everyone's title, lineage, and scandal on sight.",
            "I thank servants by name; it costs nothing and buys loyalty.",
            "Poverty is an adventure to me, which shames me to admit.",
            "I duel with words first and consider it mercy.",
            "I dress for the occasion. All occasions. Including ambushes.",
            "Etiquette is my armor; rudeness genuinely wounds me.",
            "I assume doors, hearts, and treasuries open for me.",
        ],
        'ideals': [
            "Responsibility. Privilege is a debt, paid in service.",
            "Honor. My name will not be cheapened by my deeds.",
            "Noblesse. Those beneath my station are under my shield.",
            "Power. My family climbed; I will not be the rung that breaks.",
            "Merit. Titles should be earned again each generation.",
            "Grace. Whatever happens, one behaves beautifully.",
        ],
        'bonds': [
            "My house's fortunes fell with me; I will restore both.",
            "A common soldier saved me and refused reward. I'll find them.",
            "My signet ring is my claim, my burden, and my target.",
            "My sibling wears the coronet I was promised.",
            "The family estate shelters everyone who ever served us.",
            "I was betrothed to someone I've never met. The date approaches.",
        ],
        'flaws': [
            "I mistake deference for agreement.",
            "An insult to my house outvotes my judgment.",
            "I cannot cook, launder, or barter, and hide it poorly.",
            "I believe rules are for people without my responsibilities.",
            "I keep score of favors like a banker.",
            "Beneath the manners, I need to be needed.",
        ],
    },
    'Outlander': {
        'traits': [
            "I sleep better on stone than on feathers.",
            "I read weather and tracks the way scholars read books.",
            "Walls make my shoulders climb toward my ears.",
            "I share food with strangers; the wild taught me why.",
            "I measure distance in days walked, not miles.",
            "Silence doesn't need filling. Most people disagree.",
            "I collect a stone from every place that almost killed me.",
            "Towns smell wrong to me. All of them.",
        ],
        'ideals': [
            "Endurance. The land doesn't care, so I care enough for both.",
            "Kinship. My tribe is scattered; my loyalty isn't.",
            "The Old Ways. Some knowledge should never be paved over.",
            "Wanderlust. The horizon owes me one more ridge.",
            "Stewardship. Take what's needed, mend what's taken.",
            "Strength. The wild respects nothing else, and it's honest.",
        ],
        'bonds': [
            "My tribe was driven from its land. The land remembers us.",
            "A wolf pack once let me winter among them. I owe a debt of meat.",
            "The trapper who taught me everything vanished on a routine trail.",
            "I am the last who knows my people's songs. They must not die with me.",
            "A city took someone from me. I'm here to take them back.",
            "The mountain I was born under is sacred; miners disagree.",
        ],
        'flaws': [
            "I solve indoor problems with outdoor methods.",
            "Courtesy strikes me as elaborate lying.",
            "I trust animals' judgment of people over my own.",
            "I hold the civilized responsible for civilization.",
            "I'd rather walk three days than ask directions once.",
            "Old grudges keep me warmer than fires.",
        ],
    },
    'Sage': {
        'traits': [
            "I answer questions nobody asked, thoroughly.",
            "I've read about this exact situation. It went badly.",
            "Marginalia is my love language.",
            "I underestimate stairs and overestimate my satchel space.",
            "Being wrong fascinates me — briefly, then it stings.",
            "I alphabetize under stress.",
            "Every debate deserves my finest three-part rebuttal.",
            "I remember book smells better than faces.",
        ],
        'ideals': [
            "Knowledge. Ignorance is the only true monster.",
            "Accuracy. A fact worth stating is worth verifying.",
            "Access. Truth belongs to everyone, not just the towered few.",
            "Wonder. I study because the universe keeps showing off.",
            "Progress. Every generation should inherit better questions.",
            "Caution. Some doors of knowledge open only one way.",
        ],
        'bonds': [
            "The library that raised me is one fire from oblivion.",
            "My unfinished thesis will vindicate my disgraced mentor.",
            "A colleague stole my research; the plagiarism made them famous.",
            "I deciphered a text no one else believes exists. Yet.",
            "A student of mine went looking for the answer I warned about.",
            "I owe my literacy to a stranger who asked nothing in return.",
        ],
        'flaws': [
            "I choose interesting over safe, reflexively.",
            "Deadlines are aspirational; footnotes are not.",
            "I correct people at funerals.",
            "Field conditions and I remain unreconciled.",
            "I'd trade a friendship for a first edition. I have.",
            "Not knowing gnaws me until nothing else fits in my head.",
        ],
    },
    'Sailor': {
        'traits': [
            "Everything is a knot problem if you're brave enough.",
            "I walk like the ground might pitch, because it might.",
            "My vocabulary peels paint and charms dockworkers.",
            "I read moods like weather — and I batten down early.",
            "Any song becomes a shanty if I believe hard enough.",
            "I never whistle aboard anything. You don't tempt the wind.",
            "Dry land is a nice place to visit.",
            "I've eaten worse. That's not a boast; it's a diagnosis.",
        ],
        'ideals': [
            "Crew. The ship survives because nobody works alone.",
            "The Sea. She owes us nothing and gives everything. Respect her.",
            "Liberty. Past the breakwater, no king's writ runs.",
            "Courage. Storms end. Cowardice lingers.",
            "Fair Shares. Every hand pulled the rope; every hand gets paid.",
            "Home Port. Somewhere a light burns for me. I steer by it.",
        ],
        'bonds': [
            "My old captain went down with the ship. I didn't. That's the debt.",
            "There's a harpoon scar on my leg and a name I curse for it.",
            "My first ship still sails under a thief's flag. She's mine.",
            "A tavern keeper in a far port holds my sea chest and my secrets.",
            "I swore an oath to a drowning man I couldn't save.",
            "The navigator who taught me the stars is losing her sight.",
        ],
        'flaws': [
            "Port pay and port taverns have an arrangement about my coin.",
            "I take dares as binding contracts.",
            "Authority sounds like a challenge in the right accent.",
            "I'm superstitious to the point of tactical decisions.",
            "I pick fights when the horizon stays still too long.",
            "I promise a lot at sea that I forget ashore.",
        ],
    },
    'Soldier': {
        'traits': [
            "I wake at dawn without meaning to, boots already half on.",
            "I eat fast, sleep light, and sit where I can see the door.",
            "Give me a plan and I'm calm; give me chaos and I'll make a plan.",
            "I maintain my gear like lives depend on it. They have.",
            "Dark humor got my unit through. Civilians find it alarming.",
            "I bark orders in emergencies. Sorry. No I'm not.",
            "I size up everyone as friendly, hostile, or slow.",
            "Loud noises don't startle me. Quiet ones do.",
        ],
        'ideals': [
            "Duty. The mission first; my feelings filed for later.",
            "Comrades. Flags fade. The people beside me don't.",
            "Peace. I fought so someone else won't have to.",
            "Order. Discipline is the wall between us and the wolves.",
            "Honor. There are orders a soldier must refuse.",
            "Survival. Wars end. Plan to be there when they do.",
        ],
        'bonds': [
            "Half my unit didn't come home. I carry all their names.",
            "My old sergeant runs a farm now. I still send a cut of my pay.",
            "The battle I'm famous for is the one I'd give anything to undo.",
            "An enemy soldier spared me once; we've met three times since.",
            "My discharge papers say honorable; the truth is complicated.",
            "There's a war orphan who thinks I'm a hero. I'm trying to be.",
        ],
        'flaws': [
            "I follow strong leaders past the point of sense.",
            "Peace feels like a trap about to spring.",
            "I drink to make the quiet nights shorter.",
            "I treat every disagreement as a chain-of-command problem.",
            "The enemy's face changed, but I still see the old one.",
            "I volunteer for the dangerous job before anyone can vote.",
        ],
    },
    'Urchin': {
        'traits': [
            "I eat like the plate might be taken, and I pocket the bread.",
            "I know every city's rooftops before I know its streets.",
            "Small spaces feel safe; grand halls feel like traps.",
            "I befriend strays — animal and otherwise — on sight.",
            "I sleep in shifts even when nobody's after me.",
            "Kindness makes me suspicious; a fair price makes me flinch.",
            "I've got a stash within a day of everywhere I've lived.",
            "Rich smells — bread, soap, rain on clean stone — stop me cold.",
        ],
        'ideals': [
            "Survival. Every dawn I see is a victory lap.",
            "Loyalty. The gutter taught me who shares splits the cold.",
            "Defiance. They stepped over me. Now they'll look up at me.",
            "Kindness. One person fed me once. I'm still paying it forward.",
            "Freedom. Nobody owns my feet. Nobody ever will.",
            "Proof. I'll show them a rat can outrun bloodhounds.",
        ],
        'bonds': [
            "The gang of kids I ran with — I'm getting every one of them out.",
            "A baker left day-old loaves on the sill. I guard that shop still.",
            "The watchman who broke my hand walks free with a pension.",
            "Someone sold me once. I bought myself back. The receipt is a scar.",
            "There's a kid working my old corner. Not for long.",
            "I keep the button of a coat someone wrapped around me in a blizzard.",
        ],
        'flaws': [
            "I hoard food, coin, and exits.",
            "I bolt first and apologize by letter.",
            "Charity offends me even when I need it.",
            "I steal from the rich reflexively — mid-conversation, even.",
            "Trust takes me years; betrayal takes me seconds.",
            "I pick at old wounds to stay angry. Anger is warm.",
        ],
    },
}

BACKGROUNDS = list(TRAIT_TABLES.keys())

GENERIC_TRAITS = TRAIT_TABLES['Folk Hero']   # fallback for unknown backgrounds


def generate_traits(background, rng, tables=None):
    """Two personality traits, one ideal, one bond, one flaw.

    `tables` overrides the fantasy tables (used by genre packs; same shape)."""
    table = (tables or TRAIT_TABLES).get(background, GENERIC_TRAITS)
    return {
        'personality': rng.sample(table['traits'], 2),
        'ideal': rng.choice(table['ideals']),
        'bond': rng.choice(table['bonds']),
        'flaw': rng.choice(table['flaws']),
    }


def format_traits_note(traits):
    return (
        "Personality: " + " ".join(traits['personality']) + "\n"
        "Ideal: " + traits['ideal'] + "\n"
        "Bond: " + traits['bond'] + "\n"
        "Flaw: " + traits['flaw']
    )


# ── Full character assembly (needs app context for the library tables) ────────

def generate_character(min_level=1, max_level=20, rng=None, genre='fantasy'):
    from models.ttrpg import (
        tblClassesLibrary, tblClassLevelsLibrary, tblRacesLibrary,
        tblSubclassesLibrary,
    )
    from genre_packs import get_pack, generate_genre_name, genre_display
    rng = rng or random.Random()

    min_level = max(1, min(20, int(min_level)))
    max_level = max(min_level, min(20, int(max_level)))
    level = rng.randint(min_level, max_level)

    classes = tblClassesLibrary.query.all()
    races = tblRacesLibrary.query.all()
    cls = rng.choice(classes) if classes else None
    race = rng.choice(races) if races else None
    class_name = cls.name if cls else 'Fighter'
    race_name = race.name if race else 'Human'
    hit_die = (cls.hit_die if cls else None) or 8

    pack = get_pack(genre)
    if pack:
        background = rng.choice(list(pack['backgrounds']))
    else:
        genre = 'fantasy'
        background = rng.choice(BACKGROUNDS)

    # Stats: roll, assign to class priorities, racial bonuses, then ASIs.
    stats = assign_stats(roll_stat_set(rng), class_name, rng)
    stats = apply_racial_bonuses(stats, race.ability_bonuses if race else '')

    asi_rows = tblClassLevelsLibrary.query.filter(
        tblClassLevelsLibrary.class_name == class_name,
        tblClassLevelsLibrary.level <= level,
        tblClassLevelsLibrary.features_text.like('%Ability Score Improvement%'),
    ).count()
    stats = apply_asis(stats, class_name, asi_rows)

    level_row = tblClassLevelsLibrary.query.filter_by(
        class_name=class_name, level=level).first()
    prof = (level_row.prof_bonus if level_row and level_row.prof_bonus
            else prof_bonus_for(level))

    subclass = ''
    if level >= 3:
        subs = tblSubclassesLibrary.query.filter_by(class_name=class_name).all()
        if subs:
            subclass = rng.choice(subs).name

    con_mod, dex_mod, wis_mod = mod(stats['con']), mod(stats['dex']), mod(stats['wis'])
    ac = 10 + dex_mod
    if class_name == 'Barbarian':
        ac += con_mod            # Unarmored Defense
    elif class_name == 'Monk':
        ac += wis_mod            # Unarmored Defense

    traits = generate_traits(background, rng,
                             tables=pack['backgrounds'] if pack else None)
    name = (generate_genre_name(genre, level, rng) if pack
            else generate_name(race_name, rng))
    archetype, species = genre_display(genre, class_name, race_name)

    return {
        'name': name,
        'genre': genre,
        'archetype': archetype,
        'species': species,
        'char_class': class_name,
        'subclass': subclass,
        'race': race_name,
        'level': level,
        'background': background,
        'str_val': stats['str'], 'dex_val': stats['dex'], 'con_val': stats['con'],
        'int_val': stats['int'], 'wis_val': stats['wis'], 'cha_val': stats['cha'],
        'hp_max': hp_for(level, hit_die, con_mod),
        'ac': ac,
        'speed': (race.speed if race and race.speed else 30),
        'initiative_bonus': dex_mod,
        'passive_perception': 10 + wis_mod,
        'prof_bonus': prof,
        'gold': rng.randint(2, 8) * 10 + (level - 1) * rng.randint(25, 75),
        'silver': rng.randint(0, 9),
        'copper': rng.randint(0, 9),
        'traits': traits,
        'traits_note': format_traits_note(traits),
    }

from extensions import db
from datetime import datetime


class tblCharacters(db.Model):
    __tablename__ = 'tblCharacters'

    character_id   = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('tblUsers.user_id'), nullable=False)
    name           = db.Column(db.Text, nullable=False)
    char_class     = db.Column(db.Text, default='')
    race           = db.Column(db.Text, default='')
    level          = db.Column(db.Integer, default=1)
    background     = db.Column(db.Text, default='')
    portrait_path  = db.Column(db.Text, default='')

    # Core stats stored as columns for fast access
    hp_current     = db.Column(db.Integer, default=0)
    hp_max         = db.Column(db.Integer, default=0)
    ac             = db.Column(db.Integer, default=10)
    str_val        = db.Column(db.Integer, default=10)
    dex_val        = db.Column(db.Integer, default=10)
    con_val        = db.Column(db.Integer, default=10)
    int_val        = db.Column(db.Integer, default=10)
    wis_val        = db.Column(db.Integer, default=10)
    cha_val        = db.Column(db.Integer, default=10)
    speed          = db.Column(db.Integer, default=30)
    initiative_bonus = db.Column(db.Integer, default=0)
    passive_perception = db.Column(db.Integer, default=10)
    gold           = db.Column(db.Integer, default=0)
    silver         = db.Column(db.Integer, default=0)
    copper         = db.Column(db.Integer, default=0)

    active         = db.Column(db.Integer, default=1)
    created_at     = db.Column(db.Text, nullable=False)

    # Relationships
    resources   = db.relationship('tblCharacterResources',   backref='character', cascade='all, delete-orphan', lazy=True)
    conditions  = db.relationship('tblCharacterConditions',  backref='character', cascade='all, delete-orphan', lazy=True)
    inventory   = db.relationship('tblCharacterInventory',   backref='character', cascade='all, delete-orphan', lazy=True)
    skills      = db.relationship('tblCharacterSkills',      backref='character', cascade='all, delete-orphan', lazy=True)
    notes       = db.relationship('tblCharacterNotes',       backref='character', cascade='all, delete-orphan', lazy=True)
    feats       = db.relationship('tblCharacterFeats',       backref='character', cascade='all, delete-orphan', lazy=True)
    armor       = db.relationship('tblCharacterArmor',       backref='character', cascade='all, delete-orphan', lazy=True)
    weapons     = db.relationship('tblCharacterWeapons',     backref='character', cascade='all, delete-orphan', lazy=True)
    spells      = db.relationship('tblCharacterSpells',      backref='character', cascade='all, delete-orphan', lazy=True)
    user        = db.relationship('tblUsers', backref='characters', lazy=True)

    def modifier(self, score):
        return (score - 10) // 2

    def hp_pct(self):
        if self.hp_max == 0:
            return 0
        return max(0, min(100, int(self.hp_current / self.hp_max * 100)))

    def to_dict(self):
        return {
            'character_id': self.character_id,
            'name': self.name,
            'char_class': self.char_class,
            'race': self.race,
            'level': self.level,
            'hp_current': self.hp_current,
            'hp_max': self.hp_max,
            'ac': self.ac,
        }


class tblCharacterResources(db.Model):
    __tablename__ = 'tblCharacterResources'

    resource_id   = db.Column(db.Integer, primary_key=True)
    character_id  = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    resource_name = db.Column(db.Text, nullable=False)
    current_val   = db.Column(db.Integer, default=0)
    max_val       = db.Column(db.Integer, default=0)
    order_by      = db.Column(db.Integer, default=0)


class tblCharacterConditions(db.Model):
    __tablename__ = 'tblCharacterConditions'

    condition_id  = db.Column(db.Integer, primary_key=True)
    character_id  = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    condition_name = db.Column(db.Text, nullable=False)
    notes         = db.Column(db.Text, default='')
    created_at    = db.Column(db.Text, nullable=False)


class tblCharacterInventory(db.Model):
    __tablename__ = 'tblCharacterInventory'

    item_id      = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    item_name    = db.Column(db.Text, nullable=False)
    quantity     = db.Column(db.Integer, default=1)
    weight       = db.Column(db.Text, default='')
    notes        = db.Column(db.Text, default='')
    equipped     = db.Column(db.Integer, default=0)
    order_by     = db.Column(db.Integer, default=0)


class tblCharacterSkills(db.Model):
    __tablename__ = 'tblCharacterSkills'

    skill_id     = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    skill_name   = db.Column(db.Text, nullable=False)
    bonus        = db.Column(db.Integer, default=0)
    proficient   = db.Column(db.Integer, default=0)
    order_by     = db.Column(db.Integer, default=0)


class tblCharacterNotes(db.Model):
    __tablename__ = 'tblCharacterNotes'

    note_id      = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    note_text    = db.Column(db.Text, nullable=False)
    created_at   = db.Column(db.Text, nullable=False)


class tblCharacterFeats(db.Model):
    __tablename__ = 'tblCharacterFeats'

    feat_id      = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    feat_name    = db.Column(db.Text, nullable=False)
    description  = db.Column(db.Text, default='')
    order_by     = db.Column(db.Integer, default=0)


class tblSessions(db.Model):
    __tablename__ = 'tblSessions'

    session_id     = db.Column(db.Integer, primary_key=True)
    title          = db.Column(db.Text, nullable=False)
    session_number = db.Column(db.Integer, default=1)
    campaign_id    = db.Column(db.Integer, db.ForeignKey('tblcampaigns.campaign_id'), nullable=True)
    status         = db.Column(db.Text, default='planning')  # planning | active | ended
    dm_notes       = db.Column(db.Text, default='')
    session_date   = db.Column(db.Text, default='')
    created_at     = db.Column(db.Text, nullable=False)

    campaign = db.relationship('tblcampaigns', backref='ttrpg_sessions', lazy=True)


class tblSessionParty(db.Model):
    __tablename__ = 'tblSessionParty'

    sp_id        = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey('tblSessions.session_id'), nullable=False)
    character_id = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    is_active    = db.Column(db.Integer, default=1)
    joined_at    = db.Column(db.Text, nullable=False)

    character = db.relationship('tblCharacters', backref='session_entries', lazy=True)
    session   = db.relationship('tblSessions',   backref='party',          lazy=True)


class tblMonsterTemplates(db.Model):
    __tablename__ = 'tblMonsterTemplates'

    template_id   = db.Column(db.Integer, primary_key=True)
    api_index     = db.Column(db.Text, unique=True, nullable=True)  # null for homebrew
    name          = db.Column(db.Text, nullable=False)
    cr            = db.Column(db.Text, default='0')       # stored as text to handle '1/2', '1/4'
    monster_type  = db.Column(db.Text, default='')        # beast, undead, humanoid…
    size          = db.Column(db.Text, default='')
    hp_max        = db.Column(db.Integer, default=0)
    ac            = db.Column(db.Integer, default=10)
    source        = db.Column(db.Text, default='srd')     # 'srd' or 'homebrew'
    stats_json    = db.Column(db.Text, default='{}')      # full API response or custom stats
    created_at    = db.Column(db.Text, nullable=False)

    instances = db.relationship('tblSessionMonsters', backref='template', lazy=True)


class tblSessionMonsters(db.Model):
    __tablename__ = 'tblSessionMonsters'

    monster_id    = db.Column(db.Integer, primary_key=True)
    session_id    = db.Column(db.Integer, db.ForeignKey('tblSessions.session_id'), nullable=False)
    template_id   = db.Column(db.Integer, db.ForeignKey('tblMonsterTemplates.template_id'), nullable=False)
    display_name  = db.Column(db.Text, nullable=False)    # e.g. "Goblin 2"
    hp_current    = db.Column(db.Integer, default=0)
    hp_max        = db.Column(db.Integer, default=0)
    ac            = db.Column(db.Integer, default=10)
    initiative    = db.Column(db.Integer, default=0)
    conditions    = db.Column(db.Text, default='[]')      # JSON list of condition strings
    is_alive      = db.Column(db.Integer, default=1)
    sort_order    = db.Column(db.Integer, default=0)

    session = db.relationship('tblSessions', backref='monsters', lazy=True)

    def hp_pct(self):
        if self.hp_max == 0:
            return 0
        return max(0, min(100, int(self.hp_current / self.hp_max * 100)))


class tblDnDAPIConfig(db.Model):
    __tablename__ = 'tblDnDAPIConfig'
    config_id  = db.Column(db.Integer, primary_key=True)
    key        = db.Column(db.Text, unique=True, nullable=False)
    value      = db.Column(db.Text, default='')
    updated_at = db.Column(db.Text, nullable=False)


class tblFeatsLibrary(db.Model):
    __tablename__ = 'tblFeatsLibrary'

    feat_lib_id   = db.Column(db.Integer, primary_key=True)
    api_index     = db.Column(db.Text, unique=True, nullable=True)
    name          = db.Column(db.Text, nullable=False)
    prerequisites = db.Column(db.Text, default='')
    description   = db.Column(db.Text, default='')
    source        = db.Column(db.Text, default='srd')
    created_at    = db.Column(db.Text, nullable=False)


class tblWeaponsLibrary(db.Model):
    __tablename__ = 'tblWeaponsLibrary'

    weapon_lib_id          = db.Column(db.Integer, primary_key=True)
    api_index              = db.Column(db.Text, unique=True, nullable=True)
    name                   = db.Column(db.Text, nullable=False)
    weapon_category        = db.Column(db.Text, default='')
    weapon_range           = db.Column(db.Text, default='')
    damage_dice            = db.Column(db.Text, default='')
    damage_type            = db.Column(db.Text, default='')
    two_handed_damage_dice = db.Column(db.Text, default='')
    two_handed_damage_type = db.Column(db.Text, default='')
    range_normal           = db.Column(db.Integer, default=0)
    range_long             = db.Column(db.Integer, default=0)
    weight                 = db.Column(db.Float, default=0)
    cost                   = db.Column(db.Text, default='')
    properties             = db.Column(db.Text, default='')
    mastery                = db.Column(db.Text, default='')
    notes                  = db.Column(db.Text, default='')
    image_url              = db.Column(db.Text, default='')
    source                 = db.Column(db.Text, default='srd')
    created_at             = db.Column(db.Text, nullable=False)


class tblCharacterWeapons(db.Model):
    __tablename__ = 'tblCharacterWeapons'

    char_weapon_id         = db.Column(db.Integer, primary_key=True)
    character_id           = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    weapon_lib_id          = db.Column(db.Integer, db.ForeignKey('tblWeaponsLibrary.weapon_lib_id'), nullable=True)
    weapon_name            = db.Column(db.Text, nullable=False)
    weapon_category        = db.Column(db.Text, default='')   # Simple / Martial / Magic
    weapon_range           = db.Column(db.Text, default='')   # Melee / Ranged
    damage_dice            = db.Column(db.Text, default='')
    damage_type            = db.Column(db.Text, default='')
    two_handed_damage_dice = db.Column(db.Text, default='')
    two_handed_damage_type = db.Column(db.Text, default='')
    range_normal           = db.Column(db.Integer, default=0)
    range_long             = db.Column(db.Integer, default=0)
    attack_bonus           = db.Column(db.Integer, default=0)  # magical +X to attack
    damage_bonus           = db.Column(db.Integer, default=0)  # magical +X to damage
    properties             = db.Column(db.Text, default='')
    equipped               = db.Column(db.Integer, default=0)  # 1 = carried / ready
    notes                  = db.Column(db.Text, default='')
    order_by               = db.Column(db.Integer, default=0)


class tblCharacterArmor(db.Model):
    __tablename__ = 'tblCharacterArmor'

    char_armor_id    = db.Column(db.Integer, primary_key=True)
    character_id     = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    armor_lib_id     = db.Column(db.Integer, db.ForeignKey('tblArmorLibrary.armor_lib_id'), nullable=True)
    armor_name       = db.Column(db.Text, nullable=False)
    armor_category   = db.Column(db.Text, default='')   # Light / Medium / Heavy / Shield
    armor_class_base = db.Column(db.Integer, default=0)
    dex_bonus        = db.Column(db.Integer, default=0) # 1 = adds DEX mod
    max_dex_bonus    = db.Column(db.Integer, nullable=True)  # NULL=unlimited, 0=none
    ac_bonus         = db.Column(db.Integer, default=0) # magical +X enchantment
    equipped         = db.Column(db.Integer, default=0) # 1 = worn
    notes            = db.Column(db.Text, default='')
    order_by         = db.Column(db.Integer, default=0)


class tblArmorLibrary(db.Model):
    __tablename__ = 'tblArmorLibrary'

    armor_lib_id        = db.Column(db.Integer, primary_key=True)
    api_index           = db.Column(db.Text, unique=True, nullable=True)
    name                = db.Column(db.Text, nullable=False)
    armor_category      = db.Column(db.Text, default='')   # Light / Medium / Heavy / Shield
    armor_class_base    = db.Column(db.Integer, default=0) # AC value (e.g. 11) or bonus (+2 for shield)
    dex_bonus           = db.Column(db.Integer, default=0) # 1 = adds DEX mod
    max_dex_bonus       = db.Column(db.Integer, nullable=True)  # NULL=unlimited, 0=none, 2=medium cap
    str_minimum         = db.Column(db.Integer, default=0)
    stealth_disadvantage = db.Column(db.Integer, default=0)     # 1 = disadvantage on stealth
    weight              = db.Column(db.Float, default=0)
    cost                = db.Column(db.Text, default='')
    properties          = db.Column(db.Text, default='')
    notes               = db.Column(db.Text, default='')
    image_url           = db.Column(db.Text, default='')
    source              = db.Column(db.Text, default='srd')     # srd / homebrew
    created_at          = db.Column(db.Text, nullable=False)


class tblBattleMaps(db.Model):
    __tablename__ = 'tblBattleMaps'

    map_id     = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('tblSessions.session_id'), nullable=False)
    name       = db.Column(db.Text, nullable=False)
    grid_cols  = db.Column(db.Integer, default=20)
    grid_rows  = db.Column(db.Integer, default=20)
    bg_image   = db.Column(db.Text, default='')   # filename under static/uploads/battlemaps/
    is_active  = db.Column(db.Integer, default=0)  # 1 = currently shown map for this session
    movement_scale = db.Column(db.Float, default=1.0)  # feet = squares × 5 × movement_scale (per-map proportion fix)
    created_at = db.Column(db.Text, nullable=False)

    tokens  = db.relationship('tblBattleMapTokens',  backref='battle_map',
                               cascade='all, delete-orphan', lazy=True)
    effects = db.relationship('tblBattleMapEffects', backref='battle_map',
                               cascade='all, delete-orphan', lazy=True)
    session = db.relationship('tblSessions', backref='battle_maps', lazy=True)


class tblBattleMapEffects(db.Model):
    __tablename__ = 'tblBattleMapEffects'

    effect_id    = db.Column(db.Integer, primary_key=True)
    map_id       = db.Column(db.Integer, db.ForeignKey('tblBattleMaps.map_id'), nullable=False)
    shape        = db.Column(db.Text, default='circle')   # circle | cone | line | square
    label        = db.Column(db.Text, default='')
    anchor_x     = db.Column(db.Float, default=0.0)       # fractional col (0.5 = cell centre)
    anchor_y     = db.Column(db.Float, default=0.0)       # fractional row
    size_ft      = db.Column(db.Integer, default=20)      # radius/length in D&D feet
    angle        = db.Column(db.Float, default=0.0)       # degrees — direction for cone/line
    fill_color   = db.Column(db.Text, default='#ff4400')
    fill_opacity = db.Column(db.Float, default=0.35)
    border_color = db.Column(db.Text, default='#ff8800')
    created_at   = db.Column(db.Text, nullable=False)


class tblBattleMapTokens(db.Model):
    __tablename__ = 'tblBattleMapTokens'

    token_id    = db.Column(db.Integer, primary_key=True)
    map_id      = db.Column(db.Integer, db.ForeignKey('tblBattleMaps.map_id'), nullable=False)
    entity_type = db.Column(db.Text, default='monster')  # 'player' | 'monster'
    entity_id   = db.Column(db.Integer, nullable=False)   # character_id or session monster_id
    col         = db.Column(db.Integer, default=0)
    row         = db.Column(db.Integer, default=0)
    updated_at  = db.Column(db.Text, nullable=False)


class tblSpellsLibrary(db.Model):
    __tablename__ = 'tblSpellsLibrary'
    spell_lib_id  = db.Column(db.Integer, primary_key=True)
    api_index     = db.Column(db.Text, unique=True, nullable=True)
    name          = db.Column(db.Text, nullable=False)
    level         = db.Column(db.Integer, default=0)      # 0=cantrip, 1-9
    school        = db.Column(db.Text, default='')
    casting_time  = db.Column(db.Text, default='')
    range_text    = db.Column(db.Text, default='')
    components    = db.Column(db.Text, default='')        # "V, S, M (a bit of bat fur)"
    duration      = db.Column(db.Text, default='')
    concentration = db.Column(db.Integer, default=0)
    ritual        = db.Column(db.Integer, default=0)
    description   = db.Column(db.Text, default='')
    classes_text  = db.Column(db.Text, default='')        # comma-separated class names
    damage_dice   = db.Column(db.Text, default='')        # parsed from description, e.g. "8d6"
    damage_type   = db.Column(db.Text, default='')        # e.g. "fire" (best-effort)
    source        = db.Column(db.Text, default='srd')
    created_at    = db.Column(db.Text, nullable=False)


class tblSkillsLibrary(db.Model):
    __tablename__ = 'tblSkillsLibrary'
    skill_lib_id  = db.Column(db.Integer, primary_key=True)
    api_index     = db.Column(db.Text, unique=True, nullable=True)
    name          = db.Column(db.Text, nullable=False)
    ability_score = db.Column(db.Text, default='')        # STR, DEX, CON, INT, WIS, CHA
    description   = db.Column(db.Text, default='')
    source        = db.Column(db.Text, default='srd')
    created_at    = db.Column(db.Text, nullable=False)


class tblRacesLibrary(db.Model):
    __tablename__ = 'tblRacesLibrary'
    race_lib_id   = db.Column(db.Integer, primary_key=True)
    api_index     = db.Column(db.Text, unique=True, nullable=True)
    name          = db.Column(db.Text, nullable=False)
    speed         = db.Column(db.Integer, default=30)
    size          = db.Column(db.Text, default='')
    ability_bonuses = db.Column(db.Text, default='')      # e.g. "+2 STR, +1 CON"
    traits_text   = db.Column(db.Text, default='')        # newline-separated trait names
    languages     = db.Column(db.Text, default='')
    description   = db.Column(db.Text, default='')
    source        = db.Column(db.Text, default='srd')
    created_at    = db.Column(db.Text, nullable=False)


class tblCharacterSpells(db.Model):
    __tablename__ = 'tblCharacterSpells'
    char_spell_id = db.Column(db.Integer, primary_key=True)
    character_id  = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    spell_lib_id  = db.Column(db.Integer, db.ForeignKey('tblSpellsLibrary.spell_lib_id'), nullable=True)
    spell_name    = db.Column(db.Text, nullable=False)
    spell_level   = db.Column(db.Integer, default=0)
    school        = db.Column(db.Text, default='')
    prepared      = db.Column(db.Integer, default=0)
    notes         = db.Column(db.Text, default='')
    order_by      = db.Column(db.Integer, default=0)

    lib_spell = db.relationship('tblSpellsLibrary', foreign_keys=[spell_lib_id], lazy=True)


class tblDiceRolls(db.Model):
    __tablename__ = 'tblDiceRolls'
    roll_id      = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, nullable=True)
    char_name    = db.Column(db.Text, default='')
    expression   = db.Column(db.Text, default='')   # e.g. "2d6+3"
    label        = db.Column(db.Text, default='')
    dice_json    = db.Column(db.Text, default='[]') # JSON list of individual die results
    modifier     = db.Column(db.Integer, default=0)
    total        = db.Column(db.Integer, default=0)
    adv_mode     = db.Column(db.Text, default='normal')  # normal | advantage | disadvantage
    rolled_at    = db.Column(db.Text, nullable=False)


class tblEquipmentLibrary(db.Model):
    __tablename__ = 'tblEquipmentLibrary'
    equipment_lib_id = db.Column(db.Integer, primary_key=True)
    api_index        = db.Column(db.Text, unique=True, nullable=True)
    name             = db.Column(db.Text, nullable=False)
    category         = db.Column(db.Text, default='')   # Adventuring Gear, Tool, Mount, etc.
    subcategory      = db.Column(db.Text, default='')   # Standard Gear, Arcane Focus, etc.
    weight           = db.Column(db.Float, default=0)
    cost             = db.Column(db.Text, default='')   # e.g. "5 gp"
    description      = db.Column(db.Text, default='')
    source           = db.Column(db.Text, default='srd')
    created_at       = db.Column(db.Text, nullable=False)


class tblClassesLibrary(db.Model):
    __tablename__ = 'tblClassesLibrary'
    class_lib_id         = db.Column(db.Integer, primary_key=True)
    api_index            = db.Column(db.Text, unique=True, nullable=True)
    name                 = db.Column(db.Text, nullable=False)
    hit_die              = db.Column(db.Integer, default=8)      # 6, 8, 10, or 12
    saving_throws        = db.Column(db.Text, default='')        # "STR, CON"
    proficiencies        = db.Column(db.Text, default='')        # armor/weapon/tool profs
    skill_choices        = db.Column(db.Text, default='')        # "Choose 2 from Acrobatics…"
    subclasses           = db.Column(db.Text, default='')        # "Champion, Battle Master"
    spellcasting_ability = db.Column(db.Text, default='')        # "INT" / "" if non-caster
    description          = db.Column(db.Text, default='')
    source               = db.Column(db.Text, default='srd')
    created_at           = db.Column(db.Text, nullable=False)

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


class tblBattleMaps(db.Model):
    __tablename__ = 'tblBattleMaps'

    map_id     = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('tblSessions.session_id'), nullable=False)
    name       = db.Column(db.Text, nullable=False)
    grid_cols  = db.Column(db.Integer, default=20)
    grid_rows  = db.Column(db.Integer, default=20)
    bg_image   = db.Column(db.Text, default='')   # filename under static/uploads/battlemaps/
    is_active  = db.Column(db.Integer, default=0)  # 1 = currently shown map for this session
    created_at = db.Column(db.Text, nullable=False)

    tokens  = db.relationship('tblBattleMapTokens', backref='battle_map',
                               cascade='all, delete-orphan', lazy=True)
    session = db.relationship('tblSessions', backref='battle_maps', lazy=True)


class tblBattleMapTokens(db.Model):
    __tablename__ = 'tblBattleMapTokens'

    token_id    = db.Column(db.Integer, primary_key=True)
    map_id      = db.Column(db.Integer, db.ForeignKey('tblBattleMaps.map_id'), nullable=False)
    entity_type = db.Column(db.Text, default='monster')  # 'player' | 'monster'
    entity_id   = db.Column(db.Integer, nullable=False)   # character_id or session monster_id
    col         = db.Column(db.Integer, default=0)
    row         = db.Column(db.Integer, default=0)
    updated_at  = db.Column(db.Text, nullable=False)

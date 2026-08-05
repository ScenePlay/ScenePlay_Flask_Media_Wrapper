from extensions import db
from datetime import datetime

# VDO.ninja defaults. Overridable in app settings so a self-hosted instance or
# different browser-source flags need no code change.
VDO_DEFAULTS = {
    'obs_vdo_base':        'https://vdo.ninja/',
    'obs_vdo_view_params': '&cleanoutput&transparent&autostart',
    'obs_vdo_push_params': '&webcam&autostart',
}


ROOM_BITRATE_DEFAULT = 2500        # kbps; vdo.ninja's own usual target
ROOM_BITRATE_MIN, ROOM_BITRATE_MAX = 200, 8000


def _room_videobitrate():
    """Outbound video ceiling for room publishers, in kbps, clamped sane."""
    from sql import appsettingGet
    try:
        v = int(float(appsettingGet('obs_room_videobitrate', '')
                      or ROOM_BITRATE_DEFAULT))
    except (TypeError, ValueError):
        v = ROOM_BITRATE_DEFAULT
    return max(ROOM_BITRATE_MIN, min(v, ROOM_BITRATE_MAX))


def _vdo_url(kind, stream_id):
    """Build a VDO.ninja push/view URL for one stream id.

    The shared table password (obs_vdo_password) rides on BOTH ends: the
    stream id alone is a capability — anyone holding it could watch the feed
    or impersonate the push — so the password is what makes a leaked id
    useless. Players never type it; it is baked into their link."""
    from urllib.parse import quote
    from sql import appsettingGet

    def _setting(name):
        return (appsettingGet(name, '') or '').strip() or VDO_DEFAULTS[name]

    base = _setting('obs_vdo_base')
    if not base.endswith('/'):
        base += '/'
    params = _setting('obs_vdo_view_params' if kind == 'view' else 'obs_vdo_push_params')
    url = f'{base}?{kind}={quote(stream_id, safe="")}{params}'
    # Purely an audio choice: for tables whose player audio already reaches OBS
    # by another route and would otherwise be doubled.
    #
    # NOT an autoplay workaround, despite appearances. Autoplay policy was
    # measured inside OBS's own browser engine and it starts a feed with audio
    # without any gesture; black tiles came from framing the feed in an http
    # page instead (see obs_tile.html). &noaudio was kept because it is a real
    # option, not because it fixes anything. &muted and &mute were also
    # measured and neither mutes view-side playback at all.
    if kind == 'view' and (appsettingGet('obs_feed_noaudio', '0') or '0') == '1' \
            and '&noaudio' not in params:
        url += '&noaudio'
    # The table's vdo.ninja room, on the PUSH end only. Joining the room is
    # what lets the players hear each other and the GM — without it every
    # player is a solo stream that only OBS ever subscribes to, so nobody
    # hears anybody. View URLs stay solo (?view=<id>) on purpose: that is what
    # keeps one tile per player in OBS with its own mixer fader, instead of
    # one source carrying the whole room already mixed together.
    room = (appsettingGet('obs_vdo_room', '') or '').strip()
    if room and '&room=' not in params:
        url += '&room=' + quote(room, safe='')
        if kind == 'view':
            # MEASURED: a publisher inside a room is NOT reachable by stream id
            # alone — ?view=<id> resolves nothing, and the tile just sits black.
            # The room is needed to find them, and &scene is what makes this a
            # one-stream OBS view rather than joining the room as a guest
            # (?view=<id>&room=<room> on its own renders a "Join Room" page).
            url += '&scene'
        else:
            # A room is a P2P mesh: with a full table of ten, every camera
            # would upload video to nine peers AND to OBS's solo view — a load
            # phones and home upload cannot carry, failing exactly at full
            # party size. So by default guests exchange VOICES only:
            #
            # &novideo is viewer-side — this tab stops RECEIVING peers' video
            # but still SENDS its own camera, so OBS keeps every face while
            # each player uploads one video stream instead of ten. Faces reach
            # players through the broadcast anyway.
            #
            # &maxvideobitrate is the sender-side hard ceiling per outbound
            # encode (per docs; &outboundvideobitrate is only a default that
            # viewers may override), so no single link can run away.
            if (appsettingGet('obs_room_audio_only', '1') or '1') == '1':
                url += '&novideo'
            url += f'&maxvideobitrate={_room_videobitrate()}'
    password = (appsettingGet('obs_vdo_password', '') or '').strip()
    if password:
        url += '&password=' + quote(password, safe='')
    return url


class tblCharacters(db.Model):
    __tablename__ = 'tblCharacters'

    character_id   = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('tblUsers.user_id'), nullable=False)
    name           = db.Column(db.Text, nullable=False)
    char_class     = db.Column(db.Text, default='')
    subclass       = db.Column(db.Text, default='')   # archetype, e.g. Champion
    race           = db.Column(db.Text, default='')
    level          = db.Column(db.Integer, default=1)
    background     = db.Column(db.Text, default='')
    genre          = db.Column(db.Text, default='fantasy')  # genre_packs.py key
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

    # OBS / video feed (migration 0007). video_stream_id is generated by
    # ScenePlay so the player never types a URL; video_feed_url is the escape
    # hatch for anyone running their own capture and WINS when set.
    video_stream_id = db.Column(db.Text, default='')
    video_feed_url  = db.Column(db.Text, default='')

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

    def has_feed(self):
        return bool(self.video_feed_url or self.video_stream_id)

    def video_view_url(self):
        """What OBS loads in the browser source. A custom URL wins outright —
        someone using their own capture service gets it untouched."""
        if self.video_feed_url:
            return self.video_feed_url
        if not self.video_stream_id:
            return ''
        return _vdo_url('view', self.video_stream_id)

    def video_push_url(self):
        """What the player opens to start their camera. Empty when they've
        supplied a custom URL — that feed is theirs to start, not ours."""
        if self.video_feed_url or not self.video_stream_id:
            return ''
        return _vdo_url('push', self.video_stream_id)

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
    # LEGACY single-note column: content was migrated into tblSessionNotes
    # rows (0006_session_notes) and nothing writes here anymore.
    dm_notes       = db.Column(db.Text, default='')
    session_date   = db.Column(db.Text, default='')
    created_at     = db.Column(db.Text, nullable=False)

    campaign = db.relationship('tblcampaigns', backref='ttrpg_sessions', lazy=True)
    session_notes = db.relationship('tblSessionNotes', backref='session',
                                    cascade='all, delete-orphan', lazy=True)


class tblSessionNotes(db.Model):
    """DM campaign/prep notes for one session — many rows per session,
    DM-only (session_detail and every endpoint are dm_required)."""
    __tablename__ = 'tblSessionNotes'

    note_id    = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('tblSessions.session_id'), nullable=False)
    title      = db.Column(db.Text, default='')
    body       = db.Column(db.Text, default='')
    sort_order = db.Column(db.Integer, default=0)  # DM-defined order in the notes list
    created_at = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.Text, nullable=False)


class tblSessionParty(db.Model):
    __tablename__ = 'tblSessionParty'

    sp_id        = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey('tblSessions.session_id'), nullable=False)
    character_id = db.Column(db.Integer, db.ForeignKey('tblCharacters.character_id'), nullable=False)
    is_active    = db.Column(db.Integer, default=1)
    joined_at    = db.Column(db.Text, nullable=False)

    character = db.relationship('tblCharacters', backref=db.backref('session_entries', cascade='all, delete-orphan'), lazy=True)
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
    sort_order = db.Column(db.Integer, default=0)  # DM-defined display order in the maps list
    created_at = db.Column(db.Text, nullable=False)

    tokens  = db.relationship('tblBattleMapTokens',  backref='battle_map',
                               cascade='all, delete-orphan', lazy=True)
    effects = db.relationship('tblBattleMapEffects', backref='battle_map',
                               cascade='all, delete-orphan', lazy=True)
    notes   = db.relationship('tblBattleMapNotes',   backref='battle_map',
                               cascade='all, delete-orphan', lazy=True)
    floorplan = db.relationship('tblBattleMapFloorplans', backref='battle_map',
                                cascade='all, delete-orphan', lazy=True, uselist=False)
    doors   = db.relationship('tblBattleMapDoors',   backref='battle_map',
                               cascade='all, delete-orphan', lazy=True)
    prompts = db.relationship('tblBattleMapPrompts', backref='battle_map',
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


class tblBattleMapNotes(db.Model):
    """DM prep/session notes for one battle map. Never sent to players or the
    relay — served only through dm_required endpoints."""
    __tablename__ = 'tblBattleMapNotes'

    note_id    = db.Column(db.Integer, primary_key=True)
    map_id     = db.Column(db.Integer, db.ForeignKey('tblBattleMaps.map_id'), nullable=False)
    title      = db.Column(db.Text, default='')
    body       = db.Column(db.Text, default='')
    sort_order = db.Column(db.Integer, default=0)  # DM-defined order in the notes list
    created_at = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.Text, nullable=False)


class tblBattleMapFloorplans(db.Model):
    """3D wall/door/elevation geometry for one battle map, as validated
    floorplan JSON (see floorplan.py for the schema). Kept out of tblBattleMaps
    so the blob doesn't ride the map row loaded on every 2-second state poll.
    version bumps on every save; clients re-fetch geometry when it changes."""
    __tablename__ = 'tblBattleMapFloorplans'

    floorplan_id = db.Column(db.Integer, primary_key=True)
    map_id       = db.Column(db.Integer, db.ForeignKey('tblBattleMaps.map_id'),
                             nullable=False, unique=True)
    json_data    = db.Column(db.Text, nullable=False)
    version      = db.Column(db.Integer, default=1)
    updated_at   = db.Column(db.Text, nullable=False)


class tblObsSceneMap(db.Model):
    """Which OBS scene belongs to which party member — the DM clicks a player
    and OBS cuts to this scene.

    Rig-local DM config, deliberately NOT columns on tblCharacters: it must be
    wipeable when the DM rebuilds their OBS scene collection without touching
    characters, and it holds non-character rows too (entity_type='special' for
    a group shot or the ScenePlay-webpage scene). The entity_type/entity_id
    shape mirrors tblBattleMapTokens. Scenes are keyed by NAME because that is
    what obs-websocket switches on; a rename in OBS is followed by the
    SceneNameChanged event."""
    __tablename__ = 'tblObsSceneMap'

    obs_map_id   = db.Column(db.Integer, primary_key=True)
    entity_type  = db.Column(db.Text, nullable=False, default='player')  # player|special
    entity_id    = db.Column(db.Integer, nullable=False, default=0)      # character_id; 0 for special
    entity_key   = db.Column(db.Text, default='')     # 'group' | 'battlemap' | ''
    scene_name   = db.Column(db.Text, nullable=False, default='')
    source_name  = db.Column(db.Text, default='')     # browser source ScenePlay created
    auto_created = db.Column(db.Integer, default=0)   # 1 = built by "create scene"
    sort_order   = db.Column(db.Integer, default=0)
    updated_at   = db.Column(db.Text, default='')

    __table_args__ = (db.UniqueConstraint('entity_type', 'entity_id', 'entity_key',
                                          name='uq_obs_map_entity'),)


class tblBattleMapPrompts(db.Model):
    """Last LLM prompt generated for one battle map, per kind ('art' = the
    image/video prompt, 'layout' = the walls-first floorplan design prompt).
    settings_json holds the modal selections that built the prompt so the
    dialog reopens pre-filled. Latest-wins upsert — no history."""
    __tablename__ = 'tblBattleMapPrompts'

    prompt_id     = db.Column(db.Integer, primary_key=True)
    map_id        = db.Column(db.Integer, db.ForeignKey('tblBattleMaps.map_id'),
                              nullable=False)
    kind          = db.Column(db.Text, nullable=False)   # 'art' | 'layout'
    prompt_text   = db.Column(db.Text, nullable=False)
    settings_json = db.Column(db.Text, default='')
    updated_at    = db.Column(db.Text, nullable=False)

    __table_args__ = (db.UniqueConstraint('map_id', 'kind'),)


class tblBattleMapDoors(db.Model):
    """Runtime open/closed state, one row per door in the map's floorplan.
    Separate from json_data so a toggle is a one-row UPDATE and the state poll
    can read door states without parsing the geometry blob."""
    __tablename__ = 'tblBattleMapDoors'

    row_id     = db.Column(db.Integer, primary_key=True)
    map_id     = db.Column(db.Integer, db.ForeignKey('tblBattleMaps.map_id'), nullable=False)
    door_key   = db.Column(db.Text, nullable=False)   # matches doors[].id in json_data
    is_open    = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.Text, nullable=False)

    __table_args__ = (db.UniqueConstraint('map_id', 'door_key'),)


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
    relay_roll_id = db.Column(db.Integer, nullable=True)  # relay's unique roll id, for exact dedup


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


class tblConditionsLibrary(db.Model):
    __tablename__ = 'tblConditionsLibrary'
    condition_lib_id = db.Column(db.Integer, primary_key=True)
    api_index        = db.Column(db.Text, unique=True, nullable=True)
    name             = db.Column(db.Text, nullable=False)
    description      = db.Column(db.Text, default='')     # full SRD rule text
    source           = db.Column(db.Text, default='srd')
    created_at       = db.Column(db.Text, nullable=False)


class tblMagicItemsLibrary(db.Model):
    __tablename__ = 'tblMagicItemsLibrary'
    magic_item_lib_id = db.Column(db.Integer, primary_key=True)
    api_index         = db.Column(db.Text, unique=True, nullable=True)
    name              = db.Column(db.Text, nullable=False)
    category          = db.Column(db.Text, default='')    # Wondrous Items, Ring, Potion…
    rarity            = db.Column(db.Text, default='')    # Common … Legendary, Artifact
    attunement        = db.Column(db.Integer, default=0)  # 1 = requires attunement
    description       = db.Column(db.Text, default='')
    image_url         = db.Column(db.Text, default='')
    source            = db.Column(db.Text, default='srd')
    created_at        = db.Column(db.Text, nullable=False)


class tblFeaturesLibrary(db.Model):
    __tablename__ = 'tblFeaturesLibrary'
    feature_lib_id = db.Column(db.Integer, primary_key=True)
    api_index      = db.Column(db.Text, unique=True, nullable=True)
    name           = db.Column(db.Text, nullable=False)
    class_name     = db.Column(db.Text, default='')       # Barbarian, Wizard…
    subclass_name  = db.Column(db.Text, default='')       # '' for base-class features
    level          = db.Column(db.Integer, default=0)     # level the feature is gained
    prerequisites  = db.Column(db.Text, default='')
    description    = db.Column(db.Text, default='')
    source         = db.Column(db.Text, default='srd')
    created_at     = db.Column(db.Text, nullable=False)


class tblClassLevelsLibrary(db.Model):
    __tablename__ = 'tblClassLevelsLibrary'
    class_level_id  = db.Column(db.Integer, primary_key=True)
    api_index       = db.Column(db.Text, unique=True, nullable=True)  # e.g. "wizard-3"
    class_name      = db.Column(db.Text, nullable=False)
    level           = db.Column(db.Integer, default=1)
    prof_bonus      = db.Column(db.Integer, default=2)
    features_text   = db.Column(db.Text, default='')      # newline-separated feature names
    cantrips_known  = db.Column(db.Integer, default=0)
    spells_known    = db.Column(db.Integer, default=0)    # 0 = prepared caster / non-caster
    spell_slots_json    = db.Column(db.Text, default='{}')  # {"1": 4, "2": 2, …}
    class_specific_json = db.Column(db.Text, default='{}')  # rage_count, ki_points, …
    source          = db.Column(db.Text, default='srd')
    created_at      = db.Column(db.Text, nullable=False)


class tblSubclassesLibrary(db.Model):
    __tablename__ = 'tblSubclassesLibrary'
    subclass_lib_id = db.Column(db.Integer, primary_key=True)
    api_index       = db.Column(db.Text, unique=True, nullable=True)
    name            = db.Column(db.Text, nullable=False)
    class_name      = db.Column(db.Text, default='')
    flavor          = db.Column(db.Text, default='')      # "Martial Archetype", summary line
    description     = db.Column(db.Text, default='')
    source          = db.Column(db.Text, default='srd')
    created_at      = db.Column(db.Text, nullable=False)


class tblTraitsLibrary(db.Model):
    __tablename__ = 'tblTraitsLibrary'
    trait_lib_id = db.Column(db.Integer, primary_key=True)
    api_index    = db.Column(db.Text, unique=True, nullable=True)
    name         = db.Column(db.Text, nullable=False)
    races_text   = db.Column(db.Text, default='')         # races/species that get the trait
    description  = db.Column(db.Text, default='')
    source       = db.Column(db.Text, default='srd')
    created_at   = db.Column(db.Text, nullable=False)


class tblWeaponPropertiesLibrary(db.Model):
    __tablename__ = 'tblWeaponPropertiesLibrary'
    weapon_prop_id = db.Column(db.Integer, primary_key=True)
    api_index      = db.Column(db.Text, unique=True, nullable=True)
    name           = db.Column(db.Text, nullable=False)   # Finesse, Versatile, Reach…
    description    = db.Column(db.Text, default='')
    source         = db.Column(db.Text, default='srd')
    created_at     = db.Column(db.Text, nullable=False)


class tblRulesLibrary(db.Model):
    __tablename__ = 'tblRulesLibrary'
    rule_lib_id = db.Column(db.Integer, primary_key=True)
    api_index   = db.Column(db.Text, unique=True, nullable=True)
    name        = db.Column(db.Text, nullable=False)      # "Grappling", "Ability Checks"…
    parent      = db.Column(db.Text, default='')          # "Combat", "Spellcasting"… ('' = top level)
    description = db.Column(db.Text, default='')          # full SRD rules prose (markdown-ish)
    source      = db.Column(db.Text, default='srd')
    created_at  = db.Column(db.Text, nullable=False)

import os
import re
import uuid
import threading
import requests
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import login_required
from werkzeug.utils import secure_filename
from sqlalchemy import text
from extensions import db
from models.ttrpg import (tblFeatsLibrary, tblWeaponsLibrary, tblArmorLibrary, tblDnDAPIConfig,
                          tblSpellsLibrary, tblSkillsLibrary, tblRacesLibrary, tblEquipmentLibrary,
                          tblClassesLibrary, tblConditionsLibrary, tblMagicItemsLibrary,
                          tblFeaturesLibrary, tblClassLevelsLibrary, tblSubclassesLibrary,
                          tblTraitsLibrary, tblWeaponPropertiesLibrary, tblRulesLibrary)
from routes.auth import dm_required

WEAPON_IMG_FOLDER = os.path.join('static', 'uploads', 'weapons')
ALLOWED_IMG_EXTS  = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


ARMOR_IMG_FOLDER = os.path.join('static', 'uploads', 'armor')


def _save_upload(file_field, subfolder):
    """Save an uploaded image to static/uploads/<subfolder>/; return URL or None."""
    f = request.files.get(file_field)
    if not f or not f.filename:
        return None
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_IMG_EXTS:
        return None
    # Shared Pillow pipeline: downscale to token-art size, opaque->JPEG.
    from routes._util import save_upload_downscaled
    folder = os.path.join(current_app.root_path, 'static', 'uploads', subfolder)
    filename = save_upload_downscaled(f, folder)
    return url_for('static', filename=f'uploads/{subfolder}/{filename}')


def _save_weapon_image(file_field):
    return _save_upload(file_field, 'weapons')


def _save_armor_image(file_field):
    return _save_upload(file_field, 'armor')

reference_bp = Blueprint('reference_bp', __name__, url_prefix='/ttrpg/reference')

_sync_states = {}   # {job_type: {total, done, added, skipped, errors, running, message}}

API_2014 = 'https://www.dnd5eapi.co/api/2014'
API_2024 = 'https://www.dnd5eapi.co/api/2024'
MERGED_API = 'merged'   # sentinel stored in tblDnDAPIConfig — pull 2024 first, fill from 2014

DEFAULT_API_BASE = MERGED_API

API_OPTIONS = {
    MERGED_API: {
        'label':    'Merged — 2024 + 2014 SRD',
        'monsters': '~335',
        'feats':    '~18',
        'weapons':  '~70',
        'note':     'Recommended. Pulls from the 2024 API first and fills everything it '
                    'does not have yet (spells, monsters, rules, subraces…) from 2014.',
    },
    API_2014: {
        'label':    '2014 SRD',
        'monsters': '335',
        'feats':    '1',
        'weapons':  '~67',
        'note':     'Best monster coverage. Limited feats (PHB not open).',
    },
    API_2024: {
        'label':    '2024 (PHB 2024)',
        'monsters': '3',
        'feats':    '17',
        'weapons':  '38',
        'note':     'More feats available, but still incomplete: no spells, monsters, '
                    'rules or per-level class tables yet.',
    },
}


from routes._util import _now  # shared timestamp format (relay sync compares these strings)


_SPELL_DAMAGE_TYPES = ('acid', 'bludgeoning', 'cold', 'fire', 'force', 'lightning',
                       'necrotic', 'piercing', 'poison', 'psychic', 'radiant',
                       'slashing', 'thunder')


def parse_spell_damage(description):
    """Best-effort extraction of a spell's base damage from its description.

    Returns (damage_dice, damage_type), e.g. ("8d6", "fire"). Grabs the FIRST
    'NdM' found and the nearest damage-type word after it. Approximate: misses
    upcast scaling / save-for-half and may pick the wrong dice for complex
    spells — a DM can correct individual entries later."""
    if not description:
        return '', ''
    m = re.search(r'(\d+)\s*d\s*(\d+)', description)
    if not m:
        return '', ''
    dice = f'{m.group(1)}d{m.group(2)}'
    tail = description[m.end():m.end() + 40].lower()
    dtype = next((t for t in _SPELL_DAMAGE_TYPES if t in tail), '')
    return dice, dtype


def get_api_base():
    s = tblDnDAPIConfig.query.filter_by(key='dnd_api_base').first()
    return s.value if s else DEFAULT_API_BASE


def _api_version(api_base):
    return '2024' if '2024' in api_base else '2014'


# ── Merged-API fetch layer ─────────────────────────────────────────────────────
# The 2024 API is still being built out (no spells, monsters, rules, subraces,
# per-class level tables…). In merged mode every sync reads BOTH versions:
# 2024 wins where an index exists in both, 2014 fills the gaps. Each entry
# remembers which base it came from so detail fetches and version-specific
# parsing use the right API.

# 2024 renamed some resources; alias per version so 'races' works everywhere.
_RESOURCE_ALIASES = {
    '2024': {'races': 'species', 'subraces': 'subspecies'},
}


def api_sources():
    """API bases to sync from, in priority order (first listing an index wins)."""
    base = get_api_base()
    if base == MERGED_API:
        return [API_2024, API_2014]
    return [base]


def _resource_path(api_base, resource):
    return _RESOURCE_ALIASES.get(_api_version(api_base), {}).get(resource, resource)


def merged_resource_list(resource, list_key='results'):
    """Fetch a resource index from every api_source and merge by 'index'.

    Returns ([(entry, api_base), …], error). A base that lacks the endpoint
    (404 / network error) simply contributes nothing; `error` is set only when
    EVERY source failed, mirroring the old single-base failure behaviour."""
    seen, out, errs = set(), [], []
    ok = False
    for base in api_sources():
        try:
            resp = requests.get(f'{base}/{_resource_path(base, resource)}', timeout=15)
            resp.raise_for_status()
            results = resp.json().get(list_key, [])
            ok = True
        except Exception as e:
            errs.append(f'{_api_version(base)}: {e}')
            continue
        for entry in results:
            idx = entry.get('index')
            if idx and idx not in seen:
                seen.add(idx)
                out.append((entry, base))
    if not ok:
        return [], '; '.join(errs) or 'no API sources responded'
    return out, None


def merged_category_list(category_by_version):
    """Like merged_resource_list but for /equipment-categories/<cat> lists
    (weapons/armor), whose category slug differs per version.
    `category_by_version` maps version -> slug, e.g. {'2014': 'weapon', '2024': 'weapons'}."""
    seen, out, errs = set(), [], []
    ok = False
    for base in api_sources():
        cat = category_by_version.get(_api_version(base))
        if not cat:
            continue
        try:
            resp = requests.get(f'{base}/equipment-categories/{cat}', timeout=15)
            resp.raise_for_status()
            results = resp.json().get('equipment', [])
            ok = True
        except Exception as e:
            errs.append(f'{_api_version(base)}: {e}')
            continue
        for entry in results:
            idx = entry.get('index')
            if idx and idx not in seen:
                seen.add(idx)
                out.append((entry, base))
    if not ok:
        return [], '; '.join(errs) or 'no API sources responded'
    return out, None


def _desc_text(data):
    """Long-form text across API versions: 2014 uses desc (list of paragraphs,
    or a plain string for rule-sections), 2024 uses description (string)."""
    d = data.get('desc')
    if isinstance(d, list):
        return '\n'.join(d)
    if isinstance(d, str):
        return d
    return data.get('description', '') or ''


def _feature_level(data):
    """Feature level across versions: 2014 is an int; 2024 is a ref dict whose
    index ends in the level number (e.g. 'barbarian-4' or 'barbarian-4-nyi')."""
    lvl = data.get('level')
    if isinstance(lvl, int):
        return lvl
    if isinstance(lvl, dict):
        for part in reversed((lvl.get('index') or '').split('-')):
            if part.isdigit():
                return int(part)
    return 0


# ── Feats sync ─────────────────────────────────────────────────────────────────

def sync_feats_from_api(state=None):
    feat_list, err = merged_resource_list('feats')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(feat_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(feat_list):
        version = _api_version(api_base)
        try:
            index = entry['index']
            if tblFeatsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            try:
                detail = requests.get(f'{api_base}/feats/{index}', timeout=10)
                detail.raise_for_status()
                data = detail.json()

                if version == '2024':
                    description = data.get('description', '')
                    feat_type = data.get('type', '')
                    prerequisites = f'Type: {feat_type.replace("-", " ").title()}' if feat_type else ''
                else:
                    description = '\n'.join(data.get('desc', []))
                    prerequisites = ', '.join(
                        f"{p['ability_score']['name']} {p['minimum_score']}+"
                        for p in data.get('prerequisites', [])
                        if 'ability_score' in p
                    )

                feat = tblFeatsLibrary(
                    api_index=index,
                    name=data['name'],
                    prerequisites=prerequisites,
                    description=description,
                    source='srd',
                    created_at=_now(),
                )
                db.session.add(feat)
                db.session.commit()
                added += 1
            except Exception:
                errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Weapons sync ───────────────────────────────────────────────────────────────

def sync_weapons_from_api(state=None):
    weapon_list, err = merged_category_list({'2014': 'weapon', '2024': 'weapons'})
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(weapon_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(weapon_list):
        version = _api_version(api_base)
        _outcome = 'skip'
        try:
            index = entry['index']
            if tblWeaponsLibrary.query.filter_by(api_index=index).first():
                _outcome = 'skip'
            else:
                try:
                    detail = requests.get(f'{api_base}/equipment/{index}', timeout=10)

                    if detail.status_code == 404:
                        # Magic weapons live under /magic-items/ instead of /equipment/
                        magic = requests.get(f'{api_base}/magic-items/{index}', timeout=10)
                        if magic.status_code == 404:
                            _outcome = 'skip'
                        else:
                            magic.raise_for_status()
                            mdata = magic.json()
                            desc_lines = mdata.get('desc', [])
                            type_line  = desc_lines[0] if desc_lines else ''
                            full_desc  = '\n'.join(desc_lines[1:]) if len(desc_lines) > 1 else ''
                            raw_img    = mdata.get('image', '')
                            image_url  = ('https://www.dnd5eapi.co' + raw_img) if raw_img else ''
                            w = tblWeaponsLibrary(
                                api_index=index,
                                name=mdata['name'],
                                weapon_category='Magic',
                                weapon_range='',
                                damage_dice='',
                                damage_type='',
                                two_handed_damage_dice='',
                                two_handed_damage_type='',
                                range_normal=0,
                                range_long=0,
                                weight=0,
                                cost='',
                                properties=type_line,
                                mastery='',
                                notes=full_desc,
                                image_url=image_url,
                                source='srd-magic',
                                created_at=_now(),
                            )
                            db.session.add(w)
                            db.session.commit()
                            _outcome = 'add'
                    else:
                        detail.raise_for_status()
                        data = detail.json()

                        if not data.get('damage'):
                            _outcome = 'skip'
                        else:
                            dmg   = data['damage']
                            two_h = data.get('two_handed_damage') or {}
                            cost  = data.get('cost') or {}
                            rng   = data.get('range') or {}
                            throw_rng = data.get('throw_range') or {}

                            if version == '2024':
                                cats = [c['index'] for c in data.get('equipment_categories', [])]
                                weapon_category = ('Martial' if 'martial-weapons' in cats
                                                   else 'Simple' if 'simple-weapons' in cats else '')
                                weapon_range    = ('Ranged' if 'ranged-weapons' in cats
                                                   else 'Melee' if 'melee-weapons' in cats else '')
                                mastery = data.get('mastery', {}).get('name', '') if data.get('mastery') else ''
                            else:
                                weapon_category = data.get('weapon_category', '')
                                weapon_range    = data.get('weapon_range', '')
                                mastery = ''

                            if weapon_range == 'Ranged':
                                range_normal = rng.get('normal', 0)
                                range_long   = rng.get('long', 0)
                            elif throw_rng:
                                range_normal = throw_rng.get('normal', 0)
                                range_long   = throw_rng.get('long', 0)
                            else:
                                range_normal = range_long = 0

                            w = tblWeaponsLibrary(
                                api_index=index,
                                name=data['name'],
                                weapon_category=weapon_category,
                                weapon_range=weapon_range,
                                damage_dice=dmg.get('damage_dice', ''),
                                damage_type=dmg.get('damage_type', {}).get('name', ''),
                                two_handed_damage_dice=two_h.get('damage_dice', ''),
                                two_handed_damage_type=two_h.get('damage_type', {}).get('name', ''),
                                range_normal=range_normal,
                                range_long=range_long,
                                weight=data.get('weight', 0),
                                cost=f"{cost.get('quantity', '')} {cost.get('unit', '')}".strip(),
                                properties=', '.join(p['name'] for p in data.get('properties', [])),
                                mastery=mastery,
                                notes='',
                                image_url='',
                                source='srd',
                                created_at=_now(),
                            )
                            db.session.add(w)
                            db.session.commit()
                            _outcome = 'add'
                except Exception:
                    _outcome = 'error'
        except Exception:
            _outcome = 'error'
        finally:
            if _outcome == 'add':
                added += 1
            elif _outcome == 'skip':
                skipped += 1
            else:
                errors += 1
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── API Settings ───────────────────────────────────────────────────────────────

@reference_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@dm_required
def api_settings():
    if request.method == 'POST':
        choice = request.form.get('api_choice', '').strip()
        custom = request.form.get('custom_url', '').strip()
        new_url = custom if choice == 'custom' else choice
        if not new_url:
            flash('API URL cannot be empty.')
            return redirect(url_for('reference_bp.api_settings'))

        setting = tblDnDAPIConfig.query.filter_by(key='dnd_api_base').first()
        if setting:
            setting.value = new_url
            setting.updated_at = _now()
        else:
            db.session.add(tblDnDAPIConfig(key='dnd_api_base', value=new_url, updated_at=_now()))
        db.session.commit()
        flash(f'API URL updated to: {new_url}')
        return redirect(url_for('reference_bp.api_settings'))

    current = get_api_base()
    return render_template('ttrpg/api_settings.html',
                           current=current,
                           api_options=API_OPTIONS,
                           default=DEFAULT_API_BASE)


@reference_bp.route('/settings/test')
@login_required
@dm_required
def api_test():
    api_base = request.args.get('url', get_api_base()).strip()
    if api_base == MERGED_API:
        # merged mode has no single URL — test both real bases
        results = []
        for base in (API_2024, API_2014):
            try:
                resp = requests.get(base, timeout=8)
                resp.raise_for_status()
                results.append(f'{_api_version(base)} ok ({len(resp.json())} endpoints)')
            except Exception as e:
                return jsonify({'ok': False, 'error': f'{_api_version(base)}: {e}'})
        return jsonify({'ok': True, 'endpoints': results})
    try:
        resp = requests.get(api_base, timeout=8)
        resp.raise_for_status()
        keys = list(resp.json().keys())[:8]
        return jsonify({'ok': True, 'endpoints': keys})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ── Read-only library browser (all users, incl. players) ────────────────────────

@reference_bp.route('/library')
@login_required
def library_browse():
    """Read-only browse of every D&D library for any logged-in user.

    Players have no access to the DM library pages (those stay @dm_required), so
    this gives them the same reference data they already see on the relay. The
    field set mirrors relay_broadcaster.push_library so both sides match. Read
    only: no add/edit/delete/sync here."""
    def _lvl(n):
        return 'Cantrip' if (n or 0) == 0 else f'Level {n}'

    def _join(parts):
        return ' • '.join([p for p in parts if p])

    spells = [{'name': s.name,
               'sub': _join([_lvl(s.level), s.school or '', s.classes_text or '']),
               'desc': s.description or ''}
              for s in tblSpellsLibrary.query.order_by(tblSpellsLibrary.name).all()]
    feats = [{'name': f.name,
              'sub': ('Req: ' + f.prerequisites) if f.prerequisites else '',
              'desc': f.description or ''}
             for f in tblFeatsLibrary.query.order_by(tblFeatsLibrary.name).all()]
    weapons = [{'name': w.name,
                'sub': _join([w.weapon_category or '', w.weapon_range or '',
                              _join([w.damage_dice or '', w.damage_type or '']), w.properties or '']),
                'desc': w.notes or ''}
               for w in tblWeaponsLibrary.query.order_by(tblWeaponsLibrary.name).all()]
    armor = [{'name': a.name,
              'sub': _join([a.armor_category or '',
                            (f'AC {a.armor_class_base}' if a.armor_class_base is not None else ''),
                            ('Stealth disadv.' if a.stealth_disadvantage else '')]),
              'desc': a.notes or ''}
             for a in tblArmorLibrary.query.order_by(tblArmorLibrary.name).all()]
    equipment = [{'name': e.name,
                  'sub': _join([' › '.join([p for p in [e.category, e.subcategory] if p]),
                                e.cost or '', (f'{e.weight} lb' if e.weight else '')]),
                  'desc': e.description or ''}
                 for e in tblEquipmentLibrary.query.order_by(tblEquipmentLibrary.name).all()]
    skills = [{'name': sk.name, 'sub': sk.ability_score or '', 'desc': sk.description or ''}
              for sk in tblSkillsLibrary.query.order_by(tblSkillsLibrary.name).all()]
    races = [{'name': r.name,
              'sub': _join([(f'Speed {r.speed} ft' if r.speed else ''), r.size or '', r.ability_bonuses or '']),
              'desc': r.traits_text or ''}
             for r in tblRacesLibrary.query.order_by(tblRacesLibrary.name).all()]
    classes = [{'name': c.name,
                'sub': _join([(f'd{c.hit_die}' if c.hit_die else ''),
                              c.spellcasting_ability or '', c.saving_throws or '']),
                'desc': c.description or ''}
               for c in tblClassesLibrary.query.order_by(tblClassesLibrary.name).all()]
    conditions = [{'name': c.name, 'sub': '', 'desc': c.description or ''}
                  for c in tblConditionsLibrary.query.order_by(tblConditionsLibrary.name).all()]
    magic_items = [{'name': m.name,
                    'sub': _join([m.category or '', m.rarity or '',
                                  ('Requires attunement' if m.attunement else '')]),
                    'desc': m.description or ''}
                   for m in tblMagicItemsLibrary.query.order_by(tblMagicItemsLibrary.name).all()]
    features = [{'name': f.name,
                 'sub': _join([f.class_name or '', f.subclass_name or '',
                               (f'Level {f.level}' if f.level else '')]),
                 'desc': f.description or ''}
                for f in tblFeaturesLibrary.query.order_by(
                    tblFeaturesLibrary.class_name, tblFeaturesLibrary.level,
                    tblFeaturesLibrary.name).all()]
    subclasses = [{'name': s.name, 'sub': _join([s.class_name or '', s.flavor or '']),
                   'desc': s.description or ''}
                  for s in tblSubclassesLibrary.query.order_by(
                      tblSubclassesLibrary.class_name, tblSubclassesLibrary.name).all()]
    traits = [{'name': t.name, 'sub': t.races_text or '', 'desc': t.description or ''}
              for t in tblTraitsLibrary.query.order_by(tblTraitsLibrary.name).all()]
    weapon_props = [{'name': w.name, 'sub': '', 'desc': w.description or ''}
                    for w in tblWeaponPropertiesLibrary.query.order_by(
                        tblWeaponPropertiesLibrary.name).all()]
    rules = [{'name': r.name, 'sub': r.parent or '', 'desc': r.description or ''}
             for r in tblRulesLibrary.query.order_by(
                 tblRulesLibrary.parent, tblRulesLibrary.name).all()]

    # Sections listed alphabetically by label.
    categories = [
        ('armor', 'Armor', armor), ('features', 'Class Features', features),
        ('classes', 'Classes', classes), ('conditions', 'Conditions', conditions),
        ('equipment', 'Equipment', equipment), ('feats', 'Feats', feats),
        ('magicitems', 'Magic Items', magic_items), ('races', 'Races', races),
        ('rules', 'Rules', rules), ('skills', 'Skills', skills),
        ('spells', 'Spells', spells), ('subclasses', 'Subclasses', subclasses),
        ('traits', 'Traits', traits), ('weaponprops', 'Weapon Properties', weapon_props),
        ('weapons', 'Weapons', weapons),
    ]
    return render_template('ttrpg/library_browse.html', categories=categories)


# ── Clear all libraries (for a clean re-sync) ────────────────────────────────────

@reference_bp.route('/libraries/clear', methods=['POST'])
@login_required
@dm_required
def libraries_clear():
    """Clear D&D reference libraries so they can be cleanly re-synced.

    scope='srd' (default): delete only API-synced rows, KEEP homebrew — use this
    before Sync All. scope='homebrew': delete only custom (homebrew) rows.
    Characters, sessions, and the monster library are never touched."""
    models = (tblSpellsLibrary, tblFeatsLibrary, tblWeaponsLibrary, tblArmorLibrary,
              tblEquipmentLibrary, tblSkillsLibrary, tblRacesLibrary, tblClassesLibrary,
              tblConditionsLibrary, tblMagicItemsLibrary, tblFeaturesLibrary,
              tblClassLevelsLibrary, tblSubclassesLibrary, tblTraitsLibrary,
              tblWeaponPropertiesLibrary, tblRulesLibrary)
    scope = request.form.get('scope', 'srd')
    total = 0
    for model in models:
        if scope == 'all':
            q = model.query
        elif scope == 'homebrew':
            q = model.query.filter(model.source == 'homebrew')
        else:  # synced/SRD — everything that isn't homebrew
            q = model.query.filter((model.source != 'homebrew') | (model.source.is_(None)))
        total += q.delete(synchronize_session=False)
    db.session.commit()

    if scope == 'all':
        # Tables are now empty — reset the rowid counters so a fresh Sync All
        # re-creates rows starting at id 1. (These tables aren't AUTOINCREMENT,
        # so an empty table already restarts at 1; clearing sqlite_sequence is a
        # harmless safeguard in case that ever changes.)
        try:
            names = ', '.join(f"'{m.__tablename__}'" for m in models)
            db.session.execute(text(f"DELETE FROM sqlite_sequence WHERE name IN ({names})"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(f'Cleared ALL {total} library rows and reset IDs to 1. Run "Sync All" now — '
              f'if the re-sync matches, players keep their assigned items.')
    elif scope == 'homebrew':
        flash(f'Cleared {total} homebrew rows from the D&D libraries.')
    else:
        flash(f'Cleared {total} synced (SRD) rows; homebrew kept. Click "Sync All" to repopulate.')
    return redirect(url_for('reference_bp.api_settings'))


# ── Feats library ──────────────────────────────────────────────────────────────

@reference_bp.route('/feats')
@login_required
@dm_required
def feats_library():
    total = tblFeatsLibrary.query.count()
    q = request.args.get('q', '').strip()
    src = request.args.get('src', '').strip()
    feats = tblFeatsLibrary.query
    if q:
        feats = feats.filter(tblFeatsLibrary.name.ilike(f'%{q}%'))
    if src:
        feats = feats.filter(tblFeatsLibrary.source == src)
    feats = feats.order_by(tblFeatsLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/feats_library.html',
                           feats=feats, total=total, q=q, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/feats/sync', methods=['POST'])
@login_required
@dm_required
def feats_sync():
    key = 'feats'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_feats_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/feats/add', methods=['POST'])
@login_required
@dm_required
def feat_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Feat name is required.')
        return redirect(url_for('reference_bp.feats_library'))
    feat = tblFeatsLibrary(
        api_index=None,
        name=name,
        prerequisites=request.form.get('prerequisites', '').strip(),
        description=request.form.get('description', '').strip(),
        source='homebrew',
        created_at=_now(),
    )
    db.session.add(feat)
    db.session.commit()
    flash(f'Added custom feat "{name}".')
    return redirect(url_for('reference_bp.feats_library'))


@reference_bp.route('/feats/<int:feat_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def feat_delete(feat_lib_id):
    feat = tblFeatsLibrary.query.get_or_404(feat_lib_id)
    if feat.source != 'homebrew':
        flash('Only custom feats can be deleted.')
        return redirect(url_for('reference_bp.feats_library'))
    db.session.delete(feat)
    db.session.commit()
    flash(f'Deleted "{feat.name}".')
    return redirect(url_for('reference_bp.feats_library'))


@reference_bp.route('/feats/search')
@login_required
def feats_search():
    q = request.args.get('q', '').strip()
    feats = tblFeatsLibrary.query.filter(
        tblFeatsLibrary.name.ilike(f'%{q}%')
    ).order_by(tblFeatsLibrary.name).limit(500).all()
    return jsonify([{
        'feat_lib_id':   f.feat_lib_id,
        'name':          f.name,
        'prerequisites': f.prerequisites,
        'description':   f.description,
    } for f in feats])


# ── Weapons library ────────────────────────────────────────────────────────────

@reference_bp.route('/weapons/add', methods=['POST'])
@login_required
@dm_required
def weapon_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Weapon name is required.')
        return redirect(url_for('reference_bp.weapons_library'))
    uploaded = _save_weapon_image('image_file')
    image_url = uploaded or request.form.get('image_url', '')
    w = tblWeaponsLibrary(
        name                   = name,
        weapon_category        = request.form.get('weapon_category', ''),
        weapon_range           = request.form.get('weapon_range', ''),
        damage_dice            = request.form.get('damage_dice', ''),
        damage_type            = request.form.get('damage_type', ''),
        two_handed_damage_dice = request.form.get('two_handed_damage_dice', ''),
        two_handed_damage_type = request.form.get('two_handed_damage_type', ''),
        range_normal           = int(request.form.get('range_normal') or 0),
        range_long             = int(request.form.get('range_long') or 0),
        cost                   = request.form.get('cost', ''),
        weight                 = float(request.form.get('weight') or 0),
        properties             = request.form.get('properties', ''),
        mastery                = request.form.get('mastery', ''),
        notes                  = request.form.get('notes', ''),
        image_url              = image_url,
        source                 = 'homebrew',
        created_at             = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )
    db.session.add(w)
    db.session.commit()
    flash(f'Added "{name}" to the weapons library.')
    return redirect(url_for('reference_bp.weapons_library'))


@reference_bp.route('/weapons/<int:weapon_lib_id>/edit', methods=['POST'])
@login_required
@dm_required
def weapon_edit(weapon_lib_id):
    w = tblWeaponsLibrary.query.get_or_404(weapon_lib_id)
    w.name                   = request.form.get('name', w.name).strip() or w.name
    w.weapon_category        = request.form.get('weapon_category', w.weapon_category)
    w.weapon_range           = request.form.get('weapon_range', w.weapon_range)
    w.damage_dice            = request.form.get('damage_dice', w.damage_dice)
    w.damage_type            = request.form.get('damage_type', w.damage_type)
    w.two_handed_damage_dice = request.form.get('two_handed_damage_dice', w.two_handed_damage_dice)
    w.two_handed_damage_type = request.form.get('two_handed_damage_type', w.two_handed_damage_type)
    w.range_normal           = int(request.form.get('range_normal') or 0)
    w.range_long             = int(request.form.get('range_long') or 0)
    w.cost                   = request.form.get('cost', w.cost)
    w.weight                 = float(request.form.get('weight') or 0)
    w.properties             = request.form.get('properties', w.properties)
    w.mastery                = request.form.get('mastery', w.mastery)
    w.notes                  = request.form.get('notes', w.notes)
    uploaded = _save_weapon_image('image_file')
    if uploaded:
        w.image_url = uploaded
    elif request.form.get('image_url', '').strip():
        w.image_url = request.form.get('image_url').strip()
    db.session.commit()
    flash(f'Updated "{w.name}".')
    return redirect(url_for('reference_bp.weapons_library'))


@reference_bp.route('/weapons/<int:weapon_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def weapon_delete(weapon_lib_id):
    w = tblWeaponsLibrary.query.get_or_404(weapon_lib_id)
    name = w.name
    db.session.delete(w)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.weapons_library'))


@reference_bp.route('/weapons')
@login_required
@dm_required
def weapons_library():
    total = tblWeaponsLibrary.query.count()
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    rng = request.args.get('rng', '').strip()
    src = request.args.get('src', '').strip()

    weapons = tblWeaponsLibrary.query
    if q:
        weapons = weapons.filter(tblWeaponsLibrary.name.ilike(f'%{q}%'))
    if cat:
        weapons = weapons.filter(tblWeaponsLibrary.weapon_category == cat)
    if rng:
        weapons = weapons.filter(tblWeaponsLibrary.weapon_range == rng)
    if src:
        weapons = weapons.filter(tblWeaponsLibrary.source == src)
    weapons = weapons.order_by(
        tblWeaponsLibrary.weapon_category,
        tblWeaponsLibrary.weapon_range,
        tblWeaponsLibrary.name
    ).all()
    current_api = get_api_base()
    return render_template('ttrpg/weapons_library.html',
                           weapons=weapons, total=total, q=q, cat=cat, rng=rng, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/weapons/sync', methods=['POST'])
@login_required
@dm_required
def weapons_sync():
    key = 'weapons'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_weapons_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/weapons/search')
@login_required
def weapons_search():
    q = request.args.get('q', '').strip()
    weapons = tblWeaponsLibrary.query.filter(
        tblWeaponsLibrary.name.ilike(f'%{q}%')
    ).order_by(tblWeaponsLibrary.name).limit(500).all()
    return jsonify([{
        'weapon_lib_id':          w.weapon_lib_id,
        'name':                   w.name,
        'weapon_category':        w.weapon_category,
        'weapon_range':           w.weapon_range,
        'damage_dice':            w.damage_dice,
        'damage_type':            w.damage_type,
        'two_handed_damage_dice': w.two_handed_damage_dice,
        'two_handed_damage_type': w.two_handed_damage_type,
        'range_normal':           w.range_normal,
        'range_long':             w.range_long,
        'properties':             w.properties,
        'mastery':                w.mastery,
        'cost':                   w.cost,
        'weight':                 w.weight,
        'notes':                  w.notes,
    } for w in weapons])


# ── Armor sync ─────────────────────────────────────────────────────────────────

def sync_armor_from_api(state=None):
    armor_list, err = merged_category_list({'2014': 'armor', '2024': 'armor'})
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(armor_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(armor_list):
        version = _api_version(api_base)
        try:
            index = entry['index']
            if tblArmorLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            # Some armor category entries (e.g. Adamantine/Mithral variants) live
            # under /magic-items/ not /equipment/ — try equipment first, fall back.
            data = None
            for endpoint in ('equipment', 'magic-items'):
                r = requests.get(f'{api_base}/{endpoint}/{index}', timeout=10)
                if r.ok and r.content:
                    try:
                        data = r.json()
                        break
                    except Exception:
                        pass
            if not data:
                skipped += 1
                continue

            ac_obj   = data.get('armor_class', {})
            cost_obj = data.get('cost', {})

            ac_base     = ac_obj.get('base', 0)
            dex_bonus   = 1 if ac_obj.get('dex_bonus') else 0
            max_dex_raw = ac_obj.get('max_bonus')
            if max_dex_raw is None and dex_bonus:
                max_dex_bonus = None
            elif max_dex_raw is not None:
                max_dex_bonus = int(max_dex_raw)
            else:
                max_dex_bonus = 0

            if version == '2024':
                cats = [c['index'] for c in data.get('equipment_categories', [])]
                armor_category = (
                    'Heavy'  if 'heavy-armor'  in cats else
                    'Medium' if 'medium-armor' in cats else
                    'Light'  if 'light-armor'  in cats else
                    'Shield' if 'shield'        in cats else
                    data.get('armor_category', '')
                )
            else:
                armor_category = data.get('armor_category', '')

            a = tblArmorLibrary(
                api_index=index,
                name=data['name'],
                armor_category=armor_category,
                armor_class_base=ac_base,
                dex_bonus=dex_bonus,
                max_dex_bonus=max_dex_bonus,
                str_minimum=data.get('str_minimum', 0) or 0,
                stealth_disadvantage=1 if data.get('stealth_disadvantage') else 0,
                weight=data.get('weight', 0) or 0,
                cost=f"{cost_obj.get('quantity', '')} {cost_obj.get('unit', '')}".strip(),
                properties=', '.join(p.get('name', '') for p in data.get('properties', [])),
                notes=_desc_text(data),
                image_url='',
                source='srd',
                created_at=_now(),
            )
            db.session.add(a)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Armor library routes ────────────────────────────────────────────────────────

@reference_bp.route('/armor/<int:armor_lib_id>/edit', methods=['POST'])
@login_required
@dm_required
def armor_edit(armor_lib_id):
    a = tblArmorLibrary.query.get_or_404(armor_lib_id)
    a.name                = request.form.get('name', a.name).strip() or a.name
    a.armor_category      = request.form.get('armor_category', a.armor_category)
    a.armor_class_base    = int(request.form.get('armor_class_base') or 0)
    a.dex_bonus           = 1 if request.form.get('dex_bonus') else 0
    raw_max = request.form.get('max_dex_bonus', '')
    a.max_dex_bonus       = None if raw_max == '' else int(raw_max)
    a.str_minimum         = int(request.form.get('str_minimum') or 0)
    a.stealth_disadvantage = 1 if request.form.get('stealth_disadvantage') else 0
    a.weight              = float(request.form.get('weight') or 0)
    a.cost                = request.form.get('cost', a.cost)
    a.properties          = request.form.get('properties', a.properties)
    a.notes               = request.form.get('notes', a.notes)
    uploaded = _save_armor_image('image_file')
    if uploaded:
        a.image_url = uploaded
    elif request.form.get('image_url', '').strip():
        a.image_url = request.form.get('image_url').strip()
    db.session.commit()
    flash(f'Updated "{a.name}".')
    return redirect(url_for('reference_bp.armor_library'))


@reference_bp.route('/armor/<int:armor_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def armor_delete(armor_lib_id):
    a = tblArmorLibrary.query.get_or_404(armor_lib_id)
    name = a.name
    db.session.delete(a)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.armor_library'))


@reference_bp.route('/armor')
@login_required
@dm_required
def armor_library():
    total = tblArmorLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    cat = request.args.get('cat', '').strip()
    src = request.args.get('src', '').strip()

    armor = tblArmorLibrary.query
    if q:
        armor = armor.filter(tblArmorLibrary.name.ilike(f'%{q}%'))
    if cat:
        armor = armor.filter(tblArmorLibrary.armor_category == cat)
    if src:
        armor = armor.filter(tblArmorLibrary.source == src)
    armor = armor.order_by(
        tblArmorLibrary.armor_category,
        tblArmorLibrary.name
    ).all()
    current_api = get_api_base()
    return render_template('ttrpg/armor_library.html',
                           armor=armor, total=total, q=q, cat=cat, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/armor/sync', methods=['POST'])
@login_required
@dm_required
def armor_sync():
    key = 'armor'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_armor_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/armor/add', methods=['POST'])
@login_required
@dm_required
def armor_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Armor name is required.')
        return redirect(url_for('reference_bp.armor_library'))
    raw_max = request.form.get('max_dex_bonus', '')
    a = tblArmorLibrary(
        api_index=None,
        name=name,
        armor_category=request.form.get('armor_category', ''),
        armor_class_base=int(request.form.get('armor_class_base') or 0),
        dex_bonus=1 if request.form.get('dex_bonus') else 0,
        max_dex_bonus=None if raw_max == '' else int(raw_max),
        str_minimum=int(request.form.get('str_minimum') or 0),
        stealth_disadvantage=1 if request.form.get('stealth_disadvantage') else 0,
        weight=float(request.form.get('weight') or 0),
        cost=request.form.get('cost', '').strip(),
        properties=request.form.get('properties', '').strip(),
        notes=request.form.get('notes', '').strip(),
        image_url=_save_armor_image('image_file') or request.form.get('image_url', '').strip(),
        source='homebrew',
        created_at=_now(),
    )
    db.session.add(a)
    db.session.commit()
    flash(f'Added custom armor "{name}".')
    return redirect(url_for('reference_bp.armor_library'))


@reference_bp.route('/armor/search')
@login_required
def armor_search():
    q = request.args.get('q', '').strip()
    armor = tblArmorLibrary.query.filter(
        tblArmorLibrary.name.ilike(f'%{q}%')
    ).order_by(tblArmorLibrary.name).limit(500).all()
    return jsonify([{
        'armor_lib_id':      a.armor_lib_id,
        'name':              a.name,
        'armor_category':    a.armor_category,
        'armor_class_base':  a.armor_class_base,
        'dex_bonus':         a.dex_bonus,
        'max_dex_bonus':     a.max_dex_bonus,
        'str_minimum':       a.str_minimum,
        'stealth_disadvantage': a.stealth_disadvantage,
        'cost':              a.cost,
        'weight':            a.weight,
        'notes':             a.notes,
    } for a in armor])


# ── Spells sync ────────────────────────────────────────────────────────────────

def sync_spells_from_api(state=None):
    spell_list, err = merged_resource_list('spells')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(spell_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(spell_list):
        try:
            index = entry['index']
            if tblSpellsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/spells/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            components_list = data.get('components', [])
            material = data.get('material', '')
            if material and 'M' in components_list:
                components_str = ', '.join(components_list) + f' ({material})'
            else:
                components_str = ', '.join(components_list)

            _spell_desc = _desc_text(data)
            _dmg_dice, _dmg_type = parse_spell_damage(_spell_desc)
            spell = tblSpellsLibrary(
                api_index    = index,
                name         = data['name'],
                level        = data.get('level', 0),
                school       = data.get('school', {}).get('name', ''),
                casting_time = data.get('casting_time', ''),
                range_text   = data.get('range', ''),
                components   = components_str,
                duration     = data.get('duration', ''),
                concentration = 1 if data.get('concentration', False) else 0,
                ritual       = 1 if data.get('ritual', False) else 0,
                description  = _spell_desc,
                classes_text = ', '.join(c['name'] for c in data.get('classes', [])),
                damage_dice  = _dmg_dice,
                damage_type  = _dmg_type,
                source       = 'srd',
                created_at   = _now(),
            )
            db.session.add(spell)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Spells library routes ──────────────────────────────────────────────────────

@reference_bp.route('/spells')
@login_required
@dm_required
def spells_library():
    total = tblSpellsLibrary.query.count()
    q      = request.args.get('q',      '').strip()
    level  = request.args.get('level',  '').strip()
    school = request.args.get('school', '').strip()
    src    = request.args.get('src',    '').strip()

    spells = tblSpellsLibrary.query
    if q:
        spells = spells.filter(tblSpellsLibrary.name.ilike(f'%{q}%'))
    if level != '':
        try:
            spells = spells.filter(tblSpellsLibrary.level == int(level))
        except ValueError:
            pass
    if school:
        spells = spells.filter(tblSpellsLibrary.school == school)
    if src:
        spells = spells.filter(tblSpellsLibrary.source == src)
    spells = spells.order_by(tblSpellsLibrary.level, tblSpellsLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/spells_library.html',
                           spells=spells, total=total,
                           q=q, level=level, school=school, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/spells/sync', methods=['POST'])
@login_required
@dm_required
def spells_sync():
    key = 'spells'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_spells_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/spells/add', methods=['POST'])
@login_required
@dm_required
def spell_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Spell name is required.')
        return redirect(url_for('reference_bp.spells_library'))
    _desc = request.form.get('description', '').strip()
    _dmg_dice, _dmg_type = parse_spell_damage(_desc)
    spell = tblSpellsLibrary(
        api_index    = None,
        name         = name,
        level        = int(request.form.get('level', 0) or 0),
        school       = request.form.get('school', '').strip(),
        casting_time = request.form.get('casting_time', '').strip(),
        range_text   = request.form.get('range_text', '').strip(),
        components   = request.form.get('components', '').strip(),
        duration     = request.form.get('duration', '').strip(),
        concentration = 1 if request.form.get('concentration') else 0,
        ritual       = 1 if request.form.get('ritual') else 0,
        description  = _desc,
        classes_text = request.form.get('classes_text', '').strip(),
        damage_dice  = _dmg_dice,
        damage_type  = _dmg_type,
        source       = 'homebrew',
        created_at   = _now(),
    )
    db.session.add(spell)
    db.session.commit()
    flash(f'Added custom spell "{name}".')
    return redirect(url_for('reference_bp.spells_library'))


@reference_bp.route('/spells/<int:spell_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def spell_delete(spell_lib_id):
    spell = tblSpellsLibrary.query.get_or_404(spell_lib_id)
    if spell.source != 'homebrew':
        flash('Only custom spells can be deleted.')
        return redirect(url_for('reference_bp.spells_library'))
    name = spell.name
    db.session.delete(spell)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.spells_library'))


@reference_bp.route('/spells/search')
@login_required
def spells_search():
    q      = request.args.get('q',      '').strip()
    level  = request.args.get('level',  '').strip()
    school = request.args.get('school', '').strip()
    src    = request.args.get('src',    '').strip()
    limit  = int(request.args.get('limit', 20))

    spells = tblSpellsLibrary.query
    if q:
        spells = spells.filter(tblSpellsLibrary.name.ilike(f'%{q}%'))
    if level != '':
        try:
            spells = spells.filter(tblSpellsLibrary.level == int(level))
        except ValueError:
            pass
    if school:
        spells = spells.filter(tblSpellsLibrary.school == school)
    if src:
        spells = spells.filter(tblSpellsLibrary.source == src)
    spells = spells.order_by(tblSpellsLibrary.level, tblSpellsLibrary.name).limit(limit).all()
    return jsonify([{
        'spell_lib_id': s.spell_lib_id,
        'name':         s.name,
        'level':        s.level,
        'school':       s.school,
        'casting_time': s.casting_time,
        'range_text':   s.range_text,
        'components':   s.components,
        'duration':     s.duration,
        'concentration': s.concentration,
        'ritual':       s.ritual,
        'description':  s.description,
        'classes_text': s.classes_text,
        'source':       s.source,
    } for s in spells])


# ── Skills sync ────────────────────────────────────────────────────────────────

def sync_skills_from_api(state=None):
    skill_list, err = merged_resource_list('skills')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(skill_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(skill_list):
        try:
            index = entry['index']
            if tblSkillsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/skills/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            ability_obj = data.get('ability_score', {})
            ability_score = ability_obj.get('name', '') or ability_obj.get('index', '').upper()

            skill = tblSkillsLibrary(
                api_index     = index,
                name          = data['name'],
                ability_score = ability_score,
                description   = _desc_text(data),
                source        = 'srd',
                created_at    = _now(),
            )
            db.session.add(skill)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Skills library routes ──────────────────────────────────────────────────────

@reference_bp.route('/skills')
@login_required
@dm_required
def skills_library():
    total = tblSkillsLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    src = request.args.get('src', '').strip()

    skills = tblSkillsLibrary.query
    if q:
        skills = skills.filter(tblSkillsLibrary.name.ilike(f'%{q}%'))
    if src:
        skills = skills.filter(tblSkillsLibrary.source == src)
    skills = skills.order_by(tblSkillsLibrary.ability_score, tblSkillsLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/skills_library.html',
                           skills=skills, total=total, q=q, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/skills/sync', methods=['POST'])
@login_required
@dm_required
def skills_sync():
    key = 'skills'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_skills_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/skills/add', methods=['POST'])
@login_required
@dm_required
def skill_add_to_lib():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Skill name is required.')
        return redirect(url_for('reference_bp.skills_library'))
    skill = tblSkillsLibrary(
        api_index     = None,
        name          = name,
        ability_score = request.form.get('ability_score', '').strip(),
        description   = request.form.get('description', '').strip(),
        source        = 'homebrew',
        created_at    = _now(),
    )
    db.session.add(skill)
    db.session.commit()
    flash(f'Added custom skill "{name}".')
    return redirect(url_for('reference_bp.skills_library'))


@reference_bp.route('/skills/<int:skill_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def skill_lib_delete(skill_lib_id):
    skill = tblSkillsLibrary.query.get_or_404(skill_lib_id)
    if skill.source != 'homebrew':
        flash('Only custom skills can be deleted.')
        return redirect(url_for('reference_bp.skills_library'))
    name = skill.name
    db.session.delete(skill)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.skills_library'))


@reference_bp.route('/skills/search')
@login_required
def skills_search():
    q = request.args.get('q', '').strip()
    skills = tblSkillsLibrary.query.filter(
        tblSkillsLibrary.name.ilike(f'%{q}%')
    ).order_by(tblSkillsLibrary.ability_score, tblSkillsLibrary.name).limit(30).all()
    return jsonify([{
        'skill_lib_id': s.skill_lib_id,
        'name':         s.name,
        'ability_score': s.ability_score,
        'description':  s.description,
        'source':       s.source,
    } for s in skills])


# ── Races sync ─────────────────────────────────────────────────────────────────

def sync_races_from_api(state=None):
    # merged mode: 2024 renamed races -> species (aliased); species entries lack
    # ability bonuses/languages, which stay blank — 2014 fills classic races.
    race_list, err = merged_resource_list('races')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(race_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(race_list):
        try:
            index = entry['index']
            if tblRacesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/{_resource_path(api_base, "races")}/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            ability_bonuses = ', '.join(
                f"+{ab['bonus']} {ab['ability_score']['name']}"
                for ab in data.get('ability_bonuses', [])
            )

            race = tblRacesLibrary(
                api_index      = index,
                name           = data['name'],
                speed          = data.get('speed', 30),
                size           = data.get('size', ''),
                ability_bonuses = ability_bonuses,
                traits_text    = '\n'.join(t['name'] for t in data.get('traits', [])),
                languages      = ', '.join(l['name'] for l in data.get('languages', [])),
                description    = data.get('alignment', ''),
                source         = 'srd',
                created_at     = _now(),
            )
            db.session.add(race)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Races library routes ───────────────────────────────────────────────────────

@reference_bp.route('/races')
@login_required
@dm_required
def races_library():
    total = tblRacesLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    src = request.args.get('src', '').strip()

    races = tblRacesLibrary.query
    if q:
        races = races.filter(tblRacesLibrary.name.ilike(f'%{q}%'))
    if src:
        races = races.filter(tblRacesLibrary.source == src)
    races = races.order_by(tblRacesLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/races_library.html',
                           races=races, total=total, q=q, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/races/sync', methods=['POST'])
@login_required
@dm_required
def races_sync():
    key = 'races'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_races_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/races/add', methods=['POST'])
@login_required
@dm_required
def race_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Race name is required.')
        return redirect(url_for('reference_bp.races_library'))
    race = tblRacesLibrary(
        api_index       = None,
        name            = name,
        speed           = int(request.form.get('speed', 30) or 30),
        size            = request.form.get('size', '').strip(),
        ability_bonuses = request.form.get('ability_bonuses', '').strip(),
        traits_text     = request.form.get('traits_text', '').strip(),
        languages       = request.form.get('languages', '').strip(),
        description     = request.form.get('description', '').strip(),
        source          = 'homebrew',
        created_at      = _now(),
    )
    db.session.add(race)
    db.session.commit()
    flash(f'Added custom race "{name}".')
    return redirect(url_for('reference_bp.races_library'))


@reference_bp.route('/races/<int:race_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def race_delete(race_lib_id):
    race = tblRacesLibrary.query.get_or_404(race_lib_id)
    if race.source != 'homebrew':
        flash('Only custom races can be deleted.')
        return redirect(url_for('reference_bp.races_library'))
    name = race.name
    db.session.delete(race)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.races_library'))


# ── Equipment Library ───────────────────────────────────────────────────────────

SKIP_EQUIPMENT_CATEGORIES = {'armor', 'weapon', 'weapons', 'armor and shields'}

def sync_equipment_from_api(state=None):
    eq_list, err = merged_resource_list('equipment')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(eq_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(eq_list):
        try:
            index = entry['index']
            if tblEquipmentLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            r = requests.get(f'{api_base}/equipment/{index}', timeout=10)
            if not r.ok or not r.content:
                skipped += 1
                continue
            data = r.json()

            cat = (data.get('equipment_category') or {}).get('name', '')
            if cat.lower() in SKIP_EQUIPMENT_CATEGORIES:
                skipped += 1
                continue

            subcat = (data.get('gear_category') or
                      data.get('tool_category') or
                      data.get('vehicle_category') or {})
            if isinstance(subcat, dict):
                subcat = subcat.get('name', '')
            else:
                subcat = ''

            cost_obj = data.get('cost', {})
            cost_str = f"{cost_obj.get('quantity', 0)} {cost_obj.get('unit', 'gp')}" if cost_obj else ''

            item = tblEquipmentLibrary(
                api_index   = index,
                name        = data.get('name', index),
                category    = cat,
                subcategory = subcat,
                weight      = float(data.get('weight', 0) or 0),
                cost        = cost_str,
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            )
            db.session.add(item)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})

    return added, skipped, errors


@reference_bp.route('/equipment')
@login_required
@dm_required
def equipment_library():
    total = tblEquipmentLibrary.query.count()
    q    = request.args.get('q',   '').strip()
    cat  = request.args.get('cat', '').strip()
    src  = request.args.get('src', '').strip()

    query = tblEquipmentLibrary.query
    if q:   query = query.filter(tblEquipmentLibrary.name.ilike(f'%{q}%'))
    if cat: query = query.filter(tblEquipmentLibrary.category == cat)
    if src: query = query.filter(tblEquipmentLibrary.source == src)
    items = query.order_by(tblEquipmentLibrary.category, tblEquipmentLibrary.name).all()

    categories = sorted({i.category for i in tblEquipmentLibrary.query.all() if i.category})
    current_api = get_api_base()
    return render_template('ttrpg/equipment_library.html',
                           items=items, total=total, q=q, cat=cat, src=src,
                           categories=categories,
                           current_api=current_api, api_options=API_OPTIONS)


@reference_bp.route('/equipment/sync', methods=['POST'])
@login_required
@dm_required
def equipment_sync():
    key = 'equipment'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_equipment_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/sync/status/<job_type>')
@login_required
def sync_status(job_type):
    state = _sync_states.get(job_type, {})
    if not state:
        return jsonify({'running': False, 'total': 0, 'done': 0, 'message': ''})
    return jsonify(dict(state))


@reference_bp.route('/equipment/add', methods=['POST'])
@login_required
@dm_required
def equipment_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Item name is required.')
        return redirect(url_for('reference_bp.equipment_library'))
    item = tblEquipmentLibrary(
        api_index   = None,
        name        = name,
        category    = request.form.get('category', '').strip(),
        subcategory = request.form.get('subcategory', '').strip(),
        weight      = float(request.form.get('weight', 0) or 0),
        cost        = request.form.get('cost', '').strip(),
        description = request.form.get('description', '').strip(),
        source      = 'homebrew',
        created_at  = _now(),
    )
    db.session.add(item)
    db.session.commit()
    flash(f'Added "{name}".')
    return redirect(url_for('reference_bp.equipment_library'))


@reference_bp.route('/equipment/<int:equipment_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def equipment_delete(equipment_lib_id):
    item = tblEquipmentLibrary.query.get_or_404(equipment_lib_id)
    if item.source != 'homebrew':
        flash('Only custom items can be deleted.')
        return redirect(url_for('reference_bp.equipment_library'))
    name = item.name
    db.session.delete(item)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.equipment_library'))


@reference_bp.route('/equipment/search')
@login_required
def equipment_search():
    q = request.args.get('q', '').strip()
    items = tblEquipmentLibrary.query.filter(
        tblEquipmentLibrary.name.ilike(f'%{q}%')
    ).order_by(tblEquipmentLibrary.name).limit(500).all()
    return jsonify([{
        'equipment_lib_id': i.equipment_lib_id,
        'name':             i.name,
        'category':         i.category,
        'subcategory':      i.subcategory,
        'weight':           i.weight,
        'cost':             i.cost,
        'description':      i.description,
    } for i in items])


# ── Classes sync ────────────────────────────────────────────────────────────────

def sync_classes_from_api(state=None):
    class_list, err = merged_resource_list('classes')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(class_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(class_list):
        try:
            index = entry['index']
            if tblClassesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/classes/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            saving_throws = ', '.join(st['name'] for st in data.get('saving_throws', []))

            # All proficiencies except saving-throw entries
            profs = [p['name'] for p in data.get('proficiencies', [])
                     if not p['name'].startswith('Saving Throw')]
            proficiencies = ', '.join(profs)

            # Skill choices description
            skill_choices = ''
            for choice in data.get('proficiency_choices', []):
                desc = choice.get('desc', '')
                if desc:
                    skill_choices = desc
                    break

            subclasses = ', '.join(sc['name'] for sc in data.get('subclasses', []))

            spell_obj = data.get('spellcasting', {})
            spellcasting_ability = (spell_obj.get('spellcasting_ability', {}) or {}).get('name', '')

            cls = tblClassesLibrary(
                api_index            = index,
                name                 = data['name'],
                hit_die              = data.get('hit_die', 8),
                saving_throws        = saving_throws,
                proficiencies        = proficiencies,
                skill_choices        = skill_choices,
                subclasses           = subclasses,
                spellcasting_ability = spellcasting_ability,
                description          = '',
                source               = 'srd',
                created_at           = _now(),
            )
            db.session.add(cls)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Classes library routes ─────────────────────────────────────────────────────

@reference_bp.route('/classes')
@login_required
@dm_required
def classes_library():
    total = tblClassesLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    src = request.args.get('src', '').strip()

    classes = tblClassesLibrary.query
    if q:
        classes = classes.filter(tblClassesLibrary.name.ilike(f'%{q}%'))
    if src:
        classes = classes.filter(tblClassesLibrary.source == src)
    classes = classes.order_by(tblClassesLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/classes_library.html',
                           classes=classes, total=total, q=q, src=src,
                           current_api=current_api, api_options=API_OPTIONS)


@reference_bp.route('/classes/sync', methods=['POST'])
@login_required
@dm_required
def classes_sync():
    key = 'classes'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_classes_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/classes/add', methods=['POST'])
@login_required
@dm_required
def class_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Class name is required.')
        return redirect(url_for('reference_bp.classes_library'))
    cls = tblClassesLibrary(
        api_index            = None,
        name                 = name,
        hit_die              = int(request.form.get('hit_die', 8) or 8),
        saving_throws        = request.form.get('saving_throws', '').strip(),
        proficiencies        = request.form.get('proficiencies', '').strip(),
        skill_choices        = request.form.get('skill_choices', '').strip(),
        subclasses           = request.form.get('subclasses', '').strip(),
        spellcasting_ability = request.form.get('spellcasting_ability', '').strip(),
        description          = request.form.get('description', '').strip(),
        source               = 'homebrew',
        created_at           = _now(),
    )
    db.session.add(cls)
    db.session.commit()
    flash(f'Added custom class "{name}".')
    return redirect(url_for('reference_bp.classes_library'))


@reference_bp.route('/classes/<int:class_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def class_delete(class_lib_id):
    cls = tblClassesLibrary.query.get_or_404(class_lib_id)
    if cls.source != 'homebrew':
        flash('Only custom classes can be deleted.')
        return redirect(url_for('reference_bp.classes_library'))
    name = cls.name
    db.session.delete(cls)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.classes_library'))


@reference_bp.route('/races/search')
@login_required
def races_search():
    q = request.args.get('q', '').strip()
    races = tblRacesLibrary.query.filter(
        tblRacesLibrary.name.ilike(f'%{q}%')
    ).order_by(tblRacesLibrary.name).limit(500).all()
    return jsonify([{
        'race_lib_id':    r.race_lib_id,
        'name':           r.name,
        'speed':          r.speed,
        'size':           r.size,
        'ability_bonuses': r.ability_bonuses,
        'traits_text':    r.traits_text,
        'languages':      r.languages,
        'description':    r.description,
    } for r in races])


# ── Conditions sync ─────────────────────────────────────────────────────────────

def sync_conditions_from_api(state=None):
    cond_list, err = merged_resource_list('conditions')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(cond_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(cond_list):
        try:
            index = entry['index']
            if tblConditionsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/conditions/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            db.session.add(tblConditionsLibrary(
                api_index   = index,
                name        = data['name'],
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Magic items sync ────────────────────────────────────────────────────────────

def sync_magic_items_from_api(state=None):
    item_list, err = merged_resource_list('magic-items')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(item_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(item_list):
        try:
            index = entry['index']
            if tblMagicItemsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/magic-items/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            description = _desc_text(data)
            # attunement: explicit bool on 2024; 2014 states it in the type line
            # of desc[0], e.g. "Wondrous item, rare (requires attunement)"
            attune = data.get('attunement')
            if attune is None:
                attune = 'requires attunement' in description[:200].lower()
            raw_img = data.get('image', '')
            db.session.add(tblMagicItemsLibrary(
                api_index   = index,
                name        = data['name'],
                category    = (data.get('equipment_category') or {}).get('name', ''),
                rarity      = (data.get('rarity') or {}).get('name', ''),
                attunement  = 1 if attune else 0,
                description = description,
                image_url   = ('https://www.dnd5eapi.co' + raw_img) if raw_img else '',
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Class features sync ─────────────────────────────────────────────────────────

def sync_features_from_api(state=None):
    feature_list, err = merged_resource_list('features')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(feature_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(feature_list):
        try:
            index = entry['index']
            if tblFeaturesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/features/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            prereqs = ', '.join(
                p.get('name', p.get('type', '')) if isinstance(p, dict) else str(p)
                for p in data.get('prerequisites', [])
            )
            cls_name = (data.get('class') or {}).get('name', '')
            sub_name = (data.get('subclass') or {}).get('name', '')
            level    = _feature_level(data)
            # The two API editions index the same feature differently ('rage' vs
            # 'barbarian-rage'), so index dedup alone would store both editions.
            # Skip when the class/subclass/level/name combination already exists —
            # in merged mode 2024 syncs first, so its text wins.
            from sqlalchemy import func as _f
            if (tblFeaturesLibrary.query
                    .filter(_f.lower(tblFeaturesLibrary.name) == data['name'].lower(),
                            _f.lower(tblFeaturesLibrary.class_name) == cls_name.lower(),
                            _f.lower(tblFeaturesLibrary.subclass_name) == sub_name.lower(),
                            tblFeaturesLibrary.level == level)
                    .first()):
                skipped += 1
                continue
            db.session.add(tblFeaturesLibrary(
                api_index     = index,
                name          = data['name'],
                class_name    = cls_name,
                subclass_name = sub_name,
                level         = level,
                prerequisites = prereqs,
                description   = _desc_text(data),
                source        = 'srd',
                created_at    = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Class level tables sync (proficiency bonus, spell slots, class counters) ────

def sync_class_levels_from_api(state=None):
    """Per-level progression for every class: /classes/{index}/levels.

    Only the 2014 API serves level tables today; in merged mode each class
    tries its own base first, then the remaining sources — so 2024-sourced
    classes still get their 2014 progression."""
    class_list, err = merged_resource_list('classes')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(class_list) * 20   # ~20 levels per class

    added = skipped = errors = 0
    done = 0
    for entry, entry_base in class_list:
        index = entry['index']
        levels = []
        bases = [entry_base] + [b for b in api_sources() if b != entry_base]
        for base in bases:
            try:
                resp = requests.get(f'{base}/classes/{index}/levels', timeout=15)
                if not resp.ok or not resp.content:
                    continue
                data = resp.json()
                if isinstance(data, list) and data:
                    levels = data
                    break
            except Exception:
                continue

        for lvl in levels:
            done += 1
            try:
                # subclass-specific level rows ride along in some tables — skip them
                if lvl.get('subclass'):
                    skipped += 1
                    continue
                lvl_no = lvl.get('level', 0)
                api_idx = lvl.get('index') or f'{index}-{lvl_no}'
                if tblClassLevelsLibrary.query.filter_by(api_index=api_idx).first():
                    skipped += 1
                    continue
                spellcasting = lvl.get('spellcasting') or {}
                slots = {str(n): spellcasting.get(f'spell_slots_level_{n}', 0) or 0
                         for n in range(1, 10)}
                import json as _json
                db.session.add(tblClassLevelsLibrary(
                    api_index      = api_idx,
                    class_name     = (lvl.get('class') or {}).get('name', index.title()),
                    level          = lvl_no,
                    prof_bonus     = lvl.get('prof_bonus', 2) or 2,
                    features_text  = '\n'.join(f['name'] for f in lvl.get('features', [])),
                    cantrips_known = spellcasting.get('cantrips_known', 0) or 0,
                    spells_known   = spellcasting.get('spells_known', 0) or 0,
                    spell_slots_json    = _json.dumps(slots),
                    class_specific_json = _json.dumps(lvl.get('class_specific') or {}),
                    source         = 'srd',
                    created_at     = _now(),
                ))
                db.session.commit()
                added += 1
            except Exception:
                db.session.rollback()
                errors += 1
            finally:
                if state is not None:
                    state.update({'done': done, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Subclasses sync ─────────────────────────────────────────────────────────────

def sync_subclasses_from_api(state=None):
    sub_list, err = merged_resource_list('subclasses')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(sub_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(sub_list):
        try:
            index = entry['index']
            if tblSubclassesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/subclasses/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            description = _desc_text(data)
            # 2024 embeds the subclass features right in the detail — keep them
            # with the description so the archetype reads as one entry.
            embedded = data.get('features')
            if isinstance(embedded, list) and embedded:
                lines = [f"L{f.get('level', '?')} {f.get('name', '')}: {f.get('description', '')}"
                         for f in embedded if isinstance(f, dict)]
                description = (description + '\n\n' + '\n\n'.join(lines)).strip()

            db.session.add(tblSubclassesLibrary(
                api_index   = index,
                name        = data['name'],
                class_name  = (data.get('class') or {}).get('name', ''),
                flavor      = data.get('subclass_flavor') or data.get('summary', ''),
                description = description,
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Racial traits sync ──────────────────────────────────────────────────────────

def sync_traits_from_api(state=None):
    trait_list, err = merged_resource_list('traits')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(trait_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(trait_list):
        try:
            index = entry['index']
            if tblTraitsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/traits/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            # 2014 back-references races/subraces; 2024 uses species/subspecies
            holders = []
            for key in ('races', 'subraces', 'species', 'subspecies'):
                holders += [r.get('name', '') for r in data.get(key) or []]
            db.session.add(tblTraitsLibrary(
                api_index   = index,
                name        = data['name'],
                races_text  = ', '.join(h for h in holders if h),
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Weapon properties sync ──────────────────────────────────────────────────────

def sync_weapon_properties_from_api(state=None):
    prop_list, err = merged_resource_list('weapon-properties')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(prop_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(prop_list):
        try:
            index = entry['index']
            if tblWeaponPropertiesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/weapon-properties/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            db.session.add(tblWeaponPropertiesLibrary(
                api_index   = index,
                name        = data['name'],
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Rules sync (rule categories + rule sections) ────────────────────────────────

def sync_rules_from_api(state=None):
    """SRD rules prose: /rules (6 chapters) gives grouping, /rule-sections (33)
    gives the actual text. Sections store their chapter as `parent`. 2014-only
    today; merged mode just finds nothing on 2024 and moves on."""
    section_parent = {}
    rules_list, _rules_err = merged_resource_list('rules')
    for entry, api_base in rules_list:
        try:
            detail = requests.get(f'{api_base}/rules/{entry["index"]}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            for sub in data.get('subsections', []):
                section_parent[sub.get('index')] = data.get('name', '')
        except Exception:
            continue

    sec_list, err = merged_resource_list('rule-sections')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(sec_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(sec_list):
        try:
            index = entry['index']
            if tblRulesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/rule-sections/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            db.session.add(tblRulesLibrary(
                api_index   = index,
                name        = data['name'],
                parent      = section_parent.get(index, ''),
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Subclasses library (browse, homebrew subclasses + their features) ───────────

@reference_bp.route('/subclasses')
@login_required
@dm_required
def subclasses_library():
    total = tblSubclassesLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    cls = request.args.get('cls', '').strip()
    src = request.args.get('src', '').strip()

    subs = tblSubclassesLibrary.query
    if q:
        subs = subs.filter(tblSubclassesLibrary.name.ilike(f'%{q}%'))
    if cls:
        subs = subs.filter(tblSubclassesLibrary.class_name == cls)
    if src:
        subs = subs.filter(tblSubclassesLibrary.source == src)
    subs = subs.order_by(tblSubclassesLibrary.class_name, tblSubclassesLibrary.name).all()

    # features grouped per subclass name (lowercased) for the card expanders
    feats_by_sub = {}
    for f in (tblFeaturesLibrary.query
              .filter(tblFeaturesLibrary.subclass_name != '')
              .order_by(tblFeaturesLibrary.level, tblFeaturesLibrary.name).all()):
        feats_by_sub.setdefault(f.subclass_name.lower(), []).append(f)

    class_names = [c.name for c in tblClassesLibrary.query.order_by(tblClassesLibrary.name).all()]
    current_api = get_api_base()
    return render_template('ttrpg/subclasses_library.html',
                           subclasses=subs, total=total, q=q, cls=cls, src=src,
                           feats_by_sub=feats_by_sub, class_names=class_names,
                           current_api=current_api, api_options=API_OPTIONS)


@reference_bp.route('/subclasses/add', methods=['POST'])
@login_required
@dm_required
def subclass_add():
    name       = request.form.get('name', '').strip()
    class_name = request.form.get('class_name', '').strip()
    if not name or not class_name:
        flash('Subclass name and class are both required.')
        return redirect(url_for('reference_bp.subclasses_library'))
    if (tblSubclassesLibrary.query
            .filter(db.func.lower(tblSubclassesLibrary.name) == name.lower())
            .first()):
        flash(f'A subclass named "{name}" already exists.')
        return redirect(url_for('reference_bp.subclasses_library'))
    db.session.add(tblSubclassesLibrary(
        api_index   = None,
        name        = name,
        class_name  = class_name,
        flavor      = request.form.get('flavor', '').strip(),
        description = request.form.get('description', '').strip(),
        source      = 'homebrew',
        created_at  = _now(),
    ))
    db.session.commit()
    flash(f'Added homebrew subclass "{name}" ({class_name}). Add its features below, '
          f'then players can pick it on their sheet.')
    return redirect(url_for('reference_bp.subclasses_library'))


@reference_bp.route('/subclasses/<int:subclass_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def subclass_delete(subclass_lib_id):
    sub = tblSubclassesLibrary.query.get_or_404(subclass_lib_id)
    if sub.source != 'homebrew':
        flash('Only homebrew subclasses can be deleted.')
        return redirect(url_for('reference_bp.subclasses_library'))
    name = sub.name
    # its homebrew features go with it (SRD features are never touched)
    dropped = (tblFeaturesLibrary.query
               .filter(db.func.lower(tblFeaturesLibrary.subclass_name) == name.lower(),
                       tblFeaturesLibrary.source == 'homebrew')
               .delete(synchronize_session=False))
    db.session.delete(sub)
    db.session.commit()
    flash(f'Deleted "{name}"' + (f' and its {dropped} homebrew features.' if dropped else '.'))
    return redirect(url_for('reference_bp.subclasses_library'))


@reference_bp.route('/subclasses/features/add', methods=['POST'])
@login_required
@dm_required
def subclass_feature_add():
    sub = tblSubclassesLibrary.query.get_or_404(
        int(request.form.get('subclass_lib_id', 0) or 0))
    name = request.form.get('name', '').strip()
    if not name:
        flash('Feature name is required.')
        return redirect(url_for('reference_bp.subclasses_library'))
    try:
        level = max(1, min(20, int(request.form.get('level', 1) or 1)))
    except ValueError:
        level = 1
    db.session.add(tblFeaturesLibrary(
        api_index     = None,
        name          = name,
        class_name    = sub.class_name,
        subclass_name = sub.name,
        level         = level,
        prerequisites = '',
        description   = request.form.get('description', '').strip(),
        source        = 'homebrew',
        created_at    = _now(),
    ))
    db.session.commit()
    flash(f'Added "{name}" (level {level}) to {sub.name}.')
    return redirect(url_for('reference_bp.subclasses_library'))


@reference_bp.route('/features/<int:feature_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def feature_delete(feature_lib_id):
    f = tblFeaturesLibrary.query.get_or_404(feature_lib_id)
    if f.source != 'homebrew':
        flash('Only homebrew features can be deleted.')
        return redirect(url_for('reference_bp.subclasses_library'))
    name = f.name
    db.session.delete(f)
    db.session.commit()
    flash(f'Deleted feature "{name}".')
    return redirect(url_for('reference_bp.subclasses_library'))


# ── Generic sync runner for the new libraries ────────────────────────────────────
# The classic libraries each grew a bespoke /X/sync route; the newer ones share
# one runner keyed by job type (same background-thread + _sync_states pattern,
# same /sync/status/<job_type> poller).

EXTRA_SYNCS = {
    'conditions':  sync_conditions_from_api,
    'magicitems':  sync_magic_items_from_api,
    'features':    sync_features_from_api,
    'classlevels': sync_class_levels_from_api,
    'subclasses':  sync_subclasses_from_api,
    'traits':      sync_traits_from_api,
    'weaponprops': sync_weapon_properties_from_api,
    'rules':       sync_rules_from_api,
}


def _join_sub(parts):
    return ' • '.join(p for p in parts if p)


# name/sub/desc lookups for the newer libraries — one generic search endpoint
# (used by the sheet's Reference tab) instead of a bespoke /X/search per type.
LOOKUP_MODELS = {
    'conditions':  (tblConditionsLibrary, lambda r: {
        'name': r.name, 'sub': '', 'desc': r.description or ''}),
    'magicitems':  (tblMagicItemsLibrary, lambda r: {
        'name': r.name,
        'sub': _join_sub([r.category or '', r.rarity or '',
                          'Requires attunement' if r.attunement else '']),
        'desc': r.description or ''}),
    'features':    (tblFeaturesLibrary, lambda r: {
        'name': r.name,
        'sub': _join_sub([r.class_name or '', r.subclass_name or '',
                          f'Level {r.level}' if r.level else '']),
        'desc': r.description or ''}),
    'subclasses':  (tblSubclassesLibrary, lambda r: {
        'name': r.name, 'sub': _join_sub([r.class_name or '', r.flavor or '']),
        'desc': r.description or ''}),
    'traits':      (tblTraitsLibrary, lambda r: {
        'name': r.name, 'sub': r.races_text or '', 'desc': r.description or ''}),
    'weaponprops': (tblWeaponPropertiesLibrary, lambda r: {
        'name': r.name, 'sub': '', 'desc': r.description or ''}),
    'rules':       (tblRulesLibrary, lambda r: {
        'name': r.name, 'sub': r.parent or '', 'desc': r.description or ''}),
}


@reference_bp.route('/lookup/<category>')
@login_required
def reference_lookup(category):
    entry = LOOKUP_MODELS.get(category)
    if entry is None:
        return jsonify([]), 404
    model, to_dict = entry
    q = request.args.get('q', '').strip()
    try:
        limit = min(int(request.args.get('limit', 20)), 200)
    except ValueError:
        limit = 20
    query = model.query
    if q:
        query = query.filter(model.name.ilike(f'%{q}%'))
    rows = query.order_by(model.name).limit(limit).all()
    return jsonify([to_dict(r) for r in rows])


@reference_bp.route('/sync/run/<job_type>', methods=['POST'])
@login_required
@dm_required
def sync_run(job_type):
    fn = EXTRA_SYNCS.get(job_type)
    if fn is None:
        return jsonify({'error': f'unknown sync job {job_type!r}'}), 404
    if _sync_states.get(job_type, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[job_type] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = fn(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': job_type})


@reference_bp.route('/classes/search')
@login_required
def classes_search():
    q = request.args.get('q', '').strip()
    classes = tblClassesLibrary.query.filter(
        tblClassesLibrary.name.ilike(f'%{q}%')
    ).order_by(tblClassesLibrary.name).limit(500).all()
    return jsonify([{
        'class_lib_id':         c.class_lib_id,
        'name':                 c.name,
        'hit_die':              c.hit_die,
        'saving_throws':        c.saving_throws,
        'proficiencies':        c.proficiencies,
        'skill_choices':        c.skill_choices,
        'subclasses':           c.subclasses,
        'spellcasting_ability': c.spellcasting_ability,
        'description':          c.description,
    } for c in classes])

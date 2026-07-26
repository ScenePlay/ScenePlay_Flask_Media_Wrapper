"""Small helpers shared across route modules."""
import os
import uuid
from datetime import datetime


def save_upload_downscaled(file_storage, dest_dir, max_dim=1024):
    """Save an uploaded image downscaled to `max_dim` on the long side.

    Token art and portraits render at a few hundred pixels at most, so
    storing multi-MB AI generations wastes disk, LAN bandwidth, and a
    Pillow pass on every relay push. Reuses the broadcaster's battle-tested
    _downscale_image: animated images and Pillow failures fall back to the
    original bytes unchanged, and JPEG/PNG is chosen by actual transparency.

    Returns the saved filename (uuid + chosen extension).
    """
    from relay_broadcaster import _downscale_image
    orig_ext = (file_storage.filename.rsplit('.', 1)[-1].lower()
                if file_storage.filename and '.' in file_storage.filename else 'png')
    raw = file_storage.read()
    out, ext = _downscale_image(raw, orig_ext, max_dim)
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(dest_dir, exist_ok=True)
    with open(os.path.join(dest_dir, filename), 'wb') as f:
        f.write(out)
    return filename


def _now():
    """Local wall-clock timestamp, 'YYYY-MM-DD HH:MM:SS'.

    Single definition matters: these strings are stored in created_at /
    rolled_at columns and compared during relay sync ordering, so every
    module must format identically.
    """
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def campaign_scene_ids(campaign_filter):
    """SQLAlchemy subquery of scene_IDs for the campaign filter
    (-1 = scenes with no campaign). Call only when campaign_filter != 0."""
    from extensions import db
    from models.scenes import tblscenes as sc
    q = db.session.query(sc.scene_ID)
    if campaign_filter == -1:
        return q.filter(db.or_(sc.campaign_id.is_(None), sc.campaign_id == 0))
    return q.filter(sc.campaign_id == campaign_filter)


def scenes_for_filter(campaign_filter):
    """(scene_ID, sceneName) rows for the scene dropdown, limited to the
    active campaign filter — the scene list must only offer scenes the
    campaign filter can actually show."""
    from extensions import db
    from models.scenes import tblscenes as sc
    q = sc.query.with_entities(sc.scene_ID, sc.sceneName)
    if campaign_filter == -1:
        q = q.filter(db.or_(sc.campaign_id.is_(None), sc.campaign_id == 0))
    elif campaign_filter:
        q = q.filter(sc.campaign_id == campaign_filter)
    return q.order_by(sc.sceneName).all()


def campaigns_for_filter():
    """(campaign_id, campaign_name) rows for the campaign filter dropdowns."""
    from models.campaigns import tblcampaigns as cp
    return (cp.query.with_entities(cp.campaign_id, cp.campaign_name)
            .order_by(cp.campaign_name).all())


def dm_only_sceneplay_enabled():
    """True when the 'DM-only ScenePlay' switch (Utilities > Access Control)
    is on. Any read failure means open — the historical LAN-trust default."""
    from sql import appsettingGet
    try:
        return str(appsettingGet('DMOnlyScenePlay', '0') or '0') == '1'
    except Exception:
        return False


def sceneplay_dm_guard():
    """Blueprint before_request guard for the ScenePlay controls/tables.

    With the switch off (default) everything stays LAN-open, as it always
    was. With it on, non-DM visitors get a JSON 403 for API/POST calls and
    a login redirect for page views. The TTRPG/auth blueprints never route
    through this guard, so players keep their pages either way."""
    if not dm_only_sceneplay_enabled():
        return None
    from flask_login import current_user
    if current_user.is_authenticated and current_user.is_dm():
        return None
    from flask import request, jsonify, redirect, url_for, flash
    if request.path.startswith('/api/') or request.method != 'GET':
        return jsonify({'error': 'This server restricts ScenePlay to DM '
                        'logins.'}), 403
    flash('That section is DM-only on this server — log in with a DM account.')
    return redirect(url_for('auth.login', next=request.path))

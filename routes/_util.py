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

"""Local thumbnail cache for media metadata.

YouTube thumbnail URLs in tblMediaMetadata are hotlinked — offline boxes (a
Pi at the game table) show broken images even though the metadata is fine.
This module downloads each thumbnail once, shrinks it with Pillow to a small
JPEG, and serves it from static/thumbs/; the API routes prefer the local copy
and fall back to the remote URL.

Deliberately OUTSIDE static/uploads: everything under uploads/ travels in
every backup archive, and thumbnails are derived data — regenerable any time
from the `thumbnail` URLs still stored in tblMediaMetadata — so they must not
re-bloat the archives (see the Pi-sizing discussion in backup_restore.py).
"""
import os
from io import BytesIO

import requests
from PIL import Image

_START_DIR = os.path.dirname(os.path.realpath(__file__))
THUMBS_DIR = os.path.join(_START_DIR, 'static', 'thumbs')


class ThumbnailStore:
    """Fetch → downscale → save pipeline for media thumbnails.

    Files are `<media_type>_<media_id>.jpg`, at most `max_width` px wide,
    quality-reduced JPEG (~5-15 KB vs ~100+ KB for a maxresdefault). The UI
    shows thumbnails at picker/card size, so nothing bigger is ever needed.
    cache() never raises — a dead URL or offline network just means the
    caller keeps the remote fallback."""

    def __init__(self, directory=THUMBS_DIR, max_width=320, quality=78):
        self.directory = directory
        self.max_width = max_width
        self.quality = quality

    def _filename(self, media_type, media_id):
        return f'{media_type}_{int(media_id)}.jpg'

    def path(self, media_type, media_id):
        return os.path.join(self.directory, self._filename(media_type, media_id))

    def exists(self, media_type, media_id):
        return os.path.exists(self.path(media_type, media_id))

    def url(self, media_type, media_id):
        """'/static/thumbs/music_7.jpg' when cached locally, else None.
        (Serving path assumes `directory` lives under static/ — the default.)"""
        if self.exists(media_type, media_id):
            return f'/static/thumbs/{self._filename(media_type, media_id)}'
        return None

    def cache(self, media_type, media_id, remote_url, timeout=20):
        """Download `remote_url`, shrink, save atomically. True on success."""
        if not remote_url:
            return False
        try:
            resp = requests.get(remote_url, timeout=timeout)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            img = img.convert('RGB')   # JPEG can't hold alpha/palette modes
            if img.width > self.max_width:
                height = max(1, round(img.height * self.max_width / img.width))
                img = img.resize((self.max_width, height), Image.Resampling.LANCZOS)
            os.makedirs(self.directory, exist_ok=True)
            target = self.path(media_type, media_id)
            tmp = target + '.tmp'
            img.save(tmp, 'JPEG', quality=self.quality, optimize=True)
            os.replace(tmp, target)
            return True
        except Exception as e:
            print(f'[thumbs] cache failed for {media_type}/{media_id}: {e}')
            return False


store = ThumbnailStore()

from extensions import *

# yt-dlp metadata for one media row. Soft FK: (media_type, media_id) points at
# tblMusic.song_id ('music') or tblVideoMedia.video_ID ('video') — a single
# db.ForeignKey can't span two tables, so this mirrors the app's soft-FK style.


class tblmediametadata(db.Model):
    __tablename__ = 'tblMediaMetadata'
    metadata_id  = db.Column(db.Integer, primary_key=True)
    media_type   = db.Column(db.Text)
    media_id     = db.Column(db.Integer)
    title        = db.Column(db.Text)
    duration     = db.Column(db.Integer)
    uploader     = db.Column(db.Text)
    upload_date  = db.Column(db.Text)
    thumbnail    = db.Column(db.Text)
    view_count   = db.Column(db.Integer)
    description  = db.Column(db.Text)
    categories   = db.Column(db.Text)
    raw_json     = db.Column(db.Text)
    retry_count  = db.Column(db.Integer, default=0)
    last_error   = db.Column(db.Text)
    extracted_at = db.Column(db.Text)
    active       = db.Column(db.Integer, default=1)

    def to_dict(self):
        return {
            'metadata_id': self.metadata_id,
            'media_type': self.media_type,
            'media_id': self.media_id,
            'title': self.title,
            'duration': self.duration,
            'uploader': self.uploader,
            'upload_date': self.upload_date,
            'thumbnail': self.thumbnail,
            'view_count': self.view_count,
            'description': self.description,
            'categories': self.categories,
            'retry_count': self.retry_count,
            'last_error': self.last_error,
            'extracted_at': self.extracted_at,
            'active': self.active,
        }

from extensions import db


class tblTokenPositions(db.Model):
    __tablename__ = 'tblTokenPositions'

    id           = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey('tblSessions.session_id'), nullable=False)
    character_id = db.Column(db.Integer, nullable=True)
    label        = db.Column(db.Text, nullable=False)
    x_pct        = db.Column(db.Float, default=0.0)
    y_pct        = db.Column(db.Float, default=0.0)
    token_type   = db.Column(db.Text, default='player')  # 'player' | 'npc' | 'monster'
    updated_at   = db.Column(db.Text, nullable=False)
    relay_seq    = db.Column(db.Integer, default=0)       # last relay write-seq processed for this token

    session = db.relationship('tblSessions', backref='token_positions', lazy=True)

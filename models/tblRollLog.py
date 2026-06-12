from extensions import db


class tblRollLog(db.Model):
    __tablename__ = 'tblRollLog'

    id          = db.Column(db.Integer, primary_key=True)
    session_id  = db.Column(db.Integer, db.ForeignKey('tblSessions.session_id'), nullable=False)
    player_name = db.Column(db.Text, nullable=False)
    roll_expr   = db.Column(db.Text, nullable=False)
    result      = db.Column(db.Integer, default=0)
    breakdown   = db.Column(db.Text, default='')
    rolled_at   = db.Column(db.Text, nullable=False)

    session = db.relationship('tblSessions', backref='roll_log', lazy=True)

from extensions import db, bcrypt
from flask_login import UserMixin


class tblUsers(UserMixin, db.Model):
    __tablename__ = 'tblUsers'

    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    display_name = db.Column(db.Text, nullable=False)
    role = db.Column(db.Text, nullable=False, default='player')  # 'dm' or 'player'
    active = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.Text, nullable=False)

    # Flask-Login requires get_id() to return a string
    def get_id(self):
        return str(self.user_id)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def is_dm(self):
        return self.role == 'dm'

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'username': self.username,
            'display_name': self.display_name,
            'role': self.role,
            'active': self.active,
        }

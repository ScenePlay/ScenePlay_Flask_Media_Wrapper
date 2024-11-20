from extensions import db

class lutgenre(db.Model):
    genre_id = db.Column(db.Integer, primary_key=True)
    genre = db.Column(db.Text)
    directory = db.Column(db.Text)
    active = db.Column(db.Integer)
    orderBy = db.Column(db.Integer)

    
    def to_dict(self):
        return {
            'genre_id': self.genre_id,
            'genre': self.genre,
            'directory': self.directory,
            'active': self.active,
            'orderBy': self.orderBy
        }
        
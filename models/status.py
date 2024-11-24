from extensions import *

class lutstatus(db.Model):
    pkey = db.Column(db.Integer, primary_key=True)
    status_ID = db.Column(db.Integer)
    status = db.Column(db.Text)

    def to_dict(self):
        return {
            'pkey': self.pkey,
            'status_ID': self.status_ID,
            'status': self.status
        }
        
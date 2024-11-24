from extensions import *

class tblledconfig(db.Model):
    ledConfig_ID = db.Column(db.Integer, primary_key=True)
    pin = db.Column(db.Integer)
    ledCount = db.Column(db.Integer)
    active = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'ledConfig_ID': self.ledConfig_ID,
            'pin': self.pin,
            'ledCount': self.ledCount,
            'active': self.active
        }
        
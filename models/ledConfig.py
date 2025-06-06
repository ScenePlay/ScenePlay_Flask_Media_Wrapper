from extensions import *

class tblledconfig(db.Model):
    ledConfig_ID = db.Column(db.Integer, primary_key=True)
    pin = db.Column(db.Integer)
    ledCount = db.Column(db.Integer)
    brightness = db.Column(db.Float)
    active = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'ledConfig_ID': self.ledConfig_ID,
            'pin': self.pin,
            'ledCount': self.ledCount,
            'brightness': self.brightness,
            'active': self.active
        }
        
from extensions import *

class tblscenepattern(db.Model):
    scenePattern_ID = db.Column(db.Integer, primary_key=True)
    scene_ID = db.Column(db.Integer)
    ledTypeModel_ID = db.Column(db.Integer)
    color = db.Column(db.Text)
    wait_ms = db.Column(db.Integer)
    iterations = db.Column(db.Integer)
    direction = db.Column(db.Integer)
    cdiff = db.Column(db.Text)
    orderBy = db.Column(db.Integer)
    outPin = db.Column(db.Integer)
    brightness = db.Column(db.Float)
        
    def to_dict(self):
        return {
            'scenePattern_ID': self.scenePattern_ID,
            'scene_ID': self.scene_ID,
            'ledTypeModel_ID': self.ledTypeModel_ID,
            'color': self.color,
            'wait_ms': self.wait_ms,
            'iterations' : self.iterations,
            'direction': self.direction,
            'cdiff': self.cdiff,
            'orderBy': self.orderBy,
            'outPin': self.outPin,
            'brightness': self.brightness
        }
        

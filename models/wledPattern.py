from extensions import db

class tblwledpattern(db.Model):
    wledPattern_ID = db.Column(db.Integer, primary_key=True)
    scene_ID = db.Column(db.Integer)
    server_ID = db.Column(db.Integer)
    effect = db.Column(db.Integer)
    pallette = db.Column(db.Integer)
    color1= db.Column(db.Text)
    color2 = db.Column(db.Text)
    color3 = db.Column(db.Text)
    speed = db.Column(db.Integer)
    brightness = db.Column(db.Integer)
    orderBy = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'wledPattern_ID': self.wledPattern_ID,
            'scene_ID': self.scene_ID,
            'server_ID': self.server_ID,
            'effect': self.effect,
            'pallette': self.pallette,
            'color1': self.color1,
            'color2': self.color2,
            'color3': self.color3,
            'speed': self.speed,
            'brightness': self.brightness,
            'orderBy': self.orderBy
        }
        
class tbleffect(db.Model):
    effect_ID = db.Column(db.Integer, primary_key=True)
    effectName = db.Column(db.Text)
    ef_ID = db.Column(db.Integer)

    def to_dict(self):
        return {
            'effect_ID': self.effect_ID,
            'effectName': self.effectName,
            'ef_ID': self.ef_ID
        }
class tblpallette(db.Model):
    pallette_ID = db.Column(db.Integer, primary_key=True)
    palletteName = db.Column(db.Text)
    pa_ID = db.Column(db.Integer)

    def to_dict(self):
        return {
            'pallette_ID': self.pallette_ID,
            'palletteName': self.palletteName,
            'pa_ID': self.pa_ID
        }
from extensions import *

class tblscenes(db.Model):
    scene_ID = db.Column(db.Integer, primary_key=True)
    sceneName = db.Column(db.Text)
    active = db.Column(db.Integer)
    orderBy = db.Column(db.Integer)
    campaign_id = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'scene_ID': self.scene_ID,
            'sceneName': self.sceneName,
            'active': self.active,
            'orderBy': self.orderBy,
            'campaign_id': self.campaign_id
        }
        

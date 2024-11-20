from extensions import db

# cid  name              type     notnull  dflt_value  pk
# ---  ----------------  -------  -------  ----------  --
# 0    videoScene_ID     INTEGER  0                    1 
# 1    scene_ID          INT      0                    0 
# 2    video_ID          INT      0                    0 
# 3    DisplayScreen_ID  INT      0                    0 
# 4    orderBy           INT      0                    0 
# 5    volume            INT      0                    0 

class tblvideoscene(db.Model):
    videoScene_ID = db.Column(db.Integer, primary_key=True)
    scene_ID = db.Column(db.Integer)
    video_ID = db.Column(db.Integer)
    DisplayScreen_ID = db.Column(db.Integer)
    orderBy = db.Column(db.Integer)
    volume = db.Column(db.Integer)
    loops = db.Column(db.Integer)

    
    def to_dict(self):
        return {
            'videoScene_ID': self.videoScene_ID,
            'scene_ID': self.scene_ID,
            'video_ID': self.video_ID,
            'DisplayScreen_ID': self.DisplayScreen_ID,
            'orderBy': self.orderBy,
            'volume': self.volume,
            'loops': self.loops
        }
        

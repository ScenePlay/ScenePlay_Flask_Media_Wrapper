from extensions import *

# cid  name           type     notnull  dflt_value  pk
# ---  -------------  -------  -------  ----------  --
# 0    musicScene_ID  INTEGER  0                    1 
# 1    scene_ID       INT      0                    0 
# 2    song_ID        INT      0                    0 
# 3    orderBy        INT      0                    0 
# 4    volume         INTEGER  0                    0 

class tblmusicscene(db.Model):
    musicScene_ID = db.Column(db.Integer, primary_key=True)
    scene_ID = db.Column(db.Integer)
    song_ID = db.Column(db.Integer)
    orderBy = db.Column(db.Integer)
    volume = db.Column(db.Integer)

    
    def to_dict(self):
        return {
            'musicScene_ID': self.musicScene_ID,
            'scene_ID': self.scene_ID,
            'song_ID': self.song_ID,
            'orderBy': self.orderBy,
            'volume': self.volume
        }
        

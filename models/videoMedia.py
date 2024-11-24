from extensions import *

# ---  ------------  -------  -------  ----------  --
# 0    video_ID      INTEGER  0                    1 
# 1    path          TEXT     0                    0 
# 2    title         TEXT     0                    0 
# 3    pTimes        INT      0                    0 
# 4    playedDTTM    TEXT     0                    0 
# 5    active        INT      0                    0 
# 6    genre         INT      0                    0 
# 7    que           INT      0                    0 
# 8    urlSource     TEXT     0                    0 
# 9    dnLoadStatus  INT      0                    0 


class tblvideomedia(db.Model):
    video_id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.Text)
    title = db.Column(db.Text)
    pTimes = db.Column(db.Integer)
    playedDTTM = db.Column(db.Text)
    active = db.Column(db.Integer)
    genre = db.Column(db.Integer)
    que = db.Column(db.Integer)
    urlSource = db.Column(db.Text)
    dnLoadStatus = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'video_ID': self.video_id,
            'path': self.path,
            'title': self.title,
            'pTimes': self.pTimes,
            'playedDTTM': self.playedDTTM,
            'active' : self.active,
            'genre': self.genre,
            'que': self.que,
            'urlSource': self.urlSource,
            'dnLoadStatus': self.dnLoadStatus
        }
        
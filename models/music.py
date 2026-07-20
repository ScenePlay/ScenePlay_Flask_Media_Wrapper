from extensions import *

class tblmusic(db.Model):
    song_id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.Text)
    song = db.Column(db.Text)
    pTimes = db.Column(db.Integer)
    playedDTTM = db.Column(db.Text)
    active = db.Column(db.Integer)
    genre = db.Column(db.Integer)
    que = db.Column(db.Integer)
    urlSource = db.Column(db.Text)
    dnLoadStatus = db.Column(db.Integer)
    videoId = db.Column(db.Text)
    displayName = db.Column(db.Text)
    metaStatus = db.Column(db.Integer)
    metaNextRetry = db.Column(db.Text)
    dnLastError = db.Column(db.Text)

    def to_dict(self):
        return {
            'song_ID': self.song_id,
            'path': self.path,
            'song': self.song,
            'pTimes': self.pTimes,
            'playedDTTM': self.playedDTTM,
            'active' : self.active,
            'genre': self.genre,
            'que': self.que,
            'urlSource': self.urlSource,
            'dnLoadStatus': self.dnLoadStatus,
            'videoId': self.videoId,
            'displayName': self.displayName,
            'metaStatus': self.metaStatus,
            'dnLastError': self.dnLastError
        }
        
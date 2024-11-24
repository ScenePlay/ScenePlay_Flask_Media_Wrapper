from extensions import *

# 0    ServerIP_ID   INTEGER  0                    1 
# 1    serverName    TEXT     0                    0 
# 2    ipAddress     TEXT     0                    0 
# 3    ports         TEXT     0                    0 
# 4    active        INT      0                    0 
# 5    PingTime      TEXT     0                    0 
# 6    serverroleid  INT      0                    0 


class tblserversip(db.Model):
    ServerIP_ID = db.Column(db.Integer, primary_key=True)
    serverName = db.Column(db.Text)
    ipAddress = db.Column(db.Text)
    ports = db.Column(db.Text)
    active = db.Column(db.Integer)
    PingTime = db.Column(db.Text)
    serverroleid = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'ServerIP_ID': self.ServerIP_ID,
            'serverName': self.serverName,
            'ipAddress': self.ipAddress,
            'ports': self.ports,
            'active': self.active,
            'PingTime' : self.PingTime,
            'serverroleid': self.serverroleid
        }
        

from extensions import db

# 0|ID|INTEGER|0||1
# 1|name|TEXT|0||0
# 2|active|INT|0||0
# 3|orderBy|INT|0||0

class tblserverrole(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text)
    active = db.Column(db.Integer)
    orderBy = db.Column(db.Integer)
    
    def to_dict(self):
        return {
            'ID': self.ID,
            'name': self.name,
            'active': self.active,
            'orderBy': self.orderBy
        }
        

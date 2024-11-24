from extensions import *

class tblledtypemodel(db.Model):
    ledTypeModel_ID = db.Column(db.Integer, primary_key=True)
    modelName = db.Column(db.Text)
    ledJSON = db.Column(db.Text)
    
    def to_dict(self):
        return {
            'ledTypeModel_ID': self.ledTypeModel_ID,
            'modelName': self.modelName,
            'ledJSON': self.ledJSON
        }
        

from extensions import *

class tblcampaigns(db.Model):
    campaign_id = db.Column(db.Integer, primary_key=True)
    campaign_name = db.Column(db.Text)
    active = db.Column(db.Integer)
    order_by = db.Column(db.Text)
    
    def to_dict(self):
        return {
            'campaign_id': self.campaign_id,
            'campaign_name': self.campaign_name,
            'active': self.active,
            'order_by': self.order_by
        }
        

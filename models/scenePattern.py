import json

from extensions import *


class tblscenepattern(db.Model):
    """One RPiLED pattern in a scene. `patternType` is a key in
    led_patterns.PATTERNS; `params` is the JSON dict of that pattern's
    generic parameters (see led_patterns.coerce)."""
    scenePattern_ID = db.Column(db.Integer, primary_key=True)
    scene_ID = db.Column(db.Integer)
    patternType = db.Column(db.Text)
    params = db.Column(db.Text)
    orderBy = db.Column(db.Integer)

    def params_dict(self):
        try:
            d = json.loads(self.params or '{}')
        except (TypeError, ValueError):
            d = {}
        return d if isinstance(d, dict) else {}

    def to_dict(self):
        return {
            'scenePattern_ID': self.scenePattern_ID,
            'scene_ID': self.scene_ID,
            'patternType': self.patternType,
            'params': self.params_dict(),
            'orderBy': self.orderBy,
        }

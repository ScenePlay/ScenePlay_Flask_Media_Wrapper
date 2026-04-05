from extensions import *

# cid  name          type     notnull  dflt_value  pk
# ---  ------------  -------  -------  ----------  --
# 0    schedule_id   INTEGER  0                    1
# 1    name          TEXT     0                    0
# 2    minute        TEXT     0                    0
# 3    hour          TEXT     0                    0
# 4    day_of_month  TEXT     0                    0
# 5    month         TEXT     0                    0
# 6    day_of_week   TEXT     0                    0
# 7    command       TEXT     0                    0
# 8    description   TEXT     0                    0
# 9    active        INT      0                    0


class tblcronschedule(db.Model):
    __tablename__ = 'tblCronSchedule'
    schedule_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text)
    minute = db.Column(db.Text)
    hour = db.Column(db.Text)
    day_of_month = db.Column(db.Text)
    month = db.Column(db.Text)
    day_of_week = db.Column(db.Text)
    command = db.Column(db.Text)
    description = db.Column(db.Text)
    active = db.Column(db.Integer)

    def to_dict(self):
        return {
            'schedule_id': self.schedule_id,
            'name': self.name,
            'minute': self.minute,
            'hour': self.hour,
            'day_of_month': self.day_of_month,
            'month': self.month,
            'day_of_week': self.day_of_week,
            'command': self.command,
            'description': self.description,
            'active': self.active,
        }

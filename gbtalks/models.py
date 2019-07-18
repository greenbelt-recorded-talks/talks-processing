from . import db

class Talk(db.Model):
    __tablename__ = 'talks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String)
    description = db.Column(db.String)
    speaker =  db.Column(db.String)

    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)

    venue = db.Column(db.String)

    recorder_name = db.Column(db.String, db.ForeignKey('recorders.name'))

    def __repr__(self):
        return "<Talk(id='%d', title='%s', description='%s')>" % (self.id, self.title, self.description)


class Recorder(db.Model):
    __tablename__ = 'recorders'

    name = db.Column(db.String, primary_key=True)
    max_shifts_per_day = db.Column(db.Integer)

    talks = db.relationship("Talk", backref="recorded_by")




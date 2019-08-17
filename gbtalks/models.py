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

    is_priority = db.Column(db.Boolean)

    recorder_name = db.Column(db.String, db.ForeignKey('recorders.name'))
    editor_name = db.Column(db.String, db.ForeignKey('editors.name'))

    def __repr__(self):
        return "<Talk(id='%d', title='%s', description='%s', start_time='%s', end_time='%s', venue='%s', recorder_name='%s', priority='%s')>" % (self.id, self.title, self.description, self.start_time, self.end_time, self.venue, self.recorder_name, self.is_priority)


class Recorder(db.Model):
    __tablename__ = 'recorders'

    name = db.Column(db.String, primary_key=True)
    max_shifts_per_day = db.Column(db.Integer)
    can_record_in_red_tent = db.Column(db.Boolean)

    talks = db.relationship("Talk", backref="recorded_by", order_by="Talk.start_time")


class Editor(db.Model):
    __tablename__ = 'editors'

    name = db.Column(db.String, primary_key=True)
    talks = db.relationship("Talk", backref="edited_by", order_by="Talk.start_time")

from . import db

from sqlalchemy.ext.hybrid import hybrid_property


class Talk(db.Model):
    __tablename__ = "talks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String)
    description = db.Column(db.String)
    speaker = db.Column(db.String)

    day = db.Column(db.String)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)

    venue = db.Column(db.String)

    is_priority = db.Column(db.Boolean)
    is_rotaed = db.Column(db.Boolean)
    is_cleared = db.Column(db.Boolean)
    
    has_explicit_warning_sticker = db.Column(db.Boolean)
    has_distressing_content_warning_sticker = db.Column(db.Boolean)
    has_technical_issues_sticker = db.Column(db.Boolean)
    has_copyright_removal_sticker = db.Column(db.Boolean)

    notes_photo = db.Column(db.LargeBinary)

    recorder_name = db.Column(db.String, db.ForeignKey("recorders.name"))
    editor_name = db.Column(db.String, db.ForeignKey("editors.name"))

    def __repr__(self):
        return (
            "<Talk(id='%d', title='%s', description='%s', day='%s', start_time='%s', end_time='%s', venue='%s', recorder_name='%s', cleared='%s', explicit='%s', distressing='%s', technical_issues='%s', copyright_removal='%s')>"
            % (
                self.id,
                self.title,
                self.description,
                self.day,
                self.start_time,
                self.end_time,
                self.venue,
                self.recorder_name,
                self.is_cleared,
                self.has_explicit_warning_sticker,
                self.has_distressing_content_warning_sticker,
                self.has_technical_issues_sticker,
                self.has_copyright_removal_sticker,
            )
        )


class Recorder(db.Model):
    __tablename__ = "recorders"

    name = db.Column(db.String, primary_key=True)
    max_shifts_per_day = db.Column(db.Integer)

    talks = db.relationship("Talk", backref="recorded_by", order_by="Talk.start_time")

    def __repr__(self):
        return (
            "<Recorder(name='%s', max_shifts_per_day='%d', number_of_talks='%d'))>"
            % (self.name, self.max_shifts_per_day, len(self.talks))
        )


class Editor(db.Model):
    __tablename__ = "editors"

    name = db.Column(db.String, primary_key=True)
    talks = db.relationship("Talk", backref="edited_by", order_by="Talk.start_time")


class RotaSettings(db.Model):
    __tablename__ = "rota_settings"
    
    key = db.Column(db.String, primary_key=True)
    value = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String)
    unit = db.Column(db.String)  # e.g., "hours", "minutes", "talks"
    
    @staticmethod
    def get_value(key, default=None):
        """Get a rota setting value, returning default if not found"""
        setting = RotaSettings.query.filter_by(key=key).first()
        return setting.value if setting else default
    
    @staticmethod
    def set_value(key, value, description=None, unit=None):
        """Set a rota setting value, creating or updating as needed"""
        setting = RotaSettings.query.filter_by(key=key).first()
        if setting:
            setting.value = int(value)
            if description:
                setting.description = description
            if unit:
                setting.unit = unit
        else:
            setting = RotaSettings(
                key=key, 
                value=int(value), 
                description=description, 
                unit=unit
            )
            db.session.add(setting)
        db.session.commit()
        return setting
    
    @staticmethod
    def initialize_defaults():
        """Initialize default rota settings if they don't exist"""
        defaults = {
            'shift_length': (3, 'Maximum duration of a recording shift', 'hours'),
            'break_between_shifts': (2, 'Minimum break required between shifts', 'hours'),
            'minimum_time_between_talks': (20, 'Minimum gap between consecutive talks', 'minutes'),
            'max_talks_per_shift': (2, 'Maximum number of talks per shift', 'talks'),
            'max_shifts_per_day_limit': (2, 'Maximum shifts per day (cannot exceed 3)', 'shifts'),
            'same_venue_assignment_window': (3, 'Time window to assign same-venue talks to same recorder', 'hours'),
            'additional_talk_search_window': (1, 'Time window to search for additional talks to fill shifts', 'hours'),
            'additional_talk_minimum_gap': (20, 'Minimum gap before considering additional talks', 'minutes'),
        }
        
        for key, (default_value, description, unit) in defaults.items():
            existing = RotaSettings.query.filter_by(key=key).first()
            if not existing:
                RotaSettings.set_value(key, default_value, description, unit)
    
    @staticmethod
    def get_all_settings():
        """Get all rota settings as a dictionary"""
        settings = {}
        for setting in RotaSettings.query.all():
            settings[setting.key] = {
                'value': setting.value,
                'description': setting.description,
                'unit': setting.unit
            }
        return settings


### Models for Google login

from flask_login import LoginManager, UserMixin
from flask_dance.consumer.storage.sqla import OAuthConsumerMixin


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(256), unique=True)


class OAuth(OAuthConsumerMixin, db.Model):
    provider_user_id = db.Column(db.String(256), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id), nullable=False)
    user = db.relationship(User)


# setup login manager
login_manager = LoginManager()
login_manager.login_view = "google.login"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

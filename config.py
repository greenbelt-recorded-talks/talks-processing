import os
from datetime import datetime

class Config:
    """Set Flask configuration vars from .env file."""

    # General
    TESTING = os.getenv("TESTING")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG")
    SECRET_KEY = os.getenv('SECRET_KEY')

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:///gbtalks.sqlite")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Files
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/storage/uploads")
    PROCESSED_DIR = os.getenv("PROCESSED_DIR", "/storage/processed")
    CD_DIR = os.getenv("CD_DIR", "/storage/cds")
    IMG_DIR = os.getenv("IMG_DIR", "/storage/images")
    USB_GOLD_DIR = os.getenv("USB_GOLD_DIR", "/usb_gold")
    WEB_MP3_DIR = os.getenv("WEB_MP3_DIR", "/storage/web_mp3s")


    TALKS_DIRS = {
        "raw": {
            "directory": UPLOAD_DIR,
            "suffix": "_RAW"
            },
        "edited":{
            "directory": UPLOAD_DIR,
            "suffix": "_EDITED"
            },
        "processed": {
            "directory": PROCESSED_DIR,
            "suffix": "mp3"
            }
    }

    # Greenbelt - Default to Friday of August Bank Holiday weekend of current year
    current_year = datetime.now().year
    # August bank holiday is last Monday of August, so Friday is 3 days before
    august_last_monday = datetime(current_year, 8, 31)
    while august_last_monday.weekday() != 0:  # Find last Monday
        august_last_monday = august_last_monday.replace(day=august_last_monday.day - 1)
    default_gb_friday = august_last_monday.replace(day=august_last_monday.day - 3)
    GB_FRIDAY = os.getenv("GB_FRIDAY", default_gb_friday.strftime("%Y-%m-%d"))
    GB_SHORT_YEAR = GB_FRIDAY[2:4]

    # Login

    GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

    # Team leaders perms (update on server)

    TEAM_LEADERS_EMAILS = {'gb-talks-onsite@greenbelt.org.uk','rob@redpath.family', 'recordedtalks@greenbelt.org.uk'}

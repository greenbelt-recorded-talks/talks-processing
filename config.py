import os

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
    TOP_TAIL_DIR = os.getenv("TOP_TAIL_DIR", "/home/gbtalks/top_tail")
    IMG_DIR = os.getenv("IMG_DIR", "/storage/images")
    USB_GOLD_DIR = os.getenv("USB_GOLD_DIR", "/home/gbtalks/usb_gold")

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

    # Greenbelt
    GB_FRIDAY = "2023-08-25"
    GB_SHORT_YEAR = GB_FRIDAY[2:4]

    # Login

    GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

    # Team leaders perms (update on server)

    TEAM_LEADERS_EMAILS = {'gb-talks-onsite@greenbelt.org.uk','rob@redpath.family', 'recordedtalks@greenbelt.org.uk'}

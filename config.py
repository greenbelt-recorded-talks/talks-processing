import os

class Config:
    """Set Flask configuration vars from .env file."""

    # General
    TESTING = os.getenv("TESTING")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG")
    SECRET_KEY = os.getenv('SECRET_KEY')

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:///gbtalks.sqlite")
    SQLALCHEMY_TRACK_MODIFICATIONS = os.getenv("SQLALCHEMY_TRACK_MODIFICATIONS")

    # Files
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/storage/uploads")
    RAW_UPLOAD_DIR = os.getenv("RAW_UPLOAD_DIR", "/storage/uploads")
    EDITED_UPLOAD_DIR = os.getenv("EDITED_UPLOAD_DIR", "/storage/uploads")
    PROCESSED_DIR = os.getenv("PROCESSED_DIR", "/storage/processed")
    CD_DIR = os.getenv("CD_DIR", "/storage/cds")
    SNIP_DIR = os.getenv("SNIP_DIR", "/storage/processed")
    TOP_TAIL_DIR = os.getenv("TOP_TAIL_DIR", "/home/gbtalks/top_tail")
    IMG_DIR = os.getenv("IMG_DIR", "/home/gbtalks/images")
    USB_GOLD_DIR = os.getenv("USB_GOLD_DIR", "/home/gbtalks/usb_gold")

    TALKS_DIRS = {
        "raw": {
            "directory": RAW_UPLOAD_DIR,
            "suffix": "_RAW"
            },
        "edited":{
            "directory": EDITED_UPLOAD_DIR,
            "suffix": "_EDITED"
            },
        "processed": {
            "directory": PROCESSED_DIR,
            "suffix": "mp3"
            },
        "snip": {
            "directory": SNIP_DIR,
            "suffix": "_SNIP"
            }
    }

    # Greenbelt
    GB_FRIDAY = "2022-08-26"
    GB_SHORT_YEAR = GB_FRIDAY[2:4]

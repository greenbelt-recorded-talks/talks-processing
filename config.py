import os

class Config:
    """Set Flask configuration vars from .env file."""

    # General
    TESTING = os.getenv("TESTING") 
    FLASK_DEBUG = os.getenv("FLASK_DEBUG")
    SECRET_KEY = os.getenv('SECRET_KEY')

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI")
    SQLALCHEMY_DATABASE_URI = "sqlite:///gbtalks.sqlite"
    SQLALCHEMY_TRACK_MODIFICATIONS = os.getenv("SQLALCHEMY_TRACK_MODIFICATIONS")

    # Files
    UPLOAD_DIR = "/storage/uploads"
    RAW_UPLOAD_DIR = "/storage/uploads"
    EDITED_UPLOAD_DIR = "/storage/uploads"
    PROCESSED_DIR = "/storage/processed"
    CD_DIR = "/storage/cds"
    SNIP_DIR = "/storage/processed"
    TOP_TAIL_DIR = "/home/gbtalks/top_tail"
    IMG_DIR = "/home/gbtalks/images"

    TALKS_DIRS = {
        "raw": {
            "directory": "/storage/uploads",
            "suffix": "_RAW"
            },
        "edited":{
            "directory": "/storage/uploads",
            "suffix": "_EDITED"
            },
        "processed": {
            "directory": "/storage/processed",
            "suffix": "mp3"
            },
        "snip": {
            "directory": "/storage/processed",
            "suffix": "_SNIP"
            }
    }

    # Greenbelt
    GB_FRIDAY = "2022-08-26"
    GB_SHORT_YEAR = GB_FRIDAY[2:4]

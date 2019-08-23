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

    # Greenbelt
    GB_FRIDAY = "2019-08-23"

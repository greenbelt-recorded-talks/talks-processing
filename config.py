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
    UPLOAD_DIR = "/tmp"
    RAW_UPLOAD_DIR = "/tmp"
    EDITED_UPLOAD_DIR = "/tmp"
    PROCESSED_DIR = "/tmp"
    SNIP_DIR = "/tmp"

    # Greenbelt
    GB_FRIDAY = "2019-08-23"

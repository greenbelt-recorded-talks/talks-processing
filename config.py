import os

from festival_dates import default_gb_friday


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
    USB_GOLD_DIR = os.getenv("USB_GOLD_DIR", "/storage/usb_gold")
    WEB_MP3_DIR = os.getenv("WEB_MP3_DIR", "/storage/web_mp3s")
    BACKUP_DIR = os.getenv("BACKUP_DIR", "/storage/backups")


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

    # Greenbelt - the Friday of the August Bank Holiday weekend, worked out
    # from the calendar so a year nobody rolled over still lands on the right
    # dates. Setting GB_FRIDAY in .env overrides it; leaving it unset is the
    # normal case. Read once, when this class body executes, so a change to
    # either the pin or the calendar needs a restart to be picked up - the
    # default only moves at New Year, when nothing is running on site.
    GB_FRIDAY = os.getenv("GB_FRIDAY") or default_gb_friday()
    GB_SHORT_YEAR = GB_FRIDAY[2:4]

    # The .env the setup page's festival-year control writes to. Defaults to
    # the deployed checkout, which is the only place it means anything on the
    # festival server; overridable so the tests are not editing the real one.
    ENV_FILE = os.getenv("ENV_FILE", os.path.expanduser("~/talks-processing/.env"))

    # Cover art
    # Embedded in every processed MP3, so it is worth keeping small. Uploads
    # are resized to this square regardless of what was handed in.
    COVER_ART_SIZE = int(os.getenv("COVER_ART_SIZE", "300"))

    # Audio levels
    # The loudness every finished talk is aimed at, and the peak ceiling it
    # must not cross. These are the figures convert-talks normalises to, and
    # the same pair the health check measures top.mp3 and tail.mp3 against -
    # a jingle that sits well off this target is audibly wrong against the
    # speech it is bolted to, and only shows up once the MP3s are cut.
    AUDIO_TARGET_LUFS = float(os.getenv("AUDIO_TARGET_LUFS", "-13"))
    AUDIO_TRUE_PEAK_DBTP = float(os.getenv("AUDIO_TRUE_PEAK_DBTP", "-2"))

    # How far off target a file may sit before the health check mentions it.
    # Loudness measurement of a clip only a few seconds long is not accurate
    # to a fraction of a LU, and nobody can hear 1 LU on a jingle anyway.
    AUDIO_LEVEL_TOLERANCE_LU = float(os.getenv("AUDIO_LEVEL_TOLERANCE_LU", "1"))

    # Deployment environment
    # PythonAnywhere sets these in web workers and consoles alike; nothing on
    # the on-site box does, so their absence is what "bare metal" looks like.
    # DEPLOYMENT_ENV overrides the guess for the awkward cases - a laptop
    # standing in for the festival server, or a staging site on PythonAnywhere.
    _ON_PYTHONANYWHERE = bool(
        os.getenv("PYTHONANYWHERE_DOMAIN") or os.getenv("PYTHONANYWHERE_SITE")
    )
    DEPLOYMENT_ENV = os.getenv(
        "DEPLOYMENT_ENV", "cloud" if _ON_PYTHONANYWHERE else "onsite"
    )

    # Login

    GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

    # Team leaders perms (update on server)

    TEAM_LEADERS_EMAILS = {'gb-talks-onsite@greenbelt.org.uk','rob@redpath.family', 'recordedtalks@greenbelt.org.uk'}

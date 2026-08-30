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

    # Hand large files to nginx (X-Accel-Redirect) instead of pushing them
    # through uWSGI. See send_stored_file in libgbtalks.py for what this buys
    # and why it is off by default: it only works behind an nginx carrying the
    # matching internal locations, so nothing may assume it. The festival
    # server turns it on in its systemd unit, which is exactly the process
    # that runs behind that nginx; the dev server, the tests and
    # PythonAnywhere leave it off and get send_file.
    X_ACCEL_REDIRECT = os.getenv("X_ACCEL_REDIRECT", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    # One place the whole pipeline agrees on: convert-talks normalises every
    # talk to these, and the health check measures top.mp3 and tail.mp3
    # against the same figures. They were three literals in the middle of an
    # ffmpeg-normalize argument list, which is how the loudness range target
    # came to be asking for something no talk has ever been able to give.
    #
    # -16 LUFS is the usual figure for spoken word. Up to GB26 this archive
    # sat at -13, so this year's talks are quieter than every previous year's
    # - a deliberate change, not a tidy-up. -13 was chosen for playback in a
    # car, and the cost of it was a loudness range target of 3 against
    # material measuring 8 to 11, which the loudnorm filter can only meet by
    # riding the gain 3-4 dB throughout. At -16 with a reachable range target
    # that movement drops to well under 1 dB on most talks.
    AUDIO_TARGET_LUFS = float(os.getenv("AUDIO_TARGET_LUFS", "-16"))
    AUDIO_TRUE_PEAK_DBTP = float(os.getenv("AUDIO_TRUE_PEAK_DBTP", "-1.5"))

    # Deliberately above the loudness range of any talk we have measured, so
    # the filter is never asked to compress the life out of one to hit it.
    # Lower this and you are asking for compression; that is what it is for.
    AUDIO_LOUDNESS_RANGE_LU = float(os.getenv("AUDIO_LOUDNESS_RANGE_LU", "11"))

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

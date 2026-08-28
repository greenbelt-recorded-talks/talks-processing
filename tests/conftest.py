"""Shared pytest fixtures.

config.Config reads os.environ at class-definition time, which happens on the
first import of the config module. Every environment variable the tests rely on
therefore has to be set here, at module scope, before gbtalks is imported.
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path

# The suite is dominated by SQLite commits - the db fixture drops and recreates
# every table per test, and each commit costs an fsync. Landing those on a
# spinning disk is what makes the suite take minutes on the festival server, so
# put the database and the temp storage dirs on tmpfs where the machine has
# one. Falls back to the normal temp dir anywhere that does not (macOS).
_TMPFS = Path("/dev/shm")
_TEST_ROOT = Path(
    tempfile.mkdtemp(
        prefix="gbtalks-tests-",
        dir=_TMPFS if _TMPFS.is_dir() and os.access(_TMPFS, os.W_OK) else None,
    )
)

# A year where the last Monday in August is the 31st, so the Friday before it
# falls in the same month. Pinned so date-dependent assertions stay stable.
TEST_GB_FRIDAY = "2026-08-28"
TEAM_LEADER_EMAIL = "team-leader@example.test"

os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_TEST_ROOT / 'test.sqlite'}"
os.environ["GB_FRIDAY"] = TEST_GB_FRIDAY
# The festival-year control rewrites this file, so it must not be the real one.
os.environ["ENV_FILE"] = str(_TEST_ROOT / "dotenv")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")

for _var, _subdir in [
    ("UPLOAD_DIR", "uploads"),
    ("PROCESSED_DIR", "processed"),
    ("CD_DIR", "cds"),
    ("IMG_DIR", "images"),
    ("USB_GOLD_DIR", "usb_gold"),
    ("WEB_MP3_DIR", "web_mp3s"),
    ("BACKUP_DIR", "backups"),
]:
    _path = _TEST_ROOT / _subdir
    _path.mkdir(parents=True, exist_ok=True)
    os.environ[_var] = str(_path)

import pytest  # noqa: E402

from gbtalks import create_app  # noqa: E402
from gbtalks import db as _db
from gbtalks.models import Editor, Recorder, RotaSettings, Talk, User  # noqa: E402


@pytest.fixture(scope="session")
def app():
    """The Flask application, built once for the whole test session."""
    application = create_app()
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        # The decorator reads this at request time, so injecting here is enough
        # to let the test user through the team-leader gate.
        TEAM_LEADERS_EMAILS={TEAM_LEADER_EMAIL},
    )
    return application


@pytest.fixture
def app_ctx(app):
    """An application context, for helpers that read current_app.config."""
    with app.app_context():
        yield app


@pytest.fixture
def db(app):
    """A clean database for each test."""
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        RotaSettings.initialize_defaults()
        yield _db
        _db.session.remove()


@pytest.fixture
def client(app, db):
    """An unauthenticated test client."""
    return app.test_client()


@pytest.fixture
def auth_client(app, db):
    """A test client logged in as a user with team-leader permissions."""
    user = User(email=TEAM_LEADER_EMAIL)
    db.session.add(user)
    db.session.commit()

    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return test_client


# --- Data factories -------------------------------------------------------


@pytest.fixture
def make_talk(db):
    """Create a Talk. Times are given as (day, "HH:MM") in Greenbelt terms."""

    def _make_talk(
        talk_id=None,
        title="A Talk About Things",
        speaker="Sam Speaker",
        day="Saturday",
        start="10:00",
        end="11:00",
        venue="The Big Top",
        **kwargs,
    ):
        from gbtalks.libgbtalks import gb_time_to_datetime

        talk = Talk(
            id=talk_id,
            title=title,
            speaker=speaker,
            description="A description",
            day=day,
            start_time=gb_time_to_datetime(day, start),
            end_time=gb_time_to_datetime(day, end),
            venue=venue,
            **kwargs,
        )
        db.session.add(talk)
        db.session.commit()
        return talk

    return _make_talk


@pytest.fixture
def make_recorder(db):
    def _make_recorder(name="Robin Recorder", max_shifts_per_day=2, **kwargs):
        recorder = Recorder(name=name, max_shifts_per_day=max_shifts_per_day, **kwargs)
        db.session.add(recorder)
        db.session.commit()
        return recorder

    return _make_recorder


@pytest.fixture
def make_editor(db):
    def _make_editor(name="Eddie Editor"):
        editor = Editor(name=name)
        db.session.add(editor)
        db.session.commit()
        return editor

    return _make_editor


@pytest.fixture
def gb_friday():
    """The pinned Greenbelt Friday as a date object."""
    return datetime.strptime(TEST_GB_FRIDAY, "%Y-%m-%d").date()

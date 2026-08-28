"""Moving the database between the cloud and on-site deployments.

These tests replace the file the test suite itself is running on, so each one
restores it afterwards - see the `live_database` fixture.
"""

import io
import os
import shutil
import sqlite3

import pytest

from gbtalks.models import Talk


@pytest.fixture
def live_database(app_ctx, db, tmp_path):
    """The path of the database under test, put back as it was afterwards.

    The upload route replaces this file, and the suite's engine is
    session-scoped, so without the restore every later test would be looking
    at whatever a test here happened to install.
    """
    from gbtalks.routes import database_path

    path = database_path()
    assert path is not None

    keep = tmp_path / "original.sqlite"
    shutil.copy(path, keep)

    yield path

    db.engine.dispose()
    shutil.copy(keep, path)
    db.engine.dispose()


def make_database(path, talk_title="Imported Talk", talk_id=901):
    """A valid gbtalks database, built by the app's own create_all."""
    from gbtalks import db as _db

    source = _db.engine.url.database
    shutil.copy(source, path)

    connection = sqlite3.connect(path)
    try:
        connection.execute("DELETE FROM talks")
        connection.execute(
            "INSERT INTO talks (id, title, speaker, day, venue) VALUES (?, ?, ?, ?, ?)",
            (talk_id, talk_title, "Sam Speaker", "Saturday", "The Big Top"),
        )
        connection.commit()
    finally:
        connection.close()

    return path


def upload(client, content, filename="incoming.sqlite", confirm="yes"):
    data = {"file": (io.BytesIO(content), filename)}
    if confirm is not None:
        data["confirm"] = confirm
    return client.post("/upload_database", data=data, content_type="multipart/form-data")


class TestDownloadDatabase:
    def test_serves_a_usable_sqlite_database(self, auth_client, live_database, make_talk, tmp_path):
        make_talk(talk_id=7, title="A Talk To Carry Over")

        response = auth_client.get("/download_database")

        assert response.status_code == 200
        assert response.data.startswith(b"SQLite format 3\x00")

        downloaded = tmp_path / "downloaded.sqlite"
        downloaded.write_bytes(response.data)

        connection = sqlite3.connect(downloaded)
        try:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            titles = [row[0] for row in connection.execute("SELECT title FROM talks")]
        finally:
            connection.close()

        assert titles == ["A Talk To Carry Over"]

    def test_is_offered_as_a_named_attachment(self, auth_client, live_database):
        response = auth_client.get("/download_database")

        disposition = response.headers["Content-Disposition"]
        assert disposition.startswith("attachment;")
        assert ".sqlite" in disposition

    def test_needs_a_team_leader(self, client, db):
        response = client.get("/download_database")

        assert response.status_code == 302


class TestUploadDatabase:
    def test_replaces_the_talks(self, auth_client, live_database, make_talk, tmp_path):
        make_talk(talk_id=1, title="The Talk That Is Here Now")
        incoming = make_database(tmp_path / "incoming.sqlite", talk_title="The Talk That Arrives")

        response = upload(auth_client, incoming.read_bytes())

        assert response.status_code == 302
        titles = [t.title for t in Talk.query.all()]
        assert titles == ["The Talk That Arrives"]

    def test_saves_the_database_it_overwrote(self, auth_client, live_database, make_talk, tmp_path):
        make_talk(talk_id=1, title="The Talk That Is Here Now")
        incoming = make_database(tmp_path / "incoming.sqlite")

        upload(auth_client, incoming.read_bytes())

        instance_dir = os.path.dirname(live_database)
        saved = [n for n in os.listdir(instance_dir) if n.startswith("replaced-")]
        assert len(saved) == 1

        connection = sqlite3.connect(os.path.join(instance_dir, saved[0]))
        try:
            titles = [row[0] for row in connection.execute("SELECT title FROM talks")]
        finally:
            connection.close()
            os.remove(os.path.join(instance_dir, saved[0]))

        assert titles == ["The Talk That Is Here Now"]

    def test_an_unticked_confirmation_changes_nothing(
        self, auth_client, live_database, make_talk, tmp_path
    ):
        make_talk(talk_id=1, title="Still Here")
        incoming = make_database(tmp_path / "incoming.sqlite")

        upload(auth_client, incoming.read_bytes(), confirm=None)

        assert [t.title for t in Talk.query.all()] == ["Still Here"]

    def test_a_file_that_is_not_sqlite_changes_nothing(
        self, auth_client, live_database, make_talk
    ):
        make_talk(talk_id=1, title="Still Here")

        upload(auth_client, b"id,title\n1,Not a database\n", filename="talks.csv")

        assert [t.title for t in Talk.query.all()] == ["Still Here"]

    def test_a_truncated_database_changes_nothing(
        self, auth_client, live_database, make_talk, tmp_path
    ):
        make_talk(talk_id=1, title="Still Here")
        incoming = make_database(tmp_path / "incoming.sqlite")
        # Keep the magic bytes, lose the rest.
        truncated = incoming.read_bytes()[:200]

        upload(auth_client, truncated)

        assert [t.title for t in Talk.query.all()] == ["Still Here"]

    def test_a_database_missing_our_tables_changes_nothing(
        self, auth_client, live_database, make_talk, tmp_path
    ):
        make_talk(talk_id=1, title="Still Here")

        stranger = tmp_path / "stranger.sqlite"
        connection = sqlite3.connect(stranger)
        try:
            connection.execute("CREATE TABLE something_else (id INTEGER)")
            connection.commit()
        finally:
            connection.close()

        upload(auth_client, stranger.read_bytes())

        assert [t.title for t in Talk.query.all()] == ["Still Here"]

    def test_a_database_from_newer_code_is_refused(
        self, auth_client, live_database, make_talk, tmp_path
    ):
        """Its schema has changes this code cannot read, and there is no way back."""
        make_talk(talk_id=1, title="Still Here")
        incoming = make_database(tmp_path / "incoming.sqlite")

        connection = sqlite3.connect(incoming)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TEXT)"
            )
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES ('099_from_the_future', datetime('now'))"
            )
            connection.commit()
        finally:
            connection.close()

        response = upload(auth_client, incoming.read_bytes())

        assert response.status_code == 302
        assert [t.title for t in Talk.query.all()] == ["Still Here"]

    def test_no_file_selected_changes_nothing(self, auth_client, live_database, make_talk):
        make_talk(talk_id=1, title="Still Here")

        auth_client.post(
            "/upload_database",
            data={"confirm": "yes"},
            content_type="multipart/form-data",
        )

        assert [t.title for t in Talk.query.all()] == ["Still Here"]

    def test_leaves_no_staging_files_behind(self, auth_client, live_database, tmp_path):
        incoming = make_database(tmp_path / "incoming.sqlite")

        upload(auth_client, incoming.read_bytes())

        instance_dir = os.path.dirname(live_database)
        leftovers = [n for n in os.listdir(instance_dir) if n.startswith("incoming-")]
        for name in os.listdir(instance_dir):
            if name.startswith("replaced-"):
                os.remove(os.path.join(instance_dir, name))

        assert leftovers == []

    def test_needs_a_team_leader(self, client, live_database, tmp_path):
        incoming = make_database(tmp_path / "incoming.sqlite")

        response = upload(client, incoming.read_bytes())

        assert response.status_code == 302
        assert "/upload_database" not in response.headers.get("Location", "")


class TestInspectDatabaseFile:
    def test_reports_a_database_that_is_behind_as_a_note_not_a_problem(
        self, app_ctx, live_database, tmp_path
    ):
        from gbtalks.routes import inspect_database_file

        incoming = make_database(tmp_path / "incoming.sqlite")

        from gbtalks.commands import MIGRATIONS

        connection = sqlite3.connect(incoming)
        try:
            connection.execute(
                "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT)"
            )
            # Everything but the last one, so it is genuinely behind.
            for migration in MIGRATIONS[:-1]:
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (?, datetime('now'))",
                    (migration.version,),
                )
            connection.commit()
        finally:
            connection.close()

        problems, notes = inspect_database_file(str(incoming))

        assert problems == []
        assert notes and MIGRATIONS[-1].version in notes[0]
        assert "flask migrate" in notes[0]

    def test_a_database_with_no_migration_history_is_allowed_with_a_note(
        self, app_ctx, live_database, tmp_path
    ):
        """`flask createdb` never creates schema_migrations, so its absence is
        normal rather than suspicious."""
        from gbtalks.routes import inspect_database_file

        incoming = make_database(tmp_path / "incoming.sqlite")

        problems, notes = inspect_database_file(str(incoming))

        assert problems == []
        assert notes and "no migration history" in notes[0]


class TestSetupPageWiring:
    """The card is the only way anyone reaches either route."""

    def test_setup_offers_the_download_and_the_replace_form(self, auth_client, live_database):
        page = auth_client.get("/setup").get_data(as_text=True)

        assert "/download_database" in page
        assert 'action="upload_database"' in page
        # Replacing everything should not be one careless click.
        assert "confirm" in page

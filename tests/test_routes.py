"""Route-level tests.

These are deliberately broad rather than deep: the point is a safety net that
notices if a refactor breaks a page, not exhaustive behavioural coverage.
"""

from datetime import datetime
from pathlib import Path

import pytest

from gbtalks.libgbtalks import calculate_greenbelt_friday
from gbtalks.models import Talk

# Routes that render a page and need no query parameters.
PAGE_ROUTES = [
    "/",
    "/talks",
    "/editing",
    "/front_desk",
    "/duplication",
    "/recorders",
    "/setup",
    "/rota",
    "/rota_by_recorder",
    "/rota_by_time",
    "/rota_by_venue",
    "/talks_archive.csv",
    "/talks_products.csv",
]

# Routes that currently have no @login_required / @current_user_is_team_leader.
# See TestUnauthenticatedRoutes below - this list documents present behaviour,
# it is not an endorsement of it.
CURRENTLY_UNAUTHENTICATED = {
    "/rota",
    "/rota_by_recorder",
    "/rota_by_time",
    "/rota_by_venue",
    "/talks_archive.csv",
    "/talks_products.csv",
}


class TestAuthentication:
    @pytest.mark.parametrize(
        "route", [r for r in PAGE_ROUTES if r not in CURRENTLY_UNAUTHENTICATED]
    )
    def test_pages_reject_anonymous_users(self, client, route):
        response = client.get(route)
        assert response.status_code in (302, 401), f"{route} was reachable anonymously"

    def test_health_check_also_requires_a_team_leader(self, client):
        """/health is not a public liveness endpoint; it sits behind the gate."""
        assert client.get("/health").status_code in (302, 401)

    def test_edit_talk_requires_authentication(self, client):
        assert client.get("/edit_talk?talk_id=1").status_code in (302, 401)

    def test_non_team_leader_is_rejected(self, app, db, client):
        """A valid login is not enough; the email must be a listed team leader."""
        from gbtalks.models import User

        outsider = User(email="someone-else@example.test")
        db.session.add(outsider)
        db.session.commit()

        with client.session_transaction() as session:
            session["_user_id"] = str(outsider.id)
            session["_fresh"] = True

        assert client.get("/talks").status_code in (302, 401)


class TestPagesRender:
    @pytest.mark.parametrize("route", PAGE_ROUTES)
    def test_renders_with_an_empty_database(self, auth_client, route):
        response = auth_client.get(route)
        assert response.status_code < 500, f"{route} returned {response.status_code}"

    @pytest.mark.parametrize("route", PAGE_ROUTES)
    def test_renders_with_data_present(self, auth_client, make_talk, make_recorder, route):
        recorder = make_recorder(name="Robin Recorder")
        make_talk(talk_id=1, title="First Talk", recorder_name=recorder.name)
        make_talk(talk_id=2, title="Second Talk", day="Sunday", venue="Playhouse")

        response = auth_client.get(route)
        assert response.status_code < 500, f"{route} returned {response.status_code}"


class TestUnauthenticatedRoutes:
    """Documents routes that are currently reachable without logging in.

    These tests assert what the application does today so that a deliberate
    decision to lock them down shows up as a failing test rather than a silent
    behaviour change.
    """

    @pytest.mark.parametrize("route", sorted(CURRENTLY_UNAUTHENTICATED))
    def test_readable_without_logging_in(self, client, route):
        assert client.get(route).status_code == 200

    def test_rota_cannot_be_regenerated_without_logging_in(
        self, client, db, make_talk, make_recorder
    ):
        """POST /rota calls clear_rota(), so it must be team-leader only."""
        make_recorder(name="Robin Recorder")
        make_talk(talk_id=1, recorder_name="Robin Recorder", is_priority=False)

        response = client.post("/rota")

        assert response.status_code in (302, 401)
        assert db.session.get(Talk, 1).recorder_name == "Robin Recorder"

    def test_rota_can_still_be_regenerated_by_a_team_leader(
        self, auth_client, db, make_talk, make_recorder
    ):
        make_recorder(name="Robin Recorder")
        make_talk(talk_id=1, recorder_name="Robin Recorder", is_priority=False)

        response = auth_client.post("/rota")

        assert response.status_code == 200
        assert db.session.get(Talk, 1).recorder_name is None


class TestEditTalkPage:
    def test_renders_for_an_existing_talk(self, auth_client, make_talk):
        make_talk(talk_id=1, title="Editable Talk")
        response = auth_client.get("/edit_talk?talk_id=1")

        assert response.status_code == 200
        assert "Editable Talk" in response.get_data(as_text=True)

    @pytest.mark.parametrize(
        ("query", "description"),
        [
            ("", "no talk_id at all"),
            ("?talk_id=", "an empty talk_id"),
            ("?talk_id=99999", "an unknown talk_id"),
            ("?talk_id=abc", "a non-numeric talk_id"),
        ],
    )
    def test_redirects_instead_of_crashing_for_a_bad_talk_id(
        self, auth_client, query, description
    ):
        """Every one of these used to raise AttributeError and return a 500.

        db.session.get returns None for all of them, and the template then
        read .start_time off it.
        """
        response = auth_client.get(f"/edit_talk{query}")

        assert response.status_code == 302, f"expected a redirect for {description}"
        assert "/talks" in response.headers["Location"]

    def test_bad_talk_id_flashes_an_explanation(self, auth_client):
        response = auth_client.get("/edit_talk?talk_id=99999", follow_redirects=True)

        assert response.status_code == 200
        assert "Talk 99999 not found" in response.get_data(as_text=True)


class TestEditTalkDiscardsProcessedFile:
    """Editing the details on the MP3 should make the cron job rebuild it.

    convert_talks matches a processed file to a talk by the id in its name and
    ignores the rest, so a file left under the old title would go on standing
    in for the talk and it would never be rebuilt.
    """

    @pytest.fixture
    def storage(self, app):
        directories = [
            Path(app.config[name]) for name in ("UPLOAD_DIR", "PROCESSED_DIR")
        ]
        yield directories
        for directory in directories:
            for leftover in directory.iterdir():
                if leftover.is_file():
                    leftover.unlink()

    def processed_path(self, app, talk_id, title, speaker):
        from gbtalks.libgbtalks import get_path_for_file

        with app.app_context():
            return Path(get_path_for_file(str(talk_id), "processed", title, speaker))

    def form(self, **overrides):
        fields = {
            "talk_id": "1",
            "title": "Old Title",
            "description": "A description",
            "speaker": "Sam Speaker",
            "day": "Saturday",
            "start_time": "10:00",
            "end_time": "11:00",
            "is_cleared": "on",
        }
        fields.update(overrides)
        return fields

    @pytest.fixture
    def talk(self, make_talk, app, storage):
        """A cleared talk with an edited file and a processed file."""
        talk = make_talk(talk_id=1, title="Old Title", is_cleared=True)
        Path(app.config["UPLOAD_DIR"], "gb26-001_EDITED.mp3").touch()
        self.processed_path(app, 1, "Old Title", "Sam Speaker").touch()
        return talk

    def test_a_new_title_removes_the_file_named_after_the_old_one(
        self, auth_client, app, talk
    ):
        old = self.processed_path(app, 1, "Old Title", "Sam Speaker")

        auth_client.post("/edit_talk", data=self.form(title="New Title"))

        assert not old.exists(), "the stale file would suppress the rebuild for good"

    def test_a_new_speaker_removes_it_too(self, auth_client, app, talk):
        old = self.processed_path(app, 1, "Old Title", "Sam Speaker")

        auth_client.post("/edit_talk", data=self.form(speaker="Others"))

        assert not old.exists()

    def test_a_new_description_removes_it(self, auth_client, app, talk):
        """The description is not in the filename, but it is in the ID3 tags."""
        old = self.processed_path(app, 1, "Old Title", "Sam Speaker")

        auth_client.post("/edit_talk", data=self.form(description="Rewritten"))

        assert not old.exists()

    def test_a_new_time_leaves_it_alone(self, auth_client, app, talk):
        """Nothing about the time reaches the MP3, so there is nothing to redo."""
        old = self.processed_path(app, 1, "Old Title", "Sam Speaker")

        auth_client.post("/edit_talk", data=self.form(start_time="14:00", end_time="15:00"))

        assert old.exists()

    def test_the_edited_file_survives(self, auth_client, app, talk):
        """Deleting the source is how a rename would destroy the recording."""
        auth_client.post("/edit_talk", data=self.form(title="New Title"))

        assert Path(app.config["UPLOAD_DIR"], "gb26-001_EDITED.mp3").exists()

    def test_the_edit_still_applies(self, auth_client, db, app, talk):
        auth_client.post("/edit_talk", data=self.form(title="New Title"))

        assert db.session.get(Talk, 1).title == "New Title"

    def test_it_says_so(self, auth_client, app, talk):
        response = auth_client.post(
            "/edit_talk", data=self.form(title="New Title"), follow_redirects=True
        )

        assert "rebuilt with the new details" in response.get_data(as_text=True)

    def test_no_processed_file_is_not_an_error(
        self, auth_client, make_talk, app, storage
    ):
        make_talk(talk_id=1, title="Old Title", is_cleared=True)

        response = auth_client.post(
            "/edit_talk", data=self.form(title="New Title"), follow_redirects=True
        )

        page = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Successfully updated talk" in page
        assert "processed file has been removed" not in page

    def test_says_when_there_is_nothing_to_rebuild_from(
        self, auth_client, make_talk, app, storage
    ):
        """Removing the file without an edited file to redo it from is a loss."""
        make_talk(talk_id=1, title="Old Title", is_cleared=True)
        self.processed_path(app, 1, "Old Title", "Sam Speaker").touch()

        response = auth_client.post(
            "/edit_talk", data=self.form(title="New Title"), follow_redirects=True
        )

        assert "no edited file to rebuild it from" in response.get_data(as_text=True)

    def test_says_when_the_talk_is_not_cleared(self, auth_client, app, talk):
        """convert_talks only converts cleared talks, so do not promise sooner."""
        response = auth_client.post(
            "/edit_talk",
            data=self.form(title="New Title", is_cleared=""),
            follow_redirects=True,
        )

        assert "once the talk is cleared" in response.get_data(as_text=True)


class TestUploadingAnEditedFileDiscardsProcessedFile:
    """A replacement edited file has to reach the MP3 people are given.

    convert_talks only converts a talk that has no processed file, so leaving
    the old one there means the new edit is never built and nobody finds out
    until they play the USB stick.
    """

    @pytest.fixture
    def storage(self, app):
        directories = [
            Path(app.config[name]) for name in ("UPLOAD_DIR", "PROCESSED_DIR")
        ]
        yield directories
        for directory in directories:
            for leftover in directory.iterdir():
                if leftover.is_file():
                    leftover.unlink()

    def processed_path(self, app, talk_id=1, title="Old Title", speaker="Sam Speaker"):
        from gbtalks.libgbtalks import get_path_for_file

        with app.app_context():
            return Path(get_path_for_file(str(talk_id), "processed", title, speaker))

    @pytest.fixture
    def talk(self, make_talk, app, storage):
        """A cleared talk that has already been edited and converted."""
        talk = make_talk(talk_id=1, title="Old Title", is_cleared=True)
        Path(app.config["UPLOAD_DIR"], "gb26-001_EDITED.mp3").write_bytes(b"old edit")
        self.processed_path(app).write_bytes(b"built from the old edit")
        return talk

    def upload(self, auth_client, file_type="edited", content=b"a longer new edit"):
        import io

        return auth_client.post(
            "/uploadtalk",
            data={
                "talk_id": "1",
                "file_type": file_type,
                "file": (io.BytesIO(content), "talk.mp3"),
            },
            content_type="multipart/form-data",
            headers={"Referer": "http://localhost/talks"},
            follow_redirects=True,
        )

    def test_it_removes_the_processed_file(self, auth_client, app, talk):
        processed = self.processed_path(app)

        self.upload(auth_client)

        assert not processed.exists(), "the old one would suppress the rebuild"

    def test_the_new_edited_file_is_in_place(self, auth_client, app, talk):
        self.upload(auth_client)

        edited = Path(app.config["UPLOAD_DIR"], "gb26-001_EDITED.mp3")
        assert edited.read_bytes() == b"a longer new edit"

    def test_it_says_so(self, auth_client, app, talk):
        page = self.upload(auth_client).get_data(as_text=True)

        assert "rebuilt from the new edited file" in page

    def test_a_raw_upload_leaves_it_alone(self, auth_client, app, talk):
        """Only the edited file is what the processed MP3 is built from."""
        processed = self.processed_path(app)

        self.upload(auth_client, file_type="raw", content=b"a raw recording")

        assert processed.exists()

    def test_no_processed_file_is_not_an_error(
        self, auth_client, make_talk, app, storage
    ):
        make_talk(talk_id=1, title="Old Title", is_cleared=True)

        response = self.upload(auth_client)

        page = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Successfully uploaded edited file" in page
        assert "processed file has been removed" not in page

    def test_says_when_the_talk_is_not_cleared(
        self, auth_client, make_talk, app, storage
    ):
        """convert_talks only converts cleared talks, so do not promise sooner."""
        make_talk(talk_id=1, title="Old Title", is_cleared=False)
        self.processed_path(app).write_bytes(b"built from the old edit")

        page = self.upload(auth_client).get_data(as_text=True)

        assert "once the talk is cleared" in page


class TestTalksPage:
    def test_lists_talks_in_start_time_order(self, auth_client, make_talk):
        make_talk(talk_id=2, title="Later Talk", start="15:00", end="16:00")
        make_talk(talk_id=1, title="Earlier Talk", start="09:00", end="10:00")

        body = auth_client.get("/talks").get_data(as_text=True)
        assert body.index("Earlier Talk") < body.index("Later Talk")

    def test_summary_counts_the_talks(self, auth_client, make_talk):
        # The filters are applied in the browser, so this is the unfiltered
        # figure the script starts from and revises on the first click.
        for talk_id in range(1, 4):
            make_talk(talk_id=talk_id)

        body = auth_client.get("/talks").get_data(as_text=True)
        assert "Showing all 3 talks" in body

    def test_summary_is_singular_for_one_talk(self, auth_client, make_talk):
        make_talk(talk_id=1)

        body = auth_client.get("/talks").get_data(as_text=True)
        assert "Showing all 1 talk<" in body

    def test_summary_with_no_talks_at_all(self, auth_client):
        body = auth_client.get("/talks").get_data(as_text=True)
        assert "No talks loaded" in body


class TestAddTalk:
    def test_creates_a_talk(self, auth_client, db):
        response = auth_client.post(
            "/add_talk",
            data={
                "talk_id": "42",
                "title": "A New Talk",
                "speaker": "Sam Speaker",
                "description": "About things",
                "venue": "The Big Top",
                "day": "Saturday",
                "start_time": "10:00",
                "end_time": "11:00",
            },
            follow_redirects=True,
        )
        assert response.status_code < 500

        talk = db.session.get(Talk, 42)
        assert talk is not None
        assert talk.title == "A New Talk"


class TestToggleTalkCancelled:
    """Despite the name this is not a toggle - the action is passed explicitly."""

    def test_cancels_and_restores_a_talk(self, auth_client, db, make_talk):
        make_talk(talk_id=1, is_cancelled=False)

        auth_client.post(
            "/toggle_talk_cancelled", data={"talk_id": "1", "action": "cancel"}
        )
        assert db.session.get(Talk, 1).is_cancelled is True

        auth_client.post(
            "/toggle_talk_cancelled", data={"talk_id": "1", "action": "uncancel"}
        )
        assert db.session.get(Talk, 1).is_cancelled is False

    def test_cancelling_preserves_the_talk_row(self, auth_client, db, make_talk):
        """Cancellation must never delete the talk or free up its ID."""
        make_talk(talk_id=1, title="Keep Me")

        auth_client.post(
            "/toggle_talk_cancelled", data={"talk_id": "1", "action": "cancel"}
        )

        talk = db.session.get(Talk, 1)
        assert talk is not None
        assert talk.title == "Keep Me"

    @pytest.mark.parametrize(
        "payload",
        [
            {"talk_id": "1"},  # no action
            {"action": "cancel"},  # no talk_id
            {"talk_id": "1", "action": "explode"},  # unknown action
            {"talk_id": "99999", "action": "cancel"},  # unknown talk
        ],
    )
    def test_bad_input_redirects_without_changing_anything(
        self, auth_client, db, make_talk, payload
    ):
        make_talk(talk_id=1, is_cancelled=False)

        response = auth_client.post("/toggle_talk_cancelled", data=payload)

        assert response.status_code == 302
        assert db.session.get(Talk, 1).is_cancelled is False


class TestAssignRecorder:
    def test_assigns_a_recorder_to_a_talk(self, auth_client, db, make_talk, make_recorder):
        make_recorder(name="Robin Recorder")
        make_talk(talk_id=1)

        auth_client.post(
            "/assign_recorder",
            data={"talk_id": "1", "recorder_name": "Robin Recorder"},
        )

        assert db.session.get(Talk, 1).recorder_name == "Robin Recorder"


class TestUpdateFestivalYear:
    """The setup page's festival-year control writes GB_FRIDAY into .env.

    It should only ever leave a pin behind for a year the calendar would not
    have given on its own. A pin naming the current year is how the on-site
    .env came to claim 2025 a year later.
    """

    @pytest.fixture
    def env_file(self, app_ctx):
        path = Path(app_ctx.config["ENV_FILE"])
        path.write_text("SECRET_KEY=whatever\n")
        yield path
        path.unlink(missing_ok=True)

    def _post(self, auth_client, year):
        return auth_client.post("/update_festival_year", data={"festival_year": str(year)})

    def test_current_year_leaves_no_pin(self, auth_client, env_file):
        response = self._post(auth_client, datetime.now().year)

        assert response.status_code == 302
        assert "GB_FRIDAY" not in env_file.read_text()

    def test_a_later_year_is_pinned(self, auth_client, env_file):
        year = datetime.now().year + 1

        self._post(auth_client, year)

        expected = calculate_greenbelt_friday(year).strftime("%Y-%m-%d")
        assert f"GB_FRIDAY={expected}\n" in env_file.read_text()

    def test_choosing_the_current_year_again_removes_an_existing_pin(
        self, auth_client, env_file
    ):
        self._post(auth_client, datetime.now().year + 1)
        assert "GB_FRIDAY" in env_file.read_text()

        self._post(auth_client, datetime.now().year)

        assert "GB_FRIDAY" not in env_file.read_text()

    def test_leaves_the_rest_of_the_file_alone(self, auth_client, env_file):
        self._post(auth_client, datetime.now().year + 1)

        assert "SECRET_KEY=whatever\n" in env_file.read_text()

    def test_does_not_duplicate_the_pin(self, auth_client, env_file):
        year = datetime.now().year + 1

        self._post(auth_client, year)
        self._post(auth_client, year)

        assert env_file.read_text().count("GB_FRIDAY=") == 1


class TestRawFileScan:
    """Previous festivals' recordings share the upload directory with this
    year's - nothing sweeps them out at rollover - so a scan for "which talks
    have been recorded" has to ignore them rather than trying to read a talk
    ID out of a filename that does not carry one.
    """

    @pytest.fixture
    def uploads(self, app):
        """The upload directory, emptied of anything a test left behind."""
        directory = Path(app.config["UPLOAD_DIR"])
        yield directory
        for leftover in directory.iterdir():
            leftover.unlink()

    def test_finds_this_years_recordings(self, app_ctx, uploads):
        from gbtalks.routes import talk_ids_with_file

        (uploads / "gb26-001_RAW.mp3").touch()
        (uploads / "gb26-042_RAW.mp3").touch()

        assert talk_ids_with_file(uploads, "_RAW.mp3") == {1, 42}

    def test_ignores_other_years_and_other_kinds(self, app_ctx, uploads):
        from gbtalks.routes import talk_ids_with_file

        (uploads / "gb26-001_RAW.mp3").touch()
        (uploads / "gb25-001_RAW.mp3").touch()
        (uploads / "gb26-001_EDITED.mp3").touch()
        (uploads / "notes.txt").touch()

        assert talk_ids_with_file(uploads, "_RAW.mp3") == {1}

    def test_front_desk_survives_last_years_recordings(
        self, auth_client, make_talk, uploads
    ):
        make_talk(talk_id=1)
        (uploads / "gb25-001_RAW.mp3").touch()

        assert auth_client.get("/front_desk").status_code == 200

    def test_editing_lists_talks_whose_raw_file_has_not_been_edited(
        self, auth_client, make_talk, uploads
    ):
        make_talk(talk_id=1, title="Still To Edit")
        make_talk(talk_id=2, title="Already Edited")
        make_talk(talk_id=3, title="Never Recorded")
        for name in ("gb26-001_RAW.mp3", "gb26-002_RAW.mp3", "gb26-002_EDITED.mp3"):
            (uploads / name).touch()

        page = auth_client.get("/editing").get_data(as_text=True)

        assert "Still To Edit" in page
        assert "Already Edited" not in page
        assert "Never Recorded" not in page

    def test_editing_ignores_last_years_recordings(
        self, auth_client, make_talk, uploads
    ):
        """The IDs collide across years - gb25-001 must not stand in for talk 1."""
        make_talk(talk_id=1, title="Not Recorded This Year")
        (uploads / "gb25-001_RAW.mp3").touch()

        page = auth_client.get("/editing").get_data(as_text=True)

        assert "Not Recorded This Year" not in page


class TestDeleteTalkFile:
    """POST /delete_talk_file - removes one of a talk's files from disk."""

    @pytest.fixture
    def storage(self, app):
        """The storage directories, emptied of anything a test left behind."""
        directories = [
            Path(app.config[name])
            for name in ("UPLOAD_DIR", "PROCESSED_DIR", "WEB_MP3_DIR", "IMG_DIR")
        ]
        yield directories
        for directory in directories:
            for leftover in directory.iterdir():
                if leftover.is_file():
                    leftover.unlink()

    def path_for(self, app, talk, file_type):
        from gbtalks.routes import talk_file_path

        with app.app_context():
            return Path(talk_file_path(talk, file_type))

    def test_requires_a_team_leader(self, client, make_talk, app, storage):
        talk = make_talk(talk_id=1)
        path = self.path_for(app, talk, "raw")
        path.touch()

        response = client.post(
            "/delete_talk_file", data={"talk_id": 1, "file_type": "raw"}
        )

        assert response.status_code in (302, 401)
        assert path.exists(), "the file went even though the caller was anonymous"

    @pytest.mark.parametrize(
        "file_type", ["raw", "edited", "processed", "web_mp3", "recorder_notes", "video"]
    )
    def test_deletes_one_kind_of_file(
        self, auth_client, make_talk, app, storage, file_type
    ):
        talk = make_talk(talk_id=1)
        path = self.path_for(app, talk, file_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

        response = auth_client.post(
            "/delete_talk_file", data={"talk_id": 1, "file_type": file_type}
        )

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        assert not path.exists()

    def test_leaves_the_talks_other_files_alone(
        self, auth_client, make_talk, app, storage
    ):
        """A talk has several files; deleting one must not take the rest."""
        talk = make_talk(talk_id=1)
        raw = self.path_for(app, talk, "raw")
        edited = self.path_for(app, talk, "edited")
        raw.touch()
        edited.touch()

        auth_client.post("/delete_talk_file", data={"talk_id": 1, "file_type": "raw"})

        assert not raw.exists()
        assert edited.exists()

    def test_the_talk_itself_survives(self, auth_client, db, make_talk, app, storage):
        talk = make_talk(talk_id=1, title="Still Here")
        self.path_for(app, talk, "raw").touch()

        auth_client.post("/delete_talk_file", data={"talk_id": 1, "file_type": "raw"})

        assert db.session.get(Talk, 1).title == "Still Here"

    def test_unknown_file_type_is_rejected(self, auth_client, make_talk, app, storage):
        talk = make_talk(talk_id=1)
        raw = self.path_for(app, talk, "raw")
        raw.touch()

        response = auth_client.post(
            "/delete_talk_file", data={"talk_id": 1, "file_type": "../../etc/passwd"}
        )

        assert response.status_code == 400
        assert raw.exists()

    def test_missing_file_is_a_404(self, auth_client, make_talk, storage):
        make_talk(talk_id=1)

        response = auth_client.post(
            "/delete_talk_file", data={"talk_id": 1, "file_type": "raw"}
        )

        assert response.status_code == 404
        assert response.get_json()["success"] is False

    def test_unknown_talk_is_a_404(self, auth_client, storage):
        response = auth_client.post(
            "/delete_talk_file", data={"talk_id": 99, "file_type": "raw"}
        )

        assert response.status_code == 404

    def test_the_talks_page_delete_button_posts_here(
        self, auth_client, make_talk, app, storage
    ):
        """The button is wired to this route. /deletetalk is gone; a template
        reverted to it would render fine and 404 on click, so check for it."""
        talk = make_talk(talk_id=1)
        self.path_for(app, talk, "processed").touch()

        page = auth_client.get("/talks").get_data(as_text=True)

        assert 'action="/delete_talk_file"' in page
        assert "action=deletetalk" not in page


class TestWebsiteExports:
    """Both exports list the same talks: the cleared, uncancelled ones."""

    @pytest.mark.parametrize("route", ["/talks_archive.csv", "/talks_products.csv"])
    def test_uncleared_and_cancelled_talks_are_left_out(
        self, client, make_talk, route
    ):
        make_talk(talk_id=1, title="Cleared Talk", is_cleared=True)
        make_talk(talk_id=2, title="Uncleared Talk")
        make_talk(
            talk_id=3, title="Cancelled Talk", is_cleared=True, is_cancelled=True
        )

        csv = client.get(route).get_data(as_text=True)

        assert "Cleared Talk" in csv
        assert "Uncleared Talk" not in csv
        assert "Cancelled Talk" not in csv

    def test_the_products_export_adds_two_variations_per_talk(
        self, app, client, make_talk
    ):
        make_talk(talk_id=1, is_cleared=True)

        csv = client.get("/talks_products.csv").get_data(as_text=True)
        reference = "GB" + app.config["GB_SHORT_YEAR"] + "-001"

        assert reference + "-DL" in csv
        assert reference + "-MS" in csv

    def test_the_archive_export_is_one_row_per_talk(self, client, make_talk):
        make_talk(talk_id=1, is_cleared=True)

        csv = client.get("/talks_archive.csv").get_data(as_text=True)

        assert "-DL" not in csv
        assert "-MS" not in csv

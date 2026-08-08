"""Both ways talks get into the database: the /talks upload and the CLI."""

import io

from gbtalks.models import Talk

HEADER = "id,title,speaker,day,venue,start_time,end_time,is_priority,is_rotaed,is_cleared"


def upload(client, body, filename="talks.csv"):
    return client.post(
        "/talks",
        data={
            "form_name": "upload_talks_list",
            "file": (io.BytesIO(body.encode()), filename),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )


class TestTalksUpload:
    def test_loads_talks_from_a_valid_file(self, auth_client, db):
        response = upload(
            auth_client,
            f"{HEADER}\n"
            "GB26-001,Opening,Sam Speaker,Friday,The Big Top,19:00,20:00,Yes,Yes,Yes\n"
            "GB26-002,Closing,Alex Speaker,Monday,The Playhouse,14:00,15:00,No,Yes,Yes\n",
        )

        assert response.status_code == 200
        assert Talk.query.count() == 2

        talk = db.session.get(Talk, 1)
        assert talk.title == "Opening"
        assert talk.speaker == "Sam Speaker"
        assert talk.is_priority is True
        assert talk.start_time.hour == 19

    def test_replaces_the_existing_talks(self, auth_client, db, make_talk):
        make_talk(talk_id=99, title="Old Talk")

        upload(
            auth_client,
            f"{HEADER}\n1,New Talk,Sam,Friday,The Big Top,10:00,11:00,Yes,Yes,Yes\n",
        )

        assert db.session.get(Talk, 99) is None
        assert db.session.get(Talk, 1).title == "New Talk"

    def test_a_malformed_file_leaves_the_existing_talks_alone(
        self, auth_client, db, make_talk
    ):
        """The file is parsed in full before anything is deleted."""
        make_talk(talk_id=99, title="Keep Me")

        response = upload(auth_client, f"{HEADER}\n1,Broken,Sam,Friday,The Big Top,NOT A TIME,11:00,Yes,Yes,Yes\n")

        assert response.status_code == 200
        assert db.session.get(Talk, 99).title == "Keep Me"
        assert Talk.query.count() == 1

    def test_a_malformed_file_explains_what_is_wrong(self, auth_client, db, make_talk):
        make_talk(talk_id=99)

        body = upload(
            auth_client, f"{HEADER}\n1,Broken,Sam,Friday,The Big Top,NOT A TIME,11:00,Yes,Yes,Yes\n"
        ).get_data(as_text=True)

        assert "Row 2" in body
        assert "start_time" in body

    def test_a_file_missing_columns_is_rejected(self, auth_client, db, make_talk):
        make_talk(talk_id=99)

        body = upload(auth_client, "id,title\n1,Broken\n").get_data(as_text=True)

        assert "Missing required column" in body
        assert Talk.query.count() == 1

    def test_reports_how_many_talks_were_loaded(self, auth_client, db):
        body = upload(
            auth_client,
            f"{HEADER}\n"
            "1,One,Sam,Friday,The Big Top,10:00,11:00,Yes,Yes,Yes\n"
            "2,Two,Sam,Friday,The Big Top,12:00,13:00,Yes,Yes,Yes\n",
        ).get_data(as_text=True)

        assert "Loaded 2 talks" in body


class TestLoadSampleData:
    def test_loads_the_shipped_sample_talks(self, app, db):
        result = app.test_cli_runner().invoke(args=["load-sample-data", "talks"])

        assert result.exit_code == 0, result.output
        assert Talk.query.count() == 75

    def test_sample_talks_are_usable_by_the_rota_generator(self, app, db):
        """Talks must be rota-flagged, or generation silently assigns nothing."""
        app.test_cli_runner().invoke(args=["load-sample-data", "talks"])

        assert Talk.query.filter(Talk.is_rotaed.is_(True)).count() > 0

    def test_sample_talks_use_the_configured_festival_year(self, app, db):
        app.test_cli_runner().invoke(args=["load-sample-data", "talks"])

        assert Talk.query.filter(Talk.start_time < "2026-01-01").count() == 0

    def test_loads_sample_recorders(self, app, db):
        from gbtalks.models import Recorder

        result = app.test_cli_runner().invoke(args=["load-sample-data", "recorders"])

        assert result.exit_code == 0, result.output
        assert Recorder.query.count() > 0
        assert Recorder.query.filter(Recorder.earliest_start_time.isnot(None)).count() > 0

    def test_loads_sample_editors(self, app, db):
        from gbtalks.models import Editor

        result = app.test_cli_runner().invoke(args=["load-sample-data", "editors"])

        assert result.exit_code == 0, result.output
        assert Editor.query.count() > 0

    def test_clear_flag_replaces_existing_rows(self, app, db, make_talk):
        make_talk(talk_id=500, title="Stale Talk")

        result = app.test_cli_runner().invoke(
            args=["load-sample-data", "talks", "--clear"]
        )

        assert result.exit_code == 0, result.output
        assert db.session.get(Talk, 500) is None
        assert Talk.query.count() == 75

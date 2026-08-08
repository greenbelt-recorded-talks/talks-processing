"""Route-level tests.

These are deliberately broad rather than deep: the point is a safety net that
notices if a refactor breaks a page, not exhaustive behavioural coverage.
"""

import pytest

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

    def test_crashes_when_no_talk_id_is_given(self, auth_client):
        """Currently a 500 - Talk.query.get(None) returns None and is then used."""
        with pytest.raises(AttributeError):
            auth_client.get("/edit_talk")

    def test_crashes_for_an_unknown_talk_id(self, auth_client):
        with pytest.raises(AttributeError):
            auth_client.get("/edit_talk?talk_id=99999")


class TestTalksPage:
    def test_lists_talks_in_start_time_order(self, auth_client, make_talk):
        make_talk(talk_id=2, title="Later Talk", start="15:00", end="16:00")
        make_talk(talk_id=1, title="Earlier Talk", start="09:00", end="10:00")

        body = auth_client.get("/talks").get_data(as_text=True)
        assert body.index("Earlier Talk") < body.index("Later Talk")


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

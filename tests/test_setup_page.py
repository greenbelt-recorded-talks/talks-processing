"""The setup page still offers every tool it is supposed to.

The page is a stack of unrelated tools, each one a form wrapped in
instructions, and folding them behind disclosures moved every one of them.
Nothing here checks how it looks - only that each section is still present and
still points its form at the route that does the work, because a tool that
quietly stops being rendered is invisible until somebody needs it mid-festival.
"""

from datetime import datetime

import pytest
from flask import render_template

# Section heading -> something from the rendered page that proves the section
# can still be used: the form action it posts to, or the path it links to.
# A section with no destination is one nobody can do anything with.
SECTIONS = {
    "System Health Check": "/health",          # a link, so url_for's path
    "Upload All Talks Index File": "put_alltalks_pdf",
    "Festival Year": "update_festival_year",
    "Upload Icon": "upload_cover_image",
    "Upload Top and Tail Audio": "upload_top_tail",
    "Rota Settings": "update_rota_settings",
    "Add New Talk": "add_talk",
    "Move the Database": "upload_database",
    "Replace Talks File": '"talks"',           # quoted: it is the whole action
}


def render_setup(app, rota_settings):
    from gbtalks.routes import perform_health_check

    with app.test_request_context("/setup"):
        return render_template(
            "setup.html",
            rota_settings=rota_settings,
            current_year=datetime.now().year,
            health_check=perform_health_check(),
        )


@pytest.fixture
def rota_settings(app_ctx):
    from gbtalks.models import RotaSettings

    RotaSettings.initialize_defaults()
    settings = RotaSettings.get_all_settings()
    assert settings, "expected initialize_defaults to give us something to render"
    return settings


class TestEveryToolIsStillThere:
    @pytest.mark.parametrize("heading,destination", sorted(SECTIONS.items()))
    def test_the_section_and_its_destination_are_rendered(
        self, app, rota_settings, heading, destination
    ):
        page = render_setup(app, rota_settings)

        assert heading in page
        assert destination in page

    def test_every_rota_setting_gets_a_field(self, app, rota_settings):
        page = render_setup(app, rota_settings)

        for key in rota_settings:
            assert f'name="{key}"' in page

    def test_the_page_survives_having_no_rota_settings(self, app, app_ctx):
        # What a database straight from `flask createdb` looks like. The rota
        # form cannot render, so the section says so rather than disappearing.
        page = render_setup(app, {})

        assert "Rota Settings" in page
        assert "update_rota_settings" not in page
        assert "flask createdb" in page

    def test_replacing_the_database_is_not_one_careless_click(self, app,
                                                              rota_settings):
        page = render_setup(app, rota_settings)

        assert 'name=confirm type=checkbox value="yes" required' in page

    def test_the_upload_fields_have_ids_of_their_own(self, app, rota_settings):
        # Three of these were all id=file, so two of the three labels pointed
        # at somebody else's input.
        page = render_setup(app, rota_settings)

        for field in ["alltalks_file", "cover_file", "top_file", "tail_file",
                      "talks_file", "database_file"]:
            assert f"id={field}" in page


class TestCertificateInstructions:
    """On-site machines are the only ones with a certificate to trust."""

    @pytest.mark.parametrize("env", ["onsite", None, "typo"])
    def test_they_show_anywhere_that_is_not_the_cloud(self, app, rota_settings,
                                                      env):
        # Gated on "not cloud" rather than "is onsite", so an unset or
        # mistyped DEPLOYMENT_ENV still leaves them on the machine that needs
        # them.
        app.config["DEPLOYMENT_ENV"] = env

        page = render_setup(app, rota_settings)

        assert "gbtalks-ca.crt" in page
        assert "Windows 10 and 11" in page
        assert "macOS" in page

    def test_they_are_hidden_on_the_cloud_deployment(self, app, rota_settings):
        app.config["DEPLOYMENT_ENV"] = "cloud"

        page = render_setup(app, rota_settings)

        assert "gbtalks-ca.crt" not in page


class TestTheRenderedPage:
    def test_a_team_leader_gets_the_whole_page(self, auth_client):
        page = auth_client.get("/setup").get_data(as_text=True)

        assert page.count("<form") == 9
        for heading in SECTIONS:
            assert heading in page

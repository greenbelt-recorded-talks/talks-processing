"""The health check's carried-over file detection.

Four files - top.mp3, tail.mp3, the cover art and the all-talks index - keep
the same names from one festival to the next, so last year's copy sits in place
looking perfectly healthy. The check flags anything untouched since the last
festival ended, and confirming it touches the file.
"""

import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from gbtalks.libgbtalks import festival_cycle_start

# Comfortably before any cycle start these tests will ever compute.
LONG_AGO = datetime(2020, 1, 1).timestamp()


# gbtalks.routes registers its routes against current_app as it is imported, so
# it can only be reached once the app fixture has built one.
def critical_files():
    from gbtalks.routes import critical_files as _critical_files

    return _critical_files()


def perform_health_check():
    from gbtalks.routes import perform_health_check as _perform_health_check

    return _perform_health_check()


@pytest.fixture
def carried_over_files(app):
    """The four critical files, present on disk and left over from a past year."""
    with app.app_context():
        paths = [Path(f["path"]) for f in critical_files()]

    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder")
        os.utime(path, (LONG_AGO, LONG_AGO))

    yield paths

    for path in paths:
        path.unlink(missing_ok=True)


class TestFestivalCycleStart:
    """The line between "put in place for this year" and "left over"."""

    def test_a_finished_festival_starts_the_next_cycle(self):
        """GB26 ran 28 Aug to 31 Aug; the Tuesday after belongs to GB27."""
        assert festival_cycle_start(datetime(2026, 9, 5)) == datetime(2026, 9, 1)

    def test_the_cycle_runs_up_to_the_next_festival(self):
        """The day before GB26 is still the cycle that began after GB25."""
        assert festival_cycle_start(datetime(2026, 8, 27)) == datetime(2025, 8, 26)

    def test_the_festival_itself_is_still_the_old_cycle(self):
        """Files uploaded mid-festival were prepared for the festival running."""
        assert festival_cycle_start(datetime(2026, 8, 29)) == datetime(2025, 8, 26)

    def test_it_does_not_depend_on_the_configured_year(self, app_ctx, monkeypatch):
        """A GB_FRIDAY nobody rolled over is the thing this is meant to catch."""
        monkeypatch.setitem(app_ctx.config, "GB_FRIDAY", "2019-08-23")

        assert festival_cycle_start(datetime(2026, 8, 27)) == datetime(2025, 8, 26)


class TestStaleFileDetection:

    def test_untouched_files_are_flagged(self, app_ctx, carried_over_files):
        health = perform_health_check()

        assert health["stale_count"] == len(carried_over_files)
        assert all(f["status"] == "stale" for f in health["files"])
        assert all(f["stale"] for f in health["files"])

    def test_staleness_is_a_warning_not_an_error(self, app_ctx, carried_over_files):
        """The file is present and readable; it might just be the wrong year's."""
        assert perform_health_check()["overall_status"] == "warning"

    def test_a_file_touched_this_cycle_is_healthy(self, app_ctx, carried_over_files):
        for path in carried_over_files:
            os.utime(path, None)

        health = perform_health_check()

        assert health["stale_count"] == 0
        assert all(f["status"] == "healthy" for f in health["files"])

    def test_a_missing_file_is_still_an_error(self, app_ctx, carried_over_files):
        carried_over_files[0].unlink()

        health = perform_health_check()

        assert health["files"][0]["status"] == "error"
        assert health["overall_status"] == "error"


class TestHealthPage:

    def test_it_offers_a_confirmation_for_carried_over_files(self, auth_client, carried_over_files):
        response = auth_client.get("/health")

        assert b"These are all still correct" in response.data
        assert b"top.mp3 is still correct" in response.data

    def test_it_asks_nothing_once_everything_is_current(self, auth_client, carried_over_files):
        for path in carried_over_files:
            os.utime(path, None)

        response = auth_client.get("/health")

        assert b"still correct" not in response.data


class TestConfirmFileCurrent:

    def test_it_requires_a_team_leader(self, client, carried_over_files):
        response = client.post("/confirm_file_current", data={"name": "top.mp3"})

        assert response.status_code in (302, 401)
        assert os.stat(carried_over_files[0]).st_mtime == LONG_AGO

    def test_confirming_touches_the_file(self, auth_client, app_ctx, carried_over_files):
        auth_client.post("/confirm_file_current", data={"name": "top.mp3"})

        # Loosely, because a filesystem timestamp comes from the kernel's coarse
        # clock and can land a few milliseconds behind time.time().
        top = next(p for p in carried_over_files if p.name == "top.mp3")
        assert os.stat(top).st_mtime == pytest.approx(time.time(), abs=60)

        health = perform_health_check()
        top_status = next(f for f in health["files"] if f["name"] == "top.mp3")
        assert top_status["status"] == "healthy"

    def test_confirming_one_file_leaves_the_others_alone(self, auth_client, carried_over_files):
        auth_client.post("/confirm_file_current", data={"name": "top.mp3"})

        others = [p for p in carried_over_files if p.name != "top.mp3"]
        assert all(os.stat(p).st_mtime == LONG_AGO for p in others)

    def test_confirming_all_clears_every_stale_file(self, auth_client, app_ctx, carried_over_files):
        auth_client.post("/confirm_file_current", data={"name": "all"})

        assert perform_health_check()["stale_count"] == 0

    def test_an_unknown_name_touches_nothing(self, auth_client, carried_over_files):
        response = auth_client.post(
            "/confirm_file_current", data={"name": "nonesuch.mp3"}, follow_redirects=True
        )

        assert b"Unknown file" in response.data
        assert all(os.stat(p).st_mtime == LONG_AGO for p in carried_over_files)

    def test_a_path_is_not_a_name(self, auth_client, app_ctx, carried_over_files):
        """Names are resolved against the list; a path from the form is not one."""
        top = next(p for p in carried_over_files if p.name == "top.mp3")

        response = auth_client.post(
            "/confirm_file_current", data={"name": str(top)}, follow_redirects=True
        )

        assert b"Unknown file" in response.data
        assert os.stat(top).st_mtime == LONG_AGO

    def test_confirming_a_missing_file_does_not_create_it(self, auth_client, carried_over_files):
        """An empty top.mp3 would pass the exists check and break conversion."""
        top = next(p for p in carried_over_files if p.name == "top.mp3")
        top.unlink()

        response = auth_client.post(
            "/confirm_file_current", data={"name": "top.mp3"}, follow_redirects=True
        )

        assert b"not there to confirm" in response.data
        assert not top.exists()


class TestFileDescriptions:
    """The media details shown beside each critical file."""

    def test_an_image_reports_its_size_and_format(self, tmp_path):
        from PIL import Image

        from gbtalks.libgbtalks import describe_image_file

        path = tmp_path / "icon.png"
        Image.new("RGBA", (300, 300)).save(path)

        details = dict(describe_image_file(path))

        assert details["Dimensions"] == "300 × 300 px"
        assert details["Format"] == "PNG"
        assert "Shape" not in details

    def test_a_non_square_image_says_so(self, tmp_path):
        """The cover art upload squares its output, so this one came from elsewhere."""
        from PIL import Image

        from gbtalks.libgbtalks import describe_image_file

        path = tmp_path / "icon.png"
        Image.new("RGBA", (400, 300)).save(path)

        assert "Not square" in dict(describe_image_file(path))["Shape"]

    def test_a_pdf_reports_its_version(self, tmp_path):
        from gbtalks.libgbtalks import describe_pdf_file

        path = tmp_path / "index.pdf"
        path.write_bytes(b"%PDF-1.7\nrest of it")

        assert dict(describe_pdf_file(path))["Format"] == "PDF 1.7"

    def test_something_that_is_not_a_pdf_is_rejected(self, tmp_path):
        from gbtalks.libgbtalks import describe_pdf_file

        path = tmp_path / "index.pdf"
        path.write_bytes(b"placeholder")

        with pytest.raises(ValueError):
            describe_pdf_file(path)

    def test_an_unreadable_file_is_reported_not_raised(self, tmp_path):
        """describe_file is for display; the health check's verdict is its own."""
        from gbtalks.libgbtalks import describe_file

        path = tmp_path / "top.mp3"
        path.write_bytes(b"placeholder")

        details, error = describe_file(path, "audio")

        assert details == []
        assert "MP3" in error

    def test_a_bad_file_does_not_make_the_check_unhealthy(self, app_ctx, carried_over_files):
        """A present, readable file is fine by the check whatever it contains."""
        for path in carried_over_files:
            os.utime(path, None)

        health = perform_health_check()

        assert all(f["status"] == "healthy" for f in health["files"])
        assert all(f["detail_error"] for f in health["files"])
        assert all(f["issues"] == [] for f in health["files"])


class TestCriticalFileServing:
    """/critical_file, which the previews and download buttons point at."""

    def test_it_requires_a_team_leader(self, client, carried_over_files):
        response = client.get("/critical_file?name=top.mp3")

        assert response.status_code in (302, 401)
        assert b"placeholder" not in response.data

    def test_it_serves_audio_inline_for_the_player(self, auth_client, carried_over_files):
        response = auth_client.get("/critical_file?name=top.mp3")

        assert response.status_code == 200
        assert response.mimetype == "audio/mpeg"
        assert "attachment" not in response.headers.get("Content-Disposition", "")
        assert response.data == b"placeholder"

    def test_download_sends_it_as_an_attachment(self, auth_client, carried_over_files):
        response = auth_client.get("/critical_file?name=top.mp3&download=1")

        disposition = response.headers["Content-Disposition"]
        assert disposition.startswith("attachment")
        assert "top.mp3" in disposition

    def test_the_pdf_is_downloadable(self, auth_client, app_ctx, carried_over_files):
        name = f"GB{app_ctx.config['GB_SHORT_YEAR']}-AllTalksIndex.pdf"

        response = auth_client.get(f"/critical_file?name={name}&download=1")

        assert response.status_code == 200
        assert response.mimetype == "application/pdf"

    def test_an_unknown_name_serves_nothing(self, auth_client, carried_over_files):
        response = auth_client.get(
            "/critical_file?name=nonesuch.mp3", follow_redirects=True
        )

        assert b"Unknown file" in response.data
        assert b"placeholder" not in response.data

    def test_a_path_is_not_a_name(self, auth_client, carried_over_files):
        """Names are resolved against the list, so a path fetches nothing."""
        top = next(p for p in carried_over_files if p.name == "top.mp3")

        response = auth_client.get(
            f"/critical_file?name={top}", follow_redirects=True
        )

        assert b"Unknown file" in response.data

    def test_a_missing_file_is_not_served(self, auth_client, carried_over_files):
        carried_over_files[0].unlink()

        response = auth_client.get(
            "/critical_file?name=top.mp3", follow_redirects=True
        )

        assert b"is not there" in response.data


class TestPreviewsOnThePage:

    def test_audio_files_get_a_player(self, auth_client, carried_over_files):
        response = auth_client.get("/health")

        assert b"<audio" in response.data
        assert b"/critical_file?name=top.mp3" in response.data

    def test_the_cover_art_gets_an_image(self, auth_client, carried_over_files):
        response = auth_client.get("/health")

        assert b"file-preview-image" in response.data
        assert b"name=alltalksicon.png" in response.data

    def test_every_file_gets_a_download_button(self, auth_client, app_ctx, carried_over_files):
        response = auth_client.get("/health")

        assert response.data.count(b"download=1") == len(carried_over_files)

    def test_a_missing_file_gets_no_preview(self, auth_client, carried_over_files):
        for path in carried_over_files:
            path.unlink()

        response = auth_client.get("/health")

        assert b"<audio" not in response.data
        assert b"download=1" not in response.data

    def test_the_image_details_are_shown(self, auth_client, carried_over_files):
        from PIL import Image

        icon = next(p for p in carried_over_files if p.name == "alltalksicon.png")
        Image.new("RGBA", (300, 300)).save(icon)

        response = auth_client.get("/health")

        assert "300 × 300 px".encode() in response.data

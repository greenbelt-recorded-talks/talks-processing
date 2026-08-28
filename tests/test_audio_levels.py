"""Loudness checking and re-levelling for the two carried-over jingles.

top.mp3 and tail.mp3 are bolted onto every processed talk, so they want to sit
at the loudness the talks themselves are cut to. The health check measures
them and says where they are; the re-level route rewrites one in place.

ffmpeg is not assumed to exist here - every test stubs the measurement, so
these run the same on a CI box with no audio tooling as they do on site.
"""

from pathlib import Path

import pytest

from gbtalks import libgbtalks
from gbtalks.libgbtalks import audio_level_check, relevel_audio

TARGET = -13.0
CEILING = -2.0


def stats(integrated, true_peak, lra=4.0):
    return {
        "integrated": integrated,
        "true_peak": true_peak,
        "lra": lra,
        "threshold": integrated - 10.0,
    }


@pytest.fixture
def measured(monkeypatch):
    """Make measure_loudness return whatever a test puts in the list."""
    queue = []

    def _measure(_path):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(libgbtalks, "measure_loudness", _measure)
    return queue


class TestAudioLevelCheck:
    """The verdict has to separate 'turn it up' from 'it has nowhere to go'."""

    def test_on_target_is_ok_and_offers_no_fix(self, measured):
        measured.append(stats(-13.2, -3.0))

        result = audio_level_check("top.mp3", TARGET, CEILING)

        assert result["status"] == "ok"
        assert result["fixable"] is False
        assert "-13 LUFS target" in result["message"]

    def test_quiet_with_headroom_can_simply_be_turned_up(self, measured):
        measured.append(stats(-17.0, -8.0))

        result = audio_level_check("top.mp3", TARGET, CEILING)

        assert result["status"] == "quiet"
        assert result["fixable"] is True
        assert result["limiting"] == 0.0
        assert "room to turn it up" in result["message"]

    def test_quiet_without_headroom_is_squashed_and_says_the_cost(self, measured):
        # 4.2 LU down, and already 0.9 dB past the ceiling: 5.1 dB of limiting.
        measured.append(stats(-17.2, -1.1))

        result = audio_level_check("top.mp3", TARGET, CEILING)

        assert result["status"] == "squashed"
        assert result["fixable"] is True
        assert result["limiting"] == pytest.approx(5.1, abs=0.05)
        assert "0.9 dB above the -2 dBTP ceiling" in result["message"]
        assert "limiting peaks by about 5.1 dB" in result["message"]

    def test_a_lot_of_limiting_suggests_a_recut_instead(self, measured):
        measured.append(stats(-17.2, -1.1))
        assert "re-cut with headroom" in audio_level_check(
            "top.mp3", TARGET, CEILING)["message"]

    def test_a_little_limiting_does_not(self, measured):
        # 1.5 LU down against 0.5 dB of headroom: 1.0 dB of limiting.
        measured.append(stats(-14.5, -2.5))
        assert "re-cut with headroom" not in audio_level_check(
            "top.mp3", TARGET, CEILING)["message"]

    def test_too_loud_is_always_fixable(self, measured):
        measured.append(stats(-9.0, -6.0))

        result = audio_level_check("top.mp3", TARGET, CEILING)

        assert result["status"] == "loud"
        assert result["fixable"] is True
        assert "4.0 LU above" in result["message"]

    def test_within_tolerance_counts_as_on_target(self, measured):
        measured.append(stats(-13.9, -3.0))
        assert audio_level_check("top.mp3", TARGET, CEILING,
                                 tolerance_lu=1.0)["status"] == "ok"

    def test_an_unmeasurable_file_says_so_rather_than_raising(self, monkeypatch):
        def _boom(_path):
            raise ValueError("ffmpeg is not installed here")

        monkeypatch.setattr(libgbtalks, "measure_loudness", _boom)

        result = audio_level_check("top.mp3", TARGET, CEILING)

        assert result["status"] == "unknown"
        assert result["fixable"] is False
        assert "ffmpeg is not installed" in result["message"]


class TestRelevelAudio:
    """Gain is solved for, because limiting costs loudness unpredictably."""

    @pytest.fixture
    def rendering(self, monkeypatch):
        """Record each render; hand back measurements in the order asked for.

        relevel_audio measures the original once, then measures each render,
        so `results` reads as [original, after first go, after second, ...].
        """
        calls = []
        results = []

        def _render(source, destination, gain_db, limit_dbtp=None):
            calls.append({"gain": gain_db, "limit": limit_dbtp})
            Path(destination).write_bytes(b"rendered-%d" % len(calls))

        monkeypatch.setattr(libgbtalks, "_render_at_gain", _render)
        monkeypatch.setattr(libgbtalks, "measure_loudness",
                            lambda _path: results.pop(0))
        return calls, results

    def test_it_stops_as_soon_as_it_lands_on_target(self, rendering):
        calls, results = rendering
        results.extend([stats(-17.0, -8.0), stats(-13.1, -4.1)])

        content, achieved = relevel_audio("top.mp3", TARGET, CEILING)

        assert len(calls) == 1
        assert calls[0]["gain"] == pytest.approx(4.0)
        assert achieved["integrated"] == -13.1
        assert content == b"rendered-1"

    def test_it_corrects_the_gain_when_limiting_ate_some(self, rendering):
        calls, results = rendering
        results.extend([
            stats(-17.2, -1.1),   # the original
            stats(-14.6, -2.4),   # first go, 1.6 LU short after limiting
            stats(-13.1, -2.4),   # corrected
        ])

        _, achieved = relevel_audio("top.mp3", TARGET, CEILING)

        assert len(calls) == 2
        assert calls[1]["gain"] == pytest.approx(calls[0]["gain"] + 1.6, abs=0.05)
        assert achieved["integrated"] == -13.1

    def test_it_gives_up_after_the_attempt_limit(self, rendering):
        calls, results = rendering
        results.extend([stats(-17.2, -1.1)] + [stats(-15.0, -2.4)] * 5)

        relevel_audio("top.mp3", TARGET, CEILING, attempts=3)

        assert len(calls) == 3

    def test_the_limiter_is_used_only_when_the_gain_will_not_fit(self, rendering):
        calls, results = rendering
        results.extend([stats(-17.0, -8.0), stats(-13.0, -4.0)])

        relevel_audio("top.mp3", TARGET, CEILING)

        # -8.0 dBTP plus 4 dB of gain is -4.0, comfortably under the ceiling.
        assert calls[0]["limit"] is None

    def test_the_limiter_is_used_when_it_will_not(self, rendering):
        calls, results = rendering
        results.extend([stats(-17.2, -1.1), stats(-13.0, -2.4)])

        relevel_audio("top.mp3", TARGET, CEILING)

        assert calls[0]["limit"] == CEILING


class TestRelevelRoute:
    """Rewriting a critical file in place, with a way back."""

    @pytest.fixture
    def jingle(self, app, monkeypatch):
        """top.mp3 on disk, with the audio work stubbed to a known result."""
        with app.app_context():
            path = Path(app.config["UPLOAD_DIR"]) / "top.mp3"
            backups = Path(app.config["BACKUP_DIR"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"the original jingle")

        # The temp storage is built once for the whole session, so an earlier
        # test's backup would otherwise still be sitting here.
        backups.mkdir(parents=True, exist_ok=True)
        for earlier in backups.glob("top-*.mp3"):
            earlier.unlink()

        from gbtalks import routes

        monkeypatch.setattr(
            routes, "relevel_audio",
            lambda *a, **kw: (b"the re-levelled jingle", stats(-13.1, -2.4)),
        )
        monkeypatch.setattr(
            routes, "audio_level_check",
            lambda *a, **kw: {"status": "squashed", "fixable": True,
                              "message": "off target", "integrated": -17.2,
                              "true_peak": -1.1, "gain": 4.2, "headroom": -0.9,
                              "limiting": 5.1},
        )
        return path, backups

    def test_it_rewrites_the_file_and_keeps_the_original(self, auth_client, jingle):
        path, backups = jingle

        response = auth_client.post(
            "/relevel_critical_file", data={"name": "top.mp3"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert path.read_bytes() == b"the re-levelled jingle"
        kept = list(backups.glob("top-*.mp3"))
        assert len(kept) == 1
        assert kept[0].read_bytes() == b"the original jingle"

    def test_it_reports_what_it_achieved(self, auth_client, jingle):
        response = auth_client.post(
            "/relevel_critical_file", data={"name": "top.mp3"},
            follow_redirects=True,
        )
        assert "-13.1 LUFS" in response.get_data(as_text=True)

    def test_it_leaves_no_temporary_file_behind(self, auth_client, jingle):
        path, _ = jingle

        auth_client.post("/relevel_critical_file", data={"name": "top.mp3"})

        assert sorted(p.name for p in path.parent.iterdir()) == ["top.mp3"]

    def test_a_file_with_no_level_to_check_is_refused(self, auth_client, jingle):
        response = auth_client.post(
            "/relevel_critical_file", data={"name": "alltalksicon.png"},
            follow_redirects=True,
        )
        assert "Unknown file" in response.get_data(as_text=True)

    def test_an_unknown_name_is_refused(self, auth_client, jingle):
        response = auth_client.post(
            "/relevel_critical_file", data={"name": "../../etc/passwd"},
            follow_redirects=True,
        )
        assert "Unknown file" in response.get_data(as_text=True)

    def test_a_missing_file_is_not_created(self, auth_client, jingle):
        path, _ = jingle
        path.unlink()

        response = auth_client.post(
            "/relevel_critical_file", data={"name": "top.mp3"},
            follow_redirects=True,
        )

        assert not path.exists()
        assert "not there to re-level" in response.get_data(as_text=True)

    def test_a_failed_render_leaves_the_file_alone(self, auth_client, jingle,
                                                   monkeypatch):
        path, backups = jingle
        from gbtalks import routes

        def _boom(*a, **kw):
            raise ValueError("ffmpeg is not installed here")

        monkeypatch.setattr(routes, "relevel_audio", _boom)

        response = auth_client.post(
            "/relevel_critical_file", data={"name": "top.mp3"},
            follow_redirects=True,
        )

        assert path.read_bytes() == b"the original jingle"
        assert list(backups.glob("top-*.mp3")) == []
        assert "ffmpeg is not installed here" in response.get_data(as_text=True)

    def test_it_needs_a_signed_in_team_leader(self, client, jingle):
        path, _ = jingle

        client.post("/relevel_critical_file", data={"name": "top.mp3"})

        assert path.read_bytes() == b"the original jingle"

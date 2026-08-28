"""Which talks `flask convert-talks` picks up, and how the normalise step fails.

The audio work itself is not exercised here - `process_talk` is stubbed out,
so what these cover is the selection step that decides what gets handed to it,
plus `normalise_audio`, whose whole job is turning a failed ffmpeg-normalize
into something that says so.
"""

import os
import subprocess

import pytest
from flask import current_app as app

from gbtalks import commands

# Whatever the configured levels happen to be, these are what the calls below
# hand over - the point of the tests is the failure handling, not the figures.
LEVELS = (-16.0, 11.0, -1.5)


@pytest.fixture
def selected(app, app_ctx, monkeypatch):
    """Run convert_talks with the audio work stubbed, return the chosen ids."""
    chosen = []

    class FakePool:
        def __init__(self, _processes):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def map(self, _func, iterable):
            chosen.extend(iterable)

    monkeypatch.setattr(commands, "Pool", FakePool)
    monkeypatch.setattr(commands.singleton, "SingleInstance", lambda **kw: object())

    def _run():
        result = app.test_cli_runner().invoke(commands.convert_talks)
        assert result.exit_code == 0, result.output
        # The runner captures stdout, so what the cron job would log is here
        # rather than in capsys.
        _run.output = result.output
        return chosen

    _run.output = ""
    return _run


def _edited(talk_id):
    """Drop an edited file in UPLOAD_DIR the way an editor's upload would."""
    name = f"gb26-{str(talk_id).zfill(3)}_EDITED.mp3"
    path = os.path.join(app.config["UPLOAD_DIR"], name)
    with open(path, "wb") as f:
        f.write(b"not really audio")
    return path


def _write(dirname, name):
    """Put an arbitrarily named file in one of the working directories."""
    key = {"uploads": "UPLOAD_DIR", "processed": "PROCESSED_DIR"}[dirname]
    path = os.path.join(app.config[key], name)
    with open(path, "wb") as f:
        f.write(b"not really audio")
    return path


def _processed(talk_id):
    name = f"GB26_{str(talk_id).zfill(3)}_A Talk_Sam Speaker.mp3"
    path = os.path.join(app.config["PROCESSED_DIR"], name)
    with open(path, "wb") as f:
        f.write(b"not really audio")
    return path


@pytest.fixture(autouse=True)
def clean_dirs(app_ctx):
    """Both directories are session-scoped, so leave them as they were found."""
    yield
    for key in ("UPLOAD_DIR", "PROCESSED_DIR"):
        for entry in os.scandir(app.config[key]):
            if entry.is_file():
                os.remove(entry.path)


class TestConvertTalksSelection:
    def test_cleared_talk_with_an_edited_file_is_picked_up(self, selected, make_talk):
        make_talk(talk_id=20, is_cleared=True)
        _edited(20)

        assert selected() == ["020"]

    def test_uncleared_talk_is_left_alone(self, selected, make_talk):
        make_talk(talk_id=21, is_cleared=False)
        _edited(21)

        assert selected() == []

    def test_talk_with_no_clearance_recorded_is_left_alone(self, selected, make_talk):
        # is_cleared is nullable, and a CSV without the column leaves it NULL.
        make_talk(talk_id=22)
        _edited(22)

        assert selected() == []

    def test_edited_file_with_no_talk_behind_it_is_skipped(self, selected):
        # An id in this year's format, but no such talk in the database.
        _edited(99)

        assert selected() == []

    def test_already_processed_talk_is_not_done_twice(self, selected, make_talk):
        make_talk(talk_id=23, is_cleared=True)
        _edited(23)
        _processed(23)

        assert selected() == []

    def test_only_the_cleared_ones_out_of_several(self, selected, make_talk):
        make_talk(talk_id=30, is_cleared=True)
        make_talk(talk_id=31, is_cleared=False)
        make_talk(talk_id=32, is_cleared=True)
        for talk_id in (30, 31, 32):
            _edited(talk_id)

        assert selected() == ["030", "032"]

    def test_three_digit_ids_are_matched(self, selected, make_talk):
        # zfill(3) is a no-op above 99, so this is where a padding mismatch
        # between the filename and the database would show up.
        make_talk(talk_id=101, is_cleared=True)
        _edited(101)

        assert selected() == ["101"]

    def test_nothing_to_do_is_not_an_error(self, selected):
        assert selected() == []


class TestConvertTalksFilenames:
    """Only files named the way get_path_for_file writes them are acted on."""

    def test_last_years_edited_file_is_ignored(self, selected, make_talk):
        # The old strip removed this year's prefix only, so gb25-013 survived
        # whole and went forward as a talk id of its own.
        make_talk(talk_id=13, is_cleared=True)
        _write("uploads", "gb25-013_EDITED.mp3")

        assert selected() == []

    def test_a_misnumbered_edited_file_is_ignored(self, selected, make_talk):
        # Two digits where there should be three. Silently reading it as talk
        # 20 would convert the wrong talk under the right name.
        make_talk(talk_id=20, is_cleared=True)
        _write("uploads", "gb26-20_EDITED.mp3")

        assert selected() == []

    def test_last_years_processed_file_does_not_block_this_years_talk(
        self, selected, make_talk
    ):
        make_talk(talk_id=20, is_cleared=True)
        _edited(20)
        _write("processed", "GB25_020_A Talk_Sam Speaker.mp3")

        assert selected() == ["020"]

    def test_a_stray_mp3_in_processed_does_not_stop_the_run(
        self, selected, make_talk
    ):
        # x.name.split("_")[1] raised IndexError on this and took the whole
        # run down with it.
        make_talk(talk_id=20, is_cleared=True)
        _edited(20)
        _write("processed", "notes.mp3")

        assert selected() == ["020"]

    def test_a_non_mp3_in_uploads_is_not_reported_as_skipped(self, selected):
        # top.mp3 and tail.mp3 live in here too, and are not edited files.
        _write("uploads", "top.mp3")
        _write("uploads", "tail.mp3")

        assert selected() == []


class TestConvertTalksReporting:
    """What is not converted has to be visible, or it is never chased up.

    The cron job pipes this into the journal, so naming a file here is the
    only sign anyone gets that an edit is sitting unused.
    """

    def test_an_unrecognised_file_is_named(self, selected):
        _write("uploads", "gb25-013_EDITED.mp3")
        selected()

        assert "Not an edited file for GB26 - ignoring:" in selected.output
        assert "gb25-013_EDITED.mp3" in selected.output

    def test_an_uncleared_talk_is_named(self, selected, make_talk):
        make_talk(talk_id=21, is_cleared=False)
        _edited(21)
        selected()

        assert "Edited, but not a cleared talk - not converting:" in selected.output
        assert "021" in selected.output

    def test_a_clean_run_says_none_of_it(self, selected, make_talk):
        make_talk(talk_id=20, is_cleared=True)
        _edited(20)
        selected()

        assert "020" in selected.output
        assert "ignoring" not in selected.output
        assert "not converting" not in selected.output


class TestProcessTalkFailures:
    """One bad talk costs one talk, not the rest of its pool chunk."""

    def test_a_failure_is_swallowed_and_reported(self, app_ctx, monkeypatch, capsys):
        def _boom(talk_id):
            raise RuntimeError("unreadable file")

        monkeypatch.setattr(commands, "_process_talk", _boom)

        commands.process_talk("020")

        captured = capsys.readouterr()
        assert "FAILED to process talk 020" in captured.out
        # The traceback goes to stderr, which the cron job folds into its log.
        assert "unreadable file" in captured.err

    def test_a_success_is_passed_through_quietly(self, app_ctx, monkeypatch, capsys):
        done = []
        monkeypatch.setattr(commands, "_process_talk", done.append)

        commands.process_talk("020")

        assert done == ["020"]
        assert "FAILED" not in capsys.readouterr().out


class TestNormaliseAudio:
    """A failed ffmpeg-normalize has to raise, and say what it said."""

    def test_a_non_zero_exit_raises_with_the_stderr_tail(self, monkeypatch, tmp_path):
        def _fail(command, **kwargs):
            raise subprocess.CalledProcessError(
                1, command, stderr="ERROR: Invalid loudness target\n"
            )

        monkeypatch.setattr(commands.subprocess, "run", _fail)

        with pytest.raises(RuntimeError) as raised:
            commands.normalise_audio("in.wav", str(tmp_path / "out.wav"), *LEVELS)

        assert "exited 1" in str(raised.value)
        assert "Invalid loudness target" in str(raised.value)

    def test_a_timeout_raises_rather_than_hanging_the_lock(self, monkeypatch, tmp_path):
        def _hang(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr=b"")

        monkeypatch.setattr(commands.subprocess, "run", _hang)

        with pytest.raises(RuntimeError, match="did not finish within"):
            commands.normalise_audio("in.wav", str(tmp_path / "out.wav"), *LEVELS)

    def test_a_missing_ffmpeg_normalize_says_which_tool_is_missing(
            self, monkeypatch, tmp_path):
        def _absent(command, **kwargs):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(commands.subprocess, "run", _absent)

        with pytest.raises(RuntimeError, match="ffmpeg-normalize is not on PATH"):
            commands.normalise_audio("in.wav", str(tmp_path / "out.wav"), *LEVELS)

    def test_a_clean_exit_that_wrote_nothing_still_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            commands.subprocess, "run", lambda command, **kwargs: None
        )

        with pytest.raises(RuntimeError, match="wrote no output"):
            commands.normalise_audio("in.wav", str(tmp_path / "out.wav"), *LEVELS)

    def test_a_written_output_is_accepted_quietly(self, monkeypatch, tmp_path):
        output = tmp_path / "out.wav"

        def _succeed(command, **kwargs):
            output.write_bytes(b"RIFF")

        monkeypatch.setattr(commands.subprocess, "run", _succeed)

        commands.normalise_audio("in.wav", str(output), *LEVELS)

    def test_the_call_carries_a_timeout_and_checks_its_exit(self, monkeypatch, tmp_path):
        seen = {}
        output = tmp_path / "out.wav"

        def _record(command, **kwargs):
            seen.update(kwargs, command=command)
            output.write_bytes(b"RIFF")

        monkeypatch.setattr(commands.subprocess, "run", _record)

        commands.normalise_audio("in.wav", str(output), *LEVELS)

        assert seen["check"] is True
        assert seen["timeout"] == commands.NORMALIZE_TIMEOUT_SECONDS
        assert seen["capture_output"] is True
        assert seen["command"][0] == "ffmpeg-normalize"

    def test_the_configured_levels_reach_the_command_line(self, monkeypatch,
                                                          tmp_path):
        seen = {}
        output = tmp_path / "out.wav"

        def _record(command, **kwargs):
            seen["command"] = command
            output.write_bytes(b"RIFF")

        monkeypatch.setattr(commands.subprocess, "run", _record)

        commands.normalise_audio("in.wav", str(output), -16.0, 11.0, -1.5)

        command = seen["command"]
        assert command[command.index("-t") + 1] == "-16.0"
        assert command[command.index("--loudness-range-target") + 1] == "11.0"
        assert command[command.index("-tp") + 1] == "-1.5"

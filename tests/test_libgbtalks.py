"""Tests for the pure helpers in gbtalks.libgbtalks."""

import os
from datetime import date, datetime

import pytest

from gbtalks.libgbtalks import (
    calculate_greenbelt_friday,
    character_mapping,
    default_gb_friday,
    festival_cycle_start,
    gb_time_to_datetime,
    get_cd_dir_for_talk,
    get_path_for_file,
    get_path_for_video_file,
)


class TestCalculateGreenbeltFriday:
    """The festival starts on the Friday before the late August bank holiday."""

    @pytest.mark.parametrize(
        ("year", "expected"),
        [
            (2023, date(2023, 8, 25)),
            (2024, date(2024, 8, 23)),
            (2025, date(2025, 8, 22)),
            (2026, date(2026, 8, 28)),  # last Monday is the 31st itself
            (2027, date(2027, 8, 27)),
            (2028, date(2028, 8, 25)),
        ],
    )
    def test_returns_friday_before_late_august_bank_holiday(self, year, expected):
        assert calculate_greenbelt_friday(year).date() == expected

    def test_result_is_always_a_friday(self):
        for year in range(2020, 2041):
            assert calculate_greenbelt_friday(year).weekday() == 4

    def test_config_default_matches_this_calculation(self):
        """config.Config's GB_FRIDAY default is this calculation.

        Both now call the one implementation in festival_dates, so this guards
        the wiring rather than two copies of the arithmetic. Reloading config
        with GB_FRIDAY unset re-runs its class body so we see the computed
        default rather than the value the test environment pins.
        """
        import importlib

        import config

        pinned = os.environ.pop("GB_FRIDAY", None)
        try:
            recomputed = importlib.reload(config)
            expected = calculate_greenbelt_friday(datetime.now().year).strftime("%Y-%m-%d")
            assert recomputed.Config.GB_FRIDAY == expected
        finally:
            if pinned is not None:
                os.environ["GB_FRIDAY"] = pinned
            importlib.reload(config)

    def test_config_treats_a_blank_pin_as_unset(self):
        """GB_FRIDAY= with nothing after it means "follow the calendar"."""
        import importlib

        import config

        pinned = os.environ.get("GB_FRIDAY")
        os.environ["GB_FRIDAY"] = ""
        try:
            recomputed = importlib.reload(config)
            expected = calculate_greenbelt_friday(datetime.now().year).strftime("%Y-%m-%d")
            assert recomputed.Config.GB_FRIDAY == expected
        finally:
            if pinned is not None:
                os.environ["GB_FRIDAY"] = pinned
            else:
                del os.environ["GB_FRIDAY"]
            importlib.reload(config)


class TestDefaultGbFriday:
    """The default follows the calendar year, not the festival cycle."""

    def test_is_this_calendar_years_festival(self):
        for year in (2025, 2026, 2027):
            now = datetime(year, 3, 1)
            assert default_gb_friday(now) == calculate_greenbelt_friday(year).strftime(
                "%Y-%m-%d"
            )

    def test_still_names_this_years_festival_after_it_has_finished(self):
        """September is spent processing August's talks, and the filenames want
        the year those talks came from - so this does not follow
        festival_cycle_start over to the next year."""
        assert default_gb_friday(datetime(2026, 9, 15)) == "2026-08-28"
        assert festival_cycle_start(datetime(2026, 9, 15)) == datetime(2026, 9, 1)


class TestGbTimeToDatetime:
    """Greenbelt days are named, and times arrive in several formats."""

    @pytest.mark.parametrize(
        ("day", "expected_date"),
        [
            ("Friday", date(2026, 8, 28)),
            ("Saturday", date(2026, 8, 29)),
            ("Sunday", date(2026, 8, 30)),
            ("Monday", date(2026, 8, 31)),
        ],
    )
    def test_named_days_offset_from_greenbelt_friday(self, app_ctx, day, expected_date):
        assert gb_time_to_datetime(day, "10:00").date() == expected_date

    @pytest.mark.parametrize(
        ("time_string", "expected"),
        [
            ("10:00 AM", (10, 0)),
            ("02:30 PM", (14, 30)),
            ("14:30:00", (14, 30)),
            ("14:30", (14, 30)),
            ("09:05", (9, 5)),
        ],
    )
    def test_accepts_each_supported_time_format(self, app_ctx, time_string, expected):
        result = gb_time_to_datetime("Saturday", time_string)
        assert (result.hour, result.minute) == expected

    def test_falls_back_to_parsing_an_explicit_date(self, app_ctx):
        """An unrecognised day is treated as a dd/mm/yy date instead."""
        result = gb_time_to_datetime("29/08/26", "14:30")
        assert result == datetime(2026, 8, 29, 14, 30)

    def test_rejects_an_unparseable_time(self, app_ctx):
        with pytest.raises(ValueError):
            gb_time_to_datetime("Saturday", "half past ten")


class TestGetPathForFile:
    def test_raw_and_edited_use_the_zero_padded_id(self, app_ctx):
        raw = get_path_for_file(7, "raw")
        edited = get_path_for_file(7, "edited")

        assert raw.endswith("/gb26-007_RAW.mp3")
        assert edited.endswith("/gb26-007_EDITED.mp3")

    def test_processed_includes_title_and_speaker(self, app_ctx):
        path = get_path_for_file(7, "processed", title="My Talk", speaker="Sam Speaker")
        assert path.endswith("/GB26_007_My Talk_Sam Speaker.mp3")

    def test_processed_collapses_multiple_speakers(self, app_ctx):
        path = get_path_for_file(7, "processed", title="My Talk", speaker="Sam, Alex, Jo")
        assert "Sam & others" in path

    def test_processed_replaces_characters_fat_filesystems_reject(self, app_ctx):
        path = get_path_for_file(7, "processed", title="What/When: Why?", speaker="Sam")

        for forbidden in '"*/:<>?\\|':
            assert forbidden not in path.rsplit("/", 1)[-1]

    def test_processed_truncates_long_titles_and_speakers(self, app_ctx):
        path = get_path_for_file(7, "processed", title="T" * 200, speaker="S" * 200)
        assert "T" * 120 in path
        assert "T" * 121 not in path

    def test_web_mp3_path(self, app_ctx):
        assert get_path_for_file(7, "web_mp3").endswith("/gb26-007mp3.mp3")

    def test_recorder_notes_requires_a_string_id(self, app_ctx):
        """Unlike every other branch, this one concatenates talk_id directly."""
        assert get_path_for_file("7", "recorder_notes").endswith("/gb26-7recorder_notes.jpg")

        with pytest.raises(TypeError):
            get_path_for_file(7, "recorder_notes")


def test_get_path_for_video_file(app_ctx):
    assert get_path_for_video_file(7, "mp4").endswith("/gb26-007_VIDEO.mp4")


def test_get_cd_dir_for_talk(app_ctx):
    assert get_cd_dir_for_talk(7).endswith("/gb26-007/")


def test_character_mapping_covers_every_fat_reserved_character():
    translated = '"*/:<>?\\|'.translate(character_mapping)
    for forbidden in '"*/:<>?\\|':
        assert forbidden not in translated

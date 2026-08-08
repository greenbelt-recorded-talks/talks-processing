"""Tests for the canonical talks CSV format."""

import io
from datetime import datetime

import pytest

from gbtalks.talks_csv import TalksCsvError, parse_talks_csv

HEADER = (
    "id,title,description,speaker,day,venue,start_time,end_time,"
    "is_priority,is_rotaed,is_cleared,"
    "has_explicit_warning_sticker,has_distressing_content_warning_sticker,"
    "has_technical_issues_sticker,has_copyright_removal_sticker,"
    "recorder_name,editor_name"
)

ROW = "1,A Talk,About things,Sam Speaker,Saturday,The Big Top,10:00,11:00,Yes,Yes,Yes,No,No,No,No,,"


def parse(*rows, header=HEADER):
    return parse_talks_csv(io.StringIO("\n".join([header, *rows]) + "\n"))


class TestRequiredColumns:
    def test_names_every_missing_column(self):
        with pytest.raises(TalksCsvError) as exc:
            parse("1,A Talk", header="id,title")

        message = str(exc.value)
        for column in ("speaker", "day", "start_time", "end_time", "venue"):
            assert column in message

    def test_rejects_an_empty_file(self):
        with pytest.raises(TalksCsvError, match="empty"):
            parse_talks_csv(io.StringIO(""))

    def test_rejects_a_file_with_only_a_header(self):
        with pytest.raises(TalksCsvError, match="No talks"):
            parse()

    def test_column_order_does_not_matter(self, app_ctx):
        reordered = "venue,day,end_time,start_time,speaker,title,id"
        talks = parse("The Big Top,Saturday,11:00,10:00,Sam,A Talk,1", header=reordered)

        assert talks[0]["title"] == "A Talk"
        assert talks[0]["venue"] == "The Big Top"

    def test_optional_columns_default_to_false_and_none(self, app_ctx):
        minimal = "id,title,speaker,day,venue,start_time,end_time"
        talk = parse("1,A Talk,Sam,Saturday,The Big Top,10:00,11:00", header=minimal)[0]

        assert talk["is_priority"] is False
        assert talk["is_rotaed"] is False
        assert talk["has_explicit_warning_sticker"] is False
        assert talk["recorder_name"] is None
        assert talk["description"] == ""


class TestBooleans:
    @pytest.mark.parametrize("value", ["Yes", "yes", "Y", "true", "TRUE", "1", "t"])
    def test_true_spellings(self, app_ctx, value):
        assert parse(ROW.replace(",Yes,Yes,Yes,", f",{value},Yes,Yes,"))[0]["is_priority"] is True

    @pytest.mark.parametrize("value", ["No", "no", "N", "false", "0", "f", ""])
    def test_false_spellings(self, app_ctx, value):
        assert parse(ROW.replace(",Yes,Yes,Yes,", f",{value},Yes,Yes,"))[0]["is_priority"] is False

    def test_unreadable_value_names_the_row_and_column(self, app_ctx):
        with pytest.raises(TalksCsvError, match="Row 2.*is_priority.*maybe"):
            parse(ROW.replace(",Yes,Yes,Yes,", ",maybe,Yes,Yes,"))


class TestTalkIds:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1", 1), ("007", 7), ("GB26-001", 1), ("GB26-123", 123), (" 42 ", 42)],
    )
    def test_accepted_id_forms(self, app_ctx, value, expected):
        assert parse(ROW.replace("1,A Talk", f"{value},A Talk", 1))[0]["id"] == expected

    @pytest.mark.parametrize("value", ["", "abc", "GB26-xyz"])
    def test_rejected_id_forms(self, app_ctx, value):
        with pytest.raises(TalksCsvError, match="Row 2"):
            parse(ROW.replace("1,A Talk", f"{value},A Talk", 1))


class TestTimes:
    def test_time_of_day_resolves_against_the_day_column(self, app_ctx):
        talk = parse(ROW)[0]
        assert talk["start_time"] == datetime(2026, 8, 29, 10, 0)  # GB Friday + 1
        assert talk["end_time"] == datetime(2026, 8, 29, 11, 0)

    @pytest.mark.parametrize("value", ["10:00", "10:00:00", "10:00 AM"])
    def test_time_of_day_formats(self, app_ctx, value):
        talk = parse(ROW.replace(",10:00,11:00,", f",{value},11:00,"))[0]
        assert talk["start_time"].hour == 10

    def test_absolute_timestamps_are_used_verbatim(self, app_ctx):
        talk = parse(
            ROW.replace(",10:00,11:00,", ",2024-08-23 09:00:00,2024-08-23 10:00:00,")
        )[0]
        assert talk["start_time"] == datetime(2024, 8, 23, 9, 0)

    @pytest.mark.parametrize(
        ("start", "end"),
        [
            ("15:00", "14:00"),  # transposed
            ("11:00", "11:00"),  # zero length
            ("23:30", "00:30"),  # would be a talk running past midnight
        ],
    )
    def test_end_must_be_after_start(self, app_ctx, start, end):
        """Talks run inside one day, so these are all errors."""
        with pytest.raises(TalksCsvError, match="not after"):
            parse(ROW.replace(",10:00,11:00,", f",{start},{end},"))

    def test_absolute_timestamps_must_also_be_ordered(self, app_ctx):
        with pytest.raises(TalksCsvError, match="not after"):
            parse(
                ROW.replace(",10:00,11:00,", ",2024-08-23 23:30:00,2024-08-23 00:30:00,")
            )

    def test_unparseable_time_names_the_row(self, app_ctx):
        with pytest.raises(TalksCsvError, match="Row 2.*start_time"):
            parse(ROW.replace(",10:00,11:00,", ",half past ten,11:00,"))


class TestRowHandling:
    def test_blank_lines_are_skipped(self, app_ctx):
        talks = parse(ROW, ",,,,,,,,,,,,,,,,", ROW.replace("1,A Talk", "2,Another", 1))
        assert [t["id"] for t in talks] == [1, 2]

    def test_row_numbers_match_the_file(self, app_ctx):
        """The bad row is the third line of the file, header included."""
        with pytest.raises(TalksCsvError, match="Row 3"):
            parse(ROW, ROW.replace(",Yes,Yes,Yes,", ",maybe,Yes,Yes,"))


class TestSampleData:
    """The shipped sample data must be a valid example of the real format."""

    def test_parses(self, app_ctx):
        with open("sample_data/talks.csv", newline="", encoding="utf-8") as f:
            talks = parse_talks_csv(f)

        assert len(talks) == 75

    def test_has_talks_flagged_for_the_rota(self, app_ctx):
        """Without this the rota generator has nothing to do - see the 0/28 report."""
        with open("sample_data/talks.csv", newline="", encoding="utf-8") as f:
            talks = parse_talks_csv(f)

        rotaed = [t for t in talks if t["is_rotaed"]]
        assert len(rotaed) > 0
        assert len(rotaed) < len(talks), "some talks should exercise the skip path"

    def test_every_talk_runs_within_the_festival_day(self, app_ctx):
        """Programming runs roughly 08:00-22:00, and never past midnight."""
        with open("sample_data/talks.csv", newline="", encoding="utf-8") as f:
            talks = parse_talks_csv(f)

        for talk in talks:
            assert talk["start_time"].hour >= 8, talk["id"]
            assert talk["end_time"] <= talk["end_time"].replace(hour=22, minute=0), talk["id"]
            assert talk["start_time"].date() == talk["end_time"].date(), talk["id"]

    def test_dates_track_the_configured_festival_year(self, app_ctx):
        """Times of day, not hard-coded dates, so the file does not go stale."""
        with open("sample_data/talks.csv", newline="", encoding="utf-8") as f:
            talks = parse_talks_csv(f)

        assert all(t["start_time"].year == 2026 for t in talks)

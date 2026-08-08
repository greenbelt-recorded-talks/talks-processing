"""The canonical talks CSV format.

One parser serves both ways talks enter the database - the /talks upload and
the load-sample-data command - so the two cannot drift apart again.

Columns are matched by header name, not position, and are named after the Talk
model fields. Only these are required:

    id, title, speaker, day, start_time, end_time, venue

Everything else is optional and defaults to empty/False. Values are read
leniently, because the file usually comes out of the festival programme export
rather than being written by hand:

    booleans    Yes/No, Y/N, true/false, 1/0, or blank for False
    id          a plain number, or a prefixed reference like GB26-001
    start_time  an absolute "YYYY-MM-DD HH:MM[:SS]" timestamp, or a time of day
    end_time    ("7:00 PM", "19:00") resolved against the day column

Preferring a time of day is what keeps a file usable across festivals: the date
comes from the day column and the configured GB_FRIDAY, so the same file still
works next year.
"""

import csv
from datetime import datetime, timedelta

from .libgbtalks import gb_time_to_datetime

# An end time before its start is read as running past midnight, but only if the
# result is a plausible length. Beyond this it is treated as a transposed typo.
MAX_TALK_DURATION = timedelta(hours=6)

REQUIRED_COLUMNS = (
    "id",
    "title",
    "speaker",
    "day",
    "start_time",
    "end_time",
    "venue",
)

BOOLEAN_COLUMNS = (
    "is_priority",
    "is_rotaed",
    "is_cleared",
    "has_explicit_warning_sticker",
    "has_distressing_content_warning_sticker",
    "has_technical_issues_sticker",
    "has_copyright_removal_sticker",
)

TEXT_COLUMNS = ("title", "description", "speaker", "day", "venue")

NULLABLE_COLUMNS = ("recorder_name", "editor_name")

ALL_COLUMNS = ("id", *TEXT_COLUMNS, "start_time", "end_time", *BOOLEAN_COLUMNS, *NULLABLE_COLUMNS)

_TRUE_VALUES = {"yes", "y", "true", "t", "1"}
_FALSE_VALUES = {"no", "n", "false", "f", "0", ""}

_ABSOLUTE_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


class TalksCsvError(ValueError):
    """Raised when a talks CSV cannot be parsed."""


def parse_boolean(value, column, row_number):
    normalised = (value or "").strip().lower()

    if normalised in _TRUE_VALUES:
        return True
    if normalised in _FALSE_VALUES:
        return False

    raise TalksCsvError(
        f"Row {row_number}: could not read {column!r} value {value!r}. "
        f"Use Yes or No."
    )


def parse_talk_id(value, row_number):
    """Accept a plain number or a prefixed reference such as GB26-001."""
    reference = (value or "").strip()

    if not reference:
        raise TalksCsvError(f"Row {row_number}: missing a talk id.")

    # "GB26-001" -> "001"; a plain "17" is left alone.
    candidate = reference.rsplit("-", 1)[-1]

    try:
        return int(candidate)
    except ValueError:
        raise TalksCsvError(
            f"Row {row_number}: could not read a talk id from {value!r}. "
            f"Use a number, or a reference like GB26-001."
        ) from None


def parse_timestamp(day, value, column, row_number):
    """Read a start/end value.

    Returns (datetime, is_time_of_day). The flag matters because a time of day
    carries no date, so an end time earlier than its start means the talk runs
    past midnight - whereas an absolute timestamp saying that is just wrong.
    """
    timestamp = (value or "").strip()

    if not timestamp:
        raise TalksCsvError(f"Row {row_number}: missing a {column!r} value.")

    for time_format in _ABSOLUTE_TIME_FORMATS:
        try:
            return datetime.strptime(timestamp, time_format), False
        except ValueError:
            continue

    try:
        return gb_time_to_datetime(day, timestamp), True
    except (ValueError, TypeError):
        raise TalksCsvError(
            f"Row {row_number}: could not read {column!r} value {value!r} "
            f"for day {day!r}. Use a time like '7:00 PM' or '19:00', or a full "
            f"'YYYY-MM-DD HH:MM:SS' timestamp."
        ) from None


def parse_talks_csv(fileobj):
    """Parse a talks CSV into a list of Talk keyword-argument dicts.

    Raises TalksCsvError, with the offending row and column named, rather than
    letting a malformed file surface as an IndexError or a 500.
    """
    reader = csv.DictReader(fileobj)

    if reader.fieldnames is None:
        raise TalksCsvError("The file is empty - expected a header row.")

    headers = {name.strip() for name in reader.fieldnames if name}
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise TalksCsvError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Expected a header row containing: {', '.join(REQUIRED_COLUMNS)}."
        )

    talks = []

    # Start at 2 so the number matches the line in the file, header included.
    for row_number, row in enumerate(reader, start=2):
        row = {(k.strip() if k else k): v for k, v in row.items()}

        if all(not (value or "").strip() for value in row.values()):
            continue  # tolerate blank lines

        day = (row.get("day") or "").strip()

        start_time, start_is_time_of_day = parse_timestamp(
            day, row.get("start_time"), "start_time", row_number
        )
        end_time, end_is_time_of_day = parse_timestamp(
            day, row.get("end_time"), "end_time", row_number
        )

        # A late-night talk written as 23:30 -> 00:30 ends on the following day.
        # Only times of day can mean this; an absolute timestamp says its date.
        if (
            start_is_time_of_day
            and end_is_time_of_day
            and end_time <= start_time
            and (end_time + timedelta(days=1)) - start_time <= MAX_TALK_DURATION
        ):
            end_time += timedelta(days=1)

        talk = {
            "id": parse_talk_id(row.get("id"), row_number),
            "day": day,
            "start_time": start_time,
            "end_time": end_time,
        }

        for column in TEXT_COLUMNS:
            if column == "day":
                continue
            talk[column] = (row.get(column) or "").strip()

        for column in BOOLEAN_COLUMNS:
            talk[column] = parse_boolean(row.get(column), column, row_number)

        for column in NULLABLE_COLUMNS:
            talk[column] = (row.get(column) or "").strip() or None

        if talk["end_time"] <= talk["start_time"]:
            raise TalksCsvError(
                f"Row {row_number}: end_time {row.get('end_time')!r} is not after "
                f"start_time {row.get('start_time')!r}."
            )

        talks.append(talk)

    if not talks:
        raise TalksCsvError("No talks found in the file.")

    return talks

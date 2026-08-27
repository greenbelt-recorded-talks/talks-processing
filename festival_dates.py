"""Greenbelt's dates, worked out from the calendar.

Lives at the top level, beside config.py, because config.py needs it and must
not import the application package. gbtalks.libgbtalks re-exports
calculate_greenbelt_friday so the app keeps importing it from where it always
has.
"""

from datetime import datetime, timedelta


def calculate_greenbelt_friday(year):
    """
    Calculate the Friday before the UK Summer Bank Holiday (last Monday in August).
    Greenbelt Festival traditionally starts on this Friday.
    """
    # Find last Monday in August (Aug 31 - weekday gives us the Monday)
    last_day_of_august = datetime(year, 8, 31)
    weekday = last_day_of_august.weekday()  # 0=Monday, 1=Tuesday, etc.
    last_monday = last_day_of_august - timedelta(days=weekday)

    # Go back 3 days from that Monday to get the Friday before
    greenbelt_friday = last_monday - timedelta(days=3)

    return greenbelt_friday


def default_gb_friday(now=None):
    """
    GB_FRIDAY when nothing has pinned it: this calendar year's festival.

    Deliberately the calendar year, and deliberately *not* festival_cycle_start's
    notion of the cycle. The two disagree from the Tuesday after the festival
    until New Year, and for this value the calendar year is the right answer:
    September is spent turning August's recordings into MP3s, and every one of
    those filenames wants the year of the festival they came from.

    The turn of the year is therefore the one moment this default moves under
    you. If a year's talks are still unfinished in January, that is when to pin
    GB_FRIDAY in .env - which is what the override is for.
    """
    if now is None:
        now = datetime.now()

    return calculate_greenbelt_friday(now.year).strftime("%Y-%m-%d")

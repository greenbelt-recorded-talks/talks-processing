"""Tests for the rota assignment algorithm.

This is the most intricate logic in the codebase and the least safe to change
blind, so these tests pin down the current behaviour in detail - including the
places where that behaviour looks wrong. Tests covering known bugs say so.
"""

from datetime import time

import pytest

from gbtalks.models import Talk
from gbtalks.rota.routes import (
    clear_rota,
    find_recorder_for_talk,
    recorder_is_maxed_out_for_day,
    talk_would_clash,
)


class TestTalkWouldClash:
    """A talk clashes if it overlaps an existing one, plus a 20 minute gap.

    The worked examples in the source comment use an existing 16:00-17:00 talk.
    """

    @pytest.fixture
    def recorder_with_4pm_talk(self, make_recorder, make_talk):
        recorder = make_recorder(name="Robin Recorder")
        make_talk(talk_id=1, start="16:00", end="17:00", recorder_name=recorder.name)
        return recorder

    def test_talk_starting_inside_the_gap_clashes(
        self, recorder_with_4pm_talk, make_talk
    ):
        candidate = make_talk(talk_id=2, start="17:00", end="18:00")
        assert talk_would_clash(recorder_with_4pm_talk, candidate) is True

    def test_talk_starting_after_the_gap_does_not_clash(
        self, recorder_with_4pm_talk, make_talk
    ):
        """The comment states explicitly that 17:30 is clear."""
        candidate = make_talk(talk_id=2, start="17:30", end="18:30")
        assert talk_would_clash(recorder_with_4pm_talk, candidate) is False

    def test_talk_ending_inside_the_existing_talk_clashes(
        self, recorder_with_4pm_talk, make_talk
    ):
        candidate = make_talk(talk_id=2, start="15:00", end="16:00")
        assert talk_would_clash(recorder_with_4pm_talk, candidate) is True

    def test_talk_on_an_earlier_day_does_not_clash(
        self, recorder_with_4pm_talk, make_talk
    ):
        candidate = make_talk(talk_id=2, day="Friday", start="16:00", end="17:00")
        assert talk_would_clash(recorder_with_4pm_talk, candidate) is False

    def test_recorder_with_no_talks_never_clashes(self, make_recorder, make_talk):
        recorder = make_recorder(name="Idle Ian")
        candidate = make_talk(talk_id=2, start="16:00", end="17:00")
        assert talk_would_clash(recorder, candidate) is False


class TestRecorderIsMaxedOutForDay:
    """Capacity is max_shifts_per_day * max_talks_per_shift (default 2 * 2)."""

    def test_recorder_under_capacity(self, make_recorder, make_talk):
        recorder = make_recorder(name="Robin Recorder", max_shifts_per_day=2)
        make_talk(talk_id=1, start="09:00", end="10:00", recorder_name=recorder.name)
        candidate = make_talk(talk_id=9, start="16:00", end="17:00")

        assert recorder_is_maxed_out_for_day(recorder, candidate) is False

    def test_recorder_at_capacity(self, make_recorder, make_talk):
        recorder = make_recorder(name="Robin Recorder", max_shifts_per_day=2)
        for i, start in enumerate(["09:00", "11:00", "13:00", "15:00"], start=1):
            make_talk(
                talk_id=i,
                start=start,
                end=f"{int(start[:2]) + 1:02d}:00",
                recorder_name=recorder.name,
            )
        candidate = make_talk(talk_id=9, start="19:00", end="20:00")

        assert recorder_is_maxed_out_for_day(recorder, candidate) is True

    def test_capacity_is_counted_per_day(self, make_recorder, make_talk):
        """Four talks on Saturday must not block a Sunday talk."""
        recorder = make_recorder(name="Robin Recorder", max_shifts_per_day=2)
        for i, start in enumerate(["09:00", "11:00", "13:00", "15:00"], start=1):
            make_talk(
                talk_id=i,
                day="Saturday",
                start=start,
                end=f"{int(start[:2]) + 1:02d}:00",
                recorder_name=recorder.name,
            )
        candidate = make_talk(talk_id=9, day="Sunday", start="09:00", end="10:00")

        assert recorder_is_maxed_out_for_day(recorder, candidate) is False


class TestFindRecorderForTalk:
    def test_assigns_a_free_recorder(self, make_recorder, make_talk):
        make_recorder(name="Robin Recorder")
        talk = make_talk(talk_id=1)

        result = find_recorder_for_talk(talk)

        assert result.name == "Robin Recorder"
        assert talk.recorder_name == "Robin Recorder"

    def test_prefers_the_recorder_with_fewest_talks(self, make_recorder, make_talk):
        busy = make_recorder(name="Busy Bea")
        make_recorder(name="Free Fred")
        make_talk(talk_id=1, start="09:00", end="10:00", recorder_name=busy.name)

        talk = make_talk(talk_id=2, start="14:00", end="15:00")
        find_recorder_for_talk(talk)

        assert talk.recorder_name == "Free Fred"

    def test_respects_earliest_start_time(self, make_recorder, make_talk):
        make_recorder(name="Late Riser", earliest_start_time=time(12, 0))
        talk = make_talk(talk_id=1, start="09:00", end="10:00")

        find_recorder_for_talk(talk)

        assert talk.recorder_name is None

    def test_respects_latest_end_time(self, make_recorder, make_talk):
        make_recorder(name="Early Finisher", latest_end_time=time(15, 0))
        talk = make_talk(talk_id=1, start="16:00", end="17:00")

        find_recorder_for_talk(talk)

        assert talk.recorder_name is None

    def test_time_constraints_still_allow_talks_inside_the_window(
        self, make_recorder, make_talk
    ):
        make_recorder(
            name="Middle Of The Day",
            earliest_start_time=time(10, 0),
            latest_end_time=time(16, 0),
        )
        talk = make_talk(talk_id=1, start="12:00", end="13:00")

        find_recorder_for_talk(talk)

        assert talk.recorder_name == "Middle Of The Day"

    def test_returns_none_when_no_recorder_is_eligible(self, make_recorder, make_talk):
        """A rejected candidate must not be reported as the assigned recorder.

        Callers use the return value to assign follow-on talks in the same
        venue, and that path does not re-check availability windows - so
        returning a rejected recorder let those constraints be bypassed.
        """
        make_recorder(name="Late Riser", earliest_start_time=time(12, 0))
        talk = make_talk(talk_id=1, start="09:00", end="10:00")

        result = find_recorder_for_talk(talk)

        assert talk.recorder_name is None
        assert result is None

    def test_returns_none_when_every_recorder_is_rejected(self, make_recorder, make_talk):
        make_recorder(name="Late Riser", earliest_start_time=time(12, 0))
        make_recorder(name="Early Finisher", latest_end_time=time(8, 0))
        talk = make_talk(talk_id=1, start="09:00", end="10:00")

        assert find_recorder_for_talk(talk) is None

    def test_returns_none_when_there_are_no_recorders_at_all(self, make_talk):
        talk = make_talk(talk_id=1)
        assert find_recorder_for_talk(talk) is None


class TestClearRota:
    def test_removes_every_assignment(self, db, make_recorder, make_talk):
        make_recorder(name="Robin Recorder")
        make_talk(talk_id=1, recorder_name="Robin Recorder")
        make_talk(talk_id=2, start="14:00", end="15:00", recorder_name="Robin Recorder")

        clear_rota()

        assert db.session.get(Talk, 1).recorder_name is None
        assert db.session.get(Talk, 2).recorder_name is None

    def test_leaves_the_talks_themselves_intact(self, db, make_recorder, make_talk):
        make_recorder(name="Robin Recorder")
        make_talk(talk_id=1, title="Keep Me", recorder_name="Robin Recorder")

        clear_rota()

        assert db.session.get(Talk, 1).title == "Keep Me"

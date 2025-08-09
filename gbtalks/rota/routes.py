from . import rota_blueprint

from flask import (
    request,
    redirect,
    url_for,
    render_template,
    flash,
)
from datetime import datetime, timedelta
from flask import current_app as app
from gbtalks.models import db, Talk, Recorder, RotaSettings

def talk_would_clash(recorder, talk):
    # A talk clashes if it starts while the recorder is currently recording, or within the configured gap
    minimum_time_between_talks = RotaSettings.get_value('minimum_time_between_talks', 20)  # Default: 20 minutes

# Examples:
# Recorder has existing talk at 16:00. Candidate talk is at 17:00.
# First condition:
# Candidate talk clashes because:
# * It starts after 16:00
# AND
# * It starts before 17:20 (assuming a 1h talk)
#
# Second condition:
# Candidate talk clashes because:
# * It ends after 16:00
# AND
# * It ends before 17:20 (assuming a 1h talk)
#
# A talk at 17:30 would not clash. 
#

    for existing_talk in recorder.talks:
        if existing_talk.start_time <= talk.start_time <= (
            existing_talk.end_time + timedelta(minutes=minimum_time_between_talks)
        ) or existing_talk.start_time <= talk.end_time <= (
            existing_talk.end_time + timedelta(minutes=minimum_time_between_talks)
        ):
            return True

    return False


def recorder_is_maxed_out_for_day(recorder, talk):
    # Maximum talks per day = max shifts per day * max talks per shift
    max_talks_per_shift = RotaSettings.get_value('max_talks_per_shift', 2)  # Default: 2 talks per shift maximum
    candidates_max_talks = recorder.max_shifts_per_day * max_talks_per_shift
    candidates_talks_on_this_day = 0
    for candidates_talk in recorder.talks:
        if candidates_talk.start_time.day == talk.start_time.day:
            candidates_talks_on_this_day += 1

    if candidates_talks_on_this_day >= candidates_max_talks:
        return True
    else:
        return False


def recorder_shifts_exceeded(recorder, candidate_talk):
    # The shift pattern is up to three hours per shift, with three hours off between, up to the maximum number of shifts the recorder can do per day

    day = candidate_talk.start_time.day()

    shifts = []

    for talk in recorder.talks:
        if talk.start_time.day() != day:
            continue


def talk_would_break_shift_pattern(recorder, candidate_talk):
    # make sure that if this talk is assigned, we don't violate any of the shift rules
    # - prepare the list of talks that would result if this talk were allocated
    # - check that there are no more shift_length groups containing talks than the candidate is allowed shifts
    # - check that the shift groups are more than break_between_shifts apart
    
    shift_length = RotaSettings.get_value('shift_length', 3)  # Default: 3 hours
    break_between_shifts = RotaSettings.get_value('break_between_shifts', 2)  # Default: 2 hours

    # Make a list of what the candidate's day would look like if the talk was assigned
    talks_on_this_day_if_talk_assigned = []
    for talk in Talk.query.filter(
        Talk.recorded_by == recorder,
        Talk.start_time
        > datetime(
            candidate_talk.start_time.year,
            candidate_talk.start_time.month,
            candidate_talk.start_time.day,
            0,
            0,
            0,
        ),
        Talk.start_time
        < datetime(
            candidate_talk.start_time.year,
            candidate_talk.start_time.month,
            candidate_talk.start_time.day,
            23,
            59,
            59,
        ),
    ):
        talks_on_this_day_if_talk_assigned.append(talk)

    talks_on_this_day_if_talk_assigned.append(candidate_talk)
    talks_on_this_day_if_talk_assigned.sort(key=lambda x: x.start_time)

    # The first shift is all talks that end in a period 0-3h after the start of the first talk
    talks_in_first_shift = []
    for talk in talks_on_this_day_if_talk_assigned:
        if talk.end_time <= talks_on_this_day_if_talk_assigned[
            0
        ].start_time + timedelta(hours=shift_length):
            talks_in_first_shift.append(talk)

    # Build shifts dynamically based on max_shifts_per_day_limit
    max_shifts_per_day_limit = RotaSettings.get_value('max_shifts_per_day_limit', 2)
    max_allowed_shifts = min(recorder.max_shifts_per_day, max_shifts_per_day_limit)
    
    all_shifts = [talks_in_first_shift]
    remaining_talks = talks_on_this_day_if_talk_assigned[len(talks_in_first_shift):]
    
    # Build additional shifts up to the maximum allowed
    for shift_num in range(2, max_allowed_shifts + 1):
        if not remaining_talks:
            break
            
        # Find the start time for this shift (first remaining talk)
        shift_start_time = remaining_talks[0].start_time
        
        # Check if this shift starts with adequate break after previous shift
        previous_shift = all_shifts[-1]
        if previous_shift and shift_start_time < previous_shift[-1].end_time + timedelta(hours=break_between_shifts):
            return True  # Violates break rules
        
        # Collect talks for this shift
        current_shift = []
        for talk in remaining_talks[:]:  # Copy list to avoid modification during iteration
            if shift_start_time <= talk.start_time <= shift_start_time + timedelta(hours=shift_length - 1):
                current_shift.append(talk)
                remaining_talks.remove(talk)
        
        if current_shift:
            all_shifts.append(current_shift)
        else:
            break

    # Check if all talks are accounted for in shifts
    total_talks_in_shifts = sum(len(shift) for shift in all_shifts)
    if len(talks_on_this_day_if_talk_assigned) == total_talks_in_shifts:
        return False  # All talks fit within shift rules
    else:
        return True  # Some talks don't fit, violates rules


def assign_talk_to_recorder(recorder, talk):
    recorder.talks.append(talk)
    recorder.talks.sort(key=lambda x: x.start_time)

    db.session.add(talk)
    db.session.add(recorder)
    db.session.commit()
    db.session.flush()


def clear_rota():
    for talk in Talk.query.all():
        talk.recorded_by = None
        db.session.add(talk)

    db.session.commit()
    db.session.flush()


def find_recorder_for_talk(talk):
    recorders = Recorder.query.all()

    while talk.recorded_by is None and len(recorders)>0:
        # Pick the recorder with fewest talks first, consider them a candidate
        recorders.sort(key=lambda x: len(x.talks))
        candidate_recorder = recorders.pop(0)

        # Do some checks that only make sense if the recorder already has some talks assigned
        if candidate_recorder.talks:
            candidate_recorders_last_talk = candidate_recorder.talks[-1]

            # Move on if the recorder is currently recording
            if talk_would_clash(candidate_recorder, talk):
                continue

            # Move on if the talk starts less than the required break after the recorders' last talk ended
            break_between_shifts = RotaSettings.get_value('break_between_shifts', 2)  # Default: 2 hours
            if talk.start_time < candidate_recorders_last_talk.end_time + timedelta(
                hours=break_between_shifts
            ):
                continue

            # Move on if this talk would result in the recorder doing too many talks in one day
            if recorder_is_maxed_out_for_day(candidate_recorder, talk):
                continue

            # Move on if this talk doens't fit within the shift pattern
            if talk_would_break_shift_pattern(candidate_recorder, talk):
                continue

        # If we've got this far, we're ok to assign the talk to the candidate recorder
        assign_talk_to_recorder(candidate_recorder, talk)

    return candidate_recorder or None


@rota_blueprint.route("/rota", methods=["GET", "POST"])
def rota():
    """Define a rota"""

    if request.method == "POST":
        # If we've been asked to make a new rota, clear out the old one
        clear_rota()

    talks = Talk.query.filter(Talk.is_priority == True).order_by(Talk.start_time)

    for talk in talks:
        app.logger.error("Finding a recorder for priority talk " + str(talk.id))
        
        # Move on if this talk is already being recorded
        if talk.recorder_name is not None:
            continue

        # Move on if the talk has been externally rota-ed in some way
        if talk.is_rotaed is not True:
            continue

        # If we've got this far, find a recorder for the talk
        assigned_recorder = find_recorder_for_talk(talk)

        if assigned_recorder is not None:
            # If there are any other talks in the same venue starting within the configured window, assign them to the same recorder
            same_venue_assignment_window = RotaSettings.get_value('same_venue_assignment_window', 3)  # Default: 3 hours
            for future_talk in Talk.query.filter(
                Talk.start_time > talk.end_time,
                Talk.start_time <= talk.start_time + timedelta(hours=same_venue_assignment_window - 1),
                Talk.venue == talk.venue,
                Talk.is_priority == True,
            ).order_by(Talk.start_time):
                if (
                    future_talk.start_time
                    < talk.start_time + timedelta(hours=same_venue_assignment_window - 1)
                    and talk_would_break_shift_pattern(assigned_recorder, future_talk)
                    is False
                    and talk_would_clash(assigned_recorder, future_talk) is False
                ):
                    assign_talk_to_recorder(assigned_recorder, future_talk)

    additional_talks = Talk.query.filter(Talk.is_priority == False).order_by(
        Talk.start_time
    )

    for talk in additional_talks:
        app.logger.error("Finding a recorder for additional talk " + str(talk.id))

        # Move on if this talk is already being recorded
        if talk.recorder_name is not None:
            continue

        # Move on if the talk isn't to be rota-ed
        if talk.is_rotaed is not True:
            continue

        # If we've got this far, find a recorder for the talk
        assigned_recorder = find_recorder_for_talk(talk)

        # If there is an unallocated talk starting after minimum gap within search window, and assigning it wouldn't exceed shift limits, assign it
        if assigned_recorder is not None:
            additional_talk_search_window = RotaSettings.get_value('additional_talk_search_window', 1)  # Default: 1 hour
            additional_talk_minimum_gap = RotaSettings.get_value('additional_talk_minimum_gap', 20)  # Default: 20 minutes
            for future_talk in (
                Talk.query.filter(
                    Talk.start_time > talk.end_time,
                    Talk.start_time <= talk.end_time + timedelta(hours=additional_talk_search_window),
                    Talk.recorded_by == None,
                )
                .order_by(Talk.start_time)
                .all()
            ):
                if (
                    future_talk.start_time < talk.end_time + timedelta(hours=additional_talk_search_window)
                    and future_talk.start_time > talk.end_time + timedelta(minutes=additional_talk_minimum_gap)
                    and talk_would_break_shift_pattern(assigned_recorder, future_talk)
                    is False
                    and talk_would_clash(assigned_recorder, future_talk) is False
                ):
                    assign_talk_to_recorder(assigned_recorder, future_talk)

    # Add completion message if this was a POST request (rota generation)
    if request.method == "POST":
        priority_talks_count = Talk.query.filter(Talk.is_priority == True).count()
        assigned_priority_talks = Talk.query.filter(Talk.is_priority == True, Talk.recorded_by != None).count()
        
        additional_talks_count = Talk.query.filter(Talk.is_priority == False).count()
        assigned_additional_talks = Talk.query.filter(Talk.is_priority == False, Talk.recorded_by != None).count()
        
        flash(f"Rota generation completed! Assigned {assigned_priority_talks}/{priority_talks_count} priority talks and {assigned_additional_talks}/{additional_talks_count} additional talks.", "success")

    return render_template("rota.html")


@rota_blueprint.route("/rota_by_venue", methods=["GET"])
def rota_by_venue():
    """Print the rota by venue"""

    days = [t.day for t in Talk.query.order_by(Talk.start_time).group_by(Talk.day).distinct()]
    talks = {}        
    times = {}
    venues = {}
    
    for day in days:
        talks[day] = Talk.query.where(Talk.day == day).order_by(Talk.start_time) 
        venues[day] = [t.venue for t in Talk.query.where(Talk.day==day).order_by(Talk.venue).group_by(Talk.venue).distinct()]
        times[day] = [t.start_time for t in Talk.query.where(Talk.day==day).order_by(Talk.start_time).group_by(Talk.start_time).distinct()]

    return render_template("rota_by_venue.html", talks=talks, times=times, venues=venues, days=days)


@rota_blueprint.route("/rota_by_time", methods=["GET"])
def rota_by_time():
    """Print the rota by time"""

    talks = Talk.query.order_by(Talk.start_time).all()
    times = {}
    venues = {}

    for talk in talks:
        times[talk.start_time] = None
        venues[talk.venue] = None

    return render_template("rota_by_time.html", talks=talks, times=times, venues=venues)

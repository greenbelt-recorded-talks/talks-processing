from . import rota_blueprint

from flask import request, redirect, url_for, render_template, make_response, send_from_directory
from datetime import datetime, date, time, timedelta
from flask import current_app as app
from gbtalks.models import db, Talk, Recorder
import random

shift_length = 3
break_between_shifts = 3

def talk_would_clash(recorder, talk):
    # A talk clashes if it starts while the recorder is currently recording, or within 20 mins of another talk ending

    for existing_talk in recorder.talks:
        app.logger.error("talk_would_clash: Comparing " + str(talk.id) + " with " + str(existing_talk.id))
        if (existing_talk.start_time <= talk.start_time <= (existing_talk.end_time + timedelta(minutes=20))
            or existing_talk.start_time <= talk.end_time <= (existing_talk.end_time + timedelta(minutes=20))):
            app.logger.error("Clashes!")
            return True

    app.logger.error("Does not clash")
    return False


def recorder_is_maxed_out_for_day(recorder, talk):
    # A normal shift is 3 hours - assume 2 talks to account for gaps. This algorithm only works if people do max 2 shifts per day!

    candidates_max_talks = recorder.max_shifts_per_day * 2
    candidates_talks_on_this_day = 0;
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
    # - check that there are no more 3h groups containing talks than the candidate is allowed shifts
    # - check that the 3h groups are more than 3h apart

    # Make a list of what the candidate's day would look like if the talk was assigned
    talks_on_this_day_if_talk_assigned = []
    for talk in Talk.query.filter(Talk.recorded_by == recorder,\
            Talk.start_time > datetime(candidate_talk.start_time.year,\
                candidate_talk.start_time.month,\
                candidate_talk.start_time.day, 0,0,0),\
            Talk.start_time < datetime(candidate_talk.start_time.year,\
                candidate_talk.start_time.month,\
                candidate_talk.start_time.day, 23,59,59)):

            talks_on_this_day_if_talk_assigned.append(talk)

    talks_on_this_day_if_talk_assigned.append(candidate_talk)
    talks_on_this_day_if_talk_assigned.sort(key=lambda x: x.start_time)


    # The first shift is all talks that end in a period 0-3h after the start of the first talk
    talks_in_first_shift = []
    for talk in talks_on_this_day_if_talk_assigned:
        if talk.end_time <= talks_on_this_day_if_talk_assigned[0].start_time + timedelta(hours=shift_length):
            talks_in_first_shift.append(talk)

    # The second shift is all talks that start in a period that starts a minimum of 3h after the end of the last talk of the first shift, and lasts for 3h.

    talks_in_second_shift = []
    if recorder.max_shifts_per_day == 2 and len(talks_on_this_day_if_talk_assigned) > len(talks_in_first_shift):
        # Consider the second shift to start at the start of the first talk after the end of the first shift
        # Note that len() deals with the zero-offset of the array index
        second_shift_start_time = talks_on_this_day_if_talk_assigned[len(talks_in_first_shift)].start_time

        # If the second shift would start less than break_between_shifts hours after the end of the first shift, fail
        if second_shift_start_time < talks_in_first_shift[-1].end_time + timedelta(hours=break_between_shifts):
            return True

        for talk in talks_on_this_day_if_talk_assigned:
            if (second_shift_start_time <= talk.start_time <= second_shift_start_time + timedelta(hours=shift_length-1)):
                talks_in_second_shift.append(talk)

    # If there are more talks in the list than were allowed by the shift rules, then the list violates the rules

    if len(talks_on_this_day_if_talk_assigned) == len(talks_in_first_shift) + len(talks_in_second_shift):
        return False
    else:
        return True

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

@rota_blueprint.route('/rota', methods=['GET','POST'])
def rota():
    """Define a rota"""


    talks = Talk.query.filter(Talk.is_priority==True).order_by(Talk.start_time)
    recorders = Recorder.query.all()

    app.logger.error("Generating a rota for " + str(talks.count()) + " talks")


    if request.method == 'POST':
        # If we've been asked to make a new rota, clear out the old one
        clear_rota()

    for talk in talks:

        app.logger.error("Finding a recorder for " + str(talk.id))

        # Move on if this talk is already being recorded
        if talk.recorder_name is not None:
            continue


        # Move on if the talk is in a venue that's externally rota-ed
        if talk.is_rotaed is not True:
            continue

        recorder = None
        candidate_recorders = []

        while recorder is None and len(candidate_recorders) <= len(recorders):

            # Pick a random recorder, consider them a candidate

            candidate_recorder = random.choice(recorders)
            candidate_recorders.append(candidate_recorder)

            # Do some checks that only make sense if the recorder already has some talks assigned
            if candidate_recorder.talks:
                candidate_recorders_last_talk = candidate_recorder.talks[-1]

                # Move on if the recorder is current recording
                if talk_would_clash(candidate_recorder, talk):
                    continue

                # Move on if the talk starts less than 3h after the recorders' last talk ended
                if talk.start_time < candidate_recorders_last_talk.end_time + timedelta(hours=break_between_shifts):
                    continue

                # Move on if this talk would result in the recorder doing too many talks in one day
                if recorder_is_maxed_out_for_day(candidate_recorder, talk):
                    continue

                if talk_would_break_shift_pattern(candidate_recorder, talk):
                    continue

            else:
                candidate_recorder.talks = []

            # If we've got this far, we're ok to assign the talk to the candidate recorder
            assign_talk_to_recorder(candidate_recorder, talk)

            # If there are any other talks in the same venue starting within 2h, assign them to the same recorder
            for future_talk in Talk.query.filter(Talk.start_time > talk.end_time,
                    Talk.start_time <= talk.start_time + timedelta(hours=shift_length-1),
                    Talk.venue == talk.venue, Talk.is_priority == True).order_by(Talk.start_time):
                if (future_talk.start_time < talk.start_time + timedelta(hours=shift_length-1)
                    and talk_would_break_shift_pattern(candidate_recorder, future_talk) is False
                    and talk_would_clash(candidate_recorder, future_talk) is False):
                    assign_talk_to_recorder(candidate_recorder, future_talk)

    additional_talks = Talk.query.filter(Talk.is_priority==False).order_by(Talk.start_time)

    for talk in additional_talks:

        # Move on if this talk is already being recorded
        if talk.recorder_name is not None:
            continue

        # Move on if the talk isn't to be rota-ed
        if talk.is_rotaed is not True:
            continue

        recorder = None
        candidate_recorders = []

        while recorder is None and len(candidate_recorders) <= len(recorders):

            # Pick a random recorder, consider them a candidate
            candidate_recorder = random.choice(recorders)
            candidate_recorders.append(candidate_recorder)

            # Do some checks that only make sense if the recorder already has some talks assigned
            if candidate_recorder.talks:

                # Move on if the recorder is current recording
                if talk_would_clash(candidate_recorder, talk):
                    continue

                # Move on if this talk would result in the recorder doing too many talks in one day
                if recorder_is_maxed_out_for_day(candidate_recorder, talk):
                    continue

                if talk_would_break_shift_pattern(candidate_recorder, talk):
                    continue

            else:
                candidate_recorder.talks = []

            # If we've got this far, we're ok to assign the talk to the candidate recorder
            assign_talk_to_recorder(candidate_recorder, talk)

            # If there is an unallocated talk starting 20-60 minutes later anywhere on site, and assigning it wouldn't exceed shift limits, assign it

            for future_talk in Talk.query.filter(Talk.start_time > talk.end_time,
                    Talk.start_time <= talk.end_time + timedelta(hours=1),
                    Talk.recorded_by == None).order_by(Talk.start_time).all():

                if (future_talk.start_time < talk.end_time + timedelta(hours=1)
                        and future_talk.start_time > talk.end_time + timedelta(minutes=20)
                        and talk_would_break_shift_pattern(candidate_recorder, future_talk) is False
                        and talk_would_clash(candidate_recorder, future_talk) is False):
                    assign_talk_to_recorder(candidate_recorder, talk)

    # Set up everything we need for rendering the page

    talks = Talk.query.order_by(Talk.start_time).all()
    times = {}
    venues = {}

    for talk in talks:
        times[talk.start_time] = None
        venues[talk.venue] = None

    return render_template("rota.html", talks=talks, times=times, venues=venues)


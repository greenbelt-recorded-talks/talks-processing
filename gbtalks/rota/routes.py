from . import rota_blueprint

from flask import request, redirect, url_for, render_template, make_response, send_from_directory
from datetime import datetime, date, time, timedelta
from flask import current_app as app
from gbtalks.models import db, Talk, Recorder
import random
import pprint

def talk_would_clash(recorder, talk):
    # A talk clashes if it starts while the recorder is currently recording, or within 20 mins of another talk ending

    for existing_talk in recorder.talks:
        if existing_talk.start_time <= talk.start_time <= (existing_talk.end_time + timedelta(minutes=20)):
            return True
    
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

        


@rota_blueprint.route('/rota', methods=['GET','POST'])
def rota():
    """Define a rota"""

    priority_talks = Talk.query.filter(Talk.is_priority==True).order_by(Talk.start_time)
    recorders = Recorder.query.all()

    if request.method == 'POST':
        # If we've been asked to make a new rota, clear out the old one
        for talk in Talk.query.all():
            talk.recorder_name = None
            db.session.add(talk)

        db.session.commit()
        db.session.flush()

    import pprint

    for talk in priority_talks:
        #pprint.pprint("Considering Talk:")
        #pprint.pprint(talk)

        # Move on if this talk is already being recorded
        if talk.recorder_name is not None:
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
                if talk.start_time < candidate_recorders_last_talk.end_time + timedelta(hours=3):
                    continue

                # Move on if this talk would result in the recorder doing too many talks in one day
                if recorder_is_maxed_out_for_day(candidate_recorder, talk):
                    continue

            else:
                candidate_recorder.talks = []

            # If we've got this far, we're ok to assign the talk to the candidate recorder
            candidate_recorder.talks.append(talk)
            candidate_recorder.talks.sort(key=lambda x: x.start_time)

            # If there are any other talks in the same venue starting within 2h, assign them to the same recorder
            for future_talk in Talk.query.order_by(Talk.start_time).all():
                    if (future_talk.start_time < talk.start_time + timedelta(hours=2)
                            and future_talk.start_time > talk.start_time
                            and future_talk.venue == talk.venue):
                        pprint.pprint("Assigning:")
                        pprint.pprint(talk)
                        pprint.pprint(recorder)
                        candidate_recorder.talks.append(future_talk)
                        db.session.add(future_talk)

            recorder = candidate_recorder
            db.session.add(recorder)
            db.session.add(talk)

        # If we run out of recorders, stop and error
        # TODO ^^


    non_priority_talks = Talk.query.filter(Talk.is_priority==False).order_by(Talk.start_time)

    for talk in non_priority_talks:

        # Move on if this talk is already being recorded
        if talk.recorder_name is not None:
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

                # Move on if this talk would result in the recorder doing too many talks in one day
                if recorder_is_maxed_out_for_day(candidate_recorder, talk):
                    continue

                # Move on if this talk would result in the recorder doing too many talks in one go (ie, over 3h straight)
                adjacent_talks = Talk.query.filter(Talk.end_time >= talk.start_time - timedelta(hours=3), Talk.end_time <= talk.end_time + timedelta(hours=3)).\
                        filter(Talk.recorded_by == candidate_recorder).\
                        order_by(Talk.start_time)

                if adjacent_talks.count() > 1:
                    continue
            
            else:
                candidate_recorder.talks = []

            # If we've got this far, we're ok to assign the talk to the candidate recorder
            candidate_recorder.talks.append(talk)
            candidate_recorder.talks.sort(key=lambda x: x.start_time)

            # If there are any other talks in the same venue starting within 2h, assign them to the same recorder
            #for future_talk in Talk.query.order_by(Talk.start_time).all():
            #        if (future_talk.start_time < talk.start_time + timedelta(hours=2)
            #                and future_talk.start_time > talk.start_time
            #                and future_talk.venue == talk.venue):
            #            candidate_recorder.talks.append(future_talk)
            #            db.session.add(future_talk)

            recorder = candidate_recorder
            db.session.add(recorder)
            db.session.add(talk)

            # If there is an unallocated talk starting 20-60 minutes later anywhere on site, and assigning it wouldn't exceed shift limits, assign it
            
            for future_talk in Talk.query.order_by(Talk.start_time).all():
                adjacent_talks = Talk.query.filter(Talk.end_time >= talk.start_time - timedelta(hours=3), Talk.end_time <= talk.end_time + timedelta(hours=3)).\
                        filter(Talk.recorded_by == candidate_recorder).\
                        order_by(Talk.start_time)

                if (future_talk.start_time > talk.start_time 
                        and future_talk.start_time < talk.end_time + timedelta(hours=1) 
                        and future_talk.start_time > talk.end_time + timedelta(minutes=20)
                        and future_talk.recorded_by is None
                        and adjacent_talks.count() < 2):
                    candidate_recorder.talks.append(future_talk)
                    db.session.add(future_talk)
                    recorder = candidate_recorder
                    db.session.add(recorder)

        # If we run out of recorders, stop and error
        # TODO ^^

        db.session.commit()

    # Set up everything we need for rendering the page

    talks = Talk.query.order_by(Talk.start_time).all()
    times = {}
    venues = {}

    for talk in talks:
        times[talk.start_time] = None
        venues[talk.venue] = None

    return render_template("rota.html", talks=talks, times=times, venues=venues)


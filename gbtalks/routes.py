import csv
from flask import request, redirect, url_for, render_template, make_response
from datetime import datetime, date, time, timedelta
from flask import current_app as app
from .models import db, Talk, Recorder
from werkzeug.utils import secure_filename
import os
import random 
import sys
import pprint

def start_time_of_talk(day, time):
    fri_of_gb = datetime.strptime(app.config['GB_FRIDAY'], '%Y-%m-%d').date()
    days = {
            "Friday": 0,
            "Saturday": 1,
            "Sunday": 2,
            "Monday": 3
    }

    day_of_talk = fri_of_gb + timedelta(days=days.get(day))
    time_of_talk = datetime.strptime(time, '%I:%M %p').time()
    print(pprint.pprint(time), file=sys.stderr)
    print(pprint.pprint(time_of_talk), file=sys.stderr)
    return datetime.combine(day_of_talk, time_of_talk)


@app.route('/talks', methods=['GET','POST'])
def talks():
    """View or add talks to the database"""

    if request.method == 'POST':

        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)

        file = request.files['file']

        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_DIR'], filename))

            Talk.query.delete()

            with open(os.path.join(app.config['UPLOAD_DIR'], filename), newline='') as csvfile:
                talksreader = csv.reader(csvfile)
                for talk_line in talksreader:
                    start_time = start_time_of_talk(talk_line[6], talk_line[5])
                    end_time = start_time + timedelta(hours=1)
                    talk = Talk(id=talk_line[0], 
                            title=talk_line[7], 
                            description=talk_line[9], 
                            speaker=talk_line[8],
                            venue=talk_line[4],
                            start_time=start_time,
                            end_time=end_time)
                    db.session.add(talk)


            db.session.commit()
            return redirect(url_for('talks',
                                    filename=filename))

    talks = Talk.query.all()
    return render_template("talks.html", talks=talks)

@app.route('/recorders', methods=['GET','POST'])
def recorders():
    """View or add recorders to the database"""

    if request.method == 'POST':

        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)

        file = request.files['file']

        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_DIR'], filename))
            
            Recorder.query.delete()
        
        with open(os.path.join(app.config['UPLOAD_DIR'], filename), newline='') as csvfile:
            recordersreader = csv.reader(csvfile)

            for recorder_line in recordersreader:
                if recorder_line[2] == "red_tent":
                    can_record_in_red_tent = True
                else:
                    can_record_in_red_tent = False

                recorder = Recorder(
                    name = recorder_line[0],
                    max_shifts_per_day = recorder_line[1],
                    can_record_in_red_tent = can_record_in_red_tent
                )
                db.session.add(recorder)

        db.session.commit()

        return redirect(url_for('recorders'))

    recorders = Recorder.query.all()
    return render_template("recorders.html", recorders=recorders)
                

@app.route('/rota', methods=['GET'])
def rota():
    """Define a rota"""
            
    talks = Talk.query.order_by(Talk.start_time).all()
    recorders = Recorder.query.all()

    # Before making this into production, stop deleting everything!
    for talk in talks:
        talk.recorder_name = None
        db.session.add(talk)

    db.session.commit()
    db.session.flush()

    import pprint

    for talk in talks:
        pprint.pprint("Considering Talk:") 
        pprint.pprint(talk)

        # Move on if this talk is already being recorded
        if talk.recorder_name is not None:
            continue

        recorder = None
        candidate_recorders = []

        while recorder is None and len(candidate_recorders) < len(recorders):

            # Pick a random recorder, consider them a candidate

            candidate_recorder = random.choice(recorders)
            #pprint.pprint("Considering Recorder:")
            #pprint.pprint(candidate_recorder)
            #pprint.pprint("Recorder's Talks:")
            #pprint.pprint(candidate_recorder.talks)

            candidate_recorders.append(candidate_recorder)

            # Move on if the talk is in the Red Tent but the recorder can't record there

            if talk.venue == "Red Tent" and candidate_recorder.can_record_in_red_tent == False:
                continue

            # Do some checks that only make sense if the recorder already has some talks assigned
            if candidate_recorder.talks:
                candidate_recorders_last_talk = candidate_recorder.talks[-1]
    
                #pprint.pprint("Recorder's last talk:")
                #pprint.pprint(candidate_recorders_last_talk)

                # Move on if the recorder is current recording
                for existing_talk in candidate_recorder.talks:
                    if existing_talk.start_time < talk.start_time < existing_talk.end_time:
                        continue

                # Move on if the talk starts less than 3h after the recorders' last talk ended
                if talk.start_time < candidate_recorders_last_talk.end_time + timedelta(hours=3):
                    continue
                
                # Move on if this talk would result in the recorder doing too many talks in one day
                # A normal shift is 3 talks - assume 2 to account for incomplete shifts. This only works if people do max 2 shifts per day!
                candidates_max_talks = candidate_recorder.max_shifts_per_day * 2
                candidates_talks_on_this_day = 0;
                for candidates_talk in candidate_recorder.talks:
                    if candidates_talk.start_time.day == talk.start_time.day:
                        candidates_talks_on_this_day += 1

                if candidates_talks_on_this_day >= candidates_max_talks:
                    continue
                    
            else:
                candidate_recorder.talks = []

            # If we've got this far, we're ok to assign the talk to the candidate recorder
            candidate_recorder.talks.append(talk)
            candidate_recorder.talks.sort(key=lambda x: x.start_time)

            # If there are any other talks in the same venue starting within 2h, assign them to the same recorder
            for future_talk in Talk.query.order_by(Talk.start_time).all():
                    if (future_talk.start_time < talk.start_time + timedelta(hours=3) 
                            and future_talk.start_time > talk.start_time
                            and future_talk.venue == talk.venue):
                        candidate_recorder.talks.append(future_talk)
                        db.session.add(future_talk)

            recorder = candidate_recorder
            db.session.add(recorder)
            db.session.add(talk)
            db.session.flush()

        # If we run out of recorders, stop and error

        db.session.commit()

    talks = Talk.query.order_by(Talk.start_time).all()
    times = {}
    venues = {}

    for talk in talks:
        times[talk.start_time] = None
        venues[talk.venue] = None
     
    return render_template("rota.html", talks=talks, times=times, venues=venues)


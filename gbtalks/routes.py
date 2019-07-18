import csv
from flask import request, redirect, url_for, render_template, make_response
from datetime import datetime, date, time, timedelta
from flask import current_app as app
from .models import db, Talk, Recorder
from werkzeug.utils import secure_filename
import os
import random 

def start_time_of_talk(day, time):
    fri_of_gb = datetime.strptime(app.config['GB_FRIDAY'], '%Y-%m-%d').date()
    days = {
            "Friday": 0,
            "Saturday": 1,
            "Sunday": 2,
            "Monday": 3
    }

    day_of_talk = fri_of_gb + timedelta(days=days.get(day))
    time_of_talk = datetime.strptime(time, '%H:%M %p').time()
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

            Talk.query.all().delete()

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
            
            Recorder.query.all().delete()
        
        with open(os.path.join(app.config['UPLOAD_DIR'], filename), newline='') as csvfile:
            recordersreader = csv.reader(csvfile)

            for recorder_line in recordersreader:
                recorder = Recorder(
                    name = recorder_line[0],
                    max_shifts_per_day = recorder_line[1]
                )
                db.session.add(recorder)

        db.session.commit()

        return redirect(url_for('recorders'))

    recorders = Recorder.query.all()
    return render_template("recorders.html", recorders=recorders)
                

@app.route('/rota', methods=['GET','POST'])
def rota():
    """Define a rota"""

    if request.method == 'POST':
            
        talks = Talk.query.all().order_by(Talk.start_time)
        recorders = Recorder.query.all()

        for talk in talks:

            # Move on if this talk is already being recorded
            if talk.recorder_name is not None:
                continue

            recorder = None

            while recorder is None:

                # Pick a random recorder, consider them a candidate

                candidate_recorder = random.choice(recorders)

                # Move on if the talk starts less than 3h after the recorders' last talk ended

                if candidate_recorder.talks[-1].end_time > talk.start_time + datetime.timedelta 

                # Move on if the recorder is only doing 1 shift per day, and this would be their second shift

                # If we run out of recorders, stop and error

                # Once we've selected a recorder, assign the talk to them

                # If there are any other talks in the same venue starting within 2.5h, assign them to the same recorder
            


        








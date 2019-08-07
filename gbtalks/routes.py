import csv
from flask import request, redirect, url_for, render_template, make_response, send_from_directory
from datetime import datetime, date, time, timedelta
from flask import current_app as app
from .models import db, Talk, Recorder, Editor
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
    """View or add talks to the database, upload the files"""

    if request.method == 'POST':
        if request.form['form_name'] == "upload_talks_list":
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

        elif request.form['form_name'] == "upload_raw_talk":
            if 'file' not in request.files:
                flash('No file part')
                return redirect(request.url)

            talk_id = request.form['talk_id']
            file = request.files['file']

            if file:
                filename = talk_id + "_RAW.mp3"
                file.save(os.path.join(app.config['RAW_UPLOAD_DIR'], filename))

    talks = Talk.query.all()
    uploaded_files = [x.name for x in os.scandir(app.config['RAW_UPLOAD_DIR'])]

    return render_template("talks.html", talks=talks, uploaded_files=uploaded_files)


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
                

@app.route('/rota', methods=['GET','POST'])
def rota():
    """Define a rota"""
            
    talks = Talk.query.order_by(Talk.start_time).all()
    recorders = Recorder.query.all()

    if request.method == 'POST':
        # If we've been asked to make a new rota, clear out the old one
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
            candidate_recorders.append(candidate_recorder)

            # Move on if the talk is in the Red Tent but the recorder can't record there
            if talk.venue == "Red Tent" and candidate_recorder.can_record_in_red_tent == False:
                continue

            # Do some checks that only make sense if the recorder already has some talks assigned
            if candidate_recorder.talks:
                candidate_recorders_last_talk = candidate_recorder.talks[-1]
    
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


@app.route('/editing', methods=['GET','POST'])
def editing():
    """ Where editors obtain and upload files """

    # This page needs to have:
    # - A way for someone to upload a list of editors

    if request.method == 'POST':
        if request.form['form_name'] == "upload_editors_list":
            if 'file' not in request.files:
                flash('No file part')
                return redirect(request.url)

            file = request.files['file']

            if file:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_DIR'], filename))

                Editor.query.delete()

                with open(os.path.join(app.config['UPLOAD_DIR'], filename), newline='') as csvfile:
                    editorsreader = csv.reader(csvfile)
    
                    for editor_line in editorsreader:
                        editor = Editor(
                            name = editor_line[0],
                        )
                        db.session.add(editor)

        elif request.form['form_name'] == "assign_talk":
            editor = Editor.query.filter(name = request.form['editor_to_assign']).first()
            talk = Talk.query.filter(id=request.form['talk_id']).first()
            
            editor.talks.append(talk)
            
            db.session.add(editor)
            db.session.add(talk)

            return redirect(url_for('editing'))

        elif request.form['form_name'] == "upload_edited_talk":
           pass 

        db.session.commit()
        return redirect(url_for('editing'))

    else:
        if request.args.get("download_raw_talk"):
            return send_from_directory(app.config["RAW_UPLOAD_DIR"], filename=request.args["download_raw_talk"] + "_RAW.mp3" , as_attachment=True)

    # Data on the current state of the talks files
    raw_talks_available = [x.name.split("_")[0] for x in os.scandir(app.config['RAW_UPLOAD_DIR']) if x.name.endswith("_RAW.mp3")] 
    edited_talks_available = [x.name.split("_")[0] for x in os.scandir(app.config['EDITED_UPLOAD_DIR']) if x.name.endswith("_EDITED.mp3")]
    processed_talks_available = [x.name.split("_")[0] for x in os.scandir(app.config['PROCESSED_DIR']) if x.name.endswith("_PROCESSED.mp3")]
    snips_available = [x.name.split("_")[0] for x in os.scandir(app.config['SNIP_DIR']) if x.name.endswith("_SNIP.mp3")]
    
    # Talks that need editing
    talks_to_edit = Talk.query.filter(Talk.editor_name==None).filter(Talk.id.in_(raw_talks_available))
    

    # - A way for someone to download raw files, assign a talk to an editor, upload the edited files
    editors = Editor.query.all()
    return render_template("editing.html", editors=editors, talks_to_edit=talks_to_edit, raw_talks_available=raw_talks_available, edited_talks_available=edited_talks_available, processed_talks_available=processed_talks_available, snips_available=snips_available)


@app.route('/getfile', methods=['GET'])
def getfile():
    """ Download a talk file """

    file_type = request.args.get("file_type")
    talk_id = request.args.get("talk_id")

    directories = {
        "raw": "RAW_UPLOAD_DIR",
        "edited": "EDITED_UPLOAD_DIR",
        "processed": "PROCESSED_DIR",
        "snip": "SNIP_DIR"
    }

    return send_from_directory(directory=app.config[directories[file_type]], filename=talk_id + "_" + file_type.upper() + ".mp3")


@app.route('/uploadtalk', methods=['POST'])
def uploadtalk():
    """ Upload a talk file, then redirect back to where you came from """

    file_type = request.form.get("file_type")
    talk_id = request.form.get("talk_id")
    
    source_path = request.referrer.split("/")[-1]

    directories = {
        "raw": "RAW_UPLOAD_DIR",
        "edited": "EDITED_UPLOAD_DIR",
        "processed": "PROCESSED_DIR",
        "snip": "SNIP_DIR"
    }

    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)

    file = request.files['file']
        
    if file:
        filename = talk_id + "_" + file_type.upper() + ".mp3"
        file.save(os.path.join(app.config[directories[file_type]], filename))

    return redirect(url_for(source_path))


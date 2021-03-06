import csv
from flask import request, redirect, url_for, render_template, make_response, send_from_directory, send_file
from datetime import datetime, date, time, timedelta
from flask import current_app as app
from .models import db, Talk, Recorder, Editor
from werkzeug.utils import secure_filename
import os
import random 
import sys
import pprint

def get_path_for_file(talk_id, file_type):
    path = app.config["TALKS_DIRS"][file_type]["directory"] + \
        "/gb" + \
        app.config['GB_FRIDAY'][2:4] + \
        "-"  + \
        str(talk_id).zfill(3) + \
        app.config["TALKS_DIRS"][file_type]["suffix"] + \
        '.mp3'

    pprint.pprint("Path")
    pprint.pprint(path)

    return path

def start_time_of_talk(day, time):
    fri_of_gb = datetime.strptime(app.config['GB_FRIDAY'], '%Y-%m-%d').date()
    days = {
            "Friday": 0,
            "Saturday": 1,
            "Sunday": 2,
            "Monday": 3
    }

    try:
        day_of_talk = fri_of_gb + timedelta(days=days.get(day))
    except TypeError:
        day_of_talk = datetime.strptime(day, '%d/%m/%y').date()
        
    try:
        time_of_talk = datetime.strptime(time, '%I:%M %p').time()
    except ValueError:
        time_of_talk = datetime.strptime(time, '%H:%M:%S').time()
    return datetime.combine(day_of_talk, time_of_talk)


@app.route('/talks', methods=['GET','POST'])
def talks():
    """View talks in the database, replace the talks list, upload files for talks"""

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
                        start_time = start_time_of_talk(talk_line[2], talk_line[3])
                        end_time = start_time + timedelta(hours=1)
                        is_priority = True if talk_line[10] == "Yes" else False
                        talk = Talk(id=talk_line[0].split('-')[1], 
                                title=talk_line[5], 
                                description=talk_line[6], 
                                speaker=talk_line[7],
                                venue=talk_line[1],
                                start_time=start_time,
                                end_time=end_time,
                                is_priority=is_priority)
                        db.session.add(talk)

                db.session.commit()
                return redirect(url_for('talks',
                                    filename=filename))



    show_additional_talks = True if request.args.get("show_additional_talks") == "true" else False

    talks = Talk.query.all()
    raw_files = [x.name for x in os.scandir(app.config['RAW_UPLOAD_DIR'])]
    edited_files = [x.name for x in os.scandir(app.config['EDITED_UPLOAD_DIR'])]
    processed_files = [x.name for x in os.scandir(app.config['PROCESSED_DIR'])]
    snip_files = [x.name for x in os.scandir(app.config['SNIP_DIR'])]

    return render_template("talks.html", 
                            talks=talks,
                            raw_files=raw_files,
                            edited_files=edited_files,
                            processed_files=processed_files,
                            snip_files=snip_files,
                            show_additional_talks=show_additional_talks
                            )


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
                
                recorder = Recorder(
                    name = recorder_line[0],
                    max_shifts_per_day = recorder_line[1],
                )
                db.session.add(recorder)

        db.session.commit()

        return redirect(url_for('recorders'))

    recorders = Recorder.query.all()
    return render_template("recorders.html", recorders=recorders)
                

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

    return send_file(get_path_for_file(talk_id, file_type), as_attachment=True)


@app.route('/uploadtalk', methods=['POST'])
def uploadtalk():
    """ Upload a talk file, then redirect back to where you came from """

    file_type = request.form.get("file_type")
    talk_id = request.form.get("talk_id")
    
    source_path = request.referrer.split("/")[-1]

    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)

    file = request.files['file']
        
    if file:
        file.save(os.path.join(get_path_for_file(talk_id, file_type)))

    return redirect(url_for(source_path))


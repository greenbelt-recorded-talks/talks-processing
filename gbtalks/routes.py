import csv
import filetype
from flask import current_app, flash, request, redirect, url_for, render_template, make_response, send_from_directory, send_file
from datetime import datetime, date, time, timedelta
from flask import current_app as app
from flask_login import login_required, logout_user
from flask_login.utils import _get_user 
from functools import wraps
from sqlalchemy import desc, asc
from .models import db, Talk, Recorder, Editor
from werkzeug.utils import secure_filename
from werkzeug.local import LocalProxy
import os
import random 
import sys
import pprint

# current_user is a proxy for the current user
current_user = LocalProxy(lambda: _get_user())

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
    """Convert "Greenbelt Days" to real days, and parse out the start times of talks"""
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
        try:
            time_of_talk = datetime.strptime(time, '%H:%M:%S').time()
        except ValueError:
            time_of_talk = datetime.strptime(time, '%H:%M').time()
    return datetime.combine(day_of_talk, time_of_talk)

def current_user_is_team_leader(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        """Make sure that the user is on the list of team leaders"""
        if not current_user.email in app.config["TEAM_LEADERS_EMAILS"]:
            return current_app.login_manager.unauthorized()
        
        return func(*args, **kwargs)
    return wrapper

@app.route('/', methods=['GET'])
@login_required
@current_user_is_team_leader
def index():
    return redirect('talks')


@app.route('/talks', methods=['GET','POST'])
@login_required
@current_user_is_team_leader
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
                    next(talksreader, None)  # skip the headers
                    for talk_line in talksreader:
                        start_time = start_time_of_talk(talk_line[2], talk_line[3])
                        end_time = start_time + timedelta(hours=1)
                        is_priority = True if talk_line[8] == "Yes" else False
                        is_rotaed = True if talk_line[9] == "Yes" else False
                        talk = Talk(id=talk_line[0].split('-')[1], 
                                title=talk_line[4],
                                description=talk_line[7],
                                speaker=talk_line[6],
                                venue=talk_line[1],
                                start_time=start_time,
                                end_time=end_time,
                                is_priority=is_priority,
                                is_rotaed=is_rotaed)
                        db.session.add(talk)

                db.session.commit()
                return redirect(url_for('talks',
                                    filename=filename))



    show_additional_talks = True if request.args.get("show_additional_talks") == "true" else False

    talks = Talk.query.order_by(asc(Talk.start_time)).all()
    raw_files = [x.name for x in os.scandir(app.config['RAW_UPLOAD_DIR'])]
    edited_files = [x.name for x in os.scandir(app.config['EDITED_UPLOAD_DIR'])]
    processed_files = [x.name for x in os.scandir(app.config['PROCESSED_DIR'])]

    return render_template("talks.html", 
                            gb_year=app.config['GB_SHORT_YEAR'],
                            talks=talks,
                            raw_files=raw_files,
                            edited_files=edited_files,
                            processed_files=processed_files,
                            show_additional_talks=show_additional_talks
                            )


@app.route('/setup', methods=['GET'])
@login_required
@current_user_is_team_leader
def setup():
    """Various setup functions"""

    return render_template("setup.html")


@app.route('/put_alltalks_pdf', methods=['POST'])
@login_required
@current_user_is_team_leader
def put_alltalks_pdf():
    """Upload the all talks PDF to the USB gold copy"""

    if 'file' not in request.files:
        flash('No file supplied!')
        return redirect(url_for('setup'))

    file = request.files['file']

    if file:
        filename = "GB" + app.config['GB_SHORT_YEAR'] + "-AllTalksIndex.pdf"
        file.save(os.path.join(app.config['USB_GOLD_DIR'], filename))

    return redirect(url_for('setup'))


@app.route('/create_alltalks_gold', methods=['POST'])
@login_required
@current_user_is_team_leader
def create_alltalks_gold():
    """Create the alltalks USB Gold copy"""

    # First, wipe all mp3s from the gold dir (don't touch the PDF) 
    # For each talk in the database, either copy the processed file to the USB gold dir, or add it to the list of talks that couldn't be copied to show to the user


@app.route('/copy_all_talks', methods=['POST'])
@login_required
@current_user_is_team_leader
def copy_all_talks():
    """Copy the USB gold copy on to every connected USB drive"""

    # First, detect all USB drives
    # Then, give up if any aren't either ~8GB, ~16GB or ~128GB 
    # Then, copy the USB gold to /dev/shm
    # Then, spawn a bunch of children to do some rsyncing 

@app.route('/duplication', methods=['GET'])
@login_required
@current_user_is_team_leader
def duplication():
    """Functions and instructions for the duplication team"""

    return render_template("duplication.html")

@app.route('/recorders', methods=['GET','POST'])
@login_required
@current_user_is_team_leader
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


@app.route('/front_desk', methods=['GET','POST'])
@login_required
@current_user_is_team_leader
def front_desk():
    """ Management functions for front desk """

    gb_year = str(app.config['GB_FRIDAY'][2:4])
    gb_prefix = "gb" + gb_year + "-"                
    
    raw_files = set([int(x.name.replace('_RAW.mp3','').replace(gb_prefix,'')) for x in os.scandir(app.config['RAW_UPLOAD_DIR']) if x.name.endswith('RAW.mp3')]) or set()

    past_horizon = datetime.now() + timedelta(hours = 1)

    talks_to_upload = Talk.query.filter(Talk.start_time < past_horizon)

    return render_template("front_desk.html",
            talks_to_upload=talks_to_upload,
            raw_talks_available=raw_files)


@app.route('/editing', methods=['GET','POST'])
@login_required
@current_user_is_team_leader
def editing():
    """ Where editors obtain and upload files """

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
            db.session.commit()

            return redirect(url_for('editing'))

        elif request.form['form_name'] == "upload_edited_talk":
           pass 

        db.session.commit()
        return redirect(url_for('editing'))

    else:
        if request.args.get("download_raw_talk"):
            return send_from_directory(app.config["RAW_UPLOAD_DIR"], filename=request.args["download_raw_talk"] + "_RAW.mp3" , as_attachment=True)


    gb_year = str(app.config['GB_FRIDAY'][2:4])
    gb_prefix = "gb" + gb_year + "-"

    raw_files = set([x.name.replace('_RAW.mp3','').replace(gb_prefix,'') for x in os.scandir(app.config['RAW_UPLOAD_DIR']) if x.name.endswith('RAW.mp3')]) or set()
    edited_files = set([x.name.replace('_EDITED.mp3','').replace(gb_prefix,'') for x in os.scandir(app.config['EDITED_UPLOAD_DIR']) if x.name.endswith('EDITED.mp3')]) or set()
    processed_files = set([x.name.replace('mp3.mp3','').replace(gb_prefix,'') for x in os.scandir(app.config['PROCESSED_DIR']) if x.name.endswith('mp3.mp3')]) or set()
    
    talks_to_edit = Talk.query.filter(Talk.id.in_(set(raw_files.difference(edited_files)))).order_by(asc(Talk.start_time))
    
    # - A way for someone to download raw files, assign a talk to an editor, upload the edited files
    editors = Editor.query.all()
    return render_template("editing.html", 
            editors=editors, 
            talks_to_edit=talks_to_edit, 
            raw_talks_available=raw_files, 
            edited_talks_available=edited_files, 
            processed_talks_available=processed_files)


@app.route('/getfile', methods=['GET'])
@login_required
@current_user_is_team_leader
def getfile():
    """ Download a talk file """

    file_type = request.args.get("file_type")
    talk_id = request.args.get("talk_id")

    return send_file(get_path_for_file(talk_id, file_type), as_attachment=True)


@app.route('/upload_cover_image', methods=['POST'])
@login_required
@current_user_is_team_leader
def upload_cover_image():
    """ Upload a new cover image, then redirect back to where you came from """

    source_path = request.referrer.split("/")[-1]

    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)

    file = request.files['file']

    if file:
        kind = filetype.guess(file.read(261))
        if kind.extension == "png":
            file.save(app.config["IMG_DIR"] + '/alltalksicon.png')
        else:
            flash("Must be a PNG")

    return redirect(url_for(source_path))


@app.route('/uploadtalk', methods=['POST'])
@login_required
@current_user_is_team_leader
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


@app.route('/upload_talk', methods=['POST'])
@login_required
@current_user_is_team_leader
def upload_talk():
    """ Upload a talk file, then redirect back to where you came from """

    talk_id = request.form.get("talk_id")

    source_path = request.referrer.split("/")[-1]

    if 'editedfile' not in request.files:
        flash('No edited file')
        return redirect(request.url)

    editedfile = request.files['editedfile']

    if editedfile:
        editedfile.save(os.path.join(get_path_for_file(talk_id, 'edited')))
    else:
        flash("Something went wrong! Check the logs")

    return redirect(url_for(source_path))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have logged out")
    return redirect(url_for("index"))

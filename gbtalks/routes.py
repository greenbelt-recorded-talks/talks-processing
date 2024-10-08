import csv
import filetype
from flask import (
    current_app,
    flash,
    request,
    redirect,
    url_for,
    render_template,
    send_from_directory,
    send_file,
)
from datetime import datetime, timedelta
from flask import current_app as app
from flask_login import login_required, logout_user
from flask_login.utils import _get_user
from functools import wraps
from sqlalchemy import desc, asc
from .models import db, Talk, Recorder, Editor
from werkzeug.utils import secure_filename
from werkzeug.local import LocalProxy
import os
import shutil
import shortuuid
import pprint
from .libgbtalks import (
    get_path_for_file, 
    gb_time_to_datetime
)

# current_user is a proxy for the current user
current_user = LocalProxy(lambda: _get_user())


def current_user_is_team_leader(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        """Make sure that the user is on the list of team leaders"""
        if not current_user.email in app.config["TEAM_LEADERS_EMAILS"]:
            return current_app.login_manager.unauthorized()

        return func(*args, **kwargs)

    return wrapper


@app.route("/", methods=["GET"])
@login_required
@current_user_is_team_leader
def index():
    return redirect("talks")


@app.route("/talks", methods=["GET", "POST"])
@login_required
@current_user_is_team_leader
def talks():
    """View talks in the database, replace the talks list, upload files for talks"""

    if request.method == "POST":
        if request.form["form_name"] == "upload_talks_list":
            if "file" not in request.files:
                flash("No file part")
                return redirect(request.url)

            file = request.files["file"]

            if file:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config["UPLOAD_DIR"], filename))

                Talk.query.delete()

                with open(
                    os.path.join(app.config["UPLOAD_DIR"], filename), newline=""
                ) as csvfile:
                    talksreader = csv.reader(csvfile)
                    next(talksreader, None)  # skip the headers
                    for talk_line in talksreader:
                        start_time = gb_time_to_datetime(talk_line[3], talk_line[4])
                        end_time = gb_time_to_datetime(talk_line[3], talk_line[5])
                        is_priority = True if talk_line[8] == "Yes" else False
                        is_rotaed = True if talk_line[9] == "Yes" else False
                        is_cleared = True if talk_line[10] == "Yes" else False
                        talk = Talk(
                            id=talk_line[0].split("-")[1],
                            title=talk_line[2],
                            description=talk_line[7],
                            speaker=talk_line[1],
                            venue=talk_line[6],
                            day=talk_line[3],
                            start_time=start_time,
                            end_time=end_time,
                            is_priority=is_priority,
                            is_rotaed=is_rotaed,
                            is_cleared=is_cleared
                        )
                        db.session.add(talk)

                db.session.commit()
                return redirect(url_for("talks", filename=filename))

    talks = Talk.query.order_by(asc(Talk.start_time)).all()
    raw_files = [x.name for x in os.scandir(app.config["UPLOAD_DIR"])]
    edited_files = [x.name for x in os.scandir(app.config["UPLOAD_DIR"])]
    processed_files = [
        x.name.split("_")[1] for x in os.scandir(app.config["PROCESSED_DIR"])
    ]
    notes_files = [x.name for x in os.scandir(app.config["IMG_DIR"])]

    return render_template(
        "talks.html",
        gb_year=app.config["GB_SHORT_YEAR"],
        talks=talks,
        raw_files=raw_files,
        edited_files=edited_files,
        processed_files=processed_files,
        notes_files=notes_files,
    )

@app.route("/edit_talk", methods=["GET","POST"])
@login_required
@current_user_is_team_leader
def edit_talk():
    """Edit an individual talk in the database"""

    if request.method == "GET":
        talk_id = request.args.get("talk_id")
        talk = Talk.query.get(talk_id)
        return render_template("edit_talk.html",
                                start_time=talk.start_time.strftime("%H:%M:%S"),
                                end_time=talk.end_time.strftime("%H:%M:%S"),
                                talk=talk
                                )


    if request.method == "POST":
        talk_id = request.form.get("talk_id")
        talk = Talk.query.get(talk_id)

        talk.title = request.form.get("title")
        talk.description = request.form.get("description")
        talk.speaker = request.form.get("speaker")
        talk.day = request.form.get("day")
        talk.start_time = gb_time_to_datetime(request.form.get("day"), request.form.get("start_time"))
        talk.end_time = gb_time_to_datetime(request.form.get("day"), request.form.get("end_time"))

        talk.has_explicit_warning_sticker = True if request.form.get("has_explicit_warning_sticker") else False
        talk.has_distressing_content_warning_sticker = True if request.form.get("has_distressing_content_warning_sticker") else False
        talk.has_technical_issues_sticker = True if request.form.get("has_technical_issues_sticker") else False
        talk.has_copyright_removal_sticker = True if request.form.get("has_copyright_removal_sticker") else False

        talk.is_cleared = True if request.form.get("is_cleared") else False

        db.session.commit()
        return redirect(url_for("talks") + "#talk_" +  talk_id)


@app.route("/setup", methods=["GET"])
@login_required
@current_user_is_team_leader
def setup():
    """Various setup functions"""

    return render_template("setup.html")


@app.route("/put_alltalks_pdf", methods=["POST"])
@login_required
@current_user_is_team_leader
def put_alltalks_pdf():
    """Upload the all talks PDF to the USB gold copy"""

    if "file" not in request.files:
        flash("No file supplied!")
        return redirect(url_for("setup"))

    file = request.files["file"]

    if file:
        filename = "GB" + app.config["GB_SHORT_YEAR"] + "-AllTalksIndex.pdf"
        file.save(os.path.join(app.config["USB_GOLD_DIR"], filename))

    return redirect(url_for("setup"))


@app.route("/create_alltalks_gold", methods=["POST"])
@login_required
@current_user_is_team_leader
def create_alltalks_gold():
    """Create the alltalks USB Gold copy"""

    # First, wipe all mp3s from the gold dir (don't touch the PDF)
    # For each talk in the database, either copy the processed file to the USB gold dir, or add it to the list of talks that couldn't be copied to show to the user


@app.route("/copy_all_talks", methods=["POST"])
@login_required
@current_user_is_team_leader
def copy_all_talks():
    """Copy the USB gold copy on to every connected USB drive"""

    # First, detect all USB drives
    # Then, give up if any aren't either ~8GB, ~16GB or ~128GB
    # Then, copy the USB gold to /dev/shm
    # Then, spawn a bunch of children to do some rsyncing


@app.route("/duplication", methods=["GET"])
@login_required
@current_user_is_team_leader
def duplication():
    """Functions and instructions for the duplication team"""

    return render_template("duplication.html")


@app.route("/recorders", methods=["GET", "POST"])
@login_required
@current_user_is_team_leader
def recorders():
    """View or add recorders to the database"""

    if request.method == "POST":
        if "file" not in request.files:
            flash("No file part")
            return redirect(request.url)

        file = request.files["file"]

        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_DIR"], filename))

            Recorder.query.delete()

        with open(
            os.path.join(app.config["UPLOAD_DIR"], filename), newline=""
        ) as csvfile:
            recordersreader = csv.reader(csvfile)

            for recorder_line in recordersreader:
                recorder = Recorder(
                    name=recorder_line[0],
                    max_shifts_per_day=recorder_line[1],
                )
                db.session.add(recorder)

        db.session.commit()

        return redirect(url_for("recorders"))

    recorders = Recorder.query.all()
    return render_template("recorders.html", recorders=recorders)


@app.route("/front_desk", methods=["GET", "POST"])
@login_required
@current_user_is_team_leader
def front_desk():
    """Management functions for front desk"""

    gb_year = str(app.config["GB_FRIDAY"][2:4])
    gb_prefix = "gb" + gb_year + "-"

    raw_files = (
        set(
            [
                int(x.name.replace("_RAW.mp3", "").replace(gb_prefix, ""))
                for x in os.scandir(app.config["UPLOAD_DIR"])
                if x.name.endswith("RAW.mp3")
            ]
        )
        or set()
    )

    past_horizon = datetime.now() + timedelta(minutes=30)

    talks_to_upload = Talk.query.filter(Talk.start_time < past_horizon).order_by(
        asc(Talk.start_time)
    )

    return render_template(
        "front_desk.html",
        talks_to_upload=talks_to_upload,
        raw_talks_available=raw_files,
    )


@app.route("/editing", methods=["GET", "POST"])
@login_required
@current_user_is_team_leader
def editing():
    """Where editors obtain and upload files"""

    if request.method == "POST":
        if request.form["form_name"] == "upload_editors_list":
            if "file" not in request.files:
                flash("No file part")
                return redirect(request.url)

            file = request.files["file"]

            if file:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config["UPLOAD_DIR"], filename))

                Editor.query.delete()

                with open(
                    os.path.join(app.config["UPLOAD_DIR"], filename), newline=""
                ) as csvfile:
                    editorsreader = csv.reader(csvfile)

                    for editor_line in editorsreader:
                        editor = Editor(
                            name=editor_line[0],
                        )
                        db.session.add(editor)

        elif request.form["form_name"] == "assign_talk":
            editor = Editor.query.filter(name=request.form["editor_to_assign"]).first()
            talk = Talk.query.filter(id=request.form["talk_id"]).first()

            editor.talks.append(talk)

            db.session.add(editor)
            db.session.add(talk)
            db.session.commit()

            return redirect(url_for("editing"))

        elif request.form["form_name"] == "upload_edited_talk":
            pass

        db.session.commit()
        return redirect(url_for("editing"))

    else:
        if request.args.get("download_raw_talk"):
            return send_from_directory(
                app.config["UPLOAD_DIR"],
                filename=request.args["download_raw_talk"] + "_RAW.mp3",
                as_attachment=True,
            )

    gb_year = str(app.config["GB_FRIDAY"][2:4])
    gb_prefix = "gb" + gb_year + "-"

    raw_files = (
        set(
            [
                x.name.replace("_RAW.mp3", "").replace(gb_prefix, "")
                for x in os.scandir(app.config["UPLOAD_DIR"])
                if x.name.endswith("RAW.mp3")
            ]
        )
        or set()
    )
    edited_files = (
        set(
            [
                x.name.replace("_EDITED.mp3", "").replace(gb_prefix, "")
                for x in os.scandir(app.config["UPLOAD_DIR"])
                if x.name.endswith("EDITED.mp3")
            ]
        )
        or set()
    )
    processed_files = (
        set(
            [
                x.name.replace("mp3.mp3", "").replace(gb_prefix, "")
                for x in os.scandir(app.config["PROCESSED_DIR"])
                if x.name.endswith("mp3.mp3")
            ]
        )
        or set()
    )

    talks_to_edit = Talk.query.filter(
        Talk.id.in_(set(raw_files.difference(edited_files)))
    ).order_by(asc(Talk.start_time))

    # - A way for someone to download raw files, assign a talk to an editor, upload the edited files
    editors = Editor.query.all()
    return render_template(
        "editing.html",
        editors=editors,
        talks_to_edit=talks_to_edit,
        raw_talks_available=raw_files,
        edited_talks_available=edited_files,
        processed_talks_available=processed_files,
    )


@app.route("/getfile", methods=["GET"])
@login_required
@current_user_is_team_leader
def getfile():
    """Download a file"""

    file_type = request.args.get("file_type")
    talk_id = request.args.get("talk_id")

    talk = Talk.query.get(talk_id)

    return send_file(
        get_path_for_file(talk_id, file_type, talk.title, talk.speaker),
        as_attachment=True,
    )


@app.route("/upload_cover_image", methods=["POST"])
@login_required
@current_user_is_team_leader
def upload_cover_image():
    """Upload a new cover image, then redirect back to where you came from"""

    source_path = request.referrer.split("/")[-1]

    if "file" not in request.files:
        flash("No file part")
        return redirect(request.url)

    file = request.files["file"]

    if file:
        kind = filetype.guess(file.read(261))
        file.seek(0)
        if kind.extension == "png":
            file.save(app.config["IMG_DIR"] + "/alltalksicon.png")
        else:
            flash("Must be a PNG")

    return redirect(url_for(source_path))


@app.route("/uploadtalk", methods=["POST"])
@login_required
@current_user_is_team_leader
def uploadtalk():
    """Upload a talk file, then redirect back to where you came from"""

    file_type = request.form.get("file_type")
    talk_id = request.form.get("talk_id")

    source_path = request.referrer.split("/")[-1]

    if "file" not in request.files:
        flash("No file part")
        return redirect(request.url)

    file = request.files["file"]

    if file:
        # Save it to /tmp for now
        uploaded_file_path = os.path.join("/tmp", shortuuid.uuid())
        file.save(uploaded_file_path)
        # Check the size, and then see if another file of the same size exists in the relevant directory for the file type, error if so
        uploaded_file_size = os.path.getsize(uploaded_file_path)

        for root, dirs, files in os.walk(app.config["UPLOAD_DIR"]):
            for name in files:
                if name.endswith(".mp3"):
                    existing_file_path = os.path.join(root, name)
                    existing_file_size = os.path.getsize(existing_file_path)

                    if existing_file_size == uploaded_file_size:
                        app.logger.error(
                            "File size collision detected: %s has size %s bytes, which is the same as uploaded file %s",
                            existing_file_path,
                            existing_file_size,
                            uploaded_file_path,
                        )

                        error_message = """
The file you uploaded had the same file size as an existing file: {}; {} bytes

Your file has been uploaded to {}

This almost certainly means that the file has the same contents. Usually, this means that a mistake is in the process of being made.

Speak to your nearest team leader for advice.

If you are the nearest team leader, check the contents of the existing file and the new file carefully, and make a decision as to which one is the correct one. You might need to delete the existing file to allow this one to be uploaded. Don't forget to clean up when you're done - such as checking for CD files, processed files, database entries, already-shipped USBs, etc.
""".format(
                            existing_file_path, existing_file_size, uploaded_file_path
                        )

                        return render_template("error.html", error_text=error_message)

        # If we've made it this far, we're all good - move the file into position
        talk = Talk.query.get(talk_id)
        shutil.move(
            uploaded_file_path,
            os.path.join(
                get_path_for_file(talk_id, file_type, talk.title, talk.speaker)
            ),
        )

    return redirect(url_for(source_path))


@app.route("/uploadrecordernotes", methods=["POST"])
@login_required
@current_user_is_team_leader
def uploadrecordernotes():
    """Upload a recorder notes photo, then redirect back where you came from"""

    talk_id = request.form.get("talk_id")

    source_path = request.referrer.split("/")[-1]

    if "file" not in request.files:
        flash("No file!")
        return redirect(request.url)

    file = request.files["file"]

    if file:
        kind = filetype.guess(file.read(261))
        if kind.extension == "jpg":
            file.save(
                app.config["IMG_DIR"]
                + "/gb"
                + str(app.config["GB_FRIDAY"][2:4])
                + "-"
                + talk_id
                + "recorder_notes.jpg"
            )
        else:
            flash("Must be a JPEG")

    return redirect(url_for(source_path))


@app.route("/deletetalk", methods=["POST"])
@login_required
@current_user_is_team_leader
def deletetalk():
    """Delete a talk file"""

    file_type = request.form.get("file_type")
    talk_id = request.form.get("talk_id")

    talk = Talk.query.get(talk_id)

    os.remove(get_path_for_file(talk_id, file_type, talk.title, talk.speaker))

    source_path = request.referrer.split("/")[-1]
    return redirect(url_for(source_path))


@app.route("/talks_archive.csv", methods=["GET"])
def talks_archive():
    """ CSV download of talks products for import into the GB website """

    import pyexcel as pe
    import io
    from flask import make_response

    talks = [["Title", "Description", "Talk ID", "Talk Variation ID", "Media", "Price", "Virtual", "Downloadable", "Shipping Class", "MP3 Filename", "MP3 URL", "Speakers", "Festival", "Date and Time", "Panel", "Venue", "Categories", "Talks Category", "Talks Category2", "Talks Category3", "Parental Advisory", "Explicit Content", "Copyright", "Technical"]]

    for t in Talk.query.all():
        talks.append([
            t.title, 
            t.description, 
            "GB" + app.config["GB_SHORT_YEAR"] + "-" + str(t.id).zfill(3),
            "", "", "", "", "", "", 
            get_path_for_file(t.id, "processed", t.title, t.speaker).split('/')[-1],
            "/home/greenbeltorg/digital_downloads/" + get_path_for_file(t.id, "processed", t.title, t.speaker).split('/')[-1],
            t.speaker,
            "20" + app.config["GB_SHORT_YEAR"],
            t.start_time,
            "No",
            t.venue,
            "Talks",
            "","","",
            "Yes" if t.has_distressing_content_warning_sticker else "",
            "Yes" if t.has_explicit_warning_sticker else "",
            "Yes" if t.has_copyright_removal_sticker else "",
            "Yes" if t.has_technical_issues_sticker else ""
        ])

    sheet = pe.Sheet(talks)
    io = io.StringIO()
    sheet.save_to_memory("csv", io)
    output = make_response(io.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=talks_archive.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@app.route("/talks_products.csv", methods=["GET"])
def talks_products():
    """ CSV download of talks products for import into the GB website """

    import pyexcel as pe
    import io
    from flask import make_response

    talks = [["Title", "Description", "Talk ID", "Talk Variation ID", "Media", "Price", "Virtual", "Downloadable", "Shipping Class", "MP3 Filename", "MP3 URL", "Speakers", "Festival", "Date and Time", "Panel", "Venue", "Categories", "Talks Category", "Talks Category2", "Talks Category3", "Parental Advisory", "Explicit Content", "Copyright", "Technical"]]

    for t in Talk.query.all():
        talks.append([
            t.title,
            t.description,
            "GB" + app.config["GB_SHORT_YEAR"] + "-" + str(t.id).zfill(3),
            "", "", "", "", "", "",
            get_path_for_file(t.id, "processed", t.title, t.speaker).split('/')[-1],
            "/home/greenbeltorg/digital_downloads/" + get_path_for_file(t.id, "processed", t.title, t.speaker).split('/')[-1],
            t.speaker,
            "20" + app.config["GB_SHORT_YEAR"],
            t.start_time,
            "No",
            t.venue,
            "Talks",
            "","","",
            "Yes" if t.has_distressing_content_warning_sticker else "",
            "Yes" if t.has_explicit_warning_sticker else "",
            "Yes" if t.has_copyright_removal_sticker else "",
            "Yes" if t.has_technical_issues_sticker else ""
        ])
        talks.append(
        [
            "", "",
            "GB" + app.config["GB_SHORT_YEAR"] + "-" + str(t.id).zfill(3) + "-DL",
            "GB" + app.config["GB_SHORT_YEAR"] + "-" + str(t.id).zfill(3),
            "download",
            3,
            "yes", "yes",
            "",
            get_path_for_file(t.id, "processed", t.title, t.speaker).split('/')[-1],
            "/home/greenbeltorg/digital_downloads/" + get_path_for_file(t.id, "processed", t.title, t.speaker).split('/')[-1],
            "", "", "", "", "", "", "", "", "", "", ""
        ])
        talks.append(
        [
            "", "",
            "GB" + app.config["GB_SHORT_YEAR"] + "-" + str(t.id).zfill(3) + "-MS",
            "GB" + app.config["GB_SHORT_YEAR"] + "-" + str(t.id).zfill(3),
            "memory-stick",
            3,
            "", "",
            "memory-stick"
            "","",
            "", "", "", "", "", "", "", "", "", "", ""
        ])

    sheet = pe.Sheet(talks)
    io = io.StringIO()
    sheet.save_to_memory("csv", io)
    output = make_response(io.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=talks_products.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have logged out")
    return redirect(url_for("index"))

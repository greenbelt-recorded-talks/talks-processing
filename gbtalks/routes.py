import csv
import os
import shutil
from datetime import datetime, timedelta
from functools import wraps

import filetype
import shortuuid
from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from flask import current_app as app
from flask_login import login_required, logout_user
from flask_login.utils import _get_user
from sqlalchemy import asc
from werkzeug.local import LocalProxy
from werkzeug.utils import secure_filename

from .libgbtalks import (
    calculate_greenbelt_friday,
    describe_file,
    extract_audio_from_video_async,
    festival_cycle_start,
    gb_time_to_datetime,
    get_path_for_file,
    get_path_for_video_file,
    get_video_processing_status,
    normalise_cover_image,
)
from .models import Editor, Recorder, Talk, db
from .talks_csv import TalksCsvError, parse_talks_csv

# Supported file formats for RAW uploads
SUPPORTED_RAW_AUDIO_EXTENSIONS = ['mp3']
SUPPORTED_RAW_VIDEO_EXTENSIONS = ['mp4']



# current_user is a proxy for the current user
current_user = LocalProxy(lambda: _get_user())


def current_user_is_team_leader(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        """Make sure that the user is on the list of team leaders"""
        if current_user.email not in app.config["TEAM_LEADERS_EMAILS"]:
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

                # Parse the whole file before touching the database, so a
                # malformed upload leaves the existing talks alone.
                with open(
                    os.path.join(app.config["UPLOAD_DIR"], filename),
                    newline="",
                    encoding="utf-8",
                ) as csvfile:
                    try:
                        parsed_talks = parse_talks_csv(csvfile)
                    except TalksCsvError as error:
                        flash(f"Could not read {filename}: {error}", "error")
                        return redirect(request.url)

                Talk.query.delete()
                for talk_data in parsed_talks:
                    db.session.add(Talk(**talk_data))

                db.session.commit()
                flash(f"Loaded {len(parsed_talks)} talks from {filename}", "success")
                return redirect(url_for("talks", filename=filename))

    talks = Talk.query.order_by(asc(Talk.start_time)).all()
    raw_files = [x.name for x in os.scandir(app.config["UPLOAD_DIR"])]
    edited_files = [x.name for x in os.scandir(app.config["UPLOAD_DIR"])]
    processed_files = [
        x.name.split("_")[1] for x in os.scandir(app.config["PROCESSED_DIR"])
    ]
    notes_files = [x.name for x in os.scandir(app.config["IMG_DIR"])]
    recorders = Recorder.query.order_by(Recorder.name).all()

    return render_template(
        "talks.html",
        gb_year=app.config["GB_SHORT_YEAR"],
        talks=talks,
        raw_files=raw_files,
        edited_files=edited_files,
        processed_files=processed_files,
        notes_files=notes_files,
        recorders=recorders,
    )

@app.route("/edit_talk", methods=["GET","POST"])
@login_required
@current_user_is_team_leader
def edit_talk():
    """Edit an individual talk in the database"""

    if request.method == "GET":
        talk_id = request.args.get("talk_id")
        # Skip the lookup entirely without an id: SQLAlchemy warns that loading
        # a NULL primary key may become an error in a future release.
        talk = db.session.get(Talk, talk_id) if talk_id else None

        if not talk:
            flash(f"Talk {talk_id} not found", "error")
            return redirect(url_for("talks"))

        return render_template("edit_talk.html",
                                start_time=talk.start_time.strftime("%H:%M:%S"),
                                end_time=talk.end_time.strftime("%H:%M:%S"),
                                talk=talk
                                )


    if request.method == "POST":
        talk_id = request.form.get("talk_id")
        talk = db.session.get(Talk, talk_id)

        if not talk:
            flash(f"Talk {talk_id} not found", "error")
            return redirect(url_for("talks"))

        try:
            # Parse datetime fields with error handling
            start_datetime = gb_time_to_datetime(request.form.get("day"), request.form.get("start_time"))
            end_datetime = gb_time_to_datetime(request.form.get("day"), request.form.get("end_time"))

            # Ensure end time is after start time
            if end_datetime <= start_datetime:
                flash("End time must be after start time", "error")
                return redirect(url_for("edit_talk", talk_id=talk_id))

            # Update talk fields
            talk.title = request.form.get("title")
            talk.description = request.form.get("description")
            talk.speaker = request.form.get("speaker")
            talk.day = request.form.get("day")
            talk.start_time = start_datetime
            talk.end_time = end_datetime

            talk.has_explicit_warning_sticker = True if request.form.get("has_explicit_warning_sticker") else False
            talk.has_distressing_content_warning_sticker = True if request.form.get("has_distressing_content_warning_sticker") else False
            talk.has_technical_issues_sticker = True if request.form.get("has_technical_issues_sticker") else False
            talk.has_copyright_removal_sticker = True if request.form.get("has_copyright_removal_sticker") else False

            talk.is_cleared = True if request.form.get("is_cleared") else False

            db.session.commit()
            flash(f"Successfully updated talk: '{talk.title}'", "success")
            return redirect(url_for("talks") + "#talk_" +  talk_id)

        except ValueError:
            flash("Invalid day or time format", "error")
            return redirect(url_for("edit_talk", talk_id=talk_id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating talk: {str(e)}", "error")
            return redirect(url_for("edit_talk", talk_id=talk_id))


def critical_files():
    """The files that have to be in place before the pipeline will run.

    The health check and the confirm-still-correct route both work from
    this one list, so the route resolves a name to a path itself and never
    has to trust a path arriving from a form.
    """
    return [
        {
            "name": "top.mp3",
            "path": os.path.join(app.config["UPLOAD_DIR"], "top.mp3"),
            "purpose": "Audio segment played at the start of each processed talk",
            "critical": True,
            "used_by": ["Audio processing pipeline"],
            "expected_type": "MP3 audio file",
            "preview": "audio",
            "mimetype": "audio/mpeg",
            "upload": "mp3",
            "upload_label": "an MP3",
            "accept": ".mp3,audio/mpeg"
        },
        {
            "name": "tail.mp3",
            "path": os.path.join(app.config["UPLOAD_DIR"], "tail.mp3"),
            "purpose": "Audio segment played at the end of each processed talk",
            "critical": True,
            "used_by": ["Audio processing pipeline"],
            "expected_type": "MP3 audio file",
            "preview": "audio",
            "mimetype": "audio/mpeg",
            "upload": "mp3",
            "upload_label": "an MP3",
            "accept": ".mp3,audio/mpeg"
        },
        {
            "name": "alltalksicon.png",
            "path": os.path.join(app.config["IMG_DIR"], "alltalksicon.png"),
            "purpose": "Cover art embedded in all processed MP3 files",
            "critical": True,
            "used_by": ["Audio processing pipeline", "MP3 metadata"],
            "expected_type": "Square PNG image file, written by the cover art upload",
            "preview": "image",
            "mimetype": "image/png",
            # Squared and converted on the way in, so a JPEG off the
            # designer's desk is a perfectly good thing to hand it.
            "upload": "cover",
            "upload_label": "a PNG or a JPEG",
            "accept": ".png,.jpg,.jpeg,image/png,image/jpeg"
        },
        {
            "name": f"GB{app.config['GB_SHORT_YEAR']}-AllTalksIndex.pdf",
            "path": os.path.join(app.config["USB_GOLD_DIR"], f"GB{app.config['GB_SHORT_YEAR']}-AllTalksIndex.pdf"),
            "purpose": "Complete index of all talks for USB distribution",
            "critical": True,
            "used_by": ["USB duplication process", "All talks distribution"],
            "expected_type": "PDF document",
            "preview": "pdf",
            "mimetype": "application/pdf",
            "upload": "pdf",
            "upload_label": "a PDF",
            "accept": ".pdf,application/pdf"
        }
    ]


def _is_older_than(path, cutoff):
    """True when path is a file last touched before cutoff (a POSIX timestamp)."""
    try:
        return os.path.isfile(path) and os.stat(path).st_mtime < cutoff
    except OSError:
        return False


def perform_health_check():
    """Perform a comprehensive health check of the system with detailed information"""

    cycle_start = festival_cycle_start()

    health_status = {
        "directories": [],
        "files": [],
        "system_info": [],
        "overall_status": "healthy",
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        # Anything older than this was in place before the last festival ended,
        # so it belongs to a previous year until somebody says otherwise.
        "cycle_start": cycle_start.strftime("%Y-%m-%d"),
        "previous_festival_year": cycle_start.year,
        "stale_count": 0
    }

    # Add system information
    import platform
    health_status["system_info"] = [
        {"key": "Python Version", "value": platform.python_version()},
        {"key": "Platform", "value": platform.platform()},
        {"key": "Current Working Directory", "value": os.getcwd()},
        {"key": "Flask App Name", "value": app.name}
    ]

    # Define required directories and their purposes
    required_dirs = {
        "UPLOAD_DIR": {
            "purpose": "File uploads (raw recordings, edited files, top/tail audio)",
            "critical": True,
            "used_by": ["Front Desk uploads", "Audio processing", "File management"]
        },
        "PROCESSED_DIR": {
            "purpose": "Final processed MP3 files ready for distribution",
            "critical": True,
            "used_by": ["Audio processing pipeline", "CD creation", "Web downloads"]
        },
        "CD_DIR": {
            "purpose": "CD preparation files (WAV segments for burning)",
            "critical": False,
            "used_by": ["CD burning process"]
        },
        "IMG_DIR": {
            "purpose": "Images, cover art, and recorder notes photos",
            "critical": True,
            "used_by": ["MP3 metadata", "Recorder notes", "Cover art"]
        },
        "USB_GOLD_DIR": {
            "purpose": "USB gold master files for duplication",
            "critical": False,
            "used_by": ["USB duplication process", "All talks PDF storage"]
        },
        "WEB_MP3_DIR": {
            "purpose": "Web-ready MP3 files for online access",
            "critical": False,
            "used_by": ["Web downloads", "Online streaming"]
        }
    }

    # Check directories with detailed information
    for dir_key, dir_info in required_dirs.items():
        dir_path = app.config.get(dir_key, "")
        status = {
            "name": dir_key,
            "path": dir_path,
            "purpose": dir_info["purpose"],
            "critical": dir_info["critical"],
            "used_by": dir_info["used_by"],
            "exists": False,
            "is_directory": False,
            "readable": False,
            "writable": False,
            "file_count": 0,
            "total_size": "Unknown",
            "permissions": "Unknown",
            "status": "error",
            "issues": []
        }

        if not dir_path:
            status["issues"].append("Directory path not configured")
        elif os.path.exists(dir_path):
            status["exists"] = True
            status["is_directory"] = os.path.isdir(dir_path)

            if status["is_directory"]:
                status["readable"] = os.access(dir_path, os.R_OK)
                status["writable"] = os.access(dir_path, os.W_OK)

                # Get permissions in octal format
                try:
                    stat_info = os.stat(dir_path)
                    status["permissions"] = oct(stat_info.st_mode)[-3:]
                except Exception:
                    status["permissions"] = "Unknown"

                # Count files and calculate size
                try:
                    files = list(os.scandir(dir_path))
                    status["file_count"] = len([f for f in files if f.is_file()])

                    total_size = sum(f.stat().st_size for f in files if f.is_file())
                    if total_size > 1024**3:  # GB
                        status["total_size"] = f"{total_size / 1024**3:.1f} GB"
                    elif total_size > 1024**2:  # MB
                        status["total_size"] = f"{total_size / 1024**2:.1f} MB"
                    elif total_size > 1024:  # KB
                        status["total_size"] = f"{total_size / 1024:.1f} KB"
                    else:
                        status["total_size"] = f"{total_size} bytes"
                except Exception as e:
                    status["issues"].append(f"Could not scan directory: {e}")

                # Determine status
                if status["readable"] and status["writable"]:
                    status["status"] = "healthy"
                elif status["readable"]:
                    status["status"] = "warning"
                    status["issues"].append("Directory is not writable")
                else:
                    status["status"] = "error"
                    status["issues"].append("Directory is not readable")
            else:
                status["status"] = "error"
                status["issues"].append("Path exists but is not a directory")
        else:
            status["status"] = "error"
            status["issues"].append("Directory does not exist")

        # Update overall status based on critical directories
        if status["status"] == "error" and status["critical"]:
            health_status["overall_status"] = "error"
        elif status["status"] in ["error", "warning"] and health_status["overall_status"] == "healthy":
            health_status["overall_status"] = "warning" if not status["critical"] else "error"

        health_status["directories"].append(status)

    # Check critical files with detailed information
    for file_info in critical_files():
        file_status = {
            "name": file_info["name"],
            "path": file_info["path"],
            "purpose": file_info["purpose"],
            "critical": file_info["critical"],
            "used_by": file_info["used_by"],
            "expected_type": file_info["expected_type"],
            "preview": file_info.get("preview"),
            "upload_label": file_info.get("upload_label"),
            "accept": file_info.get("accept"),
            "exists": False,
            "readable": False,
            "file_size": "Unknown",
            "last_modified": "Unknown",
            "permissions": "Unknown",
            "status": "error",
            "stale": False,
            "found_at": None,
            "issues": [],
            # Media details for the preview, and the reason there are none.
            # Display only: a file the check has found and read is fine by the
            # check's own lights whatever the describer makes of it.
            "details": [],
            "detail_error": None,
            # Bumped when the file changes, so a replaced cover image is not
            # served from the browser cache.
            "cache_key": None
        }

        check_path = file_info["path"]
        if os.path.exists(check_path) and os.path.isfile(check_path):
            file_status["exists"] = True
            file_status["readable"] = os.access(check_path, os.R_OK)
            file_status["found_at"] = check_path

            # Get file details
            mtime = None
            try:
                stat_info = os.stat(check_path)
                file_size = stat_info.st_size
                if file_size > 1024**2:  # MB
                    file_status["file_size"] = f"{file_size / 1024**2:.1f} MB"
                elif file_size > 1024:  # KB
                    file_status["file_size"] = f"{file_size / 1024:.1f} KB"
                else:
                    file_status["file_size"] = f"{file_size} bytes"

                mtime = stat_info.st_mtime
                file_status["last_modified"] = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                file_status["permissions"] = oct(stat_info.st_mode)[-3:]
                file_status["cache_key"] = int(mtime)
            except Exception as e:
                file_status["issues"].append(f"Could not read file details: {e}")

            if file_status["readable"]:
                file_status["details"], file_status["detail_error"] = describe_file(
                    check_path, file_info.get("preview")
                )

            if not file_status["readable"]:
                file_status["status"] = "warning"
                file_status["issues"].append("File is not readable")
            elif mtime is not None and mtime < cycle_start.timestamp():
                # These filenames stay the same from year to year, so an
                # untouched one is indistinguishable from a current one until
                # somebody plays it. Ask.
                file_status["status"] = "stale"
                file_status["stale"] = True
                file_status["issues"].append(
                    f"Not touched since before the {cycle_start.year} festival ended, "
                    "so this may still be last year's file"
                )
            else:
                file_status["status"] = "healthy"
        else:
            file_status["issues"].append("File not found")

        # Update overall status
        if file_status["status"] == "stale":
            health_status["stale_count"] += 1
            if health_status["overall_status"] == "healthy":
                health_status["overall_status"] = "warning"
        elif file_status["status"] == "error" and file_status["critical"]:
            health_status["overall_status"] = "error"
        elif file_status["status"] in ["error", "warning"] and health_status["overall_status"] == "healthy":
            health_status["overall_status"] = "warning" if not file_status["critical"] else "error"

        health_status["files"].append(file_status)

    return health_status


@app.route("/setup", methods=["GET"])
@login_required
@current_user_is_team_leader
def setup():
    """Various setup functions"""

    # Perform comprehensive health check
    health_check = perform_health_check()

    try:
        from .models import RotaSettings
        # Ensure defaults are initialized
        RotaSettings.initialize_defaults()
        rota_settings = RotaSettings.get_all_settings()
    except Exception as e:
        app.logger.error(f"Error loading rota settings: {e}")
        rota_settings = {}
        flash("Warning: Could not load rota settings. Database may need to be recreated.", "warning")

    return render_template("setup.html",
                         rota_settings=rota_settings,
                         current_year=datetime.now().year,
                         health_check=health_check)


@app.route("/health", methods=["GET"])
@login_required
@current_user_is_team_leader
def health_check_page():
    """Detailed system health check page"""

    health_check = perform_health_check()

    return render_template("health_check.html", health_check=health_check)


@app.route("/confirm_file_current", methods=["POST"])
@login_required
@current_user_is_team_leader
def confirm_file_current():
    """Record that a carried-over file has been checked and is right for this year.

    The confirmation is the touch itself: the file's mtime moves into the
    current festival cycle, which is exactly what the health check reads. No
    second copy of the truth to drift out of step with the files.
    """

    requested = request.form.get("name", "")
    files = critical_files()

    if requested == "all":
        cutoff = festival_cycle_start().timestamp()
        wanted = [f for f in files if _is_older_than(f["path"], cutoff)]
        if not wanted:
            flash("Nothing left to confirm", "warning")
            return redirect(url_for("health_check_page"))
    else:
        # Resolved by name against the list above, never by a path from the
        # form - this route touches those four files and nothing else.
        wanted = [f for f in files if f["name"] == requested]
        if not wanted:
            flash("Unknown file - nothing confirmed", "error")
            return redirect(url_for("health_check_page"))

    confirmed = []
    for file_info in wanted:
        path = file_info["path"]

        # Never create the file. An empty top.mp3 would satisfy the exists
        # check and break conversion quietly, which is worse than a red card.
        if not os.path.isfile(path):
            flash(f"{file_info['name']} is not there to confirm", "error")
            continue

        try:
            os.utime(path, None)
            confirmed.append(file_info["name"])
        except OSError as e:
            flash(f"Could not confirm {file_info['name']}: {e}", "error")

    if confirmed:
        flash(f"Confirmed as current for this year: {', '.join(confirmed)}", "success")

    return redirect(url_for("health_check_page"))


@app.route("/critical_file", methods=["GET"])
@login_required
@current_user_is_team_leader
def critical_file():
    """Serve one of the critical files, for the health check page's previews.

    Inline by default, so the page can put top.mp3 in an audio element and the
    cover art in an img; ?download=1 for the save-it-to-your-machine button,
    which is the only thing on offer for the PDF.

    Like the confirm route, the name is resolved against critical_files()
    rather than a path being taken from the query string: this serves those
    four files and nothing else.
    """

    requested = request.args.get("name", "")
    wanted = next((f for f in critical_files() if f["name"] == requested), None)

    if wanted is None:
        flash("Unknown file", "error")
        return redirect(url_for("health_check_page"))

    if not os.path.isfile(wanted["path"]):
        flash(f"{wanted['name']} is not there", "error")
        return redirect(url_for("health_check_page"))

    download = bool(request.args.get("download"))

    return send_file(
        wanted["path"],
        mimetype=wanted.get("mimetype"),
        as_attachment=download,
        download_name=wanted["name"],
    )


@app.route("/replace_critical_file", methods=["POST"])
@login_required
@current_user_is_team_leader
def replace_critical_file():
    """Put a new copy of one of the critical files in place.

    The health check asks "is this one still right?"; confirming is one answer
    and this is the other. Setup can already upload three of these four, but
    it drops you back on the setup page with nothing to look at - here the
    card you have just listened to is the thing you are replacing.

    The name is resolved against critical_files() exactly as the confirm and
    download routes do, so a form cannot nominate a destination of its own.
    """

    requested = request.form.get("name", "")
    wanted = next((f for f in critical_files() if f["name"] == requested), None)

    if wanted is None:
        flash("Unknown file - nothing uploaded", "error")
        return redirect(url_for("health_check_page"))

    file = request.files.get("file")

    if not file or not file.filename:
        flash("No file selected", "error")
        return redirect(url_for("health_check_page"))

    # filetype.guess returns None for anything it cannot place, so the format
    # check cannot go through kind.extension unguarded.
    kind = filetype.guess(file.read(261))
    file.seek(0)
    extension = kind.extension if kind is not None else None

    if wanted["upload"] == "cover":
        if extension not in ("png", "jpg"):
            flash(f"{wanted['name']} must be {wanted['upload_label']}", "error")
            return redirect(url_for("health_check_page"))
        try:
            content = normalise_cover_image(file, app.config["COVER_ART_SIZE"])
        except ValueError:
            flash("That file is not an image we can read", "error")
            return redirect(url_for("health_check_page"))
    else:
        if extension != wanted["upload"]:
            flash(f"{wanted['name']} must be {wanted['upload_label']}", "error")
            return redirect(url_for("health_check_page"))
        content = file.read()

    try:
        with open(wanted["path"], "wb") as f:
            f.write(content)
    except OSError as e:
        flash(f"Could not write {wanted['name']}: {e}", "error")
        return redirect(url_for("health_check_page"))

    flash(f"Replaced {wanted['name']}", "success")

    return redirect(url_for("health_check_page"))


@app.route("/put_alltalks_pdf", methods=["POST"])
@login_required
@current_user_is_team_leader
def put_alltalks_pdf():
    """Upload the all talks PDF to the USB gold copy"""

    if "file" not in request.files:
        flash("No file supplied!", "error")
        return redirect(url_for("setup"))

    file = request.files["file"]

    if file and file.filename:
        filename = "GB" + app.config["GB_SHORT_YEAR"] + "-AllTalksIndex.pdf"
        file.save(os.path.join(app.config["USB_GOLD_DIR"], filename))
        flash("Successfully uploaded All Talks PDF", "success")
    else:
        flash("No file selected", "error")

    return redirect(url_for("setup"))


@app.route("/upload_top_tail", methods=["POST"])
@login_required
@current_user_is_team_leader
def upload_top_tail():
    """Upload top and tail MP3 files for audio processing"""

    file_type = request.form.get("file_type")

    if not file_type or file_type not in ["top", "tail"]:
        flash("Invalid file type", "error")
        return redirect(url_for("setup"))

    if "file" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for("setup"))

    file = request.files["file"]

    if file and file.filename:
        # Validate file type
        kind = filetype.guess(file.read(261))
        file.seek(0)  # Reset file pointer

        if kind and kind.extension == "mp3":
            # Save the file with the correct name in the upload directory
            filename = f"{file_type}.mp3"
            filepath = os.path.join(app.config["UPLOAD_DIR"], filename)
            file.save(filepath)

            flash(f"Successfully uploaded {file_type}.mp3", "success")
        else:
            flash("File must be an MP3", "error")
    else:
        flash("No file selected", "error")

    return redirect(url_for("setup"))


@app.route("/update_festival_year", methods=["POST"])
@login_required
@current_user_is_team_leader
def update_festival_year():
    """Update the festival year and calculate the Friday date automatically"""

    festival_year = request.form.get("festival_year")

    if not festival_year:
        flash("No year provided!", "error")
        return redirect(url_for("setup"))

    try:
        # Parse and validate the year
        year = int(festival_year)

        # Validate reasonable year range (current year to 10 years in future)
        current_year = datetime.now().year
        if year < current_year or year > current_year + 10:
            flash(f"Year must be between {current_year} and {current_year + 10}!", "error")
            return redirect(url_for("setup"))

        # Calculate the Greenbelt Friday for this year
        gb_friday = calculate_greenbelt_friday(year)
        festival_date = gb_friday.strftime("%Y-%m-%d")

        # Update the .env file
        project_folder = os.path.expanduser('~/talks-processing')
        env_path = os.path.join(project_folder, '.env')

        # Read existing .env file or create new content
        env_lines = []
        if os.path.exists(env_path):
            with open(env_path) as f:
                env_lines = f.readlines()

        # Update or add GB_FRIDAY line
        gb_friday_updated = False
        for i, line in enumerate(env_lines):
            if line.startswith('GB_FRIDAY='):
                env_lines[i] = f'GB_FRIDAY={festival_date}\n'
                gb_friday_updated = True
                break

        if not gb_friday_updated:
            env_lines.append(f'GB_FRIDAY={festival_date}\n')

        # Write back to .env file
        with open(env_path, 'w') as f:
            f.writelines(env_lines)

        flash(f"Festival year set to {year}. Calculated Friday date: {festival_date}. Restart the application for changes to take effect.", "success")

    except ValueError:
        flash("Invalid year format!", "error")
        return redirect(url_for("setup"))
    except Exception as e:
        flash(f"Error updating festival year: {str(e)}", "error")
        return redirect(url_for("setup"))

    return redirect(url_for("setup"))


@app.route("/update_rota_settings", methods=["POST"])
@login_required
@current_user_is_team_leader
def update_rota_settings():
    """Update rota configuration settings"""

    from .models import RotaSettings

    try:
        # Get all current settings to validate against
        current_settings = RotaSettings.get_all_settings()

        updated_count = 0
        for key in current_settings.keys():
            if key in request.form:
                new_value = request.form.get(key)
                if new_value and new_value.isdigit():
                    new_value_int = int(new_value)

                    # Special validation for max_shifts_per_day_limit
                    if key == 'max_shifts_per_day_limit' and new_value_int > 3:
                        flash("Maximum shifts per day cannot exceed 3", "error")
                        return redirect(url_for("setup"))

                    current_value = RotaSettings.get_value(key)
                    if new_value_int != current_value:
                        RotaSettings.set_value(key, new_value_int)
                        updated_count += 1
                else:
                    flash(f"Invalid value for {key}: must be a positive integer", "error")
                    return redirect(url_for("setup"))

        if updated_count > 0:
            flash(f"Updated {updated_count} rota setting(s). Changes will apply to new rota generations.", "success")
        else:
            flash("No changes were made to rota settings.", "info")

    except Exception as e:
        flash(f"Error updating rota settings: {str(e)}", "error")

    return redirect(url_for("setup"))


@app.route("/add_talk", methods=["POST"])
@login_required
@current_user_is_team_leader
def add_talk():
    """Add a new talk to the database"""

    try:

        from .models import Talk

        # Get form data
        talk_id = request.form.get('talk_id', '').strip()
        title = request.form.get('title', '').strip()
        speaker = request.form.get('speaker', '').strip()
        description = request.form.get('description', '').strip()
        day = request.form.get('day', '').strip()
        start_time = request.form.get('start_time', '').strip()
        end_time = request.form.get('end_time', '').strip()
        venue = request.form.get('venue', '').strip()

        # Validate required fields
        if not all([talk_id, title, speaker, day, start_time, end_time, venue]):
            flash("All required fields must be filled out", "error")
            return redirect(url_for("setup"))

        # Validate and convert talk ID
        try:
            talk_id = int(talk_id)
            if talk_id <= 0:
                flash("Talk ID must be a positive number", "error")
                return redirect(url_for("setup"))
        except ValueError:
            flash("Talk ID must be a valid number", "error")
            return redirect(url_for("setup"))

        # Check if talk ID already exists
        existing_talk = db.session.get(Talk, talk_id)
        if existing_talk:
            flash(f"Talk ID {talk_id} already exists", "error")
            return redirect(url_for("setup"))

        # Parse time fields using gb_time_to_datetime
        try:
            start_datetime = gb_time_to_datetime(day, start_time)
            end_datetime = gb_time_to_datetime(day, end_time)

            # Ensure end time is after start time
            if end_datetime <= start_datetime:
                flash("End time must be after start time", "error")
                return redirect(url_for("setup"))

        except ValueError:
            flash("Invalid day or time format", "error")
            return redirect(url_for("setup"))

        # Create new talk
        new_talk = Talk(
            id=talk_id,
            title=title,
            speaker=speaker,
            description=description if description else None,
            day=day,
            start_time=start_datetime,
            end_time=end_datetime,
            venue=venue,
            is_priority=bool(request.form.get('is_priority')),
            is_rotaed=bool(request.form.get('is_rotaed')),
            is_cleared=bool(request.form.get('is_cleared')),
            is_cancelled=False  # New talks start as active
        )

        # Add to database
        db.session.add(new_talk)
        db.session.commit()

        flash(f"Successfully added talk: '{title}' by {speaker}", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error adding talk: {str(e)}", "error")
        app.logger.error(f"Error adding talk: {e}")

    return redirect(url_for("setup"))


@app.route("/toggle_talk_cancelled", methods=["POST"])
@login_required
@current_user_is_team_leader
def toggle_talk_cancelled():
    """Toggle the cancelled status of a talk"""

    try:
        talk_id = request.form.get('talk_id')
        action = request.form.get('action')

        if not talk_id or not action:
            flash("Missing talk ID or action", "error")
            return redirect(url_for("talks"))

        talk = db.session.get(Talk, int(talk_id))
        if not talk:
            flash(f"Talk {talk_id} not found", "error")
            return redirect(url_for("talks"))

        if action == "cancel":
            talk.is_cancelled = True
            flash(f"Talk {talk_id} ({talk.title}) has been marked as cancelled", "success")
        elif action == "uncancel":
            talk.is_cancelled = False
            flash(f"Talk {talk_id} ({talk.title}) has been restored to active status", "success")
        else:
            flash("Invalid action", "error")
            return redirect(url_for("talks"))

        db.session.commit()

    except ValueError:
        flash("Invalid talk ID", "error")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating talk status: {str(e)}", "error")
        app.logger.error(f"Error toggling talk cancelled status: {e}")

    return redirect(url_for("talks"))


@app.route("/assign_recorder", methods=["POST"])
@login_required
@current_user_is_team_leader
def assign_recorder():
    """Assign or unassign a recorder to a talk"""

    try:
        talk_id = request.form.get('talk_id')
        recorder_name = request.form.get('recorder_name')

        if not talk_id:
            flash("Missing talk ID", "error")
            return redirect(url_for("talks"))

        talk = db.session.get(Talk, int(talk_id))
        if not talk:
            flash(f"Talk {talk_id} not found", "error")
            return redirect(url_for("talks"))

        # Handle unassignment (empty recorder_name)
        if not recorder_name:
            if talk.recorder_name:
                old_recorder = talk.recorder_name
                talk.recorder_name = None
                db.session.commit()
                flash(f"Removed {old_recorder} from talk {talk_id} ({talk.title})", "success")
            else:
                flash(f"Talk {talk_id} already has no assigned recorder", "info")
            return redirect(url_for("talks"))

        # Validate recorder exists
        recorder = Recorder.query.filter_by(name=recorder_name).first()
        if not recorder:
            flash(f"Recorder '{recorder_name}' not found", "error")
            return redirect(url_for("talks"))

        # Check for time clashes with recorder's existing talks
        for existing_talk in recorder.talks:
            if existing_talk.id != talk.id:  # Don't check against the same talk
                if talks_overlap(talk, existing_talk):
                    flash(f"Cannot assign {recorder_name}: Talk {talk_id} ({talk.start_time.strftime('%H:%M')}-{talk.end_time.strftime('%H:%M')}) clashes with existing assignment to Talk {existing_talk.id} ({existing_talk.start_time.strftime('%H:%M')}-{existing_talk.end_time.strftime('%H:%M')})", "error")
                    return redirect(url_for("talks"))

        # Assign recorder
        old_recorder = talk.recorder_name
        talk.recorder_name = recorder_name
        db.session.commit()

        if old_recorder:
            flash(f"Reassigned talk {talk_id} ({talk.title}) from {old_recorder} to {recorder_name}", "success")
        else:
            flash(f"Assigned {recorder_name} to talk {talk_id} ({talk.title})", "success")

    except ValueError:
        flash("Invalid talk ID", "error")
    except Exception as e:
        db.session.rollback()
        flash(f"Error assigning recorder: {str(e)}", "error")
        app.logger.error(f"Error assigning recorder: {e}")

    return redirect(url_for("talks"))


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
    all_talks = Talk.query.order_by(Talk.start_time).all()
    return render_template("recorders.html", recorders=recorders, all_talks=all_talks)


@app.route("/update_recorder_shifts", methods=["POST"])
@login_required
@current_user_is_team_leader
def update_recorder_shifts():
    """Update a recorder's max shifts per day and time constraints"""

    recorder_name = request.form.get("recorder_name")
    max_shifts_per_day = request.form.get("max_shifts_per_day")
    earliest_start_time = request.form.get("earliest_start_time")
    latest_end_time = request.form.get("latest_end_time")

    if not recorder_name or not max_shifts_per_day:
        flash("Missing recorder name or shifts value", "error")
        return redirect(url_for("recorders"))

    try:
        max_shifts_value = int(max_shifts_per_day)

        if max_shifts_value < 1 or max_shifts_value > 3:
            flash("Max shifts per day must be between 1 and 3", "error")
            return redirect(url_for("recorders"))

        recorder = Recorder.query.filter_by(name=recorder_name).first()
        if not recorder:
            flash(f"Recorder '{recorder_name}' not found", "error")
            return redirect(url_for("recorders"))

        # Handle time constraint updates
        from datetime import time

        # Parse earliest start time
        earliest_time_obj = None
        if earliest_start_time and earliest_start_time.strip():
            try:
                time_parts = earliest_start_time.split(":")
                earliest_time_obj = time(int(time_parts[0]), int(time_parts[1]))
            except (ValueError, IndexError):
                flash("Invalid earliest start time format", "error")
                return redirect(url_for("recorders"))

        # Parse latest end time
        latest_time_obj = None
        if latest_end_time and latest_end_time.strip():
            try:
                time_parts = latest_end_time.split(":")
                latest_time_obj = time(int(time_parts[0]), int(time_parts[1]))
            except (ValueError, IndexError):
                flash("Invalid latest end time format", "error")
                return redirect(url_for("recorders"))

        # Validate time constraint logic
        if earliest_time_obj and latest_time_obj and earliest_time_obj >= latest_time_obj:
            flash("Earliest start time must be before latest end time", "error")
            return redirect(url_for("recorders"))

        # Update recorder fields
        old_shifts = recorder.max_shifts_per_day
        old_earliest = recorder.earliest_start_time
        old_latest = recorder.latest_end_time

        recorder.max_shifts_per_day = max_shifts_value
        recorder.earliest_start_time = earliest_time_obj
        recorder.latest_end_time = latest_time_obj

        db.session.commit()

        # Build success message
        changes = []
        if old_shifts != max_shifts_value:
            changes.append(f"max shifts from {old_shifts} to {max_shifts_value}")
        if old_earliest != earliest_time_obj:
            earliest_str = earliest_time_obj.strftime('%H:%M') if earliest_time_obj else 'no constraint'
            changes.append(f"earliest start time to {earliest_str}")
        if old_latest != latest_time_obj:
            latest_str = latest_time_obj.strftime('%H:%M') if latest_time_obj else 'no constraint'
            changes.append(f"latest end time to {latest_str}")

        if changes:
            flash(f"Updated {recorder_name}'s {', '.join(changes)}", "success")
        else:
            flash(f"No changes made to {recorder_name}", "info")

    except ValueError:
        flash("Invalid number format for max shifts per day", "error")
    except Exception as e:
        flash(f"Error updating recorder: {str(e)}", "error")
        db.session.rollback()

    return redirect(url_for("recorders"))


@app.route("/swap_recorder_assignments", methods=["POST"])
@login_required
@current_user_is_team_leader
def swap_recorder_assignments():
    """Swap recorder assignments between two talks"""

    talk1_id = request.form.get("talk1")
    talk2_id = request.form.get("talk2")

    if not talk1_id or not talk2_id:
        flash("Please select both talks", "error")
        return redirect(url_for("recorders"))

    if talk1_id == talk2_id:
        flash("Please select two different talks", "error")
        return redirect(url_for("recorders"))

    try:
        talk1 = db.session.get(Talk, int(talk1_id))
        talk2 = db.session.get(Talk, int(talk2_id))

        if not talk1 or not talk2:
            flash("One or both talks not found", "error")
            return redirect(url_for("recorders"))

        if not talk1.recorder_name or not talk2.recorder_name:
            flash("Both talks must have assigned recorders", "error")
            return redirect(url_for("recorders"))

        # Get the recorders
        recorder1 = Recorder.query.filter_by(name=talk1.recorder_name).first()
        recorder2 = Recorder.query.filter_by(name=talk2.recorder_name).first()

        if not recorder1 or not recorder2:
            flash("One or both assigned recorders not found", "error")
            return redirect(url_for("recorders"))

        # Validate no timing clashes would occur after swap
        clash_error = check_swap_clashes(talk1, talk2, recorder1, recorder2)
        if clash_error:
            flash(clash_error, "error")
            return redirect(url_for("recorders"))

        # Perform the swap
        talk1.recorder_name = recorder2.name
        talk2.recorder_name = recorder1.name

        db.session.commit()

        flash(f"Successfully swapped recorder assignments: {recorder1.name} ↔ {recorder2.name}", "success")

    except ValueError:
        flash("Invalid talk IDs", "error")
    except Exception as e:
        flash(f"Error swapping assignments: {str(e)}", "error")
        db.session.rollback()

    return redirect(url_for("recorders"))


def check_swap_clashes(talk1, talk2, recorder1, recorder2):
    """Check if swapping the recorder assignments would create timing clashes"""

    # Get all other talks for each recorder (excluding the talk being swapped)
    recorder1_other_talks = [t for t in recorder1.talks if t.id != talk1.id]
    recorder2_other_talks = [t for t in recorder2.talks if t.id != talk2.id]

    # Check if talk2 would clash with recorder1's other talks
    for other_talk in recorder1_other_talks:
        if talks_overlap(talk2, other_talk):
            return f"Cannot swap: Talk {talk2.id} would clash with {recorder1.name}'s existing Talk {other_talk.id}"

    # Check if talk1 would clash with recorder2's other talks
    for other_talk in recorder2_other_talks:
        if talks_overlap(talk1, other_talk):
            return f"Cannot swap: Talk {talk1.id} would clash with {recorder2.name}'s existing Talk {other_talk.id}"

    return None


def talks_overlap(talk_a, talk_b):
    """Check if two talks have overlapping time periods"""
    return (talk_a.start_time < talk_b.end_time and talk_b.start_time < talk_a.end_time)


@app.route("/front_desk", methods=["GET", "POST"])
@login_required
@current_user_is_team_leader
def front_desk():
    """Management functions for front desk"""

    gb_year = str(app.config["GB_FRIDAY"][2:4])
    gb_prefix = "gb" + gb_year + "-"

    raw_files = (
        {

                int(x.name.replace("_RAW.mp3", "").replace(gb_prefix, ""))
                for x in os.scandir(app.config["UPLOAD_DIR"])
                if x.name.endswith("RAW.mp3")

        }
        or set()
    )

    past_horizon = datetime.now() + timedelta(minutes=30)

    talks_to_upload = Talk.query.filter(Talk.start_time < past_horizon, Talk.is_cancelled.is_(False)).order_by(
        asc(Talk.start_time)
    )

    return render_template(
        "front_desk.html",
        talks_to_upload=talks_to_upload,
        raw_talks_available=raw_files,
        supported_audio_extensions=SUPPORTED_RAW_AUDIO_EXTENSIONS,
        supported_video_extensions=SUPPORTED_RAW_VIDEO_EXTENSIONS,
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
        {

                x.name.replace("_RAW.mp3", "").replace(gb_prefix, "")
                for x in os.scandir(app.config["UPLOAD_DIR"])
                if x.name.endswith("RAW.mp3")

        }
        or set()
    )
    edited_files = (
        {

                x.name.replace("_EDITED.mp3", "").replace(gb_prefix, "")
                for x in os.scandir(app.config["UPLOAD_DIR"])
                if x.name.endswith("EDITED.mp3")

        }
        or set()
    )
    processed_files = (
        {

                x.name.replace("mp3.mp3", "").replace(gb_prefix, "")
                for x in os.scandir(app.config["PROCESSED_DIR"])
                if x.name.endswith("mp3.mp3")

        }
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

    talk = db.session.get(Talk, talk_id)

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
        # Whatever comes in - a 2000px JPEG off the designer's desk, a PNG
        # someone already sized - is converted to the square PNG the tagger
        # embeds. filetype.guess returns None for anything it cannot place,
        # so the format check cannot go through kind.extension unguarded.
        kind = filetype.guess(file.read(261))
        file.seek(0)
        if kind is not None and kind.extension in ("png", "jpg"):
            try:
                icon = normalise_cover_image(file, app.config["COVER_ART_SIZE"])
            except ValueError:
                flash("That file is not an image we can read")
            else:
                with open(app.config["IMG_DIR"] + "/alltalksicon.png", "wb") as f:
                    f.write(icon)
                flash("Cover image updated", "success")
        else:
            flash("Must be a PNG or a JPEG")

    return redirect(url_for(source_path))


@app.route("/uploadtalk", methods=["POST"])
@login_required
@current_user_is_team_leader
def uploadtalk():
    """Upload a talk file (audio or video), then redirect back to where you came from"""

    file_type = request.form.get("file_type")
    talk_id = request.form.get("talk_id")

    source_path = request.referrer.split("/")[-1]

    if "file" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for(source_path))

    file = request.files["file"]

    if file and file.filename:
        # Save it to /tmp for now
        uploaded_file_path = os.path.join("/tmp", shortuuid.uuid())
        file.save(uploaded_file_path)

        # Get file extension from filename
        original_filename = file.filename.lower()
        file_extension = original_filename.split('.')[-1] if '.' in original_filename else ''

        # Determine file type based on extension
        is_audio = file_extension in SUPPORTED_RAW_AUDIO_EXTENSIONS
        is_video = file_extension in SUPPORTED_RAW_VIDEO_EXTENSIONS

        # Only allow video or audio files for raw uploads
        if file_type == "raw" and not (is_video or is_audio):
            flash("RAW files must be audio or video files", "error")
            os.remove(uploaded_file_path)
            return redirect(url_for(source_path))
        elif file_type != "raw" and not is_audio:
            flash(f"{file_type} files must be audio files", "error")
            os.remove(uploaded_file_path)
            return redirect(url_for(source_path))

        # Check the size, and then see if another file of the same size exists in the relevant directory for the file type, error if so
        uploaded_file_size = os.path.getsize(uploaded_file_path)

        for root, _dirs, files in os.walk(app.config["UPLOAD_DIR"]):
            for name in files:
                if name.endswith((".mp3", ".mp4", ".mov", ".avi", ".mkv")):
                    existing_file_path = os.path.join(root, name)
                    existing_file_size = os.path.getsize(existing_file_path)

                    if existing_file_size == uploaded_file_size:
                        app.logger.error(
                            "File size collision detected: %s has size %s bytes, which is the same as uploaded file %s",
                            existing_file_path,
                            existing_file_size,
                            uploaded_file_path,
                        )

                        error_message = f"""
The file you uploaded had the same file size as an existing file: {existing_file_path}; {existing_file_size} bytes

Your file has been uploaded to {uploaded_file_path}

This almost certainly means that the file has the same contents. Usually, this means that a mistake is in the process of being made.

Speak to your nearest team leader for advice.

If you are the nearest team leader, check the contents of the existing file and the new file carefully, and make a decision as to which one is the correct one. You might need to delete the existing file to allow this one to be uploaded. Don't forget to clean up when you're done - such as checking for CD files, processed files, database entries, already-shipped USBs, etc.
"""

                        return render_template("error.html", error_text=error_message)

        talk = db.session.get(Talk, talk_id)

        # Handle video files for raw uploads
        if file_type == "raw" and is_video:
            try:
                # Save the video file
                video_file_path = get_path_for_video_file(talk_id, file_extension)
                shutil.move(uploaded_file_path, video_file_path)

                # Start background audio extraction
                raw_audio_path = get_path_for_file(talk_id, file_type, talk.title, talk.speaker)
                success, message = extract_audio_from_video_async(video_file_path, raw_audio_path)

                if success:
                    flash(f"Successfully uploaded video file for Talk {talk_id}: {talk.title}. Audio extraction started in background.", "success")
                else:
                    # If we can't start background processing, clean up and report error
                    if os.path.exists(video_file_path):
                        os.remove(video_file_path)
                    flash(f"Failed to start audio extraction: {message}", "error")

            except Exception as e:
                # Clean up on error
                if os.path.exists(uploaded_file_path):
                    os.remove(uploaded_file_path)
                flash(f"Error processing video file: {str(e)}", "error")
        else:
            # Handle regular audio files
            target_path = get_path_for_file(talk_id, file_type, talk.title, talk.speaker)
            shutil.move(uploaded_file_path, target_path)
            flash(f"Successfully uploaded {file_type} file for Talk {talk_id}: {talk.title}", "success")
    else:
        flash("No file selected", "error")

    return redirect(url_for(source_path))


@app.route("/check_video_status", methods=["GET"])
@login_required
@current_user_is_team_leader
def check_video_status():
    """Check the status of video processing for a specific talk"""

    talk_id = request.args.get("talk_id")

    if not talk_id:
        return jsonify({"success": False, "error": "No talk_id provided"})

    talk = db.session.get(Talk, talk_id)
    if not talk:
        return jsonify({"success": False, "error": f"Talk {talk_id} not found"})

    # Get the expected raw audio path
    raw_audio_path = get_path_for_file(talk_id, "raw", talk.title, talk.speaker)

    # Check processing status
    status, message = get_video_processing_status(raw_audio_path)

    return jsonify({
        "success": True,
        "talk_id": talk_id,
        "status": status,
        "message": message,
        "audio_file_exists": os.path.exists(raw_audio_path)
    })



@app.route("/check_ongoing_uploads", methods=["GET"])
@login_required
@current_user_is_team_leader
def check_ongoing_uploads():
    """Check for ongoing uploads that might affect the front desk"""

    try:
        import glob

        # Find all upload status files in /tmp
        upload_status_files = glob.glob("/tmp/upload_*.status")
        video_status_files = glob.glob(f"{app.config['UPLOAD_DIR']}/*.status")
        chunked_upload_dirs = glob.glob("/tmp/chunks_*")

        app.logger.info(f"Found upload status files: {upload_status_files}")
        app.logger.info(f"Found video status files: {video_status_files}")
        app.logger.info(f"Found chunked upload dirs: {chunked_upload_dirs}")

        ongoing_uploads = {}

        # Check upload status files
        for status_file in upload_status_files:
            try:
                with open(status_file) as f:
                    status_content = f.read().strip()

                # Only include active uploads/processing
                if status_content.startswith(('uploading', 'processing')):
                    session_id = status_file.split('/')[-1].replace('upload_', '').replace('.status', '')

                    # Extract talk_id from status content
                    talk_id = None
                    if 'talk_id=' in status_content:
                        try:
                            # Parse talk_id from formats like "uploading:talk_id=123" or "uploading:talk_id=123:bytes=456"
                            for part in status_content.split(':'):
                                if part.startswith('talk_id='):
                                    talk_id = int(part.split('=')[1])
                                    break
                        except ValueError:
                            pass

                    upload_info = {
                        'type': 'upload',
                        'status': status_content.split(':')[0],
                        'file': status_file,
                        'session_id': session_id
                    }

                    if talk_id:
                        upload_info['talk_id'] = talk_id

                    ongoing_uploads[f"upload_{session_id}"] = upload_info
            except Exception:
                continue

        # Check video processing status files
        for status_file in video_status_files:
            try:
                with open(status_file) as f:
                    status_content = f.read().strip()

                if status_content == 'processing':
                    # Extract talk info from the status file path
                    # Status files are named like: gb24-001_RAW.mp3.status
                    base_name = status_file.replace('.status', '')
                    if '_RAW.mp3' in base_name:
                        # Extract talk ID
                        filename = base_name.split('/')[-1]
                        if filename.startswith('gb') and '-' in filename:
                            talk_id_part = filename.split('-')[1].split('_')[0]
                            try:
                                talk_id = int(talk_id_part)
                                ongoing_uploads[f"video_{talk_id}"] = {
                                    'type': 'video_processing',
                                    'talk_id': talk_id,
                                    'status': 'processing',
                                    'file': status_file
                                }
                            except ValueError:
                                pass
            except Exception:
                continue

        # Check chunked uploads
        for chunk_dir in chunked_upload_dirs:
            try:
                metadata_file = os.path.join(chunk_dir, "metadata.json")
                if os.path.exists(metadata_file):
                    import json
                    with open(metadata_file) as f:
                        metadata = json.load(f)

                    session_id = metadata.get('upload_session_id')
                    talk_id = metadata.get('talk_id')
                    chunks_received = len(metadata.get('chunks_received', []))
                    total_chunks = metadata.get('total_chunks', 0)

                    if chunks_received < total_chunks:  # Upload still in progress
                        ongoing_uploads[f"chunked_{session_id}"] = {
                            'type': 'chunked_upload',
                            'talk_id': talk_id,
                            'chunks_received': chunks_received,
                            'total_chunks': total_chunks,
                            'progress_percent': round((chunks_received / total_chunks) * 100),
                            'status': 'uploading',
                            'file_name': metadata.get('file_name', 'Unknown'),
                            'session_id': session_id
                        }
                    else:
                        # Check if reassembly is in progress
                        reassembly_status_file = os.path.join(chunk_dir, "reassembly.status")
                        if os.path.exists(reassembly_status_file):
                            try:
                                with open(reassembly_status_file) as f:
                                    reassembly_status = f.read().strip()

                                if reassembly_status in ['starting', 'reassembling']:
                                    ongoing_uploads[f"reassembly_{session_id}"] = {
                                        'type': 'reassembly',
                                        'talk_id': talk_id,
                                        'status': reassembly_status,
                                        'file_name': metadata.get('file_name', 'Unknown'),
                                        'session_id': session_id
                                    }
                            except Exception:
                                pass
            except Exception:
                continue

        response_data = {
            "success": True,
            "ongoing_uploads": ongoing_uploads,
            "count": len(ongoing_uploads),
            "debug": {
                "upload_status_files": upload_status_files,
                "video_status_files": video_status_files,
                "upload_dir": app.config.get("UPLOAD_DIR", "Not configured")
            }
        }

        app.logger.info(f"Returning ongoing uploads response: {response_data}")
        return jsonify(response_data)

    except Exception as e:
        app.logger.error(f"Error in check_ongoing_uploads: {str(e)}")
        return jsonify({"success": False, "error": f"Error checking uploads: {str(e)}"})


@app.route("/init_chunked_upload", methods=["POST"])
@login_required
@current_user_is_team_leader
def init_chunked_upload():
    """Initialize a chunked upload session"""

    try:
        talk_id = request.form.get("talk_id")
        file_type = request.form.get("file_type")
        file_name = request.form.get("file_name")
        file_size = request.form.get("file_size")
        total_chunks = request.form.get("total_chunks")

        if not all([talk_id, file_type, file_name, file_size, total_chunks]):
            return jsonify({"success": False, "error": "Missing required parameters"})

        talk = db.session.get(Talk, talk_id)
        if not talk:
            return jsonify({"success": False, "error": f"Talk {talk_id} not found"})

        # Validate file type
        file_extension = file_name.lower().split('.')[-1] if '.' in file_name else ''

        is_audio = file_extension in SUPPORTED_RAW_AUDIO_EXTENSIONS
        is_video = file_extension in SUPPORTED_RAW_VIDEO_EXTENSIONS

        if file_type == "raw" and not (is_video or is_audio):
            return jsonify({"success": False, "error": "RAW files must be audio or video files"})
        elif file_type != "raw" and not is_audio:
            return jsonify({"success": False, "error": f"{file_type} files must be audio files"})

        # Create upload session
        upload_session_id = shortuuid.uuid()
        chunk_dir = os.path.join("/tmp", f"chunks_{upload_session_id}")
        os.makedirs(chunk_dir, exist_ok=True)

        # Store upload metadata
        metadata = {
            "upload_session_id": upload_session_id,
            "talk_id": talk_id,
            "file_type": file_type,
            "file_name": file_name,
            "file_size": int(file_size),
            "total_chunks": int(total_chunks),
            "file_extension": file_extension,
            "is_video": is_video,
            "is_audio": is_audio,
            "chunks_received": [],
            "created_at": datetime.now().isoformat()
        }

        metadata_file = os.path.join(chunk_dir, "metadata.json")
        with open(metadata_file, 'w') as f:
            import json
            json.dump(metadata, f)

        # Check for existing chunks (resume capability)
        existing_chunks = []
        for i in range(int(total_chunks)):
            chunk_file = os.path.join(chunk_dir, f"chunk_{i}")
            if os.path.exists(chunk_file):
                existing_chunks.append(i)

        return jsonify({
            "success": True,
            "upload_session_id": upload_session_id,
            "existing_chunks": existing_chunks,
            "message": f"Upload session initialized. {len(existing_chunks)} chunks already uploaded."
        })

    except Exception as e:
        app.logger.error(f"Error in init_chunked_upload: {str(e)}")
        return jsonify({"success": False, "error": f"Failed to initialize upload: {str(e)}"})


@app.route("/upload_chunk", methods=["POST"])
@login_required
@current_user_is_team_leader
def upload_chunk():
    """Upload a single chunk"""

    try:
        upload_session_id = request.form.get("upload_session_id")
        chunk_number = request.form.get("chunk_number")

        if not upload_session_id or chunk_number is None:
            return jsonify({"success": False, "error": "Missing upload_session_id or chunk_number"})

        chunk_number = int(chunk_number)
        chunk_dir = os.path.join("/tmp", f"chunks_{upload_session_id}")

        if not os.path.exists(chunk_dir):
            return jsonify({"success": False, "error": "Upload session not found"})

        # Load metadata
        metadata_file = os.path.join(chunk_dir, "metadata.json")
        if not os.path.exists(metadata_file):
            return jsonify({"success": False, "error": "Upload session metadata not found"})

        with open(metadata_file) as f:
            import json
            metadata = json.load(f)

        # Get the chunk data
        if 'chunk' not in request.files:
            return jsonify({"success": False, "error": "No chunk data provided"})

        chunk_file_obj = request.files['chunk']
        chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_number}")

        # Save chunk to disk
        chunk_file_obj.save(chunk_path)

        # Update metadata
        if chunk_number not in metadata['chunks_received']:
            metadata['chunks_received'].append(chunk_number)
            metadata['chunks_received'].sort()

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f)

        # Check if all chunks received
        all_chunks_received = len(metadata['chunks_received']) == metadata['total_chunks']

        return jsonify({
            "success": True,
            "chunk_number": chunk_number,
            "chunks_received": len(metadata['chunks_received']),
            "total_chunks": metadata['total_chunks'],
            "upload_complete": all_chunks_received,
            "message": f"Chunk {chunk_number} uploaded successfully"
        })

    except Exception as e:
        app.logger.error(f"Error in upload_chunk: {str(e)}")
        return jsonify({"success": False, "error": f"Failed to upload chunk: {str(e)}"})


@app.route("/complete_chunked_upload", methods=["POST"])
@login_required
@current_user_is_team_leader
def complete_chunked_upload():
    """Complete a chunked upload by reassembling chunks"""

    try:
        upload_session_id = request.form.get("upload_session_id")

        if not upload_session_id:
            return jsonify({"success": False, "error": "Missing upload_session_id"})

        chunk_dir = os.path.join("/tmp", f"chunks_{upload_session_id}")
        metadata_file = os.path.join(chunk_dir, "metadata.json")

        if not os.path.exists(metadata_file):
            return jsonify({"success": False, "error": "Upload session not found"})

        # Load metadata
        with open(metadata_file) as f:
            import json
            metadata = json.load(f)

        # Verify all chunks are present
        if len(metadata['chunks_received']) != metadata['total_chunks']:
            return jsonify({
                "success": False,
                "error": f"Missing chunks: {metadata['total_chunks'] - len(metadata['chunks_received'])} chunks not received"
            })

        # Get talk info before background thread (while we have database context)
        talk_id = metadata['talk_id']
        file_type = metadata['file_type']
        file_extension = metadata['file_extension']
        is_video = metadata['is_video']
        expected_file_size = metadata['file_size']

        talk = db.session.get(Talk, talk_id)
        if not talk:
            return jsonify({"success": False, "error": f"Talk {talk_id} not found"})

        talk_title = talk.title
        talk_speaker = talk.speaker

        # Determine final file path
        if file_type == "raw" and is_video:
            final_path = get_path_for_video_file(talk_id, file_extension)
        else:
            final_path = get_path_for_file(talk_id, file_type, talk_title, talk_speaker)

        # Create status file for tracking reassembly
        reassembly_status_file = os.path.join(chunk_dir, "reassembly.status")

        # Capture the current app instance for background thread
        flask_app = current_app._get_current_object()

        # Reassemble file in background thread
        import threading

        def reassemble_file():
            # Create Flask application context for background thread
            with flask_app.app_context():
                try:
                    # Write status: starting
                    with open(reassembly_status_file, 'w') as f:
                        f.write("starting")

                    # Verify all chunks exist before starting
                    missing_chunks = []
                    for chunk_num in range(metadata['total_chunks']):
                        chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_num}")
                        if not os.path.exists(chunk_path):
                            missing_chunks.append(chunk_num)

                    if missing_chunks:
                        error_msg = f"Missing chunks: {missing_chunks}"
                        with open(reassembly_status_file, 'w') as f:
                            f.write(f"error:{error_msg}")
                        flask_app.logger.error(f"Reassembly failed for talk {talk_id}: {error_msg}")
                        return

                    # Write status: reassembling
                    with open(reassembly_status_file, 'w') as f:
                        f.write("reassembling")

                    # Reassemble chunks
                    flask_app.logger.info(f"Starting reassembly for talk {talk_id}: {final_path}")
                    bytes_written = 0

                    with open(final_path, 'wb') as output_file:
                        for chunk_num in range(metadata['total_chunks']):
                            chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_num}")
                            try:
                                with open(chunk_path, 'rb') as chunk_file:
                                    chunk_data = chunk_file.read()
                                    output_file.write(chunk_data)
                                    bytes_written += len(chunk_data)
                            except Exception as e:
                                error_msg = f"Error reading chunk {chunk_num}: {str(e)}"
                                with open(reassembly_status_file, 'w') as f:
                                    f.write(f"error:{error_msg}")
                                flask_app.logger.error(f"Reassembly failed for talk {talk_id}: {error_msg}")
                                # Clean up partial file
                                if os.path.exists(final_path):
                                    os.remove(final_path)
                                return

                    # Verify file size
                    if bytes_written != expected_file_size:
                        error_msg = f"File size mismatch: expected {expected_file_size}, got {bytes_written}"
                        with open(reassembly_status_file, 'w') as f:
                            f.write(f"error:{error_msg}")
                        flask_app.logger.error(f"Reassembly failed for talk {talk_id}: {error_msg}")
                        # Clean up incorrect file
                        if os.path.exists(final_path):
                            os.remove(final_path)
                        return

                    # Write status: success
                    with open(reassembly_status_file, 'w') as f:
                        f.write("success")

                    flask_app.logger.info(f"Reassembly completed for talk {talk_id}: {final_path} ({bytes_written} bytes)")

                    # Start video processing if needed
                    if file_type == "raw" and is_video:
                        raw_audio_path = get_path_for_file(talk_id, file_type, talk_title, talk_speaker)
                        extract_audio_from_video_async(final_path, raw_audio_path)

                    # Clean up chunks only after successful reassembly
                    import shutil
                    shutil.rmtree(chunk_dir)

                except Exception as e:
                    error_msg = f"Unexpected error during reassembly: {str(e)}"
                    try:
                        with open(reassembly_status_file, 'w') as f:
                            f.write(f"error:{error_msg}")
                    except Exception:
                        pass
                    flask_app.logger.error(f"Reassembly failed for talk {talk_id}: {error_msg}")
                    # Clean up partial file
                    if os.path.exists(final_path):
                        try:
                            os.remove(final_path)
                        except Exception:
                            pass

        # Start reassembly in background
        reassembly_thread = threading.Thread(target=reassemble_file)
        reassembly_thread.daemon = True
        reassembly_thread.start()

        return jsonify({
            "success": True,
            "message": "Upload completed successfully. File is being reassembled.",
            "talk_id": metadata['talk_id'],
            "file_type": metadata['file_type'],
            "upload_session_id": upload_session_id
        })

    except Exception as e:
        app.logger.error(f"Error in complete_chunked_upload: {str(e)}")
        return jsonify({"success": False, "error": f"Failed to complete upload: {str(e)}"})


@app.route("/check_reassembly_status", methods=["GET"])
@login_required
@current_user_is_team_leader
def check_reassembly_status():
    """Check the status of file reassembly after chunked upload"""

    upload_session_id = request.args.get("session_id")

    if not upload_session_id:
        return jsonify({"success": False, "error": "No session_id provided"})

    try:
        chunk_dir = os.path.join("/tmp", f"chunks_{upload_session_id}")
        reassembly_status_file = os.path.join(chunk_dir, "reassembly.status")

        if not os.path.exists(reassembly_status_file):
            # Check if chunk dir exists at all
            if not os.path.exists(chunk_dir):
                return jsonify({
                    "success": True,
                    "status": "completed",
                    "message": "Reassembly completed (chunks cleaned up)"
                })
            else:
                return jsonify({
                    "success": True,
                    "status": "not_started",
                    "message": "Reassembly not yet started"
                })

        with open(reassembly_status_file) as f:
            status_content = f.read().strip()

        if status_content == "starting":
            return jsonify({
                "success": True,
                "status": "starting",
                "message": "Reassembly initializing..."
            })
        elif status_content == "reassembling":
            return jsonify({
                "success": True,
                "status": "reassembling",
                "message": "Reassembling file from chunks..."
            })
        elif status_content == "success":
            return jsonify({
                "success": True,
                "status": "completed",
                "message": "File reassembly completed successfully"
            })
        elif status_content.startswith("error:"):
            error_msg = status_content[6:]  # Remove "error:" prefix
            return jsonify({
                "success": True,
                "status": "error",
                "message": f"Reassembly failed: {error_msg}"
            })
        else:
            return jsonify({
                "success": True,
                "status": "unknown",
                "message": f"Unknown reassembly status: {status_content}"
            })

    except Exception as e:
        return jsonify({"success": False, "error": f"Error checking reassembly status: {str(e)}"})


@app.route("/upload_progress", methods=["GET"])
@login_required
@current_user_is_team_leader
def upload_progress():
    """Check the progress of a streaming upload"""

    upload_session_id = request.args.get("session_id")

    if not upload_session_id:
        return jsonify({"success": False, "error": "No session_id provided"})

    try:
        temp_file_path = os.path.join("/tmp", f"upload_{upload_session_id}")
        status_file = f"{temp_file_path}.status"

        if not os.path.exists(status_file):
            return jsonify({
                "success": True,
                "status": "not_found",
                "message": "Upload session not found"
            })

        with open(status_file) as f:
            status_content = f.read().strip()

        if status_content.startswith("uploading"):
            bytes_uploaded = None

            # Parse bytes from status content like "uploading:talk_id=123:bytes=456"
            if 'bytes=' in status_content:
                try:
                    for part in status_content.split(':'):
                        if part.startswith('bytes='):
                            bytes_uploaded = int(part.split('=')[1])
                            break
                except ValueError:
                    pass

            if bytes_uploaded is not None:
                return jsonify({
                    "success": True,
                    "status": "uploading",
                    "bytes_uploaded": bytes_uploaded,
                    "message": f"Uploading... {bytes_uploaded // (1024*1024)} MB"
                })
            else:
                return jsonify({
                    "success": True,
                    "status": "uploading",
                    "message": "Upload starting..."
                })
        elif status_content.startswith("processing"):
            return jsonify({
                "success": True,
                "status": "processing",
                "message": "Upload complete, processing file..."
            })
        elif status_content.startswith("success:"):
            message = status_content[8:]  # Remove "success:" prefix
            # Clean up status file
            os.remove(status_file)
            return jsonify({
                "success": True,
                "status": "completed",
                "message": message
            })
        elif status_content.startswith("error:"):
            error_msg = status_content[6:]  # Remove "error:" prefix
            # Clean up status file
            os.remove(status_file)
            return jsonify({
                "success": True,
                "status": "error",
                "message": error_msg
            })
        else:
            return jsonify({
                "success": True,
                "status": "unknown",
                "message": f"Unknown status: {status_content}"
            })

    except Exception as e:
        return jsonify({"success": False, "error": f"Error checking progress: {str(e)}"})


@app.route("/uploadtalk_ajax", methods=["POST"])
@login_required
@current_user_is_team_leader
def uploadtalk_ajax():
    """AJAX endpoint for uploading talk files with JSON response"""

    file_type = request.form.get("file_type")
    talk_id = request.form.get("talk_id")

    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file selected"})

    file = request.files["file"]

    if not file or not file.filename:
        return jsonify({"success": False, "error": "No file selected"})

    try:
        # Save it to /tmp for now
        uploaded_file_path = os.path.join("/tmp", shortuuid.uuid())
        file.save(uploaded_file_path)

        # Get file extension from filename
        original_filename = file.filename.lower()
        file_extension = original_filename.split('.')[-1] if '.' in original_filename else ''

        # Determine file type based on extension
        is_audio = file_extension in SUPPORTED_RAW_AUDIO_EXTENSIONS
        is_video = file_extension in SUPPORTED_RAW_VIDEO_EXTENSIONS

        # Only allow video or audio files for raw uploads
        if file_type == "raw" and not (is_video or is_audio):
            os.remove(uploaded_file_path)
            return jsonify({"success": False, "error": "RAW files must be audio or video files"})
        elif file_type != "raw" and not is_audio:
            os.remove(uploaded_file_path)
            return jsonify({"success": False, "error": f"{file_type} files must be audio files"})

        # Check the size, and then see if another file of the same size exists in the relevant directory for the file type, error if so
        uploaded_file_size = os.path.getsize(uploaded_file_path)

        for root, _dirs, files in os.walk(app.config["UPLOAD_DIR"]):
            for name in files:
                if name.endswith((".mp3", ".mp4", ".mov", ".avi", ".mkv")):
                    existing_file_path = os.path.join(root, name)
                    existing_file_size = os.path.getsize(existing_file_path)

                    if existing_file_size == uploaded_file_size:
                        app.logger.error(
                            "File size collision detected: %s has size %s bytes, which is the same as uploaded file %s",
                            existing_file_path,
                            existing_file_size,
                            uploaded_file_path,
                        )

                        os.remove(uploaded_file_path)
                        return jsonify({
                            "success": False,
                            "error": f"File size collision detected with existing file: {existing_file_path} ({existing_file_size} bytes). This usually means duplicate content."
                        })

        talk = db.session.get(Talk, talk_id)
        if not talk:
            os.remove(uploaded_file_path)
            return jsonify({"success": False, "error": f"Talk {talk_id} not found"})

        # Handle video files for raw uploads
        if file_type == "raw" and is_video:
            # Save the video file
            video_file_path = get_path_for_video_file(talk_id, file_extension)
            shutil.move(uploaded_file_path, video_file_path)

            # Start background audio extraction
            raw_audio_path = get_path_for_file(talk_id, file_type, talk.title, talk.speaker)
            success, message = extract_audio_from_video_async(video_file_path, raw_audio_path)

            if success:
                return jsonify({
                    "success": True,
                    "message": f"Successfully uploaded video file for Talk {talk_id}: {talk.title}. Audio extraction started in background."
                })
            else:
                # If we can't start background processing, clean up and report error
                if os.path.exists(video_file_path):
                    os.remove(video_file_path)
                return jsonify({"success": False, "error": f"Failed to start audio extraction: {message}"})
        else:
            # Handle regular audio files
            target_path = get_path_for_file(talk_id, file_type, talk.title, talk.speaker)
            shutil.move(uploaded_file_path, target_path)
            return jsonify({
                "success": True,
                "message": f"Successfully uploaded {file_type} file for Talk {talk_id}: {talk.title}"
            })

    except Exception as e:
        # Clean up on error
        if 'uploaded_file_path' in locals() and os.path.exists(uploaded_file_path):
            os.remove(uploaded_file_path)
        app.logger.error(f"Error in uploadtalk_ajax: {str(e)}")
        return jsonify({"success": False, "error": f"Error processing file: {str(e)}"})


@app.route("/uploadrecordernotes", methods=["POST"])
@login_required
@current_user_is_team_leader
def uploadrecordernotes():
    """Upload a recorder notes photo, then redirect back where you came from"""

    talk_id = request.form.get("talk_id")

    source_path = request.referrer.split("/")[-1]

    if "file" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for(source_path))

    file = request.files["file"]

    if file and file.filename:
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
            talk = db.session.get(Talk, talk_id)
            flash(f"Successfully uploaded recorder notes photo for Talk {talk_id}: {talk.title}", "success")
        else:
            flash("Must be a JPEG file", "error")
    else:
        flash("No file selected", "error")

    return redirect(url_for(source_path))


@app.route("/deletetalk", methods=["POST"])
@login_required
@current_user_is_team_leader
def deletetalk():
    """Delete a talk file"""

    file_type = request.form.get("file_type")
    talk_id = request.form.get("talk_id")

    talk = db.session.get(Talk, talk_id)

    os.remove(get_path_for_file(talk_id, file_type, talk.title, talk.speaker))

    source_path = request.referrer.split("/")[-1]
    return redirect(url_for(source_path))


@app.route("/talks_archive.csv", methods=["GET"])
def talks_archive():
    """ CSV download of talks products for import into the GB website """

    import io

    import pyexcel as pe
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
            t.start_time.strftime("%A %d %B %Y, %I:%M %p"),
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

    import io

    import pyexcel as pe
    from flask import make_response

    talks = [["Title", "Description", "Talk ID", "Talk Variation ID", "Media", "Price", "Virtual", "Downloadable", "Shipping Class", "MP3 Filename", "MP3 URL", "Speakers", "Festival", "Date and Time", "Panel", "Venue", "Categories", "Talks Category", "Talks Category2", "Talks Category3", "Parental Advisory", "Explicit Content", "Copyright", "Technical"]]

    for t in Talk.query.filter(Talk.is_cleared.is_(True), Talk.is_cancelled.is_(False)).all():
        talks.append([
            t.title,
            t.description,
            "GB" + app.config["GB_SHORT_YEAR"] + "-" + str(t.id).zfill(3),
            "", "", "", "", "", "",
            get_path_for_file(t.id, "processed", t.title, t.speaker).split('/')[-1],
            "/home/greenbeltorg/digital_downloads/" + get_path_for_file(t.id, "processed", t.title, t.speaker).split('/')[-1],
            t.speaker,
            "20" + app.config["GB_SHORT_YEAR"],
            t.start_time.strftime("%A %d %B %Y, %I:%M %p"),
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

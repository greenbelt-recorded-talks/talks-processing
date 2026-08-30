import io
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import abort, send_file
from flask import current_app as app
from mutagen import MutagenError
from mutagen.mp3 import MP3
from PIL import Image, UnidentifiedImageError
from werkzeug.http import dump_options_header

# One implementation, shared with config.Config's GB_FRIDAY default. Re-exported
# here because this is where the rest of the app has always imported it from.
from festival_dates import calculate_greenbelt_friday, default_gb_friday  # noqa: F401


def festival_cycle_start(now=None):
    """
    The moment preparation for the next festival began: the Tuesday after the
    most recently finished festival.

    This is the line between "put in place for this year" and "left over from
    last year". A file not touched since before it is a carry-over, whatever
    its name suggests.

    Deliberately worked out from the clock rather than from GB_FRIDAY. A year
    nobody remembered to roll over is exactly what this is meant to catch, and
    GB_FRIDAY is one of the things that gets forgotten.
    """
    if now is None:
        now = datetime.now()

    # The festival runs Friday to the Bank Holiday Monday, so the Tuesday after
    # is the first day belonging to the next year's cycle.
    cycle_start = calculate_greenbelt_friday(now.year) + timedelta(days=4)
    if now < cycle_start:
        cycle_start = calculate_greenbelt_friday(now.year - 1) + timedelta(days=4)

    return cycle_start


# Character mapping table to avoid FAT filesystem character problems
character_mapping = str.maketrans(
    {
        '"': '＂',
        '*': '＊',
        '/': '∕',
        ':':'：',
        '<':'＜',
        '>':'＞',
        '?':'？',
        '\\':'＼',
        '|':'｜'
    }
)

def get_path_for_file(talk_id, file_type, title=None, speaker=None):
    if file_type in {"raw", "edited"}:
        path = (
            app.config["TALKS_DIRS"][file_type]["directory"]
            + "/gb"
            + app.config["GB_FRIDAY"][2:4]
            + "-"
            + str(talk_id).zfill(3)
            + app.config["TALKS_DIRS"][file_type]["suffix"]
            + ".mp3"
        )

    if file_type == "processed":
        if "," in speaker:
            speaker = speaker.split(",")[0] + " & others"

        path = (
            app.config["TALKS_DIRS"][file_type]["directory"]
            + "/GB"
            + app.config["GB_SHORT_YEAR"]
            + "_"
            + str(talk_id).zfill(3)
            + "_"
            + title[:120].translate(character_mapping)
            + "_"
            + speaker[:120].translate(character_mapping)
            + ".mp3"
        )

    if file_type == "recorder_notes":
        path = (
            app.config["IMG_DIR"]
            + "/gb"
            + str(app.config["GB_SHORT_YEAR"])
            + "-"
            + talk_id
            + "recorder_notes.jpg"
        )

    if file_type == "web_mp3":
        path = (
            app.config["WEB_MP3_DIR"]
            + "/gb"
            + str(app.config["GB_SHORT_YEAR"])
            + "-"
            + str(talk_id).zfill(3)
            + "mp3.mp3"
        )

    return path


# Where nginx has been told it may serve each storage directory from. The
# prefixes are internal URIs, not routes: they exist only inside nginx, and
# ansible/gbtalks-nginx has to carry a matching `internal` location for each.
# Anything not listed here falls back to being served through the app.
X_ACCEL_LOCATIONS = (
    ("UPLOAD_DIR", "/_storage/uploads/"),
    ("PROCESSED_DIR", "/_storage/processed/"),
    ("IMG_DIR", "/_storage/images/"),
    ("WEB_MP3_DIR", "/_storage/web_mp3s/"),
)


def x_accel_uri(path):
    """The internal nginx URI for a file in one of the storage directories.

    None for anything else, which is what makes this safe to hand a path: a
    file nginx has not been told about is served through the app instead.
    Only files sitting directly in one of the directories qualify, which is
    how every one of them is used and leaves no room for a traversal.
    """
    real = os.path.realpath(path)
    for config_key, prefix in X_ACCEL_LOCATIONS:
        if os.path.dirname(real) == os.path.realpath(app.config[config_key]):
            return prefix + quote(os.path.basename(real), safe="")

    return None


def content_disposition(filename, attachment=False):
    """A Content-Disposition header naming a file, non-ASCII names included.

    This is what send_file does for us on the other branch, reproduced because
    Headers.set does not: it quotes the option but does not encode it, so the
    full-width colon character_mapping puts in every processed filename with a
    colon in its title reaches the WSGI server as a raw non-latin-1 character
    and takes the request down with a UnicodeEncodeError.

    An ASCII name gets a plain `filename=`. Anything else gets both: a
    stripped-down `filename=` for clients that only understand that, and the
    RFC 5987 `filename*=UTF-8''...` carrying the real name.
    """
    disposition = "attachment" if attachment else "inline"

    try:
        filename.encode("ascii")
    except UnicodeEncodeError:
        # NFKD then dropping what will not fit: the full-width colon decomposes
        # to an ordinary one, so the fallback name stays readable.
        simple = unicodedata.normalize("NFKD", filename)
        simple = simple.encode("ascii", "ignore").decode("ascii")
        names = {
            "filename": simple,
            "filename*": "UTF-8''" + quote(filename, safe="!#$&+-.^_`|~"),
        }
    else:
        names = {"filename": filename}

    return dump_options_header(disposition, names)


def send_stored_file(path, as_attachment=False):
    """Serve a file out of one of the storage directories.

    Behind nginx this hands the file over rather than pushing it through
    uWSGI: Flask still does the auth check and still decides which file you
    get, then names it in an X-Accel-Redirect header and returns no body.

    That matters because the talks page renders an <audio> player for every
    file of every talk, and each one probes its file for a duration on page
    load. With `processes = 1` those transfers serialise, and nginx's response
    buffering drains the whole file out of the worker even after the browser
    has cancelled - so a probe that needs the first few hundred KB of an MP3
    header costs the entire 150 MB. On HTTP/1.1 the cancel closes the
    connection and nginx drops the upstream request early; on HTTP/2 it is an
    RST_STREAM on a connection that is still open, nginx does not propagate
    it, and every probe pays in full. Measured across GB26: 8.9 MB per request
    on HTTP/1.1 against 48.8 MB on HTTP/2. One machine moving to the https URL
    was enough to make every player on the page give up and show 00:00.

    nginx serves the file from disk and answers the range requests natively,
    so the app is out of the byte path entirely and a probe costs it nothing.
    """
    if not app.config["X_ACCEL_REDIRECT"]:
        return send_file(path, as_attachment=as_attachment)

    internal_uri = x_accel_uri(path)
    if internal_uri is None:
        return send_file(path, as_attachment=as_attachment)

    # send_file's own 404, kept here because nginx would otherwise answer a
    # missing file from an internal location we never meant to expose at all.
    if not os.path.isfile(path):
        abort(404)

    response = app.response_class()
    response.headers["X-Accel-Redirect"] = internal_uri
    response.headers["Content-Type"] = (
        mimetypes.guess_type(path)[0] or "application/octet-stream"
    )
    response.headers["Content-Disposition"] = content_disposition(
        os.path.basename(path), attachment=as_attachment
    )
    # The body stays empty and goes no further than nginx, which throws the
    # whole of it away - Content-Length: 0 and all - and answers from the file
    # instead, filling in its own length and the Content-Range on a partial
    # request. Content-Type and Content-Disposition are the headers that
    # survive, which is why they are set here and the length is not worth
    # trying to remove.
    return response


def get_path_for_video_file(talk_id, file_extension):
    """Get the path for storing video files"""
    path = (
        app.config["UPLOAD_DIR"]
        + "/gb"
        + app.config["GB_FRIDAY"][2:4]
        + "-"
        + str(talk_id).zfill(3)
        + "_VIDEO."
        + file_extension
    )
    return path


def extract_audio_from_video(video_path, audio_output_path):
    """Extract high-quality audio from video file using ffmpeg"""
    try:
        # Use ffmpeg to extract audio at high quality
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vn',  # No video
            '-acodec', 'libmp3lame',  # MP3 codec
            '-ab', '320k',  # High bitrate
            '-ar', '44100',  # 44.1kHz sample rate
            '-y',  # Overwrite output file
            audio_output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            return True, "Audio extracted successfully"
        else:
            return False, f"FFmpeg error: {result.stderr}"

    except FileNotFoundError:
        return False, "FFmpeg not found. Please install ffmpeg."
    except Exception as e:
        return False, f"Error extracting audio: {str(e)}"


def extract_audio_from_video_async(video_path, audio_output_path):
    """Start background audio extraction from video file using ffmpeg"""
    import threading

    # Create a status file to track progress
    status_file = audio_output_path + ".status"

    def background_extraction():
        try:
            # Write status: processing
            with open(status_file, 'w') as f:
                f.write("processing")

            # Use ffmpeg to extract audio at high quality
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vn',  # No video
                '-acodec', 'libmp3lame',  # MP3 codec
                '-ab', '320k',  # High bitrate
                '-ar', '44100',  # 44.1kHz sample rate
                '-y',  # Overwrite output file
                audio_output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                # Write status: success
                with open(status_file, 'w') as f:
                    f.write("success")
            else:
                # Write status: error with message
                with open(status_file, 'w') as f:
                    f.write(f"error: FFmpeg error: {result.stderr}")

        except FileNotFoundError:
            with open(status_file, 'w') as f:
                f.write("error: FFmpeg not found. Please install ffmpeg.")
        except Exception as e:
            with open(status_file, 'w') as f:
                f.write(f"error: Error extracting audio: {str(e)}")

    # Start background thread
    thread = threading.Thread(target=background_extraction)
    thread.daemon = True
    thread.start()

    return True, "Audio extraction started in background"


def get_video_processing_status(audio_output_path):
    """Check the status of video processing"""
    import os

    status_file = audio_output_path + ".status"

    if not os.path.exists(status_file):
        return "not_started", "Processing not started"

    try:
        with open(status_file) as f:
            status_content = f.read().strip()

        if status_content == "processing":
            return "processing", "Audio extraction in progress"
        elif status_content == "success":
            # Clean up status file
            os.remove(status_file)
            return "completed", "Audio extraction completed successfully"
        elif status_content.startswith("error:"):
            error_msg = status_content[6:]  # Remove "error:" prefix
            # Clean up status file
            os.remove(status_file)
            return "error", error_msg
        else:
            return "unknown", f"Unknown status: {status_content}"
    except Exception as e:
        return "error", f"Error reading status: {str(e)}"


def get_cd_dir_for_talk(talk_id):
    """Get the CD directory path for a talk"""
    return (
        app.config["CD_DIR"]
        + "/gb"
        + app.config["GB_SHORT_YEAR"]
        + "-"
        + str(talk_id).zfill(3)
        + "/"
    )


def gb_time_to_datetime(day, time):
    """Convert "Greenbelt Days" to real days, and parse out the start times of talks"""
    fri_of_gb = datetime.strptime(app.config["GB_FRIDAY"], "%Y-%m-%d").date()
    days = {"Friday": 0, "Saturday": 1, "Sunday": 2, "Monday": 3}

    try:
        day_of_talk = fri_of_gb + timedelta(days=days.get(day))
    except TypeError:
        day_of_talk = datetime.strptime(day, "%d/%m/%y").date()

    try:
        time_of_talk = datetime.strptime(time, "%I:%M %p").time()
    except ValueError:
        try:
            time_of_talk = datetime.strptime(time, "%H:%M:%S").time()
        except ValueError:
            time_of_talk = datetime.strptime(time, "%H:%M").time()
    return datetime.combine(day_of_talk, time_of_talk)


def normalise_cover_image(source, size):
    """Turn an uploaded image into the square PNG the MP3 tagger expects.

    Takes anything Pillow can open - the point is that you can hand it the
    2000px JPEG straight from the designer rather than preparing a PNG by
    hand - and returns the PNG bytes.

    A non-square source is padded out to a square with transparency rather
    than centre-cropped. The icon is a logo, and cropping a logo silently
    eats the edges of it; padding is visibly wrong instead of subtly wrong,
    which is the better failure when nobody checks the result until the MP3s
    are already on the USB sticks.

    Raises ValueError if the file is not an image Pillow recognises.
    """
    try:
        with Image.open(source) as img:
            img = img.convert("RGBA")

            # thumbnail() only ever shrinks, so scale explicitly - a source
            # smaller than the target still wants to fill the square.
            scale = size / max(img.width, img.height)
            scaled = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                Image.LANCZOS,
            )

            square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            square.paste(
                scaled,
                ((size - scaled.width) // 2, (size - scaled.height) // 2),
            )

            buffer = io.BytesIO()
            square.save(buffer, format="PNG")
            return buffer.getvalue()
    except UnidentifiedImageError as exc:
        raise ValueError("Not an image file we can read") from exc


def _format_duration(seconds):
    """Seconds as m:ss, or h:mm:ss once it runs past the hour."""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def describe_audio_file(path):
    """What an MP3 will sound like, as (label, value) pairs.

    Duration is the useful one: top.mp3 and tail.mp3 are a few seconds long,
    so anything reported in minutes is a talk somebody has copied into the
    wrong place.

    Raises ValueError if mutagen cannot read it as an MP3.
    """
    try:
        audio = MP3(path)
    except MutagenError as exc:
        raise ValueError("Not an MP3 file we can read") from exc

    info = audio.info
    channels = {1: "Mono", 2: "Stereo"}.get(info.channels, f"{info.channels} channels")

    return [
        ("Duration", _format_duration(info.length)),
        ("Bitrate", f"{round(info.bitrate / 1000)} kbps"),
        ("Sample rate", f"{info.sample_rate / 1000:g} kHz"),
        ("Channels", channels),
    ]


# Measuring loudness means decoding the whole file, so this belongs on the
# short produced assets - top.mp3 is four seconds - and never on a talk from
# inside a request.
LOUDNESS_TIMEOUT_SECONDS = 120

_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\".*?\}", re.S)


def measure_loudness(path):
    """The EBU R128 figures for an audio file, via ffmpeg's loudnorm filter.

    Returns integrated (LUFS), true_peak (dBTP), lra (LU) and threshold.

    Raises ValueError for anything that stops a number coming back, ffmpeg
    not being installed included - that is the normal state of the
    PythonAnywhere deployment, and it must not take the health page with it.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-i", path,
             "-af", "loudnorm=print_format=json", "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=LOUDNESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise ValueError("ffmpeg is not installed here, so levels cannot be "
                         "measured") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Measuring the level took too long") from exc

    found = _LOUDNORM_JSON.search(result.stderr)
    if found is None:
        raise ValueError("ffmpeg could not measure this file's level")

    try:
        measured = json.loads(found.group(0))
        stats = {
            "integrated": float(measured["input_i"]),
            "true_peak": float(measured["input_tp"]),
            "lra": float(measured["input_lra"]),
            "threshold": float(measured["input_thresh"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("ffmpeg's level report could not be read") from exc

    # A silent file measures as -inf, which is a real answer to a different
    # question and poison to every calculation downstream.
    if stats["integrated"] == float("-inf"):
        raise ValueError("This file is silent")

    return stats


def audio_level_check(path, target_lufs, ceiling_dbtp, tolerance_lu=1.0):
    """Where a produced audio asset sits against the level talks are cut to.

    The useful verdict is not only how far off a file is, but whether it can
    be put right by turning it up. A jingle mastered hard against the peak
    ceiling has nowhere to go: reaching the target costs peak limiting, which
    on a finished asset is a compromise rather than a correction. The two
    cases read the same on a loudness meter and want different answers, so
    they are separated here.

    Returns a dict whose "status" is one of:
      ok       - within tolerance of the target
      quiet    - below target, and gain alone will fix it
      loud     - above target; turning down always works
      squashed - below target by more than the headroom allows
      unknown  - could not be measured, and "message" says why
    """
    try:
        stats = measure_loudness(path)
    except ValueError as exc:
        return {"status": "unknown", "message": str(exc), "fixable": False}

    gain = target_lufs - stats["integrated"]
    headroom = ceiling_dbtp - stats["true_peak"]
    target = f"{target_lufs:g} LUFS"

    level = {
        "integrated": stats["integrated"],
        "true_peak": stats["true_peak"],
        "gain": gain,
        "headroom": headroom,
        "limiting": max(gain - headroom, 0.0),
        "fixable": True,
    }

    if abs(gain) <= tolerance_lu:
        level["status"] = "ok"
        level["fixable"] = False
        level["message"] = (
            f"At the {target} target ({stats['integrated']:.1f} LUFS measured)."
        )
    elif gain < 0:
        level["status"] = "loud"
        level["message"] = (
            f"{abs(gain):.1f} LU above the {target} target "
            f"({stats['integrated']:.1f} LUFS measured)."
        )
    elif gain <= headroom:
        level["status"] = "quiet"
        level["message"] = (
            f"{gain:.1f} LU below the {target} target "
            f"({stats['integrated']:.1f} LUFS measured), and there is room to "
            "turn it up."
        )
    else:
        level["status"] = "squashed"
        # A file can be past the ceiling already, which is a different
        # sentence from having a little room left and not enough of it.
        if headroom < 0:
            peaks = (
                f"its peaks are already {abs(headroom):.1f} dB above the "
                f"{ceiling_dbtp:g} dBTP ceiling"
            )
        else:
            peaks = (
                f"its peaks leave only {headroom:.1f} dB of headroom under "
                f"the {ceiling_dbtp:g} dBTP ceiling"
            )
        level["message"] = (
            f"{gain:.1f} LU below the {target} target "
            f"({stats['integrated']:.1f} LUFS measured), but {peaks}. "
            f"Reaching the target means limiting peaks by about "
            f"{level['limiting']:.1f} dB."
        )
        # Past a couple of dB the limiter stops catching stray peaks and
        # starts flattening the thing, which a re-cut with headroom would
        # avoid entirely. Worth saying so before somebody presses the button.
        if level["limiting"] > 2.0:
            level["message"] += (
                " That is enough to hear: better re-cut with headroom if you "
                "can, and use this if you cannot."
            )

    return level


def _render_at_gain(source, destination, gain_db, limit_dbtp=None):
    """Write `source` to `destination` with a fixed gain, optionally limited."""
    chain = f"volume={gain_db:.2f}dB"
    if limit_dbtp is not None:
        # alimiter works on sample peaks, and inter-sample peaks sit a little
        # above them, so it is set below the true-peak ceiling rather than on
        # it. level=disabled because its default is to make the gain back up,
        # which would undo the thing we are here to control.
        chain += f",alimiter=limit={limit_dbtp - 0.5:.2f}dB:level=disabled"

    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-y", "-i", source,
         "-af", chain, "-map_metadata", "0",
         "-c:a", "libmp3lame", "-b:a", "320k", destination],
        capture_output=True,
        text=True,
        timeout=LOUDNESS_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ValueError(
            "ffmpeg could not re-level this file: "
            + "\n".join(result.stderr.strip().splitlines()[-3:])
        )


def relevel_audio(path, target_lufs, ceiling_dbtp, tolerance_lu=0.3, attempts=3):
    """MP3 bytes of `path` brought to the target level, and what it achieved.

    Gain first, and a peak limiter only when the gain will not fit under the
    ceiling without one. A produced jingle wants gain-matching rather than
    compression, so the limiter is here to catch what does not fit, not to
    shape anything.

    Limiting costs loudness, and how much depends entirely on the material, so
    the gain is solved for rather than calculated: render, measure, correct,
    up to `attempts` times. Every attempt renders from the original, so the
    limiter is never applied on top of its own output.

    Re-encoding costs a generation of MP3, which is why it happens at 320k on
    a file that is seconds long. Raises ValueError if the file cannot be
    measured or rendered.

    Returns (mp3_bytes, achieved_stats).
    """
    stats = measure_loudness(path)
    gain = target_lufs - stats["integrated"]
    rendered = None

    with tempfile.TemporaryDirectory(prefix="gbtalks-relevel-") as work:
        destination = os.path.join(work, "relevelled.mp3")

        for _ in range(attempts):
            # Decided from the original's peak each time: the limiter is
            # needed or not, it does not creep in as the gain is corrected.
            needs_limiter = (stats["true_peak"] + gain) > ceiling_dbtp
            _render_at_gain(path, destination, gain,
                            ceiling_dbtp if needs_limiter else None)

            achieved = measure_loudness(destination)
            with open(destination, "rb") as f:
                rendered = (f.read(), achieved)

            error = target_lufs - achieved["integrated"]
            if abs(error) <= tolerance_lu:
                break
            gain += error

    return rendered


def describe_image_file(path):
    """An image's dimensions and format, as (label, value) pairs.

    The tagger wants a square cover, and the upload route produces one, so a
    file that is not square got here some other way and is worth seeing.

    Raises ValueError if Pillow cannot open it.
    """
    try:
        with Image.open(path) as img:
            width, height = img.size
            details = [
                ("Dimensions", f"{width} × {height} px"),
                ("Format", img.format or "Unknown"),
                ("Colour mode", img.mode),
            ]
    except UnidentifiedImageError as exc:
        raise ValueError("Not an image file we can read") from exc

    if width != height:
        details.append(("Shape", "Not square - the cover art upload squares this up"))

    return details


def describe_pdf_file(path):
    """A PDF's version, from its header, as (label, value) pairs.

    Only the header is read. Counting pages properly means a PDF library the
    app has no other use for, and the question this answers on the health
    check page is "is this actually a PDF" - for anything past that, the
    download button is right there.

    Raises ValueError if the file does not begin with a PDF header.
    """
    with open(path, "rb") as pdf:
        header = pdf.read(8)

    if not header.startswith(b"%PDF-"):
        raise ValueError("Does not start with a PDF header")

    return [("Format", f"PDF {header[5:8].decode('ascii', 'replace').strip()}")]


DESCRIBERS = {
    "audio": describe_audio_file,
    "image": describe_image_file,
    "pdf": describe_pdf_file,
}


def describe_file(path, kind):
    """Media details for a file, and whatever went wrong reading them.

    Returns (details, error): a list of (label, value) pairs, and a message
    when the file could not be read as the kind it is meant to be. Both are
    for display only - a file the health check has already found and read is
    present and correct as far as the check is concerned, and a describer
    that chokes on it is a hint to a human, not a verdict.
    """
    describer = DESCRIBERS.get(kind)
    if describer is None:
        return [], None

    try:
        return describer(path), None
    except ValueError as exc:
        return [], str(exc)
    except Exception as exc:  # a truncated or half-written file, most likely
        return [], f"Could not read the file's details: {exc}"

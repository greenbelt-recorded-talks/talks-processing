from flask import current_app as app
from datetime import datetime, timedelta
import subprocess

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

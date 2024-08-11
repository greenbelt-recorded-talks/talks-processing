from flask import current_app as app
from datetime import datetime, timedelta

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
            + app.config["GB_FRIDAY"][2:4]
            + "-"
            + str(talk_id).zfill(3)
            + " "
            + title[:120].replace(
                "/", "∕"
            )  # Replace any forward slashes with UCS-2 codepoint 2215 (division slash)
            + " | "
            + speaker[:120].replace(
                "/", "∕"
            )  # Replace any forward slashes with UCS-2 codepoint 2215 (division slash)
            + ".mp3"
        )

    if file_type == "recorder_notes":
        path = (
            app.config["IMG_DIR"]
            + "/gb"
            + str(app.config["GB_FRIDAY"][2:4])
            + "-"
            + talk_id
            + "recorder_notes.jpg"
        )

    return path

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
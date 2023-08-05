from flask import current_app as app


def get_path_for_file(talk_id, file_type):
    return (
        app.config["TALKS_DIRS"][file_type]["directory"]
        + "/gb"
        + app.config["GB_FRIDAY"][2:4]
        + "-"
        + str(talk_id).zfill(3)
        + app.config["TALKS_DIRS"][file_type]["suffix"]
        + ".mp3"
    )

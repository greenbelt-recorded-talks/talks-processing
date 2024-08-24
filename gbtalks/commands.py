import threading
import os
import json
import subprocess
import click
from flask import current_app as app
from flask.cli import with_appcontext
from werkzeug.exceptions import MethodNotAllowed, NotFound

import shutil

from .models import db, Talk, Recorder, Editor
import sys
from tendo import singleton
from pydub import AudioSegment

from multiprocessing import Pool
from mutagen.id3 import ID3, TALB, TCOP, TIT2, TPE1, TPE2, TRCK, TDRC, COMM, TCMP, APIC
import pprint

from .libgbtalks import (
    get_path_for_file,
    gb_time_to_datetime
)

def run_command(cmd):
    with semaphore:
        os.system(cmd)


def get_cd_dir_for_talk(talk):
    return (
        app.config["CD_DIR"]
        + "/gb"
        + app.config["GB_SHORT_YEAR"]
        + "-"
        + str(talk).zfill(3)
        + "/"
    )


def process_talk(talk_id):
    top = AudioSegment.from_file(app.config["TOP_TAIL_DIR"] + "/" + "top.mp3")
    tail = AudioSegment.from_file(app.config["TOP_TAIL_DIR"] + "/" + "tail.mp3")

    talk = db.session.get(Talk, talk_id)

    # Add the top and tail, create a high-quality mp3
    hq_mp3 = top + AudioSegment.from_file(get_path_for_file(talk.id, "edited")) + tail

    # Export a WAV file of the top/tailed audio into /tmp for further processing
    toptail_path = "/tmp/toptailed" + str(talk.id) + ".wav"
    hq_mp3.export(toptail_path, format="wav")

    # Normalise to a fixed level
    normalized_path = "/tmp/normalized" + str(talk.id) + ".wav"
    subprocess.call(
        [
            "ffmpeg-normalize",
            toptail_path,
            "-o",
            normalized_path,
            "--loudness-range-target",
            "3",
            "-t",
            "-13",
            "-f",
            "-ar",
            "44100",
        ]
    )

    # Load the normalised file back in
    hq_mp3 = AudioSegment.from_file(normalized_path)

    # Create a reduced-bitrate MP3 from the normalized file
    hq_mp3.export(
        get_path_for_file(talk.id, "processed", talk.title, talk.speaker),
        format="mp3",
        bitrate="128k",
    )

    # Put appropriate metadata on the resultant mp3
    mp3 = ID3(get_path_for_file(talk.id, "processed", talk.title, talk.speaker))

    mp3["TALB"] = TALB(text="Greenbelt Festival Talks " + app.config["GB_FRIDAY"][0:4])
    mp3["TCOP"] = TCOP(text=app.config["GB_FRIDAY"][0:4] + " Greenbelt Festivals")
    mp3["TIT2"] = TIT2(text=talk.title)
    mp3["TPE1"] = TPE1(text=talk.speaker)
    mp3["TPE2"] = TPE2(text=talk.speaker)
    mp3["TRCK"] = TRCK(text=str(talk.id))
    mp3["TDRC"] = TDRC(text=str(app.config["GB_FRIDAY"][0:4]))
    mp3["COMM"] = COMM(text=talk.description)
    mp3["TCMP"] = TCMP(text="1")

    with open(app.config["IMG_DIR"] + "/alltalksicon.png", "rb") as albumart:
        mp3["APIC"] = APIC(
            mime="image/png", type=3, desc="Front cover", data=albumart.read()
        )
    mp3.save()



    # Clean up
    if os.path.exists(toptail_path):
        os.remove(toptail_path)

    if os.path.exists(normalized_path):
        os.remove(normalized_path)

    # Copy the file to the web_mp3 directory with filename format gbXX-XXXmp3.mp3
    shutil.copy(get_path_for_file(str(talk.id), "processed", talk.title, talk.speaker), get_path_for_file(str(talk.id), "web_mp3"))

    # Create files for later CD burning
    cd_dir = get_cd_dir_for_talk(talk.id)
    if os.path.exists(cd_dir):
        shutil.rmtree(cd_dir)

    os.makedirs(cd_dir)

    # Split the mp3 into 5min (300k ms) slices
    for idx, cd_file in enumerate(hq_mp3[::300000]):
        cd_file.export(
            cd_dir + "/" + str(idx).zfill(2) + ".wav",
            format="wav",
        )


@click.command()
@with_appcontext
def convert_talks():
    """Create production files (MP3 and CD) from edited files"""

    # Make sure we only run one of these at a time
    only_once_preventer = singleton.SingleInstance(flavor_id="convert_talks")

    gb_year = str(app.config["GB_FRIDAY"][2:4])
    gb_prefix = "gb" + gb_year + "-"

    # Work out which files need to be converted by looking at the filesystem
    # If a talk has an edited file but no converted file, convert it!

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
                x.name.split("-")[1].split(" ")[0]
                for x in os.scandir(app.config["PROCESSED_DIR"])
                if x.name.endswith(".mp3")
            ]
        )
        or set()
    )

    talks = edited_files
    talks.difference_update(processed_files)

    talks_to_process = [x for x in list(talks) if Talk.query.where(Talk.id==x, Talk.is_cleared)] or []

    pprint.pprint("Processing Talks:")
    pprint.pprint(talks_to_process)

    with Pool(3) as p:
        p.map(process_talk, talks_to_process)


def burn_cd(talk_id, cd_index, cd_writer):
    talk_cd_files = [
        x for x in list(os.scandir(get_cd_dir_for_talk(talk_id))) if x.is_file()
    ]
    cd_files = talk_cd_files[::15][cd_index]
    subprocess.call(
        [
            "wodim",
            "dev=/dev/sg" + cd_writer,
            "-dao",
            "-pad",
            "-audio",
            "-eject",
            cd_files,
        ]
    )


@click.command(name="createdb")
@with_appcontext
def create_db():
    db.create_all()
    db.session.commit()
    print("Database tables created")

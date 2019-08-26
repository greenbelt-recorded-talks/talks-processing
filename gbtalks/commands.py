import threading
import os

import subprocess
import click
from flask import current_app as app
from flask.cli import with_appcontext
from werkzeug.exceptions import MethodNotAllowed, NotFound

from .models import db, Talk, Recorder, Editor

from tendo import singleton
from pydub import AudioSegment

from multiprocessing import Pool

import pprint


def run_command(cmd):
    with semaphore:
        os.system(cmd)

def get_path_for_file(talk_id, file_type):
    return (app.config["TALKS_DIRS"][file_type]["directory"] + 
        "/gb" + 
        app.config['GB_FRIDAY'][2:4] + 
        "-"  + 
        str(talk_id).zfill(3) + 
        app.config["TALKS_DIRS"][file_type]["suffix"] + 
        '.mp3')

def get_cd_dir_for_talk(talk):
    return app.config['CD_DIR'] + '/gb' + app.config['GB_FRIDAY'][2:4] + "-"  + str(talk).zfill(3) + '/'

def process_talk(talk):

    top = AudioSegment.from_file(app.config['TOP_TAIL_DIR'] + '/' + 'top.mp3')
    tail = AudioSegment.from_file(app.config['TOP_TAIL_DIR'] + '/' + 'tail.mp3')

    # Add the top and tail, create a high-quality mp3
    hq_mp3 = top + AudioSegment.from_file(get_path_for_file(talk.id, "edited")) + tail

    # Create a reduced-bitrate MP3 from the source MP3
    hq_mp3.export('/tmp/toptailed' + str(talk.id) + '.wav',
                    format='wav',
                    parameters=["-f"])

    # Normalise to a fixed level
    subprocess.call(['ffmpeg-normalize', '/tmp/toptailed' + str(talk.id) + '.wav',
                    '-o', '/tmp/normalized' + str(talk.id) + '.wav',
                    '--loudness-range-target', '3',
                    '-t', '-13', '-f', '-ar', '44100'])

    hq_mp3 = AudioSegment.from_file('/tmp/normalized' + str(talk.id) + '.wav')

    # Create a reduced-bitrate MP3 from the normalized file
    hq_mp3.export(get_path_for_file(talk.id, "processed"),
                    format='mp3',
                    bitrate='128k')

    # Put appropriate metadata on the resultant mp3
    subprocess.call(['mid3v2',
                    "--TALB", "Greenbelt Festival Talks " + app.config['GB_FRIDAY'][:-4],
                    "--TCOP", app.config['GB_FRIDAY'][:-4] + " Greenbelt Festivals",
                    "--TIT2", talk.title,
                    "--TPE1", talk.speaker,
                    "--TPE2", talk.speaker,
                    "--TRCK", str(talk.id),
                    "--TDRC", str(app.config['GB_FRIDAY'][:-4]),
                    "--COMM", talk.description,
                    "--TCMP", "1",
                    "--picture", app.config["IMG_DIR"] + '/alltalksicon.png',
                    get_path_for_file(talk.id, "processed")])

    # Create files for later CD burning
    # Split the mp3 into 5min (300k ms) slices
    os.makedirs(get_cd_dir_for_talk(talk.id))
    for idx,cd_file in enumerate(hq_mp3[::300000]):
         cd_file.export(get_cd_dir_for_talk(talk.id) +
                        '/' +
                        str(idx).zfill(2) +
                        '.wav',
                        format="wav")


@click.command()
@with_appcontext
def convert_talks():
    """Convert edited talks to lower-quality versions to save on disk space"""

    # Make sure we only run one of these at a time
    only_once_preventer = singleton.SingleInstance(flavor_id='convert_talks')

    # Work out which files need to be converted by looking at the filesystem
    # If a talk has an edited file and a snip, but no converted file, convert it!

    edited_files = set([x.name.replace('_EDITED.mp3','').replace('gb19-','') for x in os.scandir(app.config['EDITED_UPLOAD_DIR']) if x.name.endswith('EDITED.mp3')]) or set()
    pprint.pprint(edited_files)
    processed_files = set([x.name.replace('mp3.mp3','').replace('gb19-','') for x in os.scandir(app.config['PROCESSED_DIR']) if x.name.endswith('mp3.mp3')]) or set()
    snip_files = set([x.name.replace('_SNIP.mp3','').replace('gb19-','') for x in os.scandir(app.config['SNIP_DIR']) if x.name.endswith('SNIP.mp3')]) or set()

    pprint.pprint("Edited")
    pprint.pprint(edited_files)
    pprint.pprint("Processed")
    pprint.pprint(processed_files)
    pprint.pprint("Snip")
    pprint.pprint(snip_files)

    # If there are any snips that don't have edited files, or edited files that don't have snips, skip over them and error

    edited_without_snip = set(edited_files.difference(snip_files))
    snip_without_edited = set(snip_files.difference(edited_files))

    exclude_list = set(edited_without_snip|snip_without_edited)

    if len(exclude_list) > 0:
        print("Exclude list:", exclude_list)

    talks = edited_files.union(snip_files) 
    talks.difference_update(exclude_list)
    talks.difference_update(processed_files)

    pprint.pprint("Talks")
    pprint.pprint(talks)
    talks_to_process = [Talk.query.get(x) for x in list(talks)] or []

    top = AudioSegment.from_file(app.config['TOP_TAIL_DIR'] + '/' + 'top.mp3')
    tail = AudioSegment.from_file(app.config['TOP_TAIL_DIR'] + '/' + 'tail.mp3')

    with Pool(3) as p:
        p.map(process_talk, talks_to_process)


def burn_cd(talk_id, cd_index, cd_writer):
    talk_cd_files = [x for x in list(os.scandir(get_cd_dir_for_talk(talk_id))) if x.is_file()]
    cd_files = talk_cd_files[::15][cd_index]
    subprocess.call(['wodim', 'dev=/dev/sg' + cd_writer, '-dao' , '-pad', '-audio', '-eject', cd_files])


@click.command()
@with_appcontext
@click.option('--talk')
@click.option('--cds')
def burn_cds(talk, cds):
    import subprocess

    # Work out how many CDs we need
    # If there are more than 15 files (15 * 5min = 75, capacity of a CD is 79 minutes), we need 2 CDs

    cd_dir = get_cd_dir_for_talk(talk)
    try:
        files = len([x for x in list(os.scandir(cd_dir)) if x.is_file()])

        print("Talk length is " + files_count*5 + " minutes. Ish." )
        
        for cd in cds:
            for idx,cd_files in enumerable(files[::15]):
                print("Burning CD #" + idx)
            

    except:
        print("Talk not ready yet")



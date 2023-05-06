import threading
import os
import json
import subprocess
import click
from flask import current_app as app
from flask.cli import with_appcontext
from werkzeug.exceptions import MethodNotAllowed, NotFound

from .models import db, Talk, Recorder, Editor
import sys
from tendo import singleton
from pydub import AudioSegment

from multiprocessing import Pool
from mutagen.id3 import ID3, TALB, TCOP, TIT2, TPE1, TPE2, TRCK, TDRC, COMM, TCMP, APIC
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

    # Export a WAV file of the top/tailed audio into /tmp for further processing
    hq_mp3.export('/tmp/toptailed' + str(talk.id) + '.wav',
                    format='wav')

    # Normalise to a fixed level
    subprocess.call(['ffmpeg-normalize', '/tmp/toptailed' + str(talk.id) + '.wav',
                    '-o', '/tmp/normalized' + str(talk.id) + '.wav',
                    '--loudness-range-target', '3',
                    '-t', '-13', '-f', '-ar', '44100'])

    # Load the normalised file back in
    hq_mp3 = AudioSegment.from_file('/tmp/normalized' + str(talk.id) + '.wav')

    # Create a reduced-bitrate MP3 from the normalized file
    hq_mp3.export(get_path_for_file(talk.id, "processed"),
                    format='mp3',
                    bitrate='128k')

    # Put appropriate metadata on the resultant mp3
    mp3 = ID3(get_path_for_file(talk.id, "processed"))

    mp3['TALB'] = TALB(text = "Greenbelt Festival Talks " + app.config['GB_FRIDAY'][:-4])
    mp3['TCOP'] = TCOP(text = app.config['GB_FRIDAY'][:-4] + " Greenbelt Festivals")
    mp3['TIT2'] = TIT2(text = talk.title)
    mp3['TPE1'] = TPE1(text = talk.speaker)
    mp3['TPE2'] = TPE2(text = talk.speaker)
    mp3['TRCK'] = TRCK(text = str(talk.id))
    mp3['TDRC'] = TDRC(text = str(app.config['GB_FRIDAY'][:-4]))
    mp3['COMM'] = COMM(text = talk.description)
    mp3['TCMP'] = TCMP(text = '1')

    with open(app.config["IMG_DIR"] + '/alltalksicon.png', 'rb') as albumart:
        mp3['APIC'] = APIC(
                          mime='image/png',
                          type=3, desc='Front cover',
                          data=albumart.read()
                        )
    mp3.save()
    
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
    """Create production files (MP3 and CD) from edited files"""

    # Make sure we only run one of these at a time
    only_once_preventer = singleton.SingleInstance(flavor_id='convert_talks')

    gb_year = str(app.config['GB_FRIDAY'][2:4])
    gb_prefix = "gb" + gb_year + "-"

    # Work out which files need to be converted by looking at the filesystem
    # If a talk has an edited file and a snip, but no converted file, convert it!

    edited_files = set([x.name.replace('_EDITED.mp3','').replace(gb_prefix,'') for x in os.scandir(app.config['EDITED_UPLOAD_DIR']) if x.name.endswith('EDITED.mp3')]) or set()
    processed_files = set([x.name.replace('mp3.mp3','').replace(gb_prefix,'') for x in os.scandir(app.config['PROCESSED_DIR']) if x.name.endswith('mp3.mp3')]) or set()
    snip_files = set([x.name.replace('_SNIP.mp3','').replace(gb_prefix,'') for x in os.scandir(app.config['SNIP_DIR']) if x.name.endswith('SNIP.mp3')]) or set()

    # If there are any snips that don't have edited files, or edited files that don't have snips, skip over them and error

    edited_without_snip = set(edited_files.difference(snip_files))
    snip_without_edited = set(snip_files.difference(edited_files))
    exclude_list = set(edited_without_snip|snip_without_edited)

    if len(exclude_list) > 0:
        print("Excluded due to snip without edited file, or edited file without snip:", exclude_list)

    talks = edited_files.union(snip_files)
    talks.difference_update(exclude_list)
    talks.difference_update(processed_files)

    talks_to_process = [Talk.query.get(x) for x in list(talks)] or []

    pprint.pprint("Processing Talks:")
    pprint.pprint(talks_to_process)

    with Pool(3) as p:
        p.map(process_talk, talks_to_process)


def burn_cd(talk_id, cd_index, cd_writer):
    talk_cd_files = [x for x in list(os.scandir(get_cd_dir_for_talk(talk_id))) if x.is_file()]
    cd_files = talk_cd_files[::15][cd_index]
    subprocess.call(['wodim', 'dev=/dev/sg' + cd_writer, '-dao' , '-pad', '-audio', '-eject', cd_files])

@click.command(name="createdb")
@with_appcontext
def create_db():
    db.create_all()
    db.session.commit()
    print("Database tables created")

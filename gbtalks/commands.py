import threading
import os

from glob import glob
from subprocess import call

import click
from flask import current_app as app
from flask.cli import with_appcontext
from werkzeug.exceptions import MethodNotAllowed, NotFound

from .models import db, Talk, Recorder, Editor

from tendo import singleton
from pydub import AudioSegment

import pprint


def run_command(cmd):
    with semaphore:
        os.system(cmd)


@click.command()
@with_appcontext
def convert_talks():
    """Convert edited talks to lower-quality versions to save on disk space"""

    # Make sure we only run one of these at a time
    only_once_preventer = singleton.SingleInstance(flavor_id='convert_talks')

    # Work out which files need to be converted by looking at the filesystem
    # If a talk has an edited file and a snip, but no converted file, convert it!

    edited_files = set([x.name.replace('EDITED.mp3','') for x in os.scandir(app.config['EDITED_UPLOAD_DIR']) if x.name.endswith('EDITED.mp3')]) or set()
    pprint.pprint(edited_files)
    processsed_files = set([x.name.replace('mp3.mp3','') for x in os.scandir(app.config['PROCESSED_DIR']) if x.name.endswith('mp3.mp3')]) or set()
    snip_files = set([x.name.replace('snip.mp3','') for x in os.scandir(app.config['SNIP_DIR']) if x.name.endswith('snip.mp3')]) or set()

    # If there are any snips that don't have edited files, or edited files that don't have snips, skip over them and error

    edited_without_snip = set(edited_files.difference(snip_files))
    snip_without_edited = set(snip_files.difference(edited_files))

    exclude_list = edited_without_snip|snip_without_edited

    if len(exclude_list) > 0:
        print("Exclude list:", exclude_list)

    talks = edited_files|snip_files - exclude_list
    pprint.pprint("Talks")
    pprint.pprint(talks)
    talks_to_process = [Talk.query.get(x[5:]) for x in list(talks)] or []

    for talk in talks_to_process:
        pprint.pprint(talk)
        talk_data = Talk.query.get(talk.id)

        # Create a reduced-bitrate MP3 from the source MP3
        hq_mp3 = AudioSegment.from_file(app.config['EDITED_UPLOAD_DIR'] + 
                                            "/gb" + 
                                            app.config['GB_FRIDAY'][2:4] + 
                                            "-" +  
                                            str(talk.id).zfill(3) + 'EDITED.mp3')
        
        hq_mp3.export(app.config['PROCESSED_DIR'] + "/gb" + app.config['GB_FRIDAY'][2:4] + "-"  + str(talk.id).zfill(3) + 'mp3.mp3', 
                            format='mp3', 
                            bitrate="96k",
                            tags={'artist': talk.speaker, 
                                'album': 'Greenbelt Festival Talks ' + app.config['GB_FRIDAY'][:-4], 
                                'title': talk.title,
                                'year': app.config['GB_FRIDAY'][:-4],
                                'track': talk.id }
                            )

        # Create files for later CD burning

        # Split the mp3 into 5min (300k ms) slices
        for idx,cd_file in enumerate(hq_mp3[::300000]):
            cd_file.export(app.config['CD_DIR'] + 
                            '/gb' + 
                            app.config['GB_FRIDAY'][2:4] + 
                            "-"  + 
                            str(talk.id).zfill(3) + 
                            '/' + 
                            idx +
                            '.wav',
                            format="wav")



def get_cd_dir_for_talk(talk):
    return app.config['CD_DIR'] + '/gb' + app.config['GB_FRIDAY'][2:4] + "-"  + str(talk).zfill(3) + '/'

def burn_cd(talk, cd_index, cd_writer):
    talk_cd_files = [x for x in list(os.scandir(get_cd_dir_for_talk)) if x.is_file()]
    cd_files = talk_cd_files[::15][cd_index]
    subprocess.run(['wodim', 'dev=/dev/sg' + cd_writer, '-dao' , '-pad', '-audio', '-eject', cd_files])


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



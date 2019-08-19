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

@click.command()
def test():
    print("hello world!")

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
        AudioSegment.from_file(
                app.config['EDITED_UPLOAD_DIR'] + "/gb" + app.config['GB_FRIDAY'][2:4] + "-" +  str(talk.id).zfill(3) + 'EDITED.mp3').export(
                        app.config['PROCESSD_DIR'] + "/gb" + app.config['GB_FRIDAY'][2:4] + "-"  + str(talk.id).zfill(3) + 'mp3.mp3', 
                            format='mp3', 
                            bitrate="96k",
                            tags={'artist': talk.speaker, 
                                'album': 'Greenbelt Festival Talks ' + app.config['GB_FRIDAY'][:-4], 
                                'title': talk.title,
                                'year': app.config['GB_FRIDAY'][:-4],
                                'track': talk.id }
                            )




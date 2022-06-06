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


def copy_all_talks(usb_label):
    # rsync the master copy to the labelled USB

    subprocess.run(['rsync', '--delete', '--archive', '/usb_master/', '/usbs/' + str(usb_label)])

@click.command()
@with_appcontext
def all_talks():
    """Make all talks USBs"""

    # Make sure we only run one of these at a time
    only_once_preventer = singleton.SingleInstance(flavor_id='all_talks')

    completed_all_talks = set()
    usb_label = 1
    command = ''

    # Initialise by scanning all USB ports and starting update runs for all connected drives with labels

    ## Look at all the USBs that are currently plugged in
    lsblk = subprocess.check_output(['lsblk', '-JO'], text=True)
    all_disks = json.loads(lsblk)

    p = Pool(24)

    for usb in [x for x in all_disks['blockdevices'] if x['tran'] == 'usb']:
        try:
            with open(usb['children'][0]['mountpoint'] + '/label', 'r') as content_file:
                usb_label = content_file.read()
            p.apply_async(copy_all_talks(usb_label))
        except (FileNotFoundError, TypeError):
            print("Unlabelled USB found - please remove!")
            sys.exit()

    # Start a continuous loop, which waits for input at the end
    while(command != 'quit'):
        
        lsblk = subprocess.check_output(['lsblk', '-JO'], text=True)
        all_disks = json.loads(lsblk)

        usb_label = command
        
        for usb in [x for x in all_disks['blockdevices'] if x['tran'] == 'usb']:
            try:
                with open(usb['children'][0]['mountpoint'] + '/label', 'r') as content_file:
                    usb_label = content_file.read()
                p.apply_async(copy_all_talks(usb_label))
            except (FileNotFoundError, TypeError):
                # If there isn't a label, then set up the disk and make one
                if click.confirm('Please insert USB with label ' + usb_label):
                    subprocess.run(['sudo', 'mount', '/dev/' + usb['kname'] + '1', '/usbs/' + str(usb_label)])
                    subprocess.run(['sudo', 'chown', '-R', 'gbtalks:', '/usbs/' + str(usb_label), '-o', 'uid=1000,gid=1000,utf8,dmask=027,fmask=137'])
                    file = open('/usbs/' + usb_label + '/label', 'w')
                    file.write(str(usb_label))
                    file.close()


        ### For each one that has a label file, check the list of talks and filesizes against the proof list. Copy any files that are missing or the wrong size. Remove any files that shouldn't be there.
        ### Check the list against the list of all talks that we know of. If the stick is complete, add it to the set of completed all talks stick

        ### If there is one that doesn't have a label file, add one and then copy all the files that we have to the disk

        ### If there is more than one without a label file, ask the user to take one out!



        ## Ask for the ID of the next USB to be plugged in (default to most recent input +1), then end the loop iteration
        print("Plug in a USB, enter its ID, then press Enter")
        command = click.prompt("ID")




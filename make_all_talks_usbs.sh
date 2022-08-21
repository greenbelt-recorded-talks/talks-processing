#!/bin/bash

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

# Then, check that the USB gold dir is there and has at least 50 files in it
# Then, get all of the USB devices from lsblk, and get their /dev locations
# If any are mounted, error out - that's not right
# Then, mount them all at the relevant locations in ~/gbtalks
# Then, start an rsync to each one, and background it 

lsblk -JO | jq '.blockdevices[] | select(.tran == "usb") | .path' | tr -d '"' | xargs -P5 -I {} /home/gbtalks/talks-processing/make_single_all_talks_usb.sh {}


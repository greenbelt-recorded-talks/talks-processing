#!/bin/bash

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

# Then, check that the USB gold dir is there and has at least 50 files in it

if ! ls /storage/usb_gold > /dev/null; then 
    echo "USB gold dir missing"
    exit
fi

if (( $(ls /storage/usb_gold | wc -l ) < 50)); then
    echo "USB gold dir has less than 50 files - are you sure it's ready?"
    exit
fi

# If any USBs are mounted, error out - that's not right


echo -n "There are "
/home/gbtalks/talks-processing/usb_tools/count_connected_usbs.sh
echo " USB drives connected. Press any key to continue, or Ctrl+C to quit"

read

echo "Starting work"

lsblk -JO | jq '.blockdevices[] | select(.tran == "usb") | .path' | tr -d '"' | xargs -P20 -I {} /home/gbtalks/talks-processing/usb_tools/make_single_all_talks_usb.sh {}


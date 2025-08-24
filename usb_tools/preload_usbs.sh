#!/bin/bash

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

if ! ls /storage/usb_gold > /dev/null; then 
    echo "USB gold dir missing"
    exit
fi

echo -n "There are "
/home/gbtalks/talks-processing/usb_tools/count_connected_usbs.sh
echo " USB drives connected. Press any key to continue, or Ctrl+C to quit"

read

echo "Starting work"

lsblk -JO | jq '.blockdevices[] | select(.tran == "usb") | .path' | tr -d '"' | xargs -P20 -I {} /home/gbtalks/talks-processing/usb_tools/make_single_all_talks_usb.sh {}


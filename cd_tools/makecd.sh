#!/bin/bash

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

talk=$(printf %03d $1)

echo $talk

echo "Writing Talk GB25-" $talk " to drive $2"
cd /storage/cds/gb25-$talk || exit 1
sudo wodim dev=/dev/sr$2 -dao -pad -audio -eject * 2>&1 | tee -a ~/cdlog.txt > /dev/null
echo "TALK GB25-$talk WRITTEN TO DRIVE $2"

#!/bin/bash

# Repartition and reformat every connected USB stick. This destroys data.

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit 1
fi

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mapfile -t devices < <("$USB_TOOLS_DIR/list_usb_disks.sh")

if (( ${#devices[@]} == 0 )); then
    echo "No USB drives found - nothing to do"
    exit 1
fi

# This is the one script here that destroys data, so it does not take a
# keypress. Show what is actually about to be wiped - the drives are picked by
# a filter, and the only way to know the filter got it right is to look - and
# make the operator type the whole word.

echo "The following ${#devices[@]} drive(s) will be WIPED - all data on them lost:"
echo
lsblk -d -o PATH,SIZE,VENDOR,MODEL,SERIAL "${devices[@]}"
echo
read -r -p "Type 'yes' to wipe these drives, anything else to quit: " reply

if [[ $reply != "yes" ]]; then
    echo "Aborted - nothing has been written"
    exit 1
fi

echo "Starting work"

printf '%s\n' "${devices[@]}" | xargs -P20 -I {} "$USB_TOOLS_DIR/fix_usb.sh" {}

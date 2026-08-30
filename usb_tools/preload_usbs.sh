#!/bin/bash

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! ls /storage/usb_gold > /dev/null; then 
    echo "USB gold dir missing"
    exit
fi

echo -n "There are "
"$USB_TOOLS_DIR/count_connected_usbs.sh"
echo " USB drives connected. Press any key to continue, or Ctrl+C to quit"

read

echo "Starting work"

"$USB_TOOLS_DIR/list_usb_disks.sh" | xargs -P20 -I {} "$USB_TOOLS_DIR/make_single_all_talks_usb.sh" {}


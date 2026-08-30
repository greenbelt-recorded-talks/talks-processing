#!/bin/bash

# Error unless running as root

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$USB_TOOLS_DIR/list_usb_disks.sh" | xargs -P20 -I {} mkdir -p /usbs{}1

"$USB_TOOLS_DIR/list_usb_disks.sh" | xargs -P20 -I {} mount -o quiet -t vfat {}1 /usbs{}1

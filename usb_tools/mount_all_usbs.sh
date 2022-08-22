#!/bin/bash

# Error unless running as root

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

lsblk -JO | jq '.blockdevices[] | select(.tran == "usb") | .path' | tr -d '"' | xargs -P20 -I {} mkdir -p /usbs{}1

lsblk -JO | jq '.blockdevices[] | select(.tran == "usb") | .path' | tr -d '"' | xargs -P20 -I {} mount -o quiet -t vfat {}1 /usbs{}1

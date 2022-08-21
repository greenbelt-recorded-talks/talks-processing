#!/bin/bash

# Usage ./make_single_all_talks_usb.sh /dev/sda 

# Error unless running as root

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi


mkdir -p /usbs$11
mount -o quiet -t vfat $11 /usbs$11
rsync --size-only --delete -a /usbmaster/ /usbs$11
umount /usbs$11

#!/bin/bash

# Usage ./make_single_all_talks_usb.sh /dev/sda 

# Error unless running as root

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

mkdir -p /usbs$11
sleep 0.5 
mount -o quiet,utf8 -t vfat $11 /usbs$11 && 
	rsync --size-only --delete -a /storage/usb_gold/ /usbs$11 &&
	umount /usbs$11 &&
	sudo fatlabel $11 "GREENBELT"

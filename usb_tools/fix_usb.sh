#!/bin/bash

# Usage: ./fix_usb.sh /dev/sdd

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
	echo "Please run as root"
	exit
fi


# Then, zero out start of the block device

dd if=/dev/zero of=$1 bs=1M count=1

# Then, repartition 

sfdisk $1 << EOF
label: dos
label-id: 0x18eb9334
device: /dev/sdc
unit: sectors
sector-size: 512

/dev/sdc1 : start=          56, size=    15702048, type=b, bootable
EOF

# Finally, format

mkfs.vfat $11

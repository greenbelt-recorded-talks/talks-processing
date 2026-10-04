#!/bin/bash

# Usage: fix_usb.sh /dev/sdc
#
# Repartition and reformat one USB stick. This destroys everything on it.
#
# Note it takes the whole disk, not a partition. In 2025 this was called as
# `fix_usb.sh /dev/sdb1` twice before the mistake was spotted, which zeroed
# the first megabyte of the partition and then went looking for /dev/sdb11.
# Hence the guard below.
#
# This is a repair tool for a stick that turns up wrongly partitioned. It is
# deliberately not part of the build: make_all_talks_usbs.sh mounts and rsyncs
# the filesystem that is already there, which is what makes preloading worth
# doing.

force=false
device=""

while (( $# )); do
    case "$1" in
        --force) force=true ;;
        -h|--help) sed -n '3,15p' "$0" | cut -c 3-; exit 0 ;;
        -*) echo "Unknown option: $1"; exit 1 ;;
        *) device=$1 ;;
    esac
    shift
done

if [[ -z $device ]]; then
    echo "Usage: $(basename "$0") /dev/sdc"
    exit 1
fi

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit 1
fi

if [[ ! -b $device ]]; then
    echo "$device is not a block device"
    exit 1
fi

# A partition reports TYPE=part. Passing one is never what anybody means, so
# there is no --force for this: point it at the disk the partition is on.

kind=$(lsblk -dno TYPE "$device" 2>/dev/null)

if [[ $kind != disk ]]; then
    parent=$(lsblk -dno PKNAME "$device" 2>/dev/null)
    echo "$device is a $kind, not a whole disk."
    echo "Point this at the disk instead${parent:+, i.e. /dev/$parent}"
    exit 1
fi

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# And it has to be one of the drives we are willing to write to - which rules
# out the system disk, the management controller's virtual media, and anything
# too small to take the partition laid out below.

if ! $force && ! "$USB_TOOLS_DIR/list_usb_disks.sh" | grep -qxF "$device"; then
    echo "$device is not a writable USB stick - refusing to wipe it."
    lsblk -dno PATH,SIZE,TRAN,VENDOR,MODEL "$device"
    echo "If you are certain, pass --force."
    exit 1
fi

partition="${device}1"

echo "$device: wiping $(lsblk -dno SIZE,VENDOR,MODEL "$device" | tr -s ' ')"

# Then, zero out start of the block device

dd if=/dev/zero of="$device" bs=1M count=1 || exit 1

# Then, repartition. sfdisk ignores the device names in the script and uses
# the target given on the command line, so the /dev/sdc below is cosmetic.

sfdisk "$device" << EOF || exit 1
label: dos
label-id: 0x18eb9334
device: /dev/sdc
unit: sectors
sector-size: 512

/dev/sdc1 : start=          56, size=    15702048, type=b, bootable
EOF

# Finally, format

mkfs.vfat "$partition" || exit 1

echo "$device: done"

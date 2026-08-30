#!/bin/bash

# Usage: make_single_all_talks_usb.sh /dev/sdc
#
# Write the staged talks to one stick. Normally driven by
# make_all_talks_usbs.sh, one of these per stick, twenty at a time.

STAGED_DIR=/dev/shm/usb_gold

# Error unless running as root

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit 1
fi

if [[ -z $1 ]]; then
    echo "Usage: $(basename "$0") /dev/sdc"
    exit 1
fi

device=$1
partition="${device}1"
mountpoint="/usbs${partition}"

# make_all_talks_usbs.sh stages the talks in RAM before fanning out. Say so
# plainly if that has not happened: as a bare rsync error it is easy to lose
# among nineteen other sticks' output.

if [[ ! -d $STAGED_DIR ]]; then
    echo "$device: $STAGED_DIR is missing - run make_all_talks_usbs.sh rather than this script on its own"
    exit 1
fi

mkdir -p "$mountpoint"
sleep 0.5

if ! mount -o quiet,utf8 -t vfat "$partition" "$mountpoint"; then
    echo "$device: mount failed - is it partitioned? has something else mounted it?"
    exit 1
fi

# Past here the stick is mounted, so every failure has to unmount before it
# gives up. A stick left mounted gets pulled out of the hub still mounted.

if ! rsync --size-only --delete -a "$STAGED_DIR/" "$mountpoint"; then
    echo "$device: copy failed"
    umount "$mountpoint"
    exit 1
fi

if ! umount "$mountpoint"; then
    echo "$device: unmount failed - do not unplug it yet"
    exit 1
fi

if ! fatlabel "$partition" "GREENBELT"; then
    echo "$device: copied, but labelling failed"
    exit 1
fi

echo "$device: done"

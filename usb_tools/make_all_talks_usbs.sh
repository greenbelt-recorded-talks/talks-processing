#!/bin/bash

# Write the finished talks to every connected USB stick.
#
#   make_all_talks_usbs.sh             the final run. Refuses unless the gold
#                                      dir looks complete.
#   make_all_talks_usbs.sh --partial   an early run against a gold dir that is
#                                      knowingly incomplete.
#
# The two differ in that one guard and nothing else. Preloading sticks
# mid-festival is worth doing because make_single_all_talks_usb.sh rsyncs
# --size-only, so the final run only copies the talks that landed since.
#
# This used to be two scripts, and preload_usbs.sh went unnoticed for a week
# after the talks moved to a RAM staging dir that only this one created.

GOLD_DIR=/storage/usb_gold
STAGED_DIR=/dev/shm/usb_gold
MINIMUM_GOLD_FILES=50

usage() {
    sed -n '3,13p' "$0" | cut -c 3-
}

partial=false

while (( $# )); do
    case "$1" in
        --partial) partial=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1"; echo; usage; exit 1 ;;
    esac
    shift
done

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit 1
fi

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Then, check the gold dir is there and holds what we expect

if [[ ! -d $GOLD_DIR ]]; then
    echo "USB gold dir $GOLD_DIR is missing - run make_usb_gold.sh first"
    exit 1
fi

gold_files=$(ls "$GOLD_DIR" | wc -l)

# An empty gold dir is fatal even with --partial. The copy onto each stick is
# rsync --delete, so an empty source does not mean "copy nothing", it means
# "erase every stick".

if (( gold_files == 0 )); then
    echo "USB gold dir $GOLD_DIR is empty - run make_usb_gold.sh first"
    echo "(copying from it would wipe the sticks rather than fill them)"
    exit 1
fi

if [[ $partial == false ]] && (( gold_files < MINIMUM_GOLD_FILES )); then
    echo "USB gold dir holds $gold_files talks, fewer than $MINIMUM_GOLD_FILES."
    echo "If the rest are still converting, either wait, or use --partial to"
    echo "preload the sticks with what is ready so far."
    exit 1
fi

# If any USBs are mounted, error out - that's not right

echo -n "There are "
"$USB_TOOLS_DIR/count_connected_usbs.sh"
echo " USB drives connected, and $gold_files talks to write to each."
if [[ $partial == true ]]; then
    echo "This is a --partial run, so the gold dir is not expected to be complete."
fi
echo "Press any key to continue, or Ctrl+C to quit"

read

# Copy usb_gold to RAM. /storage is on a spinning disk, and the fan-out below
# would otherwise have twenty rsyncs reading from it at once.
#
# Directory to directory with --delete, not "$GOLD_DIR"/* - the glob copies
# files rather than a tree, and --delete is quietly ignored when the source is
# a list of files. Without it a talk dropped from the gold dir stays in the RAM
# copy, and the fan-out below faithfully mirrors the RAM copy onto every stick.

mkdir -p "$STAGED_DIR"
rsync -a --delete "$GOLD_DIR/" "$STAGED_DIR/" || exit 1

echo "Starting work"

"$USB_TOOLS_DIR/list_usb_disks.sh" | xargs -P20 -I {} "$USB_TOOLS_DIR/make_single_all_talks_usb.sh" {}

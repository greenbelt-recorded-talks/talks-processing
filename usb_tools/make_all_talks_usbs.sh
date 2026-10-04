#!/bin/bash

# Write the finished talks to every connected USB stick.
#
#   make_all_talks_usbs.sh             the final run. Refuses unless the gold
#                                      dir looks complete.
#   make_all_talks_usbs.sh --partial   an early run against a gold dir that is
#                                      knowingly incomplete.
#
# The two differ in the completeness guards and nothing else: a final run wants
# a plausible number of talks and the all-talks index alongside them, and a
# --partial run knows it has neither yet. Preloading sticks mid-festival is
# worth doing because make_single_all_talks_usb.sh rsyncs --size-only, so the
# final run only copies the talks that landed since.
#
# This used to be two scripts, and preload_usbs.sh went unnoticed for a week
# after the talks moved to a RAM staging dir that only this one created.
#
# Every stick is read back after it is written, and the run ends with a count
# of how many passed against how many were connected. Before GB26 it ended with
# xargs exiting and nothing else: twenty children interleaved their output, one
# "copy failed" line among sixty scrolled past, and the run looked exactly like
# a clean one. Two sticks carrying the 2025 talks went out to a customer.
#
# The outcome of every stick, by serial number, goes to $USB_LOG_DIR. Serial
# numbers because that is the only durable name a stick has - /dev/sdc is
# whatever was in the port at the time.

GOLD_DIR=/storage/usb_gold
STAGED_DIR=/dev/shm/usb_gold
MINIMUM_GOLD_TALKS=50

usage() {
    sed -n '3,14p' "$0" | cut -c 3-
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
# shellcheck source=stick_log.sh
source "$USB_TOOLS_DIR/stick_log.sh"

# Then, check the gold dir is there and holds what we expect

if [[ ! -d $GOLD_DIR ]]; then
    echo "USB gold dir $GOLD_DIR is missing - run make_usb_gold.sh first"
    exit 1
fi

# Count the talks, not the files. The gold dir also holds the all-talks index
# PDF, and counting it as a talk would let a run through the minimum below one
# talk short.

shopt -s nullglob
gold_talks=("$GOLD_DIR"/*.mp3)
shopt -u nullglob

# A gold dir with no talks in it is fatal even with --partial. The copy onto
# each stick is rsync --delete, so a source holding nothing but the index does
# not mean "copy nothing", it means "erase every stick".

if (( ${#gold_talks[@]} == 0 )); then
    echo "USB gold dir $GOLD_DIR holds no talks - run make_usb_gold.sh first"
    echo "(copying from it would wipe the sticks rather than fill them)"
    exit 1
fi

if [[ $partial == false ]] && (( ${#gold_talks[@]} < MINIMUM_GOLD_TALKS )); then
    echo "USB gold dir holds ${#gold_talks[@]} talks, fewer than $MINIMUM_GOLD_TALKS."
    echo "If the rest are still converting, either wait, or use --partial to"
    echo "preload the sticks with what is ready so far."
    exit 1
fi

# The index is named for its festival, and so are the talks, so take the year
# from the talks rather than from the clock or a flag - that way last year's
# index sitting beside this year's talks is caught rather than accepted.
# make_usb_gold.sh keeps the gold dir to one festival, so the first talk speaks
# for all of them.

if [[ ${gold_talks[0]##*/} =~ ^GB([0-9]{2})_ ]]; then
    year=${BASH_REMATCH[1]}
else
    year=$(date +%y)
fi

index_pdf="GB$year-AllTalksIndex.pdf"

# Missing on a final run is a refusal, not a warning: nothing downstream
# notices, and the sticks are handed over with no talk list on them. It comes
# from the setup page, so this script cannot supply it.

if [[ -f $GOLD_DIR/$index_pdf ]]; then
    echo "All-talks index $index_pdf is in the gold dir."
elif [[ $partial == true ]]; then
    echo "All-talks index $index_pdf is missing - fine for a --partial run, upload it on the setup page before the final one."
else
    echo "All-talks index $index_pdf is missing from $GOLD_DIR."
    echo "Upload it on the setup page and re-run make_usb_gold.sh, or use"
    echo "--partial to write sticks without a talk list on them."
    exit 1
fi

# Take the device list once and use that same list for both the count below
# and the fan-out at the bottom. Calling list_usb_disks.sh twice means the
# number on screen is from a different moment than the sticks actually written,
# and the difference is invisible.

mapfile -t devices < <("$USB_TOOLS_DIR/list_usb_disks.sh")

if (( ${#devices[@]} == 0 )); then
    echo "No USB drives found - nothing to do"
    exit 1
fi

echo "There are ${#devices[@]} USB drives connected, and ${#gold_talks[@]} talks to write to each."
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

# Every child appends its outcome to this file, and the summary below is read
# back out of it. The children's exit codes are not enough on their own: xargs
# collapses twenty of them into one status, and twenty children interleaving
# their output means a single "copy failed" line scrolls past unread. That is
# how the 2026 run finished with nobody aware that anything had gone wrong.

export USB_RUN_LOG="$USB_LOG_DIR/run-$(date +%Y%m%d-%H%M%S).csv"
export USB_FESTIVAL_YEAR="$year"

# Fail here rather than at the end. The summary below is read back out of the
# run log, so a log that cannot be written turns every stick into "reported
# nothing at all" and a perfectly good run into an alarming one.

if ! mkdir -p "$USB_LOG_DIR"; then
    echo "Cannot create $USB_LOG_DIR - there would be no record of which stick got what."
    exit 1
fi

echo "Starting work - logging to $USB_RUN_LOG"

printf '%s\n' "${devices[@]}" \
    | xargs -P20 -I {} "$USB_TOOLS_DIR/make_single_all_talks_usb.sh" {}

# Summary. Anything that did not write a line is counted too: a child killed
# partway through leaves no outcome, and silence must not read as success.

echo
echo "=============================================================="

summarise_run "$USB_RUN_LOG" "${#devices[@]}"
run_ok=$?

echo "$RUN_WRITTEN of ${#devices[@]} sticks written and verified."

if (( ${#RUN_FAILURES[@]} )); then
    echo
    echo "FAILED - these sticks must not go out:"
    printf '    %s\n' "${RUN_FAILURES[@]}"
fi

if (( RUN_UNACCOUNTED != 0 )); then
    echo
    if (( RUN_UNACCOUNTED > 0 )); then
        echo "$RUN_UNACCOUNTED stick(s) reported nothing at all - treat them as failed."
    else
        echo "The log holds more outcomes than there were sticks - read $USB_RUN_LOG."
    fi
fi

echo
echo "Serial numbers of every stick are in $USB_REGISTRY"
echo "Check what is on a stick with: $USB_TOOLS_DIR/check_usbs.sh"

exit $run_ok

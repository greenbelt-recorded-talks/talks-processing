#!/bin/bash

# Usage: make_single_all_talks_usb.sh /dev/sdc
#
# Write the staged talks to one stick, then read it back and check they are
# there. Normally driven by make_all_talks_usbs.sh, one of these per stick,
# twenty at a time.
#
# The verification is the point of this script, not a flourish. In 2026 a
# customer was sent two sticks carrying the 2025 talks, and nothing anywhere in
# this toolchain would have noticed: the copy is rsync --delete, so a stick
# that is written is correct by construction, and a stick that is *not* written
# keeps last year's set and last year's GREENBELT label and looks identical to
# a good one. The only defence is to open the stick afterwards and look.
#
# So the sequence is deliberately mount, copy, unmount, mount again, check.
# Unmounting in the middle is what makes it a read-back: checking before it
# would read the page cache and agree with itself.

set -u

STAGED_DIR=/dev/shm/usb_gold

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=stick_log.sh
source "$USB_TOOLS_DIR/stick_log.sh"
# shellcheck source=stick_verify.sh
source "$USB_TOOLS_DIR/stick_verify.sh"

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit 1
fi

if [[ -z ${1:-} ]]; then
    echo "Usage: $(basename "$0") /dev/sdc"
    exit 1
fi

device=$1
partition="${device}1"
mountpoint="/usbs${partition}"

serial=$(stick_serial "$device")
label="$device ($serial)"

# make_all_talks_usbs.sh stages the talks in RAM before fanning out. Say so
# plainly if that has not happened: as a bare rsync error it is easy to lose
# among nineteen other sticks' output.

if [[ ! -d $STAGED_DIR ]]; then
    echo "$label: $STAGED_DIR is missing - run make_all_talks_usbs.sh rather than this script on its own"
    log_stick "$device" staging-missing 0 "$STAGED_DIR is missing"
    exit 1
fi

# What the stick should end up holding, by name and size. Read once, here,
# into STAGED, which verify_stick compares against later.

staged_files "$STAGED_DIR"

if (( ${#STAGED[@]} == 0 )); then
    echo "$label: $STAGED_DIR holds no files - refusing to erase the stick"
    log_stick "$device" staging-empty 0 "staging dir empty"
    exit 1
fi

# The festival year the registry records this stick as carrying, taken from the
# files about to go on it rather than from the clock.

if [[ -z ${USB_FESTIVAL_YEAR:-} ]]; then
    for name in "${!STAGED[@]}"; do
        if [[ $name =~ ^GB([0-9]{2})_ ]]; then
            USB_FESTIVAL_YEAR=${BASH_REMATCH[1]}
            break
        fi
    done
fi

# Past here the stick may be mounted, so every failure has to unmount before it
# gives up. A stick left mounted gets pulled out of the hub still mounted.

give_up() {
    local result=$1 message=$2
    umount "$mountpoint" 2>/dev/null
    echo "$label: $message"
    log_stick "$device" "$result" 0 "$message"
    exit 1
}

mkdir -p "$mountpoint"
sleep 0.5

if ! mount -o quiet,utf8 -t vfat "$partition" "$mountpoint"; then
    echo "$label: mount failed - is it partitioned? has something else mounted it?"
    log_stick "$device" mount-failed 0 "mount of $partition failed"
    exit 1
fi

if ! rsync --size-only --delete -a "$STAGED_DIR/" "$mountpoint"; then
    give_up copy-failed "copy failed"
fi

# Unmount to flush, then mount again read-only to read back what actually
# landed. Read-only because nothing from here on should be writing to it.

if ! umount "$mountpoint"; then
    give_up unmount-failed "unmount after copy failed - do not unplug it yet"
fi

if ! mount -o ro,quiet,utf8 -t vfat "$partition" "$mountpoint"; then
    echo "$label: could not mount for verification"
    log_stick "$device" verify-failed 0 "re-mount for verification failed"
    exit 1
fi

verify_stick "$mountpoint"
verdict=$?

if ! umount "$mountpoint"; then
    give_up unmount-failed "unmount after verification failed - do not unplug it yet"
fi

# Name a few examples of each kind rather than all of them - twenty sticks
# reporting sixty filenames each buries the summary that follows them.

name_some() {
    local heading=$1; shift
    (( $# )) || return 0
    printf '    %s: %s\n' "$heading" "$1"
    (( $# > 1 )) && printf '    %s: ... and %d more\n' "$heading" "$(( $# - 1 ))"
    return 0
}

if (( verdict != 0 )); then
    detail="${#VERIFY_MISSING[@]} missing, ${#VERIFY_WRONG_SIZE[@]} wrong size, ${#VERIFY_UNEXPECTED[@]} unexpected"
    echo "$label: VERIFICATION FAILED - $detail"
    name_some missing "${VERIFY_MISSING[@]}"
    name_some "wrong size" "${VERIFY_WRONG_SIZE[@]}"
    name_some unexpected "${VERIFY_UNEXPECTED[@]}"
    log_stick "$device" verify-failed "${#STAGED[@]}" "$detail"
    exit 1
fi

# The label goes on last, and only once the stick has been read back. An
# unlabelled stick is then a visible sign that something went wrong with this
# one, which a stick carrying a previous year's GREENBELT label never is.

if ! fatlabel "$partition" "GREENBELT"; then
    echo "$label: copied and verified, but labelling failed"
    log_stick "$device" label-failed "${#STAGED[@]}" "fatlabel failed"
    exit 1
fi

echo "$label: done, ${#STAGED[@]} files verified"
log_stick "$device" ok "${#STAGED[@]}" ""

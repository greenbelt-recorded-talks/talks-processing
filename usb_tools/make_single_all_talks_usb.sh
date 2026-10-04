#!/bin/bash

# Usage: make_single_all_talks_usb.sh /dev/sdc
#
# Write the staged talks to one stick and read them back. Normally driven by
# make_all_talks_usbs.sh, twenty of these at a time.
#
# Mount, copy, unmount, mount again, check. The unmount in the middle is what
# makes it a read-back - checking before it reads the page cache. See the USB
# Sticks section of CLAUDE.md for why it is here.

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
# plainly - as a bare rsync error it is easy to lose among nineteen others.

if [[ ! -d $STAGED_DIR ]]; then
    echo "$label: $STAGED_DIR is missing - run make_all_talks_usbs.sh rather than this script on its own"
    log_stick "$device" staging-missing 0 "$STAGED_DIR is missing"
    exit 1
fi

# What the stick should end up holding, read once into STAGED.

staged_files "$STAGED_DIR"

if (( ${#STAGED[@]} == 0 )); then
    echo "$label: $STAGED_DIR holds no files - refusing to erase the stick"
    log_stick "$device" staging-empty 0 "staging dir empty"
    exit 1
fi

# The year comes from the files about to go on the stick, not the clock.

if [[ -z ${USB_FESTIVAL_YEAR:-} ]]; then
    for name in "${!STAGED[@]}"; do
        if [[ $name =~ ^GB([0-9]{2})_ ]]; then
            USB_FESTIVAL_YEAR=${BASH_REMATCH[1]}
            break
        fi
    done
fi

# The label carries that year, so an unlabellable stick is not worth writing.

if ! fs_label=$(volume_label "${USB_FESTIVAL_YEAR:-}"); then
    echo "$label: cannot tell which festival $STAGED_DIR holds - not writing an unlabellable stick"
    log_stick "$device" year-unknown 0 "no GB<yy>_ talks in the staging dir"
    exit 1
fi

# Past here the stick may be mounted, so every failure unmounts before giving
# up - otherwise it gets pulled out of the hub still mounted.

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

# Unmount to flush, then mount read-only to read back what landed.

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

# One example of each, not all of them - twenty sticks naming sixty files each
# buries the summary.

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

# Label last, and only on a stick that passed, so the old label means failure.

if ! fatlabel "$partition" "$fs_label"; then
    echo "$label: copied and verified, but labelling failed"
    log_stick "$device" label-failed "${#STAGED[@]}" "fatlabel $fs_label failed"
    exit 1
fi

echo "$label: done, ${#STAGED[@]} files verified, labelled $fs_label"
log_stick "$device" ok "${#STAGED[@]}" ""

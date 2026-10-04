#!/bin/bash

# Report what is actually on every connected USB stick. Writes nothing to them.
#
#   check_usbs.sh              check against this calendar year's festival
#   check_usbs.sh --year 25    check against a particular festival
#
# This exists because of GB26, where two sticks carrying the 2025 talks went
# out to a customer. Nothing about a stick's outside says which festival is on
# it: both years' sticks are labelled GREENBELT, and the 2025 mail-order batch
# is a different model and capacity from the on-site one, so even "ours look
# like this" does not hold. The only way to know is to open it and look, which
# is what this does.
#
# Use it on stock before a run, and on anything that comes back afterwards.
# Every stick checked is recorded in the registry by serial number, so a stick
# that turns up again later has a history.
#
# Mounts are read-only throughout. A stick that is already wrong should not be
# modified by the act of finding out.

set -u

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=stick_log.sh
source "$USB_TOOLS_DIR/stick_log.sh"

year=$(date +%y)

usage() { sed -n '3,6p' "$0" | cut -c 3-; }

while (( $# )); do
    case "$1" in
        --year) year=$2; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1"; echo; usage; exit 1 ;;
    esac
    shift
done

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit 1
fi

mapfile -t devices < <("$USB_TOOLS_DIR/list_usb_disks.sh")

if (( ${#devices[@]} == 0 )); then
    echo "No USB drives found - nothing to check"
    exit 1
fi

export USB_FESTIVAL_YEAR="$year"

echo "Checking ${#devices[@]} stick(s) against GB$year."
echo

ok=0
stale=0
blank=0
unreadable=0

for device in "${devices[@]}"; do
    partition="${device}1"
    mountpoint="/usbs${partition}"

    serial=$(stick_serial "$device")
    model=$(stick_model "$device")
    size=$(lsblk -dno SIZE "$device" 2>/dev/null | tr -d ' ')
    fslabel=$(lsblk -no LABEL "$partition" 2>/dev/null | head -1 | tr -d ' ')

    printf '%s  %s  %s  %s  label=%s\n' \
        "$device" "$serial" "${size:-?}" "$model" "${fslabel:-<none>}"

    mkdir -p "$mountpoint"

    if ! mount -o ro,quiet,utf8 -t vfat "$partition" "$mountpoint" 2>/dev/null; then
        echo "    UNREADABLE - no mountable filesystem on $partition"
        echo
        (( unreadable++ ))
        log_stick "$device" audit-unreadable 0 "no mountable filesystem"
        continue
    fi

    # Count the talks by the festival their filenames claim, and keep anything
    # that is not a talk separately rather than ignoring it.

    declare -A talks=()
    indexes=''
    other=0

    shopt -s nullglob dotglob
    for path in "$mountpoint"/*; do
        name=${path##*/}
        if [[ $name =~ ^GB([0-9]{2})_.*\.mp3$ ]]; then
            (( talks[${BASH_REMATCH[1]}]++ ))
        elif [[ $name =~ ^GB([0-9]{2})-AllTalksIndex\.pdf$ ]]; then
            indexes+=" GB${BASH_REMATCH[1]}"
        else
            (( other++ ))
        fi
    done
    shopt -u nullglob dotglob

    umount "$mountpoint" 2>/dev/null

    summary=''
    for found in "${!talks[@]}"; do
        summary+=" GB$found:${talks[$found]}"
    done
    summary=${summary# }

    if (( ${#talks[@]} == 0 )); then
        echo "    BLANK - no talks on it${other:+ ($other other file(s))}"
        (( blank++ ))
        log_stick "$device" audit-blank 0 "no talks"
    elif [[ ${#talks[@]} -eq 1 && -v talks[$year] ]]; then
        echo "    OK - ${talks[$year]} GB$year talks,${indexes:- no index}"
        (( ok++ ))
        log_stick "$device" audit-ok "${talks[$year]}" "$summary"
    else
        echo "    WRONG FESTIVAL - holds $summary,${indexes:- no index}"
        echo "    Do not send this out. Re-run make_all_talks_usbs.sh with it connected."
        (( stale++ ))
        log_stick "$device" audit-stale 0 "$summary"
    fi

    unset talks
    echo
done

echo "=============================================================="
echo "GB$year and correct: $ok    wrong festival: $stale    blank: $blank    unreadable: $unreadable"
echo
echo "Recorded by serial number in $USB_REGISTRY"

if (( stale || unreadable )); then
    exit 1
fi

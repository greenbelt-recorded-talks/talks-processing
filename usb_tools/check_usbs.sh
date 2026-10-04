#!/bin/bash

# Report what is actually on every connected USB stick. Writes nothing to them.
#
#   check_usbs.sh              check against this calendar year's festival
#   check_usbs.sh --year 25    check against a particular festival
#
# Goes on the contents, and says so when the label disagrees. Sticks carry the
# festival year in their label now, but only from the first run that writes
# one, and a label is a claim rather than a fact. Nor does the model help: the
# 2025 mail-order batch is a different make and capacity from the on-site one.
#
# Run it on stock before a run and on anything that comes back.
#
# Every stick checked goes into the registry by serial, so one that turns up
# again has a history. Mounts are read-only throughout.

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

if ! expected_label=$(volume_label "$year"); then
    echo "--year wants a two-digit festival year, e.g. --year 25"
    exit 1
fi

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

echo "Checking ${#devices[@]} stick(s) against GB$year, expecting label $expected_label."
echo

ok=0
stale=0
blank=0
unreadable=0
mislabelled=0

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

    # Count talks by the festival their filenames claim; keep non-talks apart
    # rather than ignoring them.

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

        # Safe to send, but the label is what somebody sorting a box goes on.
        # Anything written before the label carried a year says GREENBELT.

        if [[ $fslabel != "$expected_label" ]]; then
            echo "    note: labelled '${fslabel:-<none>}', should be '$expected_label'"
            echo "          contents are right; re-run make_all_talks_usbs.sh to relabel"
            (( mislabelled++ ))
        fi
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

if (( mislabelled )); then
    echo "$mislabelled of the correct ones carry the wrong label."
fi
echo
echo "Recorded by serial number in $USB_REGISTRY"

if (( stale || unreadable )); then
    exit 1
fi

#!/bin/bash

# Stick identification and run logging. Sourced by the other scripts here, not
# run on its own.
#
# Sticks are tracked by serial number, because that is the only thing about one
# that survives being unplugged. /dev/sdc is just whatever was in the port at
# the time: on 30 August 2026 that letter meant one stick before 19:28 and a
# different one after, which is exactly the sort of thing that makes "which
# stick got what?" unanswerable a month later.
#
# Two files get written, both CSV, both under USB_LOG_DIR:
#
#   run-<stamp>.csv  one run, one line per stick. make_all_talks_usbs.sh reads
#                    its own children's lines back out of this, because xargs
#                    discards their exit codes and twenty of them interleave
#                    their output anyway.
#
#   registry.csv     every stick ever seen, appended to and never rewritten.
#                    This is the file that answers "what was on the one with
#                    this serial?" when a stick comes back in the post.
#
# Both are written under flock: twenty children append to the same file at
# once, and a line interleaved halfway through another is worse than no line.

USB_LOG_DIR="${USB_LOG_DIR:-/storage/usb_logs}"
USB_REGISTRY="${USB_REGISTRY:-$USB_LOG_DIR/registry.csv}"

# Field order is not cosmetic. make_all_talks_usbs.sh reads its summary back
# out of the run log with a plain `IFS=, read`, so every column before `result`
# is one that cannot contain a comma - a timestamp, a device path, a serial, an
# integer. The free-text ones, model and detail, come after it, where a comma
# inside a quoted field can only run into the part already read.

RUN_LOG_HEADER='time,device,serial,size_bytes,result,files,model,detail'
REGISTRY_HEADER='time,serial,size_bytes,festival,result,model,detail'

# lsblk prints nothing at all for a device it cannot read, so every one of
# these falls back rather than returning an empty field that looks like data.

stick_serial() {
    local serial
    serial=$(lsblk -dno SERIAL "$1" 2>/dev/null | tr -d ' ')
    echo "${serial:-unknown}"
}

stick_model() {
    local model
    model=$(lsblk -dno VENDOR,MODEL "$1" 2>/dev/null | tr -s ' ' | sed 's/ *$//')
    echo "${model:-unknown}"
}

stick_size() {
    local size
    size=$(lsblk -dnbo SIZE "$1" 2>/dev/null)
    echo "${size:-0}"
}

# Minimal RFC 4180 quoting. Model strings hold spaces, and the detail field
# holds whatever went wrong, which is the one field most likely to contain a
# comma just when somebody is trying to read the log.

csv_row() {
    local out='' field
    for field in "$@"; do
        [[ -n $out ]] && out+=','
        if [[ $field == *[,\"$'\n']* ]]; then
            out+="\"${field//\"/\"\"}\""
        else
            out+=$field
        fi
    done
    echo "$out"
}

# Append one row, creating the file with its header if it is not there yet.
# The lock is on the file itself, so two different logs never wait on each
# other.

log_append() {
    local file=$1 header=$2; shift 2
    local dir=${file%/*}

    mkdir -p "$dir" 2>/dev/null || return 1

    {
        flock 9 || return 1
        [[ -s $file ]] || echo "$header" >&9
        csv_row "$@" >&9
    } 9>>"$file"
}

# One stick, one outcome. Called by make_single_all_talks_usb.sh as it
# finishes, and by check_usbs.sh when auditing stock.
#
# USB_RUN_LOG is set by make_all_talks_usbs.sh so that every child of one run
# writes to the same file; a stick done on its own just skips that half.

log_stick() {
    local device=$1 result=$2 files=$3 detail=$4
    local now serial model size
    now=$(date --iso-8601=seconds)
    serial=$(stick_serial "$device")
    model=$(stick_model "$device")
    size=$(stick_size "$device")

    if [[ -n ${USB_RUN_LOG:-} ]]; then
        log_append "$USB_RUN_LOG" "$RUN_LOG_HEADER" \
            "$now" "$device" "$serial" "$size" "$result" "$files" "$model" "$detail"
    fi

    log_append "$USB_REGISTRY" "$REGISTRY_HEADER" \
        "$now" "$serial" "$size" "GB${USB_FESTIVAL_YEAR:-??}" "$result" "$model" "$detail"
}

# Read a run log back and work out what happened, filling RUN_WRITTEN,
# RUN_FAILURES and RUN_UNACCOUNTED. Returns non-zero unless every stick that
# was connected came back ok.
#
# RUN_UNACCOUNTED is the sticks that logged nothing at all. A child killed
# partway through - or one that never started - leaves no line behind, and
# saying nothing must not be mistaken for saying it went fine.

summarise_run() {
    local file=$1 expected=$2
    local _time device serial _size result _rest

    RUN_WRITTEN=0
    RUN_FAILURES=()

    if [[ -f $file ]]; then
        while IFS=, read -r _time device serial _size result _rest; do
            [[ $device == device ]] && continue
            if [[ $result == ok ]]; then
                (( RUN_WRITTEN++ ))
            else
                RUN_FAILURES+=("$device ($serial): $result")
            fi
        done < "$file"
    fi

    RUN_UNACCOUNTED=$(( expected - RUN_WRITTEN - ${#RUN_FAILURES[@]} ))

    (( ${#RUN_FAILURES[@]} == 0 && RUN_UNACCOUNTED == 0 ))
}

#!/bin/bash

# Stick identification and run logging. Sourced, not run.
#
# Sticks are keyed on serial number: /dev/sdc is only whatever was in the port
# at the time. Two CSVs under USB_LOG_DIR:
#
#   run-<stamp>.csv  one line per stick per run, read back by summarise_run
#   registry.csv     every stick ever seen, append-only
#
# Both under flock - twenty children append at once.

USB_LOG_DIR="${USB_LOG_DIR:-/storage/usb_logs}"
USB_REGISTRY="${USB_REGISTRY:-$USB_LOG_DIR/registry.csv}"

# summarise_run parses these with a plain `IFS=, read`, so every column before
# `result` has to be comma-free. The free-text ones come after it.

RUN_LOG_HEADER='time,device,serial,size_bytes,result,files,model,detail'
REGISTRY_HEADER='time,serial,size_bytes,festival,result,model,detail'

# lsblk prints nothing for a device it cannot read, hence the fallbacks - an
# empty field would look like data.

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

# The volume label for a festival. GREENBELT plus a two-digit year is exactly
# the eleven characters FAT allows. Refuses anything else rather than quietly
# writing a bare GREENBELT, which is what made GB25 and GB26 stock identical.

volume_label() {
    [[ $1 =~ ^[0-9]{2}$ ]] || return 1
    echo "GREENBELT$1"
}

# Minimal RFC 4180 quoting.

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

# Append one row, writing the header first if the file is new. The lock is on
# the file itself, so the two logs never wait on each other.

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

# One stick, one outcome. USB_RUN_LOG is set by make_all_talks_usbs.sh so every
# child of a run writes to the same file; a stick done on its own skips it.

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

# Fill RUN_WRITTEN, RUN_FAILURES and RUN_UNACCOUNTED from a run log. Non-zero
# unless every connected stick came back ok.
#
# RUN_UNACCOUNTED is sticks that logged nothing: a child killed partway through
# leaves no line, and silence is not success.

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

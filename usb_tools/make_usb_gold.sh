#!/bin/bash

# Build the set of talks that goes onto the USB sticks.
#
#   make_usb_gold.sh              build for this calendar year's festival
#   make_usb_gold.sh --year 25    build for a particular festival
#   make_usb_gold.sh --dry-run    report what would change, touch nothing
#
# This is deliberately NOT a mirror of the processed dir. convert_talks only
# ever converts a cleared talk, but clearance can be withdrawn afterwards and
# nothing removes the MP3 it already produced. So the processed dir is the
# archive of everything ever converted, and the gold dir is the authoritative
# "what we are allowed to hand out" set, rebuilt from the database each time.
# There is a real example on disk: GB26_048 was converted on 28 August and
# un-cleared after that.
#
# It also drops cancelled talks and talks from other festivals, neither of
# which the conversion step checks.
#
# Everything excluded is named on the way past, because a talk missing from
# the sticks because somebody unticked a box is worth seeing rather than
# silently obeying.

set -u

PROCESSED_DIR="${PROCESSED_DIR:-/storage/processed}"
GOLD_DIR="${USB_GOLD_DIR:-/storage/usb_gold}"
DATABASE="${GBTALKS_DATABASE:-/home/gbtalks/talks-processing/instance/gbtalks.sqlite}"

# The default follows the calendar year, which is what config.py's
# default_gb_friday() does. If GB_FRIDAY has been pinned to a different year,
# pass --year. A wrong guess is loud rather than silent: every talk lands in
# the "other festivals" list below and the gold dir comes out empty.
year=$(date +%y)
dry_run=false

usage() { sed -n '3,7p' "$0" | cut -c 3-; }

while (( $# )); do
    case "$1" in
        --year) year=$2; shift ;;
        --dry-run) dry_run=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1"; echo; usage; exit 1 ;;
    esac
    shift
done

if [[ ! -f $DATABASE ]]; then
    echo "Database not found at $DATABASE"
    exit 1
fi

if [[ ! -d $PROCESSED_DIR ]]; then
    echo "Processed dir $PROCESSED_DIR is missing"
    exit 1
fi

$dry_run || mkdir -p "$GOLD_DIR" || exit 1

# Cancelled is checked as well as cleared, matching the products CSV export.
# coalesce() because a database from an older schema can have these null.

declare -A sellable=()
while IFS='|' read -r id title; do
    sellable[$id]=$title
done < <(sqlite3 -separator '|' "$DATABASE" \
    "select printf('%03d', id), title from talks
     where coalesce(is_cleared, 0) = 1 and coalesce(is_cancelled, 0) = 0;")

if (( ${#sellable[@]} == 0 )); then
    echo "No cleared, uncancelled talks in the database - refusing to empty the gold dir"
    exit 1
fi

# Classify what has been converted. Filenames are GB<yy>_<nnn>_<title>_<speaker>.mp3
# and can contain spaces, ampersands and full-width punctuation, so everything
# below goes through arrays rather than word splitting. No rsync filter rules
# either: a title containing [ or ] would be read as a pattern, and rsync's
# --delete-excluded would then empty the gold dir rather than skip one file.

wanted=()
not_sellable=()
other_festival=()
unrecognised=()

shopt -s nullglob
for path in "$PROCESSED_DIR"/*; do
    [[ -f $path ]] || continue
    name=${path##*/}
    if [[ $name =~ ^GB([0-9]{2})_([0-9]{3})_ ]]; then
        file_year=${BASH_REMATCH[1]}
        file_id=${BASH_REMATCH[2]}
    else
        unrecognised+=("$name")
        continue
    fi
    if [[ $file_year != "$year" ]]; then
        other_festival+=("$name")
    elif [[ -v sellable[$file_id] ]]; then
        wanted+=("$name")
    else
        not_sellable+=("$file_id  $name")
    fi
done

# Anything in gold that is not wanted goes, whatever put it there.

stale=()
for path in "$GOLD_DIR"/*; do
    [[ -f $path ]] || continue
    name=${path##*/}
    keep=false
    for w in "${wanted[@]}"; do
        [[ $w == "$name" ]] && { keep=true; break; }
    done
    $keep || stale+=("$name")
done
shopt -u nullglob

report() {
    local heading=$1; shift
    (( $# )) || return 0
    echo "$heading"
    printf '    %s\n' "$@"
}

echo "GB$year: ${#wanted[@]} talks for the sticks, out of ${#sellable[@]} cleared and uncancelled in the database."
report "Converted but NOT cleared, or cancelled - leaving these off:" "${not_sellable[@]}"
report "From another festival - leaving these off:" "${other_festival[@]}"
report "Not a processed talk filename - ignoring:" "${unrecognised[@]}"

# Bail out before reporting removals, so a run that refuses to act never
# announces deletions it is not going to make.

if (( ${#wanted[@]} == 0 )); then
    echo
    echo "Nothing to copy, so the gold dir has been left alone."
    echo "If that is a surprise, check --year: this run looked for GB$year."
    exit 1
fi

if $dry_run; then
    report "Would remove from the gold dir:" "${stale[@]}"
    echo
    echo "Dry run - nothing written."
    exit 0
fi

report "Removing from the gold dir:" "${stale[@]}"

for name in "${stale[@]}"; do
    rm -f -- "$GOLD_DIR/$name" || exit 1
done

# Explicit paths, so nothing here is interpreted as a pattern.
( cd "$PROCESSED_DIR" && rsync -a -- "${wanted[@]}" "$GOLD_DIR/" ) || exit 1

echo
echo "Gold dir $GOLD_DIR now holds $(ls -1 "$GOLD_DIR" | wc -l) talks."

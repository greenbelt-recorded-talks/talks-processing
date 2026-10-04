#!/bin/bash

# Comparing what is on a stick against what should be. Sourced, not run.
#
# Split out so it can be tested against two ordinary directories - see
# test_stick_verify.sh.
#
# Names and sizes, no checksums. Both failures worth catching show up in a
# directory listing, and hashing 3.3 GB back off twenty sticks would cost more
# than the write.

# Populate STAGED (filename -> size) from a directory's top level. Global,
# because bash cannot return a map.

staged_files() {
    local dir=$1 path
    unset STAGED
    declare -gA STAGED=()
    while IFS= read -r -d '' path; do
        STAGED["${path##*/}"]=$(stat -c %s "$path")
    done < <(find "$dir" -maxdepth 1 -type f -print0)
}

# Compare a mounted stick against STAGED. Non-zero if any of the three arrays
# comes back non-empty.
#
# VERIFY_UNEXPECTED matters most: missing and wrong-size files mean a copy that
# went wrong, unexpected ones mean a copy that never happened.

verify_stick() {
    local mountpoint=$1 name path

    VERIFY_MISSING=()
    VERIFY_WRONG_SIZE=()
    VERIFY_UNEXPECTED=()

    for name in "${!STAGED[@]}"; do
        if [[ ! -f $mountpoint/$name ]]; then
            VERIFY_MISSING+=("$name")
        elif (( $(stat -c %s "$mountpoint/$name") != STAGED[$name] )); then
            VERIFY_WRONG_SIZE+=("$name")
        fi
    done

    shopt -s nullglob dotglob
    for path in "$mountpoint"/*; do
        name=${path##*/}
        [[ -v STAGED[$name] ]] || VERIFY_UNEXPECTED+=("$name")
    done
    shopt -u nullglob dotglob

    (( ${#VERIFY_MISSING[@]} + ${#VERIFY_WRONG_SIZE[@]} + ${#VERIFY_UNEXPECTED[@]} == 0 ))
}

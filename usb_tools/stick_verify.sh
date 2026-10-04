#!/bin/bash

# Comparing what is on a stick against what should be. Sourced, not run.
#
# Separate from make_single_all_talks_usb.sh so it can be exercised against two
# ordinary directories, which is the only way to test it without twenty sticks
# and a hub: see test_stick_verify.sh beside it.
#
# Names and sizes only, deliberately - no checksums. The failures this is here
# to catch are a copy that did not happen and a file that should not be there,
# and both of those are visible in a directory listing. Hashing 3.3 GB back off
# twenty sticks over one USB bus would cost more than the write did, and would
# be the reason somebody stopped running it.

# Populate STAGED (filename -> size in bytes) from the top level of a
# directory. Global, because bash cannot return a map.

staged_files() {
    local dir=$1 path
    unset STAGED
    declare -gA STAGED=()
    while IFS= read -r -d '' path; do
        STAGED["${path##*/}"]=$(stat -c %s "$path")
    done < <(find "$dir" -maxdepth 1 -type f -print0)
}

# Compare a mounted stick against STAGED, filling three arrays and returning
# non-zero if any of them has anything in it.
#
# VERIFY_UNEXPECTED is the one that matters most. Missing and wrong-size files
# mean a copy that went wrong, which at least has a chance of being noticed;
# unexpected files mean a copy that never touched the stick at all, which is
# what put a previous festival's talks in the post.

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

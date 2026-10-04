#!/bin/bash

# Tests for stick_verify.sh. Run it directly:
#
#   usb_tools/test_stick_verify.sh
#
# Two ordinary directories stand in for the staging dir and a mounted stick,
# which is the whole reason the comparison lives in its own file. No root, no
# hardware, no USB hub.

set -u

TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=stick_verify.sh
source "$TOOLS/stick_verify.sh"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0

check() {
    if [[ $2 == "$3" ]]; then
        echo "  ok   $1"
    else
        echo "  FAIL $1 - got '$2', expected '$3'"
        (( fails++ ))
    fi
}

# A plausible gold set: this year's talks plus this year's index.
make_gold() {
    local dir=$1 year=$2 n
    mkdir -p "$dir"
    for n in 001 002 003; do
        printf 'talk %s' "$n" > "$dir/GB${year}_${n}_A Talk_A Speaker.mp3"
    done
    printf 'index' > "$dir/GB$year-AllTalksIndex.pdf"
}

staged="$TMP/staged"
make_gold "$staged" 26
staged_files "$staged"

echo "staged_files reads the set:"
check "four files" "${#STAGED[@]}" '4'

echo
echo "a stick that matches:"
stick="$TMP/good"
make_gold "$stick" 26
verify_stick "$stick" && result=pass || result=fail
check "passes"       "$result"                      'pass'
check "no missing"   "${#VERIFY_MISSING[@]}"        '0'
check "no unexpected" "${#VERIFY_UNEXPECTED[@]}"    '0'

echo
echo "a stick with one talk missing:"
stick="$TMP/short"
make_gold "$stick" 26
rm "$stick/GB26_002_A Talk_A Speaker.mp3"
verify_stick "$stick" && result=pass || result=fail
check "fails"      "$result"                 'fail'
check "one missing" "${#VERIFY_MISSING[@]}"  '1'

echo
echo "a stick with a truncated talk:"
stick="$TMP/truncated"
make_gold "$stick" 26
printf 'x' > "$stick/GB26_003_A Talk_A Speaker.mp3"
verify_stick "$stick" && result=pass || result=fail
check "fails"          "$result"                     'fail'
check "one wrong size" "${#VERIFY_WRONG_SIZE[@]}"    '1'

echo
echo "the GB26 regression - a stick still holding last year's talks:"
stick="$TMP/lastyear"
make_gold "$stick" 25
verify_stick "$stick" && result=pass || result=fail
check "fails"              "$result"                   'fail'
check "all four missing"   "${#VERIFY_MISSING[@]}"     '4'
check "all four unexpected" "${#VERIFY_UNEXPECTED[@]}" '4'

echo
echo "both years side by side - a copy that did not delete:"
stick="$TMP/mixed"
make_gold "$stick" 26
make_gold "$stick" 25
verify_stick "$stick" && result=pass || result=fail
check "fails"               "$result"                   'fail'
check "nothing missing"     "${#VERIFY_MISSING[@]}"     '0'
check "last year unexpected" "${#VERIFY_UNEXPECTED[@]}" '4'

echo
echo "an empty stick:"
stick="$TMP/empty"
mkdir -p "$stick"
verify_stick "$stick" && result=pass || result=fail
check "fails"            "$result"                'fail'
check "everything missing" "${#VERIFY_MISSING[@]}" '4'

echo
echo "filenames with the awkward characters real talks have:"
staged="$TMP/awkward-staged"
mkdir -p "$staged"
printf 'a' > "$staged/GB26_010_Palestine∕Israel： What Is Mine To Do？_Claire Thiel & others.mp3"
printf 'b' > "$staged/GB26_011_Bracket [sic], comma, quote\".mp3"
staged_files "$staged"
stick="$TMP/awkward-stick"
mkdir -p "$stick"
cp -a "$staged/." "$stick/"
verify_stick "$stick" && result=pass || result=fail
check "two files staged" "${#STAGED[@]}" '2'
check "passes"           "$result"       'pass'

echo
if (( fails )); then
    echo "$fails check(s) FAILED"
    exit 1
fi
echo "all checks passed"

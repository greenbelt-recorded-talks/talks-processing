#!/bin/bash

# Tests for stick_log.sh. Run it directly:
#
#   usb_tools/test_stick_log.sh
#
# No root and no hardware: the only thing here that touches a real device is
# log_stick, and only to read /dev/sda's serial out of lsblk.

set -u

TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export USB_LOG_DIR="$TMP/logs"
export USB_REGISTRY="$TMP/logs/registry.csv"
export USB_RUN_LOG="$TMP/logs/run-test.csv"
export USB_FESTIVAL_YEAR=26

# shellcheck source=stick_log.sh
source "$TOOLS/stick_log.sh"

fails=0

check() {
    if [[ $2 == "$3" ]]; then
        echo "  ok   $1"
    else
        echo "  FAIL $1 - got '$2', expected '$3'"
        (( fails++ ))
    fi
}

echo "csv_row quoting:"
check "plain"             "$(csv_row a b c)"          'a,b,c'
check "comma quoted"      "$(csv_row a 'b,x' c)"      'a,"b,x",c'
check "quote doubled"     "$(csv_row 'he said "hi"')" '"he said ""hi"""'
check "empty field kept"  "$(csv_row a '' c)"         'a,,c'

echo
echo "log_append writes the header once:"
log_append "$TMP/t.csv" 'h1,h2' one two
log_append "$TMP/t.csv" 'h1,h2' three four
check "header once" "$(head -1 "$TMP/t.csv")" 'h1,h2'
check "row count"   "$(wc -l < "$TMP/t.csv")" '3'

echo
echo "twenty concurrent appends do not interleave:"
for i in $(seq 1 20); do
    log_append "$TMP/c.csv" 'n' "row$i" &
done
wait
check "all rows present" "$(wc -l < "$TMP/c.csv")"                  '21'
check "no torn lines"    "$(grep -cvE '^(n|row[0-9]+)$' "$TMP/c.csv")" '0'

echo
echo "log_stick records a real device:"
log_stick /dev/sda ok 63 ""
check "registry header" "$(head -1 "$USB_REGISTRY")" \
    'time,serial,size_bytes,festival,result,model,detail'
check "festival" "$(tail -1 "$USB_REGISTRY" | cut -d, -f4)" 'GB26'
check "result"   "$(tail -1 "$USB_REGISTRY" | cut -d, -f5)" 'ok'

# A model containing a comma is the case the column order exists to survive:
# everything before `result` has to stay comma-free or summarise_run misreads
# the row.
cat > "$TMP/run.csv" <<'CSV'
time,device,serial,size_bytes,result,files,model,detail
2026-08-30T20:40:00+01:00,/dev/sdb,SCY0000000014481,15938355200,ok,63,USB Flash Disk 1100,
2026-08-30T20:39:04+01:00,/dev/sdc,SCY0000000012281,15938355200,verify-failed,63,"Acme, Inc Flash",61 unexpected
2026-08-30T20:40:31+01:00,/dev/sdd,SCY0000000016519,15938355200,ok,63,USB Flash Disk 1100,
CSV

echo
echo "summarise_run, three sticks connected and one bad:"
summarise_run "$TMP/run.csv" 3 && result=pass || result=fail
check "fails"           "$result"              'fail'
check "two written"     "$RUN_WRITTEN"         '2'
check "one failure"     "${#RUN_FAILURES[@]}"  '1'
check "named"           "${RUN_FAILURES[0]}"   '/dev/sdc (SCY0000000012281): verify-failed'
check "none unaccounted" "$RUN_UNACCOUNTED"    '0'

echo
echo "summarise_run, a stick that logged nothing at all:"
summarise_run "$TMP/run.csv" 5 && result=pass || result=fail
check "fails"           "$result"           'fail'
check "two unaccounted" "$RUN_UNACCOUNTED"  '2'

echo
echo "summarise_run, a clean run:"
cat > "$TMP/clean.csv" <<'CSV'
time,device,serial,size_bytes,result,files,model,detail
2026-08-30T20:40:00+01:00,/dev/sdb,SCY0000000014481,15938355200,ok,63,USB Flash Disk 1100,
CSV
summarise_run "$TMP/clean.csv" 1 && result=pass || result=fail
check "passes"       "$result"              'pass'
check "one written"  "$RUN_WRITTEN"         '1'
check "no failures"  "${#RUN_FAILURES[@]}"  '0'

echo
echo "summarise_run, no log written at all:"
summarise_run "$TMP/nothing-here.csv" 4 && result=pass || result=fail
check "fails"            "$result"          'fail'
check "all unaccounted"  "$RUN_UNACCOUNTED" '4'

echo
if (( fails )); then
    echo "$fails check(s) FAILED"
    exit 1
fi
echo "all checks passed"

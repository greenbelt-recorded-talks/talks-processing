#!/bin/bash

# Preload the sticks from a gold dir that is not complete yet, so the final
# run has less to copy.
#
# This is now just make_all_talks_usbs.sh --partial. The name is kept because
# it is the one in four years of shell history and on the run sheet.

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec "$USB_TOOLS_DIR/make_all_talks_usbs.sh" --partial "$@"

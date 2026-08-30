#!/bin/bash

# Count of writable USB sticks. Callers print this mid-sentence, so no newline.

USB_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$USB_TOOLS_DIR/list_usb_disks.sh" | wc -l | tr -d "\n"

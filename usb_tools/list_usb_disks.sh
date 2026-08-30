#!/bin/bash

# Print the block devices that are real, writable USB sticks - one path per
# line, no quotes. Every other script here builds its device list from this
# one, so there is a single place to get the selection right.
#
# A bare "tran == usb" test is not enough. The server's management controller
# permanently presents its virtual media slot as a USB disk:
#
#   /dev/sdb  tran=usb  type=disk  size=4M  ro=true  "KVM  Vir tual Media"
#
# It is not a stick, it is never absent, and under the old selector it was
# counted, partitioned and mounted along with the real drives. It is currently
# read-only, so fix_usb.sh could not actually damage it, but that flag only
# reflects what the controller is presenting - attach a writable image through
# the management console and the dd would land.
#
# The -b is load-bearing. Without it lsblk reports .size as a human string
# ("4M"), and jq orders every number before every string, so `.size > 2e9`
# would be true for every device and the filter would pass everything.
#
# The size floor excludes the virtual media, not a USB-attached hard disk -
# check what is plugged in before running anything destructive.

lsblk -JOb | jq -r '.blockdevices[]
    | select(.tran == "usb"
             and .type == "disk"
             and .ro != true
             and (.size // 0) > 2000000000)
    | .path'

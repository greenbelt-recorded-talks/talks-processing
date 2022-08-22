#!/bin/bash

lsblk -JO | jq '.blockdevices[] | select(.tran == "usb") | .path' | wc -l | tr -d "\n"

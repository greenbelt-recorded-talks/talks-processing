#!/bin/bash

# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi

talk=`printf %03d $1`

# Stop unless the CD files are actually ready

/home/gbtalks/talks-processing/cd_tools/checkfor.sh $talk || exit

echo "Burning CD for talk " $1
echo "Load 4 CDs then press Enter to continue"

read -n 1 -s

echo -e "0\n1\n2\n3" | xargs -P4 -n1 --verbose /home/gbtalks/talks-processing/cd_tools/makecd.sh $1


#!/bin/bash

# cron runs with a minimal PATH, and convert-talks shells out to ffmpeg
# (via pydub) and ffmpeg-normalize.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

date
cd /home/gbtalks/talks-processing
source .ve/bin/activate
flask convert-talks


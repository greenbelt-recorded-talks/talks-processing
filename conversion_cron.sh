#!/bin/bash

date
cd /home/gbtalks/talks-processing
source .ve/bin/activate
flask convert-talks


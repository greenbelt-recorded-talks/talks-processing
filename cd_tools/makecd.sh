echo "Writing Talk GB19-$1 to drive $2"
cd /storage/cds/gb19-$1
sudo wodim dev=/dev/sr$2 -dao -pad -audio -eject * 2>&1 | tee -a ~/cdlog.txt > /dev/null
echo "TALK GB19-$1 WRITTEN TO DRIVE $2"

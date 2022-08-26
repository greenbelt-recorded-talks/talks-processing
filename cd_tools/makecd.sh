# First, make sure that this is run as root so that we can mount things

if (( $EUID != 0 )); then
    echo "Please run as root"
    exit
fi


echo "Writing Talk GB22-$1 to drive $2"
cd /storage/cds/gb22-$1 || exit 1
sudo wodim dev=/dev/sr$2 -dao -pad -audio -eject * 2>&1 | tee -a ~/cdlog.txt > /dev/null
echo "TALK GB22-$1 WRITTEN TO DRIVE $2"

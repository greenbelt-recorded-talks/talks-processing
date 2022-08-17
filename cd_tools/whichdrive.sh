echo “Ejecting drive 0”
sudo wodim dev=/dev/sr0 -eject
read -n 1 -p "Ready for next drive?" mainmenuinput
echo “Ejecting drive 1”
sudo wodim dev=/dev/sr1 -eject
read -n 1 -p "Ready for next drive?" mainmenuinput
echo “Ejecting drive 2”
sudo wodim dev=/dev/sr2 -eject
read -n 1 -p "Ready for next drive?" mainmenuinput
echo “Ejecting drive 3”
sudo wodim dev=/dev/sr3 -eject
read -n 1 -p "Ready for next drive?" mainmenuinput

#!/bin/bash
#if xhost >& /dev/null ; then echo "Display exists"
sudo apt-get update
sudo apt-get -y upgrade 
sudo apt-get -y install byobu 
sudo apt-get -y install mpg123 
sudo apt-get -y install python3-pip 
sudo apt-get -y install mpv 
sudo apt-get -y install sqlite3 
sudo apt-get -y install libasound2-dev
python3 -m venv ~/ScenePlay
source ~/ScenePlay/bin/activate
pip3 install waitress --break-system-packages
pip3 install pathlib --break-system-packages
pip3 install flask --break-system-packages 
pip3 install gtts --break-system-packages
pip3 install pyalsaaudio --break-system-packages
pip3 install flask_sqlalchemy --break-system-packages 
pip3 install flask_migrate --break-system-packages
pip3 install gtts --break-system-packages
pip3 install psutil --break-system-packages
sudo pip3 install rpi_ws281x adafruit-circuitpython-neopixel --break-system-packages
sudo python3 -m pip install --force-reinstall adafruit-blinka --break-system-packages
deactivatede

chmod +x *.sh
chmod +x ~/ScenePlay/supportFiles/*.sh
chmod +x ~/ScenePlay/processMedia/*.sh

printf "Setup AutoStart\n"
cd ~/ScenePlay/supportFiles
source ~/ScenePlay/supportFiles/setupAutoStart.sh
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
sudo apt-get -y install socat
sudo apt-get -y install jq

is_raspberry_pi() {
    local CPUINFO_PATH="/proc/cpuinfo"
    if [[ ! -e "$CPUINFO_PATH" ]]; then
        return 1
    fi
    # The Raspberry Pi's architecture is armv6l or aarch64 (for newer models).
    # The uname -m command returns the architecture of the system.
    # The case statement checks if the result is either armv6l or aarch64.
    # If it is, the function returns 0 (true), meaning this is a Raspberry Pi.
    # If it is not, the function returns 1 (false), meaning this is not a Raspberry Pi.
    case "$(uname -m)" in
        armv6l|aarch64) return 0 ;;
        *) return 1 ;;
    esac
}

python3 -m venv ~/ScenePlay
source ~/ScenePlay/bin/activate
BREAK_SYSTEM_PACKAGES=""
if is_raspberry_pi; then
    BREAK_SYSTEM_PACKAGES="--break-system-packages"
fi
pip3 install waitress $BREAK_SYSTEM_PACKAGES
pip3 install pathlib $BREAK_SYSTEM_PACKAGES
pip3 install flask $BREAK_SYSTEM_PACKAGES 
pip3 install gtts $BREAK_SYSTEM_PACKAGES
pip3 install pyalsaaudio $BREAK_SYSTEM_PACKAGES
pip3 install flask_sqlalchemy $BREAK_SYSTEM_PACKAGES 
pip3 install flask_migrate $BREAK_SYSTEM_PACKAGES
pip3 install gtts $BREAK_SYSTEM_PACKAGES
pip3 install psutil $BREAK_SYSTEM_PACKAGES
pip3 install pulsectl $BREAK_SYSTEM_PACKAGES
sudo pip3 install rpi_ws281x adafruit-circuitpython-neopixel $BREAK_SYSTEM_PACKAGES
sudo python3 -m pip install --force-reinstall adafruit-blinka $BREAK_SYSTEM_PACKAGES
deactivated

chmod +x *.sh
chmod +x ~/ScenePlay/supportFiles/*.sh
chmod +x ~/ScenePlay/processMedia/*.sh

printf "Setup AutoStart\n"
cd ~/ScenePlay/supportFiles
source ~/ScenePlay/supportFiles/setupAutoStart.sh


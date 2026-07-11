#!/bin/bash
#if xhost >& /dev/null ; then echo "Display exists"
sudo apt-get update
sudo apt-get -y upgrade
sudo apt-get -y install mpg123
sudo apt-get -y install python3-pip
sudo apt-get -y install python3-venv
sudo apt-get -y install mpv
# ffmpeg: yt-dlp extract/merge + relay_audio_stream encoding (ws.py warns at
# boot if it's missing; mpv does NOT provide the ffmpeg CLI)
sudo apt-get -y install ffmpeg
sudo apt-get -y install sqlite3
sudo apt-get -y install socat
# pactl: relay_audio_stream's pulse backend (works against pipewire-pulse too;
# desktop images ship it, Lite/server images don't)
sudo apt-get -y install pulseaudio-utils

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
pip3 install -r ~/ScenePlay/requirements.txt $BREAK_SYSTEM_PACKAGES

# LED support: led_Run.py runs via `sudo python3` (system Python, not the
# venv), so its libraries must be installed with sudo — but only on a Pi.
if is_raspberry_pi; then
    sudo pip3 install rpi_ws281x adafruit-circuitpython-neopixel $BREAK_SYSTEM_PACKAGES
    sudo python3 -m pip install --force-reinstall adafruit-blinka $BREAK_SYSTEM_PACKAGES
fi
deactivate

chmod +x *.sh
chmod +x ~/ScenePlay/supportFiles/*.sh
chmod +x ~/ScenePlay/processMedia/*.sh

printf "Setup AutoStart\n"
cd ~/ScenePlay/supportFiles
source ~/ScenePlay/supportFiles/setupAutoStart.sh


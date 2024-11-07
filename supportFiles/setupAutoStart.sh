#!/bin/bash
mkdir ~/.config/autostart
_base=~
_dir=${_base}"/Desktop/ScenePlay.sh"
_exec="Exec=${_dir}"
#printf "$_exec\n"
cp sceneplay.desktop.txt ~/.config/autostart/sceneplay.desktop
cp ScenePlay.sh ~/Desktop
sed -i "s|Exec=/something.sh|$_exec|g" ~/.config/autostart/sceneplay.desktop


##watchdog service
mkdir -p ~/.config/systemd/user
cp ~/ScenePlay/supportFiles/sceneplay_watchdog.service ~/.config/systemd/user/sceneplay_watchdog.service
sed -i "s|userName|$USER|g" ~/.config/systemd/user/sceneplay_watchdog.service
sudo chown $USER:$USER ~/ScenePlay/supportFiles/sceneplay_watchdog_service.py
sudo chmod u+x ~/ScenePlay/supportFiles/sceneplay_watchdog_service.py
loginctl enable-linger $USER
systemctl --user daemon-reload
systemctl --user enable sceneplay_watchdog.service
systemctl --user start sceneplay_watchdog.service



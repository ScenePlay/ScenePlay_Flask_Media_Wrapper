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

#Set Background Image
pcmanfm --set-wallpaper ~/ScenePlay/static/image/ScenePlayWide.png
pcmanfm --wallpaper-mode=stretch
pcmanfm --wallpaper-mode=stretch

#set nginx
sudo apt-get -y install nginx
sudo systemctl stop nginx
sudo mv /etc/nginx/sites-available/default /etc/nginx/sites-available/default.bak
sudo rm /etc/nginx/sites-enabled/default
sudo cp ~/ScenePlay/supportFiles/default.txt /etc/nginx/sites-available/default
sudo ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
sudo systemctl start nginx



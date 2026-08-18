#!/bin/bash
# ScenePlay Linux uninstaller — reverses requirements.sh + setupAutoStart.sh.
# ScenePlay-only pieces (watchdog, autostart entries, venv) are removed
# outright; system-wide tools (apt packages, nginx) are SHARED with other
# software, so removing those is opt-in per prompt.

_dir=~/ScenePlay

read -r -p "Uninstall ScenePlay? This stops the app and removes its autostart/services. [y/N] " _ok
case "$_ok" in
    [yY]*) ;;
    *) echo "Aborted — nothing changed."; exit 0 ;;
esac

# Same detection as requirements.sh (redefined so this script runs standalone).
is_raspberry_pi() {
    [[ -e /proc/cpuinfo ]] || return 1
    case "$(uname -m)" in
        armv6l|aarch64) return 0 ;;
        *) return 1 ;;
    esac
}

# --- watchdog FIRST: it would restart the app within ~30 s of any kill ------
if [[ -e ~/.config/systemd/user/sceneplay_watchdog.service ]]; then
    systemctl --user stop sceneplay_watchdog.service 2>/dev/null
    systemctl --user disable sceneplay_watchdog.service 2>/dev/null
    rm -f ~/.config/systemd/user/sceneplay_watchdog.service
    systemctl --user daemon-reload 2>/dev/null
    # linger was enabled by the installer solely for this service
    loginctl disable-linger "$USER" 2>/dev/null
    echo "[ok] watchdog service removed"
fi

# --- stop the app + its players (same match patterns the app itself uses) ---
pkill -f "ScenePlay/ws.py"      2>/dev/null   # main server
pkill -f "ScenePlay/bin/python" 2>/dev/null   # venv children (yt-dlp etc.)
pkill -f "mpvsocket-"           2>/dev/null   # both mpv instances, never a user's own mpv
pkill mpg123                    2>/dev/null   # legacy/effects player
# [l]ed_Run: the bracket keeps the pattern from matching this sudo wrapper's
# own command line (classic pkill-under-sudo self-match).
sudo pkill -f "[l]ed_Run.py"    2>/dev/null   # LED worker runs under sudo
echo "[ok] ScenePlay processes stopped"

# --- autostart entries ------------------------------------------------------
rm -f ~/.config/autostart/sceneplay.desktop ~/Desktop/ScenePlay.sh
echo "[ok] autostart entries removed"

# --- nginx: put back the stock site config setupAutoStart.sh replaced -------
if [[ -e /etc/nginx/sites-available/default.bak ]]; then
    sudo mv /etc/nginx/sites-available/default.bak /etc/nginx/sites-available/default
    sudo ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
    sudo systemctl restart nginx 2>/dev/null
    echo "[ok] nginx site config restored from default.bak"
fi
read -r -p "Also REMOVE nginx itself? Only if nothing else uses this box as a web server. [y/N] " _ng
case "$_ng" in
    [yY]*) sudo systemctl stop nginx 2>/dev/null
           sudo apt-get -y purge nginx nginx-common
           sudo apt-get -y autoremove ;;
esac

# --- Pi LED libraries (requirements.sh put them in SYSTEM python) -----------
if is_raspberry_pi; then
    sudo pip3 uninstall -y rpi_ws281x adafruit-circuitpython-neopixel \
        adafruit-blinka --break-system-packages 2>/dev/null
    echo "[ok] LED libraries removed from system python"
fi

# --- apt tools: shared with other software, so opt-in -----------------------
# (python3-pip / python3-venv are left alone on purpose — too foundational.)
read -r -p "Remove apt packages the installer added (mpv ffmpeg mpg123 sqlite3 socat pulseaudio-utils python3-requests)? [y/N] " _apt
case "$_apt" in
    [yY]*) sudo apt-get -y remove mpv ffmpeg mpg123 sqlite3 socat pulseaudio-utils python3-requests
           sudo apt-get -y autoremove ;;
esac

# --- the folder itself: repo + venv + DATABASE + all downloaded media -------
if [[ -d "$_dir" ]]; then
    printf "\n%s holds the app AND your data: ScenePlay.db, downloaded music/video, backups.\n" "$_dir"
    read -r -p "Delete the whole folder? THIS CANNOT BE UNDONE. [y/N] " _del
    case "$_del" in
        [yY]*) cd ~
               rm -rf "$_dir"
               echo "[ok] $_dir deleted" ;;
        *)  # venv-only cleanup: requirements.sh overlaid the venv ON the repo
            # clone, so these names are venv artifacts, not project files.
            read -r -p "Remove just the Python virtualenv (keeps code, DB and media)? [y/N] " _venv
            case "$_venv" in
                [yY]*) rm -rf "$_dir/bin" "$_dir/lib" "$_dir/lib64" \
                              "$_dir/include" "$_dir/share" "$_dir/pyvenv.cfg"
                       echo "[ok] virtualenv removed — re-run requirements.sh to reinstall" ;;
            esac ;;
    esac
fi

echo
echo "Uninstall finished."

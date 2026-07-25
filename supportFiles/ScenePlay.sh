#!/bin/bash
_IP=$(hostname -I) || true
if [ ! "$_IP" ]; then
sleep 10
_IP=$(hostname -I) || true
fi
if [ "$_IP" ]; then
  printf "My IP address is %s\n" "$_IP"
fi
_port=":8086"
_IPP="$(echo ${_IP}${_port} | tr -d '[:space:]')"
_dir=~/ScenePlay

# Terminal emulators differ per distro: lxterminal is Raspberry Pi OS (PIXEL),
# Ubuntu ships gnome-terminal, etc. Probe in order and use whatever exists;
# x-terminal-emulator is Debian's catch-all alternative. With no graphical
# terminal at all (server install), run headless with output to a log.
if command -v lxterminal >/dev/null 2>&1; then
  lxterminal --working-directory=$_dir --title=$_IPP --geometry=50X1 --command=./startApp.sh
elif command -v gnome-terminal >/dev/null 2>&1; then
  gnome-terminal --working-directory="$_dir" -- ./startApp.sh
elif command -v xfce4-terminal >/dev/null 2>&1; then
  xfce4-terminal --working-directory="$_dir" --title="$_IPP" --command=./startApp.sh
elif command -v konsole >/dev/null 2>&1; then
  konsole --workdir "$_dir" -e ./startApp.sh
elif command -v x-terminal-emulator >/dev/null 2>&1; then
  cd "$_dir" && x-terminal-emulator -e ./startApp.sh
else
  printf "No terminal emulator found — starting ScenePlay headless (log: %s)\n" \
         "$_dir/sceneplay_launch.log"
  cd "$_dir" && nohup ./startApp.sh >> "$_dir/sceneplay_launch.log" 2>&1 &
fi
exit 0
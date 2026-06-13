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
lxterminal --working-directory=$_dir --title=$_IPP --geometry=50X1 --command=./startApp.sh
exit 0
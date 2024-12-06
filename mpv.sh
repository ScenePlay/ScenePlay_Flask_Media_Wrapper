#!/bin/bash
spd=$(echo $1)
loop=$(echo $2)
vol=$(echo $3)
scr=$(echo $4)
fi=$(echo $5)

DISPLAY=:0 mpv $fi --no-terminal --input-ipc-server=/tmp/mpvsocket --fullscreen=yes --speed=$spd --input-ipc-server=/tmp/mpvsocket --loop-file=$loop --volume=$vol --screen=$scr 
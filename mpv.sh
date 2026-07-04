#!/bin/bash
spd=$1
loop=$2
vol=$3
scr=$4
fi=$5

# VIDEO mpv instance. Socket renamed mpvsocket -> mpvsocket-video now that a
# second (audio-only) mpv exists on mpvsocket-music — commands and pkill -f
# target instances by socket name, never by the bare process name.
# exec: bash is replaced by mpv, so the stored/probed PID is mpv itself.
export DISPLAY=:0
exec mpv "$fi" --no-terminal --input-ipc-server=/tmp/mpvsocket-video --fullscreen=yes --speed="$spd" --loop-file="$loop" --volume="$vol" --screen="$scr"

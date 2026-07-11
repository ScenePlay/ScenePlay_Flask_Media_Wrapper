#!/bin/bash
vol=$1
fi=$2
sink=$3

# Audio-only mpv on its OWN IPC socket. --no-video keeps this instance off the
# display entirely (no window, no fullscreen fight with the video player).
# The socket name is the instance identity: music seek/pause/kill all target
# mpvsocket-music, the video player owns mpvsocket-video (see mpv.sh).
# exec: bash is replaced by mpv, so the PID the threader stores and probes is
# mpv itself, and pkill -f patterns can't hit a lingering wrapper.
# Optional $3: PulseAudio sink to play into — the relay stream's capture sink
# (a loopback mirrors it to the speakers); empty means the default output.
if [ -n "$sink" ]; then
   exec mpv "$fi" --no-terminal --no-video --input-ipc-server=/tmp/mpvsocket-music --volume="$vol" --audio-device="pulse/$sink"
else
   exec mpv "$fi" --no-terminal --no-video --input-ipc-server=/tmp/mpvsocket-music --volume="$vol"
fi

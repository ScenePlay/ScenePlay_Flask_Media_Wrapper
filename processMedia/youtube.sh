#!/bin/bash
renice -n 19 -p $$
if [ $# -eq 0 ];
then
  echo "$0: Missing arguments"
  read -p "Enter Youtube URL ": http
  read -p "Enter File Name ": name
elif [ $# -gt 6 ];
then
  echo "$0: Too many arguments: $@"
  exit 1
else
  echo "We got some argument(s)"
  echo "==========================="
  #echo "Number of arguments.: $#"
  #echo "List of arguments...: $@"
  echo "HTTp...................: $1"
  echo "Name...................: $2"
  echo "DIRECTORY..............: $3"
  echo "MEDIA TYPE.............: $4"
  echo "PKey...................: $5"
  echo "table..................: $6"
  echo "==========================="
  http=$(echo $1)
  name=$(echo $2)
  dir=$(echo $3)
  mediaType=$(echo $4)
  pkey=${5:-0}
  table=$(echo $6)
fi

# Ensure yt-dlp is available: clone once, update if we can, but never proceed without it
if [ -d "yt-dlp/.git" ]; then
  git -C yt-dlp pull || echo "$0: warning: could not update yt-dlp, using existing copy" >&2
else
  git clone https://github.com/yt-dlp/yt-dlp.git || { echo "$0: ERROR: failed to clone yt-dlp" >&2; exit 1; }
fi

if [ ! -f "yt-dlp/yt-dlp.sh" ]; then
  echo "$0: ERROR: yt-dlp/yt-dlp.sh not found - cannot download (check network/git on this server)" >&2
  exit 1
fi

# Filenames are now the YouTube video id (<vid>.<ext>), which can START WITH '-'
# (~1.6% of videos). --output=VALUE (the '=' form) stops optparse reading a
# dash-leading id as a flag; 'mv --' and quoting stop the shell doing the same.
# --no-playlist guards against a stray &list= making yt-dlp iterate a whole list.
if [ "$mediaType" = "mp3" ]; then
  bash yt-dlp/./yt-dlp.sh -i -x --audio-format "$mediaType" --no-playlist --output="$name" "$http" --proxy ""
else
  bash yt-dlp/./yt-dlp.sh -f 'bestvideo[height<=720]+bestaudio/best[height<=720]' --merge-output-format "$mediaType" --no-playlist --output="$name" "$http" --proxy ""
fi

  mkdir -p "$dir"
  mv -- "$name" "$dir$name"

 fl="$dir$name"

# sqlite3 CLI defaults to a 0 ms busy-timeout; with the extra metadata/playlist
# writer processes a concurrent write would otherwise fail and wedge the row at
# status 2. -cmd ".timeout 5000" gives it a 5s wait, matching Python's default.
if [ -f "$fl" ]; then
  if [ "$mediaType" = "mp3" ]; then
    sqlite3 -cmd ".timeout 5000" ScenePlay.db "UPDATE tblMusic SET dnLoadStatus = 3  where song_id = '"$pkey"'"
  else
    sqlite3 -cmd ".timeout 5000" ScenePlay.db "UPDATE tblVideoMedia SET dnLoadStatus = 3  where video_id = '"$pkey"'"
  fi
  mpg123 -q effects/finished.mp3
else
    if [ "$mediaType" = "mp3" ]; then
    sqlite3 -cmd ".timeout 5000" ScenePlay.db "UPDATE tblMusic SET dnLoadStatus = 4  where song_id = '"$pkey"'"
  else
    sqlite3 -cmd ".timeout 5000" ScenePlay.db "UPDATE tblVideoMedia SET dnLoadStatus = 4  where video_id = '"$pkey"'"
  fi
  mpg123 -q effects/failed.mp3
fi


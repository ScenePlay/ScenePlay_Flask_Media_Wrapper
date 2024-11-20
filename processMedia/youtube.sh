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

git clone https://github.com/yt-dlp/yt-dlp.git
git -C yt-dlp pull

if [ "$mediaType" = "mp3" ]; then
  bash yt-dlp/./yt-dlp.sh -i -x --audio-format $mediaType --output $name $http --proxy ""
else
  bash yt-dlp/./yt-dlp.sh  -f 'bestvideo[height<=720]+bestaudio/best[height<=720]' --merge-output-format $mediaType --output $name $http --proxy ""
fi

  mkdir -p $dir
  mv $name $dir$name

 fl=$dir$name

if [ -f $fl ]; then
  if [ "$mediaType" = "mp3" ]; then
    sqlite3 ScenePlay.db "UPDATE tblMusic SET dnLoadStatus = 3  where song_id = '"$pkey"'"
  else
    sqlite3 ScenePlay.db "UPDATE tblVideoMedia SET dnLoadStatus = 3  where video_id = '"$pkey"'"
  fi
  mpg123 -q effects/finished.mp3
else
    if [ "$mediaType" = "mp3" ]; then
    sqlite3 ScenePlay.db "UPDATE tblMusic SET dnLoadStatus = 4  where song_id = '"$pkey"'"
  else
    sqlite3 ScenePlay.db "UPDATE tblVideoMedia SET dnLoadStatus = 4  where video_id = '"$pkey"'"
  fi
  mpg123 -q effects/failed.mp3
fi


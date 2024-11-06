#!/bin/bash
renice -n 19 -p $$
if [ $# -eq 0 ];
then
  echo "$0: Missing arguments"
  read -p "Enter Youtube URL ": http
  read -p "Enter File Name ": name
elif [ $# -gt 5 ];
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
  echo "SCENE ID...............: $5"
  echo "==========================="
  http=$(echo $1)
  name=$(echo $2 | sed -e 's/[^A-Za-z0-9._-]/_/g')
  dir=$(echo $3)
  mediaType=$(echo $4)
  scene_ID=${5:-0}
fi

git clone https://github.com/yt-dlp/yt-dlp.git
git -C yt-dlp pull

if [ "$mediaType" = "mp3" ]; then
  bash yt-dlp/./yt-dlp.sh -i -x --audio-format mp3 --output $name.$mediaType $http --proxy ""
else
  bash yt-dlp/./yt-dlp.sh  --merge-output-format $mediaType --output $name.$mediaType $http --proxy ""
  #bash yt-dlp/./yt-dlp.sh -v -f "bv*[height<=360][ext=mp4]+ba*[ext=m4a]" -N 4 --output $name.$mediaType $http --proxy ""
fi

  mkdir -p $dir
  mv $name.$mediaType $dir$name.$mediaType

 fl=$dir$name.$mediaType

if [ -f $fl ]; then
  if [ "$mediaType" = "mp3" ]; then
    song_id=$(sqlite3 ScenePlay.db "insert into tblmusic (path,song,pTimes,active,genre,que,urlSource) values ('"$dir"','"$name"."$mediaType"',0,1,1,0,'"$http"'); select last_insert_rowid()" | awk '{print $1}')
    song_id=$(echo "$song_id" | sed 's/[^0-9]//g')
    if [ $scene_ID -gt 0 ]; then
      sqlite3 ScenePlay.db "insert into tblmusicScene (scene_ID,song_ID,orderBy,volume) values ($scene_ID, $song_id, 1,100);"
    fi
  else
    video_id=$(sqlite3 ScenePlay.db "insert into tblVideoMedia (path,title,pTimes,active,genre,que,urlSource) values ('"$dir"','"$name"."$mediaType"',0,1,1,0,'"$http"'); select last_insert_rowid()" | awk '{print $1}')
    video_id=$(echo "$video_id" | sed 's/[^0-9]//g')
    if [ $scene_ID -gt 0 ]; then
      sqlite3 ScenePlay.db "insert into tblVideoScene (scene_ID,video_ID,DisplayScreen_ID,orderBy,volume,loops) values ($scene_ID, $video_id,0, 1,100,0);"
    fi
  fi
  mpg123 -q effects/finished.mp3
else
  mpg123 -q effects/failed.mp3
fi


import threading


def remove_list_param(input_str):
    if '&list' in input_str:
        return input_str.split('&list')[0]
    return input_str


def yt_process(url, name, filePath='', mediaType='mp3', scene_ID=0):
    """Legacy direct-download entry — now routed through the shared Python
    yt-dlp pipeline in yt_que.YT_Exec (youtube.sh is retired). Fire-and-forget
    in a thread, matching the old detached Popen behavior."""
    from yt_que import YT_Exec
    url = remove_list_param(url)
    tbl = 'tblMusic' if mediaType == 'mp3' else 'tblVideoMedia'
    fi = [[0, filePath, name, url, mediaType, tbl]]
    threading.Thread(target=YT_Exec, args=(fi,), daemon=True).start()
    return "Done"

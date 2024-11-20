import subprocess

def remove_list_param(input_str):
    if '&list' in input_str:
        return input_str.split('&list')[0]
    return input_str


def yt_process(url,name,filePath,mediaType,scene_ID):
    url = remove_list_param(url)
    p = subprocess.Popen(['processMedia/./youtube.sh', url, name, filePath, mediaType, scene_ID],shell=False)
    p.kill
    return "Done"


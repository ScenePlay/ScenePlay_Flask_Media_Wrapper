"""Pure-function tests for the metadata / video-id / playlist feature.

No DB or network — just the URL parser, the failure classifier, the field
promoter, and the dead-entry filter.
"""

import json

from ytid import youtube_video_id, canonical_watch_url, is_playlist_url


class TestYoutubeVideoId:
    def test_watch_v(self):
        assert youtube_video_id('https://www.youtube.com/watch?v=IzOx0X5FWrc') == 'IzOx0X5FWrc'

    def test_watch_v_with_extra_params(self):
        # &list= / &t= must never leak into the id
        assert youtube_video_id('https://www.youtube.com/watch?v=IzOx0X5FWrc&list=PLabc&t=42') == 'IzOx0X5FWrc'

    def test_dash_leading_id(self):
        # ~1.6% of ids start with '-'; must survive parsing
        assert youtube_video_id('https://www.youtube.com/watch?v=-wtIMTCHWuI') == '-wtIMTCHWuI'

    def test_youtu_be(self):
        assert youtube_video_id('https://youtu.be/IzOx0X5FWrc?t=30') == 'IzOx0X5FWrc'

    def test_shorts_embed_live(self):
        assert youtube_video_id('https://www.youtube.com/shorts/abcdefghijk') == 'abcdefghijk'
        assert youtube_video_id('https://www.youtube.com/embed/abcdefghijk') == 'abcdefghijk'
        assert youtube_video_id('https://www.youtube.com/live/abcdefghijk') == 'abcdefghijk'

    def test_bare_id(self):
        assert youtube_video_id('IzOx0X5FWrc') == 'IzOx0X5FWrc'

    def test_playlist_url_has_no_video_id(self):
        assert youtube_video_id('https://www.youtube.com/playlist?list=PLabc') is None

    def test_garbage(self):
        assert youtube_video_id('') is None
        assert youtube_video_id('https://example.com/foo') is None
        assert youtube_video_id('https://youtube.com/watch?v=tooShort') is None  # not 11 chars


class TestPlaylistDetection:
    def test_pure_playlist(self):
        assert is_playlist_url('https://www.youtube.com/playlist?list=PLabc') is True

    def test_watch_with_list_is_single_video(self):
        # watch?v=X&list=Y = the user pasted a specific video; treat as single
        assert is_playlist_url('https://www.youtube.com/watch?v=IzOx0X5FWrc&list=PLabc') is False

    def test_youtu_be_with_list_is_single_video(self):
        # YouTube's Share button emits these while watching inside a playlist —
        # the video id lives in the path, so it must NOT be auto-expanded.
        assert is_playlist_url('https://youtu.be/IzOx0X5FWrc?list=PLabc') is False

    def test_plain_video(self):
        assert is_playlist_url('https://youtu.be/IzOx0X5FWrc') is False


def test_canonical_watch_url():
    assert canonical_watch_url('IzOx0X5FWrc') == 'https://www.youtube.com/watch?v=IzOx0X5FWrc'


class TestClassifyError:
    def test_permanent_markers(self):
        from meta_que import classify_error
        for msg in ('ERROR: Private video. Sign in if you have been granted access',
                    'ERROR: Video unavailable',
                    'This video has been removed by the uploader',
                    'Join this channel to get access (members-only)',
                    'Sign in to confirm your age',
                    'The uploader has not made this video available in your country'):
            assert classify_error(msg) == 'permanent', msg

    def test_transient_default(self):
        from meta_que import classify_error
        for msg in ('ERROR: unable to download: HTTP Error 503',
                    'Temporary failure in name resolution',
                    '', 'some unknown error'):
            assert classify_error(msg) == 'transient', msg


def test_promoted_fields():
    from meta_que import _promoted_fields
    info = {'id': 'IzOx0X5FWrc', 'title': 'Song', 'duration': 212,
            'channel': 'Chan', 'upload_date': '20240101', 'thumbnail': 'http://t',
            'view_count': 99, 'description': 'desc', 'categories': ['Music']}
    f = _promoted_fields(info)
    assert f['title'] == 'Song' and f['duration'] == 212 and f['uploader'] == 'Chan'
    assert json.loads(f['categories']) == ['Music']


class TestDeadEntry:
    def test_dead_titles(self):
        from playlist_que import _entry_is_dead
        assert _entry_is_dead({'title': '[Private video]'}) is True
        assert _entry_is_dead({'title': '[Deleted video]'}) is True

    def test_live_entry(self):
        from playlist_que import _entry_is_dead
        assert _entry_is_dead({'id': 'IzOx0X5FWrc', 'title': 'Real Song'}) is False

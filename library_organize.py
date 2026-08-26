"""Organize the library in one go: genres → artists → smart scenes.

The three pieces exist on their own pages (Suggest Genres, Artists, Smart
Scenes) for review; this composes them into a single function so a fresh
library can be organised with one click. Every step is conservative by
default — only the trusted derivations are written — and plan() reports
exactly what run() would do without writing anything.

Steps (each can be switched off in opts):
  1. genres   — genre_suggest: scene-membership proposals; optionally the
                tag-only ones too. Songs already labelled are left alone.
  2. artists  — media_facets: exact + high derivations; optionally medium.
                DM-confirmed artists are never overwritten.
  3. scenes   — smart_scenes.bulk_create per genre and per artist above a
                threshold, into one campaign; existing same-named scenes are
                attached (made smart) rather than duplicated.
  4. refresh  — every smart scene picks up whatever 1-3 just labelled.

Pure module: sqlite paths + injected settings getter, like its parts.
"""
import genre_suggest
import media_facets
import smart_scenes

DEFAULTS = {
    'genres': True, 'genres_include_tags': False,
    'artists': True, 'artists_include_medium': False,
    'scenes': True, 'genre_scenes': True, 'artist_scenes': True,
    'artist_min': 4, 'genre_min': 3, 'campaign_id': 0,
    'media': ['music', 'video'], 'attach_existing': True,
}


def options(opts):
    o = dict(DEFAULTS)
    o.update({k: v for k, v in (opts or {}).items() if k in DEFAULTS})
    o['artist_min'] = max(1, int(o['artist_min'] or 1))
    o['genre_min'] = max(1, int(o['genre_min'] or 1))
    o['campaign_id'] = int(o['campaign_id'] or 0)
    o['media'] = [m for m in (o['media'] or []) if m in smart_scenes.MEDIA] or list(smart_scenes.MEDIA)
    return o


def _genre_choices(database, get, o):
    want = {'scene'} | ({'tags'} if o['genres_include_tags'] else set())
    rows = genre_suggest.suggest(database, get)
    picked = [{'song_id': r['song_id'], 'genre': r['suggested']} for r in rows
              if r['confidence'] in want and r['suggested']]
    return picked, {k: sum(1 for r in rows if r['confidence'] == k) for k in ('scene', 'tags', 'conflict', 'none')}


def _artist_choices(database, o):
    want = {'exact', 'high'} | ({'medium'} if o['artists_include_medium'] else set())
    rows = media_facets.suggest_artists(database)
    picked = [{'media_type': r['media_type'], 'id': r['id'], 'artist': r['artist']} for r in rows
              if r['confidence'] in want and r['artist']]
    return picked, {k: sum(1 for r in rows if r['confidence'] == k) for k in ('exact', 'high', 'medium', 'low', 'none')}


def plan(database, get, opts=None):
    """What run() would do: counts per step and the scenes it would make.
    Scene counts are computed against the CURRENT labels, so with the
    genre/artist steps on, the real run can make a few more."""
    o = options(opts)
    out = {'options': o}
    if o['genres']:
        picked, by = _genre_choices(database, get, o)
        out['genres'] = {'apply': len(picked), 'by_confidence': by,
                         'names': sorted({p['genre'] for p in picked}, key=str.lower)}
    if o['artists']:
        picked, by = _artist_choices(database, o)
        out['artists'] = {'apply': len(picked), 'by_confidence': by}
    if o['scenes']:
        sc = {}
        if o['genre_scenes']:
            sc['genres'] = smart_scenes.bulk_create(database, 'genre', o['genre_min'], o['campaign_id'],
                                                    media=tuple(o['media']), dry_run=True,
                                                    attach_existing=o['attach_existing'])
        if o['artist_scenes']:
            sc['artists'] = smart_scenes.bulk_create(database, 'artist', o['artist_min'], o['campaign_id'],
                                                     media=tuple(o['media']), dry_run=True,
                                                     attach_existing=o['attach_existing'])
        out['scenes'] = sc
    return out


def run(database, get, opts=None):
    """Do it. Returns a summary in the same shape as plan(), with what was
    actually written, plus 'refreshed' (links added by the final refresh)."""
    o = options(opts)
    out = {'options': o}
    if o['genres']:
        picked, by = _genre_choices(database, get, o)
        res = genre_suggest.apply(database, picked)
        out['genres'] = {'applied': res['updated'], 'created_genres': res['created'], 'by_confidence': by}
    if o['artists']:
        picked, by = _artist_choices(database, o)
        out['artists'] = {'applied': media_facets.apply_artists(database, picked), 'by_confidence': by}
    if o['scenes']:
        sc = {}
        if o['genre_scenes']:
            sc['genres'] = smart_scenes.bulk_create(database, 'genre', o['genre_min'], o['campaign_id'],
                                                    media=tuple(o['media']), attach_existing=o['attach_existing'])
        if o['artist_scenes']:
            sc['artists'] = smart_scenes.bulk_create(database, 'artist', o['artist_min'], o['campaign_id'],
                                                     media=tuple(o['media']), attach_existing=o['attach_existing'])
        out['scenes'] = sc
    added = smart_scenes.refresh_all(database, auto_only=False)
    out['refreshed'] = {'scenes': len(added),
                        'links': sum(v['music'] + v['video'] for v in added.values())}
    return out

from flask import (Blueprint, render_template, request, abort, jsonify, json,
                   redirect, url_for, flash)
from extensions import *

from sql import *
from sql import appsettingGetKeepMusicPlaying, appsettingSetKeepMusicPlaying
from ledPlayer import *
from sys import platform
import os
import subprocess

from ytProcess import yt_process
from pathlib import Path
from models.scenes import tblscenes as sc
from routes.main import addMediaToYT_que
from flask import send_from_directory
import backup_restore

ut = Blueprint('ut', __name__)


def restart_computer():
    """Reboot the box: shutdown.exe on Windows, the repo-root
    restartComputer.sh (sudo shutdown -r now) on Linux."""
    if os.name == 'nt':
        subprocess.Popen(['shutdown', '/r', '/t', '3'], shell=False)
        return
    repo_root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    subprocess.Popen(['bash', os.path.join(repo_root, 'restartComputer.sh')],
                     shell=False)

def remove_list_param(input_str):
    if '&list' in input_str:
        return input_str.split('&list')[0]
    return input_str

@ut.route('/utilities',methods=['GET', 'POST'])
def main():
    if request.method == 'POST':
        pass
        if request.form['submit'] == 'Process Youtube':
            # Pass the RAW url (no remove_list_param): addMediaToYT_que detects a
            # playlist from &list= and enqueue_single canonicalizes single videos to
            # watch?v=<id>, so the &list= no longer needs stripping here.
            url = request.form['URLLink']
            # Optional display-name override — raw text; only the legacy
            # no-video-id path turns it into a filename (and scrubs it there).
            flname = request.form.get('FileName', '').strip()
            scene_ID = request.form.get("Scene")
            mediaType = request.form.get("Media")
            addMediaToYT_que(url, flname, mediaType, scene_ID)

            return  redirect(url_for('main.home'))
        elif request.form['submit'] == 'Backfill Metadata':
            # Tag legacy rows with their video id + queue metadata (see
            # sql.backfill_video_ids). Manual trigger so it doesn't hammer YouTube
            # on boot; pre-dedup duplicate videos are reported, not merged.
            summary = backfill_video_ids()
            flash(f"Backfill: tagged {summary['tagged']}, duplicates skipped "
                  f"{summary['duplicates_skipped']}, unparseable {summary['unparseable']}.")
            return  redirect(url_for('main.home'))
        elif request.form['submit'] == 'Scan Media Files':
            # Re-queue rows whose file is missing on disk (imported/merged data,
            # files removed outside the app, failed downloads worth retrying).
            from sql import scan_missing_media
            summary = scan_missing_media()
            if summary['music'] or summary['video']:
                flash(f"Scan: re-queued {summary['music']} songs and {summary['video']} videos "
                      f"for download — they are downloading now.")
            else:
                flash("Scan: all downloadable media files are present on disk.")
            return redirect(url_for('ut.main'))
        elif request.form['submit'] == 'Create Backup':
            path = backup_restore.create_backup(label='manual')
            flash(f"Backup created: {os.path.basename(path)}")
            return redirect(url_for('ut.main'))
        elif request.form['submit'] in ('Enable Nightly Backup', 'Disable Nightly Backup'):
            enable = request.form['submit'].startswith('Enable')
            appsettingSet('backup_auto', 1 if enable else 0, 'int')
            flash(f"Nightly backup {'enabled' if enable else 'disabled'}.")
            return redirect(url_for('ut.main'))
        elif request.form['submit'] == 'Restart Computer':
            # Rebooting the box is DM-only: anyone on the LAN can reach this
            # page, and a mid-session reboot kills music, maps, and the relay.
            from flask_login import current_user
            from models.user import tblUsers
            if not (current_user.is_authenticated and current_user.is_dm()):
                if tblUsers.query.first() is None:
                    flash('Restarting the computer requires a DM account — create one first.')
                    return redirect(url_for('auth.setup'))
                flash('Restarting the computer requires a DM login.')
                return redirect(url_for('auth.login', next=url_for('ut.main')))
            # Show the wait-for-reboot page FIRST, then reboot: the response
            # (and the page itself, fully self-contained) must reach the
            # browser before the network drops. It polls /api/server-info and
            # loads the app again once the box is back.
            import threading
            threading.Timer(3.0, restart_computer).start()
            return render_template('restarting.html')
        else:
            pass

    scenes = sc.query.with_entities(sc.scene_ID, sc.sceneName).order_by(sc.sceneName).all()
    scenes.insert(0, (0, "None"))
    data = select_data_stats()#arr)
    volume = currentvolume()
    keep_music = appsettingGetKeepMusicPlaying()
    backups = backup_restore.list_backups()
    backup_auto = str(appsettingGet('backup_auto', '0') or '0') == '1'
    return render_template('utils.html', items=data, volume=volume, Scenes=scenes,
                           keep_music=keep_music, backups=backups, backup_auto=backup_auto)

    
def _safe_backup_name(name):
    """Backup filenames only — no separators, must match what we generate."""
    return ('/' not in name and '\\' not in name
            and name.startswith('sceneplay-') and name.endswith('.zip'))


@ut.route('/backups/<name>')
def backup_download(name):
    if not _safe_backup_name(name):
        abort(404)
    return send_from_directory(backup_restore.BACKUP_DIR, name, as_attachment=True)


@ut.route('/api/backupdelete', methods=['POST'])
def backup_delete():
    name = (request.get_json() or {}).get('name', '')
    if not _safe_backup_name(name):
        abort(400)
    try:
        os.remove(os.path.join(backup_restore.BACKUP_DIR, name))
    except OSError:
        abort(404)
    return jsonify({'deleted': name})


@ut.route('/backup/import', methods=['POST'])
def backup_import():
    """Restore an uploaded archive. mode=replace swaps the whole database
    (safety snapshot taken first); mode=merge folds campaigns/scenes/media in
    with dedup. Either way missing media re-queues for download."""
    f = request.files.get('backupFile')
    mode = request.form.get('mode', 'merge')
    if not f or not f.filename:
        flash('Import: no file selected.')
        return redirect(url_for('ut.main'))
    os.makedirs(backup_restore.BACKUP_DIR, exist_ok=True)
    staged = os.path.join(backup_restore.BACKUP_DIR, '.upload.zip')
    f.save(staged)
    try:
        if mode == 'replace':
            summary = backup_restore.restore_replace(staged)
            db.engine.dispose()   # drop pooled connections to the swapped-out file
            flash(f"Restored from {summary['from']} (backup of {summary['created_at']}): "
                  f"{summary['uploads_restored']} images, {summary['requeued_downloads']} downloads "
                  f"re-queued. Safety copy: {summary['safety_backup']}. RESTART the app now.")
        else:
            summary = backup_restore.restore_merge(staged)
            flash(f"Merged from {summary['from']}: {summary['campaigns']} campaigns, "
                  f"{summary['scenes']} scenes, {summary['music']} songs, {summary['video']} videos, "
                  f"{summary['links']} scene links, {summary.get('homebrew', 0)} homebrew library entries, "
                  f"{summary['uploads_added']} images "
                  f"({summary['skipped_legacy']} legacy rows skipped). New media is downloading.")
    except ValueError as e:
        flash(f'Import failed: {e}')
    finally:
        try:
            os.remove(staged)
        except OSError:
            pass
    return redirect(url_for('ut.main'))


@ut.route('/api/keepmusicplaying', methods=['POST'])
def toggle_keep_music():
    current = appsettingGetKeepMusicPlaying()
    appsettingSetKeepMusicPlaying(0 if current else 1)
    return jsonify({'keep_music': 0 if current else 1})

@ut.route('/api/keepmusicplaying/off', methods=['GET'])
def set_keep_music_off():
    appsettingSetKeepMusicPlaying(0)
    return jsonify({'keep_music': 0})

@ut.route('/api/keepmusicplaying/on', methods=['GET'])
def set_keep_music_on():
    appsettingSetKeepMusicPlaying(1)
    return jsonify({'keep_music': 1})


@ut.route('/processyt', methods=['GET'])
def processyt():
    url = request.form['URLLink']
    url = remove_list_param(url)
    #print(url)
    flname = request.form['FileName']
    #print(flname)
    yt_process(url,flname)
    # currentvolume() (Pulse on Linux / Core Audio on Windows) — this was the
    # one remaining direct ALSA read; every other page already reads this way.
    volume = currentvolume()
    return render_template('utils.html',volume=volume)

from flask import (Blueprint, render_template, request, abort, jsonify, json,
                   redirect, url_for, flash)
from extensions import *

from sql import *
from sql import appsettingGetKeepMusicPlaying, appsettingSetKeepMusicPlaying
from sql import lights_off_on_scene_end_enabled, appsettingSet, LIGHTS_OFF_ON_SCENE_END
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


def restart_computer(sudo_password=None):
    """Reboot the box: shutdown.exe on Windows, the repo-root
    restartComputer.sh (sudo shutdown -r now) on Linux.

    sudo_password (optional, from the web page) is for boxes where sudo
    prompts: it goes to sudo -S on stdin and is never stored or logged."""
    if os.name == 'nt':
        subprocess.Popen(['shutdown', '/r', '/t', '3'], shell=False)
        return
    if sudo_password:
        # -S reads the password from stdin; -p '' silences the prompt so it
        # never hits the server's terminal.
        subprocess.run(['sudo', '-S', '-p', '', 'shutdown', '-r', 'now'],
                       input=sudo_password + '\n', text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30)
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
        elif request.form['submit'] == 'Save Media Folders':
            # Extra roots for the restore/merge file locator — point these at
            # actual media folders (e.g. /mnt/media/Music), not a whole drive:
            # every restore walks them recursively.
            roots = request.form.get('media_search_roots', '').strip()
            appsettingSet('media_search_roots', roots)
            missing = [p.strip() for p in roots.split(';')
                       if p.strip() and not os.path.isdir(p.strip())]
            msg = 'Media search folders saved.'
            if missing:
                msg += f" Warning — not found on this machine: {', '.join(missing)}"
            flash(msg)
            return redirect(url_for('ut.main'))
        elif request.form['submit'] in ('Enable Nightly Backup', 'Disable Nightly Backup'):
            enable = request.form['submit'].startswith('Enable')
            appsettingSet('backup_auto', 1 if enable else 0, 'int')
            flash(f"Nightly backup {'enabled' if enable else 'disabled'}.")
            return redirect(url_for('ut.main'))
        elif request.form['submit'] == 'Reset yt-dlp':
            # Escape hatch for a stale/corrupted checkout: delete the yt-dlp
            # git clone and pull it fresh. Runs inline (clone is --depth 1)
            # so the flash message reports the real outcome.
            import ytdlp_source
            if ytdlp_source.reset():
                flash('yt-dlp reset: checkout deleted and re-cloned fresh from GitHub.')
            else:
                flash('yt-dlp reset: checkout deleted, but the re-clone failed '
                      '(network/git problem?) — downloads fall back to the '
                      'pip-installed copy until the next successful refresh.')
            return redirect(url_for('ut.main'))
        elif request.form['submit'] == 'Save DM Access':
            # Flipping who may use ScenePlay is itself DM-only — otherwise a
            # player could simply switch it back off.
            from flask_login import current_user
            if not (current_user.is_authenticated and current_user.is_dm()):
                flash('Changing access control requires a DM login.')
                return redirect(url_for('auth.login', next=url_for('ut.main')))
            enable = bool(request.form.get('dm_only_sceneplay'))
            appsettingSet('DMOnlyScenePlay', 1 if enable else 0, 'int')
            flash('ScenePlay controls and tables are now DM-only.' if enable
                  else 'ScenePlay controls and tables are open to everyone '
                       'on the network.')
            return redirect(url_for('ut.main'))
        elif request.form['submit'] == 'Save Lighting':
            enable = bool(request.form.get('lights_off_on_scene_end'))
            appsettingSet(LIGHTS_OFF_ON_SCENE_END, '1' if enable else '0')
            flash('Lights will turn off when a scene\'s media finishes.' if enable
                  else 'Lights stay on after a scene\'s media finishes (until the '
                       'next scene or All Stop).')
            return redirect(url_for('ut.main'))
        elif request.form['submit'] == 'Save AI Settings':
            # AI settings are DM-only, and the key follows the relay-secret
            # masking rule: a blank submission keeps the existing key.
            from flask_login import current_user
            if not (current_user.is_authenticated and current_user.is_dm()):
                flash('Changing AI settings requires a DM login.')
                return redirect(url_for('auth.login', next=url_for('ut.main')))
            import gemini
            if request.form.get('gemini_clear_key'):
                gemini.clear_api_key()
                flash('Gemini API key removed.')
            else:
                key = request.form.get('gemini_api_key', '').strip()
                if key:
                    gemini.save_api_key(key)
                    flash('Gemini API key saved (stored locally in '
                          'instance/, never in the database or git).')
            for modality in ('text', 'image', 'video'):
                chosen = request.form.get(f'gemini_model_{modality}', '')
                if chosen in gemini._ALLOWED[modality]:
                    appsettingSet(f'gemini_model_{modality}', chosen)
            # Runware: the alternative image provider (same key hygiene)
            import runware
            if request.form.get('runware_clear_key'):
                runware.clear_api_key()
                flash('Runware API key removed.')
            else:
                rkey = request.form.get('runware_api_key', '').strip()
                if rkey:
                    runware.save_api_key(rkey)
                    flash('Runware API key saved (stored locally in '
                          'instance/, never in the database or git).')
            rmodel = request.form.get('runware_model', '').strip()
            if rmodel and ':' in rmodel:
                ok, why = runware.validate_image_model(rmodel)
                if ok:
                    appsettingSet('runware_model', rmodel)
                else:
                    flash(why)          # keep the previous model

            provider = request.form.get('image_provider', 'gemini')
            appsettingSet('image_provider',
                          'runware' if provider == 'runware' else 'gemini')
            rtext = request.form.get('runware_text_model', '').strip()
            if rtext:
                slug, why = runware.normalize_text_model(rtext)
                if slug:
                    appsettingSet('runware_text_model', slug)
                    if slug != rtext:
                        flash(f'Layout model saved as "{slug}" (the chat API '
                              'uses slug ids; converted automatically).')
                else:
                    flash(why)          # keep the previous model
            tprov = request.form.get('text_provider', 'gemini')
            appsettingSet('text_provider',
                          'runware' if tprov == 'runware' else 'gemini')
            flash('AI settings saved.')
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
            sudo_pw = request.form.get('sudo_password') or None
            threading.Timer(3.0, restart_computer,
                            kwargs={'sudo_password': sudo_pw}).start()
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
    media_roots = appsettingGet('media_search_roots', '') or ''
    from routes._util import dm_only_sceneplay_enabled
    from flask_login import current_user
    import gemini
    import runware
    return render_template('utils.html', items=data, volume=volume, Scenes=scenes,
                           keep_music=keep_music, backups=backups, backup_auto=backup_auto,
                           lights_off_on_end=lights_off_on_scene_end_enabled(),
                           media_roots=media_roots,
                           dm_only_sceneplay=dm_only_sceneplay_enabled(),
                           gemini_configured=gemini.configured(),
                           gemini_key_source=gemini.key_source(),
                           gemini_models={m: gemini.resolve_model(m)
                                          for m in ('text', 'image', 'video')},
                           gemini_choices={'text': gemini.TEXT_MODELS,
                                           'image': gemini.IMAGE_MODELS,
                                           'video': gemini.VIDEO_MODELS},
                           runware_configured=runware.configured(),
                           runware_key_source=runware.key_source(),
                           runware_model=runware.resolve_model(),
                           image_provider=(appsettingGet('image_provider', 'gemini')
                                           or 'gemini'),
                           text_provider=(appsettingGet('text_provider', 'gemini')
                                          or 'gemini'),
                           runware_text_model=runware.resolve_text_model(),
                           is_dm=(current_user.is_authenticated
                                  and current_user.is_dm()))

    
def _dm_required_json():
    """DM gate for the update APIs (same policy as Restart Computer: anyone
    on the LAN reaches this page, but changing the box is DM-only). The
    login_url lets the page send the visitor STRAIGHT to the login form,
    which brings them back here afterwards."""
    from flask_login import current_user
    if not (current_user.is_authenticated and current_user.is_dm()):
        return jsonify({'error': 'DM login required.',
                        'login_url': url_for('auth.login', next=url_for('ut.main'))}), 403
    return None


@ut.route('/api/update/check')
def update_check():
    """Read-only: how far behind upstream is this install? Safe for the page
    to call on load (git fetch only updates remote-tracking refs)."""
    import app_update
    return jsonify(app_update.check_updates())


@ut.route('/api/update/run', methods=['POST'])
def update_run():
    gate = _dm_required_json()
    if gate:
        return gate
    import app_update
    # Optional system password from the page, for the sudo step (nginx fix).
    # Handed straight to sudo -S via stdin — never stored or logged.
    data = request.get_json(silent=True) or {}
    return jsonify(app_update.run_update(
        sudo_password=data.get('sudo_password') or None))


@ut.route('/utilities/restart-app')
def utilities_restart_app():
    """Post-update restart: render the wait page FIRST (self-contained; polls
    /api/server-info), then exit — the watchdog (Linux) or the detached
    helper (Windows) brings the app back with the new code."""
    from flask_login import current_user
    if not (current_user.is_authenticated and current_user.is_dm()):
        flash('Restarting ScenePlay requires a DM login.')
        return redirect(url_for('auth.login', next=url_for('ut.main')))
    import app_update
    app_update.restart_app(3.0)
    return render_template('restarting.html')


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
    # Database only: skip extracting uploads/ (battlemap images/videos) —
    # unzipping a big media tree crashes low-memory boxes (Pi Zero).
    include_uploads = not request.form.get('db_only')
    if not f or not f.filename:
        flash('Import: no file selected.')
        return redirect(url_for('ut.main'))
    os.makedirs(backup_restore.BACKUP_DIR, exist_ok=True)
    staged = os.path.join(backup_restore.BACKUP_DIR, '.upload.zip')
    f.save(staged)
    try:
        img_note = '' if include_uploads else ' (database only — images skipped)'
        if mode == 'replace':
            summary = backup_restore.restore_replace(staged, include_uploads=include_uploads)
            db.engine.dispose()   # drop pooled connections to the swapped-out file
            flash(f"Restored from {summary['from']} (backup of {summary['created_at']}): "
                  f"{summary['uploads_restored']} images, {summary.get('found_local', 0)} media files "
                  f"found already on this machine, {summary['requeued_downloads']} downloads "
                  f"re-queued{img_note}. Safety copy: {summary['safety_backup']}. RESTART the app now.")
        else:
            # Full merge also brings the TTRPG tree; imported characters whose
            # owner has no same-named account here land under the importing DM.
            full = bool(request.form.get('full_merge'))
            from flask_login import current_user
            fallback_uid = (current_user.user_id
                            if full and current_user.is_authenticated else None)
            summary = backup_restore.restore_merge(staged, include_uploads=include_uploads,
                                                   full=full, fallback_user_id=fallback_uid)
            msg = (f"Merged from {summary['from']}: {summary['campaigns']} campaigns, "
                   f"{summary['scenes']} scenes, {summary['music']} songs, {summary['video']} videos, "
                   f"{summary['links']} scene links, {summary.get('homebrew', 0)} library entries, "
                   f"{summary['uploads_added']} images{img_note} "
                   f"({summary['skipped_legacy']} legacy rows skipped, "
                   f"{summary.get('found_local', 0)} media files found already local).")
            if full:
                msg += (f" TTRPG: {summary['characters']} characters "
                        f"({summary['characters_skipped']} kept local), "
                        f"{summary['sessions']} sessions, {summary['maps']} maps, "
                        f"{summary['session_monsters']} monsters, {summary['tokens']} tokens, "
                        f"{summary.get('floorplans', 0)} 3D floorplans, "
                        f"{summary.get('map_prompts', 0)} map prompts, "
                        f"{summary.get('obs_bindings', 0)} OBS bindings, "
                        f"{summary.get('dice_rolls', 0)} dice rolls, "
                        f"{summary.get('cron_schedules', 0)} cron schedules (imported inactive), "
                        f"{summary['notes']} notes, {summary['lighting']} lighting links.")
                if summary.get('characters_no_owner'):
                    msg += (f" WARNING: {summary['characters_no_owner']} characters were NOT "
                            f"imported — this box has no user accounts yet. Create the DM "
                            f"account (or log in) and run the merge again.")
            flash(msg + ' New media is downloading.')
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

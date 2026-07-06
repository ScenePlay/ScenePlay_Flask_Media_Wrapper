import hashlib
import hmac
import logging
import os
import secrets

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, bcrypt
from models.user import tblUsers
from functools import wraps
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

auth = Blueprint('auth', __name__)


# ── Local-access password recovery ─────────────────────────────────────────────
# Self-service reset with the server's FILESYSTEM as the root of trust: the
# one-time code is written to a text file on the box, so retrieving it proves
# local access (console, SSH, or file share). LAN-only app, no PII — anyone
# who can read the server's disk already owns the game, so this is exactly as
# strong as it needs to be. Codes are single-use, expire, and rate-limit.

RECOVERY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'password_recovery')
_RECOVERY_FILE      = 'recovery_code.txt'
_RECOVERY_TTL_MIN   = 15
_RECOVERY_MAX_TRIES = 5
# no ambiguous characters (I/O/0/1) — the code gets read off a screen and retyped
_RECOVERY_ALPHABET  = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _recovery_norm(code):
    return (code or '').replace('-', '').replace(' ', '').strip().upper()


def _recovery_begin(username):
    """Write a fresh one-time code file for `username`; return its path.

    Only the sha256 of the code is kept in tblAppSettings — the file on disk
    is the sole copy of the code itself."""
    from sql import appsettingSet
    code = '-'.join(''.join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(4))
                    for _ in range(2))
    expires = (datetime.utcnow() + timedelta(minutes=_RECOVERY_TTL_MIN)
               ).strftime('%Y-%m-%d %H:%M:%S')
    os.makedirs(RECOVERY_DIR, exist_ok=True)
    path = os.path.join(RECOVERY_DIR, _RECOVERY_FILE)
    with open(path, 'w') as f:
        f.write(
            'ScenePlay password recovery\n'
            '===========================\n\n'
            f'Account:  {username}\n'
            f'Code:     {code}\n\n'
            f'Enter this code on the password recovery page within '
            f'{_RECOVERY_TTL_MIN} minutes.\n'
            'This file is deleted automatically once the code is used or expires.\n'
        )
    appsettingSet('pw_recovery_user',     username)
    appsettingSet('pw_recovery_hash',     hashlib.sha256(_recovery_norm(code).encode()).hexdigest())
    appsettingSet('pw_recovery_expires',  expires)
    appsettingSet('pw_recovery_attempts', '0')
    log.warning('Password recovery code generated for %r -> %s', username, path)
    return path


def _recovery_clear():
    from sql import appsettingSet
    appsettingSet('pw_recovery_hash', '')
    appsettingSet('pw_recovery_user', '')
    try:
        os.remove(os.path.join(RECOVERY_DIR, _RECOVERY_FILE))
    except OSError:
        pass


def _recovery_check(username, code):
    """Validate a recovery attempt. Returns (ok, error_message).

    Every call consumes an attempt; the code is invalidated after
    _RECOVERY_MAX_TRIES failures or expiry."""
    from sql import appsettingGet, appsettingSet
    stored = appsettingGet('pw_recovery_hash', '') or ''
    if not stored:
        return False, 'No recovery code is active — generate one first.'
    expires = appsettingGet('pw_recovery_expires', '') or ''
    if not expires or datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') > expires:
        _recovery_clear()
        return False, 'The recovery code has expired — generate a new one.'
    try:
        tries = int(appsettingGet('pw_recovery_attempts', '0') or 0) + 1
    except ValueError:
        tries = 1
    if tries > _RECOVERY_MAX_TRIES:
        _recovery_clear()
        return False, 'Too many attempts — generate a new code.'
    appsettingSet('pw_recovery_attempts', str(tries))
    if username != (appsettingGet('pw_recovery_user', '') or ''):
        return False, 'The active code was generated for a different username.'
    digest = hashlib.sha256(_recovery_norm(code).encode()).hexdigest()
    if not hmac.compare_digest(digest, stored):
        left = _RECOVERY_MAX_TRIES - tries
        return False, f'Incorrect code ({left} attempt{"s" if left != 1 else ""} left).'
    return True, None


def dm_required(f):
    """Decorator that requires the current user to have the 'dm' role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_dm():
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


@auth.route('/ttrpg/setup', methods=['GET', 'POST'])
def setup():
    """First-run only: create the initial DM account. Locked once any user exists."""
    if tblUsers.query.first():
        return redirect(url_for('auth.login'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')

        if not username or not display_name or not password:
            error = 'All fields are required.'
        else:
            dm = tblUsers(
                username=username,
                display_name=display_name,
                role='dm',
                active=1,
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            )
            dm.set_password(password)
            db.session.add(dm)
            db.session.commit()
            login_user(dm, remember=True)
            return redirect(url_for('ttrpg.dashboard'))

    return render_template('ttrpg/setup.html', error=error)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('ttrpg.dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = tblUsers.query.filter_by(username=username, active=1).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('ttrpg.dashboard'))
        error = 'Invalid username or password.'

    no_users = tblUsers.query.first() is None
    return render_template('ttrpg/login.html', error=error, no_users=no_users)


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth.route('/ttrpg/recover', methods=['GET', 'POST'])
def recover_password():
    """Locked-out reset (works for the DM too, who has no higher authority to
    ask): step 1 writes a one-time code to a file on the server, step 2 takes
    the code + a new password. Reading the file is the proof of local access."""
    if current_user.is_authenticated:
        return redirect(url_for('ttrpg.dashboard'))

    error = None
    code_path = None
    username = ''
    if request.method == 'POST':
        action   = request.form.get('action', '')
        username = request.form.get('username', '').strip()

        if action == 'generate':
            if not username:
                error = 'Enter your username first.'
            elif not tblUsers.query.filter_by(username=username, active=1).first():
                error = 'No active account with that username.'
            else:
                code_path = _recovery_begin(username)

        elif action == 'reset':
            code       = request.form.get('code', '')
            new_pw     = request.form.get('new_password', '').strip()
            confirm_pw = request.form.get('confirm_password', '').strip()
            if not username or not new_pw:
                error = 'Username and new password are required.'
            elif new_pw != confirm_pw:
                error = 'New passwords do not match.'
            else:
                ok, err = _recovery_check(username, code)
                if not ok:
                    error = err
                else:
                    user = tblUsers.query.filter_by(username=username, active=1).first()
                    if not user:
                        error = 'Account not found.'
                    else:
                        user.set_password(new_pw)
                        db.session.commit()
                        _recovery_clear()
                        log.warning('Password reset via recovery code for %r', username)
                        # Best-effort: the relay portal logs players in against
                        # this same hash, so re-push accounts when relaying.
                        try:
                            import relay_broadcaster
                            relay_broadcaster.push_session_users()
                        except Exception:
                            pass
                        flash('Password updated — log in with your new password.')
                        return redirect(url_for('auth.login'))

    return render_template('ttrpg/password_recovery.html',
                           error=error, code_path=code_path, username=username,
                           ttl=_RECOVERY_TTL_MIN)


@auth.route('/ttrpg/register', methods=['GET', 'POST'])
@login_required
@dm_required
def register():
    """DM-only: create a new player account."""
    error = None
    success = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'player')

        if not username or not display_name or not password:
            error = 'All fields are required.'
        elif tblUsers.query.filter_by(username=username).first():
            error = f'Username "{username}" is already taken.'
        else:
            user = tblUsers(
                username=username,
                display_name=display_name,
                role=role,
                active=1,
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            success = f'Account created for {display_name}.'

    players = tblUsers.query.order_by(tblUsers.display_name).all()
    return render_template('ttrpg/register.html', error=error, success=success, players=players)


@auth.route('/ttrpg/users/<int:user_id>/delete', methods=['POST'])
@login_required
@dm_required
def delete_user(user_id):
    user = tblUsers.query.get_or_404(user_id)
    if user.is_dm():
        flash('Cannot delete a DM account.')
        return redirect(url_for('auth.register'))
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('auth.register'))


@auth.route('/ttrpg/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@dm_required
def reset_password(user_id):
    """DM-only: set a new password for any user."""
    user = tblUsers.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()
    if not new_password:
        flash('Password cannot be empty.')
        return redirect(url_for('auth.register'))
    user.set_password(new_password)
    db.session.commit()
    flash(f'Password reset for {user.display_name}.')
    return redirect(url_for('auth.register'))


@auth.route('/ttrpg/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Any logged-in user can change their own password."""
    error = None
    success = None
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '').strip()
        confirm_pw = request.form.get('confirm_password', '').strip()
        if not current_user.check_password(current_pw):
            error = 'Current password is incorrect.'
        elif not new_pw:
            error = 'New password cannot be empty.'
        elif new_pw != confirm_pw:
            error = 'New passwords do not match.'
        else:
            current_user.set_password(new_pw)
            db.session.commit()
            success = 'Password updated successfully.'
    return render_template('ttrpg/change_password.html', error=error, success=success)

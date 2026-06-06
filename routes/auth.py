from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, bcrypt
from models.user import tblUsers
from functools import wraps
from datetime import datetime

auth = Blueprint('auth', __name__)


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

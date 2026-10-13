"""Local accounts and consent preferences. No email delivery or Scout dependencies."""
import hashlib
import time
import os
import re
import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path

import click
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint('membership', __name__, url_prefix='/members')


def db():
    if 'member_db' not in g:
        g.member_db = sqlite3.connect(current_app.config['MEMBERSHIP_DATABASE'])
        g.member_db.row_factory = sqlite3.Row
    return g.member_db


def migrate():
    """Transactional, versioned schema initialization; safe to repeat."""
    connection = db()
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version > 2:
        raise RuntimeError('Membership database is newer than this application')
    if version == 0:
        with connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL, newsletter_opt_in INTEGER NOT NULL DEFAULT 0,
                newsletter_frequency TEXT NOT NULL DEFAULT 'weekly',
                consent_updated_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(newsletter_opt_in IN (0,1)),
                CHECK(newsletter_frequency IN ('weekly','monthly')))''')
            connection.execute('PRAGMA user_version = 1')
        version = 1
    if version == 1:
        with connection:
            connection.execute('ALTER TABLE members ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0')
            connection.execute('CREATE TABLE password_resets (token_hash TEXT PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id), expires_at INTEGER NOT NULL)')
            connection.execute('CREATE TABLE auth_limits (bucket TEXT PRIMARY KEY, started_at INTEGER NOT NULL, attempts INTEGER NOT NULL)')
            connection.execute('PRAGMA user_version = 2')


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


def init_membership(app):
    app.config.update(
        SECRET_KEY=os.environ.get('TREND_FINDAH_SECRET_KEY'),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('TREND_FINDAH_ENV') == 'production',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MEMBERSHIP_DATABASE=os.environ.get('TREND_FINDAH_DATABASE', str(Path(app.instance_path) / 'members.sqlite3')),
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config['SECRET_KEY']:
        if os.environ.get('TREND_FINDAH_ENV') == 'production':
            raise RuntimeError('TREND_FINDAH_SECRET_KEY is required in production')
        # Stable across local restarts; never checked into source control.
        keyfile = Path(app.instance_path) / 'session.key'
        try:
            with open(keyfile, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = keyfile.read_text().strip()
    app.config['MEMBERSHIP_DUMMY_HASH'] = generate_password_hash(secrets.token_urlsafe(32))
    app.register_blueprint(bp)
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def load_member():
        g.member = None
        if session.get('member_id'):
            g.member = db().execute('SELECT id,email,newsletter_opt_in,newsletter_frequency,session_version FROM members WHERE id=?', (session['member_id'],)).fetchone()
        if g.member is not None and session.get('member_version', 0) != g.member['session_version']:
            session.clear()
            g.member = None
        # Protect membership mutations without changing Scout or legacy analysis requests.
        if request.blueprint == 'membership' and request.method == 'POST':
            token = request.form.get('csrf_token', '')
            expected = session.get('_csrf')
            if not expected or not secrets.compare_digest(expected, token):
                abort(400, description='Your form expired. Reload the page and try again.')

    @app.after_request
    def protect_recovery_response(response):
        if request.endpoint in ('membership.forgot_password', 'membership.reset_password'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.teardown_appcontext
    def close_db(error):
        connection = g.pop('member_db', None)
        if connection is not None:
            connection.close()

    @app.cli.command('init-membership-db')
    def initialize():
        migrate()
        click.echo('Membership database initialized (schema version 2).')

    @app.cli.command('membership-reset-link')
    @click.argument('email')
    def reset_link(email):
        """Generate a local test link for an account you control; never logs automatically."""
        if os.environ.get('TREND_FINDAH_ENV') == 'production':
            raise click.ClickException('Local reset links are disabled in production.')
        member = db().execute('SELECT id FROM members WHERE email=?', (email.strip().lower(),)).fetchone()
        if member is None:
            raise click.ClickException('No local account found.')
        token = issue_reset(member['id'])
        click.echo('Local test only; expires in 15 minutes:')
        click.echo('http://localhost:5002/members/reset-password/' + token)

    @app.cli.command('backup-membership-db')
    @click.argument('destination', type=click.Path())
    def backup(destination):
        """Create a consistent SQLite backup without overwriting existing files."""
        path = Path(destination)
        with open(path, 'xb', opener=lambda p, f: os.open(p, f, 0o600)):
            pass
        try:
            target = sqlite3.connect(path)
            try:
                db().backup(target)
            finally:
                target.close()
        except Exception:
            path.unlink()
            raise
        click.echo('Membership backup created.')

    with app.app_context():
        migrate()


@bp.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            error = 'Enter a valid email address.'
        elif not 10 <= len(password) <= 128:
            error = 'Use a password between 10 and 128 characters.'
        elif password != request.form.get('password_confirm'):
            error = 'Passwords must match.'
        elif request.form.get('newsletter_opt_in', '') not in ('', 'yes'):
            error = 'Choose a valid newsletter preference.'
        else:
            try:
                with db():
                    cursor = db().execute('INSERT INTO members(email,password_hash,newsletter_opt_in,consent_updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)', (email, generate_password_hash(password), int(request.form.get('newsletter_opt_in') == 'yes')))
                session.clear()
                session['member_id'] = cursor.lastrowid
                session.permanent = True
                return redirect(url_for('membership.preferences'))
            except sqlite3.IntegrityError:
                error = 'An account with that email already exists. Please log in.'
    return render_template('membership.html', mode='register', error=error), 400 if error else 200


@bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not allow_attempt('login', email):
            return render_template('membership.html', mode='login', error='Too many attempts. Please try again in 15 minutes.'), 429
        member = db().execute('SELECT * FROM members WHERE email=?', (email[:254],)).fetchone()
        # Perform password work even for unknown accounts.
        stored = member['password_hash'] if member else current_app.config['MEMBERSHIP_DUMMY_HASH']
        valid = check_password_hash(stored, password[:128])
        if member and valid and len(password) <= 128:
            session.clear()
            session['member_id'] = member['id']
            session['member_version'] = member['session_version']
            session.permanent = True
            return redirect(url_for('membership.preferences'))
        error = 'Email or password is incorrect.'
    return render_template('membership.html', mode='login', error=error), 400 if error else 200


@bp.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


@bp.route('/preferences', methods=['GET', 'POST'])
def preferences():
    if g.member is None:
        return redirect(url_for('membership.login'))
    error = None
    saved = False
    if request.method == 'POST':
        frequency = request.form.get('newsletter_frequency', '')
        opt_in = request.form.get('newsletter_opt_in', '')
        if frequency not in ('weekly', 'monthly') or opt_in not in ('', 'yes'):
            error = 'Choose valid newsletter preferences.'
        else:
            with db():
                db().execute('UPDATE members SET newsletter_opt_in=?,newsletter_frequency=?,consent_updated_at=CURRENT_TIMESTAMP WHERE id=?', (int(opt_in == 'yes'), frequency, g.member['id']))
            g.member = db().execute('SELECT * FROM members WHERE id=?', (g.member['id'],)).fetchone()
            saved = True
    return render_template('membership.html', mode='preferences', error=error, saved=saved), 400 if error else 200


def allow_attempt(action, email):
    """Database-backed limits survive restarts and work across workers.

    Uses the actual peer address; never trusts client-supplied forwarded headers.
    """
    now = int(time.time())
    keys = [(action + ':ip:' + (request.remote_addr or 'unknown'), 30),
            (action + ':email:' + email[:254].lower(), 5)]
    connection = db()
    connection.execute('BEGIN IMMEDIATE')
    try:
        connection.execute('DELETE FROM auth_limits WHERE started_at <= ?', (now - 900,))
        for key, limit in keys:
            bucket = hashlib.sha256(key.encode()).hexdigest()
            row = connection.execute('SELECT attempts FROM auth_limits WHERE bucket=?', (bucket,)).fetchone()
            if row and row['attempts'] >= limit:
                connection.rollback()
                return False
        for key, limit in keys:
            bucket = hashlib.sha256(key.encode()).hexdigest()
            connection.execute('INSERT INTO auth_limits VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1', (bucket, now))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def issue_reset(member_id):
    token = secrets.token_urlsafe(32)
    with db():
        db().execute('DELETE FROM password_resets WHERE member_id=? OR expires_at<=?', (member_id, int(time.time())))
        db().execute('INSERT INTO password_resets VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), member_id, int(time.time()) + 900))
    return token


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    message = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not allow_attempt('recovery', email):
            return render_template('password_recovery.html', mode='forgot', error='Too many requests. Please try again in 15 minutes.'), 429
        # No email service is configured. Never expose account existence or tokens here.
        message = 'Email recovery is not active yet. No email has been sent. For local testing, use the reset-link command described in the setup guide.'
    return render_template('password_recovery.html', mode='forgot', message=message)


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    reset = db().execute('SELECT * FROM password_resets WHERE token_hash=? AND expires_at>?', (digest, int(time.time()))).fetchone()
    if reset is None:
        return render_template('password_recovery.html', mode='invalid', error='This reset link is invalid or expired. Request a new one.'), 400
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if not 10 <= len(password) <= 128:
            error = 'Use a password between 10 and 128 characters.'
        elif password != request.form.get('password_confirm'):
            error = 'Passwords must match.'
        else:
            hashed = generate_password_hash(password)
            connection = db()
            connection.execute('BEGIN IMMEDIATE')
            try:
                consumed = connection.execute('DELETE FROM password_resets WHERE token_hash=? AND expires_at>?', (digest, int(time.time())))
                if consumed.rowcount != 1:
                    connection.rollback()
                    return render_template('password_recovery.html', mode='invalid', error='This reset link is invalid or expired.'), 400
                connection.execute('UPDATE members SET password_hash=?,session_version=session_version+1 WHERE id=?', (hashed, reset['member_id']))
                connection.execute('DELETE FROM password_resets WHERE member_id=?', (reset['member_id'],))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            session.clear()
            return redirect(url_for('membership.login', reset='complete'))
    response = current_app.make_response((render_template('password_recovery.html', mode='reset', error=error), 400 if error else 200))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

"""Local accounts and consent preferences. Transactional recovery email; no Scout dependencies."""
import hashlib
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, parse_qsl, urlencode
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
    if version > 4:
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
        version = 2
    if version == 2:
        with connection:
            connection.execute('CREATE TABLE IF NOT EXISTS watchlist (id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id), kind TEXT NOT NULL CHECK(kind IN ("team","trend")), target TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(member_id,kind,target))')
            connection.execute('PRAGMA user_version = 3')
        version = 3
    if version == 3:
        with connection:
            connection.execute('CREATE TABLE IF NOT EXISTS site_owners (member_id INTEGER PRIMARY KEY REFERENCES members(id))')
            connection.execute('CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, member_id INTEGER REFERENCES members(id), category TEXT NOT NULL, page TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT "open", created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            connection.execute('PRAGMA user_version = 4')


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


def init_membership(app):
    app.config.update(
        RESEND_API_KEY=os.environ.get('RESEND_API_KEY', ''),
        RECOVERY_FROM=os.environ.get('TREND_FINDAH_EMAIL_FROM', 'Trend Findah <noreply@mail.trendfindah.com>'),
        PUBLIC_ORIGIN=os.environ.get('TREND_FINDAH_PUBLIC_ORIGIN', 'https://trendfindah.com'),
        SECRET_KEY=os.environ.get('TREND_FINDAH_SECRET_KEY'),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('TREND_FINDAH_ENV') == 'production',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MEMBERSHIP_DATABASE=os.environ.get('TREND_FINDAH_DATABASE', str(Path(app.instance_path) / 'members.sqlite3')),
    )
    origin = urlsplit(app.config['PUBLIC_ORIGIN'])
    if (origin.scheme != 'https' or not origin.hostname or origin.username
            or origin.password or origin.query or origin.fragment or origin.path not in ('', '/')):
        raise RuntimeError('TREND_FINDAH_PUBLIC_ORIGIN must be an HTTPS origin without a path')
    app.config['PUBLIC_ORIGIN'] = app.config['PUBLIC_ORIGIN'].rstrip('/')
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
        g.is_owner = bool(g.member and db().execute('SELECT 1 FROM site_owners WHERE member_id=?', (g.member['id'],)).fetchone())
        # Protect membership mutations without changing Scout or legacy analysis requests.
        if request.blueprint == 'membership' and request.method == 'POST':
            token = request.form.get('csrf_token', '')
            expected = session.get('_csrf')
            if not expected or not secrets.compare_digest(expected, token):
                abort(400, description='Your form expired. Reload the page and try again.')

    @app.after_request
    def protect_recovery_response(response):
        if request.endpoint in ('membership.forgot_password', 'membership.reset_password', 'membership.feedback_review'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.teardown_appcontext
    def close_db(error):
        connection = g.pop('member_db', None)
        if connection is not None:
            connection.close()

    @app.cli.command('membership-owner')
    @click.argument('email')
    def membership_owner(email):
        """Grant owner review access from the private service Shell only."""
        member = db().execute('SELECT id FROM members WHERE email=?', (email.strip().lower(),)).fetchone()
        if member is None:
            raise click.ClickException('Register your account first; no account matched.')
        with db():
            db().execute('INSERT OR IGNORE INTO site_owners(member_id) VALUES(?)', (member['id'],))
        click.echo('Owner feedback access enabled for that registered account.')

    @app.cli.command('membership-count')
    def membership_count():
        """Show signup totals to a service operator without exposing member details."""
        total = db().execute('SELECT COUNT(*) FROM members').fetchone()[0]
        recent = db().execute("SELECT COUNT(*) FROM members WHERE created_at >= datetime('now','-7 days')").fetchone()[0]
        opted_in = db().execute('SELECT COUNT(*) FROM members WHERE newsletter_opt_in=1').fetchone()[0]
        click.echo(f'Total members: {total}')
        click.echo(f'Signed up in the last 7 days: {recent}')
        click.echo(f'Newsletter opt-ins: {opted_in}')

    @app.cli.command('init-membership-db')
    def initialize():
        migrate()
        click.echo('Membership database initialized (schema version 4).')

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

    @app.cli.command('membership-backup-status')
    def backup_status():
        """Report backup health without printing account details."""
        import json
        folder = Path(current_app.config['MEMBERSHIP_DATABASE']).resolve().parent/'account-backups'
        status_path = folder/'status.json'
        if not status_path.exists():
            click.echo('No automatic account backup has completed yet.')
            return
        status = json.loads(status_path.read_text())
        from datetime import datetime
        from zoneinfo import ZoneInfo
        stamp = datetime.fromisoformat(status['completed_at']).astimezone(ZoneInfo('America/New_York'))
        click.echo('Latest backup: ' + stamp.strftime('%b %d, %I:%M %p %Z'))
        click.echo('Restore verified: ' + ('yes' if status['restore_verified'] else 'no'))
        click.echo('Stored in: ' + str(folder))

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
    from newsletter import init_newsletter
    init_newsletter(app)
    from member_picks import init_picks
    init_picks(app)


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
                return redirect(url_for('home'))
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
            return redirect(url_for('home'))
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
    return render_template('membership.html', mode='preferences', error=error, saved=saved, watchlist=db().execute('SELECT * FROM watchlist WHERE member_id=? ORDER BY created_at DESC,id DESC', (g.member['id'],)).fetchall()), 400 if error else 200


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


def send_recovery_email(email, token):
    # Never build recovery links from the request Host or forwarded headers.
    link = current_app.config['PUBLIC_ORIGIN'] + url_for('membership.reset_password', token=token)
    payload = {
        'from': current_app.config['RECOVERY_FROM'],
        'to': [email],
        'subject': 'Reset your Trend Findah password',
        'text': ('Reset your Trend Findah password using this link:\n\n' + link +
                 '\n\nThis link expires in 15 minutes and works once. '
                 'If you did not request this, you can ignore this email. '
                 'Your password has not changed.'),
    }
    request_data = Request('https://api.resend.com/emails',
        data=json.dumps(payload).encode(), method='POST', headers={
            'Authorization': 'Bearer ' + current_app.config['RESEND_API_KEY'],
            'Content-Type': 'application/json', 'User-Agent': 'TrendFindah/1.0'})
    try:
        with urlopen(request_data, timeout=8) as response:
            result = json.loads(response.read(65536))
        if not isinstance(result, dict) or not result.get('id'):
            raise ValueError('Missing email ID')
        return True
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        # Do not log recipient, provider response bodies, credentials or reset links.
        current_app.logger.error('Password recovery email was not confirmed by Resend')
        return False


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    message = None
    enabled = bool(current_app.config['RESEND_API_KEY'])
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not allow_attempt('recovery', email):
            return render_template('password_recovery.html', mode='forgot', recovery_enabled=enabled,
                error='Too many requests. Please try again in 15 minutes.'), 429
        if enabled:
            member = db().execute('SELECT id FROM members WHERE email=?', (email,)).fetchone() if len(email) <= 254 else None
            if member:
                token = issue_reset(member['id'])
                if not send_recovery_email(email, token):
                    with db():
                        db().execute('DELETE FROM password_resets WHERE token_hash=?',
                                     (hashlib.sha256(token.encode()).hexdigest(),))
            message = ('If an account exists for that email, a password-reset link will be sent. '
                       'Check your inbox and spam folder. The link expires in 15 minutes.')
        else:
            message = 'Email recovery is temporarily unavailable. No email has been sent. Please try again later.'
    return render_template('password_recovery.html', mode='forgot', message=message,
                           recovery_enabled=enabled)


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


@bp.post('/watchlist/save')
def save_watchlist():
    if g.member is None:
        return redirect(url_for('membership.login'))
    kind = request.form.get('kind')
    target = request.form.get('target', '')
    title = request.form.get('title', '').strip()
    if kind == 'team':
        from scout4.stats import team_code
        code = team_code(target)
        if code not in {'ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE','DAL','DEN','DET','GB','HOU','IND','JAX','KC','LA','LAC','LV','MIA','MIN','NE','NO','NYG','NYJ','PHI','PIT','SEA','SF','TB','TEN','WAS'}:
            abort(400)
        target = url_for('scout4.teams_page', team=code)
        title = code
    elif kind == 'trend':
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or parts.fragment or parts.path not in ('/combination-details','/trend-games','/trend-details') or len(target)>4000 or not 1<=len(title)<=200:
            abort(400)
        try:
            target = parts.path + '?' + urlencode(sorted(parse_qsl(parts.query, max_num_fields=30)))
        except ValueError:
            abort(400)
    else:
        abort(400)
    connection = db()
    with connection:
        count = connection.execute('SELECT COUNT(*) FROM watchlist WHERE member_id=?', (g.member['id'],)).fetchone()[0]
        exists = connection.execute('SELECT 1 FROM watchlist WHERE member_id=? AND kind=? AND target=?', (g.member['id'],kind,target)).fetchone()
        if count >= 100 and not exists:
            abort(400, description='Your watchlist is full. Remove an item before saving another.')
        connection.execute('INSERT INTO watchlist(member_id,kind,target,title) VALUES(?,?,?,?) ON CONFLICT(member_id,kind,target) DO NOTHING', (g.member['id'],kind,target,title))
    return redirect(url_for('membership.preferences') + '#my-watchlist')


@bp.post('/watchlist/<int:item_id>/remove')
def remove_watchlist(item_id):
    if g.member is None:
        return redirect(url_for('membership.login'))
    with db():
        db().execute('DELETE FROM watchlist WHERE id=? AND member_id=?', (item_id,g.member['id']))
    return redirect(url_for('membership.preferences') + '#my-watchlist')


@bp.route('/feedback', methods=['GET','POST'])
def feedback_page():
    page = request.form.get('page', '/') if request.method=='POST' else request.args.get('page','/')
    try:
        parts = urlsplit(page)
    except ValueError:
        page = '/'
        parts = urlsplit(page)
    if parts.scheme or parts.netloc or not parts.path.startswith('/') or len(page)>200:
        page = '/'
    else:
        page = parts.path
    if page.startswith('/members/reset-password/'):
        page = '/members/reset-password'
    error = None
    if request.method=='POST':
        if not allow_attempt('feedback', str(g.member['id']) if g.member else csrf_token()):
            return render_template('feedback.html',page=page,error='Too many reports. Please try again in 15 minutes.'),429
        category = request.form.get('category','')
        message = request.form.get('message','').strip()
        if category not in ('Problem','Suggestion','Other') or not 10<=len(message)<=2000:
            error = 'Choose a feedback type and enter 10–2,000 characters.'
        else:
            with db():
                db().execute('INSERT INTO feedback(member_id,category,page,message) VALUES(?,?,?,?)',
                    (g.member['id'] if g.member else None,category,page,message))
            return redirect(url_for('membership.feedback_page',sent=1))
    return render_template('feedback.html',page=page,error=error),400 if error else 200


@bp.get('/feedback/review')
def feedback_review():
    if not g.is_owner:
        abort(403)
    status = request.args.get('status','open')
    if status not in ('open','resolved'):
        abort(400)
    try:
        page = int(request.args.get('page','1'))
    except ValueError:
        abort(400)
    count = db().execute('SELECT COUNT(*) FROM feedback WHERE status=?',(status,)).fetchone()[0]
    pages = max(1,(count+49)//50)
    if not 1<=page<=pages:
        abort(400)
    reports = db().execute('SELECT * FROM feedback WHERE status=? ORDER BY id DESC LIMIT 50 OFFSET ?', (status,(page-1)*50)).fetchall()
    return render_template('feedback_review.html',reports=reports,status=status,page=page,pages=pages)


@bp.post('/feedback/<int:report_id>/status')
def feedback_status(report_id):
    if not g.is_owner:
        abort(403)
    status = request.form.get('status')
    if status not in ('open','resolved'):
        abort(400)
    with db():
        db().execute('UPDATE feedback SET status=? WHERE id=?',(status,report_id))
    return redirect(url_for('membership.feedback_review'))

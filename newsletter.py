"""Owner-reviewed newsletters. Startup and page views never send email."""
import json
import os
import secrets
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import click
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from itsdangerous import URLSafeSerializer, BadSignature
from membership import db

bp = Blueprint('newsletter', __name__, url_prefix='/newsletter')
SECTIONS = [('predictions', 'Prediction highlights'), ('matchups', 'Upcoming matchups'),
            ('trends', 'Notable trends'), ('updates', 'Site updates')]


def init_newsletter(app):
    app.config.update(
        NEWSLETTER_ENABLED=os.environ.get('TREND_FINDAH_NEWSLETTER_ENABLED') == 'true',
        NEWSLETTER_FROM=os.environ.get('TREND_FINDAH_NEWSLETTER_FROM',
            'Trendfindah <noreply@mail.trendfindah.com>'),
        NEWSLETTER_ADDRESS=os.environ.get('TREND_FINDAH_NEWSLETTER_ADDRESS', '').strip(),
    )
    app.register_blueprint(bp)
    with app.app_context():
        with db():
            db().execute('''CREATE TABLE IF NOT EXISTS newsletter_issues (
                id INTEGER PRIMARY KEY, subject TEXT NOT NULL, frequency TEXT NOT NULL,
                sections TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                approved_at TEXT, audience_frozen INTEGER NOT NULL DEFAULT 0, owner_id INTEGER NOT NULL,
                CHECK(frequency IN ('weekly','monthly')),
                CHECK(status IN ('draft','approved','canceled')))''')
            db().execute('''CREATE TABLE IF NOT EXISTS newsletter_deliveries (
                issue_id INTEGER NOT NULL, member_id INTEGER NOT NULL,
                payload TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL DEFAULT 'pending', provider_id TEXT,
                attempted_at INTEGER, claimed_at INTEGER,
                PRIMARY KEY(issue_id,member_id),
                CHECK(state IN ('pending','sending','accepted','failed','unknown','skipped')))''')

    @app.before_request
    def protect_newsletter_forms():
        if request.blueprint == 'newsletter' and request.method == 'POST':
            # RFC 8058 one-click requests authenticate with their signed URL.
            if request.endpoint == 'newsletter.unsubscribe' and request.form.get('List-Unsubscribe') == 'One-Click':
                return
            expected = session.get('_csrf', '')
            token = request.form.get('csrf_token', '')
            if not expected or not secrets.compare_digest(expected, token):
                abort(400, description='Your form expired. Reload and try again.')

    @app.after_request
    def private_newsletter_response(response):
        if request.blueprint == 'newsletter':
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.cli.command('newsletter-send')
    @click.argument('issue_id', type=int)
    @click.option('--send', is_flag=True, help='Actually send the approved issue; omitted means dry run.')
    def send_command(issue_id, send):
        issue = get_issue(issue_id)
        if issue['status'] != 'approved':
            raise click.ClickException('Approve the issue in the owner newsletter page first.')
        if not send:
            if issue['audience_frozen']:
                eligible = db().execute("SELECT COUNT(*) FROM newsletter_deliveries d JOIN members m ON m.id=d.member_id WHERE d.issue_id=? AND d.state NOT IN ('accepted','skipped') AND m.newsletter_opt_in=1 AND m.newsletter_frequency=?", (issue_id,issue['frequency'])).fetchone()[0]
            else:
                eligible = db().execute('SELECT COUNT(*) FROM members WHERE newsletter_opt_in=1 AND newsletter_frequency=?', (issue['frequency'],)).fetchone()[0]
            click.echo(f'Dry run: {eligible} members currently eligible. No email sent.')
            return
        try:
            accepted, skipped, failed = send_issue(issue_id)
        except ValueError as error:
            raise click.ClickException(str(error)) from None
        click.echo(f'Provider accepted: {accepted}; skipped: {skipped}; failed/uncertain: {failed}. Accepted does not confirm inbox delivery.')


def require_owner():
    if not g.get('is_owner'):
        abort(403)


def get_issue(issue_id):
    issue = db().execute('SELECT * FROM newsletter_issues WHERE id=?', (issue_id,)).fetchone()
    if issue is None:
        abort(404)
    return issue


def signer():
    return URLSafeSerializer(current_app.secret_key, salt='newsletter-unsubscribe-v1')


def unsubscribe_url(member_id):
    return current_app.config['PUBLIC_ORIGIN'] + '/newsletter/unsubscribe/' + signer().dumps(member_id)


def email_payload(issue, member):
    sections = json.loads(issue['sections'])
    link = unsubscribe_url(member['id'])
    context = dict(issue=issue, sections=sections, headings=SECTIONS, unsubscribe_url=link,
                   origin=current_app.config['PUBLIC_ORIGIN'], address=current_app.config['NEWSLETTER_ADDRESS'])
    text = issue['subject'] + '\n\n'
    for key, heading in SECTIONS:
        if sections.get(key):
            text += heading + '\n' + sections[key] + '\n\n'
    text += 'Visit Gravy Train: ' + context['origin'] + '\n\n' + context['address'] + '\nUnsubscribe: ' + link
    return {'from':current_app.config['NEWSLETTER_FROM'], 'to':[member['email']],
            'subject':issue['subject'], 'text':text,
            'html':render_template('newsletter_email.html', **context),
            'headers':{'List-Unsubscribe':'<' + link + '>', 'List-Unsubscribe-Post':'List-Unsubscribe=One-Click'}}


@bp.route('/manage', methods=['GET','POST'])
@bp.route('/issues/<int:issue_id>/edit', methods=['GET','POST'])
def manage(issue_id=None):
    require_owner()
    editing = get_issue(issue_id) if issue_id is not None else None
    if editing is not None and editing['status'] != 'draft':
        abort(409, description='Approved or canceled issues cannot be edited.')
    defaults = dict(json.loads(editing['sections']), subject=editing['subject'], frequency=editing['frequency']) if editing is not None else {}
    error = None
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        frequency = request.form.get('frequency', '')
        sections = {key:request.form.get(key, '').strip() for key, heading in SECTIONS}
        if not 5 <= len(subject) <= 150 or '\n' in subject or '\r' in subject:
            error = 'Enter a subject between 5 and 150 characters.'
        elif frequency not in ('weekly','monthly'):
            error = 'Choose weekly or monthly.'
        elif not 20 <= len(sections['predictions']) <= 6000 or any(len(value)>6000 for value in sections.values()):
            error = 'Add 20–6,000 characters of prediction highlights; each other section allows up to 6,000.'
        else:
            with db():
                if editing is not None:
                    result = db().execute("UPDATE newsletter_issues SET subject=?,frequency=?,sections=? WHERE id=? AND status='draft'", (subject,frequency,json.dumps(sections),issue_id))
                    if result.rowcount != 1:
                        abort(409)
                else:
                    issue_id = db().execute('INSERT INTO newsletter_issues(subject,frequency,sections,owner_id) VALUES(?,?,?,?)', (subject,frequency,json.dumps(sections),g.member['id'])).lastrowid
            return redirect(url_for('newsletter.issue_page', issue_id=issue_id))
    issues = db().execute('SELECT id,subject,frequency,status,created_at FROM newsletter_issues ORDER BY id DESC LIMIT 50').fetchall()
    counts = {row['newsletter_frequency']:row['n'] for row in db().execute('SELECT newsletter_frequency,COUNT(*) n FROM members WHERE newsletter_opt_in=1 GROUP BY newsletter_frequency')}
    return render_template('newsletter_manage.html', issues=issues, counts=counts, headings=SECTIONS,error=error,defaults=defaults,editing=editing),400 if error else 200


@bp.get('/issues/<int:issue_id>')
def issue_page(issue_id):
    require_owner()
    issue = get_issue(issue_id)
    counts = {row['state']:row['n'] for row in db().execute('SELECT state,COUNT(*) n FROM newsletter_deliveries WHERE issue_id=? GROUP BY state', (issue_id,))}
    return render_template('newsletter_issue.html',issue=issue,sections=json.loads(issue['sections']),headings=SECTIONS,counts=counts)


@bp.get('/issues/<int:issue_id>/preview')
def preview(issue_id):
    require_owner()
    issue=get_issue(issue_id)
    # Preview footer links stay on the owner's preview; no live unsubscribe token.
    return render_template('newsletter_email.html', issue=issue,sections=json.loads(issue['sections']),headings=SECTIONS,
        unsubscribe_url=url_for('newsletter.issue_page',issue_id=issue_id),origin=current_app.config['PUBLIC_ORIGIN'],
        address=current_app.config['NEWSLETTER_ADDRESS'] or 'Mailing address will appear here')


@bp.post('/issues/<int:issue_id>/approve')
def approve(issue_id):
    require_owner()
    with db():
        db().execute("UPDATE newsletter_issues SET status='approved',approved_at=CURRENT_TIMESTAMP WHERE id=? AND status='draft'", (get_issue(issue_id)['id'],))
    return redirect(url_for('newsletter.issue_page', issue_id=issue_id))


@bp.post('/issues/<int:issue_id>/cancel')
def cancel(issue_id):
    require_owner()
    with db():
        db().execute("UPDATE newsletter_issues SET status='canceled' WHERE id=?", (get_issue(issue_id)['id'],))
    return redirect(url_for('newsletter.issue_page', issue_id=issue_id))


@bp.route('/unsubscribe/<token>', methods=['GET','POST'])
def unsubscribe(token):
    try:
        member_id = signer().loads(token)
        if not isinstance(member_id, int):
            raise BadSignature('Invalid token')
    except BadSignature:
        abort(400, description='This unsubscribe link is invalid.')
    done=False
    if request.method == 'POST':
        with db():
            db().execute('UPDATE members SET newsletter_opt_in=0,consent_updated_at=CURRENT_TIMESTAMP WHERE id=?',(member_id,))
        done=True
        if request.form.get('List-Unsubscribe') == 'One-Click':
            return '',200
    return render_template('newsletter_unsubscribe.html', done=done)


def send_issue(issue_id):
    """Explicit operator invocation only. Never called by page views or approval."""
    if not current_app.config['NEWSLETTER_ENABLED']:
        raise ValueError('Newsletter sending is disabled. Enable it only after reviewing the preview and sender settings.')
    if not current_app.config['RESEND_API_KEY'] or not current_app.config['NEWSLETTER_ADDRESS']:
        raise ValueError('Configure the Resend key and newsletter mailing address before sending.')
    issue=get_issue(issue_id)
    if issue['status']!='approved':
        raise ValueError('Issue is not approved.')
    # Freeze the actual payload and key before making any external request.
    connection=db();connection.execute('BEGIN IMMEDIATE')
    try:
        if not get_issue(issue_id)['audience_frozen']:
            for member in connection.execute('SELECT id,email FROM members WHERE newsletter_opt_in=1 AND newsletter_frequency=?',(issue['frequency'],)).fetchall():
                connection.execute('INSERT INTO newsletter_deliveries(issue_id,member_id,payload,idempotency_key) VALUES(?,?,?,?)',
                    (issue_id,member['id'],json.dumps(email_payload(issue,member)),secrets.token_hex(24)))
            connection.execute('UPDATE newsletter_issues SET audience_frozen=1 WHERE id=?',(issue_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    accepted=skipped=failed=0
    rows=db().execute("SELECT * FROM newsletter_deliveries WHERE issue_id=? AND state NOT IN ('accepted','skipped')",(issue_id,)).fetchall()
    for row in rows:
        now=int(time.time())
        connection=db();connection.execute('BEGIN IMMEDIATE')
        member=connection.execute('SELECT * FROM members WHERE id=?',(row['member_id'],)).fetchone()
        current=connection.execute('SELECT * FROM newsletter_deliveries WHERE issue_id=? AND member_id=?',(issue_id,row['member_id'])).fetchone()
        if get_issue(issue_id)['status']!='approved':
            connection.rollback();break
        if current['state'] in ('accepted','skipped') or (current['state']=='sending' and (current['claimed_at'] or 0)>now-300):
            connection.rollback();continue
        if current['attempted_at'] is not None and current['attempted_at']<=now-23*3600:
            # Resend keys expire after 24h; stop before that rather than duplicate an uncertain send.
            connection.rollback();failed+=1;continue
        if not member or not member['newsletter_opt_in'] or member['newsletter_frequency']!=issue['frequency'] or json.loads(current['payload'])['to'] != [member['email']]:
            connection.execute("UPDATE newsletter_deliveries SET state='skipped' WHERE issue_id=? AND member_id=?",(issue_id,row['member_id']))
            connection.commit();skipped+=1;continue
        connection.execute("UPDATE newsletter_deliveries SET state='sending',claimed_at=?,attempted_at=COALESCE(attempted_at,?) WHERE issue_id=? AND member_id=?",(now,now,issue_id,row['member_id']))
        connection.commit()
        provider_id=None
        req=Request('https://api.resend.com/emails',data=current['payload'].encode(),method='POST',headers={
            'Authorization':'Bearer '+current_app.config['RESEND_API_KEY'],'Content-Type':'application/json',
            'Idempotency-Key':current['idempotency_key'],'User-Agent':'TrendfindahNewsletter/1.0'})
        try:
            with urlopen(req,timeout=10) as response:
                provider_id=json.load(response).get('id')
            if not provider_id:
                raise ValueError('Missing provider acknowledgment')
            state='accepted';accepted+=1
        except HTTPError:
            state='failed';failed+=1
        except (URLError, TimeoutError, OSError, ValueError):
            state='unknown';failed+=1
        with connection:
            connection.execute('UPDATE newsletter_deliveries SET state=?,provider_id=? WHERE issue_id=? AND member_id=?',(state,provider_id,issue_id,row['member_id']))
        # Sequential sending stays within the provider's default request budget.
        time.sleep(.6)
    return accepted,skipped,failed

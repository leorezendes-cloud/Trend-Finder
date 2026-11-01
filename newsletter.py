"""Owner-reviewed newsletters. Startup and page views never send email."""
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import click
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from itsdangerous import URLSafeSerializer, BadSignature
from membership import db

bp = Blueprint('newsletter', __name__, url_prefix='/newsletter')
SECTIONS = [('predictions', "The Plug's Picks"), ('trends', 'Hot Right Now'),
            ('expert', "The Expert's Take"), ('matchups', 'Around the League'),
            ('updates', 'Site Updates')]


def plug_email_blocks(value, section, frequency):
    """Keep new multi-line cards intact and split legacy single-line digests.

    Older saved weekly drafts have one line per game/trend with no blank lines;
    newer records contain a title, detail, and link separated with newlines.
    """
    value = value or ''
    blocks = [part.strip() for part in value.split('\n\n') if part.strip()]
    if section not in ('predictions', 'trends', 'matchups') or len(blocks) != 1:
        return blocks
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) < 2:
        return blocks
    result = []
    for line in lines:
        continuation = (line.startswith(('https://', 'http://', 'ATS:', 'Total:', 'Pick:', 'Scout:')))
        if continuation and result:
            result[-1] += '\n' + line
        else:
            result.append(line)
    return result


def plug_period_label(issue):
    """Readable heading for old stored YYYY-Wxx subjects; no DB mutation."""
    label = issue['subject'].split(' · ', 1)[-1]
    if issue['frequency'] == 'weekly' and re.fullmatch(r'\d{4}-W\d{2}', label):
        try:
            return newsletter_subject('weekly', label).split(' · ', 1)[-1]
        except ValueError:
            pass
    return label


def init_newsletter(app):
    app.config.update(
        NEWSLETTER_AUTO_DRAFT_ENABLED=True,
        NEWSLETTER_ENABLED=os.environ.get('TREND_FINDAH_NEWSLETTER_ENABLED') == 'true',
        NEWSLETTER_FROM=os.environ.get('TREND_FINDAH_NEWSLETTER_FROM',
            'The Weekly Plug <noreply@mail.trendfindah.com>'),
        NEWSLETTER_ADDRESS=os.environ.get('TREND_FINDAH_NEWSLETTER_ADDRESS', '').strip(),
    )
    app.register_blueprint(bp)
    app.jinja_env.filters['plug_email_blocks'] = plug_email_blocks
    app.jinja_env.filters['plug_period_label'] = plug_period_label
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

    with app.app_context():
        with db():
            db().execute("CREATE TABLE IF NOT EXISTS newsletter_generated (frequency TEXT NOT NULL, period TEXT NOT NULL, issue_id INTEGER NOT NULL UNIQUE, metadata TEXT NOT NULL, PRIMARY KEY(frequency,period))")

    @app.cli.command('newsletter-generate')
    @click.option('--frequency', type=click.Choice(['weekly','monthly']), default='weekly')
    def generate_command(frequency):
        owner = db().execute('SELECT member_id FROM site_owners ORDER BY member_id LIMIT 1').fetchone()
        if not owner:
            raise click.ClickException('Configure a site-owner account first.')
        if frequency == 'monthly':
            issue_id = prepare_completed_month_draft(app, scheduled=False)
            if issue_id == 'not_due':
                raise click.ClickException('No completed monthly issue is due or it already exists.')
        else:
            issue_id = generate_draft(owner['member_id'], frequency)
        click.echo(f'Draft #{issue_id} ready for review at /newsletter/issues/{issue_id}. No email sent.')

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
                eligible = db().execute("SELECT COUNT(*) FROM newsletter_deliveries d JOIN members m ON m.id=d.member_id WHERE d.issue_id=? AND d.state NOT IN ('accepted','skipped') AND m.newsletter_opt_in=1 AND m.newsletter_frequency IN (?,?)", (issue_id,issue['frequency'],'weekly')).fetchone()[0]
            else:
                eligible = db().execute('SELECT COUNT(*) FROM members WHERE newsletter_opt_in=1 AND newsletter_frequency IN (?,?)', (issue['frequency'],'weekly')).fetchone()[0]
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


def headings_for_issue(issue):
    if issue['frequency'] == 'monthly':
        return [('predictions', 'Month in Review'), ('trends', 'Trend Spotlight'),
                ('expert', 'Expert Highlights'), ('matchups', 'Looking Ahead'),
                ('updates', 'Site Updates')]
    return SECTIONS


def email_payload(issue, member):
    sections = json.loads(issue['sections'])
    link = unsubscribe_url(member['id'])
    context = dict(issue=issue, sections=sections, headings=headings_for_issue(issue), unsubscribe_url=link,
                   origin=current_app.config['PUBLIC_ORIGIN'], address=current_app.config['NEWSLETTER_ADDRESS'])
    text = issue['subject'] + '\n\n'
    for key, heading in headings_for_issue(issue):
        if sections.get(key):
            text += heading + '\n' + sections[key] + '\n\n'
    text += 'Visit TrendFindah.com: ' + context['origin'] + '\n\n' + context['address'] + '\nUnsubscribe: ' + link
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
    # GET only lists saved drafts; live previews never freeze monthly content.
    defaults = dict(json.loads(editing['sections']), subject=editing['subject'], frequency=editing['frequency']) if editing is not None else {}
    error = None
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        frequency = editing['frequency'] if editing is not None else request.form.get('frequency', '')
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
    return render_template('newsletter_manage.html', issues=issues, counts=counts, headings=headings_for_issue(editing) if editing is not None else SECTIONS,error=error,defaults=defaults,editing=editing),400 if error else 200


@bp.get('/issues/<int:issue_id>')
def issue_page(issue_id):
    require_owner()
    issue = get_issue(issue_id)
    counts = {row['state']:row['n'] for row in db().execute('SELECT state,COUNT(*) n FROM newsletter_deliveries WHERE issue_id=? GROUP BY state', (issue_id,))}
    metadata = db().execute('SELECT metadata FROM newsletter_generated WHERE issue_id=?',(issue_id,)).fetchone()
    return render_template('newsletter_issue.html',issue=issue,sections=json.loads(issue['sections']),headings=headings_for_issue(issue),counts=counts,generated=json.loads(metadata['metadata']) if metadata else None)


@bp.get('/results/<int:year>/<int:month>')
def monthly_results(year, month):
    """Public read-only saved scores, pinned to the original newsletter time."""
    from newsletter_draft import completed_month_games, ET
    if not (1999 <= year <= 2100 and 1 <= month <= 12):
        abort(404)
    raw_at = request.args.get('at', '')
    if not raw_at.isdecimal() or len(raw_at) > 12:
        abort(400, description='A valid monthly results date is required.')
    try:
        at = datetime.fromtimestamp(int(raw_at), timezone.utc)
    except (ValueError, OSError, OverflowError):
        abort(400, description='Invalid monthly results date.')
    snapshot_date = at.astimezone(ET).date()
    snapshot_month = snapshot_date.replace(day=1)
    previous_month = (snapshot_month - timedelta(days=1)).replace(day=1)
    selected_month = datetime(year, month, 1).date()
    if at > datetime.now(timezone.utc) or selected_month not in (snapshot_month, previous_month):
        abort(400, description='Monthly results date is out of range.')
    games = completed_month_games(Path(current_app.root_path), at,
                                  report_month=f'{year:04d}-{month:02d}')
    month_name = selected_month.strftime('%B %Y')
    next_month = (selected_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month - timedelta(days=1)
    coverage_end = min(month_end, snapshot_date)
    coverage_label = (
        f"{selected_month.strftime('%b')} {selected_month.day} – "
        f"{coverage_end.strftime('%b')} {coverage_end.day}, {year}"
    )
    return render_template('newsletter_results.html', games=games,
                           month_name=month_name, coverage_label=coverage_label,
                           as_of=at.astimezone(ET),
                           origin=current_app.config['PUBLIC_ORIGIN'])



@bp.get('/weekly/diagnostics')
def weekly_diagnostics():
    """Owner-only counts for newsletter eligibility; never expose private picks."""
    require_owner()
    from flask import jsonify
    from newsletter_draft import timestamp
    from expert_beta import store
    now = datetime.now(timezone.utc)
    result = {'archive_readable': False, 'archive_records': 0,
              'released_records': 0, 'upcoming_within_seven_days': 0,
              'scout_with_side': 0, 'approved_expert': 0,
              'publicly_featured_expert': 0, 'errors': []}
    try:
        archive = store()
        records = archive.records()
        result['archive_readable'] = True
        result['archive_records'] = len(records)
        featured_cache = {}
        for record in records:
            if record.get('kind') not in ('production_import', 'prospective'):
                continue
            result['released_records'] += 1
            game = record['scout']['game']
            kickoff = timestamp(game['kickoff_utc'])
            if not now < kickoff <= now + timedelta(days=7):
                continue
            result['upcoming_within_seven_days'] += 1
            scout = record['scout']
            if (scout.get('spread') or {}).get('side') or (scout.get('total') or {}).get('side'):
                result['scout_with_side'] += 1
            expert = record.get('expert') or {}
            if expert.get('review_status') != 'approved':
                continue
            result['approved_expert'] += 1
            key = (int(game['season']), int(game['week']))
            if key not in featured_cache:
                try:
                    featured_cache[key] = set(archive.featured(*key))
                except (OSError, ValueError, TypeError):
                    featured_cache[key] = set()
                    result['errors'].append('featured_configuration_invalid')
            identity = f"{key[0]}/{key[1]}/{game['away_team']}-{game['home_team']}"
            if identity in featured_cache[key]:
                result['publicly_featured_expert'] += 1
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        result['errors'].append('archive_read_or_validation_failed')
    response = jsonify(result)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.get('/weekly/preview')
def weekly_preview():
    """Preview currently available weekly content without freezing a draft."""
    require_owner()
    from newsletter_draft import build_draft, period_key
    now = datetime.now(timezone.utc)
    sections, _metadata = build_draft(
        Path(current_app.root_path), now, frequency='weekly'
    )
    issue = {
        'subject': newsletter_subject('weekly', period_key('weekly', now)),
        'frequency': 'weekly'
    }
    return render_template(
        'newsletter_email.html', issue=issue, sections=sections,
        headings=SECTIONS,
        unsubscribe_url=url_for('newsletter.manage'),
        origin=current_app.config['PUBLIC_ORIGIN'],
        address=current_app.config['NEWSLETTER_ADDRESS']
                or 'Mailing address will appear here'
    )


@bp.get('/monthly/preview')
def monthly_preview():
    """Owner-only look at newly generated monthly content; does not save/send."""
    require_owner()
    from newsletter_draft import build_draft, period_key
    now = datetime.now(timezone.utc)
    sections, metadata = build_draft(Path(current_app.root_path), now, frequency='monthly')
    month = datetime.strptime(period_key('monthly', now), '%Y-%m').strftime('%B %Y')
    issue = {'subject': f'The Monthly Plug · {month}', 'frequency': 'monthly'}
    return render_template('newsletter_email.html', issue=issue, sections=sections,
        headings=headings_for_issue(issue), unsubscribe_url=url_for('newsletter.manage'),
        origin=current_app.config['PUBLIC_ORIGIN'],
        address=current_app.config['NEWSLETTER_ADDRESS'] or 'Mailing address will appear here')


@bp.get('/premium/preview')
def premium_preview():
    """Owner-only full-slate preview. Never creates an email issue or recipients."""
    require_owner()
    from newsletter_draft import build_premium_preview, period_key
    now = datetime.now(timezone.utc)
    sections, metadata = build_premium_preview(Path(current_app.root_path), now)
    issue = {'subject': "The Weekly Plug · Premium Preview",
             'frequency': 'weekly'}
    return render_template('newsletter_email.html', issue=issue, sections=sections,
        headings=SECTIONS, unsubscribe_url=url_for('newsletter.manage'),
        origin=current_app.config['PUBLIC_ORIGIN'],
        address=current_app.config['NEWSLETTER_ADDRESS'] or 'Mailing address will appear here')


@bp.get('/issues/<int:issue_id>/preview')
def preview(issue_id):
    require_owner()
    issue=get_issue(issue_id)
    # Preview footer links stay on the owner's preview; no live unsubscribe token.
    return render_template('newsletter_email.html', issue=issue,sections=json.loads(issue['sections']),headings=headings_for_issue(issue),
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
            for member in connection.execute('SELECT id,email FROM members WHERE newsletter_opt_in=1 AND newsletter_frequency IN (?,?)',(issue['frequency'],'weekly')).fetchall():
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
        if not member or not member['newsletter_opt_in'] or member['newsletter_frequency'] not in (issue['frequency'], 'weekly') or json.loads(current['payload'])['to'] != [member['email']]:
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

def newsletter_subject(frequency, period):
    if frequency == "monthly":
        month = datetime.strptime(period, "%Y-%m")
        return f"The Monthly Plug · {month.strftime('%B %Y')}"

    year, week = period.split("-W")
    start = datetime.fromisocalendar(int(year), int(week), 1)
    end = start + timedelta(days=6)

    if start.month == end.month:
        dates = f"{start.strftime('%B')} {start.day}–{end.day}, {end.year}"
    else:
        dates = (
            f"{start.strftime('%b')} {start.day} – "
            f"{end.strftime('%b')} {end.day}, {end.year}"
        )

    return f"The Weekly Plug · {dates}"

def wednesday_draft_due(now):
    """Wednesday at or after 9 AM America/New_York."""
    from zoneinfo import ZoneInfo
    if now.tzinfo is None:
        raise ValueError("An aware timestamp is required")
    eastern = now.astimezone(ZoneInfo("America/New_York"))
    return eastern.weekday() == 2 and eastern.hour >= 9


def prepare_wednesday_draft(application, now=None):
    """Create at most one weekly draft. Never approve or send email."""
    from newsletter_draft import period_key
    now = now or datetime.now(timezone.utc)
    if not wednesday_draft_due(now):
        return "not_due"
    if not application.config.get("NEWSLETTER_AUTO_DRAFT_ENABLED", True):
        return "not_due"
    with application.app_context():
        owner = db().execute(
            "SELECT member_id FROM site_owners ORDER BY member_id LIMIT 1"
        ).fetchone()
        if not owner:
            raise RuntimeError("No site owner configured for newsletter drafts")
        period = period_key("weekly", now)
        existing = db().execute(
            "SELECT issue_id FROM newsletter_generated "
            "WHERE frequency=? AND period=?",
            ("weekly", period)
        ).fetchone()
        if existing:
            return "not_due"
        return generate_draft(owner["member_id"], frequency="weekly", now=now)



def completed_month_draft_due(now):
    """9AM ET on day one; retry through day seven after month end."""
    from zoneinfo import ZoneInfo
    if now.tzinfo is None:
        raise ValueError('An aware timestamp is required')
    eastern = now.astimezone(ZoneInfo('America/New_York'))
    return (eastern.day <= 7 and
            (eastern.day > 1 or eastern.hour >= 9))


def prepare_completed_month_draft(application, now=None, *, scheduled=True):
    """Prepare previous calendar month's verified recap, never send email."""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(timezone.utc)
    if scheduled and (not completed_month_draft_due(now) or not application.config.get('NEWSLETTER_AUTO_DRAFT_ENABLED', True)):
        return 'not_due'
    eastern = now.astimezone(ZoneInfo('America/New_York'))
    if eastern.day == 1 and eastern.hour < 9:
        return 'not_due'
    completed = eastern.date().replace(day=1) - timedelta(days=1)
    period = completed.strftime('%Y-%m')
    with application.app_context():
        if not db().execute("SELECT 1 FROM members WHERE newsletter_opt_in=1 AND newsletter_frequency IN ('weekly','monthly') LIMIT 1").fetchone():
            return 'not_due'
        existing = db().execute("SELECT issue_id FROM newsletter_generated WHERE frequency='monthly' AND period=?", (period,)).fetchone()
        if existing:
            return 'not_due' if scheduled else existing['issue_id']
        owner = db().execute('SELECT member_id FROM site_owners ORDER BY member_id LIMIT 1').fetchone()
        if not owner:
            raise RuntimeError('No site owner configured for newsletter drafts')
        return generate_draft(owner['member_id'], frequency='monthly',
                              now=now, report_period=period)

def generate_draft(owner_id, frequency='weekly', now=None, root=None, *, report_period=None):
    from newsletter_draft import period_key, build_draft
    if frequency not in ('weekly','monthly'):
        raise ValueError('Invalid newsletter frequency')
    now=now or datetime.now(timezone.utc)
    if frequency == 'monthly':
        if (not report_period or report_period >= period_key('monthly', now)
                or datetime.strptime(report_period, '%Y-%m').strftime('%Y-%m') != report_period):
            raise ValueError('Monthly saved drafts require a completed prior month.')
    elif report_period is not None:
        raise ValueError('Weekly drafts cannot specify a report month.')
    period=report_period or period_key(frequency,now)
    existing=db().execute('SELECT issue_id,metadata FROM newsletter_generated WHERE frequency=? AND period=?',(frequency,period)).fetchone()
    # A generated issue is a historical snapshot.  Never silently replace its
    # content on a later page view or CLI run: the games may have finished,
    # and build_draft() only selects upcoming published picks.
    if existing:
        return existing['issue_id']
    extra = {'report_month': report_period} if report_period else {}
    sections,metadata=build_draft(root or Path(current_app.root_path),now,
                                  frequency=frequency, **extra)
    subject=newsletter_subject(frequency, period)
    metadata.update(original_sections=sections,original_subject=subject)
    connection=db();connection.execute('BEGIN IMMEDIATE')
    try:
        existing=connection.execute('SELECT issue_id FROM newsletter_generated WHERE frequency=? AND period=?',(frequency,period)).fetchone()
        if existing:
            connection.rollback();return existing['issue_id']
        issue_id=connection.execute('INSERT INTO newsletter_issues(subject,frequency,sections,owner_id) VALUES(?,?,?,?)',
            (subject,frequency,json.dumps(sections),owner_id)).lastrowid
        connection.execute('INSERT INTO newsletter_generated VALUES(?,?,?,?)',(frequency,period,issue_id,json.dumps(metadata)))
        connection.commit();return issue_id
    except Exception:
        connection.rollback();raise

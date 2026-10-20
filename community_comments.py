"""Public-read, member-write discussion board. Does not load Scout or alter game data."""
import secrets
import time

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from membership import db

bp = Blueprint('community', __name__, url_prefix='/community')
# Retain legacy topic values so pre-existing comments remain readable.
# The public UI is now one conversation; all new posts use 'general'.
TOPICS = {'general': 'General Football', 'picks': 'Picks & Games', 'trends': 'Trends & Research'}
PAGE_SIZE = 20
MAX_BODY = 600
WINDOW_SECONDS = 15 * 60
MAX_POSTS_IN_WINDOW = 4


def init_community(app):
    """Add only new tables to the EXISTING persistent membership SQLite database."""
    with app.app_context():
        with db():
            db().execute('''CREATE TABLE IF NOT EXISTS community_comments (
                id INTEGER PRIMARY KEY,
                member_id INTEGER NOT NULL REFERENCES members(id),
                topic TEXT NOT NULL CHECK(topic IN ('general','picks','trends')),
                body TEXT NOT NULL,
                is_hidden INTEGER NOT NULL DEFAULT 0 CHECK(is_hidden IN (0,1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at_epoch INTEGER NOT NULL
            )''')
            db().execute('''CREATE INDEX IF NOT EXISTS community_comments_topic_idx
                            ON community_comments(topic, is_hidden, id DESC)''')
            db().execute('''CREATE INDEX IF NOT EXISTS community_comments_rate_idx
                            ON community_comments(member_id, created_at_epoch)''')
            db().execute('''CREATE TABLE IF NOT EXISTS community_reports (
                comment_id INTEGER NOT NULL REFERENCES community_comments(id),
                member_id INTEGER NOT NULL REFERENCES members(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(comment_id, member_id)
            )''')
    app.register_blueprint(bp)


@bp.before_request
def protect_posts():
    if request.method != 'POST':
        return
    if request.content_length is not None and request.content_length > 8192:
        abort(413)
    expected = session.get('_csrf')
    supplied = request.form.get('csrf_token', '')
    if not expected or not secrets.compare_digest(expected, supplied):
        # Reject the write without an unhelpful generic 400 page.
        flash('Comment not posted: your session expired. Refresh the page, then sign in again if needed.', 'error')
        return back('composer')


@bp.after_request
def no_cache_for_member_content(response):
    # Comment forms and moderation controls depend on the current session.
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def member_required():
    if g.member is None:
        abort(403, description='Please sign in to participate.')


def owner_required():
    if not g.is_owner:
        abort(403)


def back(anchor='discussion', *, return_to='', posted=False):
    # Only the documented moderation destination is accepted; never redirect to user URLs.
    endpoint = 'community.reports' if return_to == 'reports' and g.is_owner else 'community.discussion'
    return redirect(url_for(endpoint, posted='1' if posted else None) + '#' + anchor, code=303)


@bp.get('')
def discussion():
    # Existing shared links are preserved; the owner queue now has a distinct URL.
    topic = request.args.get('topic', 'all')
    if topic not in ('all', *TOPICS):
        abort(400)
    review = request.args.get('review', '')
    if review:
        if review != 'reported' or not g.is_owner:
            abort(403)
        return redirect(url_for('community.reports'), code=302)
    return show_feed()


@bp.get('/reports')
def reports():
    owner_required()
    return show_feed(review='reported')


def show_feed(review=''):
    try:
        page = int(request.args.get('page', '1'))
    except (ValueError, TypeError):
        abort(400)
    if page < 1 or page > 100_000:
        abort(400)
    if review and not g.is_owner:
        abort(403)

    conditions = []
    if not g.is_owner:
        conditions.append('c.is_hidden = 0')
    if review == 'reported':
        conditions.append('EXISTS (SELECT 1 FROM community_reports r WHERE r.comment_id = c.id)')
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    total = db().execute('SELECT COUNT(*) FROM community_comments c' + where).fetchone()[0]
    reported_total = db().execute('''SELECT COUNT(*) FROM community_comments c
                    WHERE EXISTS(SELECT 1 FROM community_reports r WHERE r.comment_id=c.id)''').fetchone()[0] if g.is_owner else 0
    max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > max_page:
        abort(404)
    posts = db().execute('''SELECT c.id, c.member_id, c.body, c.is_hidden, c.created_at,
             (SELECT COUNT(*) FROM community_reports r WHERE r.comment_id=c.id) AS reports
             FROM community_comments c''' + where + ''' ORDER BY c.id DESC LIMIT ? OFFSET ?''',
             (PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
    return render_template('community.html', posts=posts, page=page, pages=max_page,
                           review=review, reported_total=reported_total, total=total, max_body=MAX_BODY)


@bp.post('/post')
def post():
    member_required()
    body = request.form.get('body', '').strip()
    # One conversation: don't require a topic selector or allow cross-topic posts.
    if not body or len(body) > MAX_BODY or body.count('\n') > 12:
        flash('Write a comment (up to 600 characters and 12 line breaks).', 'error')
        return back('composer')

    # Atomic limit protects the board across Gunicorn workers.
    connection = db()
    connection.execute('BEGIN IMMEDIATE')
    try:
        recent = connection.execute('''SELECT COUNT(*) FROM community_comments
                        WHERE member_id=? AND created_at_epoch > ?''',
                        (g.member['id'], int(time.time()) - WINDOW_SECONDS)).fetchone()[0]
        if recent >= MAX_POSTS_IN_WINDOW:
            connection.rollback()
            flash('Post limit reached. Please try again in 15 minutes.', 'error')
            return back('composer')
        connection.execute('INSERT INTO community_comments(member_id,topic,body,created_at_epoch) VALUES(?,?,?,?)',
                           (g.member['id'], 'general', body, int(time.time())))
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return back(posted=True)


@bp.post('/<int:comment_id>/report')
def report(comment_id):
    member_required()
    post = db().execute('SELECT member_id, is_hidden FROM community_comments WHERE id=?', (comment_id,)).fetchone()
    if post is None or post['is_hidden']:
        abort(404)
    if post['member_id'] == g.member['id']:
        abort(400, description='You cannot report your own post.')
    with db():
        db().execute('INSERT OR IGNORE INTO community_reports(comment_id,member_id) VALUES(?,?)',
                     (comment_id, g.member['id']))
    return back()


@bp.post('/<int:comment_id>/<action>')
def moderate(comment_id, action):
    owner_required()
    if action not in ('hide', 'restore'):
        abort(404)
    with db():
        result = db().execute('UPDATE community_comments SET is_hidden=? WHERE id=?',
                              (1 if action == 'hide' else 0, comment_id))
    if result.rowcount == 0:
        abort(404)
    return back(return_to=request.form.get('return_to', ''))

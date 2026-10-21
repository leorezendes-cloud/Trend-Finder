"""Public-read, member-write discussion board. Does not load Scout or alter game data."""
import secrets
import time

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from membership import db

bp = Blueprint('community', __name__, url_prefix='/community')

# Huddle member identity presets, v1: no uploads, no personal information shown.
import re
import sqlite3

# key -> (emoji, accessible label). Symbols do not use official league/team marks.
AVATARS = {
    'football': ('🏈', 'Football'),
    'trophy': ('🏆', 'Trophy'),
    'shield': ('🛡️', 'Shield'),
    'bolt': ('⚡', 'Lightning'),
    'fire': ('🔥', 'Fire'),
    'star': ('⭐', 'Star'),
    'target': ('🎯', 'Target'),
    'crown': ('👑', 'Crown'),
    'tf_mascot': ('', 'TF Mascot'),
    'tf_retro': ('', 'TF Retro'),
    'tf_graffiti': ('', 'TF Graffiti'),
}


def public_identity(member_id=None):
    if member_id is None:
        if g.get('member') is None:
            return {'display_name': None, 'avatar_key': None}
        member_id = g.member['id']
    row = db().execute('SELECT display_name, avatar_key FROM community_profiles WHERE member_id=?',
                       (member_id,)).fetchone()
    return dict(row) if row else {'display_name': None, 'avatar_key': None}


def validate_nickname(raw):
    # A blank nickname explicitly restores the site's original Fan #N label.
    value = ' '.join(raw.strip().split())
    if not value:
        return None
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]{1,22}[A-Za-z0-9]', value):
        raise ValueError('Nickname must be 3–24 characters: letters, numbers, spaces, _ or -.')
    if not re.search(r'[A-Za-z]', value):
        raise ValueError('Nickname must include a letter.')
    lowered = value.lower().replace(' ', '').replace('_','').replace('-','')
    if lowered in {'admin','administrator','moderator','mod','staff','owner','support',
                   'trendfindah','trendfindah3000','official','scout'}:
        raise ValueError('That nickname is reserved. Please choose another.')
    return value


@bp.post('/identity')
def save_identity():
    member_required()
    try:
        nickname = validate_nickname(request.form.get('display_name', ''))
    except ValueError as exc:
        flash(str(exc), 'identity')
        return redirect(url_for('membership.preferences') + '#community-identity', 303)
    avatar = request.form.get('avatar', 'football')
    if avatar not in AVATARS and avatar != 'custom':
        abort(400, description='Choose one of the available avatars.')
    if avatar == 'custom' and db().execute('SELECT 1 FROM community_profile_images WHERE member_id=?', (g.member['id'],)).fetchone() is None:
        abort(400, description='Upload your photo first.')
    try:
        with db():
            db().execute("""INSERT INTO community_profiles(member_id,display_name,avatar_key)
                VALUES(?,?,?) ON CONFLICT(member_id) DO UPDATE SET
                display_name=excluded.display_name, avatar_key=excluded.avatar_key""",
                (g.member['id'], nickname, avatar))
            if avatar != 'custom':
                db().execute('DELETE FROM community_profile_images WHERE member_id=?', (g.member['id'],))
    except sqlite3.IntegrityError:
        flash('That nickname is already taken. Please choose another.', 'identity')
        return redirect(url_for('membership.preferences') + '#community-identity', 303)
    flash('Community profile updated.', 'identity')
    return redirect(url_for('membership.preferences') + '#community-identity', 303)


# Huddle image avatars v2: three local branding images, and re-encoded private-member uploads.
from io import BytesIO
from flask import send_file

LOGO_AVATAR_PATHS = {
    'tf_mascot': 'Images/Branding/trend_findah_crops_and_headers/icon_tf_mascot.png',
    'tf_retro': 'Images/Branding/trend_findah_crops_and_headers/icon_tf_retro.png',
    'tf_graffiti': 'Images/Branding/trend_findah_crops_and_headers/icon_tf_graffiti.png',
}
MAX_PHOTO_BYTES = 1_000_000  # Input; prevents multi-megabyte uploads.
MAX_PHOTO_PIXELS = 6_000_000 # Decode; mitigates decompression bombs.


def prepare_avatar_photo(source):
    '''Return small, metadata-free 160x160 JPEG; never serve the submitted file verbatim.'''
    from PIL import Image, ImageOps, UnidentifiedImageError
    raw = source.read(MAX_PHOTO_BYTES + 1)
    if not raw:
        abort(400, description='Choose an image first.')
    if len(raw) > MAX_PHOTO_BYTES:
        abort(413, description='Image must be smaller than 1 MB.')
    try:
        with Image.open(BytesIO(raw)) as loaded:
            if loaded.format not in ('JPEG', 'PNG', 'WEBP'):
                abort(400, description='Use JPG, PNG, or WebP.')
            if getattr(loaded, 'is_animated', False) or getattr(loaded, 'n_frames', 1) > 1:
                abort(400, description='Animated images are not supported.')
            if loaded.width * loaded.height > MAX_PHOTO_PIXELS:
                abort(413, description='Image dimensions are too large.')
            loaded.load()
            rotated = ImageOps.exif_transpose(loaded)
            if 'A' in rotated.getbands() or 'transparency' in rotated.info:
                rgba = rotated.convert('RGBA')
                photo = Image.new('RGB', rotated.size, (18, 27, 42))
                photo.paste(rgba, mask=rgba.getchannel('A'))
            else:
                photo = rotated.convert('RGB')
            photo = ImageOps.fit(photo, (160, 160), method=Image.Resampling.LANCZOS)
            output = BytesIO()
            photo.save(output, format='JPEG', quality=82, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        abort(400, description='The selected image could not be processed.')
    jpeg = output.getvalue()
    if len(jpeg) > 100_000:
        abort(413, description='The image could not be reduced enough.')
    return jpeg


@bp.post('/identity/photo')
def upload_identity_photo():
    member_required()
    selected = request.files.get('photo')
    if selected is None:
        abort(400, description='Select an image to upload.')
    jpeg = prepare_avatar_photo(selected.stream)
    # A single short transaction replaces the prior photo and activates it.
    with db():
        db().execute('''INSERT INTO community_profile_images(member_id, jpeg)
                        VALUES(?,?) ON CONFLICT(member_id) DO UPDATE SET jpeg=excluded.jpeg''',
                     (g.member['id'], jpeg))
        db().execute('''INSERT INTO community_profiles(member_id, display_name, avatar_key)
                        VALUES(?,NULL,'custom') ON CONFLICT(member_id) DO UPDATE SET avatar_key='custom' ''',
                     (g.member['id'],))
    flash('Your photo is now your Huddle avatar.', 'identity')
    return redirect(url_for('membership.preferences') + '#community-identity', 303)


@bp.get('/avatar/<int:member_id>.jpg')
def avatar_image(member_id):
    row = db().execute('''SELECT i.jpeg FROM community_profile_images i
         JOIN community_profiles p ON p.member_id=i.member_id
         WHERE i.member_id=? AND p.avatar_key='custom' ''', (member_id,)).fetchone()
    if row is None:
        abort(404)
    response = send_file(BytesIO(row['jpeg']), mimetype='image/jpeg', download_name='avatar.jpg',
                         etag=False, conditional=False)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@bp.post('/avatar/<int:member_id>/remove')
def moderate_avatar(member_id):
    # Existing Huddle owner can remove inappropriate member photos.
    owner_required()
    with db():
        db().execute('DELETE FROM community_profile_images WHERE member_id=?', (member_id,))
        db().execute("UPDATE community_profiles SET avatar_key='football' WHERE member_id=? AND avatar_key='custom'", (member_id,))
    return back()

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
            # Optional public identities for existing member IDs. No alteration of members or picks.
            db().execute('''CREATE TABLE IF NOT EXISTS community_profiles (
                member_id INTEGER PRIMARY KEY REFERENCES members(id),
                display_name TEXT COLLATE NOCASE,
                avatar_key TEXT NOT NULL DEFAULT 'football'
            )''')
            db().execute('''CREATE UNIQUE INDEX IF NOT EXISTS community_profiles_name_unique
                          ON community_profiles(display_name COLLATE NOCASE)
                          WHERE display_name IS NOT NULL''')
            # Sanitized JPEG avatar bytes live in the same persistent membership database.
            db().execute('''CREATE TABLE IF NOT EXISTS community_profile_images (
                member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
                jpeg BLOB NOT NULL CHECK(length(jpeg) <= 100000)
            )''')
    app.jinja_env.globals['public_identity'] = public_identity
    app.jinja_env.globals['community_avatars'] = AVATARS
    app.jinja_env.globals['community_logo_paths'] = LOGO_AVATAR_PATHS
    app.register_blueprint(bp)


@bp.before_request
def protect_posts():
    if request.method != 'POST':
        return
    limit = 1_500_000 if request.endpoint == 'community.upload_identity_photo' else 8192
    request.max_content_length = limit
    if request.content_length is not None and request.content_length > limit:
        abort(413)
    expected = session.get('_csrf')
    supplied = request.form.get('csrf_token', '')
    if not expected or not secrets.compare_digest(expected, supplied):
        if request.endpoint in ('community.save_identity', 'community.upload_identity_photo'):
            abort(400, description='Invalid CSRF token.')
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
    posts = db().execute('''SELECT c.id, c.member_id, c.body, c.is_hidden, c.created_at, p.display_name, p.avatar_key,
             (SELECT COUNT(*) FROM community_reports r WHERE r.comment_id=c.id) AS reports
             FROM community_comments c LEFT JOIN community_profiles p ON p.member_id=c.member_id''' + where + ''' ORDER BY c.id DESC LIMIT ? OFFSET ?''',
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

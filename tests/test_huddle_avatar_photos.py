"""Isolated Huddle logo/photo avatar tests; no live server, network or Scout.
Run: .venv/bin/python -m unittest discover -s tests -p 'test_huddle_avatar_photos.py' -v
"""
import io
import unittest
from PIL import Image
from test_huddle_identity import HuddleIdentityTests
from membership import db


class HuddleAvatarPhotoTests(HuddleIdentityTests):
    """Reuse established temporary Flask/membership fixture; all tests use test SQLite."""

    def png(self, size=(200, 300)):
        stream = io.BytesIO()
        Image.new('RGB', size, (255, 10, 100)).save(stream, format='PNG')
        stream.seek(0)
        return stream

    def upload(self, image=None, csrf='test-csrf'):
        return self.client.post('/community/identity/photo',
                                data={'csrf_token': csrf,
                                      'photo': (image or self.png(), 'image.png')},
                                content_type='multipart/form-data')

    def test_three_logos_render_in_profile_and_existing_posts(self):
        self.login(1)
        page=self.client.get('/members/preferences').get_data(as_text=True)
        for logo in ('tf_mascot','tf_retro','tf_graffiti'):
            self.assertIn(f'value="{logo}"', page)
            self.assertIn(f'icon_{logo}.png', page)
        self.assertEqual(self.post('Hello logos').status_code,303)
        self.assertEqual(self.identity('PatsFan','tf_retro').status_code,303)
        feed=self.client.get('/community').get_data(as_text=True)
        self.assertIn('icon_tf_retro.png',feed)
        self.assertIn('Hello logos',feed)
        self.assertIn('PatsFan',feed)

    def test_upload_reencodes_small_private_image_and_displays_it(self):
        self.login(1)
        self.assertEqual(self.post('Avatar test').status_code,303)
        response=self.upload()
        self.assertEqual(response.status_code,303)
        with self.app.app_context():
            row=db().execute('SELECT jpeg FROM community_profile_images WHERE member_id=1').fetchone()
            self.assertTrue(row['jpeg'].startswith(b'\xff\xd8\xff'))
            self.assertLess(len(row['jpeg']),100000)
            avatar=db().execute('SELECT avatar_key FROM community_profiles WHERE member_id=1').fetchone()
            self.assertEqual(avatar['avatar_key'],'custom')
        image=self.client.get('/community/avatar/1.jpg')
        self.assertEqual(image.status_code,200)
        self.assertEqual(image.mimetype,'image/jpeg')
        self.assertEqual(image.headers['X-Content-Type-Options'],'nosniff')
        with Image.open(io.BytesIO(image.data)) as photo:
            self.assertEqual(photo.size,(160,160))
            self.assertFalse(photo.getexif())
        feed=self.client.get('/community').get_data(as_text=True)
        self.assertIn('/community/avatar/1.jpg',feed)
        profile=self.client.get('/members/preferences').get_data(as_text=True)
        self.assertIn('My photo',profile)
        self.assertIn('name="avatar" value="custom" checked',profile)

    def test_switching_back_to_logo_deletes_old_upload(self):
        self.login(1)
        self.assertEqual(self.upload().status_code,303)
        self.assertEqual(self.identity('Touchdown','tf_mascot').status_code,303)
        self.assertEqual(self.client.get('/community/avatar/1.jpg').status_code,404)
        with self.app.app_context():
            self.assertIsNone(db().execute('SELECT 1 FROM community_profile_images WHERE member_id=1').fetchone())
        self.assertEqual(self.identity('Touchdown','custom').status_code,400)

    def test_upload_rejects_wrong_csrf_and_non_images(self):
        self.login(1)
        self.assertEqual(self.upload(csrf='wrong').status_code,400)
        self.assertEqual(self.upload(io.BytesIO(b'<svg onload="alert(1)"></svg>')).status_code,400)
        self.assertEqual(self.upload(io.BytesIO(b'not a real jpeg')).status_code,400)
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM community_profile_images').fetchone()[0],0)

    def test_upload_blocks_bomb_and_oversized_input(self):
        self.login(1)
        self.assertEqual(self.upload(self.png((3000,3000))).status_code,413)
        self.assertEqual(self.upload(io.BytesIO(b'X'*1_100_000)).status_code,413)
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM community_profile_images').fetchone()[0],0)


if __name__=='__main__':
    unittest.main()

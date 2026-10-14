import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from site_health import owner_health
from app import app

class SiteHealthTests(unittest.TestCase):
    def test_missing_failed_and_old_checks_need_attention(self):
        now=datetime(2030,10,16,12,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);database=root/'members.sqlite3'
            self.assertFalse(any(item['ok'] for item in owner_health(root,database,now)))
            (root/'account-backups').mkdir();(root/'logs').mkdir()
            (root/'account-backups/status.json').write_text(json.dumps({'restore_verified':True,'completed_at':now.isoformat()}))
            (root/'logs/auto_update_status.json').write_text(json.dumps({'state':'ok','finished':now.isoformat()}))
            self.assertTrue(all(item['ok'] for item in owner_health(root,database,now)))
            self.assertFalse(any(item['ok'] for item in owner_health(root,database,now+timedelta(days=2))))
            (root/'account-backups/status.json').write_text('invalid')
            self.assertFalse(owner_health(root,database,now)[0]['ok'])

    def test_methodology_is_public_indexable_and_brand_only(self):
        response=app.test_client().get('/about')
        self.assertEqual(response.status_code,200)
        self.assertIn('About Gravy Train',response.text)
        self.assertNotIn('leorezendes',response.text.lower())
        self.assertNotIn('Leo Rezendes',response.text)
        self.assertIn('Plug Total',response.text)
        self.assertIn('index, follow',response.text)
        self.assertIn('https://trendfindah.com/about',app.test_client().get('/sitemap.xml').text)

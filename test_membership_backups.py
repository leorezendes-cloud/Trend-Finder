import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from membership import init_membership, db
from membership_backups import backup_database, verify_restore


class MembershipBackupTests(unittest.TestCase):
    def test_backup_restore_private_permissions_and_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);database=root/'members.sqlite3';folder=root/'account-backups'
            with patch.dict('os.environ', {'TREND_FINDAH_DATABASE':str(database),'TREND_FINDAH_SECRET_KEY':'test-secret'}):
                app=Flask(__name__,instance_path=str(root))
                init_membership(app)
            with app.app_context():
                with db():
                    db().execute("INSERT INTO members(email,password_hash,newsletter_opt_in) VALUES('test@example.com','test-hash',1)")
                    db().execute("INSERT INTO watchlist(member_id,kind,target,title) VALUES(1,'team','/scout4/teams?team=BUF','BUF')")
                    db().execute("INSERT INTO feedback(category,page,message) VALUES('Problem','/sunday','Example beta feedback')")
                with db():
                    db().execute("INSERT INTO pick_weeks(season,week,owner_id,published_at) VALUES(2030,6,1,'2030-10-16T12:00:00+00:00')")
                    db().execute("INSERT INTO pick_games(week_id,game_id,away,home,kickoff_at,lock_at,away_spread,total,line_source) VALUES(1,'g','A','B','2030-10-20T17:00:00+00:00','2030-10-20T17:00:00+00:00',3,44,'test quote')")
                    db().execute("INSERT INTO member_picks(member_id,game_id,su,ats,ou,updated_at) VALUES(1,1,'A','B','Under','2030-10-16T12:00:00+00:00')")
                # Keep the live connection open to exercise SQLite's consistent backup API.
                backup_database(database,folder,keep=2)
            snapshots=list(folder.glob('accounts-*.sqlite3'))
            self.assertEqual(verify_restore(snapshots[0])['members'],1)
            self.assertEqual(verify_restore(snapshots[0])['member_picks'],1)
            self.assertEqual(verify_restore(snapshots[0])['pick_games'],1)
            self.assertIn('newsletter_issues',verify_restore(snapshots[0]))
            self.assertEqual(verify_restore(snapshots[0])['watchlist'],1)
            self.assertEqual(verify_restore(snapshots[0])['feedback'],1)
            self.assertEqual(snapshots[0].stat().st_mode & 0o777,0o600)
            self.assertEqual(folder.stat().st_mode & 0o777,0o700)
            backup_database(database,folder,keep=2);backup_database(database,folder,keep=2)
            self.assertEqual(len(list(folder.glob('accounts-*.sqlite3'))),2)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM members').fetchone()[0],1)
            result=app.test_cli_runner().invoke(args=['membership-backup-status'])
            self.assertIn('Restore verified: yes',result.output)
            self.assertNotIn('test@example.com',result.output)

    def test_failed_backup_retains_previous_valid_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'backups';folder.mkdir()
            previous=folder/'accounts-previous.sqlite3';previous.write_bytes(b'previous')
            broken=root/'broken.sqlite3';broken.write_bytes(b'not a database')
            with self.assertRaises(sqlite3.DatabaseError):backup_database(broken,folder)
            self.assertEqual(previous.read_bytes(),b'previous')
            self.assertEqual(list(folder.glob('*.tmp')),[])


if __name__=='__main__':unittest.main()

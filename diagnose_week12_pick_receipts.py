"""Read-only diagnostic for Week 12 public Scout and Plug receipt gaps."""
from datetime import datetime, timezone
from pathlib import Path
import os

from plug_dashboard import load_schedule
from scout4.shadow import kickoff
from scout_dynamic_public import state
from plug_dynamic_official import official_state, activation as plug_activation
from plug_dynamic_cards import card_state
from plug_ats_v5_weekly import read_week, SCOUT_POLICY
from plug_ou_weekly_v3 import read_effective

TEAMS = {'LV', 'TEN', 'WAS', 'NE'}
ROOT = Path(__file__).resolve().parent


def main():
    now = datetime.now(timezone.utc)
    print('UTC:', now.isoformat(), 'DATA ROOT:', ROOT)
    print('FLAGS:', {k: os.getenv(k) for k in ('TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC', 'TREND_FINDAH_DYNAMIC_OFFICIAL')})
    try:
        receipt = read_week(2026, 12, policy=SCOUT_POLICY)
        ats_rows = {r['game_id']: r for r in receipt['games']} if receipt else {}
        print('WEEKLY ATS RECEIPTS:', len(ats_rows))
    except Exception as exc:
        ats_rows = {}
        print('WEEKLY ATS ERROR:', type(exc).__name__, str(exc))
    try:
        print('DYNAMIC ACTIVATION:', plug_activation(ROOT))
    except Exception as exc:
        print('DYNAMIC ACTIVATION ERROR:', type(exc).__name__, str(exc))
    for game in load_schedule():
        if str(game.get('season')) != '2026' or str(game.get('week')) != '12':
            continue
        if not TEAMS.intersection((game['away_team'], game['home_team'])):
            continue
        gid = game['game_id']
        stamp = kickoff(game).isoformat()
        identity = dict(game_id=gid, away_team=game['away_team'], home_team=game['home_team'], kickoff_utc=stamp)
        print('\\nGAME:', gid, 'KICKOFF:', stamp)
        row = ats_rows.get(gid)
        print('WEEKLY ATS:', {k: row.get(k) for k in ('selected', 'side', 'away_line')} if row else 'MISSING')
        for label, fn in (
            ('SCOUT', lambda: state(ROOT, identity, now=now)),
            ('DYNAMIC OFFICIAL', lambda: official_state(ROOT, gid, as_of_utc=now.isoformat())),
            ('DYNAMIC CARD', lambda: card_state(ROOT, gid, as_of_utc=now.isoformat(), away_team=identity['away_team'], home_team=identity['home_team'], kickoff_utc=stamp)),
            ('PLUG O/U', lambda: read_effective(ROOT, gid)),
        ):
            try:
                value = fn()
                if label == 'SCOUT':
                    result = {'status': value.get('status'), 'ats_side': value.get('row', {}).get('ats_side')} if value else None
                elif label == 'DYNAMIC OFFICIAL':
                    result = {k: value.get(k) for k in ('ats_selected', 'ats_side', 'ou_selected', 'ou_side')} if value else None
                elif label == 'DYNAMIC CARD':
                    result = {k: value.get(k) for k in ('status', 'ats', 'ou')} if value else None
                else:
                    result = {k: value.get(k) for k in ('selected', 'side', 'market_total', 'selection_status')} if value else None
                print(label + ':', result)
            except Exception as exc:
                print(label + ' ERROR:', type(exc).__name__, str(exc))
        for base in ('scout_dynamic', 'plug_dynamic_official', 'plug_dynamic_journal'):
            folder = ROOT / base / gid
            file = ROOT / base / (gid + '.json')
            print(base + ' FILES:', sorted(p.name for p in folder.glob('*.json'))[:8] if folder.is_dir() else ('single JSON exists' if file.is_file() else 'none'))


if __name__ == '__main__':
    main()

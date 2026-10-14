# Site week and daily forecasts

The site's current regular-season NFL week changes Wednesday at **8 a.m. America/New_York** (including daylight-saving changes). The saved schedule determines that window's season/week. Homepage scores, upcoming matchups, market, member picks, The Plug, weekly results, upcoming trend previews, Dungeon weekly pages and automatic weekly newsletter drafts share this boundary. Explicit historical week/season selections remain available. Historical manual research filters remain user-selected.

Member sheets still require the owner's preparation and publication at `/picks/admin`. A future sheet can be published early, but member submissions open only when its week becomes current; each game locks at kickoff. `/picks/` defaults to the current published week. There are shortcuts on the homepage, Upcoming Matchups, matchup details, team comparison and market. Manual Trend Finder results can be saved to My Watchlist and reopened with the same filters.

`/market` and Upcoming Matchups read the latest valid saved spread and total for each unstarted game in the current week. Quote identity, kickoff, observation time and line structure must match. These are saved quotes, not streaming odds. Schedule lines are an explicitly labelled fallback; unavailable lines stay unavailable. Original forecast quotes never override the market display or change for grading.

On Render, the existing `TREND_FINDAH_AUTO_UPDATE=1` worker refreshes saved inputs every six hours. After successful finals, statistics, quote and original-prediction stages, it runs a daily forecast review in a separate temporary workspace using the existing model and configuration unchanged. A completed review runs once per Eastern calendar day; pending games allow later retries. Failed upstream updates prevent a misleading review. Opening a page never starts this job.

Daily records and changes are saved under persistent `data/scout4/daily/`. Fourteen daily evidence sets are retained. The Plug displays the latest revision and previous pick/line when a change is observed. Original pre-kickoff records remain untouched and control grading. No research model retraining, historical source edits or newsletter sending is introduced.

Deploy the updated application on Render with its existing persistent disk and production settings. Check `logs/auto_update_status.json` for the `daily forecast review` stage after the next successful automatic update. Missing statistics/quotes remain pending rather than generating fabricated predictions.

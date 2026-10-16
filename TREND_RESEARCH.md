# Trend Finder research views

The default `/trend-finder` view researches completed NFL games across teams, favorites, underdogs and totals. Each matchup is counted once. Separate home, away, favorite and underdog records prevent an artificial combined ATS percentage. A selected team gets its own record first. Pushes and ties are excluded from decision percentages; missing lines are reported separately.

Primetime Dogs remains available as a preset. The general Find combinations button searches up to three pregame features and checks team-side ATS records and totals. It ranks patterns with at least 10 decisions and 55% success using a Wilson lower confidence bound, retains up to 30 cards, and links back to matching games. Identical samples and metric labels are consolidated. The specialty Primetime Dogs view retains the original underdog combination finder. Existing saved searches without a view parameter retain their original underdog interpretation.

## Grouped filters

- 1 p.m. ET window: 13:00 through 13:59.
- 4 p.m. ET window: 16:00 through 16:59.
- Playoffs: WC, DIV, CON, SB and POST game types.
- Temperature: below 32°F, 32 to below 60°F, 60 to below 80°F, or 80°F and above.
- Wind: under 10 mph, 10 to below 20 mph, or 20 mph and above.

Temperature, wind and kickoff dropdowns show presets only. Other fields retain recorded categories. Game ID is not offered as a filter. Missing or nonfinite weather values do not match a weather band. These are historical recorded conditions, not guaranteed pregame forecasts. Rain/snow categories are unavailable in the current dataset. Roof can be selected separately. Score, result and overtime filters describe completed games and must not be interpreted as pregame evidence.

Results use the original stat-card layout, with separate selected-team, home/away, favorite/underdog, and total records. The three original action buttons are restored. Matching games show 100 matchups per page. Searches can be saved with their selected team, role and conditions. This feature does not change the published prediction formula or locked picks.

## Location, spreads and evidence

Team role (favorite/underdog) and Home/Away are independent: Underdog + Home + Primetime researches home primetime underdogs without requiring a named team. With a named team, Home/Away applies to that team. Without a named team or role, location focuses combination discovery on the home or away record; every matchup has both sides.

Spread presets use absolute spread size: pick’em, above zero through 3, above 3 through 7, above 7 through 10, and above 10 points. Missing spreads do not match a selected band. Legacy exact-spread URLs still retain their filter.

Each record and percentage is displayed in its own stat card. Verify games expands within the original combination card and loads a paginated evidence fragment with the same scope and conditions. ATS combinations show the appropriate side’s Cover/Loss/Push for each game. Evidence pagination stays inside that card, preserving the combination list and filters. Saved combination searches open their matching-games section directly.

Result cards begin with Games, Pick’ems, Over and Under, followed by four-card rows for Home team, Away team, Favorites and Dogs: ATS, cover %, straight up and SU %. Named-team cards follow these rows when a team is selected. Inline Verify games previews the newest ten matches only. All games involved opens a dedicated same-tab `/trend-finder/games` page with a charcoal-gray panel, preserved filters, pagination, and a Back to Trend Finder link.

## Current combination discovery

Find combinations uses the newest season in the dataset plus the preceding four seasons (2022–2026 at this release). A narrower selected season/range is honored within that window. The effective window is included in verification and saved-search URLs. A selection entirely outside the window yields no general combinations; the specialty view explains the permitted window. Manual Analyze searches retain the full historical dataset.

General automatic QB, coach, team and referee categories must appear in the newest season's dataset. QB/coach eligibility is based on current-season recorded appearances, not a live roster-status guarantee; backups without recorded appearances may not be suggested. Historical appearances of eligible personnel still contribute within the five-season window. Current-period relevance uses support in the latest two seasons: patterns with at least ten recent matches rank ahead of those without that support, followed by the existing confidence-bound score and sample support. Cards show their recent match count. The specialty scanner retains its current-season context eligibility rule, now within the same five-season history cap.

## Overlapping combinations

General discovery groups same-outcome patterns when their matching-game sets have at least 80% Jaccard overlap (intersection divided by union). Grouping happens before the 30-card display limit. The strongest ranked pattern represents each card, and coach, QB, roof, surface and other similar variations remain nested with their individual records, save controls and ten-game evidence previews. Records are never summed. Every variation is compared with its representative to avoid transitive chains of increasingly different samples. Different outcome labels remain separate.

## Home-page emerging alert

A red-outlined Gravy Train card appears above the account/watchlist button when regular-season home primetime underdogs are undefeated straight up over 3–14 completed games in the upcoming matchup’s season. The card requires an unstarted, non-neutral, matching regular-season game within seven days with a finite saved spread. It says On tonight only on the game’s Eastern calendar date. The record is calculated from completed games that started before the current clock; future filled scores do not count. It updates or hides when its qualification changes, never promises an outcome, and does not modify predictions.


### Manual primetime night filters

Select any combination of weekday night checkboxes, including Thursday, Sunday and Monday Night. Multiple nights match either selected night, so Sunday plus Monday can be analyzed together for Over/Under results. A night kickoff is 7 p.m. Eastern or later. Selecting nights enables Primetime Only; selecting All or Non-Primetime clears the checkboxes. Night selections remain in filter tags, saved trends and game evidence links.

Find Combinations retains qualifying ATS, Over and Under results separately for each filter combination. The bounded results list shares space across the three markets; overlapping variations remain grouped within the same outcome. Totals require at least 10 non-push decisions and 55% success; missing totals are excluded.

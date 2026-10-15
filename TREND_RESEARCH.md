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

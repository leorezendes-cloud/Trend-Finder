# Search setup

SEO lives in `seo.py` and the shared `templates/_seo_head.html` include. It changes the HTML head and search headers only. Page layout, artwork, visible headings, copy, navigation and pick policies are unchanged.

Public landing pages have descriptive NFL titles, unique descriptions, HTTPS canonical URLs, Open Graph and Twitter preview metadata. The homepage identifies Gravy Train (alternate name Trend Findah) with WebSite structured data. Individual matchup pages include full team names, season and week in their metadata. The old `/sunday-scout` URL identifies `/the-plug` as canonical.

URLs use the validated `PUBLIC_ORIGIN` configuration, never incoming Host headers. Private account, pick, owner and recovery pages, unknown utility pages, error responses and query-filter variations receive noindex. Parameter-free public landing pages and matchup pages can be indexed. Canonical links point to curated public paths; filtered research pages are kept out of the sitemap rather than producing thousands of indexable combinations. Existing authentication remains unchanged; noindex is not access control.

`/robots.txt` permits crawling and points to `/sitemap.xml`. The sitemap includes canonical public landing pages and current saved-schedule season regular-season matchup URLs. It excludes accounts, reset tokens, member picks, owner pages, query variants and the duplicate Plug URL. No fabricated last-modified dates or refresh priorities are added. Building a sitemap never runs collectors, model jobs or page analysis.

## Google Search Console: owner action

1. Open Google Search Console with your Google account.
2. Add `trendfindah.com` as a Domain property and complete the DNS verification shown by Google at your domain registrar.
3. Submit `https://trendfindah.com/sitemap.xml` under Sitemaps.
4. Inspect `https://trendfindah.com/`, `/trend-finder` and `/the-plug`, and request indexing if needed.
5. Check Page indexing for errors and Performance for actual search impressions/clicks as Google processes the site.

Verification needs the owner's Google account and domain access; it is not performed by deploying these files. Metadata and sitemap submission help discovery and presentation, but neither guarantees indexing nor a particular ranking. No advertising or tracking scripts are introduced.

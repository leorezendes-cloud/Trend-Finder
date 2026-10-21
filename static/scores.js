(() => {
  const panel = document.getElementById('home-scores');
  if (!panel) return;
  const list = panel.querySelector('.score-grid');
  const note = panel.querySelector('.score-update');
  let refreshSeconds = 60;
  let timer;
  let inFlight = false;

  // Only the server's confirmed, fully-qualified hot-trend matches get a flame.
  // Expected /fans/scores field: hot_matches: [{label, url, confirmed: true}].
  function hotTrendControl(rawMatches) {
    if (!Array.isArray(rawMatches)) return null;
    const seen = new Set();
    const matches = rawMatches.filter(match => {
      if (!match || match.confirmed !== true || typeof match.label !== 'string' ||
          typeof match.url !== 'string' || !match.label.trim() ||
          !match.url.startsWith('/') || match.url.startsWith('//')) return false;
      const key = `${match.url}\n${match.label}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    if (!matches.length) return null;

    const details = document.createElement('details');
    details.className = 'tf-hot-trends';
    const toggle = document.createElement('summary');
    toggle.textContent = '🔥';
    toggle.setAttribute('aria-label', `View ${matches.length} matching hot ${matches.length === 1 ? 'trend' : 'trends'}`);
    toggle.title = `${matches.length} matching hot ${matches.length === 1 ? 'trend' : 'trends'}`;
    const popup = document.createElement('div');
    popup.className = 'tf-hot-trends-panel';
    const title = document.createElement('strong');
    title.textContent = '🔥 Hot Trends';
    const links = document.createElement('ul');
    for (const match of matches) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = match.url;
      link.textContent = match.label;
      item.append(link);
      links.append(item);
    }
    popup.append(title, links);
    details.append(toggle, popup);
    return details;
  }
  async function refresh() {
    if (inFlight) return;
    inFlight = true;
    try {
      const response = await fetch(panel.dataset.url, {cache: 'no-store', signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error('Unavailable');
      const data = await response.json();
      refreshSeconds = data.refresh_seconds === 15 ? 15 : 60;
      list.replaceChildren();
      for (const game of data.games) {
        const card = document.createElement(game.url ? 'a' : 'div');
        card.className = 'score-card';
        if (game.url) card.href = game.url;
        const teams = document.createElement('strong');
        teams.textContent = `${game.away} ${game.away_score ?? ''} · ${game.home} ${game.home_score ?? ''}`;
        const status = document.createElement('span');
        const when = new Date(game.date).toLocaleString([], {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
        status.textContent = game.state === 'pre' ? `${game.status} · ${when}` : game.status;
        const market = game.market;
        const results = document.createElement('span');
        if (market) {
          const signed = market.spread === null ? '—' : `${-market.spread > 0 ? '+' : ''}${-market.spread}`;
          const lines = `${game.home} ${signed} · O/U ${market.total ?? '—'}`;
          if (game.state !== 'pre') status.textContent += ` · ${lines}`;
          if (game.state === 'post') {
            const cover = {W:'Home covered', L:'Away covered', P:'ATS push'}[market.home_ats] ?? 'ATS ungraded';
            const total = {O:'Over', U:'Under', P:'Total push'}[market.ou] ?? 'Total ungraded';
            results.textContent = `${cover} · ${total}`;
          } else results.textContent = game.state === 'pre' ? `Saved: ${lines}` : 'Saved lines · results pending';
        } else results.textContent = 'Saved lines unavailable';
        card.append(teams, status, results);
        const fire = hotTrendControl(game.hot_matches);
        if (fire) {
          // Keep the flame *outside* the matchup link so taps never conflict.
          const wrapper = document.createElement('div');
          wrapper.className = 'tf-score-wrap';
          wrapper.append(card, fire);
          list.append(wrapper);
        } else {
          list.append(card);
        }
      }
      note.textContent = data.updated ? `${data.stale ? 'Updates delayed · last received' : 'ESPN · updated'} ${new Date(data.updated).toLocaleTimeString()} · checks every ${refreshSeconds === 15 ? "15 seconds" : "minute"} · ATS/totals use saved lines` : 'Scores temporarily unavailable. Try again shortly.';
      if (!data.games.length && data.updated && !data.stale) note.textContent = 'No games listed by the score feed right now.';
    } catch (_) {
      note.textContent = 'Score updates unavailable. Any displayed scores may be outdated.';
    } finally {
      inFlight = false;
      clearTimeout(timer);
      timer = setTimeout(() => { if (!document.hidden) refresh(); }, refreshSeconds * 1000);
    }
  }
  // Close open flame menus when the visitor clicks elsewhere.
  document.addEventListener('click', event => {
    document.querySelectorAll('.tf-hot-trends[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.removeAttribute('open');
    });
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) { clearTimeout(timer); refresh(); }
  });
  refresh();
})();

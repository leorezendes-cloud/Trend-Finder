(() => {
  const panel = document.getElementById('home-scores');
  if (!panel) return;
  const list = panel.querySelector('.score-grid');
  const note = panel.querySelector('.score-update');
  async function refresh() {
    try {
      const response = await fetch(panel.dataset.url, {signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error('Unavailable');
      const data = await response.json();
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
        list.append(card);
      }
      note.textContent = data.updated ? `${data.stale ? 'Updates delayed · last received' : 'ESPN · updated'} ${new Date(data.updated).toLocaleTimeString()} · checks every minute · ATS/totals use saved lines` : 'Scores temporarily unavailable. Try again shortly.';
      if (!data.games.length && data.updated && !data.stale) note.textContent = 'No games listed by the score feed right now.';
    } catch (_) {
      note.textContent = 'Score updates unavailable. Any displayed scores may be outdated.';
    }
  }
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 60000);
})();

(() => {
  const panel = document.getElementById('plug-refresh');
  if (!panel) return;
  let timer, busy = false;
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    let seconds = 60;
    try {
      const response = await fetch(panel.dataset.scoresUrl, {cache:'no-store', signal:AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error('Scores unavailable');
      const data = await response.json();
      seconds = data.refresh_seconds === 15 ? 15 : 60;
      if (!data.stale) for (const card of document.querySelectorAll('.expert-grid > .expert-card')) {
        const day = new Date(card.dataset.kickoff).toISOString().slice(0,10);
        const game = data.games.find(g => g.away === card.dataset.away && g.home === card.dataset.home && new Date(g.date).toISOString().slice(0,10) === day);
        const slot = card.querySelector('.plug-anomaly-slot');
        if (slot && game && game.completed && game.state === 'post' && window.gameAnomalyFlag) {
          const flag = window.gameAnomalyFlag(game.anomalies);
          if (flag && !slot.querySelector('details[open]')) slot.replaceChildren(flag);
        }
        if (game && game.state !== 'pre' && !card.querySelector('.plug-final-score')) {
          const score = card.querySelector('.plug-live-score');
          if (score) {
            score.hidden = false;
            score.textContent = `${game.away} ${game.away_score ?? '—'} · ${game.home} ${game.home_score ?? '—'} · ${game.completed && game.state === 'post' ? 'FINAL' : game.status}`;
          }
        }
      }
    } catch (_) {
      // Retain the last successful display when the score feed is unavailable.
    } finally {
      busy = false;
      clearTimeout(timer);
      if (!document.hidden) timer = setTimeout(refresh, seconds * 1000);
    }
  }
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (!document.hidden) refresh();
  });
  window.addEventListener('pagehide', () => clearTimeout(timer), {once:true});
  refresh();
})();

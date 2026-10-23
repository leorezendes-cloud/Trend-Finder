(() => {
  const panel = document.getElementById('plug-refresh');
  if (!panel) return;
  let timer, busy = false, marketChecked = 0;
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
        if (slot && game && game.completed && game.state === 'post') {
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
      if (Date.now() - marketChecked >= 60000) {
        const page = await fetch(location.href, {cache:'no-store', signal:AbortSignal.timeout(10000)});
        if (page.ok) {
          const documentCopy = new DOMParser().parseFromString(await page.text(),'text/html');
          const fresh = documentCopy.getElementById('plug-weekly-slate');
          const current = document.getElementById('plug-weekly-slate');
          if (fresh && current) current.replaceChildren(...fresh.childNodes);
          marketChecked = Date.now();
        }
      }
    } catch (_) { /* Retain the last successful display when a feed is unavailable. */ }
    finally { busy = false; clearTimeout(timer); timer = setTimeout(refresh,seconds*1000); }
  }
  document.addEventListener('visibilitychange',() => {if (!document.hidden) {clearTimeout(timer);refresh();}});
  refresh();
})();

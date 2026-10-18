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
        if (game && game.state !== 'pre') card.querySelector('.plug-live-score').textContent = `${game.away} ${game.away_score ?? '—'} · ${game.home} ${game.home_score ?? '—'} · ${game.status}`;
      }
      if (Date.now() - marketChecked >= 300000) {
        const page = await fetch(location.href, {cache:'no-store', signal:AbortSignal.timeout(10000)});
        if (page.ok) {
          const documentCopy = new DOMParser().parseFromString(await page.text(),'text/html');
          const freshCards = [...documentCopy.querySelectorAll('.expert-grid > .expert-card')];
          for (const card of document.querySelectorAll('.expert-grid > .expert-card')) {
            const fresh = freshCards.find(c => c.dataset.away === card.dataset.away && c.dataset.home === card.dataset.home && c.dataset.kickoff === card.dataset.kickoff);
            if (fresh) card.querySelector('.plug-market-context').replaceChildren(...fresh.querySelector('.plug-market-context').childNodes);
          }
          marketChecked = Date.now();
        }
      }
    } catch (_) { /* Retain the last successful display when a feed is unavailable. */ }
    finally { busy = false; clearTimeout(timer); timer = setTimeout(refresh,seconds*1000); }
  }
  document.addEventListener('visibilitychange',() => {if (!document.hidden) {clearTimeout(timer);refresh();}});
  refresh();
})();

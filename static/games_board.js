(() => {
  const root = document.getElementById('tf-games-board');
  if (!root) return;
  const cards = [...root.querySelectorAll('.tf-board-game')];
  const notice = document.getElementById('tf-board-update');
  const groups = Object.fromEntries(['in','pre','post'].map(s => [s,root.querySelector(`[data-group="${s}"]`)]));
  const grids = Object.fromEntries(['in','pre','post'].map(s => [s,root.querySelector(`[data-grid="${s}"]`)]));
  const make = (tag, cls, value) => {
    const x = document.createElement(tag);
    if (cls) x.className = cls;
    if (value !== undefined) x.textContent = String(value);
    return x;
  };
  const feedback = text => make('p','tf-gc-empty',text);
  const lastDetail = new WeakMap();
  const detailData = new WeakMap();
  const activeFetch = new WeakSet();
  const touched = new WeakSet();
  let timer, busy = false, working = 0;
  const queued = [];
  const startNext = () => {
    while (working < 2 && queued.length) {
      working++;
      Promise.resolve().then(queued.shift()).finally(() => { working--; startNext(); });
    }
  };
  const enqueue = fn => { queued.push(fn); startNext(); };
  function render(card) {
    const output = card.querySelector('.tf-board-detail');
    const data = detailData.get(card);
    const view = card.dataset.view || 'scoring';
    output.replaceChildren();
    if (!data || !data.details) {
      output.append(feedback(card.dataset.state === 'pre' ? 'Scoring and team stats will appear after kickoff.' : 'Detailed game stats are temporarily unavailable. Scores will still update.'));
      return;
    }
    const info = data.details;
    if (view === 'scoring') {
      if (!info.plays?.length) return output.append(feedback('No scoring plays available yet.'));
      [...info.plays].slice(-10).reverse().forEach(p => {
        const row = make('div','tf-gc-play');
        const desc = make('div','');
        desc.append(make('span','tf-gc-play-team',p.team),make('div','tf-gc-play-desc',p.text || 'Scoring play'));
        const score = p.away_score == null || p.home_score == null ? '' : `${p.away_score}–${p.home_score}`;
        row.append(make('span','tf-gc-play-time',`Q${p.quarter} · ${p.time || '—'}`),desc,make('span','tf-gc-play-score',score));
        output.append(row);
      });
    } else if (view === 'stats') {
      if (!info.metrics?.length) return output.append(feedback('Team statistics are still pending.'));
      const heading = make('div','tf-gc-metric tf-gc-head');
      heading.append(make('strong','',data.away),make('span','','Team stats'),make('strong','',data.home));
      output.append(heading);
      info.metrics.forEach(m => { const row = make('div','tf-gc-metric');
        row.append(make('strong','',m.away),make('span','',m.label),make('strong','',m.home)); output.append(row); });
    } else {
      const columns = make('div','tf-gc-leaders');
      [data.away,data.home].forEach(team => {
        const panel = make('div','tf-gc-leader-team');
        panel.append(make('h3','',team));
        const leaders = info.leaders?.[team] || [];
        if (!leaders.length) panel.append(feedback('Player stats pending.'));
        leaders.forEach(p => { const x = make('div','tf-gc-leader');
          x.append(make('small','',p.role),make('strong','',p.name),make('span','',p.line)); panel.append(x); });
        columns.append(panel);
      });
      output.append(columns);
    }
  }
  function loadDetail(card) {
    if (!card.open || document.hidden || activeFetch.has(card)) return;
    if (card.dataset.state === 'pre') {
      if (!detailData.has(card)) render(card);
      return;
    }
    const timeout = card.dataset.state === 'in' ? 45000 : 300000;
    if (Date.now() - (lastDetail.get(card) || 0) < timeout) return;
    activeFetch.add(card);
    lastDetail.set(card,Date.now());
    if (!detailData.has(card)) card.querySelector('.tf-board-detail').replaceChildren(feedback('Loading game details…'));
    enqueue(async () => {
      try {
        const response = await fetch(card.dataset.detail,{cache:'no-store',signal:AbortSignal.timeout(8500)});
        if (!response.ok) throw new Error('Game details unavailable');
        detailData.set(card,await response.json());
        if (card.open) render(card);
      } catch (_) {
        lastDetail.set(card,Date.now()-timeout+30000);
        if (!detailData.has(card) && card.open) card.querySelector('.tf-board-detail').replaceChildren(feedback('Scoring details are delayed. Try opening the game later.'));
      } finally { activeFetch.delete(card); }
    });
  }
  cards.forEach(card => {
    card.dataset.view = 'scoring';
    card.addEventListener('click',event => {
      if (event.target.closest('summary')) touched.add(card);
    });
    card.addEventListener('toggle', () => {
      if (card.open) loadDetail(card);
    });
    card.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click',() => {
      card.dataset.view = button.dataset.view;
      card.querySelectorAll('[data-view]').forEach(b => {
        const on = b === button;
        b.classList.toggle('is-active',on);
        b.setAttribute('aria-pressed',String(on));
      });
      render(card);
    }));
  });
  function updateGame(card, live) {
    if (!live) return;
    const state = ['in','post'].includes(live.state) ? live.state : 'pre';
    const prior = card.dataset.state;
    card.dataset.state = state;
    card.classList.toggle('is-live',state === 'in');
    const final = state === 'post';
    card.querySelector('.tf-board-away').textContent = state === 'pre' ? '—' : live.away_score ?? '—';
    card.querySelector('.tf-board-home').textContent = state === 'pre' ? '—' : live.home_score ?? '—';
    const badge = card.querySelector('.tf-board-livebadge');
    badge.textContent = state === 'in' ? '● LIVE' : final ? 'FINAL' : 'UPCOMING';
    card.querySelector('.tf-board-game-status').textContent = `${live.status || (final ? 'Final' : 'Scheduled')} · Tap for details`;
    if (prior !== state && !touched.has(card)) card.open = state === 'in';
    if (card.open) loadDetail(card);
  }
  function organize() {
    const counts = {'in':0,'pre':0,'post':0};
    cards.forEach(card => {
      let state = card.dataset.state;
      if (!(state in grids)) state = 'pre';
      grids[state].append(card);
      counts[state]++;
    });
    Object.keys(counts).forEach(key => {
      groups[key].hidden = counts[key] === 0;
      groups[key].querySelector('[data-count]').textContent = counts[key];
    });
  }
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    let delay = 60000;
    try {
      const response = await fetch(root.dataset.feed,{cache:'no-store',signal:AbortSignal.timeout(9000)});
      if (!response.ok) throw new Error('Score feed delayed');
      const board = await response.json();
      const gameMap = new Map((board.games || []).filter(g => g.url).map(g => [g.url,g]));
      cards.forEach(card => updateGame(card,gameMap.get(card.dataset.url)));
      organize();
      const count = cards.filter(c => c.dataset.state === 'in').length;
      delay = board.refresh_seconds === 15 ? 15000 : 60000;
      notice.textContent = `${count ? `${count} live · ` : ''}${board.stale ? 'Live scores delayed' : 'ESPN scores updated'} ${board.updated ? new Date(board.updated).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}) : ''} · ${cards.length} scheduled games`;
    } catch (_) {
      notice.textContent = 'Live updates are temporarily unavailable. Showing saved scheduled games.';
    } finally {
      busy = false;
      clearTimeout(timer);
      if (!document.hidden) timer = setTimeout(refresh, delay);
    }
  }
  document.addEventListener('visibilitychange',() => {
    clearTimeout(timer);
    if (!document.hidden) {
      cards.forEach(card => { if (card.open) loadDetail(card); });
      refresh();
    }
  });
  organize();
  refresh();
})();

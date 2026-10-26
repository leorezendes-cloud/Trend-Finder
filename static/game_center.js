(() => {
  const root = document.getElementById('tf-game-center');
  if (!root) return;
  const $ = id => document.getElementById('tf-gc-' + id);
  let refreshTimer;
  let busy = false;
  const element = (tag, cls, text) => { const x = document.createElement(tag); if (cls) x.className = cls; if (text !== undefined) x.textContent = text; return x; };
  const blank = text => element('p', 'tf-gc-empty', text);
  const tabButtons = [...root.querySelectorAll('[data-tab]')];
  const activate = name => {
    tabButtons.forEach(b => {
      const selected = b.dataset.tab === name;
      b.classList.toggle('is-active', selected);
      b.setAttribute('aria-selected', String(selected));
      $(b.dataset.tab).hidden = !selected;
    });
  };
  tabButtons.forEach(b => b.addEventListener('click', () => activate(b.dataset.tab)));
  function draw(data) {
    const state = data.state;
    $('status').textContent = state === 'in' ? '● LIVE' : state === 'post' ? 'FINAL' : 'UPCOMING';
    $('status').className = 'tf-gc-badge' + (state === 'in' ? ' live' : state === 'post' ? ' final' : '');
    $('away').textContent = data.away_score ?? '—';
    $('home').textContent = data.home_score ?? '—';
    $('clock').textContent = data.status || 'Game status unavailable';
    $('updated').textContent = data.stale ? 'Updates delayed' : 'Updated ' + new Date().toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
    const details = data.details;
    const plays = $('plays'); plays.replaceChildren();
    if (details?.plays?.length) {
      [...details.plays].reverse().forEach(p => {
        const entry = element('div', 'tf-gc-play');
        entry.append(element('span', 'tf-gc-play-time', `Q${p.quarter} · ${p.time || '—'}`));
        const info = element('div');
        info.append(element('span', 'tf-gc-play-team', p.team));
        info.append(element('div', 'tf-gc-play-desc', p.text || 'Scoring play'));
        entry.append(info);
        const score = p.away_score == null || p.home_score == null ? '' : `${p.away_score}–${p.home_score}`;
        entry.append(element('span', 'tf-gc-play-score', score));
        plays.append(entry);
      });
    } else plays.append(blank(state === 'pre' ? 'Scoring summary will appear after kickoff.' : 'Detailed scoring feed is unavailable right now. Live scores may still update.'));
    const metrics = $('metrics'); metrics.replaceChildren();
    if (details?.metrics?.length) {
      const head = element('div', 'tf-gc-metric tf-gc-head');
      head.append(element('strong', '', data.away), element('span', '', 'Team stats'), element('strong', '', data.home));
      metrics.append(head);
      details.metrics.forEach(m => {
        const row = element('div', 'tf-gc-metric');
        row.append(element('strong', '', m.away), element('span', '', m.label), element('strong', '', m.home));
        metrics.append(row);
      });
    } else metrics.append(blank('Team statistics are not available yet.'));
    const leaders = $('leaders'); leaders.replaceChildren();
    [data.away, data.home].forEach(team => {
      const rows = details?.leaders?.[team] || [];
      const group = element('div', 'tf-gc-leader-team');
      group.append(element('h3', '', team));
      if (!rows.length) group.append(blank('Player stats pending.'));
      rows.forEach(p => {
        const card = element('div', 'tf-gc-leader');
        card.append(element('small', '', p.role), element('strong', '', p.name), element('span', '', p.line));
        group.append(card);
      });
      leaders.append(group);
    });
    $('source').textContent = (data.stale ? 'Score feed delayed · ' : '') + 'ESPN game data · ' + (state === 'in' ? 'live refresh every 30 seconds' : 'refresh every minute') + ' · Pregame picks and Scout analysis are on Team Comparison.';
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    let seconds = 60;
    try {
      const response = await fetch(root.dataset.source, {cache:'no-store', signal:AbortSignal.timeout(9000)});
      if (!response.ok) throw new Error('Score feed unavailable');
      const data = await response.json();
      seconds = data.refresh_seconds === 30 ? 30 : 60;
      draw(data);
    } catch (_) {
      $('source').textContent = 'Score data is temporarily unavailable. Existing results may be outdated.';
      $('updated').textContent = 'Updates delayed';
    } finally {
      busy = false;
      clearTimeout(refreshTimer);
      if (!document.hidden) refreshTimer = setTimeout(refresh, seconds * 1000);
    }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) clearTimeout(refreshTimer);
    else refresh();
  });
  refresh();
})();

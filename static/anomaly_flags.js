/* Saved event titles only; never insert event content as HTML. */
window.gameAnomalyFlag = function (events) {
  if (!Array.isArray(events)) return null;
  const links = events.filter(e => e && typeof e.title === 'string' && e.title.trim() &&
    typeof e.url === 'string' && e.url.startsWith('/') && !e.url.startsWith('//') && !/[\\\r\n]/.test(e.url));
  if (!links.length) return null;
  const flag = document.createElement('details');
  flag.className = 'game-anomaly-flag';
  const toggle = document.createElement('summary');
  toggle.textContent = '⚑';
  toggle.title = 'Saved game anomalies';
  toggle.setAttribute('aria-label', 'View saved game anomalies');
  const panel = document.createElement('div');
  panel.className = 'game-anomaly-links';
  for (const event of links) {
    const link = document.createElement('a');
    link.href = event.url;
    link.textContent = event.title;
    panel.append(link);
  }
  flag.append(toggle, panel);
  return flag;
};
document.addEventListener('click', event => {
  document.querySelectorAll('.game-anomaly-flag[open]').forEach(flag => {
    if (!flag.contains(event.target)) flag.removeAttribute('open');
  });
});

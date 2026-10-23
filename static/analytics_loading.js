/* Bounded navigation retries; no parallel fetches or background calculations. */
(() => {
  const status = document.getElementById('analytics-loading-status');
  const retry = document.getElementById('analytics-loading-retry');
  if (!status || !retry) return;
  const delays = [2000, 3000, 5000, 8000, 10000];
  const state = history.state && typeof history.state === 'object' ? history.state : {};
  const saved = state.tfAnalyticsLoading;
  const now = Date.now();
  const previous = saved && now - saved.started >= 0 && now - saved.started < 60000
    && Number.isInteger(saved.count) && saved.count >= 0 ? saved : {started: now, count: 0};
  let timer;
  let scheduled = false;

  function remember(value) {
    try {
      history.replaceState({...state, tfAnalyticsLoading: value}, '');
      return true;
    } catch (_) {
      return false; // Keep manual retry when browser storage is unavailable.
    }
  }

  retry.addEventListener('click', () => {
    clearTimeout(timer);
    remember({started: Date.now(), count: 0});
    location.reload();
  });

  function schedule() {
    if (document.hidden || scheduled) return;
    if (previous.count >= delays.length) {
      status.textContent = 'This is taking longer than usual. Try again in a moment, or return Home.';
      return;
    }
    scheduled = true;
    timer = setTimeout(() => {
      scheduled = false;
      if (document.hidden) return;
      if (remember({started: previous.started, count: previous.count + 1})) location.reload();
      else status.textContent = 'Select Try again to continue.';
    }, delays[previous.count]);
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      clearTimeout(timer);
      scheduled = false;
    } else schedule();
  });
  window.addEventListener('pagehide', () => clearTimeout(timer));
  schedule();
})();

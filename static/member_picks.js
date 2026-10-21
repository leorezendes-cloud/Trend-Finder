const mobilePicks = window.matchMedia('(max-width: 650px)');
mobilePicks.addEventListener('change', (event) => {
  if (!event.matches) document.querySelectorAll('.mobile-picks-menu').forEach(menu => { menu.open = true; });
});
document.addEventListener('change', (event) => {
  const input = event.target;
  if (!input.matches('[data-pick-form] input[type="checkbox"]') || !input.checked) return;
  for (const other of input.form.querySelectorAll('input[type="checkbox"]')) {
    if (other !== input && other.name === input.name) other.checked = false;
  }
});
async function sendPicks(form, data) {
  for (let attempt = 0; attempt < 2; attempt++) {
    let response;
    try {
      response = await fetch(form.action, {method: 'POST', body: data, headers: {'Accept': 'application/json'}});
    } catch (error) {
      if (attempt === 0) continue;
      throw new Error('Connection interrupted. Your picks may already be saved. Tap Save picks to retry safely.');
    }
    if ([502, 503, 504].includes(response.status) && attempt === 0) continue;
    let result;
    try {
      result = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
    } catch (error) {
      if (attempt === 0) continue;
      throw new Error('The save confirmation was interrupted. Tap Save picks to retry safely.');
    }
    if (!response.ok) throw new Error(result?.error || 'Could not save these picks. Refresh to check kickoff times, then try again.');
    if (!result) throw new Error('Sign in again to save your picks.');
    return result;
  }
}
document.querySelectorAll('[data-pick-form]').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    if (button.disabled) return;
    const status = form.querySelector('.pick-save-status');
    const data = new FormData(form);
    const choices = Array.from(form.querySelectorAll('input[type="checkbox"]')).filter(input => !input.disabled);
    choices.forEach(input => { input.disabled = true; });
    button.disabled = true;
    status.textContent = 'Saving…';
    try {
      const result = await sendPicks(form, data);
      status.textContent = result.message;
      const menu = form.closest('.mobile-picks-menu');
      if (mobilePicks.matches && result.saved > 0 &&
          menu?.matches('details.mobile-picks-menu') &&
          menu.querySelector('[data-pick-menu-label]') &&
          menu.querySelector('[data-pick-menu-status]') &&
          menu.querySelector('summary')) {
        menu.querySelector('[data-pick-menu-label]').textContent = 'Your picks — saved';
        menu.querySelector('[data-pick-menu-status]').textContent = 'Progress saved. Tap to view or finish your picks.';
        menu.open = false;
        const summary = menu.querySelector('summary');
        summary.scrollIntoView({block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
        summary.focus({preventScroll: true});
      }
    } catch (error) {
      status.textContent = error.message || 'Could not save. Please try again.';
    } finally {
      choices.forEach(input => { input.disabled = false; });
      button.disabled = false;
    }
  });
});

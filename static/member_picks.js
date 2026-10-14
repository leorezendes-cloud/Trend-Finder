document.addEventListener('change', (event) => {
  const input = event.target;
  if (!input.matches('[data-pick-form] input[type="checkbox"]') || !input.checked) return;
  for (const other of input.form.querySelectorAll('input[type="checkbox"]')) {
    if (other !== input && other.name === input.name) other.checked = false;
  }
});
document.querySelectorAll('[data-pick-form]').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const status = form.querySelector('.pick-save-status');
    const data = new FormData(form);
    button.disabled = true;
    status.textContent = 'Saving…';
    try {
      const response = await fetch(form.action, {method: 'POST', body: data, headers: {'Accept': 'application/json'}});
      const result = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
      if (!response.ok) throw new Error(result?.error || 'Could not save these picks. Refresh to check kickoff times, then try again.');
      if (!result) throw new Error('Sign in again to save your picks.');
      status.textContent = result.message;
    } catch (error) {
      status.textContent = error.message || 'Could not save. Please try again.';
    } finally {
      button.disabled = false;
    }
  });
});

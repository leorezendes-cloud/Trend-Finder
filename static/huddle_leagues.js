/* Copy invitations only after a member taps the control. No network requests. */
(() => {
  const field = document.getElementById('league-share');
  const button = document.getElementById('league-copy');
  const status = document.getElementById('league-copy-status');
  if (!field || !button || !status) return;

  function selectLink() {
    field.focus();
    field.select();
    field.setSelectionRange(0, field.value.length);
  }

  field.addEventListener('click', selectLink);
  button.hidden = false;
  button.addEventListener('click', async () => {
    button.disabled = true;
    status.textContent = '';
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error('Use selection fallback');
      await navigator.clipboard.writeText(field.value);
      status.textContent = 'Link copied! Paste it into a message to invite friends.';
    } catch (error) {
      selectLink();
      let copied = false;
      try {
        copied = document.execCommand('copy');
      } catch (fallbackError) {
        // Keep the invitation selected for the browser's Copy action.
      }
      status.textContent = copied
        ? 'Link copied! Paste it into a message to invite friends.'
        : 'Link selected. Touch and hold it, or use your browser’s Copy action.';
    } finally {
      button.disabled = false;
    }
  });
})();

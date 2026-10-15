(() => {
  const mode = document.getElementById('season_mode');
  if (!mode) return;
  function update() {
    const range = mode.value === 'range';
    document.querySelectorAll('[data-single-season]').forEach(el => { el.hidden = range; });
    document.querySelectorAll('[data-season-range]').forEach(el => { el.hidden = !range; });
  }
  mode.addEventListener('change', update);
  update();
})();

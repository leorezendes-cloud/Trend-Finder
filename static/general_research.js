(() => {
  const mode = document.getElementById('season_mode');
  if (!mode) return;
  function update() {
    const range = mode.value === 'range';
    document.querySelectorAll('[data-single-season]').forEach(el => { el.hidden = range; });
    document.querySelectorAll('[data-season-range]').forEach(el => { el.hidden = !range; });
  }
  async function loadEvidence(panel, url) {
    const content=panel.querySelector('.evidence-content');
    content.textContent='Loading matching games…';
    try {
      const response=await fetch(url, {headers:{'X-Requested-With':'XMLHttpRequest'}});
      if (!response.ok) throw new Error('load failed');
      content.innerHTML=await response.text();
      panel.dataset.loaded='1';
    } catch (_) {
      content.textContent='Games could not load. Close and reopen to retry.';
      delete panel.dataset.loaded;
    }
  }
  document.querySelectorAll('.combination-evidence').forEach(panel => {
    panel.addEventListener('toggle', () => {
      if (panel.open && !panel.dataset.loaded) {
        panel.dataset.loaded='loading';
        loadEvidence(panel,panel.dataset.evidenceUrl);
      }
    });
    panel.addEventListener('click', event => {
      const link=event.target.closest('a[data-evidence-page]');
      if (link) { event.preventDefault(); loadEvidence(panel,link.href); }
    });
  });
  if (location.hash==='#matching-games') {
    const games=document.getElementById('matching-games');
    if (games) {games.open=true;games.scrollIntoView();}
  }
  const nightChoices=document.querySelectorAll('[name=primetime_nights]');
  const primetime=document.getElementById('primetime');
  nightChoices.forEach(choice => choice.addEventListener('change', () => {
    if ([...nightChoices].some(item => item.checked)) primetime.value='yes';
  }));
  if (primetime) primetime.addEventListener('change', () => {
    if (primetime.value!=='yes') nightChoices.forEach(choice => {choice.checked=false;});
  });
  mode.addEventListener('change', update);
  update();
})();

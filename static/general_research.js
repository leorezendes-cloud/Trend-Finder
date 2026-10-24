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

// Editable research dropdowns: exact text plus compact, explicit choices.
(() => {
  for (const [id, sourceId, isSpread] of [['spread_size', 'spread-options', true], ['qb_name', 'general-qbs', false]]) {
    const input = document.getElementById(id);
    const source = document.getElementById(sourceId);
    if (!input || !source) continue;
    const entries = Array.from(source.options, option => ({value: option.value, label: option.value}));
    if (!isSpread) entries.unshift({value: '', label: 'All QBs'});
    const wrapper = document.createElement('div');
    wrapper.className = 'research-combobox';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'research-combobox-toggle';
    toggle.textContent = '▾';
    toggle.setAttribute('aria-label', isSpread ? 'Show all spread ranges' : 'Show all quarterbacks');
    const menu = document.createElement('div');
    menu.id = id + '-menu';
    menu.className = 'research-combobox-menu';
    menu.hidden = true;
    menu.setAttribute('role', 'listbox');
    menu.setAttribute('aria-label', isSpread ? 'Spread ranges' : 'Quarterbacks');
    wrapper.appendChild(toggle);
    wrapper.appendChild(menu);
    input.removeAttribute('list');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', isSpread ? 'none' : 'list');
    input.setAttribute('aria-controls', menu.id);
    input.setAttribute('autocomplete', 'off');
    toggle.setAttribute('aria-controls', menu.id);
    let active = -1;
    let visible = [];
    function expanded(open) {
      menu.hidden = !open;
      input.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-expanded', String(open));
      if (!open) {active = -1; input.removeAttribute('aria-activedescendant');}
    }
    function select(entry) {
      input.value = entry.value;
      input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
      input.focus();
      expanded(false);
    }
    function render(filter) {
      const query = filter && !isSpread ? input.value.trim().toLocaleLowerCase() : '';
      visible = entries.filter(entry => !query || !entry.value || entry.label.toLocaleLowerCase().includes(query));
      menu.replaceChildren();
      active = -1;
      input.removeAttribute('aria-activedescendant');
      visible.forEach((entry, index) => {
        const option = document.createElement('button');
        option.type = 'button';
        option.tabIndex = -1;
        option.id = menu.id + '-' + index;
        option.textContent = entry.label;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', String(entry.value === input.value));
        option.addEventListener('pointerdown', event => event.preventDefault());
        option.addEventListener('click', () => select(entry));
        menu.appendChild(option);
      });
      expanded(true);
    }
    expanded(false);
    toggle.addEventListener('click', () => { if (menu.hidden) render(false); else expanded(false); });
    input.addEventListener('focus', () => render(true));
    input.addEventListener('input', () => render(true));
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape' || event.key === 'Tab') {
        if (event.key === 'Escape' && !menu.hidden) {event.preventDefault();event.stopPropagation();}
        expanded(false);
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (menu.hidden) render(false);
        active = active < 0 ? (event.key === 'ArrowDown' ? 0 : visible.length - 1)
          : (active + (event.key === 'ArrowDown' ? 1 : -1) + visible.length) % visible.length;
        Array.from(menu.children).forEach((option, index) => option.classList.toggle('is-active', index === active));
        const option = menu.children[active];
        if (option) {input.setAttribute('aria-activedescendant', option.id);option.scrollIntoView({block: 'nearest'});}
      } else if (event.key === 'Enter' && !menu.hidden && active >= 0) {
        event.preventDefault();
        select(visible[active]);
      }
    });
    document.addEventListener('pointerdown', event => {if (!wrapper.contains(event.target)) expanded(false);});
    wrapper.addEventListener('focusout', event => {if (!wrapper.contains(event.relatedTarget)) expanded(false);});
    if (input.form) input.form.addEventListener('submit', () => expanded(false));
  }
})();

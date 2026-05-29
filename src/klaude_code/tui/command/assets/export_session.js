
(() => {
  const navItems = Array.from(document.querySelectorAll('.nav-item'));
  const entryCards = Array.from(document.querySelectorAll('.entry-card'));
  const buttons = Array.from(document.querySelectorAll('.filter-btn'));
  const search = document.getElementById('entry-search');
  const status = document.getElementById('entry-status');
  let currentFilter = 'all';

  const normalize = (value) => (value || '').toLowerCase();

  function applyFilters() {
    const query = normalize(search && search.value);
    let visibleCount = 0;

    for (const node of [...navItems, ...entryCards]) {
      const kind = normalize(node.dataset.entryKind);
      const haystack = normalize(node.dataset.search);
      const kindMatch = currentFilter === 'all' || kind === currentFilter;
      const searchMatch = !query || haystack.includes(query);
      const visible = kindMatch && searchMatch;
      node.hidden = !visible;
      if (visible && node.classList.contains('entry-card')) {
        visibleCount += 1;
      }
    }

    if (status) {
      status.textContent = `${visibleCount} visible entries`;
    }
  }

  for (const button of buttons) {
    button.addEventListener('click', () => {
      currentFilter = button.dataset.filter || 'all';
      for (const item of buttons) {
        item.classList.toggle('is-active', item === button);
      }
      applyFilters();
    });
  }

  if (search) {
    search.addEventListener('input', applyFilters);
  }

  for (const item of navItems) {
    item.addEventListener('click', () => {
      for (const navItem of navItems) {
        navItem.classList.remove('is-active');
      }
      item.classList.add('is-active');
    });
  }

  if (window.location.hash) {
    const active = document.querySelector(`.nav-item[href="${window.location.hash}"]`);
    if (active) {
      active.classList.add('is-active');
    }
  }

  applyFilters();

  const COLLAPSE_THRESHOLD = 240;
  const collapsibles = document.querySelectorAll(
    '.markdown-block, pre.tool-output, pre.json-block, pre.code-block, pre.system-prompt'
  );

  for (const el of collapsibles) {
    if (el.scrollHeight <= COLLAPSE_THRESHOLD) continue;

    el.classList.add('is-collapsed');

    const btn = document.createElement('button');
    btn.className = 'collapse-toggle';
    btn.textContent = 'Show more';
    btn.addEventListener('click', () => {
      const collapsed = el.classList.toggle('is-collapsed');
      btn.textContent = collapsed ? 'Show more' : 'Show less';
    });
    el.after(btn);
  }
})();

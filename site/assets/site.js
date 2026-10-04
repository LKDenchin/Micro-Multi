'use strict';
for (const link of document.querySelectorAll('.sidebar nav a')) {
  if (new URL(link.href).pathname === window.location.pathname) {
    link.classList.add('active');
    link.setAttribute('aria-current', 'page');
  }
}
const chinese = document.documentElement.lang === 'zh-CN';
const search = document.getElementById('doc-search');
const results = document.getElementById('search-results');
if (search && results) {
  let documents;
  let generation = 0;
  search.addEventListener('input', async () => {
    const current = ++generation;
    const query = search.value.trim().toLocaleLowerCase();
    results.replaceChildren();
    results.hidden = !query;
    if (!query) return;
    try {
      documents ??= await fetch('/Micro-Multi/assets/search-index.json').then(response => {
        if (!response.ok) throw new Error('Search unavailable');
        return response.json();
      });
      if (current !== generation) return;
      const terms = query.split(/\s+/);
      const matches = documents.filter(doc => doc.lang === document.documentElement.lang && terms.every(term => (doc.title + ' ' + doc.text).toLocaleLowerCase().includes(term)))
        .sort((a, b) => Number(b.title.toLocaleLowerCase().includes(query)) - Number(a.title.toLocaleLowerCase().includes(query)))
        .slice(0, 7);
      for (const doc of matches) {
        const link = document.createElement('a');
        link.href = doc.url;
        link.textContent = doc.title;
        results.append(link);
      }
      if (!matches.length) results.textContent = chinese ? '未找到结果' : 'No results';
    } catch {
      results.textContent = chinese ? '请使用下方文档目录' : 'Use the guide list below';
    }
  });
  search.addEventListener('keydown', event => {
    if (event.key === 'Escape') { search.value = ''; results.hidden = true; }
    if (event.key === 'Enter') {
      const first = results.querySelector('a');
      if (first) window.location.assign(first.href);
    }
  });
}

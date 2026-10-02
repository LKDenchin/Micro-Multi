// One stroke weight and view box for navigation, actions and file entries.
const paths = {
  chat: '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5Z"/>',
  folder: '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11H3Z"/>',
  branch: '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M6 8v8a2 2 0 0 0 2 2h8m0-12v4a4 4 0 0 1-4 4H9"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z M14 2v6h6"/>',
  team: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2m1-16a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 5v2"/>',
  models: '<rect x="5" y="5" width="14" height="14" rx="3"/><path d="M9 9h6v6H9zM9 2v3m6-3v3m-6 14v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3"/>',
  skills: '<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4Z"/>',
  mcp: '<circle cx="6" cy="12" r="3"/><circle cx="18" cy="5" r="3"/><circle cx="18" cy="19" r="3"/><path d="m9 11 6-4m-6 6 6 4"/>',
  plugins: '<path d="M8 3v5m8-5v5M6 8h12v4a6 6 0 0 1-12 0Zm6 10v4"/>',
  runs: '<path d="m8 4 12 8-12 8ZM4 4v16"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2 14 2 15 5 17 6 20 5 22 9 20 11 20 13 22 15 20 19 17 18 15 19 14 22 10 22 9 19 7 18 4 19 2 15 4 13 4 11 2 9 4 5 7 6 9 5 10 2Z"/>', 
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 5 5"/>',
  compose: '<path d="M12 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-7M16 3l5 5M10 14l-1 4 4-1 9-9-3-3Z"/>',
  left: '<path d="m14 5-7 7 7 7"/>',
  right: '<path d="m10 5 7 7-7 7"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  send: '<path d="M12 20V4m-7 7 7-7 7 7"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  sparkle: '<path d="m12 3 2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2Z"/><path d="m19 2 .8 2.2L22 5l-2.2.8L19 8l-.8-2.2L16 5l2.2-.8Z"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14-5L4 8"/><path d="M4 4v4h4m-4 5a8 8 0 0 0 14 5l2-2"/><path d="M20 20v-4h-4"/>',
};

export function icon(name) {
  return '<svg class="app-icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">' + (paths[name] || paths.file) + '</svg>';
}

export function installIcons() {
  const rail = {home:'chat', repository:'folder', team:'team', models:'models', skills:'skills', mcp:'mcp', plugins:'plugins', runs:'runs', settings:'settings'};
  document.querySelectorAll('[data-rail]').forEach(button => { button.innerHTML = icon(rail[button.dataset.rail]); });
  const controls = {back:'left', forward:'right', 'toggle-sidebar':'panel', 'toggle-inspector':'panel', 'sidebar-search':'search', 'close-inspector':'close', 'composer-project':'plus', 'settings-close':'left', send:'send', 'browser-back':'left', 'browser-forward':'right', 'browser-reload':'refresh'};
  for (const [id, name] of Object.entries(controls)) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = icon(name);
  }
  const newChatEl = document.getElementById('new-chat');
  if (newChatEl) newChatEl.innerHTML = icon('compose') + '<span>新聊天</span>';
  const toggleInspEl = document.getElementById('toggle-inspector');
  if (toggleInspEl) toggleInspEl.innerHTML = icon('panel');
  const newProjEl = document.getElementById('new-project');
  if (newProjEl) newProjEl.innerHTML = icon('plus') + '<span>新建或导入项目</span>';
}

/**
 * Project Aether - Code & Files Studio Controller
 * Native ES Module
 */

import { escapeHtml, showToast, store } from '../store.js';

export let fileTreeData = null;
export let expandedFolders = new Set(['', 'src', 'docs']);
export let isGrepSearch = false;
let fileSearchDebounce = null;
let isFileExplorerCollapsed = false;

// Editor State
export let openEditorTabs = [];
export let activeEditorPath = null;

function getFileIcon(extension) {
  const ext = (extension || '').toLowerCase();
  const label = ext ? ext.substring(0, 4).toUpperCase() : 'FILE';
  return `<span class="file-ext-tag ext-${ext}">${escapeHtml(label)}</span>`;
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export async function refreshFilesTreeBtn() {
  const btn = document.getElementById('btn-refresh-files');
  const icon = btn ? btn.querySelector('.refresh-icon') : null;
  if (icon) icon.classList.add('spin');
  try {
    await loadFilesTree();
    showToast('Workspace file tree refreshed', 'success');
  } catch (err) {
    showToast('Failed to refresh files: ' + err.message, 'error');
  } finally {
    if (icon) setTimeout(() => icon.classList.remove('spin'), 400);
  }
}

export async function loadFilesTree(rootPath = '.') {
  const container = document.getElementById('file-tree-container');
  if (!container) return;
  container.innerHTML = '<div class="loading-spinner">Loading workspace files...</div>';

  try {
    const res = await fetch(`/api/files/tree?path=${encodeURIComponent(rootPath)}&depth=4`);
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      fileTreeData = data.tree;
      const wsNameBadge = document.getElementById('current-workspace-name');
      if (wsNameBadge && data.workspace_name) {
        wsNameBadge.innerText = data.workspace_name;
        wsNameBadge.title = data.workspace_root || '';
      }
      if (window.updateTerminalWorkspaceBadge) {
        window.updateTerminalWorkspaceBadge();
      }
      if (window.updateCoderContextPill) {
        window.updateCoderContextPill(activeEditorPath, data.workspace_name);
      }
      renderFilesTree();
    } else {
      container.innerHTML = `<div class="empty-state" style="padding:1.5rem;"><p style="color:var(--rose);">Failed to load files: ${data.message}</p></div>`;
    }
  } catch (err) {
    container.innerHTML = `<div class="empty-state" style="padding:1.5rem;"><p style="color:var(--rose);">Error loading tree: ${err.message}</p></div>`;
  }
}

export function renderFilesTree() {
  const container = document.getElementById('file-tree-container');
  if (!container || !fileTreeData) return;

  container.innerHTML = '';
  if (!fileTreeData.children || fileTreeData.children.length === 0) {
    container.innerHTML = '<div class="no-tabs-hint" style="padding:1rem;">Workspace directory is empty</div>';
    return;
  }

  const fragment = document.createDocumentFragment();
  fileTreeData.children.forEach((child) => {
    buildTreeNode(child, fragment, 0);
  });
  container.appendChild(fragment);
}

export function buildTreeNode(node, parentEl, level) {
  const isDir = node.type === 'directory';
  const isExpanded = expandedFolders.has(node.path);

  const row = document.createElement('div');
  row.className = `tree-row ${activeEditorPath === node.path ? 'active' : ''}`;
  row.style.paddingLeft = `${0.5 + level * 0.85}rem`;

  if (isDir) {
    const chevron = document.createElement('span');
    chevron.className = `tree-chevron ${isExpanded ? 'open' : ''}`;
    chevron.innerText = isExpanded ? '[-]' : '[+]';
    row.appendChild(chevron);

    const icon = document.createElement('span');
    icon.className = 'tree-icon folder-glyph';
    icon.innerText = isExpanded ? '[dir-open]' : '[dir]';
    row.appendChild(icon);

    const name = document.createElement('span');
    name.className = 'tree-name';
    name.innerText = node.name;
    row.appendChild(name);

    const actions = document.createElement('span');
    actions.className = 'tree-hover-actions';

    const addFileBtn = document.createElement('button');
    addFileBtn.className = 'tree-mini-btn';
    addFileBtn.innerText = '+File';
    addFileBtn.title = `Create file inside ${node.name}`;
    addFileBtn.onclick = (e) => {
      e.stopPropagation();
      createFileInFolder(node.path);
    };
    actions.appendChild(addFileBtn);

    const addFolderBtn = document.createElement('button');
    addFolderBtn.className = 'tree-mini-btn';
    addFolderBtn.innerText = '+Dir';
    addFolderBtn.title = `Create folder inside ${node.name}`;
    addFolderBtn.onclick = (e) => {
      e.stopPropagation();
      createFolderInFolder(node.path);
    };
    actions.appendChild(addFolderBtn);

    const revealBtn = document.createElement('button');
    revealBtn.className = 'tree-mini-btn';
    revealBtn.innerText = 'Explorer';
    revealBtn.title = `Show "${node.name}" in Windows File Explorer`;
    revealBtn.onclick = (e) => {
      e.stopPropagation();
      revealPathInExplorer(node.path);
    };
    actions.appendChild(revealBtn);

    const orgBtn = document.createElement('button');
    orgBtn.className = 'tree-mini-btn';
    orgBtn.innerText = 'Clean';
    orgBtn.title = `Organize files inside ${node.name}`;
    orgBtn.onclick = (e) => {
      e.stopPropagation();
      organizeSpecificFolder(node.path);
    };
    actions.appendChild(orgBtn);

    row.appendChild(actions);

    row.onclick = () => {
      if (expandedFolders.has(node.path)) {
        expandedFolders.delete(node.path);
      } else {
        expandedFolders.add(node.path);
      }
      renderFilesTree();
    };

    parentEl.appendChild(row);

    if (isExpanded && node.children) {
      node.children.forEach((child) => {
        buildTreeNode(child, parentEl, level + 1);
      });
    }
  } else {
    const spacer = document.createElement('span');
    spacer.style.width = '14px';
    row.appendChild(spacer);

    const icon = document.createElement('span');
    icon.className = 'tree-icon';
    icon.innerHTML = getFileIcon(node.extension);
    row.appendChild(icon);

    const name = document.createElement('span');
    name.className = 'tree-name';
    name.innerText = node.name;
    row.appendChild(name);

    if (node.size !== undefined) {
      const size = document.createElement('span');
      size.className = 'tree-size';
      size.innerText = formatBytes(node.size);
      row.appendChild(size);
    }

    const actions = document.createElement('span');
    actions.className = 'tree-hover-actions';

    const revealBtn = document.createElement('button');
    revealBtn.className = 'tree-mini-btn';
    revealBtn.innerText = 'Explorer';
    revealBtn.title = `Show "${node.name}" in Windows File Explorer`;
    revealBtn.onclick = (e) => {
      e.stopPropagation();
      revealPathInExplorer(node.path);
    };
    actions.appendChild(revealBtn);

    const delBtn = document.createElement('button');
    delBtn.className = 'tree-mini-btn';
    delBtn.innerText = 'Del';
    delBtn.title = `Move "${node.name}" to Trash`;
    delBtn.onclick = (e) => {
      e.stopPropagation();
      deleteFileByPath(node.path);
    };
    actions.appendChild(delBtn);

    row.appendChild(actions);
    row.onclick = () => openFile(node.path);
    parentEl.appendChild(row);
  }
}

export function toggleGrepSearch() {
  isGrepSearch = !isGrepSearch;
  const btn = document.getElementById('btn-toggle-grep');
  if (btn) btn.classList.toggle('active', isGrepSearch);
  const searchInput = document.getElementById('file-search-input');
  if (searchInput && searchInput.value.trim()) {
    onFileSearchInput(searchInput.value);
  }
}

export function onFileSearchInput(val) {
  clearTimeout(fileSearchDebounce);
  fileSearchDebounce = setTimeout(async () => {
    const q = (val || '').trim();
    if (!q) {
      renderFilesTree();
      return;
    }

    const container = document.getElementById('file-tree-container');
    if (!container) return;
    container.innerHTML = '<div class="loading-spinner">Searching...</div>';

    try {
      const res = await fetch(`/api/files/search?q=${encodeURIComponent(q)}&content=${isGrepSearch}`);
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        renderSearchResults(data.results, q);
      } else {
        container.innerHTML = `<div class="empty-state"><p style="color:var(--rose);">${data.message}</p></div>`;
      }
    } catch (err) {
      container.innerHTML = `<div class="empty-state"><p style="color:var(--rose);">Search error: ${err.message}</p></div>`;
    }
  }, 250);
}

export function renderSearchResults(results, query) {
  const container = document.getElementById('file-tree-container');
  if (!container) return;
  container.innerHTML = '';

  if (!results || results.length === 0) {
    container.innerHTML = `<div class="no-tabs-hint" style="padding:1rem;">No matching files found for "${escapeHtml(query)}"</div>`;
    return;
  }

  results.forEach((item) => {
    const row = document.createElement('div');
    row.className = `tree-row ${activeEditorPath === item.path ? 'active' : ''}`;
    row.style.paddingLeft = '0.5rem';

    const icon = document.createElement('span');
    icon.className = 'tree-icon';
    icon.innerHTML = getFileIcon(item.extension);
    row.appendChild(icon);

    const name = document.createElement('span');
    name.className = 'tree-name';
    name.innerText = item.path;
    row.appendChild(name);

    if (item.line !== undefined) {
      const lineTag = document.createElement('span');
      lineTag.className = 'workspace-badge';
      lineTag.innerText = `L${item.line}`;
      row.appendChild(lineTag);
    } else if (item.size !== undefined) {
      const size = document.createElement('span');
      size.className = 'tree-size';
      size.innerText = formatBytes(item.size);
      row.appendChild(size);
    }

    row.onclick = () => openFile(item.path);
    container.appendChild(row);
  });
}

export async function openFile(filePath) {
  if (!filePath) return;

  const existingTab = openEditorTabs.find((t) => t.path === filePath);
  if (existingTab) {
    setActiveTab(filePath);
    return;
  }

  try {
    const res = await fetch(`/api/files/read?path=${encodeURIComponent(filePath)}`);
    const data = await res.json();
    if (!res.ok || data.status !== 'success') {
      showToast(data.message || 'Failed to read file', 'error');
      return;
    }

    if (data.is_binary) {
      showToast(`${data.name} is a binary file and cannot be opened in the text editor.`, 'info');
      return;
    }

    openEditorTabs.push({
      path: data.path,
      name: data.name,
      language: data.language,
      content: data.content,
      originalContent: data.content,
      size: data.size,
      lines: data.lines,
      dirty: false,
    });

    setActiveTab(data.path);
  } catch (err) {
    showToast(`Error opening file: ${err.message}`, 'error');
  }
}

export function setActiveTab(filePath) {
  activeEditorPath = filePath;
  const tab = openEditorTabs.find((t) => t.path === filePath);

  renderFilesTree();

  const emptyState = document.getElementById('editor-empty-state');
  const mainArea = document.getElementById('editor-main-area');

  if (!tab) {
    if (emptyState) emptyState.style.display = 'flex';
    if (mainArea) mainArea.style.display = 'none';
    renderEditorTabs();
    if (window.updateCoderContextPill) window.updateCoderContextPill(null);
    return;
  }

  if (emptyState) emptyState.style.display = 'none';
  if (mainArea) mainArea.style.display = 'flex';

  renderEditorTabs();

  const pathBadge = document.getElementById('editor-file-path');
  if (pathBadge) pathBadge.innerText = tab.path;

  const langBadge = document.getElementById('editor-file-lang');
  if (langBadge) langBadge.innerText = tab.language || 'Plaintext';

  const metaEl = document.getElementById('editor-file-meta');
  if (metaEl) metaEl.innerText = `${tab.lines || 0} lines • ${formatBytes(tab.size || 0)}`;

  const textarea = document.getElementById('code-editor-textarea');
  if (textarea) {
    textarea.value = tab.content;
    updateLineNumbers(tab.content);
  }

  updateEditorStatus(tab.dirty);
  if (window.updateCoderContextPill) window.updateCoderContextPill(tab.path);
}

export function renderEditorTabs() {
  const bar = document.getElementById('editor-tabs-bar');
  if (!bar) return;

  if (openEditorTabs.length === 0) {
    bar.innerHTML = '<div class="no-tabs-hint">No file open</div>';
    return;
  }

  bar.innerHTML = '';
  openEditorTabs.forEach((tab) => {
    const tabEl = document.createElement('div');
    tabEl.className = `editor-tab ${tab.path === activeEditorPath ? 'active' : ''}`;

    const icon = document.createElement('span');
    icon.innerHTML = getFileIcon(tab.name.split('.').pop());
    tabEl.appendChild(icon);

    const name = document.createElement('span');
    name.innerText = tab.name;
    tabEl.appendChild(name);

    if (tab.dirty) {
      const dot = document.createElement('span');
      dot.className = 'tab-dirty-dot';
      tabEl.appendChild(dot);
    }

    const closeBtn = document.createElement('button');
    closeBtn.className = 'tab-close-btn';
    closeBtn.innerText = 'x';
    closeBtn.onclick = (e) => {
      e.stopPropagation();
      closeTab(tab.path);
    };
    tabEl.appendChild(closeBtn);

    tabEl.onclick = () => setActiveTab(tab.path);
    bar.appendChild(tabEl);
  });
}

export function closeTab(filePath, force = false) {
  if (!filePath) return;
  const norm = filePath.replace(/\\/g, '/').replace(/^\.\//, '');
  const tab = openEditorTabs.find((t) => t.path.replace(/\\/g, '/').replace(/^\.\//, '') === norm);
  if (tab && tab.dirty && !force) {
    if (!confirm(`Save changes to ${tab.name} before closing?`)) {
      // discard
    } else {
      saveActiveFile();
    }
  }

  const idx = openEditorTabs.findIndex((t) => t.path.replace(/\\/g, '/').replace(/^\.\//, '') === norm);
  if (idx !== -1) {
    openEditorTabs.splice(idx, 1);
  }

  const activeNorm = activeEditorPath ? activeEditorPath.replace(/\\/g, '/').replace(/^\.\//, '') : null;
  if (activeNorm === norm) {
    if (openEditorTabs.length > 0) {
      const nextTab = openEditorTabs[Math.max(0, idx - 1)];
      setActiveTab(nextTab.path);
    } else {
      setActiveTab(null);
    }
  } else {
    renderEditorTabs();
  }
}

export function onEditorContentChange() {
  const textarea = document.getElementById('code-editor-textarea');
  if (!textarea || !activeEditorPath) return;

  const tab = openEditorTabs.find((t) => t.path === activeEditorPath);
  if (!tab) return;

  tab.content = textarea.value;
  tab.dirty = tab.content !== tab.originalContent;

  const lines = tab.content.split('\n').length;
  tab.lines = lines;
  const metaEl = document.getElementById('editor-file-meta');
  if (metaEl) metaEl.innerText = `${lines} lines • ${formatBytes(new Blob([tab.content]).size)}`;

  updateLineNumbers(tab.content);
  updateEditorStatus(tab.dirty);
  renderEditorTabs();
}

export function updateLineNumbers(text) {
  const gutter = document.getElementById('editor-line-numbers');
  if (!gutter) return;
  const linesCount = (text || '').split('\n').length || 1;
  let numbersHtml = '';
  for (let i = 1; i <= linesCount; i++) {
    numbersHtml += `${i}\n`;
  }
  gutter.innerText = numbersHtml;
}

export function syncEditorScroll() {
  const textarea = document.getElementById('code-editor-textarea');
  const gutter = document.getElementById('editor-line-numbers');
  if (textarea && gutter) {
    gutter.scrollTop = textarea.scrollTop;
  }
}

export function handleEditorKeydown(event) {
  const textarea = event.target;
  if (event.key === 'Tab') {
    event.preventDefault();
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    textarea.value = textarea.value.substring(0, start) + '    ' + textarea.value.substring(end);
    textarea.selectionStart = textarea.selectionEnd = start + 4;
    onEditorContentChange();
  }
  updateCursorPos();
}

export function updateCursorPos() {
  const textarea = document.getElementById('code-editor-textarea');
  const posEl = document.getElementById('editor-cursor-pos');
  if (!textarea || !posEl) return;
  const pos = textarea.selectionStart;
  const val = textarea.value.substring(0, pos);
  const lines = val.split('\n');
  const lineNum = lines.length;
  const colNum = lines[lines.length - 1].length + 1;
  posEl.innerText = `Ln ${lineNum}, Col ${colNum}`;
}

export function updateEditorStatus(isDirty) {
  const indicator = document.getElementById('editor-status-indicator');
  if (!indicator) return;
  if (isDirty) {
    indicator.className = 'status-dirty';
    indicator.innerText = '[*] Unsaved changes';
  } else {
    indicator.className = 'status-clean';
    indicator.innerText = '[OK] Saved';
  }
}

export async function saveActiveFile() {
  if (!activeEditorPath) return;
  const tab = openEditorTabs.find((t) => t.path === activeEditorPath);
  if (!tab) return;

  const btn = document.getElementById('btn-save-file');
  if (btn) btn.disabled = true;

  try {
    const res = await fetch('/api/files/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: tab.path, content: tab.content }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      tab.originalContent = tab.content;
      tab.dirty = false;
      updateEditorStatus(false);
      renderEditorTabs();
      showToast(`Saved ${tab.name}`, 'success');
    } else {
      showToast(data.message || 'Failed to save file', 'error');
    }
  } catch (err) {
    showToast(`Save error: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

export function initEditorKeybindings() {
  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      saveActiveFile();
    } else if (e.key === 'F5' || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f5')) {
      e.preventDefault();
      if (window.runActiveFile) window.runActiveFile();
    } else if ((e.ctrlKey || e.metaKey) && e.key === '`') {
      e.preventDefault();
      if (window.toggleIntegratedTerminal) window.toggleIntegratedTerminal();
    }
  });

  const textarea = document.getElementById('code-editor-textarea');
  if (textarea) {
    textarea.addEventListener('click', updateCursorPos);
    textarea.addEventListener('keyup', updateCursorPos);
  }
}

export async function promptChangeWorkspace() {
  const currentBadge = document.getElementById('current-workspace-name');
  const currentPath = currentBadge ? currentBadge.title : '';
  const chosen = prompt('Enter or paste folder path to open in Aether Studio (or leave empty to open Windows File Explorer):', currentPath);
  if (chosen === null) return;
  const trimmed = chosen.trim();
  if (!trimmed) {
    await chooseWorkspaceFolderWithExplorer();
    return;
  }
  try {
    const wsRes = await fetch('/api/files/workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: trimmed }),
    });
    const wsData = await wsRes.json();
    if (wsRes.ok && wsData.status === 'success') {
      if (currentBadge) {
        currentBadge.innerText = wsData.workspace_name;
        currentBadge.title = wsData.workspace_root;
      }
      if (window.updateTerminalWorkspaceBadge) window.updateTerminalWorkspaceBadge();
      if (window.updateCoderContextPill) window.updateCoderContextPill(activeEditorPath, wsData.workspace_name);
      await loadFilesTree();
      showToast(`Workspace switched to ${wsData.workspace_name}`, 'success');
    } else {
      showToast(wsData.message || 'Failed to switch workspace', 'error');
    }
  } catch (err) {
    showToast(`Error switching workspace: ${err.message}`, 'error');
  }
}

export async function chooseWorkspaceFolderWithExplorer() {
  try {
    showToast('Opening Windows File Explorer... Please select a folder.', 'info');
    const res = await fetch('/api/files/pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'folder', title: 'Select Workspace Folder for Aether' }),
    });
    const data = await res.json();
    if (data.status === 'success' && data.selected) {
      showToast(`Selected: ${data.name}`, 'info');
      const wsRes = await fetch('/api/files/workspace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: data.selected }),
      });
      const wsData = await wsRes.json();
      if (wsRes.ok && wsData.status === 'success') {
        const wsBadge = document.getElementById('current-workspace-name');
        if (wsBadge) {
          wsBadge.innerText = wsData.workspace_name;
          wsBadge.title = wsData.workspace_root;
        }
        if (window.updateTerminalWorkspaceBadge) window.updateTerminalWorkspaceBadge();
        if (window.updateCoderContextPill) window.updateCoderContextPill(activeEditorPath, wsData.workspace_name);
        await loadFilesTree();
        showToast(`Workspace switched to ${wsData.workspace_name}`, 'success');
      } else {
        showToast(wsData.message || 'Failed to switch workspace', 'error');
      }
    } else if (data.status === 'cancelled') {
      showToast('Folder selection cancelled.', 'info');
    } else if (data.status === 'error') {
      showToast(`Picker error: ${data.message}`, 'error');
    }
  } catch (err) {
    showToast(`Failed to open folder picker: ${err.message}`, 'error');
  }
}

export async function openFileWithExplorer() {
  try {
    showToast('Opening Windows File Explorer... Please select a file.', 'info');
    const res = await fetch('/api/files/pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'file', title: 'Open File in Aether Code Studio' }),
    });
    const data = await res.json();
    if (data.status === 'success' && data.selected) {
      if (data.relative_path) {
        await openFile(data.relative_path);
      } else {
        const parentDir = data.selected.substring(0, Math.max(data.selected.lastIndexOf('/'), data.selected.lastIndexOf('\\')));
        if (parentDir) {
          await fetch('/api/files/workspace', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: parentDir }),
          });
          await loadFilesTree();
          await openFile(data.name);
        } else {
          await openFile(data.selected);
        }
      }
      showToast(`Opened ${data.name}`, 'success');
    } else if (data.status === 'cancelled') {
      showToast('File selection cancelled.', 'info');
    } else if (data.status === 'error') {
      showToast(`Picker error: ${data.message}`, 'error');
    }
  } catch (err) {
    showToast(`Failed to open file picker: ${err.message}`, 'error');
  }
}

export async function organizeWithFolderPicker() {
  try {
    showToast('Opening Windows File Explorer to choose folder to organize...', 'info');
    const res = await fetch('/api/files/pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'folder', title: 'Select Folder to Automatically Organize' }),
    });
    const data = await res.json();
    if (data.status === 'success' && data.selected) {
      if (!confirm(`Organize files in "${data.name}" (${data.selected}) by category (Documents, Code, Images, Archives, Media)?`)) {
        return;
      }
      const orgRes = await fetch('/api/files/organize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: data.selected, strategy: 'by_type' }),
      });
      const orgData = await orgRes.json();
      if (orgRes.ok && orgData.status === 'success') {
        showToast(`Organized ${orgData.count} file(s) in ${data.name}!`, 'success');
        await loadFilesTree();
      } else {
        showToast(orgData.message || 'Organization failed', 'error');
      }
    } else if (data.status === 'cancelled') {
      showToast('Organization cancelled.', 'info');
    } else if (data.status === 'error') {
      showToast(`Picker error: ${data.message}`, 'error');
    }
  } catch (err) {
    showToast(`Failed to open folder picker: ${err.message}`, 'error');
  }
}

export async function organizeSpecificFolder(folderPath) {
  if (!confirm(`Organize loose files in "${folderPath}" into categorized subfolders?`)) {
    return;
  }
  try {
    const res = await fetch('/api/files/organize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folderPath, strategy: 'by_type' }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      showToast(`Organized ${data.count} file(s) in ${folderPath}!`, 'success');
      await loadFilesTree();
    } else {
      showToast(data.message || 'Organization failed', 'error');
    }
  } catch (err) {
    showToast(`Organize error: ${err.message}`, 'error');
  }
}

export async function revealActiveFileInExplorer() {
  if (!activeEditorPath) {
    showToast('No active file to reveal', 'info');
    return;
  }
  await revealPathInExplorer(activeEditorPath);
}

export async function revealPathInExplorer(targetPath) {
  try {
    const res = await fetch('/api/files/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: targetPath }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      showToast('Opened in Windows File Explorer', 'success');
    } else {
      showToast(data.message || 'Failed to reveal in Explorer', 'error');
    }
  } catch (err) {
    showToast(`Explorer error: ${err.message}`, 'error');
  }
}

export async function createFileInFolder(folderPath) {
  const filename = prompt(`Create new file inside "${folderPath}/":`);
  if (!filename || !filename.trim()) return;
  const fullPath = folderPath ? `${folderPath}/${filename.trim()}` : filename.trim();

  try {
    const res = await fetch('/api/files/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: fullPath, is_directory: false }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      showToast(`Created file ${filename.trim()}`, 'success');
      await loadFilesTree();
      openFile(data.path);
    } else {
      showToast(data.message || 'Failed to create file', 'error');
    }
  } catch (err) {
    showToast(`Create error: ${err.message}`, 'error');
  }
}

export async function createFolderInFolder(folderPath) {
  const foldername = prompt(`Create new folder inside "${folderPath}/":`);
  if (!foldername || !foldername.trim()) return;
  const fullPath = folderPath ? `${folderPath}/${foldername.trim()}` : foldername.trim();

  try {
    const res = await fetch('/api/files/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: fullPath, is_directory: true }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      showToast(`Created folder ${foldername.trim()}`, 'success');
      await loadFilesTree();
    } else {
      showToast(data.message || 'Failed to create folder', 'error');
    }
  } catch (err) {
    showToast(`Create error: ${err.message}`, 'error');
  }
}

export async function deleteFileByPath(targetPath) {
  const filename = targetPath.split('/').pop();
  if (!confirm(`Move "${filename}" to Trash?`)) return;

  try {
    const res = await fetch('/api/files/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: targetPath, permanent: false }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      showToast(`Moved ${filename} to Trash`, 'success');
      closeTab(targetPath);
      await loadFilesTree();
    } else {
      showToast(data.message || 'Delete failed', 'error');
    }
  } catch (err) {
    showToast(`Delete error: ${err.message}`, 'error');
  }
}

export async function promptNewFile() {
  const filename = prompt('Enter new file name or path (e.g. demo.py or src/demo.py):');
  if (!filename || !filename.trim()) return;

  try {
    const res = await fetch('/api/files/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filename.trim(), is_directory: false }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      showToast(`Created file ${filename}`, 'success');
      await loadFilesTree();
      openFile(data.path);
    } else {
      showToast(data.message || 'Failed to create file', 'error');
    }
  } catch (err) {
    showToast(`Create error: ${err.message}`, 'error');
  }
}

export async function promptNewFolder() {
  const foldername = prompt('Enter new directory name or path (e.g. modules or src/modules):');
  if (!foldername || !foldername.trim()) return;

  try {
    const res = await fetch('/api/files/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: foldername.trim(), is_directory: true }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      showToast(`Created folder ${foldername}`, 'success');
      await loadFilesTree();
    } else {
      showToast(data.message || 'Failed to create folder', 'error');
    }
  } catch (err) {
    showToast(`Create error: ${err.message}`, 'error');
  }
}

export async function deleteActiveFile() {
  if (!activeEditorPath) return;
  await deleteFileByPath(activeEditorPath);
}

export function toggleFileExplorerPanel() {
  const layout = document.querySelector('.files-workspace-layout');
  if (!layout) return;
  isFileExplorerCollapsed = !isFileExplorerCollapsed;
  layout.classList.toggle('explorer-hidden', isFileExplorerCollapsed);
  const railBtn = document.getElementById('btn-toggle-explorer-rail');
  if (railBtn) {
    railBtn.classList.toggle('active', !isFileExplorerCollapsed);
    railBtn.classList.toggle('rail-btn-collapsed', isFileExplorerCollapsed);
    railBtn.title = isFileExplorerCollapsed ? 'Expand File Explorer (Alt+E / Ctrl+Shift+E)' : 'Collapse File Explorer (Alt+E / Ctrl+Shift+E)';
    railBtn.innerHTML = isFileExplorerCollapsed ? '<span class="rail-label">Show Files</span>' : '<span class="rail-label">Files</span>';
  }
  const emptyToggleBtn = document.getElementById('btn-empty-toggle-files');
  if (emptyToggleBtn) {
    emptyToggleBtn.textContent = isFileExplorerCollapsed ? 'Show File Explorer' : 'Hide File Explorer';
  }
  const expandBtn = document.getElementById('btn-expand-explorer');
  if (expandBtn) {
    expandBtn.style.display = isFileExplorerCollapsed ? 'inline-flex' : 'none';
  }
  try {
    localStorage.setItem('aether_file_explorer_collapsed', isFileExplorerCollapsed ? '1' : '0');
  } catch (e) {}
}

export function askAetherAboutCurrentFile() {
  if (!activeEditorPath) return;
  const tab = openEditorTabs.find((t) => t.path === activeEditorPath);
  const path = tab ? tab.path : activeEditorPath;

  if (window.switchTab) window.switchTab('chat');
  const chatInput = document.getElementById('chat-input');
  if (chatInput) {
    chatInput.value = `Can you inspect and explain what "${path}" does, and suggest any improvements or tests for it?`;
    chatInput.focus();
  }
}

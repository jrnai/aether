/**
 * Project Aether - Side AI Coding Agent (Plan & Execute)
 * Native ES Module
 */

import { escapeHtml, escapeJsString, renderMarkdown, showToast } from '../store.js';
import {
  activeEditorPath,
  closeTab,
  loadFilesTree,
  openEditorTabs,
  openFile,
  updateEditorStatus,
  updateLineNumbers,
} from './editor.js';

export let isCoderPlanMode = true;
export let isCoderActiveFileContext = true;
export let isCoderAgentCollapsed = false;
export let isCoderBusy = false;

export function toggleCoderMode() {
  isCoderPlanMode = !isCoderPlanMode;
  const btn = document.getElementById('btn-coder-mode');
  const runBtn = document.getElementById('btn-send-coder');
  if (btn) {
    btn.classList.toggle('active', isCoderPlanMode);
    btn.innerText = isCoderPlanMode ? 'Plan Mode' : 'Fast Mode';
    btn.title = isCoderPlanMode ? 'Plan first, wait for user approval' : 'Direct execution mode';
  }
  if (runBtn) {
    runBtn.innerText = isCoderPlanMode ? 'Plan & Run' : 'Execute';
  }
  showToast(`Coding Agent: switched to ${isCoderPlanMode ? 'Plan Mode' : 'Fast Mode'}`, 'info');
}

export function toggleActiveFileContext() {
  isCoderActiveFileContext = !isCoderActiveFileContext;
  const pill = document.getElementById('coder-active-file-pill');
  if (pill) {
    pill.classList.toggle('active', isCoderActiveFileContext);
  }
}

export function updateCoderContextPill(filePath, wsName) {
  const nameEl = document.getElementById('coder-context-file-name');
  const wsEl = document.getElementById('coder-context-ws-name');
  const wsBadge = document.getElementById('current-workspace-name');
  const wsPill = document.getElementById('coder-context-ws-pill') || document.querySelector('.context-pill.ws-pill');

  if (filePath !== undefined && nameEl) {
    nameEl.innerText = filePath ? filePath.split(/[/\\]/).pop() : 'None';
    nameEl.title = filePath || 'No file selected';
  }

  const resolvedWs = (wsName || (wsBadge ? wsBadge.innerText : '') || 'aether').trim();
  if (wsEl) {
    wsEl.innerText = resolvedWs;
  }
  if (wsPill) {
    const wsRoot = (wsBadge && wsBadge.title) ? wsBadge.title : resolvedWs;
    wsPill.title = `Active Workspace: ${wsRoot} (Click to switch folder)`;
  }
}

export function sendActiveFileToCoder() {
  if (!activeEditorPath) {
    showToast('No active file open in editor to send.', 'info');
    return;
  }
  if (isCoderAgentCollapsed) {
    toggleCoderAgentPanel();
  }
  const input = document.getElementById('coder-prompt-input');
  if (input) {
    input.value = `Please inspect @${activeEditorPath.split(/[/\\]/).pop()} and `;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
}

export function toggleCoderAgentPanel() {
  const layout = document.querySelector('.files-workspace-layout');
  if (!layout) return;
  isCoderAgentCollapsed = !isCoderAgentCollapsed;
  layout.classList.toggle('agent-hidden', isCoderAgentCollapsed);
  const btn = document.getElementById('btn-toggle-agent-panel');
  if (btn) {
    btn.classList.toggle('active', !isCoderAgentCollapsed);
  }
  try {
    localStorage.setItem('aether_coder_agent_collapsed', isCoderAgentCollapsed ? '1' : '0');
  } catch (e) {}
}

export function suggestCoderPrompt(text) {
  const input = document.getElementById('coder-prompt-input');
  if (input) {
    input.value = text;
    input.focus();
  }
}

export function handleCoderInputKeydown(event) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    sendCoderMessage();
  }
}

export async function sendCoderMessage() {
  const input = document.getElementById('coder-prompt-input');
  if (!input || isCoderBusy) return;
  const prompt = input.value.trim();
  if (!prompt) return;

  const messagesContainer = document.getElementById('coder-chat-messages');
  if (!messagesContainer) return;

  const userMsg = document.createElement('div');
  userMsg.className = 'coder-user-msg';
  userMsg.innerText = prompt;
  messagesContainer.appendChild(userMsg);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;

  input.value = '';
  isCoderBusy = true;
  setCoderStatus(isCoderPlanMode ? 'planning' : 'executing');

  const activeFile = (isCoderActiveFileContext && activeEditorPath) ? activeEditorPath : null;

  if (isCoderPlanMode) {
    // 1. Generate Implementation Plan
    const loadingCard = document.createElement('div');
    loadingCard.className = 'coder-plan-card';
    loadingCard.innerHTML = `
      <div class="plan-header">
        <span class="plan-title">Architecting Implementation Plan...</span>
        <span class="plan-status-badge pending">Analyzing</span>
      </div>
      <div class="loading-spinner" style="padding: 0.8rem;">Synthesizing workspace context and preparing file diffs...</div>
    `;
    messagesContainer.appendChild(loadingCard);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    try {
      const res = await fetch('/api/coder/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, active_file: activeFile, mode: 'plan' }),
      });
      const data = await res.json();
      if (!res.ok || data.status !== 'success') {
        throw new Error(data.message || 'Failed to generate implementation plan.');
      }
      loadingCard.remove();
      renderCoderPlanCard(data.plan_id, data.plan, prompt, activeFile);
    } catch (err) {
      loadingCard.remove();
      const errCard = document.createElement('div');
      errCard.className = 'coder-plan-card';
      errCard.style.borderColor = 'rgba(244, 63, 94, 0.4)';
      errCard.style.borderTopColor = '#f43f5e';
      errCard.innerHTML = `
        <div class="plan-header">
          <span class="plan-title" style="color:#f43f5e;">Plan Generation Failed</span>
          <span class="plan-status-badge rejected">Error</span>
        </div>
        <p style="font-size:0.8rem; color:#fda4af;">${escapeHtml(err.message)}</p>
      `;
      messagesContainer.appendChild(errCard);
    } finally {
      isCoderBusy = false;
      setCoderStatus('ready');
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
  } else {
    // 2. Direct Execution Mode
    const execCard = document.createElement('div');
    execCard.className = 'coder-execution-card';
    execCard.innerHTML = `
      <div class="exec-header">
        <span class="exec-title" style="color:#FBBF24;">Executing Direct Implementation...</span>
        <span class="plan-status-badge pending">Running</span>
      </div>
      <div class="loading-spinner" style="padding: 0.8rem;">Applying code edits to workspace files...</div>
    `;
    messagesContainer.appendChild(execCard);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    try {
      const res = await fetch('/api/coder/execute/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, active_file: activeFile }),
      });
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);

      const progressEl = execCard.querySelector('.loading-spinner');
      let completedData = null;

      await consumeCoderStream(res, progressEl, (result) => {
        completedData = result;
      });

      execCard.remove();
      if (completedData) {
        renderCoderExecutionCard(completedData.response, completedData.touched_files);
        syncTouchedFiles(completedData.touched_files);
      }
    } catch (err) {
      execCard.remove();
      showToast(`Coding error: ${err.message}`, 'error');
    } finally {
      isCoderBusy = false;
      setCoderStatus('ready');
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
  }
}

export async function consumeCoderStream(res, progressEl, onDone) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let finalResult = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop();

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      const jsonStr = trimmed.slice(5).trim();
      if (!jsonStr) continue;

      try {
        const ev = JSON.parse(jsonStr);
        if (ev.type === 'tool_start' && progressEl) {
          const fn = ev.tool || 'tool';
          progressEl.innerText = `Running tool: ${fn}...`;
        } else if (ev.type === 'tool_end' && progressEl) {
          const fn = ev.tool || 'tool';
          progressEl.innerText = `Finished: ${fn}`;
        } else if (ev.type === 'execution_done') {
          finalResult = ev;
        } else if (ev.type === 'error') {
          throw new Error(ev.message || 'Execution error');
        }
      } catch (pe) {
        console.debug('Failed parsing coder SSE chunk:', pe, jsonStr);
      }
    }
  }

  if (finalResult && typeof onDone === 'function') {
    onDone(finalResult);
  }
}

export function renderCoderPlanCard(planId, plan, prompt, activeFile) {
  const container = document.getElementById('coder-chat-messages');
  if (!container) return;

  const card = document.createElement('div');
  card.className = 'coder-plan-card';
  card.id = `plan-card-${planId}`;

  const filesHtml = (plan.files || []).map(f => {
    const actionClass = (f.action || 'modify').toLowerCase();
    const actionLabel = actionClass === 'create' ? '[NEW]' : actionClass === 'delete' ? '[DELETE]' : '[MODIFY]';
    return `
      <div class="plan-file-item">
        <span class="action-badge ${actionClass}">${actionLabel}</span>
        <span class="plan-file-path" onclick="openFile('${escapeJsString(f.path)}')" title="Click to view file in editor">${escapeHtml(f.path)}</span>
        <span class="plan-file-desc">— ${escapeHtml(f.description || '')}</span>
      </div>
    `;
  }).join('');

  const stepsHtml = (plan.steps || []).map(s => `<li>${escapeHtml(s)}</li>`).join('');

  card.innerHTML = `
    <div class="plan-header">
      <span class="plan-title">Proposed Implementation Plan</span>
      <span class="plan-status-badge pending" id="badge-${planId}">Pending Review</span>
    </div>
    <div class="plan-goal"><strong>Goal:</strong> ${escapeHtml(plan.goal || prompt)}</div>
    ${plan.rationale ? `<div style="font-size:0.78rem; color:var(--text-dim); font-style:italic;">${escapeHtml(plan.rationale)}</div>` : ''}

    <div class="plan-section-title">Proposed File Changes</div>
    <div class="plan-files-list">${filesHtml || '<span style="color:var(--text-dim); font-size:0.75rem;">No file paths specified.</span>'}</div>

    ${stepsHtml ? `
      <div class="plan-section-title">Execution Steps</div>
      <ol class="plan-steps-list">${stepsHtml}</ol>
    ` : ''}

    ${plan.verification ? `
      <div class="plan-section-title">Verification</div>
      <div style="font-size:0.76rem; color:#38BDF8; font-family:monospace; background:rgba(0,0,0,0.2); padding:0.25rem 0.5rem; border-radius:4px;">
        ${escapeHtml(plan.verification)}
      </div>
    ` : ''}

    <div class="plan-actions" id="actions-${planId}">
      <button class="btn-approve-plan" onclick="approveAndExecutePlan('${planId}')">
        Approve & Implement
      </button>
      <button class="btn-reject-plan" onclick="rejectPlan('${planId}')">
        Reject
      </button>
    </div>
  `;

  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
}

export async function approveAndExecutePlan(planId) {
  if (isCoderBusy) return;

  const actionsBox = document.getElementById(`actions-${planId}`);
  const badge = document.getElementById(`badge-${planId}`);
  if (badge) {
    badge.className = 'plan-status-badge approved';
    badge.innerText = 'Approved & Running';
  }
  if (actionsBox) {
    actionsBox.innerHTML = `<span style="font-size:0.78rem; color:#10B981; display:flex; align-items:center; gap:0.4rem;">Executing plan changes...</span>`;
  }

  isCoderBusy = true;
  setCoderStatus('executing');

  const messagesContainer = document.getElementById('coder-chat-messages');

  try {
    const res = await fetch('/api/coder/execute/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_id: planId }),
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);

    const progressEl = actionsBox ? actionsBox.querySelector('span') : null;
    let completedData = null;

    await consumeCoderStream(res, progressEl, (result) => {
      completedData = result;
    });

    if (badge) {
      badge.className = 'plan-status-badge approved';
      badge.innerText = 'Completed';
    }
    if (actionsBox) {
      actionsBox.innerHTML = `<span style="font-size:0.78rem; color:#34D399; font-weight:600;">Approved & Implemented</span>`;
    }

    if (completedData) {
      renderCoderExecutionCard(completedData.response, completedData.touched_files);
      syncTouchedFiles(completedData.touched_files);
    }
    showToast('Implementation completed successfully!', 'success');
  } catch (err) {
    if (badge) {
      badge.className = 'plan-status-badge rejected';
      badge.innerText = 'Failed';
    }
    if (actionsBox) {
      actionsBox.innerHTML = `<span style="font-size:0.78rem; color:#f43f5e;">Error: ${escapeHtml(err.message)}</span>`;
    }
    showToast(`Execution error: ${err.message}`, 'error');
  } finally {
    isCoderBusy = false;
    setCoderStatus('ready');
    if (messagesContainer) messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }
}

export function rejectPlan(planId) {
  const badge = document.getElementById(`badge-${planId}`);
  const actionsBox = document.getElementById(`actions-${planId}`);
  if (badge) {
    badge.className = 'plan-status-badge rejected';
    badge.innerText = 'Rejected';
  }
  if (actionsBox) {
    actionsBox.innerHTML = `<span style="font-size:0.78rem; color:var(--text-dim); font-style:italic;">Plan rejected by user.</span>`;
  }
  showToast('Implementation plan rejected.', 'info');
}

export function renderCoderExecutionCard(responseText, touchedFiles) {
  const container = document.getElementById('coder-chat-messages');
  if (!container) return;

  const card = document.createElement('div');
  card.className = 'coder-execution-card';

  let touchedHtml = '';
  if (touchedFiles && touchedFiles.length > 0) {
    const fileItems = touchedFiles.map((file, idx) => {
      const isCreated = file.action === 'created';
      const isDeleted = file.action === 'deleted';
      let actionBadge = '<span class="action-badge modify">[MODIFIED]</span>';
      if (isCreated) actionBadge = '<span class="action-badge create">[NEW]</span>';
      else if (isDeleted) actionBadge = '<span class="action-badge delete">[DELETED]</span>';

      const diffLines = (file.diff || '').split('\n').map(line => {
        let cls = 'diff-line-ctx';
        if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-add';
        else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-del';
        else if (line.startsWith('@@')) cls = 'diff-hunk';
        return `<div class="diff-line ${cls}">${escapeHtml(line)}</div>`;
      }).join('');

      return `
        <div class="touched-file-card">
          <div class="touched-file-bar" ${isDeleted ? '' : `onclick="openFile('${escapeJsString(file.path)}')"`} style="${isDeleted ? 'cursor:default;' : 'cursor:pointer;'}">
            <div class="touched-file-info">
              ${actionBadge}
              <span class="touched-file-path" title="${isDeleted ? 'File deleted' : 'Open in editor'}">${escapeHtml(file.path)}</span>
            </div>
            <div class="touched-file-stats">
              <span class="stat-add">+${file.additions || 0}</span>
              <span class="stat-del">-${file.deletions || 0}</span>
              <button class="diff-view-toggle" onclick="event.stopPropagation(); toggleDiffDrawer('diff-drawer-${idx}')">Diff [v]</button>
            </div>
          </div>
          <div id="diff-drawer-${idx}" class="diff-content-drawer" style="display: none;">
            ${diffLines || '<div style="color:var(--text-dim);">No diff available</div>'}
          </div>
        </div>
      `;
    }).join('');

    touchedHtml = `
      <div class="touched-files-box">
        <div class="touched-files-title">
          <span>Files Changed (${touchedFiles.length})</span>
          <span style="font-size:0.7rem; color:var(--text-dim);">Click file to open in editor</span>
        </div>
        ${fileItems}
      </div>
    `;
  }

  card.innerHTML = `
    <div class="exec-header">
      <span class="exec-title">Changes Applied</span>
      <span class="plan-status-badge approved">Done</span>
    </div>
    <div class="exec-response-text">${renderMarkdown(responseText || 'Implementation completed.')}</div>
    ${touchedHtml}
  `;

  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
}

export function toggleDiffDrawer(drawerId) {
  const drawer = document.getElementById(drawerId);
  if (drawer) {
    drawer.style.display = drawer.style.display === 'none' ? 'block' : 'none';
  }
}

export async function syncTouchedFiles(touchedFiles) {
  loadFilesTree();

  if (!touchedFiles || touchedFiles.length === 0) return;

  for (const f of touchedFiles) {
    if (f.action === 'deleted') {
      closeTab(f.path, true);
    } else {
      await reloadTabIfOpen(f.path);
    }
  }
}

export async function reloadTabIfOpen(filePath) {
  if (!filePath) return;
  const norm = filePath.replace(/\\/g, '/').replace(/^\.\//, '');
  const tab = openEditorTabs.find(t => t.path.replace(/\\/g, '/').replace(/^\.\//, '') === norm);
  if (!tab) return;

  try {
    const res = await fetch(`/api/files/read?path=${encodeURIComponent(tab.path)}`);
    if (res.status === 404) {
      closeTab(tab.path, true);
      showToast(`${tab.name} was removed and closed`, 'info');
      return;
    }
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      tab.content = data.content;
      tab.originalContent = data.content;
      tab.lines = data.lines;
      tab.size = data.size;
      tab.dirty = false;

      if (activeEditorPath && activeEditorPath.replace(/\\/g, '/').replace(/^\.\//, '') === norm) {
        const textarea = document.getElementById('code-editor-textarea');
        if (textarea) {
          textarea.value = tab.content;
          updateLineNumbers(tab.content);
        }
        updateEditorStatus(false);
      }
      showToast(`Synced ${tab.name} in editor`, 'info');
    } else if (data.status === 'error' && data.message && data.message.includes('not exist')) {
      closeTab(tab.path, true);
    }
  } catch (e) {
    console.debug('Failed to sync editor tab:', e);
  }
}

export function setCoderStatus(status) {
  const dot = document.getElementById('coder-status-dot');
  if (!dot) return;
  dot.className = `coder-status-dot ${status}`;
}

export async function clearCoderHistory() {
  if (!confirm('Clear coding agent conversation history?')) return;
  try {
    await fetch('/api/coder/clear', { method: 'POST' });
    const messagesContainer = document.getElementById('coder-chat-messages');
    if (messagesContainer) {
      messagesContainer.innerHTML = `
        <div class="coder-welcome-card">
          <h4>Antigravity Pair Programmer</h4>
          <p>Describe what you want to build, refactor, or fix. I will analyze your workspace, draft an explicit implementation plan, and wait for your approval before modifying files.</p>
          <div class="coder-suggestions">
            <button class="chip" onclick="suggestCoderPrompt('Add comprehensive unit tests for the active file')">Add Unit Tests</button>
            <button class="chip" onclick="suggestCoderPrompt('Refactor functions with full type annotations and docstrings')">Refactor & Types</button>
            <button class="chip" onclick="suggestCoderPrompt('Explain the architecture and data flow of this file')">Explain Code</button>
            <button class="chip" onclick="suggestCoderPrompt('Run pytest tests/unit and fix any failing tests')">Run Tests & Fix</button>
          </div>
        </div>
      `;
    }
    showToast('Coding agent history cleared.', 'info');
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

export function initCoderAgent() {
  try {
    if (localStorage.getItem('aether_coder_agent_collapsed') === '1') {
      toggleCoderAgentPanel();
    }
  } catch (e) {}
}

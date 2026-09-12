/**
 * Project Aether - Integrated Terminal & Runner Controller (VS Code Style)
 * Native ES Module with interactive WebSocket & HTTP fallback
 */

import { showToast } from '../store.js';
import { activeEditorPath, openEditorTabs, saveActiveFile } from './editor.js';

let terminalCommandHistory = [];
let terminalHistoryIndex = -1;
let terminalHistoryDraft = '';
export let isTerminalExecuting = false;
let terminalWs = null;
let activeTerminalStreamingLine = null;
let isTerminalResizeInitialized = false;

export function connectTerminalWebSocket() {
  if (terminalWs && (terminalWs.readyState === WebSocket.OPEN || terminalWs.readyState === WebSocket.CONNECTING)) {
    return terminalWs;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/terminal/ws`;
  try {
    terminalWs = new WebSocket(wsUrl);
  } catch (e) {
    console.warn('Could not initialize terminal WebSocket:', e);
    return null;
  }

  terminalWs.onopen = () => {
    console.debug('Terminal WebSocket connected');
  };

  terminalWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleTerminalWsMessage(msg);
    } catch (e) {
      appendTerminalStream(event.data);
    }
  };

  terminalWs.onclose = () => {
    if (isTerminalExecuting) {
      setTerminalExecuting(false);
    }
  };

  terminalWs.onerror = (err) => {
    console.debug('Terminal WebSocket error:', err);
  };

  return terminalWs;
}

function handleTerminalWsMessage(msg) {
  if (!msg) return;
  if (msg.type === 'output') {
    appendTerminalStream(msg.data || '');
  } else if (msg.type === 'exit') {
    finalizeTerminalStream();
    const code = typeof msg.exit_code === 'number' ? msg.exit_code : 0;
    if (code === 0) {
      appendTerminalLine('[Process completed - exit code 0]', 'terminal-exit-code success');
    } else {
      appendTerminalLine(`[Process terminated - exit code ${code}]`, 'terminal-exit-code error');
    }
    setTerminalExecuting(false);
  } else if (msg.type === 'error') {
    finalizeTerminalStream();
    appendTerminalLine(`Error: ${msg.message || 'Command execution error'}`, 'terminal-stderr');
    appendTerminalLine('[Process failed]', 'terminal-exit-code error');
    setTerminalExecuting(false);
  }
}

function appendTerminalStream(text) {
  const out = document.getElementById('terminal-output');
  if (!out || !text) return;

  if (!activeTerminalStreamingLine) {
    activeTerminalStreamingLine = document.createElement('div');
    activeTerminalStreamingLine.className = 'terminal-line terminal-stdout';
    out.appendChild(activeTerminalStreamingLine);
  }

  activeTerminalStreamingLine.textContent += text;
  scrollTerminalToBottom();
}

function finalizeTerminalStream() {
  activeTerminalStreamingLine = null;
}

function setTerminalExecuting(executing) {
  isTerminalExecuting = !!executing;
  const statusIndicator = document.getElementById('terminal-status-indicator');
  const runBtn = document.getElementById('btn-terminal-run');
  const stopBtn = document.getElementById('btn-terminal-stop');
  const input = document.getElementById('terminal-input');

  if (statusIndicator) {
    if (isTerminalExecuting) {
      statusIndicator.className = 'terminal-status-indicator running';
      statusIndicator.innerText = 'RUNNING';
    } else {
      statusIndicator.className = 'terminal-status-indicator ready';
      statusIndicator.innerText = 'READY';
    }
  }

  if (stopBtn) {
    stopBtn.style.display = isTerminalExecuting ? 'inline-block' : 'none';
  }

  if (runBtn) {
    if (isTerminalExecuting) {
      runBtn.innerText = 'Send';
      runBtn.title = 'Send input to process (Enter)';
      runBtn.disabled = false;
    } else {
      runBtn.innerText = 'Run';
      runBtn.title = 'Execute command (Enter)';
      runBtn.disabled = false;
    }
  }

  if (input) {
    if (isTerminalExecuting) {
      input.placeholder = 'Send input to running process (e.g. rock, y/n)...';
    } else {
      input.placeholder = 'Type a command (e.g. python main.py, pytest)...';
    }
    input.focus();
  }
}

export async function cancelTerminalCommand() {
  if (!isTerminalExecuting) return;
  appendTerminalLine('^C', 'terminal-stderr');
  if (terminalWs && terminalWs.readyState === WebSocket.OPEN) {
    terminalWs.send(JSON.stringify({ type: 'kill' }));
  }
  try {
    await fetch('/api/terminal/kill', { method: 'POST' });
  } catch (e) {
    console.debug('Failed to send terminal kill request:', e);
  }
  setTerminalExecuting(false);
}

export function initTerminalResize() {
  if (isTerminalResizeInitialized) return;
  const handle = document.getElementById('terminal-resize-handle');
  const drawer = document.getElementById('editor-terminal-drawer');
  if (!handle || !drawer) return;

  isTerminalResizeInitialized = true;

  let startY = 0;
  let startHeight = 0;
  let isDragging = false;

  const onPointerDown = (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    e.preventDefault();
    isDragging = true;
    startY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
    startHeight = drawer.offsetHeight;

    drawer.classList.add('resizing');
    document.body.classList.add('resizing-terminal');
    handle.classList.add('active');

    window.addEventListener('mousemove', onPointerMove, { passive: false });
    window.addEventListener('mouseup', onPointerUp);
    window.addEventListener('touchmove', onPointerMove, { passive: false });
    window.addEventListener('touchend', onPointerUp);
  };

  const onPointerMove = (e) => {
    if (!isDragging) return;
    e.preventDefault();
    const currentY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
    const deltaY = startY - currentY;
    const minHeight = 100;
    const maxHeight = Math.round(window.innerHeight * 0.85);
    const targetHeight = Math.max(minHeight, Math.min(maxHeight, startHeight + deltaY));

    drawer.style.height = `${targetHeight}px`;
  };

  const onPointerUp = () => {
    if (!isDragging) return;
    isDragging = false;

    drawer.classList.remove('resizing');
    document.body.classList.remove('resizing-terminal');
    handle.classList.remove('active');

    window.removeEventListener('mousemove', onPointerMove);
    window.removeEventListener('mouseup', onPointerUp);
    window.removeEventListener('touchmove', onPointerMove);
    window.removeEventListener('touchend', onPointerUp);

    const finalHeight = drawer.offsetHeight;
    try {
      localStorage.setItem('aether_terminal_height', String(finalHeight));
    } catch (err) {}
    scrollTerminalToBottom();
  };

  handle.addEventListener('mousedown', onPointerDown);
  handle.addEventListener('touchstart', onPointerDown, { passive: false });

  const toggleExpand = () => {
    const currentH = drawer.offsetHeight;
    const halfH = Math.round(window.innerHeight * 0.5);
    const defaultH = 240;
    const targetH = currentH > 320 ? defaultH : halfH;

    drawer.style.height = `${targetH}px`;
    try {
      localStorage.setItem('aether_terminal_height', String(targetH));
    } catch (err) {}
    scrollTerminalToBottom();
  };

  handle.addEventListener('dblclick', (e) => {
    e.preventDefault();
    toggleExpand();
  });

  const headerBar = drawer.querySelector('.terminal-header-bar');
  if (headerBar) {
    headerBar.addEventListener('dblclick', (e) => {
      if (e.target.closest('button')) return;
      toggleExpand();
    });
  }
}

export function toggleIntegratedTerminal(forceOpen) {
  const drawer = document.getElementById('editor-terminal-drawer');
  const railBtn = document.getElementById('btn-toggle-terminal-rail');
  const toolbarBtn = document.getElementById('btn-toggle-terminal');
  if (!drawer) return;

  const shouldOpen = typeof forceOpen === 'boolean' ? forceOpen : drawer.style.display === 'none';
  if (shouldOpen) {
    drawer.style.display = 'flex';
    if (railBtn) railBtn.classList.add('active');
    if (toolbarBtn) toolbarBtn.classList.add('active');

    try {
      const savedH = localStorage.getItem('aether_terminal_height');
      if (savedH) {
        const parsedH = parseInt(savedH, 10);
        if (!isNaN(parsedH) && parsedH >= 100 && parsedH <= window.innerHeight * 0.85) {
          drawer.style.height = `${parsedH}px`;
        }
      }
    } catch (e) {}

    initTerminalResize();
    updateTerminalWorkspaceBadge();
    const input = document.getElementById('terminal-input');
    if (input) {
      setTimeout(() => input.focus(), 60);
    }
    scrollTerminalToBottom();
    connectTerminalWebSocket();
  } else {
    drawer.style.display = 'none';
    if (railBtn) railBtn.classList.remove('active');
    if (toolbarBtn) toolbarBtn.classList.remove('active');
  }
}

export function updateTerminalWorkspaceBadge() {
  const wsBadge = document.getElementById('current-workspace-name');
  const termWsTag = document.getElementById('terminal-workspace-tag');
  const promptPrefix = document.getElementById('terminal-prompt-prefix');
  const wsName = wsBadge ? (wsBadge.innerText || 'aether').trim() : 'aether';
  if (termWsTag) termWsTag.innerText = wsName;
  if (promptPrefix) promptPrefix.innerText = `${wsName}>`;
}

export function clearTerminalOutput() {
  finalizeTerminalStream();
  const out = document.getElementById('terminal-output');
  if (!out) return;
  out.innerHTML = `
    <div class="terminal-line terminal-system-msg">Aether Integrated Terminal [Workspace Shell]</div>
    <div class="terminal-line terminal-system-msg">Type commands below or click 'Run File' to execute active scripts.</div>
  `;
}

export function scrollTerminalToBottom() {
  const out = document.getElementById('terminal-output');
  if (out) {
    out.scrollTop = out.scrollHeight;
  }
}

export function appendTerminalLine(text, className = '') {
  finalizeTerminalStream();
  const out = document.getElementById('terminal-output');
  if (!out) return;
  const line = document.createElement('div');
  line.className = `terminal-line ${className}`.trim();
  line.textContent = text;
  out.appendChild(line);
  scrollTerminalToBottom();
}

export async function executeTerminalCommand(command) {
  const rawCmd = (command || '').trim();
  if (!rawCmd) return;

  toggleIntegratedTerminal(true);

  if (isTerminalExecuting) {
    submitTerminalCommand();
    return;
  }

  const wsBadge = document.getElementById('current-workspace-name');
  const wsName = wsBadge ? (wsBadge.innerText || 'aether').trim() : 'aether';
  appendTerminalLine(`${wsName}> ${rawCmd}`, 'terminal-cmd-line');

  if (terminalCommandHistory.length === 0 || terminalCommandHistory[terminalCommandHistory.length - 1] !== rawCmd) {
    terminalCommandHistory.push(rawCmd);
  }
  terminalHistoryIndex = -1;
  terminalHistoryDraft = '';

  setTerminalExecuting(true);
  finalizeTerminalStream();

  const ws = connectTerminalWebSocket();
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'run', command: rawCmd }));
      return;
    } else {
      const onOpen = () => {
        ws.removeEventListener('open', onOpen);
        ws.removeEventListener('error', onError);
        ws.send(JSON.stringify({ type: 'run', command: rawCmd }));
      };
      const onError = () => {
        ws.removeEventListener('open', onOpen);
        ws.removeEventListener('error', onError);
        fallbackHttpRun(rawCmd);
      };
      ws.addEventListener('open', onOpen);
      ws.addEventListener('error', onError);
      return;
    }
  }

  await fallbackHttpRun(rawCmd);
}

async function fallbackHttpRun(rawCmd) {
  try {
    const res = await fetch('/api/terminal/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: rawCmd, timeout_seconds: 45 }),
    });
    const data = await res.json();

    if (data.status === 'success') {
      if (data.stdout && data.stdout.trim()) {
        appendTerminalLine(data.stdout, 'terminal-stdout');
      }
      if (data.stderr && data.stderr.trim()) {
        appendTerminalLine(data.stderr, 'terminal-stderr');
      }
      if (!data.stdout && !data.stderr) {
        appendTerminalLine('(command completed with no output)', 'terminal-system-msg');
      }
      const exitCode = typeof data.exit_code === 'number' ? data.exit_code : 0;
      if (exitCode === 0) {
        appendTerminalLine('[Process completed - exit code 0]', 'terminal-exit-code success');
      } else {
        appendTerminalLine(`[Process terminated - exit code ${exitCode}]`, 'terminal-exit-code error');
      }
    } else {
      appendTerminalLine(`Error: ${data.message || 'Command rejected'}`, 'terminal-stderr');
      appendTerminalLine('[Process failed]', 'terminal-exit-code error');
    }
  } catch (err) {
    appendTerminalLine(`Network / execution error: ${err.message}`, 'terminal-stderr');
    appendTerminalLine('[Process failed]', 'terminal-exit-code error');
  } finally {
    setTerminalExecuting(false);
  }
}

export function submitTerminalCommand() {
  const input = document.getElementById('terminal-input');
  if (!input) return;
  const val = input.value;

  if (isTerminalExecuting) {
    input.value = '';
    appendTerminalLine(val, 'terminal-stdin-echo');
    if (terminalWs && terminalWs.readyState === WebSocket.OPEN) {
      terminalWs.send(JSON.stringify({ type: 'input', data: val + '\n' }));
    }
    return;
  }

  const cmd = val.trim();
  if (!cmd) return;
  input.value = '';
  executeTerminalCommand(cmd);
}

export function handleTerminalKeydown(event) {
  const input = event.target;
  if (event.key === 'Enter') {
    event.preventDefault();
    submitTerminalCommand();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'c') {
    if (isTerminalExecuting && !window.getSelection().toString()) {
      event.preventDefault();
      cancelTerminalCommand();
      return;
    }
  }
  if (event.key === 'ArrowUp') {
    if (isTerminalExecuting) return;
    event.preventDefault();
    if (terminalCommandHistory.length === 0) return;
    if (terminalHistoryIndex === -1) {
      terminalHistoryDraft = input.value;
      terminalHistoryIndex = terminalCommandHistory.length - 1;
    } else if (terminalHistoryIndex > 0) {
      terminalHistoryIndex--;
    }
    input.value = terminalCommandHistory[terminalHistoryIndex] || '';
    return;
  }
  if (event.key === 'ArrowDown') {
    if (isTerminalExecuting) return;
    event.preventDefault();
    if (terminalHistoryIndex === -1) return;
    if (terminalHistoryIndex < terminalCommandHistory.length - 1) {
      terminalHistoryIndex++;
      input.value = terminalCommandHistory[terminalHistoryIndex] || '';
    } else {
      terminalHistoryIndex = -1;
      input.value = terminalHistoryDraft || '';
    }
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    clearTerminalOutput();
    return;
  }
}

export async function runActiveFile() {
  if (!activeEditorPath) {
    showToast('No file is currently open to run.', 'warning');
    return;
  }

  const tab = openEditorTabs.find((t) => t.path === activeEditorPath);
  if (tab && tab.dirty) {
    await saveActiveFile();
  }

  const normalizedPath = activeEditorPath.replace(/\\/g, '/').replace(/^\.\//, '');
  const fileName = normalizedPath.split('/').pop() || '';
  const lowerName = fileName.toLowerCase();

  let cmd = '';
  if (lowerName.endsWith('.py')) {
    if (lowerName.startsWith('test_') || lowerName.endsWith('_test.py')) {
      cmd = `pytest "${normalizedPath}"`;
    } else {
      cmd = `python -u "${normalizedPath}"`;
    }
  } else if (lowerName.endsWith('.js') || lowerName.endsWith('.mjs') || lowerName.endsWith('.cjs')) {
    cmd = `node "${normalizedPath}"`;
  } else if (lowerName.endsWith('.ts')) {
    cmd = `npx ts-node "${normalizedPath}"`;
  } else if (lowerName.endsWith('.json')) {
    cmd = `python -m json.tool "${normalizedPath}"`;
  } else {
    cmd = `python -u "${normalizedPath}"`;
  }

  showToast(`Running ${fileName}...`, 'info');
  await executeTerminalCommand(cmd);
}

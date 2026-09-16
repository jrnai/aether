/**
 * Project Aether - Web Dashboard Frontend Controller
 * Native ES Module Entry Point
 */

import {
  escapeHtml,
  escapeJsString,
  isTabVisible,
  renderMarkdown,
  showToast,
  store,
} from './store.js';

import {
  closeVoiceOverlay,
  copyBriefing,
  fetchOverview,
  fetchVoiceStatus,
  fetchWeather,
  handleVoiceBadgeClick,
  handleVoiceOverlayBackdropClick,
  handleWeatherLocationInput,
  handleWeatherLocationKeydown,
  initVoiceEventsSSE,
  listenNow,
  loadCachedBriefingFromStorage,
  openVoiceOverlay,
  regenerateBriefing,
  saveWeatherLocationManual,
  selectWeatherLocation,
  toggleVoiceActivation,
  toggleWeatherLocationInput,
} from './modules/overview.js';

import {
  fetchAiDigest,
  fetchNews,
  refreshAiDigest,
  setNewsFilter,
} from './modules/news.js';

import {
  fetchCalendar,
  setCalendarView,
  prevMonth,
  nextMonth,
  goToToday,
} from './modules/calendar.js';

import {
  clearEmailSearch,
  fetchEmails,
  filterEmailsDays,
  filterEmailsFlag,
  filterEmailsStatus,
  onEmailSearch,
  toggleEmailFlag,
} from './modules/mail.js';

import {
  addNewTask,
  cycleTaskPriority,
  deleteTaskItem,
  fetchTasks,
  filterPriority,
  filterTasks,
  quickAddTask,
  toggleTaskComplete,
} from './modules/tasks.js';

import {
  changeActiveModel,
  fetchModels,
} from './modules/models.js';

import {
  clearChatHistory,
  handleImageFileSelect,
  initChatMediaHandlers,
  isChatPending,
  loadChatHistory,
  removeStagedImage,
  sendChatMessage,
  snapDesktopScreen,
  toggleTraceDrawer,
  triggerImageAttachment,
} from './modules/chat.js';

import {
  activeEditorPath,
  askAetherAboutCurrentFile,
  chooseWorkspaceFolderWithExplorer,
  closeTab,
  deleteActiveFile,
  deleteFileByPath,
  fileTreeData,
  handleEditorKeydown,
  initEditorKeybindings,
  loadFilesTree,
  onEditorContentChange,
  onFileSearchInput,
  openEditorTabs,
  openFile,
  openFileWithExplorer,
  organizeWithFolderPicker,
  promptChangeWorkspace,
  promptNewFile,
  promptNewFolder,
  refreshFilesTreeBtn,
  revealActiveFileInExplorer,
  revealPathInExplorer,
  saveActiveFile,
  setActiveTab,
  syncEditorScroll,
  toggleFileExplorerPanel,
  toggleGrepSearch,
} from './modules/editor.js';

import {
  cancelTerminalCommand,
  clearTerminalOutput,
  connectTerminalWebSocket,
  executeTerminalCommand,
  handleTerminalKeydown,
  initTerminalResize,
  runActiveFile,
  submitTerminalCommand,
  toggleIntegratedTerminal,
  updateTerminalWorkspaceBadge,
} from './modules/terminal.js';

import {
  approveAndExecutePlan,
  clearCoderHistory,
  handleCoderInputKeydown,
  initCoderAgent,
  rejectPlan,
  sendActiveFileToCoder,
  sendCoderMessage,
  suggestCoderPrompt,
  toggleActiveFileContext,
  toggleCoderAgentPanel,
  toggleCoderMode,
  toggleDiffDrawer,
  updateCoderContextPill,
} from './modules/coder.js';

// =============================================================================
// Dashboard Navigation & Layout State
// =============================================================================
export let currentTab = 'overview';

export function switchTab(tabId) {
  currentTab = tabId;
  store.currentTab = tabId;

  // Update nav buttons
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.classList.toggle('active', btn.id === `nav-${tabId}`);
  });

  // Update tab panels
  document.querySelectorAll('.tab-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id === `tab-${tabId}`);
  });

  // Trigger tab-specific refresh if needed
  if (tabId === 'calendar') fetchCalendar();
  if (tabId === 'inbox') fetchEmails();
  if (tabId === 'tasks') fetchTasks();
  if (tabId === 'news') {
    fetchNews();
    fetchAiDigest();
  }
  if (tabId === 'files') {
    if (!fileTreeData) loadFilesTree();
    else if (typeof updateCoderContextPill === 'function') updateCoderContextPill(activeEditorPath);
  }
  if (tabId === 'chat') {
    const chatContainer = document.getElementById('chat-messages');
    if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
    const input = document.getElementById('chat-input');
    if (input) input.focus();
  }
}

// =============================================================================
// Collapsible Sidebar Controller
// =============================================================================
export function toggleSidebar() {
  const layout = document.querySelector('.app-layout');
  if (!layout) return;

  layout.classList.toggle('sidebar-collapsed');
  const isCollapsed = layout.classList.contains('sidebar-collapsed');
  try {
    localStorage.setItem('aether_sidebar_collapsed', isCollapsed ? 'true' : 'false');
  } catch (e) {}

  updateSidebarToggleAttributes(isCollapsed);
}

export function updateSidebarToggleAttributes(isCollapsed) {
  const collapseBtn = document.getElementById('sidebar-collapse-btn');
  if (collapseBtn) {
    collapseBtn.title = isCollapsed ? 'Expand Sidebar (Ctrl+B)' : 'Collapse Sidebar (Ctrl+B)';
    collapseBtn.classList.toggle('collapsed', isCollapsed);
  }
}

export function initSidebarCollapse() {
  try {
    const saved = localStorage.getItem('aether_sidebar_collapsed');
    if (saved === 'true') {
      const layout = document.querySelector('.app-layout');
      if (layout) {
        layout.classList.add('sidebar-collapsed');
        updateSidebarToggleAttributes(true);
      }
    }
  } catch (e) {}

  document.addEventListener('keydown', (e) => {
    const activeEl = document.activeElement;
    const isEditing = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable);
    if (isEditing && !e.ctrlKey && !e.metaKey) {
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
      e.preventDefault();
      toggleSidebar();
    }
  });
}

// =============================================================================
// Refresh All Data
// =============================================================================
export async function refreshAllData(forceFresh = false) {
  const refreshBtn = document.getElementById('btn-refresh');
  const refreshText = document.getElementById('btn-refresh-text');
  const refreshIcon = refreshBtn ? refreshBtn.querySelector('.refresh-icon') : null;

  if (refreshBtn) {
    refreshBtn.classList.add('loading', 'refreshing');
    refreshBtn.disabled = true;
    if (refreshText) refreshText.innerText = 'Syncing...';
  }

  let refreshError = null;

  try {
    // 1. Concurrently fetch all Overview tab dependencies so all cards hydrate simultaneously
    await Promise.allSettled([
      fetchOverview(),
      fetchWeather(forceFresh),
      fetchTasks(),
      fetchCalendar(),
      fetchAiDigest(),
      fetchEmails(),
    ]);

    if (refreshBtn) {
      refreshBtn.classList.remove('loading', 'refreshing');
      refreshBtn.classList.add('refreshed');
      if (refreshText) refreshText.innerText = 'Synced';

      setTimeout(() => {
        refreshBtn.classList.remove('refreshed');
        if (refreshText) refreshText.innerText = 'Refresh';
        refreshBtn.disabled = false;
      }, 800);
    }

    if (forceFresh) {
      showToast('All dashboard data & workspace synchronized!', 'success');
    }

    // 2. Fetch remaining background feeds (news stories, models, workspace tree)
    const backgroundPromises = [];

    if (typeof fetchModels === 'function') {
      backgroundPromises.push(fetchModels());
    }

    if (typeof loadFilesTree === 'function' && fileTreeData) {
      backgroundPromises.push(loadFilesTree());
    }

    fetchNews();

    if (backgroundPromises.length > 0) {
      await Promise.allSettled(backgroundPromises);
    }
  } catch (err) {
    console.error('Error refreshing data:', err);
    refreshError = err;
    if (refreshBtn) {
      refreshBtn.classList.remove('loading', 'refreshing');
      if (refreshText) refreshText.innerText = 'Refresh';
      refreshBtn.disabled = false;
      if (forceFresh) showToast('Refresh failed: ' + refreshError.message, 'error');
    }
  }
}

// =============================================================================
// Backend Lifecycle & Heartbeat Monitor
// =============================================================================
let consecutiveHeartbeatFailures = 0;
let isDisconnectBannerActive = false;
let disconnectCountdownTimer = null;
let keepWindowOpenDismissed = false;

export function initWindowLifecycle() {
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api/app/cancel_exit');
    } else {
      fetch('/api/app/cancel_exit', { method: 'POST' }).catch(() => {});
    }
  } catch (_) {}

  window.addEventListener('pagehide', () => {
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon('/api/app/exit');
      } else {
        fetch('/api/app/exit', { method: 'POST', keepalive: true }).catch(() => {});
      }
    } catch (_) {}
  });
}

export function initBackendHeartbeatMonitor() {
  setTimeout(() => {
    setInterval(checkBackendHeartbeat, 4000);
  }, 8000);
}

export async function checkBackendHeartbeat() {
  if (keepWindowOpenDismissed || isChatPending) {
    consecutiveHeartbeatFailures = 0;
    return;
  }
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);
    const res = await fetch('/api/health', {
      signal: controller.signal,
      cache: 'no-store',
    });
    clearTimeout(timeoutId);
    if (res.ok) {
      consecutiveHeartbeatFailures = 0;
      if (isDisconnectBannerActive) {
        dismissDisconnectBanner(false);
      }
      return;
    }
  } catch (err) {
    // Network failure (server stopped or terminal closed)
  }

  if (isChatPending) {
    consecutiveHeartbeatFailures = 0;
    return;
  }

  consecutiveHeartbeatFailures++;
  if (consecutiveHeartbeatFailures >= 10 && !isDisconnectBannerActive) {
    onBackendTerminated();
  }
}

export function onBackendTerminated() {
  if (isDisconnectBannerActive || keepWindowOpenDismissed) return;
  isDisconnectBannerActive = true;

  let banner = document.getElementById('backend-disconnect-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'backend-disconnect-banner';
    banner.className = 'disconnect-banner';
    document.body.appendChild(banner);
  }

  banner.innerHTML = `
    <div style="width: 10px; height: 10px; border-radius: 50%; background: #ef4444; flex-shrink: 0;"></div>
    <div>
      <strong style="color: #f87171; display: block; font-size: 14px;">Backend Disconnected</strong>
      <span style="color: #94a3b8; font-size: 13px;">Connection to local Aether server paused. Retrying in background...</span>
    </div>
    <button onclick="checkBackendHeartbeat()" style="
      background: #3b82f6;
      color: #fff;
      border: none;
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
    ">
      Reconnect
    </button>
    <button onclick="dismissDisconnectBanner(true)" style="
      background: #27272a;
      color: #e4e4e7;
      border: 1px solid #3f3f46;
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
    ">
      Dismiss
    </button>
  `;
  banner.style.display = 'flex';
}

export function dismissDisconnectBanner(permanent = false) {
  if (disconnectCountdownTimer) {
    clearInterval(disconnectCountdownTimer);
    disconnectCountdownTimer = null;
  }
  const banner = document.getElementById('backend-disconnect-banner');
  if (banner) {
    banner.style.display = 'none';
  }
  isDisconnectBannerActive = false;
  if (permanent) {
    keepWindowOpenDismissed = true;
    showToast('Auto-close paused. Re-run start_portal to reconnect.', 'info');
  }
}

// =============================================================================
// Global Keyboard Shortcuts
// =============================================================================
window.addEventListener('keydown', (e) => {
  // Dismiss voice overlay and interrupt mid-response: Escape
  if (e.key === 'Escape') {
    closeVoiceOverlay();
  }
  // Toggle Coder Agent: Ctrl+Shift+I or Alt+A
  if ((e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'i') || (e.altKey && e.key.toLowerCase() === 'a')) {
    e.preventDefault();
    toggleCoderAgentPanel();
  }
  // Toggle File Explorer: Ctrl+Shift+E or Alt+E
  if ((e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'e') || (e.altKey && e.key.toLowerCase() === 'e')) {
    e.preventDefault();
    toggleFileExplorerPanel();
  }
});

// =============================================================================
// DOMContentLoaded App Initialization
// =============================================================================
document.addEventListener('DOMContentLoaded', () => {
  initSidebarCollapse();
  loadCachedBriefingFromStorage();
  refreshAllData();
  loadChatHistory();
  initChatMediaHandlers();
  initEditorKeybindings();
  initWindowLifecycle();
  initBackendHeartbeatMonitor();
  initCoderAgent();
  fetchVoiceStatus();
  initVoiceEventsSSE();

  // Restore explorer and terminal preferences
  try {
    if (localStorage.getItem('aether_file_explorer_collapsed') === '1') {
      toggleFileExplorerPanel();
    }
    const savedTermH = localStorage.getItem('aether_terminal_height');
    if (savedTermH) {
      const termEl = document.getElementById('editor-terminal-drawer');
      const parsed = parseInt(savedTermH, 10);
      if (termEl && !isNaN(parsed) && parsed >= 100) {
        termEl.style.height = `${parsed}px`;
      }
    }
    initTerminalResize();
  } catch (e) {}

  // Visibility-aware background polling (every 30s)
  setInterval(() => {
    if (isTabVisible()) {
      fetchOverview();
    }
  }, 30000);

  // Periodic voice status poll (every 3s when visible)
  setInterval(() => {
    if (isTabVisible()) {
      fetchVoiceStatus();
    }
  }, 3000);

  // Real-time network listeners
  window.addEventListener('online', () => {
    fetchOverview();
  });

  window.addEventListener('offline', () => {
    const netText = document.getElementById('net-status-text');
    const netDot = document.getElementById('net-dot');
    const topNetText = document.getElementById('top-net-text');
    const topNetDot = document.getElementById('top-net-dot');
    if (netText) netText.innerText = 'Internet (Offline)';
    if (netDot) netDot.className = 'dot dot-red';
    if (topNetText) topNetText.innerText = 'Internet (Offline)';
    if (topNetDot) topNetDot.className = 'dot dot-red';
  });
});

// =============================================================================
// 100% Backward-Compatible Global Window Bindings for Inline HTML Handlers
// =============================================================================
window.switchTab = switchTab;
window.toggleSidebar = toggleSidebar;
window.refreshAllData = refreshAllData;
window.checkBackendHeartbeat = checkBackendHeartbeat;
window.dismissDisconnectBanner = dismissDisconnectBanner;

// Overview
window.fetchOverview = fetchOverview;
window.fetchWeather = fetchWeather;
window.toggleWeatherLocationInput = toggleWeatherLocationInput;
window.saveWeatherLocationManual = saveWeatherLocationManual;
window.handleWeatherLocationInput = handleWeatherLocationInput;
window.handleWeatherLocationKeydown = handleWeatherLocationKeydown;
window.selectWeatherLocation = selectWeatherLocation;
window.regenerateBriefing = regenerateBriefing;
window.copyBriefing = copyBriefing;
window.loadCachedBriefingFromStorage = loadCachedBriefingFromStorage;
window.toggleVoiceActivation = toggleVoiceActivation;
window.fetchVoiceStatus = fetchVoiceStatus;
window.listenNow = listenNow;
window.handleVoiceBadgeClick = handleVoiceBadgeClick;
window.openVoiceOverlay = openVoiceOverlay;
window.closeVoiceOverlay = closeVoiceOverlay;
window.handleVoiceOverlayBackdropClick = handleVoiceOverlayBackdropClick;

// News
window.fetchNews = fetchNews;
window.setNewsFilter = setNewsFilter;
window.fetchAiDigest = fetchAiDigest;
window.refreshAiDigest = refreshAiDigest;

// Calendar
window.fetchCalendar = fetchCalendar;
window.setCalendarView = setCalendarView;
window.prevMonth = prevMonth;
window.nextMonth = nextMonth;
window.goToToday = goToToday;

// Mail
window.fetchEmails = fetchEmails;
window.filterEmailsStatus = filterEmailsStatus;
window.filterEmailsFlag = filterEmailsFlag;
window.filterEmailsDays = filterEmailsDays;
window.onEmailSearch = onEmailSearch;
window.clearEmailSearch = clearEmailSearch;
window.toggleEmailFlag = toggleEmailFlag;

// Tasks
window.fetchTasks = fetchTasks;
window.filterTasks = filterTasks;
window.filterPriority = filterPriority;
window.cycleTaskPriority = cycleTaskPriority;
window.quickAddTask = quickAddTask;
window.addNewTask = addNewTask;
window.toggleTaskComplete = toggleTaskComplete;
window.deleteTaskItem = deleteTaskItem;

// Models
window.fetchModels = fetchModels;
window.changeActiveModel = changeActiveModel;

// Chat
window.sendChatMessage = sendChatMessage;
window.loadChatHistory = loadChatHistory;
window.clearChatHistory = clearChatHistory;
window.toggleTraceDrawer = toggleTraceDrawer;
window.triggerImageAttachment = triggerImageAttachment;
window.handleImageFileSelect = handleImageFileSelect;
window.removeStagedImage = removeStagedImage;
window.snapDesktopScreen = snapDesktopScreen;

// Editor
window.loadFilesTree = loadFilesTree;
window.refreshFilesTreeBtn = refreshFilesTreeBtn;
window.openFile = openFile;
window.setActiveTab = setActiveTab;
window.closeTab = closeTab;
window.saveActiveFile = saveActiveFile;
window.deleteActiveFile = deleteActiveFile;
window.deleteFileByPath = deleteFileByPath;
window.revealPathInExplorer = revealPathInExplorer;
window.revealActiveFileInExplorer = revealActiveFileInExplorer;
window.openFileWithExplorer = openFileWithExplorer;
window.chooseWorkspaceFolderWithExplorer = chooseWorkspaceFolderWithExplorer;
window.organizeWithFolderPicker = organizeWithFolderPicker;
window.promptChangeWorkspace = promptChangeWorkspace;
window.promptNewFile = promptNewFile;
window.promptNewFolder = promptNewFolder;
window.onEditorContentChange = onEditorContentChange;
window.syncEditorScroll = syncEditorScroll;
window.handleEditorKeydown = handleEditorKeydown;
window.toggleGrepSearch = toggleGrepSearch;
window.onFileSearchInput = onFileSearchInput;
window.askAetherAboutCurrentFile = askAetherAboutCurrentFile;
window.toggleFileExplorerPanel = toggleFileExplorerPanel;

// Terminal
window.toggleIntegratedTerminal = toggleIntegratedTerminal;
window.submitTerminalCommand = submitTerminalCommand;
window.cancelTerminalCommand = cancelTerminalCommand;
window.clearTerminalOutput = clearTerminalOutput;
window.handleTerminalKeydown = handleTerminalKeydown;
window.runActiveFile = runActiveFile;
window.executeTerminalCommand = executeTerminalCommand;
window.updateTerminalWorkspaceBadge = updateTerminalWorkspaceBadge;

// Coder
window.toggleCoderMode = toggleCoderMode;
window.toggleActiveFileContext = toggleActiveFileContext;
window.updateCoderContextPill = updateCoderContextPill;
window.sendActiveFileToCoder = sendActiveFileToCoder;
window.toggleCoderAgentPanel = toggleCoderAgentPanel;
window.suggestCoderPrompt = suggestCoderPrompt;
window.handleCoderInputKeydown = handleCoderInputKeydown;
window.sendCoderMessage = sendCoderMessage;
window.approveAndExecutePlan = approveAndExecutePlan;
window.rejectPlan = rejectPlan;
window.toggleDiffDrawer = toggleDiffDrawer;
window.clearCoderHistory = clearCoderHistory;

// Utilities & Store
window.showToast = showToast;
window.renderMarkdown = renderMarkdown;
window.escapeHtml = escapeHtml;

window.copyCodeBlock = function(btn) {
  try {
    const wrapper = btn.closest('.code-block-wrapper');
    if (!wrapper) return;
    const codeEl = wrapper.querySelector('code');
    const text = codeEl ? codeEl.innerText : '';
    if (!text) return;
    const onSuccess = () => {
      btn.classList.add('copied');
      const textSpan = btn.querySelector('.copy-text');
      if (textSpan) textSpan.textContent = 'Copied!';
      setTimeout(() => {
        btn.classList.remove('copied');
        if (textSpan) textSpan.textContent = 'Copy';
      }, 2000);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(onSuccess).catch(() => {
        fallbackCopy(text, onSuccess);
      });
    } else {
      fallbackCopy(text, onSuccess);
    }
  } catch (err) {
    console.warn('Copy code block error:', err);
  }
};

function fallbackCopy(text, cb) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
    if (cb) cb();
  } finally {
    document.body.removeChild(ta);
  }
}

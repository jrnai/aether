/**
 * Project Aether - Inbox Triage & Multi-Filter Controller
 * Native ES Module
 */

import { escapeHtml, escapeJsString, showToast, isTabVisible } from '../store.js';

let currentEmailStatus = 'unread';
let currentEmailDays = '7';
let currentEmailFlag = 'all';
let currentEmailSearch = '';
let currentEmailsList = [];
let emailSearchDebounce = null;

export function filterEmailsStatus(status) {
  currentEmailStatus = status;
  currentEmailFlag = 'all';
  updateEmailFilterButtons();
  fetchEmails();
}

export function filterEmailsFlag(flag) {
  currentEmailFlag = flag;
  currentEmailStatus = 'all';
  updateEmailFilterButtons();
  fetchEmails();
}

export function filterEmailsDays(days) {
  currentEmailDays = days;
  updateEmailFilterButtons();
  fetchEmails();
}

function updateEmailFilterButtons() {
  document.querySelectorAll('#email-status-filters .btn-chip').forEach((btn) => {
    let isActive = false;
    if (currentEmailFlag !== 'all') {
      isActive = btn.id === `email-filter-${currentEmailFlag}`;
    } else {
      isActive = btn.id === `email-filter-${currentEmailStatus}`;
    }
    btn.classList.toggle('active', isActive);
  });

  document.querySelectorAll('#email-date-filters .btn-chip').forEach((btn) => {
    btn.classList.toggle('active', btn.id === `email-days-${currentEmailDays}`);
  });
}

export function onEmailSearch(query) {
  currentEmailSearch = (query || '').trim();
  const clearBtn = document.getElementById('btn-clear-email-search');
  if (clearBtn) clearBtn.style.display = currentEmailSearch ? 'inline-block' : 'none';

  clearTimeout(emailSearchDebounce);
  emailSearchDebounce = setTimeout(() => {
    fetchEmails();
  }, 250);
}

export function clearEmailSearch() {
  const input = document.getElementById('email-search-input');
  if (input) input.value = '';
  currentEmailSearch = '';
  const clearBtn = document.getElementById('btn-clear-email-search');
  if (clearBtn) clearBtn.style.display = 'none';
  fetchEmails();
}

export async function fetchEmails(refresh = false) {
  if (!refresh && !isTabVisible()) return;

  const syncBtn = document.getElementById('btn-sync-emails');
  const syncIcon = document.getElementById('sync-emails-icon');
  if (refresh && syncIcon) syncIcon.classList.add('spin');
  if (refresh && syncBtn) syncBtn.disabled = true;

  try {
    const params = new URLSearchParams({
      status: currentEmailStatus,
      days: currentEmailDays,
      flag: currentEmailFlag,
      search: currentEmailSearch,
      refresh: refresh ? 'true' : 'false',
    });

    const res = await fetch(`/api/emails?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();

    const emails = data.emails || [];
    currentEmailsList = emails;

    const unreadCount = data.unread_count !== undefined ? data.unread_count : emails.filter((e) => !e.read).length;
    const starredCount = data.starred_count !== undefined ? data.starred_count : emails.filter((e) => e.starred).length;
    const pinnedCount = data.pinned_count !== undefined ? data.pinned_count : emails.filter((e) => e.pinned).length;
    const totalCount = data.total_count !== undefined ? data.total_count : emails.length;

    const statEmail = document.getElementById('stat-email-count');
    if (statEmail) statEmail.innerText = unreadCount;
    const badgeUnread = document.getElementById('badge-unread');
    if (badgeUnread) badgeUnread.innerText = unreadCount;

    const elUnread = document.getElementById('email-stat-unread');
    if (elUnread) elUnread.innerText = `${unreadCount} unread`;
    const elStarred = document.getElementById('email-stat-starred');
    if (elStarred) elStarred.innerText = `${starredCount} starred`;
    const elPinned = document.getElementById('email-stat-pinned');
    if (elPinned) elPinned.innerText = `${pinnedCount} pinned`;
    const elTotal = document.getElementById('email-stat-total');
    if (elTotal) elTotal.innerText = `${totalCount} total`;

    renderEmailCards(emails);

    if (refresh) {
      showToast('Live email sync completed!', 'success');
    }
  } catch (err) {
    console.error('Failed to fetch emails:', err);
    if (refresh) {
      showToast('Email sync failed: ' + err.message, 'error');
    }
  } finally {
    if (syncIcon) syncIcon.classList.remove('spin');
    if (syncBtn) syncBtn.disabled = false;
  }
}

export function renderEmailCards(emails) {
  const listContainer = document.getElementById('emails-list');
  if (!listContainer) return;

  if (emails.length === 0) {
    listContainer.innerHTML = `
      <div class="empty-state">
        <p style="font-weight: 600; font-size: 1rem; color: #fff;">No emails match your filter.</p>
        <p style="font-size: 0.85rem; color: var(--text-dim); margin-top: 0.3rem;">
          Try selecting 'All' time or switching between Read / Unread / Starred / Pinned.
        </p>
      </div>
    `;
    return;
  }

  let html = '';
  for (const em of emails) {
    const sender = escapeHtml(em.sender || 'Unknown');
    const subject = escapeHtml(em.subject || '(No Subject)');
    const dateFormatted = formatEmailDate(em.date);
    const body = escapeHtml(em.body ? em.body.substring(0, 175) + '...' : '');
    const isUnread = !em.read;
    const isStarred = Boolean(em.starred);
    const isPinned = Boolean(em.pinned);
    const isImportant = Boolean(em.important);

    const cardClasses = ['email-card', isUnread ? 'unread' : 'read', isPinned ? 'pinned' : ''].filter(Boolean).join(' ');

    const accountLabel = escapeHtml(em.account_label || em.account || 'Email');

    html += `
      <div class="${cardClasses}" id="email-card-${escapeHtml(em.id)}">
        <div class="email-header">
          <div class="email-sender-wrap">
            <span class="email-sender" title="${sender}">${sender}</span>
            <span class="badge-account">${accountLabel}</span>
            ${isImportant ? `<span class="badge-important">Important</span>` : ''}
            ${isPinned ? `<span class="badge" style="background:rgba(6,182,212,0.15); color:#67E8F9; border:1px solid rgba(6,182,212,0.3); font-size:0.72rem; padding:0.12rem 0.45rem;">Pinned</span>` : ''}
          </div>

          <div class="email-actions">
            <span class="stat-meta" style="margin-right: 0.5rem;">${dateFormatted}</span>

            <!-- Star Toggle -->
            <button 
              class="btn-icon-toggle starred ${isStarred ? 'active' : ''}" 
              onclick="window.toggleEmailFlag('${escapeJsString(em.id)}', 'starred')" 
              title="${isStarred ? 'Unstar email' : 'Star email'}"
            >
              ${isStarred ? '[star]' : '[unstar]'}
            </button>

            <!-- Pin Toggle -->
            <button 
              class="btn-icon-toggle pinned ${isPinned ? 'active' : ''}" 
              onclick="window.toggleEmailFlag('${escapeJsString(em.id)}', 'pinned')" 
              title="${isPinned ? 'Unpin email' : 'Pin to top'}"
            >
              ${isPinned ? '[pin]' : '[unpin]'}
            </button>

            <!-- Read / Unread Toggle -->
            <button 
              class="btn-icon-toggle ${isUnread ? 'active' : ''}" 
              onclick="window.toggleEmailFlag('${escapeJsString(em.id)}', 'read')" 
              title="${isUnread ? 'Mark as read' : 'Mark as unread'}"
            >
              ${isUnread ? '[unread]' : '[read]'}
            </button>
          </div>
        </div>

        <div class="email-subject ${isUnread ? '' : 'read'}">${subject}</div>
        <div class="email-preview">${body}</div>
      </div>
    `;
  }
  listContainer.innerHTML = html;
}

export async function toggleEmailFlag(emailId, flagName) {
  const item = currentEmailsList.find((e) => e.id === emailId);
  if (item) {
    if (flagName === 'read') {
      item.read = !item.read;
    } else if (flagName === 'starred') {
      item.starred = !item.starred;
    } else if (flagName === 'pinned') {
      item.pinned = !item.pinned;
    } else if (flagName === 'important') {
      item.important = !item.important;
    }
    renderEmailCards(currentEmailsList);
  }

  try {
    const res = await fetch('/api/emails/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: emailId, flag: flagName }),
    });
    if (!res.ok) throw new Error('Failed to update email flag');
    const data = await res.json();
    if (data.status === 'success' && data.email && item) {
      Object.assign(item, data.email);
    }
  } catch (err) {
    console.error('Error updating email flag:', err);
    showToast(`Could not update ${flagName}: ${err.message}`, 'error');
    fetchEmails();
  }
}

function formatEmailDate(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now - d;
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffHours / 24);

    if (diffHours < 1) return 'Just now';
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;

    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch (e) {
    return dateStr;
  }
}

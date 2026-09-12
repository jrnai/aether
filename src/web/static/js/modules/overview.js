/**
 * Project Aether - Overview & Daily Briefing Module
 * Native ES Module
 */

import { renderMarkdown, showToast, escapeHtml, isTabVisible } from '../store.js';

export function loadCachedBriefingFromStorage() {
  try {
    const todayStr = new Date().toISOString().slice(0, 10);
    const cached = localStorage.getItem('aether_cached_briefing_' + todayStr);
    const briefingEl = document.getElementById('briefing-content');
    const briefingBtnText = document.getElementById('briefing-btn-text');
    const briefingBtnIcon = document.getElementById('briefing-btn-icon');
    if (cached && briefingEl && cached.includes('Morning Briefing')) {
      briefingEl.innerHTML = renderMarkdown(cached);
      if (briefingBtnText) briefingBtnText.innerText = 'Regenerate Briefing';
      if (briefingBtnIcon) briefingBtnIcon.innerText = '';
    }
  } catch (_) {}
}

export async function fetchOverview() {
  if (!isTabVisible()) return;
  try {
    const res = await fetch('/api/overview');
    if (!res.ok) return;
    const data = await res.json();

    // Top date/time
    if (data.weekday) document.getElementById('header-weekday').innerText = data.weekday;
    if (data.date) {
      const d = new Date(data.date);
      const options = { month: 'long', day: 'numeric', year: 'numeric' };
      document.getElementById('header-date').innerText = d.toLocaleDateString('en-US', options);
    }

    // Health Status
    if (data.status) {
      const ollamaText = document.getElementById('ollama-status-text');
      const ollamaDot = document.getElementById('ollama-dot');
      if (data.status.ollama) {
        ollamaText.innerText = `Ollama (${data.status.ollama_model})`;
        ollamaDot.className = 'dot dot-green';
      } else {
        ollamaText.innerText = 'Ollama (Offline)';
        ollamaDot.className = 'dot dot-red';
      }

      // Internet Status
      const netText = document.getElementById('net-status-text');
      const netDot = document.getElementById('net-dot');
      const topNetText = document.getElementById('top-net-text');
      const topNetDot = document.getElementById('top-net-dot');
      const topNetBadge = document.getElementById('top-net-badge');
      if (data.status.internet) {
        if (netText) netText.innerText = 'Internet (Connected)';
        if (netDot) netDot.className = 'dot dot-green';
        if (topNetText) topNetText.innerText = 'Internet (Connected)';
        if (topNetDot) topNetDot.className = 'dot dot-green';
        if (topNetBadge) topNetBadge.title = 'Internet status: Connected and active';
      } else {
        if (netText) netText.innerText = 'Internet (Offline)';
        if (netDot) netDot.className = 'dot dot-red';
        if (topNetText) topNetText.innerText = 'Internet (Offline)';
        if (topNetDot) topNetDot.className = 'dot dot-red';
        if (topNetBadge) topNetBadge.title = 'Internet status: Offline. External tools disabled.';
      }

      // Web Search Status
      const searchText = document.getElementById('search-status-text');
      const searchDot = document.getElementById('search-dot');
      if (searchText) {
        searchText.innerText = `Web Search (${data.status.search || 'DuckDuckGo'})`;
        if (searchDot) {
          searchDot.className = data.status.internet ? 'dot dot-green' : 'dot dot-red';
        }
      }

      const calText = document.getElementById('cal-status-text');
      if (calText) calText.innerText = data.status.calendar;

      const mailText = document.getElementById('mail-status-text');
      if (mailText) mailText.innerText = data.status.email;
    }

    // Daily briefing content
    const briefingEl = document.getElementById('briefing-content');
    const briefingBtnText = document.getElementById('briefing-btn-text');
    const briefingBtnIcon = document.getElementById('briefing-btn-icon');

    if (data.daily_note && data.daily_note.includes('Morning Briefing')) {
      briefingEl.innerHTML = renderMarkdown(data.daily_note);
      if (briefingBtnText) briefingBtnText.innerText = 'Regenerate Briefing';
      if (briefingBtnIcon) briefingBtnIcon.innerText = '';
      try {
        const todayStr = data.date || new Date().toISOString().slice(0, 10);
        localStorage.setItem('aether_cached_briefing_' + todayStr, data.daily_note);
      } catch (_) {}
    } else {
      const todayStr = data.date || new Date().toISOString().slice(0, 10);
      const localCached = localStorage.getItem('aether_cached_briefing_' + todayStr);
      if (localCached && localCached.includes('Morning Briefing')) {
        briefingEl.innerHTML = renderMarkdown(localCached);
        if (briefingBtnText) briefingBtnText.innerText = 'Regenerate Briefing';
        if (briefingBtnIcon) briefingBtnIcon.innerText = '';
      } else {
        if (briefingBtnText) briefingBtnText.innerText = 'Generate Briefing';
        if (briefingBtnIcon) briefingBtnIcon.innerText = '';
        briefingEl.innerHTML = `
          <div class="empty-state">
            <p style="font-weight: 600; font-size: 1.05rem; color: #fff;">No morning briefing generated yet today.</p>
            <p style="font-size: 0.88rem; color: var(--text-dim); margin-top: 0.4rem; max-width: 380px; margin-left: auto; margin-right: auto;">
              Aether synthesizes your calendar schedule, unread emails, and vault tasks into a personalized morning briefing.
            </p>
            <button class="btn-primary" style="margin-top: 1.25rem;" onclick="window.regenerateBriefing()">
              Generate Today's Briefing
            </button>
          </div>
        `;
      }
    }

    // Pending tasks count
    if (data.stats) {
      const statTasks = document.getElementById('stat-tasks-count');
      const badgeTasks = document.getElementById('badge-tasks');
      if (statTasks) statTasks.innerText = data.stats.pending_tasks || 0;
      if (badgeTasks) badgeTasks.innerText = data.stats.pending_tasks || 0;
    }
  } catch (err) {
    console.error('Failed to fetch overview:', err);
  }
}

export async function regenerateBriefing() {
  const btn = document.getElementById('btn-regenerate-briefing');
  const icon = document.getElementById('briefing-btn-icon');
  const text = document.getElementById('briefing-btn-text');
  const briefingEl = document.getElementById('briefing-content');

  if (btn) btn.disabled = true;
  if (icon) icon.className = 'spin';
  if (text) text.innerText = 'Generating...';

  if (briefingEl) {
    briefingEl.innerHTML = `
      <div class="generating-box">
        <div class="spinner-ring"></div>
        <div class="generating-title">Synthesizing Morning Briefing...</div>
        <div class="generating-desc">Scanning calendar schedule, unread emails, and vault priorities via local Ollama. This takes just a few seconds...</div>
      </div>
    `;
  }

  try {
    const res = await fetch('/api/briefing/regenerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    const data = await res.json();
    if (res.ok && data.status === 'success') {
      const noteContent = data.daily_note || data.briefing;
      if (noteContent && briefingEl) {
        briefingEl.innerHTML = renderMarkdown(noteContent);
        if (text) text.innerText = 'Regenerate Briefing';
        if (icon) icon.className = '';
      }
      try {
        const todayStr = data.date || new Date().toISOString().slice(0, 10);
        localStorage.setItem('aether_cached_briefing_' + todayStr, noteContent);
      } catch (_) {}
      showToast('Morning briefing generated successfully!', 'success');
      fetchOverview();
    } else {
      const errMsg = data.message || 'Failed to generate briefing';
      if (briefingEl) {
        briefingEl.innerHTML = `
          <div class="empty-state" style="border-color: rgba(244, 63, 94, 0.4);">
            <p style="color: var(--rose); font-weight: 600;">Failed to generate briefing</p>
            <p style="font-size: 0.85rem; color: var(--text-dim); margin-top: 0.4rem; max-width: 400px; margin-left: auto; margin-right: auto;">${escapeHtml(errMsg)}</p>
            <button class="btn-secondary" style="margin-top: 1rem;" onclick="window.regenerateBriefing()">Try Again</button>
          </div>
        `;
      }
      showToast(`Error: ${errMsg}`, 'error');
    }
  } catch (err) {
    console.error('Failed to regenerate briefing:', err);
    if (briefingEl) {
      briefingEl.innerHTML = `
        <div class="empty-state" style="border-color: rgba(244, 63, 94, 0.4);">
          <p style="color: var(--rose); font-weight: 600;">Connection Error</p>
          <p style="font-size: 0.85rem; color: var(--text-dim); margin-top: 0.4rem;">${escapeHtml(err.message)}</p>
          <button class="btn-secondary" style="margin-top: 1rem;" onclick="window.regenerateBriefing()">Try Again</button>
        </div>
      `;
    }
    showToast('Failed to connect to Aether server', 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (icon) icon.className = '';
    if (text) text.innerText = 'Regenerate Briefing';
  }
}

export function copyBriefing() {
  const el = document.getElementById('briefing-content');
  if (!el) return;
  const text = el.innerText;
  if (!text || text.includes('Loading') || text.includes('No morning briefing')) {
    showToast('No briefing content to copy.', 'error');
    return;
  }
  navigator.clipboard
    .writeText(text)
    .then(() => {
      showToast('Briefing copied to clipboard!', 'success');
    })
    .catch(() => {
      showToast('Failed to copy to clipboard', 'error');
    });
}

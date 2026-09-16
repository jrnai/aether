/**
 * Project Aether - Tech & AI News and AI Student Digest Module
 * Native ES Module
 */

import { showToast, escapeHtml, formatRelativeTime, isTabVisible } from '../store.js';

let allNewsItems = [];
let activeNewsFilter = 'all';
let currentAiDigest = null;
let isDigestLoading = false;

function handleNewsImageError(imgEl, domain, category) {
  if (!imgEl || !imgEl.parentElement) return;
  const parent = imgEl.parentElement;
  const cat = category || 'tech';
  const safeDomain = domain || 'news.ycombinator.com';

  parent.className = `news-item-media news-item-fallback-banner banner-${cat}`;
  parent.innerHTML = `
    <div class="fallback-favicon-box">
      <img src="https://www.google.com/s2/favicons?domain=${encodeURIComponent(safeDomain)}&sz=128" alt="favicon" class="fallback-favicon-img" onerror="this.style.display='none'">
    </div>
    <span class="fallback-domain-text">${escapeHtml(safeDomain)}</span>
  `;
}

export async function fetchNews(force = false) {
  if (!force && !isTabVisible()) return;

  const container = document.getElementById('news-headlines-container');
  const syncBtn = document.getElementById('btn-refresh-news');
  const syncIcon = syncBtn ? syncBtn.querySelector('.refresh-icon') : null;

  if (force && syncBtn) {
    syncBtn.disabled = true;
    if (syncIcon) syncIcon.classList.add('spin');
  }

  if (container && (!allNewsItems || allNewsItems.length === 0)) {
    container.innerHTML = '<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line shorter"></div>';
  }

  try {
    const url = force ? '/api/news?force=true' : '/api/news';
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allNewsItems = data.items || [];

    const badge = document.getElementById('news-badge-count');
    if (badge) {
      badge.innerText = `${allNewsItems.length} Stories`;
    }

    const updatedEl = document.getElementById('news-updated-time');
    if (updatedEl) {
      const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      updatedEl.innerText = `Updated ${nowStr}`;
    }

    renderNewsGrid();
    if (force) {
      showToast(`Synchronized ${allNewsItems.length} tech & AI headlines!`, 'success');
    }
  } catch (err) {
    console.error('Failed to fetch news:', err);
    if (container && (!allNewsItems || allNewsItems.length === 0)) {
      container.innerHTML = `
        <div class="empty-state">
          <p style="color: #f87171;">Could not load tech headlines (${escapeHtml(err.message)})</p>
          <button class="btn-subtle" onclick="window.fetchNews(true)" style="margin-top: 0.5rem;">Try Again</button>
        </div>
      `;
    }
  } finally {
    if (syncBtn) {
      syncBtn.disabled = false;
      if (syncIcon) syncIcon.classList.remove('spin');
    }
  }
}

export function setNewsFilter(filter) {
  activeNewsFilter = filter;
  const chips = {
    all: document.getElementById('news-chip-all'),
    ai_ml: document.getElementById('news-chip-ai'),
    dev_tools: document.getElementById('news-chip-tools'),
    'Hacker News': document.getElementById('news-chip-hn'),
    'Google News': document.getElementById('news-chip-gn'),
    'TechCrunch AI': document.getElementById('news-chip-tc'),
  };

  Object.entries(chips).forEach(([k, el]) => {
    if (el) {
      if (k === filter) el.classList.add('active');
      else el.classList.remove('active');
    }
  });

  renderNewsGrid();
}

export function renderNewsGrid() {
  const container = document.getElementById('news-headlines-container');
  if (!container) return;

  if (!allNewsItems || allNewsItems.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p style="color: var(--text-dim);">No headlines currently cached.</p>
        <button class="btn-primary" onclick="window.fetchNews(true)" style="margin-top: 0.75rem;">Fetch Tech & AI Headlines</button>
      </div>
    `;
    return;
  }

  let filtered = allNewsItems;
  if (activeNewsFilter && activeNewsFilter !== 'all') {
    if (activeNewsFilter === 'ai_ml') {
      filtered = allNewsItems.filter((item) => (item.category || '').toLowerCase() === 'ai_ml');
    } else if (activeNewsFilter === 'dev_tools') {
      filtered = allNewsItems.filter((item) => (item.category || '').toLowerCase() === 'dev_tools');
    } else {
      const needle = activeNewsFilter.toLowerCase();
      filtered = allNewsItems.filter((item) => (item.source || '').toLowerCase().includes(needle));
    }
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p style="color: var(--text-dim);">No stories found for "${escapeHtml(activeNewsFilter)}".</p>
        <button class="btn-subtle" onclick="window.setNewsFilter('all')" style="margin-top: 0.5rem;">Show All Stories</button>
      </div>
    `;
    return;
  }

  const html = filtered
    .map((item) => {
      const src = (item.source || '').toLowerCase();
      const isHN = src.includes('hacker');
      const isTC = src.includes('techcrunch');
      const badgeClass = isHN ? 'news-badge-hn' : isTC ? 'news-badge-tc' : 'news-badge-gn';
      const sourceLabel = item.source || (isHN ? 'Hacker News' : 'Tech News');

      const cat = (item.category || 'tech').toLowerCase();
      let domain = 'news.ycombinator.com';
      try {
        if (item.url) domain = new URL(item.url).hostname.replace(/^www\./, '');
      } catch (_) {}

      const faviconUrl = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=16`;
      const title = escapeHtml(item.title || '(No title)');
      const url = escapeHtml(item.url || '#');
      const timeAgo = formatRelativeTime(item.published_at);
      const category = cat === 'ai_ml' ? 'AI' : cat === 'dev_tools' ? 'Tools' : cat === 'research' ? 'Research' : 'Tech';

      return `
        <div class="news-item-row">
          <img class="news-source-icon" src="${faviconUrl}" alt="" width="16" height="16">
          <a class="news-headline" href="${url}" target="_blank" rel="noopener">${title}</a>
          <span class="news-meta">${timeAgo}</span>
          <span class="news-tag">${category}</span>
        </div>
      `;
    })
    .join('');

  container.innerHTML = html;
}

export async function fetchAiDigest(force = false) {
  if (isDigestLoading) return;
  isDigestLoading = true;

  const btn = document.getElementById('btn-refresh-digest');
  const icon = document.getElementById('digest-refresh-icon');
  if (btn && force) {
    btn.disabled = true;
    if (icon) icon.classList.add('spin');
  }

  try {
    const url = force ? '/api/news/digest/refresh' : '/api/news/digest';
    const method = force ? 'POST' : 'GET';
    const res = await fetch(url, { method });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const digestData = data && data.digest ? data.digest : data;
    currentAiDigest = digestData;
    renderAiDigest(digestData);
    if (force) {
      showToast('AI Student Intelligence briefing refreshed with local Ollama!', 'success');
    }
  } catch (err) {
    console.error('Failed to fetch AI digest:', err);
    renderAiDigestFallback(err.message);
  } finally {
    isDigestLoading = false;
    if (btn) {
      btn.disabled = false;
      if (icon) icon.classList.remove('spin');
    }
  }
}

export async function refreshAiDigest() {
  await fetchAiDigest(true);
}

export function renderAiDigest(raw) {
  if (!raw) return;
  const data = raw && raw.digest ? raw.digest : raw;

  const headlineEl = document.getElementById('digest-headline');
  if (headlineEl && data.headline) {
    headlineEl.innerText = data.headline;
  }

  const updatedEl = document.getElementById('digest-updated-at');
  if (updatedEl) {
    const timeStr = data.generated_at ? formatRelativeTime(data.generated_at) : 'recently';
    const modelTag = data.model ? `via ${data.model}` : data.method === 'ollama_llm' ? 'via Ollama' : 'synthesized';
    updatedEl.innerText = `${timeStr} (${modelTag})`;
  }

  const takeawayText = data.executive_takeaway || 'Stay up to date with the latest frontier AI breakthroughs and developer tools.';
  const takeawayEl = document.getElementById('digest-takeaway-text');
  if (takeawayEl) takeawayEl.innerText = takeawayText;

  const overviewTakeawayEl = document.getElementById('overview-digest-takeaway-text');
  if (overviewTakeawayEl) overviewTakeawayEl.innerText = takeawayText;

  const modelsContainer = document.getElementById('digest-models-list');
  if (modelsContainer) {
    const models = data.models_and_research || [];
    if (models.length === 0) {
      modelsContainer.innerHTML = '<div style="color: var(--text-dim); font-size: 0.85rem;">No model releases spotlighted today.</div>';
    } else {
      modelsContainer.innerHTML = models
        .map((m) => {
          const title = m.name || m.title || 'Model Research';
          const body = m.insight || m.takeaway || '';
          return `
            <div class="digest-item">
              <div class="digest-item-title">
                ${m.url ? `<a href="${escapeHtml(m.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)} [link]</a>` : escapeHtml(title)}
              </div>
              <div class="digest-item-body">${escapeHtml(body)}</div>
            </div>
          `;
        })
        .join('');
    }
  }

  const toolsContainer = document.getElementById('digest-tools-list');
  if (toolsContainer) {
    const tools = data.developer_tools || [];
    if (tools.length === 0) {
      toolsContainer.innerHTML = '<div style="color: var(--text-dim); font-size: 0.85rem;">No specific dev tools spotlighted today.</div>';
    } else {
      toolsContainer.innerHTML = tools
        .map((t) => {
          const title = t.name || t.tool || 'Developer Tool';
          const body = t.insight || t.description || '';
          return `
            <div class="digest-item">
              <div class="digest-item-title">
                ${t.url ? `<a href="${escapeHtml(t.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)} [link]</a>` : escapeHtml(title)}
              </div>
              <div class="digest-item-body">${escapeHtml(body)}</div>
            </div>
          `;
        })
        .join('');
    }
  }

  const projectContainer = document.getElementById('digest-project-idea');
  if (projectContainer) {
    const proj =
      data.student_project_takeaway ||
      (data.student_project_idea ? (typeof data.student_project_idea === 'object' ? data.student_project_idea : { description: String(data.student_project_idea) }) : null);
    if (proj && (proj.title || proj.description)) {
      projectContainer.innerHTML = `
        <div class="digest-project-card">
          <div class="digest-project-title">${escapeHtml(proj.title || 'Hands-On AI Project')}</div>
          <div class="digest-project-desc">${escapeHtml(proj.description || '')}</div>
          ${proj.tech_stack ? `<div class="digest-project-stack"><strong>Tech Stack:</strong> ${escapeHtml(proj.tech_stack)}</div>` : ''}
        </div>
      `;
    } else {
      projectContainer.innerHTML = `<div style="color: var(--text-dim); font-size: 0.85rem;">Explore today's AI tools to prototype a local agent!</div>`;
    }
  }
}

function renderAiDigestFallback(errMsg) {
  const takeawayEl = document.getElementById('digest-takeaway-text');
  if (takeawayEl) {
    takeawayEl.innerText = 'AI intelligence digest temporarily unavailable. Check internet connection or Ollama service.';
  }
  const overviewTakeawayEl = document.getElementById('overview-digest-takeaway-text');
  if (overviewTakeawayEl) {
    overviewTakeawayEl.innerText = 'AI intelligence digest temporarily unavailable.';
  }
}

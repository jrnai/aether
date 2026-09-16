/**
 * Project Aether - Reactive State Store & Shared Utilities
 * Native ES Module (zero build step)
 */

class Store {
  constructor() {
    this.state = {
      currentTab: 'overview',
      currentTaskFilter: 'pending',
      currentPriorityFilter: 'all',
      currentEmailStatus: 'unread',
      currentEmailDays: '7',
      currentEmailFlag: 'all',
      currentEmailSearch: '',
      activeWorkspace: '',
      activeFile: null,
      activeModel: 'qwen2.5-coder:7b',
      isAutoRoute: true,
      isTabVisible: !document.hidden,
      isCoderPlanMode: true,
    };
    this.listeners = new Map();
  }

  getState() {
    return this.state;
  }

  setState(updates) {
    const prevState = { ...this.state };
    this.state = { ...this.state, ...updates };
    Object.keys(updates).forEach((key) => {
      if (this.listeners.has(key)) {
        this.listeners.get(key).forEach((cb) => cb(this.state[key], prevState[key]));
      }
    });
    if (this.listeners.has('*')) {
      this.listeners.get('*').forEach((cb) => cb(this.state, prevState));
    }
  }

  on(key, callback) {
    if (!this.listeners.has(key)) {
      this.listeners.set(key, new Set());
    }
    this.listeners.get(key).add(callback);
    return () => this.listeners.get(key).delete(callback);
  }

  emit(event, data) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).forEach((cb) => cb(data));
    }
  }
}

export const store = new Store();

// Page Visibility API tracking
document.addEventListener('visibilitychange', () => {
  const visible = !document.hidden;
  store.setState({ isTabVisible: visible });
  store.emit('visibilityChange', visible);
});

export function isTabVisible() {
  return !document.hidden;
}

// HTML escape utility
export function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function escapeJsString(text) {
  if (!text) return '';
  return text.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

// Time & Date formatters
export function formatIsoTime(isoStr) {
  if (!isoStr) return '';
  if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(isoStr)) {
    const parts = isoStr.split(':');
    const h = parseInt(parts[0], 10);
    const m = parts[1];
    const ampm = h >= 12 ? 'PM' : 'AM';
    const displayH = h % 12 || 12;
    return `${displayH}:${m} ${ampm}`;
  }
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  } catch {
    return isoStr;
  }
}

export function formatEventTime(startIso, endIso) {
  if (!startIso && !endIso) return '-';
  if (!startIso) return 'All Day';
  const s = formatIsoTime(startIso);
  const e = formatIsoTime(endIso);
  if (!e || s === e) return s;
  return `${s} - ${e}`;
}

export function formatEventDate(startIso, evObj) {
  let dayName = evObj && evObj.day ? evObj.day : '';
  let dateDisplay = evObj && evObj.date_display ? evObj.date_display : '';
  let isToday = evObj && evObj.is_today ? true : false;
  let isTomorrow = false;

  if (!dayName || !dateDisplay) {
    if (!startIso) return '<span style="color:var(--text-dim);">-</span>';
    try {
      const d = new Date(startIso);
      if (!isNaN(d.getTime())) {
        const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
        dayName = days[d.getDay()];
        dateDisplay = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
        const now = new Date();
        isToday = d.toDateString() === now.toDateString();
        const tom = new Date();
        tom.setDate(now.getDate() + 1);
        isTomorrow = d.toDateString() === tom.toDateString();
      }
    } catch {
      return '<span style="color:var(--text-dim);">-</span>';
    }
  } else {
    try {
      const d = new Date(startIso);
      if (!isNaN(d.getTime())) {
        const now = new Date();
        const tom = new Date();
        tom.setDate(now.getDate() + 1);
        isTomorrow = d.toDateString() === tom.toDateString();
      }
    } catch {}
  }

  let pillClass = 'event-day-pill';
  let badgeLabel = dayName;
  if (isToday) {
    pillClass += ' today';
    badgeLabel = `${dayName} [TODAY]`;
  } else if (isTomorrow) {
    pillClass += ' tomorrow';
    badgeLabel = `${dayName} [TOMORROW]`;
  }

  return `
    <div class="event-date-cell">
      <span class="${pillClass}">${escapeHtml(badgeLabel)}</span>
      <span class="event-date-sub">${escapeHtml(dateDisplay)}</span>
    </div>
  `;
}

export function formatRelativeTime(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    const now = new Date();
    const diffSec = Math.floor((now - d) / 1000);
    if (diffSec < 60) return 'Just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return `${Math.floor(diffSec / 86400)}d ago`;
  } catch {
    return dateStr;
  }
}

// Toast notification manager
export function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span class="toast-indicator toast-indicator-${type}"></span><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Helper for KaTeX math rendering
function renderKaTeXString(latex, isDisplay) {
  if (!latex || !latex.trim()) return '';
  const cleanLatex = latex.trim();
  if (typeof window !== 'undefined' && window.katex && typeof window.katex.renderToString === 'function') {
    try {
      return window.katex.renderToString(cleanLatex, {
        displayMode: isDisplay,
        throwOnError: false,
      });
    } catch (err) {
      console.debug('KaTeX parse error:', err);
    }
  }
  return `<span class="katex-fallback ${isDisplay ? 'katex-display-fallback' : ''}">${escapeHtml(cleanLatex)}</span>`;
}

// Markdown parser
export function renderMarkdown(md) {
  if (!md) return '';

  try {
    let processed = md.replace(/^\s*---\s*[\r\n]+[\s\S]*?[\r\n]+---\s*[\r\n]*/, '');

    // Clean up internal tool calls or leaked system tags
    processed = processed.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '');
    processed = processed.replace(/<tool_response>[\s\S]*?<\/tool_response>/gi, '');
    processed = processed.replace(/<function_call>[\s\S]*?<\/function_call>/gi, '');
    processed = processed.replace(/<\/?(?:tool_call|tool_response|function_call)>/gi, '');

    // Extract DeepSeek-R1 <think> blocks
    const thinkBlocks = [];
    processed = processed.replace(/<think>([\s\S]*?)<\/think>/gi, (match, thought) => {
      const idx = thinkBlocks.length;
      thinkBlocks.push(
        `<details class="reasoning-accordion" open>` +
          `<summary class="reasoning-summary"><span class="think-icon"></span> Thought Process (DeepSeek-R1 Reasoning)</summary>` +
          `<div class="reasoning-content">${escapeHtml(thought.trim())}</div>` +
        `</details>`
      );
      return `\n\n@@AETHERTHINK${idx}@@\n\n`;
    });

    // Extract fenced code blocks
    const codeBlocks = [];
    processed = processed.replace(/```([a-zA-Z0-9_\-\.]*)\r?\n([\s\S]*?)```/g, (match, rawLang, code) => {
      const idx = codeBlocks.length;
      const lang = (rawLang || '').trim().toLowerCase();
      const codeText = code.replace(/\r\n/g, '\n').trimEnd();
      let highlightedCode = '';

      if (typeof window !== 'undefined' && window.hljs) {
        try {
          if (lang && window.hljs.getLanguage(lang)) {
            highlightedCode = window.hljs.highlight(codeText, { language: lang, ignoreIllegals: true }).value;
          } else {
            highlightedCode = window.hljs.highlightAuto(codeText).value;
          }
        } catch {
          highlightedCode = escapeHtml(codeText);
        }
      } else {
        highlightedCode = escapeHtml(codeText);
      }

      const langLabel = lang || 'code';
      codeBlocks.push(
        `<div class="code-block-wrapper">` +
          `<div class="code-block-header">` +
            `<span class="code-block-lang">${escapeHtml(langLabel)}</span>` +
            `<button type="button" class="btn-copy-code" onclick="window.copyCodeBlock(this)" title="Copy Code" aria-label="Copy code">` +
              `<svg class="copy-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>` +
              `<span class="copy-text">Copy</span>` +
            `</button>` +
          `</div>` +
          `<pre><code class="hljs language-${escapeHtml(langLabel)}">${highlightedCode}</code></pre>` +
        `</div>`
      );
      return `\n\n@@AETHERCODE${idx}@@\n\n`;
    });

    // Extract inline code
    const inlineCodes = [];
    processed = processed.replace(/`([^`\r\n]+)`/g, (match, code) => {
      const idx = inlineCodes.length;
      inlineCodes.push(`<code>${escapeHtml(code)}</code>`);
      return `@@AETHERINLINE${idx}@@`;
    });

    // Extract LaTeX Math (Display and Inline)
    const mathBlocks = [];

    // 1. Display math: $$ ... $$
    processed = processed.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
      const idx = mathBlocks.length;
      mathBlocks.push({ formula: formula.trim(), display: true });
      return `\n\n@@AETHERMATH${idx}@@\n\n`;
    });

    // 2. Display math: \[ ... \]
    processed = processed.replace(/\\\[([\s\S]*?)\\\]/g, (match, formula) => {
      const idx = mathBlocks.length;
      mathBlocks.push({ formula: formula.trim(), display: true });
      return `\n\n@@AETHERMATH${idx}@@\n\n`;
    });

    // 3. Inline math: \( ... \)
    processed = processed.replace(/\\\(([\s\S]*?)\\\)/g, (match, formula) => {
      const idx = mathBlocks.length;
      mathBlocks.push({ formula: formula.trim(), display: false });
      return `@@AETHERMATH${idx}@@`;
    });

    // 4. Inline math: $ ... $ (skipping currency amounts like $50 or $100 USD)
    processed = processed.replace(/(?<![\w\$\\])\$([^\s\$](?:[^\$\r\n]*?[^\s\$])?)\$(?![\w\$])/g, (match, formula) => {
      const trimmed = formula.trim();
      if (/^[\d,.]+(\s*(?:USD|EUR|GBP|JPY|CAD|AUD|billion|million|k))?$/i.test(trimmed)) {
        return match;
      }
      const idx = mathBlocks.length;
      mathBlocks.push({ formula: trimmed, display: false });
      return `@@AETHERMATH${idx}@@`;
    });

    // Escape HTML of the remaining narrative text
    let html = escapeHtml(processed);

    // Normalize image URLs
    html = html.replace(/https?:\/\/[^\s\)\"\'\<\>]+(\/api\/generated_images\/)/gi, '$1');

    // Extract images
    const imageBlocks = [];
    html = html.replace(/!\[([^\]\r\n]*)\]\(([^)\r\n]+)\)/g, (match, alt, rawUrl) => {
      let cleanUrl = rawUrl.trim().replace(/&amp;/g, '&');
      if (cleanUrl.includes('/api/generated_images/')) {
        cleanUrl = cleanUrl.replace(/^.*?(\/api\/generated_images\/)/, '$1');
      }
      const idx = imageBlocks.length;
      const captionHtml = alt ? `<div class="chat-image-caption">${alt}</div>` : '';
      imageBlocks.push(
        `<div class="chat-generated-image-card">` +
          `<a href="${escapeHtml(cleanUrl)}" target="_blank" rel="noopener noreferrer" class="chat-generated-image-link" onclick="window.open(this.href, '_blank'); return false;" title="Click to open full resolution: ${escapeHtml(alt || 'Generated image')}">` +
            `<img class="chat-generated-image" src="${escapeHtml(cleanUrl)}" alt="${escapeHtml(alt || 'Generated image')}" loading="lazy" />` +
            `<div class="chat-image-overlay">` +
              `<span class="chat-image-overlay-text">Click to open full resolution</span>` +
            `</div>` +
          `</a>` +
          captionHtml +
        `</div>`
      );
      return `@@AETHERIMG${idx}@@`;
    });

    // Extract links
    const linkBlocks = [];
    html = html.replace(/\[([^\]\r\n]+)\]\((((?:https?|file):\/\/|\/|\.\/)[^)\r\n]+)\)/g, (match, label, rawUrl) => {
      let cleanUrl = rawUrl.trim().replace(/&amp;/g, '&');
      if (cleanUrl.includes('/api/generated_images/')) {
        cleanUrl = cleanUrl.replace(/^.*?(\/api\/generated_images\/)/, '$1');
        const altText = (label === 'Click to open full resolution' || label === 'Image' || label.startsWith('Click to open')) ? '' : label;
        const captionHtml = altText ? `<div class="chat-image-caption">${altText}</div>` : '';
        const imgIdx = imageBlocks.length;
        imageBlocks.push(
          `<div class="chat-generated-image-card">` +
            `<a href="${escapeHtml(cleanUrl)}" target="_blank" rel="noopener noreferrer" class="chat-generated-image-link" onclick="window.open(this.href, '_blank'); return false;" title="Click to open full resolution">` +
              `<img class="chat-generated-image" src="${escapeHtml(cleanUrl)}" alt="${escapeHtml(altText || 'Generated image')}" loading="lazy" />` +
              `<div class="chat-image-overlay">` +
                `<span class="chat-image-overlay-text">Click to open full resolution</span>` +
              `</div>` +
            `</a>` +
            captionHtml +
          `</div>`
        );
        return `@@AETHERIMG${imgIdx}@@`;
      }
      const idx = linkBlocks.length;
      linkBlocks.push(`<a href="${escapeHtml(cleanUrl)}" target="_blank" rel="noopener noreferrer" class="chat-link" title="${escapeHtml(cleanUrl)}">${label}<span class="link-arrow">[link]</span></a>`);
      return `@@AETHERLINK${idx}@@`;
    });

    html = html.replace(/(^|[\s(]|&lt;)((?:https?|file):\/\/[^\s()<>"']+[^\s()<>"'.,:;?!\]\)])(?=[\s)]|&gt;|$)/g, (match, prefix, rawUrl) => {
      const cleanUrl = rawUrl.replace(/&amp;/g, '&');
      const idx = linkBlocks.length;
      linkBlocks.push(`<a href="${escapeHtml(cleanUrl)}" target="_blank" rel="noopener noreferrer" class="chat-link" title="${escapeHtml(cleanUrl)}">${cleanUrl}<span class="link-arrow">[link]</span></a>`);
      return `${prefix}@@AETHERLINK${idx}@@`;
    });

    // Horizontal rules (---, ***, ___)
    html = html.replace(/^[ \t]*(\*{3,}|-{3,}|_{3,})[ \t]*$/gim, '<hr class="chat-hr">');

    // Headers (h1 through h6)
    html = html.replace(/^###### (.*$)/gim, '<h6>$1</h6>');
    html = html.replace(/^##### (.*$)/gim, '<h5>$1</h5>');
    html = html.replace(/^#### (.*$)/gim, '<h4>$1</h4>');
    html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');

    // Bold, strikethrough, and italics
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.*?)__/g, '<strong>$1</strong>');
    html = html.replace(/~~(.*?)~~/g, '<del>$1</del>');

    // Process line by line for Tables, Blockquotes/Callouts, Task Lists, and Ordered/Unordered Lists
    const rawLines = html.split(/\r?\n/);
    const outLines = [];
    let inOl = false;
    let inSubUl = false;
    let inTopUl = false;
    let inTaskList = false;

    let i = 0;
    while (i < rawLines.length) {
      const line = rawLines[i];
      const trimmed = line.trim();

      // Check for Markdown Table
      if (trimmed.includes('|') && i + 1 < rawLines.length) {
        const nextTrimmed = rawLines[i + 1].trim();
        if (/^[\s\|:\-]+$/.test(nextTrimmed) && /-/{2,}/.test(nextTrimmed)) {
          if (inSubUl) { outLines.push('</ul></li>'); inSubUl = false; }
          if (inOl) { outLines.push('</li></ol>'); inOl = false; }
          if (inTopUl) { outLines.push('</ul>'); inTopUl = false; }
          if (inTaskList) { outLines.push('</ul>'); inTaskList = false; }

          const headerCells = trimmed.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
          const delimCells = nextTrimmed.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
          const aligns = delimCells.map(d => {
            if (d.startsWith(':') && d.endsWith(':')) return 'center';
            if (d.endsWith(':')) return 'right';
            if (d.startsWith(':')) return 'left';
            return '';
          });

          i += 2;
          const rows = [];
          while (i < rawLines.length && rawLines[i].trim().includes('|') && rawLines[i].trim().length > 0) {
            const rowCells = rawLines[i].trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
            rows.push(rowCells);
            i++;
          }

          let thHtml = '';
          headerCells.forEach((h, idx) => {
            const alignStyle = aligns[idx] ? ` style="text-align:${aligns[idx]}"` : '';
            thHtml += `<th${alignStyle}>${h}</th>`;
          });

          let trHtml = '';
          rows.forEach(row => {
            let tdHtml = '';
            row.forEach((c, idx) => {
              const alignStyle = (idx < aligns.length && aligns[idx]) ? ` style="text-align:${aligns[idx]}"` : '';
              tdHtml += `<td${alignStyle}>${c}</td>`;
            });
            trHtml += `<tr>${tdHtml}</tr>`;
          });

          outLines.push(
            `<div class="chat-table-wrapper"><table class="chat-table"><thead><tr>${thHtml}</tr></thead><tbody>${trHtml}</tbody></table></div>`
          );
          continue;
        }
      }

      // Check for Blockquote or GitHub Callout (> text)
      if (/^[ \t]*>[ \t]*/.test(line)) {
        if (inSubUl) { outLines.push('</ul></li>'); inSubUl = false; }
        if (inOl) { outLines.push('</li></ol>'); inOl = false; }
        if (inTopUl) { outLines.push('</ul>'); inTopUl = false; }
        if (inTaskList) { outLines.push('</ul>'); inTaskList = false; }

        const bqLines = [];
        while (i < rawLines.length && /^[ \t]*>[ \t]*/.test(rawLines[i])) {
          bqLines.push(rawLines[i].replace(/^[ \t]*>[ \t]?/, ''));
          i++;
        }

        const firstLine = bqLines[0] || '';
        const calloutMatch = firstLine.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$/i);
        if (calloutMatch) {
          const type = calloutMatch[1].toUpperCase();
          const restOfFirst = calloutMatch[2];
          const remainingLines = bqLines.slice(1);
          if (restOfFirst) remainingLines.unshift(restOfFirst);
          const bodyHtml = remainingLines.join('<br>');
          outLines.push(
            `<div class="chat-callout callout-${type.toLowerCase()}">` +
              `<div class="chat-callout-header"><span class="callout-badge">${type}</span></div>` +
              `<div class="chat-callout-body">${bodyHtml}</div>` +
            `</div>`
          );
        } else {
          outLines.push(`<blockquote><p>${bqLines.join('<br>')}</p></blockquote>`);
        }
        continue;
      }

      // Blank line handling
      if (!trimmed) {
        let nextNonEmpty = null;
        for (let j = i + 1; j < rawLines.length; j++) {
          if (rawLines[j].trim()) {
            nextNonEmpty = rawLines[j].trim();
            break;
          }
        }
        if (nextNonEmpty && (/^[\*\-][ \t]+/.test(nextNonEmpty) || /^\d+\.[ \t]+/.test(nextNonEmpty))) {
          i++;
          continue;
        } else {
          if (inSubUl) { outLines.push('</ul></li>'); inSubUl = false; }
          else if (inOl) { outLines.push('</li>'); }
          if (inOl) { outLines.push('</ol>'); inOl = false; }
          if (inTopUl) { outLines.push('</ul>'); inTopUl = false; }
          if (inTaskList) { outLines.push('</ul>'); inTaskList = false; }
          outLines.push('');
          i++;
          continue;
        }
      }

      // Task List items (- [ ] or - [x])
      const taskMatch = line.match(/^[ \t]*[\*\-][ \t]+\[([ xX])\][ \t]+(.*)$/);
      if (taskMatch) {
        if (inTopUl) { outLines.push('</ul>'); inTopUl = false; }
        if (inOl) { outLines.push('</ol>'); inOl = false; }
        if (!inTaskList) {
          outLines.push('<ul class="task-list">');
          inTaskList = true;
        }
        const isChecked = taskMatch[1].toLowerCase() === 'x';
        const taskText = taskMatch[2];
        const checkAttr = isChecked ? 'checked disabled' : 'disabled';
        const textWrapper = isChecked ? `<span class="task-done">${taskText}</span>` : taskText;
        outLines.push(`<li class="task-list-item"><input type="checkbox" ${checkAttr} class="task-checkbox"> ${textWrapper}</li>`);
        i++;
        continue;
      } else if (inTaskList) {
        outLines.push('</ul>');
        inTaskList = false;
      }

      // Ordered list items (1. item)
      const olMatch = line.match(/^[ \t]*(\d+)\.[ \t]+(.*)$/);
      // Unordered list items (- item or * item)
      const ulMatch = line.match(/^[ \t]*[\*\-][ \t]+(.*)$/);

      if (olMatch) {
        const num = parseInt(olMatch[1], 10);
        const content = olMatch[2];
        if (inTopUl) { outLines.push('</ul>'); inTopUl = false; }
        if (inSubUl) { outLines.push('</ul></li>'); inSubUl = false; }
        else if (inOl) { outLines.push('</li>'); }
        if (!inOl) {
          const startAttr = num !== 1 ? ` start="${num}"` : '';
          outLines.push(`<ol${startAttr}>`);
          inOl = true;
        }
        outLines.push(`<li>${content}`);
      } else if (ulMatch) {
        const content = ulMatch[1];
        if (inOl) {
          if (!inSubUl) { outLines.push('<ul>'); inSubUl = true; }
          outLines.push(`<li>${content}</li>`);
        } else {
          if (!inTopUl) { outLines.push('<ul>'); inTopUl = true; }
          outLines.push(`<li>${content}</li>`);
        }
      } else {
        if (inSubUl) { outLines.push('</ul></li>'); inSubUl = false; }
        else if (inOl) { outLines.push('</li>'); }
        if (inOl) { outLines.push('</ol>'); inOl = false; }
        if (inTopUl) { outLines.push('</ul>'); inTopUl = false; }
        outLines.push(line);
      }
      i++;
    }

    if (inSubUl) { outLines.push('</ul></li>'); }
    else if (inOl) { outLines.push('</li>'); }
    if (inOl) outLines.push('</ol>');
    if (inTopUl) outLines.push('</ul>');
    if (inTaskList) outLines.push('</ul>');

    html = outLines.join('\n');

    // Italics
    html = html.replace(/(^|[^\*])\*([^\*\s\r\n][^\*\r\n]*?[^\*\s\r\n])\*(?!\*)/g, '$1<em>$2</em>');
    html = html.replace(/(^|[^_])_([^_\s\r\n][^_\r\n]*?[^_\s\r\n])_(?!_)/g, '$1<em>$2</em>');

    // Paragraphs and line breaks
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    html = `<p>${html}</p>`;

    // Clean up empty tags and br around block elements
    html = html.replace(/<p>\s*<\/p>/g, '');
    html = html.replace(/<p>\s*(<(?:ul|ol|li|pre|h1|h2|h3|h4|h5|h6|blockquote|details|div|hr|table)[^>]*>)/g, '$1');
    html = html.replace(/(<\/(?:ul|ol|li|pre|h1|h2|h3|h4|h5|h6|blockquote|details|div|table)>\s*<hr[^>]*>)\s*<\/p>/g, '$1');
    html = html.replace(/(<\/(?:ul|ol|li|pre|h1|h2|h3|h4|h5|h6|blockquote|details|div|table)>)\s*<\/p>/g, '$1');
    html = html.replace(/(<(?:ul|ol|pre|blockquote|details|div|table)[^>]*>)\s*<br\s*\/?>/g, '$1');
    html = html.replace(/<br\s*\/?>\s*(<\/(?:ul|ol|pre|blockquote|details|div|table)>)/g, '$1');
    html = html.replace(/<br\s*\/?>\s*(<(?:ul|ol|li|pre|h1|h2|h3|h4|h5|h6|blockquote|details|div|table)[^>]*>)/g, '$1');
    html = html.replace(/(<\/(?:ul|ol|li|pre|h1|h2|h3|h4|h5|h6|blockquote|details|div|table)>)\s*<br\s*\/?>/g, '$1');
    html = html.replace(/<br\s*\/?>\s*<\/li>/g, '</li>');
    html = html.replace(/<p>\s*<\/p>/g, '');

    // Restore Math via KaTeX
    mathBlocks.forEach((item, idx) => {
      const rendered = renderKaTeXString(item.formula, item.display);
      const wrapper = item.display
        ? `<div class="chat-math-block">${rendered}</div>`
        : `<span class="chat-math-inline">${rendered}</span>`;
      html = html.replaceAll(`@@AETHERMATH${idx}@@`, () => wrapper);
    });

    // Restore stashed blocks
    thinkBlocks.forEach((thinkHtml, idx) => {
      html = html.replaceAll(`@@AETHERTHINK${idx}@@`, () => thinkHtml);
    });
    imageBlocks.forEach((imgHtml, idx) => {
      html = html.replaceAll(`@@AETHERIMG${idx}@@`, () => imgHtml);
    });
    linkBlocks.forEach((linkHtml, idx) => {
      html = html.replaceAll(`@@AETHERLINK${idx}@@`, () => linkHtml);
    });
    inlineCodes.forEach((code, idx) => {
      html = html.replaceAll(`@@AETHERINLINE${idx}@@`, () => code);
    });
    codeBlocks.forEach((block, idx) => {
      html = html.replaceAll(`@@AETHERCODE${idx}@@`, () => block);
    });

    return html;
  } catch (err) {
    console.error('renderMarkdown error:', err);
    return escapeHtml(md);
  }
}

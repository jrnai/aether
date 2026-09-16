/**
 * Project Aether - AI Assistant Chat Module
 * Native ES Module with real-time SSE streaming & multimodal vision
 */

import { renderMarkdown, showToast, escapeHtml, store } from '../store.js';

let stagedChatImages = [];
export let isChatPending = false;

export function initChatMediaHandlers() {
  const chatCard = document.querySelector('#tab-chat .chat-card');
  const chatInput = document.getElementById('chat-input');

  if (chatCard) {
    ['dragenter', 'dragover'].forEach((eventName) => {
      chatCard.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        chatCard.classList.add('drag-over');
      });
    });

    ['dragleave', 'dragend'].forEach((eventName) => {
      chatCard.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        chatCard.classList.remove('drag-over');
      });
    });

    chatCard.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      chatCard.classList.remove('drag-over');
      const files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length > 0) {
        let imageFound = false;
        Array.from(files).forEach((file) => {
          if (file.type.startsWith('image/')) {
            stageImageFile(file);
            imageFound = true;
          }
        });
        if (imageFound && chatInput) chatInput.focus();
      }
    });
  }

  window.addEventListener('paste', (e) => {
    const { currentTab } = store.getState();
    if (currentTab !== 'chat' && document.activeElement !== chatInput) return;

    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;

    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf('image') !== -1) {
        const file = items[i].getAsFile();
        if (file) {
          e.preventDefault();
          const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
          stageImageFile(file, `screenshot_${timestamp}.png`);
          if (chatInput) chatInput.focus();
          break;
        }
      }
    }
  });

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'S' || e.key === 's')) {
      e.preventDefault();
      snapDesktopScreen();
    }
  });
}

export async function snapDesktopScreen() {
  const snapBtn = document.getElementById('btn-snap-screen');
  const chatInput = document.getElementById('chat-input');
  if (snapBtn) {
    snapBtn.disabled = true;
    snapBtn.classList.add('loading');
  }
  try {
    const res = await fetch('/api/screen/capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_dimension: 1280, quality: 85 }),
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data.status !== 'success' || !data.image_base64) {
      throw new Error(data.message || 'Capture failed');
    }

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const winTitle = data.active_window || 'Desktop';
    const label = `Screen (${winTitle.slice(0, 30)} - ${timestamp})`;

    stagedChatImages.push({
      base64: data.image_base64,
      dataUrl: data.data_url || `data:image/jpeg;base64,${data.image_base64}`,
      name: label,
      activeWindow: winTitle,
    });

    renderStagedImagePreview();
    showToast(`Captured screen (${winTitle})`, 'info');
    if (chatInput) {
      if (!chatInput.value.trim()) {
        chatInput.value = 'What is on my screen?';
      }
      chatInput.focus();
    }
  } catch (err) {
    console.error('Snap screen failed:', err);
    showToast(`Failed to capture screen: ${err.message || err}`, 'error');
  } finally {
    if (snapBtn) {
      snapBtn.disabled = false;
      snapBtn.classList.remove('loading');
    }
  }
}

export function triggerImageAttachment() {
  const fileInput = document.getElementById('chat-file-input');
  if (fileInput) fileInput.click();
}

export function handleImageFileSelect(event) {
  const files = event.target && event.target.files;
  if (!files || files.length === 0) return;

  Array.from(files).forEach((file) => {
    if (file.type.startsWith('image/')) {
      stageImageFile(file);
    }
  });
  event.target.value = '';
  const chatInput = document.getElementById('chat-input');
  if (chatInput) chatInput.focus();
}

function stageImageFile(file, customName) {
  if (!file || !file.type.startsWith('image/')) return;
  const fileName = customName || file.name || 'image.png';

  const reader = new FileReader();
  reader.onload = (e) => {
    const dataUrl = e.target.result;
    const base64Str = dataUrl.includes(',') ? dataUrl.split(',')[1] : dataUrl;
    stagedChatImages.push({
      base64: base64Str,
      dataUrl: dataUrl,
      name: fileName,
    });
    renderStagedImagePreview();
  };
  reader.readAsDataURL(file);
}

export function removeStagedImage(index) {
  if (index >= 0 && index < stagedChatImages.length) {
    stagedChatImages.splice(index, 1);
    renderStagedImagePreview();
  }
}

export function renderStagedImagePreview() {
  const previewBar = document.getElementById('chat-image-preview-bar');
  const attachBtn = document.getElementById('btn-attach-image');
  if (!previewBar) return;

  if (stagedChatImages.length === 0) {
    previewBar.style.display = 'none';
    previewBar.innerHTML = '';
    if (attachBtn) attachBtn.classList.remove('has-staged');
    return;
  }

  previewBar.style.display = 'flex';
  if (attachBtn) attachBtn.classList.add('has-staged');

  previewBar.innerHTML = stagedChatImages
    .map(
      (img, idx) => `
    <div class="chat-image-thumb-wrapper" title="${escapeHtml(img.name)}">
      <img src="${img.dataUrl}" alt="${escapeHtml(img.name)}" />
      <button type="button" class="chat-image-remove-btn" onclick="window.removeStagedImage(${idx})" title="Remove image">&times;</button>
    </div>
  `
    )
    .join('');
}

export async function sendChatMessage() {
  const input = document.getElementById('chat-input');
  const sendBtn = document.getElementById('btn-send-chat');
  const message = input.value.trim();
  if (!message && stagedChatImages.length === 0) return;

  const chatContainer = document.getElementById('chat-messages');

  const imagesToSend = [...stagedChatImages];
  stagedChatImages = [];
  renderStagedImagePreview();

  let imageThumbnailsHtml = '';
  if (imagesToSend.length > 0) {
    imageThumbnailsHtml = `<div class="chat-msg-images">${imagesToSend
      .map(
        (img) => `
      <img class="chat-msg-image" src="${img.dataUrl}" alt="${escapeHtml(img.name)}" onclick="window.open(this.src, '_blank')" />
    `
      )
      .join('')}</div>`;
  }

  const userBubble = document.createElement('div');
  userBubble.className = 'chat-bubble user-bubble';
  userBubble.innerHTML = `
    <div class="bubble-sender" style="color:#CBD5E1;">YOU</div>
    <div class="bubble-text">
      ${escapeHtml(message)}
      ${imageThumbnailsHtml}
    </div>
  `;
  chatContainer.appendChild(userBubble);
  input.value = '';

  const aiBubble = document.createElement('div');
  aiBubble.className = 'chat-bubble ai-bubble';
  const hasImages = imagesToSend.length > 0;
  const thinkingPrompt = hasImages ? 'Analyzing image with Vision model...' : 'Thinking...';
  aiBubble.innerHTML = `
    <div class="bubble-sender">AETHER</div>
    <div class="bubble-text">
      <div class="chat-thinking">
        <span class="chat-thinking-pulse"></span>
        <span>${thinkingPrompt}</span>
      </div>
    </div>
  `;
  chatContainer.appendChild(aiBubble);
  chatContainer.scrollTop = chatContainer.scrollHeight;

  input.disabled = true;
  sendBtn.disabled = true;
  isChatPending = true;

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message || (hasImages ? 'Describe and analyze the attached image in detail.' : ''),
        images: imagesToSend.map((img) => img.base64),
        mode: hasImages ? 'vision' : 'auto',
      }),
    });

    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}`);
    }

    const textEl = aiBubble.querySelector('.bubble-text');
    let accumulatedText = '';
    let modelUsed = hasImages ? 'qwen2.5vl:7b' : 'qwen2.5:7b-instruct';
    let traceObj = null;

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    let renderScheduled = false;

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
        if (!jsonStr || jsonStr === '[DONE]') continue;

        let ev;
        try {
          ev = JSON.parse(jsonStr);
        } catch (parseErr) {
          console.debug('Failed parsing SSE chunk:', parseErr, jsonStr);
          continue;
        }

        if (ev.type === 'token') {
          accumulatedText += ev.delta;
          if (textEl && !renderScheduled) {
            renderScheduled = true;
            requestAnimationFrame(() => {
              renderScheduled = false;
              if (textEl) {
                textEl.innerHTML = renderMarkdown(accumulatedText) + '<span class="chat-cursor-pulse"></span>';
                chatContainer.scrollTop = chatContainer.scrollHeight;
              }
            });
          }
        } else if (ev.type === 'tool_start') {
          if (textEl) {
            const toolName = ev.tool || 'tool';
            textEl.innerHTML = renderMarkdown(accumulatedText) + `<div class="chat-tool-indicator active">[Executing ${escapeHtml(toolName)}...]</div>`;
            chatContainer.scrollTop = chatContainer.scrollHeight;
          }
        } else if (ev.type === 'tool_end') {
          if (textEl) {
            const toolName = ev.tool || 'tool';
            textEl.innerHTML = renderMarkdown(accumulatedText) + `<div class="chat-tool-indicator">[Completed ${escapeHtml(toolName)}]</div>`;
            chatContainer.scrollTop = chatContainer.scrollHeight;
          }
        } else if (ev.type === 'clear_tokens') {
          accumulatedText = '';
          if (textEl) {
            textEl.innerHTML = '<span class="chat-cursor-pulse"></span>';
          }
        } else if (ev.type === 'error') {
          throw new Error(ev.message || 'Stream error');
        } else if (ev.type === 'done') {
          if (ev.full_text) accumulatedText = ev.full_text;
          if (ev.model) modelUsed = ev.model;
          if (ev.trace) traceObj = ev.trace;
        }
      }
    }

    if (textEl) {
      textEl.removeAttribute('style');
      let rendered = renderMarkdown(accumulatedText || 'No response received.');
      rendered += `<div class="chat-model-tag">Generated with <b>${escapeHtml(modelUsed)}</b></div>`;
      if (traceObj) {
        rendered += renderTraceInspectorHtml(traceObj);
      }
      textEl.innerHTML = rendered;
    }
  } catch (err) {
    const textEl = aiBubble.querySelector('.bubble-text');
    let fallbackSuccess = false;

    // Fallback: If streaming failed and no tokens were received, try standard /api/chat endpoint
    if (!accumulatedText) {
      try {
        const fallbackRes = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: message || (hasImages ? 'Describe and analyze the attached image in detail.' : ''),
            images: imagesToSend.map((img) => img.base64),
            mode: hasImages ? 'vision' : 'auto',
          }),
        });
        if (fallbackRes.ok) {
          const fbData = await fallbackRes.json();
          if (fbData && fbData.status === 'success' && fbData.response) {
            let rendered = renderMarkdown(fbData.response);
            rendered += `<div class="chat-model-tag">Generated with <b>${escapeHtml(fbData.model_used || 'fallback')}</b></div>`;
            if (textEl) textEl.innerHTML = rendered;
            fallbackSuccess = true;
          }
        }
      } catch (_) {}
    }

    if (!fallbackSuccess && textEl) {
      textEl.removeAttribute('style');
      textEl.innerHTML = `<span style="color:#EF4444;">Error contacting Aether: ${escapeHtml(err.message || String(err))}. Please verify the server is running.</span>`;
    }
  } finally {
    isChatPending = false;
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }
}

export async function loadChatHistory() {
  const chatContainer = document.getElementById('chat-messages');
  if (!chatContainer) return;

  try {
    const res = await fetch('/api/chat/history');
    if (!res.ok) return;
    const data = await res.json();
    if (data.status === 'success' && data.messages && data.messages.length > 0) {
      chatContainer.innerHTML = '';
      data.messages.forEach((msg) => {
        const bubble = document.createElement('div');
        if (msg.role === 'user') {
          let imageThumbnailsHtml = '';
          if (msg.images && Array.isArray(msg.images) && msg.images.length > 0) {
            imageThumbnailsHtml = `<div class="chat-msg-images">${msg.images
              .map(
                (b64) => `
              <img class="chat-msg-image" src="data:image/jpeg;base64,${b64}" alt="Uploaded image" onclick="window.open(this.src, '_blank')" />
            `
              )
              .join('')}</div>`;
          }
          bubble.className = 'chat-bubble user-bubble';
          bubble.innerHTML = `
            <div class="bubble-sender" style="color:#CBD5E1;">YOU</div>
            <div class="bubble-text">${escapeHtml(msg.content)}${imageThumbnailsHtml}</div>
          `;
        } else {
          bubble.className = 'chat-bubble ai-bubble';
          bubble.innerHTML = `
            <div class="bubble-sender">AETHER</div>
            <div class="bubble-text">${renderMarkdown(msg.content)}</div>
          `;
        }
        chatContainer.appendChild(bubble);
      });
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  } catch (err) {
    console.error('Failed to load chat history:', err);
  }
}

export async function clearChatHistory() {
  if (!confirm('Are you sure you want to clear conversation history?')) return;
  try {
    const res = await fetch('/api/chat/clear', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to clear chat');
    const chatContainer = document.getElementById('chat-messages');
    if (chatContainer) {
      chatContainer.innerHTML = `
        <div class="chat-bubble ai-bubble">
          <div class="bubble-sender">AETHER</div>
          <div class="bubble-text">
            Hello! I am connected to your local calendar, email, and task vault. How can I assist you today?
          </div>
        </div>
      `;
    }
    showToast('Conversation history cleared.', 'info');
  } catch (err) {
    showToast(`Error clearing chat: ${err.message}`, 'error');
  }
}

export function toggleTraceDrawer(traceId) {
  const drawer = document.getElementById(`trace-drawer-${traceId}`);
  if (!drawer) return;
  drawer.style.display = drawer.style.display === 'none' ? 'block' : 'none';
}

export function renderTraceInspectorHtml(trace) {
  if (!trace || !trace.trace_id) return '';
  const latSec = ((trace.total_latency_ms || 0) / 1000).toFixed(2);
  const stepsCount = trace.step_count || (trace.steps ? trace.steps.length : 1);
  const tokensCount = trace.total_tokens || 0;
  const traceId = escapeHtml(trace.trace_id);

  let stepsTimelineHtml = '';
  if (trace.steps && Array.isArray(trace.steps)) {
    stepsTimelineHtml = trace.steps.map((st, idx) => {
      const typeLabel = st.type === 'tool_call' ? `Tool: ${st.name}` : (st.type === 'inference' ? 'Reasoning & Inference' : st.type);
      const badgeClass = st.status === 'error' ? 'status-err' : (st.status === 'cancelled' ? 'status-warn' : 'status-ok');
      return `
        <div class="trace-step-row">
          <span class="trace-step-num">#${idx + 1}</span>
          <span class="trace-step-type ${badgeClass}">${escapeHtml(typeLabel)}</span>
          <span class="trace-step-metric">${st.latency_ms || 0}ms</span>
          <span class="trace-step-metric">${st.tokens || 0} tok</span>
        </div>
      `;
    }).join('');
  }

  return `
    <div class="trace-inspector-container">
      <button type="button" class="trace-badge-btn" onclick="toggleTraceDrawer('${traceId}')" title="Inspect execution trace telemetry" aria-label="Toggle execution trace">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
        <span>Trace: ${latSec}s · ${tokensCount} tok · ${stepsCount} ${stepsCount === 1 ? 'step' : 'steps'}</span>
        <span class="trace-chevron">▼</span>
      </button>
      <div id="trace-drawer-${traceId}" class="trace-drawer" style="display: none;">
        <div class="trace-drawer-header">
          <span>Execution Trace <span class="trace-id-pill">${traceId}</span></span>
          <span class="trace-model-pill">${escapeHtml(trace.model || 'local')}</span>
        </div>
        <div class="trace-timeline-list">
          ${stepsTimelineHtml}
        </div>
      </div>
    </div>
  `;
}


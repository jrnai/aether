/**
 * Project Aether - LLM Models Controller
 * Native ES Module
 */

import { showToast } from '../store.js';

export async function fetchModels() {
  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      const select = document.getElementById('model-select');
      const isAuto = Boolean(data.is_auto_route || data.active_model === 'auto');
      if (select && data.models && data.models.length > 0) {
        let optionsHtml = `<option value="auto" ${isAuto ? 'selected' : ''}>Auto-Route (RTX 5060)</option>`;
        data.models.forEach((m) => {
          let roleTag = '';
          if (m.includes('coder')) roleTag = ' [Coding]';
          else if (m.includes('instruct')) roleTag = ' [Agentic]';
          else if (m.includes('deepseek') || m.includes('r1')) roleTag = ' [Reasoning]';

          const isSelected = !isAuto && m === data.active_model;
          optionsHtml += `<option value="${m}" ${isSelected ? 'selected' : ''}>${m}${roleTag}</option>`;
        });
        select.innerHTML = optionsHtml;
      }
      const modelTag = document.getElementById('editor-active-model-tag');
      const codingModel = (data.roles && data.roles.coding) || 'qwen2.5-coder:7b';
      if (modelTag) modelTag.innerText = `Coding: ${codingModel}`;

      const coderBadge = document.getElementById('coder-model-badge');
      if (coderBadge) {
        coderBadge.innerText = codingModel.split(':')[0];
      }

      const ollamaText = document.getElementById('ollama-status-text');
      const displayActive = isAuto ? 'Auto-Route' : data.active_model;
      if (ollamaText) ollamaText.innerText = `Ollama (${displayActive})`;

      const chatBadge = document.getElementById('chat-active-model-badge');
      if (chatBadge) {
        if (isAuto) {
          chatBadge.innerText = 'Auto-Route (RTX 5060)';
        } else {
          chatBadge.innerText = `Active: ${data.active_model}`;
        }
      }
    }
  } catch (err) {
    console.debug('Failed to fetch models list:', err);
  }
}

export async function changeActiveModel(modelName) {
  try {
    const res = await fetch('/api/models/set', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelName }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      const isAuto = data.is_auto_route || data.active_model === 'auto';
      const label = isAuto ? 'Auto-Route (RTX 5060)' : modelName;
      showToast(`Model routing set to: ${label}`, 'success');

      const modelTag = document.getElementById('editor-active-model-tag');
      if (modelTag) modelTag.innerText = isAuto ? 'Coding: qwen2.5-coder:7b' : `Model: ${modelName}`;

      const ollamaText = document.getElementById('ollama-status-text');
      if (ollamaText) ollamaText.innerText = `Ollama (${isAuto ? 'Auto-Route' : modelName})`;

      const chatBadge = document.getElementById('chat-active-model-badge');
      if (chatBadge) {
        chatBadge.innerText = isAuto ? 'Auto-Route' : `Active: ${modelName}`;
      }
    } else {
      showToast(data.message || 'Failed to switch model', 'error');
    }
  } catch (err) {
    showToast(`Error switching model: ${err.message}`, 'error');
  }
}

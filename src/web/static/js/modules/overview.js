/**
 * Project Aether - Overview & Daily Briefing Module
 * Native ES Module
 */

import { renderMarkdown, showToast, escapeHtml, escapeJsString, isTabVisible } from '../store.js';

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

    // Daily Weather & Hourly Forecast
    fetchWeather();

    // Voice Activation Service Status
    fetchVoiceStatus();
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

export function renderWeatherData(data) {
  const container = document.getElementById('weather-hourly-container');
  const summaryEl = document.getElementById('weather-current-summary');
  const titleEl = document.getElementById('weather-location-title');
  const locSubEl = document.getElementById('weather-location-sub');
  if (!container) return;

  if (data.status !== 'success') {
    container.innerHTML = `<div class="weather-loading-placeholder">Weather unavailable: ${escapeHtml(data.message || 'Error')}</div>`;
    return;
  }

  const configuredLoc = data.configured_location || data.query || data.location || 'Kingston Downtown';
  if (titleEl) {
    titleEl.innerText = configuredLoc;
  }
  if (locSubEl && data.location) {
    locSubEl.innerText = `${data.location} - Real-time & Hourly`;
  }

  const cur = data.current || {};
  const today = data.today || {};
  
  const topWeatherEl = document.getElementById('top-weather');
  if (topWeatherEl && cur.temp_f !== undefined) {
    const cond = cur.condition ? ` · ${cur.condition}` : '';
    topWeatherEl.textContent = `${Math.round(cur.temp_f)}°F${cond}`;
  }

  if (summaryEl) {
    const tempC = cur.temp_c !== undefined ? `${cur.temp_c}°C` : '';
    const tempF = cur.temp_f !== undefined ? `(${cur.temp_f}°F)` : '';
    const cond = cur.condition || '';
    const maxC = today.max_c !== undefined ? `High: ${today.max_c}°C` : '';
    const minC = today.min_c !== undefined ? `Low: ${today.min_c}°C` : '';
    const wind = cur.wind_kmph ? `Wind: ${cur.wind_kmph} km/h ${cur.wind_dir || ''}`.trim() : '';

    summaryEl.innerHTML = `
      <span class="weather-summary-temp">${tempC} ${tempF}</span>
      <span class="weather-summary-stat">${escapeHtml(cond)}</span>
      <span class="weather-summary-stat" style="opacity: 0.4;">|</span>
      <span class="weather-summary-stat">${maxC} / ${minC}</span>
      <span class="weather-summary-stat" style="opacity: 0.4;">|</span>
      <span class="weather-summary-stat">${escapeHtml(wind)}</span>
    `;
  }

  const hourly = today.hourly || [];
  if (!hourly.length) {
    container.innerHTML = `<div class="weather-loading-placeholder">No hourly forecast data available.</div>`;
    return;
  }

  const html = hourly.map((h) => {
    const timeLabel = escapeHtml(h.time_label || h.time || '');
    const temp = `${h.temp_c}°C`;
    const cond = escapeHtml(h.condition || '');
    const wind = `${h.wind_kmph} km/h ${h.wind_dir || ''}`.trim();
    const rain = parseInt(h.rain_chance, 10) || 0;
    const rainClass = rain >= 50 ? 'heavy-rain' : (rain >= 20 ? 'has-rain' : '');

    return `
      <div class="weather-hour-col">
        <div class="weather-hour-time">${timeLabel}</div>
        <div class="weather-hour-temp">${temp}</div>
        <div class="weather-hour-desc" title="${cond}">${cond}</div>
        <div class="weather-hour-wind" title="Wind speed and direction">${escapeHtml(wind)}</div>
        <div class="weather-hour-rain">
          <span class="rain-chance-badge ${rainClass}" title="Chance of rain: ${rain}%">Rain: ${rain}%</span>
        </div>
      </div>
    `;
  }).join('');

  container.innerHTML = html;
}

export async function fetchWeather(force = false) {
  const container = document.getElementById('weather-hourly-container');
  if (!container) return;

  try {
    const url = `/api/weather${force ? '?force=true' : ''}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderWeatherData(data);
  } catch (err) {
    console.error('Failed to fetch weather forecast:', err);
    if (container) {
      container.innerHTML = `<div class="weather-loading-placeholder">Unable to load weather forecast. Check network connection.</div>`;
    }
  }
}

let _weatherSearchTimer = null;
let _weatherSuggestions = [];
let _activeSuggestionIndex = -1;

export function toggleWeatherLocationInput(show) {
  const row = document.getElementById('weather-location-edit-row');
  const input = document.getElementById('weather-location-input');
  const dropdown = document.getElementById('weather-location-dropdown');
  const titleEl = document.getElementById('weather-location-title');
  if (!row) return;

  const willShow = show !== undefined ? show : row.style.display === 'none';
  row.style.display = willShow ? 'flex' : 'none';
  if (dropdown) {
    dropdown.style.display = 'none';
    dropdown.innerHTML = '';
  }
  _weatherSuggestions = [];
  _activeSuggestionIndex = -1;

  if (willShow && input) {
    if (titleEl && titleEl.innerText) {
      input.value = titleEl.innerText;
    } else {
      input.value = '';
    }
    input.focus();
    input.select();
  }
}

export function handleWeatherLocationInput(val) {
  const query = (val || '').trim();
  const dropdown = document.getElementById('weather-location-dropdown');
  if (!dropdown) return;

  if (_weatherSearchTimer) {
    clearTimeout(_weatherSearchTimer);
  }

  if (query.length < 2) {
    dropdown.style.display = 'none';
    dropdown.innerHTML = '';
    _weatherSuggestions = [];
    _activeSuggestionIndex = -1;
    return;
  }

  _weatherSearchTimer = setTimeout(async () => {
    dropdown.style.display = 'block';
    dropdown.innerHTML = '<div class="weather-location-item weather-location-loading">Searching locations...</div>';

    try {
      const res = await fetch(`/api/weather/search?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      // Ensure input hasn't changed or cleared in the meantime
      const currentInput = document.getElementById('weather-location-input');
      if (!currentInput || currentInput.value.trim() !== query) return;

      _weatherSuggestions = data.results || [];
      _activeSuggestionIndex = -1;

      if (_weatherSuggestions.length === 0) {
        dropdown.innerHTML = '<div class="weather-location-no-results">No matching locations found.</div>';
        return;
      }

      dropdown.innerHTML = _weatherSuggestions.map((item, idx) => {
        const regionText = [item.region, item.country].filter(Boolean).join(', ');
        return `
          <button type="button" class="weather-location-item" data-index="${idx}" onclick="selectWeatherLocation('${escapeJsString(item.formatted)}')">
            <span class="loc-item-title">${escapeHtml(item.name)}</span>
            <span class="loc-item-sub">${escapeHtml(regionText || item.formatted)}</span>
          </button>
        `;
      }).join('');
    } catch (err) {
      console.error('Weather location search failed:', err);
      dropdown.innerHTML = '<div class="weather-location-no-results">Search unavailable. Check network.</div>';
    }
  }, 250);
}

export function handleWeatherLocationKeydown(evt) {
  const dropdown = document.getElementById('weather-location-dropdown');
  if (!dropdown || dropdown.style.display === 'none') {
    if (evt.key === 'Enter') {
      evt.preventDefault();
      saveWeatherLocationManual();
    }
    return;
  }

  const items = dropdown.querySelectorAll('.weather-location-item:not(.weather-location-loading)');

  if (evt.key === 'ArrowDown') {
    evt.preventDefault();
    if (items.length === 0) return;
    _activeSuggestionIndex = (_activeSuggestionIndex + 1) % items.length;
    updateActiveSuggestion(items);
  } else if (evt.key === 'ArrowUp') {
    evt.preventDefault();
    if (items.length === 0) return;
    _activeSuggestionIndex = (_activeSuggestionIndex - 1 + items.length) % items.length;
    updateActiveSuggestion(items);
  } else if (evt.key === 'Enter') {
    evt.preventDefault();
    if (_activeSuggestionIndex >= 0 && _weatherSuggestions[_activeSuggestionIndex]) {
      selectWeatherLocation(_weatherSuggestions[_activeSuggestionIndex].formatted);
    } else if (_weatherSuggestions.length === 1) {
      selectWeatherLocation(_weatherSuggestions[0].formatted);
    } else {
      saveWeatherLocationManual();
    }
  } else if (evt.key === 'Escape') {
    evt.preventDefault();
    dropdown.style.display = 'none';
  }
}

function updateActiveSuggestion(items) {
  items.forEach((el, idx) => {
    if (idx === _activeSuggestionIndex) {
      el.classList.add('active');
      el.scrollIntoView({ block: 'nearest' });
    } else {
      el.classList.remove('active');
    }
  });
}

export async function selectWeatherLocation(locationStr) {
  const dropdown = document.getElementById('weather-location-dropdown');
  const input = document.getElementById('weather-location-input');
  if (dropdown) dropdown.style.display = 'none';
  if (input) input.value = locationStr;

  _weatherSuggestions = [];
  _activeSuggestionIndex = -1;

  showToast(`Updating weather location to ${locationStr}...`, 'info');
  try {
    const res = await fetch('/api/weather/location', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ location: locationStr }),
    });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      toggleWeatherLocationInput(false);
      if (data.weather) {
        renderWeatherData(data.weather);
      } else {
        fetchWeather(true);
      }
      showToast(`Weather location updated to ${data.location}`, 'success');
    } else {
      showToast(data.message || 'Failed to update location', 'error');
    }
  } catch (err) {
    console.error('Failed to save weather location:', err);
    showToast('Error connecting to server', 'error');
  }
}

export async function saveWeatherLocationManual() {
  const input = document.getElementById('weather-location-input');
  if (!input) return;
  const val = input.value.trim();
  if (!val) {
    showToast('Please type a location name to search', 'error');
    return;
  }
  if (_weatherSuggestions.length > 0) {
    const target = (_activeSuggestionIndex >= 0 && _weatherSuggestions[_activeSuggestionIndex])
      ? _weatherSuggestions[_activeSuggestionIndex].formatted
      : _weatherSuggestions[0].formatted;
    return selectWeatherLocation(target);
  }

  showToast(`Searching for '${val}'...`, 'info');
  try {
    const res = await fetch(`/api/weather/search?q=${encodeURIComponent(val)}`);
    const data = await res.json();
    if (data.results && data.results.length > 0) {
      return selectWeatherLocation(data.results[0].formatted);
    }
    showToast(`No verified geographic location found for '${val}'. Please select a matched city.`, 'error');
  } catch (_) {
    showToast('Could not verify location', 'error');
  }
}

export async function fetchVoiceStatus() {
  try {
    const res = await fetch('/api/voice/status');
    if (!res.ok) return;
    const data = await res.json();
    renderVoiceStatus(data);
  } catch (_) {}
}

export function renderVoiceStatus(data) {
  const topText = document.getElementById('top-voice-text');
  const topDot = document.getElementById('top-voice-dot');
  const topBadge = document.getElementById('top-voice-badge');
  const sideText = document.getElementById('voice-status-text');
  const sideDot = document.getElementById('voice-dot');

  const isRunning = data && data.running;
  const state = (data && data.state ? data.state : 'IDLE').toUpperCase();
  const wakeWord = data && data.wake_word ? data.wake_word : 'aether';

  if (!isRunning) {
    if (topText) topText.innerText = 'Voice: Inactive';
    if (topDot) topDot.className = 'dot dot-gray';
    if (topBadge) {
      topBadge.className = 'connection-badge-box voice-badge-box';
      topBadge.title = `Hands-free voice inactive. Click to enable listening for "${wakeWord}".`;
    }
    if (sideText) sideText.innerText = 'Voice (Inactive)';
    if (sideDot) sideDot.className = 'dot dot-gray';
    return;
  }

  // Running states
  if (state === 'RECORDING') {
    if (topText) topText.innerText = 'Voice: Listening...';
    if (topDot) topDot.className = 'dot dot-yellow';
    if (topBadge) {
      topBadge.className = 'connection-badge-box voice-badge-box active recording';
      topBadge.title = 'Listening to microphone... Speak now!';
    }
    if (sideText) sideText.innerText = 'Voice (Listening...)';
    if (sideDot) sideDot.className = 'dot dot-yellow';
  } else if (state === 'TRANSCRIBING') {
    if (topText) topText.innerText = 'Voice: Transcribing...';
    if (topDot) topDot.className = 'dot dot-blue';
    if (topBadge) {
      topBadge.className = 'connection-badge-box voice-badge-box active transcribing';
      topBadge.title = 'Whisper transcribing audio...';
    }
    if (sideText) sideText.innerText = 'Voice (Transcribing...)';
    if (sideDot) sideDot.className = 'dot dot-blue';
  } else if (state === 'PROCESSING') {
    if (topText) topText.innerText = 'Voice: Thinking...';
    if (topDot) topDot.className = 'dot dot-blue';
    if (topBadge) {
      topBadge.className = 'connection-badge-box voice-badge-box active processing';
      topBadge.title = 'Aether processing voice request...';
    }
    if (sideText) sideText.innerText = 'Voice (Thinking...)';
    if (sideDot) sideDot.className = 'dot dot-blue';
  } else {
    // LISTENING
    if (topText) topText.innerText = `Voice: Active ("${wakeWord}")`;
    if (topDot) topDot.className = 'dot dot-green';
    if (topBadge) {
      topBadge.className = 'connection-badge-box voice-badge-box active';
      topBadge.title = `Hands-free voice active: listening for "${wakeWord}". Click to speak now.`;
    }
    if (sideText) sideText.innerText = `Voice (Active: "${wakeWord}")`;
    if (sideDot) sideDot.className = 'dot dot-green';
  }
}

export async function toggleVoiceActivation() {
  try {
    const res = await fetch('/api/voice/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      showToast('Failed to toggle voice service', 'error');
      return;
    }
    const data = await res.json();
    renderVoiceStatus(data);
    if (data.running) {
      showToast(`Voice listening active: Say "${data.wake_word}" or click mic`, 'success');
    } else {
      showToast('Voice listening stopped', 'info');
    }
  } catch (err) {
    console.error('Error toggling voice service:', err);
    showToast('Error connecting to voice service', 'error');
  }
}

export async function listenNow() {
  try {
    showToast('Listening... Speak now', 'info');
    openVoiceOverlay('RECORDING');
    const res = await fetch('/api/voice/listen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      showToast('Failed to start microphone listening', 'error');
      return;
    }
    const data = await res.json();
    renderVoiceStatus(data);
  } catch (err) {
    console.error('Error triggering voice recording:', err);
    showToast('Error connecting to voice service', 'error');
  }
}

export async function handleVoiceBadgeClick() {
  const topBadge = document.getElementById('top-voice-badge');
  const overlay = document.getElementById('voice-assistant-overlay');
  const isOverlayOpen = overlay && (overlay.classList.contains('active') || overlay.style.display === 'flex');
  const isBusy = topBadge && (
    topBadge.classList.contains('speaking') ||
    topBadge.classList.contains('transcribing') ||
    topBadge.classList.contains('recording') ||
    topBadge.classList.contains('listening')
  );

  if (isOverlayOpen || isBusy) {
    // Immediate barge-in interrupt: cancel audio/turn and dismiss overlay immediately
    closeVoiceOverlay(false);
    return;
  }

  if (topBadge && topBadge.classList.contains('active')) {
    listenNow();
  } else {
    toggleVoiceActivation();
  }
}

let voiceEventSource = null;
let overlayAutoDismissTimer = null;

export function openVoiceOverlay(initialState = 'RECORDING') {
  const overlay = document.getElementById('voice-assistant-overlay');
  if (overlayAutoDismissTimer) {
    clearTimeout(overlayAutoDismissTimer);
    overlayAutoDismissTimer = null;
  }

  if (overlay) {
    overlay.style.display = 'flex';
    overlay.offsetHeight;
    overlay.classList.add('active');
  }

  setVoiceOverlayState(initialState);
}

export function closeVoiceOverlay(skipApiCall = false) {
  const overlay = document.getElementById('voice-assistant-overlay');
  if (overlayAutoDismissTimer) {
    clearTimeout(overlayAutoDismissTimer);
    overlayAutoDismissTimer = null;
  }

  // Signal interrupt to backend only if initiated locally (user click / Esc), avoiding feedback loops
  if (!skipApiCall) {
    fetch('/api/voice/interrupt', { method: 'POST' }).catch(() => {});
  }

  if (overlay) {
    overlay.classList.remove('active');
    setTimeout(() => {
      if (!overlay.classList.contains('active')) {
        overlay.style.display = 'none';
        overlay.className = 'voice-assistant-overlay';
        const qBox = document.getElementById('voice-overlay-query-box');
        const aBox = document.getElementById('voice-overlay-answer-box');
        if (qBox) qBox.style.display = 'none';
        if (aBox) aBox.style.display = 'none';
      }
    }, 200);
  }

  setVoiceOverlayState('IDLE');
  fetchVoiceStatus();
}

export function handleVoiceOverlayBackdropClick(event) {
  if (event.target && event.target.id === 'voice-assistant-overlay') {
    closeVoiceOverlay(false);
  }
}

export function setVoiceOverlayState(state) {
  const overlay = document.getElementById('voice-assistant-overlay');
  const badge = document.getElementById('top-voice-badge');
  const statusBadge = document.getElementById('voice-overlay-status');
  const statusText = document.getElementById('voice-overlay-status-text');

  const normalized = (state || 'RECORDING').toUpperCase();

  if (badge) {
    badge.classList.remove('listening', 'transcribing', 'speaking');
  }

  if (overlay) {
    overlay.classList.remove('state-recording', 'state-transcribing', 'state-processing', 'state-speaking');
  }
  if (statusBadge) {
    statusBadge.className = 'voice-overlay-status-badge';
  }

  if (normalized === 'RECORDING') {
    if (badge) badge.classList.add('listening');
    if (overlay) overlay.classList.add('state-recording');
    if (statusBadge) statusBadge.classList.add('status-listening');
    if (statusText) statusText.innerText = 'Listening to you...';
  } else if (normalized === 'TRANSCRIBING') {
    if (badge) badge.classList.add('transcribing');
    if (overlay) overlay.classList.add('state-transcribing');
    if (statusBadge) statusBadge.classList.add('status-transcribing');
    if (statusText) statusText.innerText = 'Transcribing speech...';
  } else if (normalized === 'PROCESSING') {
    if (badge) badge.classList.add('speaking');
    if (overlay) overlay.classList.add('state-processing');
    if (statusBadge) statusBadge.classList.add('status-processing');
    if (statusText) statusText.innerText = 'Thinking...';
  } else if (normalized === 'SPEAKING') {
    if (badge) badge.classList.add('speaking');
    if (overlay) overlay.classList.add('state-speaking');
    if (statusBadge) statusBadge.classList.add('status-speaking');
    if (statusText) statusText.innerText = 'Answering...';
  } else if (normalized === 'LISTENING' || normalized === 'IDLE' || normalized === 'DONE') {
    if (statusBadge) {
      statusBadge.className = 'voice-overlay-status-badge status-speaking';
    }
    if (statusText) statusText.innerText = 'Complete';
  }
}

export function displayVoiceTranscript(text) {
  const qBox = document.getElementById('voice-overlay-query-box');
  const qText = document.getElementById('voice-overlay-query-text');
  if (qBox && qText && text) {
    qText.innerText = `"${text}"`;
    qBox.style.display = 'block';
  }
}

export function displayVoiceAnswer(text) {
  const aBox = document.getElementById('voice-overlay-answer-box');
  const aText = document.getElementById('voice-overlay-answer-text');
  if (aBox && aText && text) {
    aText.innerHTML = renderMarkdown(text);
    aBox.style.display = 'block';
    setVoiceOverlayState('SPEAKING');
  }
}

export function initVoiceEventsSSE() {
  if (voiceEventSource) return;

  try {
    const es = new EventSource('/api/voice/events');
    voiceEventSource = es;

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (!data || !data.type) return;

        if (data.type === 'snapshot') {
          renderVoiceStatus(data);
        } else if (data.type === 'interrupt') {
          // Interrupt means cancel/stop: close overlay immediately without re-firing API
          if (overlayAutoDismissTimer) {
            clearTimeout(overlayAutoDismissTimer);
            overlayAutoDismissTimer = null;
          }
          closeVoiceOverlay(true);
        } else if (data.type === 'state') {
          renderVoiceStatus(data);
          const st = (data.state || '').toUpperCase();
          if (st === 'RECORDING') {
            openVoiceOverlay('RECORDING');
            const qBox = document.getElementById('voice-overlay-query-box');
            const aBox = document.getElementById('voice-overlay-answer-box');
            if (qBox) qBox.style.display = 'none';
            if (aBox) aBox.style.display = 'none';
          } else if (st === 'TRANSCRIBING' || st === 'PROCESSING' || st === 'SPEAKING') {
            const overlay = document.getElementById('voice-assistant-overlay');
            if (!overlay || overlay.style.display === 'none') {
              openVoiceOverlay(st);
            } else {
              setVoiceOverlayState(st);
            }
          } else if (st === 'LISTENING' || st === 'IDLE') {
            const overlay = document.getElementById('voice-assistant-overlay');
            if (overlay && overlay.classList.contains('active')) {
              const aBox = document.getElementById('voice-overlay-answer-box');
              const hasAnswer = aBox && aBox.style.display !== 'none';
              if (!hasAnswer) {
                if (overlayAutoDismissTimer) clearTimeout(overlayAutoDismissTimer);
                overlayAutoDismissTimer = setTimeout(() => {
                  closeVoiceOverlay(true);
                }, 800);
              }
            }
          }
        } else if (data.type === 'transcript') {
          openVoiceOverlay('PROCESSING');
          displayVoiceTranscript(data.text);
        } else if (data.type === 'answer') {
          displayVoiceAnswer(data.text);
          if (typeof window.loadChatHistory === 'function') {
            window.loadChatHistory();
          }
        }
      } catch (err) {
        console.error('Error parsing voice event:', err);
      }
    };

    es.onerror = () => {
      // Reconnects automatically
    };
  } catch (err) {
    console.debug('SSE initialization failed:', err);
  }
}

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const overlay = document.getElementById('voice-assistant-overlay');
    const badge = document.getElementById('top-voice-badge');
    const isOverlayOpen = overlay && (overlay.classList.contains('active') || overlay.style.display === 'flex');
    const isBusy = badge && (
      badge.classList.contains('listening') ||
      badge.classList.contains('speaking') ||
      badge.classList.contains('transcribing') ||
      badge.classList.contains('recording')
    );

    if (isOverlayOpen || isBusy) {
      closeVoiceOverlay(false);
    }
  }
});

function setupVoiceOverlayBackdropListener() {
  const overlay = document.getElementById('voice-assistant-overlay');
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        closeVoiceOverlay(false);
      }
    });
  }
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupVoiceOverlayBackdropListener);
  } else {
    setupVoiceOverlayBackdropListener();
  }
}





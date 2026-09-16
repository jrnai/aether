/**
 * Project Aether - Calendar & Focus Slots Module
 * Native ES Module
 */

import { escapeHtml, formatIsoTime, formatEventTime, formatEventDate, isTabVisible } from '../store.js';

const gcalColorMap = {
  1: '#a4bdfc',
  2: '#7ae7bf',
  3: '#dbadff',
  4: '#ff887c',
  5: '#fbd75b',
  6: '#ffb878',
  7: '#46d6db',
  8: '#e1e1e1',
  9: '#5484ed',
  10: '#51b749',
  11: '#dc2127',
};

const monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];

const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

let currentCalendarView = localStorage.getItem('aether_calendar_view') || 'calendar';
let viewDate = new Date();
let cachedEvents = [];

export function setCalendarView(view) {
  currentCalendarView = view === 'list' ? 'list' : 'calendar';
  try {
    localStorage.setItem('aether_calendar_view', currentCalendarView);
  } catch (_) {}

  const calBtn = document.getElementById('cal-view-calendar-btn');
  const listBtn = document.getElementById('cal-view-list-btn');
  const gridView = document.getElementById('calendar-grid-view');
  const listView = document.getElementById('calendar-events-table');

  if (calBtn) calBtn.classList.toggle('active', currentCalendarView === 'calendar');
  if (listBtn) listBtn.classList.toggle('active', currentCalendarView === 'list');

  if (gridView) gridView.style.display = currentCalendarView === 'calendar' ? 'block' : 'none';
  if (listView) listView.style.display = currentCalendarView === 'list' ? 'block' : 'none';

  if (currentCalendarView === 'calendar') {
    renderCalendarGrid(cachedEvents, viewDate.getFullYear(), viewDate.getMonth());
  } else {
    renderEventsTable(cachedEvents);
  }
}

export function prevMonth() {
  viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1);
  fetchCalendarForMonth();
}

export function nextMonth() {
  viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1);
  fetchCalendarForMonth();
}

export function goToToday() {
  viewDate = new Date();
  fetchCalendarForMonth();
}

async function fetchCalendarForMonth() {
  const y = viewDate.getFullYear();
  const m = viewDate.getMonth();
  const start = new Date(y, m, -6).toISOString();
  const end = new Date(y, m + 1, 7).toISOString();
  await fetchCalendar(false, start, end);
}

function getEventDateKey(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) {
    return isoStr.slice(0, 10);
  }
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatShortTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return '';
  let hours = d.getHours();
  const mins = d.getMinutes();
  const ampm = hours >= 12 ? 'p' : 'a';
  hours = hours % 12 || 12;
  return mins === 0 ? `${hours}${ampm}` : `${hours}:${String(mins).padStart(2, '0')}${ampm}`;
}

export function renderCalendarGrid(events, year, month) {
  const gridContainer = document.getElementById('calendar-month-grid');
  const monthTitle = document.getElementById('cal-month-title');
  const countBadge = document.getElementById('cal-event-count-badge');

  if (monthTitle) {
    monthTitle.innerText = `${monthNames[month]} ${year}`;
  }

  if (!gridContainer) return;

  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  const eventsByDate = new Map();
  let monthEventCount = 0;

  for (const ev of events) {
    const start = ev.start || ev.start_time;
    if (!start) continue;
    const dateKey = getEventDateKey(start);
    if (!eventsByDate.has(dateKey)) {
      eventsByDate.set(dateKey, []);
    }
    eventsByDate.get(dateKey).push(ev);

    const d = new Date(start);
    if (!isNaN(d.getTime()) && d.getFullYear() === year && d.getMonth() === month) {
      monthEventCount++;
    }
  }

  if (countBadge) {
    countBadge.innerText = `${monthEventCount} Event${monthEventCount === 1 ? '' : 's'}`;
  }

  const firstDay = new Date(year, month, 1);
  const startingDay = firstDay.getDay(); // 0 = Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const daysInPrevMonth = new Date(year, month, 0).getDate();
  const totalCells = Math.ceil((startingDay + daysInMonth) / 7) * 7;

  let html = '';

  for (const dayName of dayNames) {
    html += `<div class="cal-day-header">${dayName}</div>`;
  }

  for (let i = 0; i < totalCells; i++) {
    let cellDay, cellMonth, cellYear, isOtherMonth;

    if (i < startingDay) {
      cellDay = daysInPrevMonth - startingDay + i + 1;
      cellMonth = month - 1;
      cellYear = year;
      isOtherMonth = true;
    } else if (i < startingDay + daysInMonth) {
      cellDay = i - startingDay + 1;
      cellMonth = month;
      cellYear = year;
      isOtherMonth = false;
    } else {
      cellDay = i - (startingDay + daysInMonth) + 1;
      cellMonth = month + 1;
      cellYear = year;
      isOtherMonth = true;
    }

    const cellDate = new Date(cellYear, cellMonth, cellDay);
    const dateKey = `${cellDate.getFullYear()}-${String(cellDate.getMonth() + 1).padStart(2, '0')}-${String(cellDate.getDate()).padStart(2, '0')}`;
    const isToday = dateKey === todayKey;

    const cellClasses = ['cal-day-cell'];
    if (isOtherMonth) cellClasses.push('is-other-month');
    if (isToday) cellClasses.push('is-today');

    const dayEvents = eventsByDate.get(dateKey) || [];
    dayEvents.sort((a, b) => {
      const aStart = a.start || a.start_time || '';
      const bStart = b.start || b.start_time || '';
      return aStart.localeCompare(bStart);
    });

    const maxVisible = 3;
    const visibleEvents = dayEvents.slice(0, maxVisible);
    const overflowCount = dayEvents.length - maxVisible;

    let eventsHtml = '';
    for (const ev of visibleEvents) {
      const title = ev.title || ev.summary || '(Untitled)';
      const start = ev.start || ev.start_time;
      const timeLabel = formatShortTime(start);
      const colorHex = ev.color_id && gcalColorMap[ev.color_id] ? gcalColorMap[ev.color_id] : 'var(--cyan)';
      const loc = ev.location ? ` @ ${ev.location}` : '';
      const tooltip = `${title}${timeLabel ? ` (${timeLabel})` : ''}${loc}`;

      const linkAttr = ev.html_link
        ? `onclick="window.open('${escapeHtml(ev.html_link)}', '_blank')"`
        : '';

      eventsHtml += `
        <button class="cal-event-pill" type="button" style="border-left-color: ${colorHex};" title="${escapeHtml(tooltip)}" ${linkAttr}>
          ${timeLabel ? `<span class="cal-event-pill-time">${escapeHtml(timeLabel)}</span>` : ''}
          <span class="cal-event-pill-title">${escapeHtml(title)}</span>
        </button>
      `;
    }

    if (overflowCount > 0) {
      eventsHtml += `<div class="cal-event-more">+${overflowCount} more</div>`;
    }

    html += `
      <div class="${cellClasses.join(' ')}" data-date="${dateKey}">
        <div class="cal-day-top">
          <span class="cal-day-number">${cellDay}</span>
        </div>
        <div class="cal-day-events">
          ${eventsHtml}
        </div>
      </div>
    `;
  }

  gridContainer.innerHTML = html;
}

export function renderEventsTable(events) {
  const tableContainer = document.getElementById('calendar-events-table');
  if (!tableContainer) return;

  if (events.length === 0) {
    tableContainer.innerHTML = '<div class="empty-state">No scheduled events found. Clear skies ahead!</div>';
    return;
  }

  let html = `
    <table class="events-table">
      <thead>
        <tr>
          <th style="min-width: 140px;">Day & Date</th>
          <th style="min-width: 155px;">Time</th>
          <th>Summary</th>
          <th>Location</th>
          <th style="width: 100px;">Status</th>
        </tr>
      </thead>
      <tbody>
  `;
  for (const ev of events) {
    const title = ev.title || ev.summary || '(Untitled Event)';
    const start = ev.start || ev.start_time;
    const end = ev.end || ev.end_time;
    const dateHtml = formatEventDate(start, ev);
    const timeStr = formatEventTime(start, end);
    const location = ev.location || '-';
    const sourceBadge =
      ev.source === 'google_calendar'
        ? '<span class="badge" style="background:rgba(66,133,244,0.15); color:#93C5FD; font-size:0.75rem; margin-left:0.4rem;">Google Cal</span>'
        : '';
    const link = ev.html_link
      ? `<a href="${escapeHtml(ev.html_link)}" target="_blank" rel="noopener noreferrer" class="event-link" title="Open in Google Calendar">View [link]</a>`
      : '';
    const colorHex = ev.color_id && gcalColorMap[ev.color_id] ? gcalColorMap[ev.color_id] : null;
    const colorDot = colorHex
      ? `<span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:${colorHex}; margin-right:7px; vertical-align:middle; box-shadow:0 0 4px ${colorHex}88;" title="Color #${ev.color_id}"></span>`
      : '';

    html += `
      <tr>
        <td>${dateHtml}</td>
        <td class="event-time-badge">${escapeHtml(timeStr)}</td>
        <td>
          ${colorDot}<strong>${escapeHtml(title)}</strong>
          ${link}
          ${sourceBadge}
        </td>
        <td style="color:var(--text-muted);">${escapeHtml(location)}</td>
        <td><span class="badge badge-success">Confirmed</span></td>
      </tr>
    `;
  }
  html += `</tbody></table>`;
  tableContainer.innerHTML = html;
}

export async function fetchCalendar(force = false, customStart = null, customEnd = null) {
  if (!isTabVisible()) return;

  try {
    let url = '/api/calendar';
    if (customStart && customEnd) {
      url += `?start=${encodeURIComponent(customStart)}&end=${encodeURIComponent(customEnd)}`;
    }
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();

    const events = data.events || [];
    const freeSlots = data.free_slots || [];
    cachedEvents = events;

    const statEvents = document.getElementById('stat-events-count');
    if (statEvents) statEvents.innerText = events.length;
    const statFree = document.getElementById('stat-free-count');
    if (statFree) statFree.innerText = freeSlots.length;

    renderFreeSlots('overview-free-slots', freeSlots.slice(0, 4));
    renderFreeSlots('full-free-slots', freeSlots);

    setCalendarView(currentCalendarView);
  } catch (err) {
    console.error('Failed to fetch calendar:', err);
  }
}

export function renderFreeSlots(elementId, slots) {
  const container = document.getElementById(elementId);
  if (!container) return;

  if (slots.length === 0) {
    container.innerHTML = '<div class="empty-state">No uninterrupted 30m+ gaps detected.</div>';
    return;
  }

  let html = '';
  for (const s of slots) {
    const start = formatIsoTime(s.start);
    const end = formatIsoTime(s.end);
    html += `
      <div class="slot-item">
        <span class="slot-time">${start} - ${end}</span>
        <span class="slot-dur">${s.duration_minutes} min focus</span>
      </div>
    `;
  }
  container.innerHTML = html;
}

// Bind to window for inline onclick accessibility
if (typeof window !== 'undefined') {
  window.setCalendarView = setCalendarView;
  window.prevMonth = prevMonth;
  window.nextMonth = nextMonth;
  window.goToToday = goToToday;
  window.fetchCalendar = fetchCalendar;
}

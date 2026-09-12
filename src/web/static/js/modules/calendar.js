/**
 * Project Aether - Calendar & Focus Slots Module
 * Native ES Module
 */

import { escapeHtml, formatIsoTime, formatEventTime, formatEventDate, isTabVisible } from '../store.js';

export async function fetchCalendar() {
  if (!isTabVisible()) return;

  try {
    const res = await fetch('/api/calendar');
    if (!res.ok) return;
    const data = await res.json();

    const events = data.events || [];
    const freeSlots = data.free_slots || [];

    const statEvents = document.getElementById('stat-events-count');
    if (statEvents) statEvents.innerText = events.length;
    const statFree = document.getElementById('stat-free-count');
    if (statFree) statFree.innerText = freeSlots.length;

    renderFreeSlots('overview-free-slots', freeSlots.slice(0, 4));
    renderFreeSlots('full-free-slots', freeSlots);

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

    const tableContainer = document.getElementById('calendar-events-table');
    if (!tableContainer) return;

    if (events.length === 0) {
      tableContainer.innerHTML = '<div class="empty-state">No scheduled events found for today. Clear skies ahead!</div>';
    } else {
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

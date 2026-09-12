/**
 * Project Aether - Tasks (Obsidian/Vault) Module
 * Native ES Module
 */

import { escapeHtml, escapeJsString, showToast, isTabVisible } from '../store.js';

let currentTaskFilter = 'pending';
let currentPriorityFilter = 'all';

export async function fetchTasks() {
  if (!isTabVisible()) return;

  try {
    let url = `/api/tasks?status=${currentTaskFilter}`;
    if (currentPriorityFilter && currentPriorityFilter !== 'all') {
      url += `&priority=${encodeURIComponent(currentPriorityFilter)}`;
    }
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    const tasks = data.tasks || [];

    const pendingTasks = tasks.filter((t) => !t.completed && t.status !== 'completed');
    renderTaskList('overview-tasks-list', pendingTasks.slice(0, 5), false);
    renderTaskList('full-tasks-list', tasks, true);
  } catch (err) {
    console.error('Failed to fetch tasks:', err);
  }
}

export function renderTaskList(containerId, tasks, allowDelete) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (tasks.length === 0) {
    container.innerHTML = '<div class="empty-state">No tasks found.</div>';
    return;
  }

  let html = '';
  for (const t of tasks) {
    const isCompleted = Boolean(t.completed || t.status === 'completed');
    const priorityVal = (t.priority || 'normal').toLowerCase();
    const priorityIcons = {
      urgent: 'Urgent',
      important: 'Important',
      normal: 'Normal',
    };
    const priorityLabel = priorityIcons[priorityVal] || 'Normal';
    const tagHtml = t.tags && t.tags.length > 0 ? `<span class="task-tag">#${escapeHtml(t.tags[0].replace(/^#/, ''))}</span>` : '';
    const dueValue = t.due_date || t.due;
    const dueHtml = dueValue ? `<span class="task-due">Due: ${escapeHtml(dueValue)}</span>` : '';
    const fileSource = t.file ? `<span class="stat-meta">[${escapeHtml(t.file)}]</span>` : '';

    html += `
      <div class="task-item priority-${priorityVal} ${isCompleted ? 'completed' : ''}">
        <input 
          type="checkbox" 
          class="task-checkbox" 
          ${isCompleted ? 'checked disabled' : ''} 
          onchange="window.toggleTaskComplete('${escapeJsString(t.text)}', '${escapeJsString(t.file || 'Inbox.md')}')"
        >
        <span class="task-text ${isCompleted ? 'task-name-crossed' : ''}">${escapeHtml(t.text)}</span>
        <span 
          class="badge-priority badge-${priorityVal}" 
          title="Priority: ${priorityVal}. Click to cycle priority (Normal -> Important -> Urgent)"
          onclick="window.cycleTaskPriority('${escapeJsString(t.text)}', '${priorityVal}', '${escapeJsString(t.file || 'Inbox.md')}')"
        >
          ${priorityLabel}
        </span>
        ${tagHtml}
        ${dueHtml}
        ${fileSource}
        ${
          allowDelete
            ? `
          <button class="btn-del-task" title="Delete Task" onclick="window.deleteTaskItem('${escapeJsString(t.text)}', '${escapeJsString(t.file || 'Inbox.md')}')">
            X
          </button>
        `
            : ''
        }
      </div>
    `;
  }
  container.innerHTML = html;
}

export function filterTasks(status) {
  currentTaskFilter = status;
  document.querySelectorAll('.task-filter-btns .btn-chip').forEach((btn) => {
    btn.classList.toggle('active', btn.id === `filter-${status}`);
  });
  fetchTasks();
}

export function filterPriority(priority) {
  currentPriorityFilter = priority;
  document.querySelectorAll('.task-priority-filter-btns .btn-chip').forEach((btn) => {
    btn.classList.toggle('active', btn.id === `priority-filter-${priority}`);
  });
  fetchTasks();
}

export async function cycleTaskPriority(taskText, currentPriority, project) {
  const nextPriorityMap = {
    normal: 'important',
    important: 'urgent',
    urgent: 'normal',
  };
  const nextPriority = nextPriorityMap[currentPriority] || 'normal';
  try {
    const res = await fetch('/api/tasks/priority', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: taskText, priority: nextPriority, project: project }),
    });
    if (res.ok) {
      showToast(`Priority updated to ${nextPriority.toUpperCase()}: "${taskText}"`, 'info');
      fetchTasks();
      if (window.fetchOverview) window.fetchOverview();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.message || 'Failed to update priority', 'error');
    }
  } catch (err) {
    console.error('Failed to update task priority:', err);
    showToast('Failed to update priority', 'error');
  }
}

export async function quickAddTask() {
  const input = document.getElementById('quick-task-input');
  const prioritySelect = document.getElementById('quick-task-priority-input');
  const text = input ? input.value.trim() : '';
  const priority = prioritySelect ? prioritySelect.value : 'normal';

  if (!text) {
    if (input) input.focus();
    showToast('Please enter a task description', 'warning');
    return;
  }

  const success = await postNewTask(text, null, priority);
  if (success) {
    if (input) input.value = '';
    filterTasks('pending');
    if (window.fetchOverview) window.fetchOverview();
  }
}

export async function addNewTask() {
  const descInput = document.getElementById('task-desc-input');
  const dueInput = document.getElementById('task-due-input');
  const priorityInput = document.getElementById('task-priority-input');
  const addBtn = document.getElementById('btn-add-task');

  const text = descInput ? descInput.value.trim() : '';
  const due = dueInput ? dueInput.value || null : null;
  const priority = priorityInput ? priorityInput.value : 'normal';

  if (!text) {
    if (descInput) descInput.focus();
    showToast('Please enter a task description', 'warning');
    return;
  }

  if (addBtn) {
    addBtn.disabled = true;
    addBtn.classList.add('loading');
  }

  try {
    const success = await postNewTask(text, due, priority);
    if (success) {
      if (descInput) descInput.value = '';
      if (dueInput) dueInput.value = '';
      filterTasks('pending');
      if (window.fetchOverview) window.fetchOverview();
    }
  } finally {
    if (addBtn) {
      addBtn.disabled = false;
      addBtn.classList.remove('loading');
    }
  }
}

async function postNewTask(text, dueDate, priority = 'normal') {
  try {
    const res = await fetch('/api/tasks/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: text, due_date: dueDate, priority: priority, project: 'Inbox' }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.message || 'Failed to add task', 'error');
      return false;
    }
    showToast(`Task added (${priority.toUpperCase()}): "${text}"`, 'success');
    return true;
  } catch (err) {
    console.error('Failed to add task:', err);
    showToast('Failed to connect to server', 'error');
    return false;
  }
}

export async function toggleTaskComplete(taskText, project) {
  try {
    const res = await fetch('/api/tasks/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: taskText, project: project }),
    });
    if (res.ok) {
      showToast(`Completed: "${taskText}"`, 'success');
    }
    fetchTasks();
    if (window.fetchOverview) window.fetchOverview();
  } catch (err) {
    console.error('Failed to complete task:', err);
    showToast('Failed to complete task', 'error');
  }
}

export async function deleteTaskItem(taskText, project) {
  if (!confirm(`Delete task: "${taskText}"?`)) return;
  try {
    const res = await fetch('/api/tasks/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: taskText, project: project }),
    });
    if (res.ok) {
      showToast(`Deleted task: "${taskText}"`, 'info');
    }
    fetchTasks();
    if (window.fetchOverview) window.fetchOverview();
  } catch (err) {
    console.error('Failed to delete task:', err);
    showToast('Failed to delete task', 'error');
  }
}

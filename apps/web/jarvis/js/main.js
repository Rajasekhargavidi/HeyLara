import { API_BASE, AGENT_POLL_MS, apiUrl } from './config.js';
import { Universe } from './universe.js';
import { JarvisCore } from './jarvisCore.js';
import { AgentConstellation, AGENTS } from './agents.js';
import { ollamaHealth } from './ollamaService.js';

const token = localStorage.getItem('jarvis_token');
if (!token) {
  window.location.replace('/login.html');
  throw new Error('Authentication required');
}

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const role = localStorage.getItem('jarvis_role') || 'VIEWER';
const email = localStorage.getItem('jarvis_email') || 'operator';
const startedAt = Date.now();

$('#whoami').textContent = `${email} · ${role}`;
$('#sessionRole').textContent = `${role} / ENCRYPTED`;

function logout() {
  localStorage.removeItem('jarvis_token');
  localStorage.removeItem('jarvis_role');
  localStorage.removeItem('jarvis_email');
  window.location.replace('/login.html');
}

$('#logoutBtn').addEventListener('click', logout);

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(apiUrl(path), { ...options, headers });
  if (response.status === 401) {
    logout();
    throw new Error('Session expired');
  }
  return response;
}

function safeJson(response) {
  return response.json().catch(() => ({}));
}

function addMessage(who, content) {
  const item = document.createElement('div');
  item.className = `msg ${who === 'You' ? 'you' : 'jarvis'}`;
  const mark = document.createElement('span');
  mark.className = 'msg-mark';
  mark.textContent = who === 'You' ? '›' : 'J';
  const copy = document.createElement('div');
  const stamp = document.createElement('small');
  stamp.textContent = `${who.toUpperCase()} · ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  const text = document.createElement('p');
  text.textContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  copy.append(stamp, text);
  item.append(mark, copy);
  $('#log').appendChild(item);
  $('#log').scrollTop = $('#log').scrollHeight;
}

function responseText(data) {
  const results = data?.results || {};
  if (typeof results.answer === 'string') return results.answer;
  if (typeof results.recommendations === 'string') return results.recommendations;
  if (results.drafts?.length) return `Created ${results.drafts.length} campaign draft${results.drafts.length === 1 ? '' : 's'}.\n${results.drafts.map((draft) => draft.content || draft.title || '').join('\n\n')}`;
  if (results.task) return `Task ${results.task.status || 'updated'}${results.task.latest_update ? `: ${results.task.latest_update}` : '.'}`;
  if (results.published_post) return `Published to ${results.published_post.platform || 'the connected channel'}.`;
  return data?.recommended_next_step || data?.objective || 'Command completed.';
}

function setCoreState(state, caption) {
  $('#orbState').textContent = state.toUpperCase();
  $('#orbCaption').textContent = caption;
  window.jarvisCore?.setState(state);
  $('#streamState').textContent = state === 'idle' ? 'READY' : state.toUpperCase();
}

async function speakReply(reply) {
  if (!('speechSynthesis' in window) || !reply) return;
  window.speechSynthesis.cancel();
  setCoreState('speaking', 'Delivering your response…');
  await new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(reply);
    utterance.lang = 'en-IN';
    utterance.rate = 1;
    utterance.pitch = 1.05;
    const safety = setTimeout(resolve, Math.max(5000, reply.length * 140));
    const finish = () => { clearTimeout(safety); resolve(); };
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  });
}

async function sendCommand(message, spokenInput = false) {
  const text = (message || $('#input').value).trim();
  if (!text) return;
  addMessage('You', text);
  $('#input').value = '';
  $('#sendBtn').disabled = true;
  setCoreState('thinking', 'Processing your request through the agent network…');
  try {
    const response = await api('/api/chat', { method: 'POST', body: JSON.stringify({ message: text }) });
    const data = await safeJson(response);
    if (!response.ok) {
      const detail = data.detail || data.message || `Request rejected (${response.status})`;
      addMessage('JARVIS', detail);
      setCoreState('idle', 'Command was not authorized.');
      return;
    }
    const reply = responseText(data);
    addMessage('JARVIS', reply);
    if ((spokenInput || $('#voiceReplyToggle').checked) && 'speechSynthesis' in window) await speakReply(reply);
    await refreshActivity();
  } catch (error) {
    addMessage('JARVIS', `Uplink interrupted: ${error.message}`);
    setCoreState('idle', 'Awaiting a new command.');
  } finally {
    $('#sendBtn').disabled = false;
    setCoreState('idle', 'Awaiting your command.');
  }
}

$('#commandForm').addEventListener('submit', (event) => { event.preventDefault(); sendCommand(); });
$('#input').addEventListener('input', () => {
  if ($('#input').value.trim()) setCoreState('listening', 'Go on, I’m listening.');
  else setCoreState('idle', 'Awaiting your command.');
});

let speechRecognizer;
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
$('#micBtn').addEventListener('click', () => {
  if (!SpeechRecognition) {
    $('#voiceUnsupported').textContent = 'Voice input is unavailable in this browser.';
    return;
  }
  if (speechRecognizer) { speechRecognizer.stop(); return; }
  if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
    $('#voiceUnsupported').textContent = 'Voice input requires HTTPS or localhost.';
    return;
  }
  speechRecognizer = new SpeechRecognition();
  speechRecognizer.lang = 'en-IN';
  speechRecognizer.interimResults = false;
  speechRecognizer.maxAlternatives = 1;
  speechRecognizer.onstart = () => {
    $('#micBtn').classList.add('recording');
    $('#voiceReplyToggle').checked = true;
    setCoreState('listening', 'Listening…');
  };
  speechRecognizer.onresult = (event) => {
    const result = event.results[event.resultIndex] || event.results[event.results.length - 1];
    const transcript = result?.[0]?.transcript?.trim();
    if (transcript) sendCommand(transcript, true);
  };
  speechRecognizer.onerror = (event) => {
    const errors = {
      'not-allowed': 'Microphone permission was denied. Allow microphone access for localhost.',
      'audio-capture': 'No microphone was found. Check the Windows input device.',
      'network': 'The browser speech service needs internet access.',
      'no-speech': 'No speech detected. Speak immediately after pressing the microphone button.',
    };
    $('#voiceUnsupported').textContent = errors[event.error] || `Voice input error: ${event.error}`;
    setCoreState('idle', 'Awaiting your command.');
  };
  speechRecognizer.onend = () => { speechRecognizer = null; $('#micBtn').classList.remove('recording'); };
  speechRecognizer.start();
});
if (!('speechSynthesis' in window)) $('#voiceReplyToggle').disabled = true;

window.jarvisUniverse = new Universe($('#universe'));
window.jarvisCore = new JarvisCore($('#core-viewport'));
window.jarvisAgents = new AgentConstellation($('#agent-viewport'), (agent) => {
  $('#agentDetail').textContent = `${agent.label.toUpperCase()} · ${agent.id} · LINK STABLE`;
  setCoreState('listening', `${agent.label} is ready for instructions.`);
  setTimeout(() => setCoreState('idle', 'Awaiting your command.'), 1800);
});
$('#agentCount').textContent = `${String(AGENTS.length).padStart(2, '0')} ONLINE`;

function updateClock() {
  $('#clock').textContent = new Date().toLocaleTimeString([], { hour12: false });
  const uptime = Math.floor((Date.now() - startedAt) / 1000);
  $('#uptime').textContent = [Math.floor(uptime / 3600), Math.floor(uptime / 60) % 60, uptime % 60].map((v) => String(v).padStart(2, '0')).join(':');
}
setInterval(updateClock, 1000);
updateClock();

async function refreshHealth() {
  try {
    const response = await fetch(apiUrl('/api/health'));
    const data = await safeJson(response);
    if (!response.ok) throw new Error('offline');
    $('#systemDot').style.background = 'var(--green)';
    $('#systemStatus').textContent = 'UPLINK ONLINE';
    $('#hudSignalText').textContent = 'ONLINE';
    $('#hudMode').textContent = String(data.jarvis_mode || 'ACTIVE').toUpperCase();
    $('#hudLlm').textContent = String(data.llm_provider || 'API').toUpperCase();
  } catch {
    $('#systemDot').style.background = 'var(--red)';
    $('#systemStatus').textContent = 'UPLINK OFFLINE';
    $('#hudSignalText').textContent = 'OFFLINE';
  }
}

function renderActivity(rows) {
  const feed = $('#activityFeed');
  if (!rows?.length) { feed.innerHTML = '<div class="empty-state">Awaiting agent activity…</div>'; return; }
  feed.innerHTML = rows.slice(0, 12).map((row) => `<div class="activity-row"><i></i><div><b>${escapeHtml(row.actor || 'system')}</b> · ${escapeHtml(row.tool || 'telemetry')}<small>${new Date(row.created_at).toLocaleTimeString()} · ${row.ok ? 'completed' : 'failed'}</small></div></div>`).join('');
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
}

async function refreshActivity() {
  try {
    const response = await api('/api/audit-log');
    if (response.ok) renderActivity(await response.json());
  } catch { /* Viewer/support sessions may not have access to the audit stream. */ }
}

async function loadApprovals() {
  const response = await api('/api/chat', { method: 'POST', body: JSON.stringify({ message: 'show pending approvals' }) });
  const data = await safeJson(response);
  const rows = data.results?.pending || [];
  const body = $('#approvalsTable tbody');
  body.innerHTML = rows.length ? rows.map((draft) => `<tr><td>${escapeHtml(draft.platform)}</td><td>${escapeHtml((draft.content || '').slice(0, 110))}…</td><td>${new Date(draft.created_at).toLocaleString()}</td><td><button class="outline-btn approve-btn" data-id="${escapeHtml(draft.id)}">APPROVE</button></td></tr>`).join('') : '<tr><td colspan="4">No pending approvals.</td></tr>';
  $$('.approve-btn').forEach((button) => button.addEventListener('click', async () => { await sendCommand(`approve and publish ${button.dataset.id}`); loadApprovals(); }));
}

async function loadAudit() {
  const response = await api('/api/audit-log');
  const rows = response.ok ? await response.json() : [];
  $('#auditTable tbody').innerHTML = rows.length ? rows.map((row) => `<tr><td>${new Date(row.created_at).toLocaleString()}</td><td>${escapeHtml(row.actor)}</td><td>${escapeHtml(row.tool)}</td><td>${row.ok ? 'OK' : 'FAILED'}</td></tr>`).join('') : '<tr><td colspan="4">Audit log is restricted to ADMIN / VIEWER roles or has no events.</td></tr>';
}

async function loadKnowledge() {
  const response = await api('/api/knowledge/documents');
  const rows = response.ok ? await response.json() : [];
  $('#knowledgeTable tbody').innerHTML = rows.map((row) => `<tr><td>${escapeHtml(row.title)}</td><td>${escapeHtml(row.source)}</td><td>${escapeHtml(row.access_role)}</td><td>${new Date(row.created_at).toLocaleString()}</td></tr>`).join('') || '<tr><td colspan="4">No knowledge documents indexed.</td></tr>';
}

async function loadBriefing() {
  const response = await api('/api/technology/briefing');
  const rows = response.ok ? await response.json() : [];
  $('#techList').innerHTML = rows.map((row) => `<article class="info-card"><b>${escapeHtml(row.title)}</b><p>${escapeHtml(row.what_changed || row.summary || '')}</p><p class="muted">${escapeHtml(row.source || '')} · ${escapeHtml(row.rank || '')}</p></article>`).join('') || '<div class="empty-state">No updates yet. Ask JARVIS to research the latest updates.</div>';
}

async function loadCustomer() {
  const response = await api('/api/customer/messages');
  const rows = response.ok ? await response.json() : [];
  $('#customerList').innerHTML = rows.map((row) => `<article class="info-card"><b>${escapeHtml(row.customer_name || row.sender || 'Customer')}</b><p>${escapeHtml(row.content || row.message || '')}</p><p class="muted">${escapeHtml(row.status || 'OPEN')} · ${new Date(row.created_at).toLocaleString()}</p></article>`).join('') || '<div class="empty-state">Inbox is clear.</div>';
}

async function loadLeads() {
  const response = await api('/api/leads');
  const rows = response.ok ? await response.json() : [];
  $('#leadsTable tbody').innerHTML = rows.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.contact || row.email || row.phone || '')}</td><td>${escapeHtml(row.notes || '')}</td><td>${new Date(row.created_at).toLocaleString()}</td></tr>`).join('') || '<tr><td colspan="4">No captured leads.</td></tr>';
}

async function loadCeo() {
  const response = await api('/api/ceo/overview');
  const data = response.ok ? await response.json() : {};
  const entries = Object.entries(data);
  $('#ceoCards').innerHTML = entries.slice(0, 4).map(([key, value]) => `<div class="metric-card"><small>${escapeHtml(key.replaceAll('_', ' ').toUpperCase())}</small><strong>${escapeHtml(typeof value === 'object' ? JSON.stringify(value) : value)}</strong></div>`).join('') || '<div class="metric-card"><small>STATUS</small><strong>ONLINE</strong></div>';
  $('#ceoContent').textContent = entries.slice(4).map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`).join('\n') || 'Operational overview is ready.';
}

async function loadTasks() {
  const [employees, tasks] = await Promise.all([api('/api/employees'), api('/api/employee-tasks')]);
  const employeeRows = employees.ok ? await employees.json() : [];
  const taskRows = tasks.ok ? await tasks.json() : [];
  $('#empSelect').innerHTML = employeeRows.map((employee) => `<option value="${escapeHtml(employee.id)}">${escapeHtml(employee.name || employee.email)}</option>`).join('');
  $('#taskList').innerHTML = taskRows.map((task) => `<article class="info-card"><b>${escapeHtml(task.description || task.title || 'Task')}</b><p>${escapeHtml(task.status || 'PENDING')} · ${escapeHtml(task.channel || '')} · ${task.updated_at ? new Date(task.updated_at).toLocaleString() : ''}</p></article>`).join('') || '<div class="empty-state">No active employee tasks.</div>';
}

const loaders = { ceo: loadCeo, approvals: loadApprovals, audit: loadAudit, knowledge: loadKnowledge, technology: loadBriefing, customer: loadCustomer, leads: loadLeads, 'employee-tasks': loadTasks };
$$('.item').forEach((button) => button.addEventListener('click', async () => {
  $$('.item').forEach((item) => item.classList.toggle('active', item === button));
  $$('.view').forEach((view) => view.classList.toggle('active-view', view.id === `view-${button.dataset.view}`));
  if (loaders[button.dataset.view]) {
    try { await loaders[button.dataset.view](); } catch (error) { addMessage('JARVIS', `Could not load ${button.textContent.trim()}: ${error.message}`); }
  }
}));

$('#ingestBtn').addEventListener('click', async () => {
  const file = $('#kFile').files[0];
  if (!file || !$('#kTitle').value.trim()) { $('#kMsg').textContent = 'Choose a file and enter a title first.'; return; }
  const form = new FormData();
  form.append('file', file); form.append('title', $('#kTitle').value.trim()); form.append('access_role', $('#kRole').value);
  $('#kMsg').textContent = 'Indexing document…';
  const response = await api('/api/knowledge/ingest', { method: 'POST', body: form });
  const data = await safeJson(response);
  $('#kMsg').textContent = response.ok ? `Ingested ${data.title || file.name} as ${data.chunks || 0} chunks.` : (data.detail || 'Ingestion failed.');
  if (response.ok) { $('#kFile').value = ''; $('#kTitle').value = ''; loadKnowledge(); }
});

$('#refreshBriefingBtn').addEventListener('click', () => sendCommand("research today's AI, Playwright, Tosca and AEM updates"));
$('#assignTaskBtn').addEventListener('click', async () => {
  const description = $('#taskDesc').value.trim();
  if (!description) { $('#empMsg').textContent = 'Enter a task description first.'; return; }
  $('#empMsg').textContent = 'Assigning through the agent network…';
  await sendCommand(`assign employee task: ${description} via ${$('#taskChannel').value}`);
  $('#empMsg').textContent = 'Assignment request sent.';
});

refreshHealth();
refreshActivity();
setInterval(refreshHealth, 15000);
setInterval(refreshActivity, AGENT_POLL_MS);
ollamaHealth().then((status) => { if (status.configured) $('#hudLlm').textContent = 'OLLAMA'; }).catch(() => {});

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
let voiceLang = 'en-IN'; // 'en-IN' or 'te-IN' — toggled by the language button
let speechRecognizer = null;

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
  if (results.opened) return data?.objective || `Opening ${results.opened}…`;
  if (results.launched) return data?.objective || `Launching ${results.launched}…`;
  if (results.error) return `Sorry, I couldn't do that: ${results.error}`;
  return data?.recommended_next_step || data?.objective || 'Command completed.';
}

function setCoreState(state, caption) {
  $('#orbState').textContent = state.toUpperCase();
  $('#orbCaption').textContent = caption;
  window.jarvisCore?.setState(state);
  $('#streamState').textContent = state === 'idle' ? 'READY' : state.toUpperCase();
}

function stripMarkdown(text) {
  return text
    .replace(/```[\s\S]*?```/g, '')          // remove code blocks entirely
    .replace(/`[^`]*`/g, '')                  // remove inline code
    .replace(/\*\*([^*]+)\*\*/g, '$1')        // **bold** → plain
    .replace(/\*([^*]+)\*/g, '$1')            // *italic* → plain
    .replace(/_{1,2}([^_]+)_{1,2}/g, '$1')   // _italic_ / __bold__
    .replace(/~~([^~]+)~~/g, '$1')            // ~~strikethrough~~
    .replace(/^#{1,6}\s+/gm, '')              // headings
    .replace(/^\s*[-*+]\s+/gm, '')            // bullet points
    .replace(/^\s*\d+\.\s+/gm, '')            // numbered lists
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // [link text](url) → text
    .replace(/[|>{}[\]\\]/g, ' ')             // table pipes, blockquotes, brackets
    .replace(/\n{2,}/g, '. ')                 // paragraph breaks → pause
    .replace(/\n/g, ' ')                      // single newlines → space
    .replace(/\s{2,}/g, ' ')                  // collapse whitespace
    .trim();
}

// Split long text into sentence chunks — Chrome cuts off utterances > ~200 chars.
function splitSentences(text) {
  return text.match(/[^.!?।\n]{1,180}(?:[.!?।\n]|$)/g)?.map((s) => s.trim()).filter(Boolean) || [text];
}

async function speakReply(reply) {
  if (!('speechSynthesis' in window) || !reply) return;
  window.speechSynthesis.cancel();
  setCoreState('speaking', 'Delivering your response…');

  // Pause mic so JARVIS voice doesn't feed back into recognition.
  const wasMicActive = typeof speechRecognizer !== 'undefined' && !!speechRecognizer;
  if (wasMicActive) { try { speechRecognizer.stop(); } catch (_) {} }

  const clean = stripMarkdown(reply);

  // Auto-detect Telugu script in the reply — if Telugu characters found, speak Telugu.
  const hasTeluguScript = /[ఀ-౿]/.test(clean);
  const lang = hasTeluguScript ? 'te-IN' : (typeof voiceLang !== 'undefined' ? voiceLang : 'en-IN');

  // Load voices — some browsers need a short wait for the list to populate.
  let voices = window.speechSynthesis.getVoices();
  if (!voices.length) {
    await new Promise((res) => { window.speechSynthesis.onvoiceschanged = res; setTimeout(res, 1000); });
    voices = window.speechSynthesis.getVoices();
  }

  const voice = voices.find((v) => v.lang === lang)
    || voices.find((v) => v.lang.startsWith(lang.split('-')[0]))
    || null;

  // Speak sentence by sentence to avoid Chrome's cut-off bug.
  for (const chunk of splitSentences(clean)) {
    await new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(chunk);
      utterance.lang = lang;
      if (voice) utterance.voice = voice;
      utterance.rate = 0.92;
      utterance.pitch = 1.05;
      const safety = setTimeout(resolve, Math.max(3000, chunk.length * 120));
      const finish = () => { clearTimeout(safety); resolve(); };
      utterance.onend = finish;
      utterance.onerror = finish;
      window.speechSynthesis.speak(utterance);
    });
  }

  setCoreState('listening', 'Voice session active — waiting for your command…');

  // Resume mic after speaking — reset lastResultIndex so stale results are skipped.
  if (wasMicActive && speechRecognizer) {
    setTimeout(() => {
      if (speechRecognizer) {
        speechRecognizer._resetIndex = true; // signal onresult to reset lastResultIndex
        try { speechRecognizer.start(); } catch (_) {}
      }
    }, 500);
  }
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

// --- System / media command router ---
// URLs are opened directly in the browser (window.open) — no backend round-trip needed.
// App launches go through the backend because the browser can't spawn native processes.
async function launchApp(appName) {
  try {
    const resp = await api('/api/system/action', {
      method: 'POST',
      body: JSON.stringify({ action: 'open_app', payload: appName }),
    });
    return resp.ok;
  } catch (_) { return false; }
}

function openTab(url) {
  // Use location.href on same tab to avoid popup blocker; open in new tab as fallback.
  const a = document.createElement('a');
  a.href = url; a.target = '_blank'; a.rel = 'noopener';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

// tryLocalCommand always returns false — all commands go through the agent,
// which calls open_system_url server-side (webbrowser.open) so popup blockers
// can't interfere. Keeping this as a no-op so call sites don't break.
async function tryLocalCommand(_text) {
  return false;
}

$('#commandForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = $('#input').value.trim();
  if (text && await tryLocalCommand(text)) { $('#input').value = ''; return; }
  sendCommand();
});
$('#input').addEventListener('input', () => {
  if ($('#input').value.trim()) setCoreState('listening', 'Go on, I\'m listening.');
  else setCoreState('idle', 'Awaiting your command.');
});

// --- Language toggle: English ↔ Telugu ---
const langToggleBtn = document.createElement('button');
langToggleBtn.type = 'button';
langToggleBtn.className = 'tool-btn';
langToggleBtn.textContent = 'EN';
langToggleBtn.title = 'Switch voice language between English and Telugu';
langToggleBtn.addEventListener('click', () => {
  voiceLang = voiceLang === 'en-IN' ? 'te-IN' : 'en-IN';
  langToggleBtn.textContent = voiceLang === 'en-IN' ? 'EN' : 'TE';
  langToggleBtn.style.color = voiceLang === 'te-IN' ? 'var(--amber, #f59e0b)' : '';
  if (speechRecognizer) {
    // Restart recognizer with new language mid-session.
    try { speechRecognizer.stop(); } catch (_) {}
  }
  addMessage('JARVIS', voiceLang === 'te-IN'
    ? 'తెలుగు వాయిస్ ఇన్‌పుట్ ఎనేబుల్ అయింది. మీరు తెలుగులో మాట్లాడవచ్చు.'
    : 'Switched to English voice input.');
});
$('.command-tools').appendChild(langToggleBtn);

// --- Voice input: click to activate, 3-minute session, auto-sleep on silence ---
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let voiceSessionTimer = null;   // 3-minute auto-sleep timer
let voiceCountdownInterval = null;
const VOICE_SESSION_MS = 3 * 60 * 1000; // 3 minutes

function voiceCountdownLabel(remainingMs) {
  const s = Math.ceil(remainingMs / 1000);
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `◉ Voice active ${mm}:${ss}`;
}

function stopVoiceSession(reason) {
  if (speechRecognizer) { try { speechRecognizer.abort(); } catch (_) {} speechRecognizer = null; }
  clearTimeout(voiceSessionTimer); voiceSessionTimer = null;
  clearInterval(voiceCountdownInterval); voiceCountdownInterval = null;
  $('#micBtn').classList.remove('recording');
  $('#micBtn').textContent = '◉ Voice input';
  $('#voiceUnsupported').textContent = reason || '';
  $('#input').value = '';
  setCoreState('idle', 'Voice session ended. Click to reactivate.');
}

function startListeningCycle() {
  if (!speechRecognizer) return; // session was stopped
  try { speechRecognizer.start(); } catch (_) {}
}

function startVoiceSession() {
  if (!SpeechRecognition) {
    $('#voiceUnsupported').textContent = 'Voice input is unavailable in this browser.';
    return;
  }
  if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
    $('#voiceUnsupported').textContent = 'Voice input requires HTTPS or localhost.';
    return;
  }

  // Build recognizer once per session; restart it on each onend cycle.
  let pendingTranscript = '';
  let submitTimer = null;
  const SUBMIT_DELAY_MS = 4000; // wait 4 s after last speech before sending

  speechRecognizer = new SpeechRecognition();
  speechRecognizer.lang = voiceLang;
  speechRecognizer.interimResults = true;  // capture partial results so we can show them
  speechRecognizer.maxAlternatives = 1;
  speechRecognizer.continuous = true;      // keep mic open; we control submission timing

  speechRecognizer.onstart = () => {
    $('#micBtn').classList.add('recording');
    $('#voiceReplyToggle').checked = true;
    setCoreState('listening', 'Listening… finish speaking, I will wait.');
    $('#voiceUnsupported').textContent = '';
    $('#input').value = '';
  };

  let lastResultIndex = 0; // track where we left off to avoid re-accumulating old results

  speechRecognizer.onresult = (event) => {
    // After speaking a reply the mic restarts — skip everything said before that point.
    if (speechRecognizer._resetIndex) {
      lastResultIndex = event.results.length;
      speechRecognizer._resetIndex = false;
      return;
    }
    // Only accumulate NEW results since the last submission.
    let full = '';
    for (let i = lastResultIndex; i < event.results.length; i++) {
      full += (event.results[i][0]?.transcript || '');
    }
    pendingTranscript = full.trim();
    $('#input').value = pendingTranscript;
    setCoreState('listening', 'Got it… keep going or wait 4 seconds.');

    // Reset the 4-second submit timer on every new word.
    clearTimeout(submitTimer);
    submitTimer = setTimeout(async () => {
      const text = pendingTranscript;
      pendingTranscript = '';
      $('#input').value = '';
      submitTimer = null;
      if (!text) return;

      // Advance the index so next onresult doesn't re-include what we just sent.
      lastResultIndex = event.results.length;

      // Reset the 3-minute idle timer.
      clearTimeout(voiceSessionTimer);
      voiceSessionTimer = setTimeout(() => stopVoiceSession('Voice session timed out after 3 minutes of no activity.'), VOICE_SESSION_MS);

      // Route locally if it's a media/system command; otherwise send to agent.
      const handled = await tryLocalCommand(text);
      if (!handled) sendCommand(text, true);
    }, SUBMIT_DELAY_MS);
  };

  speechRecognizer.onerror = (event) => {
    if (event.error === 'no-speech') {
      // Silence — restart the cycle; session timer keeps ticking.
      return;
    }
    const errors = {
      'not-allowed': 'Microphone permission denied. Allow microphone access for localhost.',
      'audio-capture': 'No microphone found. Check Windows input device.',
      'network': 'Browser speech service needs internet access.',
    };
    stopVoiceSession(errors[event.error] || `Voice error: ${event.error}`);
  };

  speechRecognizer.onend = () => {
    // continuous mode — only restart if an unexpected drop; session stop sets speechRecognizer = null first.
    if (speechRecognizer) setTimeout(startListeningCycle, 200);
  };

  // Start the 3-minute auto-sleep timer.
  voiceSessionTimer = setTimeout(() => stopVoiceSession('Voice session timed out after 3 minutes of no activity.'), VOICE_SESSION_MS);

  // Update button with live countdown every second.
  const sessionStart = Date.now();
  voiceCountdownInterval = setInterval(() => {
    const remaining = VOICE_SESSION_MS - (Date.now() - sessionStart);
    if (remaining <= 0) { clearInterval(voiceCountdownInterval); return; }
    $('#micBtn').textContent = voiceCountdownLabel(remaining);
  }, 1000);

  $('#micBtn').classList.add('recording');
  setCoreState('listening', 'Voice session active — waiting for your command…');
  startListeningCycle();
}

$('#micBtn').addEventListener('click', () => {
  if (speechRecognizer) {
    stopVoiceSession('Voice session stopped.');
  } else {
    startVoiceSession();
  }
});

if (!('speechSynthesis' in window)) {
  $('#voiceReplyToggle').disabled = true;
} else {
  // Pre-load voice list — Chrome loads voices async on first call.
  window.speechSynthesis.getVoices();
  window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
}

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

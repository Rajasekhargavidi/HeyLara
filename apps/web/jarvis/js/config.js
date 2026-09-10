// Browser configuration is deliberately runtime-configurable. The API can
// provide its own Ollama model; this client never silently selects one.
const runtime = window.JARVIS_CONFIG || {};
const browserModel = window.OLLAMA_MODEL || window.__OLLAMA_MODEL__ || '';
export const API_BASE = runtime.API_BASE || '';
export const OLLAMA_BASE_URL = runtime.OLLAMA_BASE_URL || window.localStorage.getItem('ollama_base_url') || '';
export const OLLAMA_MODEL = runtime.OLLAMA_MODEL || browserModel || window.localStorage.getItem('ollama_model') || '';
export const AGENT_POLL_MS = Number(runtime.AGENT_POLL_MS || 8000);
export const apiUrl = (path) => `${API_BASE}${path}`;

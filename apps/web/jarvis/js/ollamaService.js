import { OLLAMA_BASE_URL, OLLAMA_MODEL } from './config.js';

// Optional direct Ollama adapter for installations that expose Ollama to the
// browser. The authenticated FastAPI chat route remains the primary path.
export async function ollamaGenerate(messages, options = {}) {
  if (!OLLAMA_BASE_URL || !OLLAMA_MODEL) throw new Error('Ollama is not configured: set OLLAMA_BASE_URL and OLLAMA_MODEL at runtime.');
  const response = await fetch(`${OLLAMA_BASE_URL.replace(/\/$/, '')}/api/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: OLLAMA_MODEL, messages, stream: false, options }),
  });
  if (!response.ok) throw new Error(`Ollama returned ${response.status}`);
  const data = await response.json();
  return data.message?.content || '';
}

export async function ollamaHealth() {
  if (!OLLAMA_BASE_URL) return { configured: false };
  try { const response = await fetch(`${OLLAMA_BASE_URL.replace(/\/$/, '')}/api/tags`); return { configured: response.ok, models: response.ok ? await response.json() : [] }; }
  catch { return { configured: false, models: [] }; }
}

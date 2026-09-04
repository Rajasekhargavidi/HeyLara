# LaraVisionX JARVIS — Real LLM + Real Knowledge

A private multi-agent AI operating assistant for LaraVisionX. This update
moves JARVIS off the tiny local model onto a free, fast, capable cloud LLM
(Groq), fixes a real voice-output bug, and replaces the fictional demo
knowledge document with real content pulled from laravisionx.com.

Repo: https://github.com/Rajasekhargavidi/HeyLara

## Setting up on a new/second machine

Only the *code* is in this repo. Two things are deliberately **not**
committed (see `.gitignore`) because they're per-machine local state, not
shared config:

- **`.env`** — contains real secrets (API keys, tokens). Copy
  `.env.example` to `.env` on each machine and fill in values there. If
  you want the *same* Groq/LinkedIn credentials on a second machine,
  copy your own `.env` file over some other secure channel (not git) —
  never commit it.
- **`jarvis.db`** — the local SQLite database (users, drafts, knowledge
  chunks, everything). Each machine starts with its own fresh database
  (auto-created and seeded with demo data on first run) unless you copy
  the `jarvis.db` file over yourself. There's no automatic sync between
  machines — if you need the same data everywhere, either copy this file
  around manually or point every machine's `DATABASE_URL` at one shared
  Postgres instance (see `docker-compose.yml`) instead of local SQLite.

Steps on a new machine:

```bash
git clone https://github.com/Rajasekhargavidi/HeyLara.git jarvis
cd jarvis
cp .env.example .env   # then edit .env with your real keys
pip install -r apps/api/requirements.txt
pip install -r tests/requirements.txt   # optional, only for running tests
uvicorn apps.api.main:app --port 8000
```

Also needed locally for the default `LLM_PROVIDER=ollama` fallback and for
embeddings (used regardless of which chat LLM you pick):
```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```
(Skip pulling the chat model entirely if you set `LLM_PROVIDER=groq` in
`.env` — embeddings still need Ollama either way.)

## Voice: wake-word session mode

Saying "Hey Lara" once now starts a **session**, not a one-shot command:

- After the greeting, JARVIS keeps listening continuously — no need to say
  "Hey Lara" before every question
- **Barge-in**: if you start talking while JARVIS is still speaking, it
  stops mid-sentence and handles your new question immediately instead of
  missing it (verified live via a simulated recognizer event while a
  reply was speaking)
- Saying "Hey Lara" again mid-session is treated as a check-in ("Still
  here, Boss") rather than sent to the backend as a real question
- After **3 minutes of silence**, the session ends automatically — JARVIS
  announces it's going to sleep and requires the wake phrase again to
  resume
- Verified live end-to-end: entering a session, asking a follow-up with no
  wake word, and the sleep transition all behave correctly in a simulated
  test (this sandbox has no real microphone, so the underlying speech
  *recognition accuracy* still needs verification on a real machine —
  the state machine and control flow are what's been proven)

## What changed

- **LLM provider abstraction** (`packages/config/llm_provider.py`): added
  `GroqProvider` alongside the existing `OllamaProvider`, selected via
  `LLM_PROVIDER` in `.env` (`ollama` = fully local/free, `groq` = free-tier
  cloud API). Embeddings always stay on Ollama regardless of this setting
  — switching embedding models would silently break similarity search
  against everything already ingested into the knowledge base.
- **Currently running on Groq** (`openai/gpt-oss-20b`, free tier, no card
  required): responses that took 5-90 seconds on the local 3B model now
  take under 2 seconds, and answer quality is noticeably better — verified
  live with a casual greeting, a tool-calling request (`list_pending_approvals`,
  <1s), and a grounded RAG answer (<2s)
- Fixed two real bugs surfaced by switching providers:
  1. Groq's Cloudflare front-end was blocking Python's default `urllib`
     User-Agent as a bot signature (HTTP 1010) — fixed by sending a
     normal-looking User-Agent header
  2. The originally-requested model (`llama-3.3-70b-versatile`) no longer
     exists on this key's tier — Groq's catalog moved on; switched to
     `openai/gpt-oss-20b`, which is fast, supports tool-calling, and is on
     the free tier
- **Real company knowledge**: fetched actual content from laravisionx.com
  (home + about pages) and ingested it as a new knowledge document
  alongside (not replacing) the original fictional DEMO document — verified
  live that JARVIS now answers company questions ("what services do we
  offer, how many projects completed") citing the real ingested content
  (352 projects, the real service list) rather than the demo placeholder
- **Voice output bug fixed**: long spoken replies were getting cut off
  mid-sentence — this is a documented Chrome/Edge bug where a single
  `SpeechSynthesisUtterance` over ~15 seconds silently stops. Fixed by (1)
  splitting speech into sentence-sized chunks spoken as a queue instead of
  one long utterance, and (2) a periodic pause/resume "keep-alive" while
  anything is queued, per the standard documented workaround
- **Voice selection**: automatically prefers a natural-sounding Indian
  English voice (e.g. Edge's "Neerja" neural voice) when available, with
  graceful fallback through en-IN → any English voice → browser default
- **Friendlier persona + "hold on" filler**: the orchestrator's system
  prompt now explicitly asks JARVIS to talk like a warm, casual friend
  rather than a formal report generator (never affecting the underlying
  accuracy rules); if a request takes over 3.5 seconds, JARVIS now says
  something like "Give me a few seconds, I'm gathering that for you"
  instead of leaving silence
- **Full HUD-style visual redesign**: the orb now sits inside a rotating
  dual-ring targeting reticle with orbiting markers, HUD telemetry chips
  (MODE/AGENTS/SIGNAL), corner-bracket framing, a subtle animated scan-line
  sweep, and a faint grid-line background — across every dashboard tab
- **One real (smarter-model) regression found and fixed in the test
  suite, not the app**: a test used the vague prompt "create a campaign
  about anything," which the Ollama model blindly turned into a tool call
  but the smarter Groq model correctly recognized as ambiguous and asked
  a clarifying question instead — arguably better behavior. Fixed the
  test to use an unambiguous topic instead of weakening the assertion

## Try it

1. Sign in as `marketing@laravisionx.com` (or any role)
2. Ask "What services does LaraVisionX offer, and how many projects have
   you completed?" — grounded, real answer in ~2 seconds
3. Enable "🔊 Voice replies" and ask a longer question — the full spoken
   answer now completes without cutting off
4. Notice response latency generally — should feel closer to instant now

## Switching back to fully local (zero-cost, offline)

Set `LLM_PROVIDER=ollama` in `.env` and restart — nothing else changes,
same interface, same agents, same knowledge base.

## Still outstanding

- LinkedIn: blocked on LinkedIn's Marketing Developer Platform partner
  application (submitted, pending LinkedIn's review timeline)
- Instagram/Facebook: paused mid-setup (Meta app + product configuration)
- Real employee list: still using 2 demo employees — give me real
  names + WhatsApp numbers/Teams IDs to replace them
- Voice mic permission: still needs on-device verification (Edge site
  permissions / possible corporate policy block) — the app-side error
  handling is now much clearer if it fails again

## Project structure

```
jarvis/
  apps/
    web/            # HUD-styled dashboard shell (9 tabs) + voice (STT/TTS/wake-word)
    api/             # FastAPI app, auth, db, ORM models, seed data, OAuth, webhooks
  agents/            # orchestrator + one module per specialist agent
  tools/
    registry/        # allow-listed Tool Registry + DB-backed audit log
    mock/            # zero-cost demo providers
    social/          # SocialProvider interface + real LinkedIn/Meta/X adapters
    employee/        # EmployeeChannel interface + real Teams/WhatsApp adapters
    knowledge/       # local vector-store adapter (cosine similarity)
    research/        # text extractors, chunker, web search
  packages/
    schemas/         # shared Pydantic models
    config/          # settings + LLMProvider (Ollama + Groq adapters)
  tests/
    unit/            # fast, no server/LLM (role-permission logic)
    e2e/             # Playwright, drives the real dashboard + API
  docker-compose.yml
  pytest.ini
  .env / .env.example
```

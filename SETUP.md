# Setting up Laraon on a new machine

Two ways to run this. **Use Option A** unless you already know Docker
works on your machine — see why below.

## Option A: One script, no Docker (recommended)

Works on any Windows machine, including corporate-managed laptops where
Docker Desktop is often blocked. Verified working end-to-end.

**One-time prerequisites** (normal installers, not affected by the policy
that blocks Docker below):
- [Python 3.11+](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/download)

**Then:**

```powershell
git clone https://github.com/Rajasekhargavidi/HeyLara.git jarvis
cd jarvis
.\setup.ps1
```

That's it. `setup.ps1` handles everything else:
- Creates a Python virtual environment (`.venv`)
- Installs all dependencies
- Creates `.env` from `.env.example` if you don't already have one
- Pulls the two required Ollama models (skips instantly if already pulled)
- Starts the server at **http://localhost:8000**

Safe to re-run any time — every step is a no-op if already done. Re-run it
after pulling new code to pick up any new dependencies.

**Sign in** with a demo account (see `.env.example` / dashboard login
screen for the list) or your own if you've changed them.

**To add real API keys later** (Groq for a much faster/smarter LLM,
LinkedIn/Meta for real social posting, etc.): open the `.env` file that
was created and fill in the relevant values, then restart
(`.\setup.ps1` again, or just re-run the last `uvicorn` command it printed).

## Option B: Docker Compose (recommended for multiple machines)

On each machine, install [Docker Desktop](https://www.docker.com/products/docker-desktop/), start it, then run:

```powershell
git clone https://github.com/Rajasekhargavidi/HeyLara.git laraon
cd laraon
.\docker-setup.ps1
```

The script builds the API, starts PostgreSQL, Redis, and Ollama, automatically
downloads the Qwen and embedding models, waits for the health endpoint, and
opens Laraon at **http://localhost:8000**. No Python, Ollama, or `.env` file is
needed on the host.

The Compose file uses container-safe defaults even if a host `.env` already
exists. To use optional cloud credentials, export them before starting:

```powershell
$env:GROQ_API_KEY = "your-key"
$env:LLM_PROVIDER = "groq"
.\docker-setup.ps1
```

Useful commands:

```powershell
docker compose logs -f api
docker compose ps
docker compose down
```

**Known issue on Deloitte-managed laptops**: Docker Desktop on Windows
requires WSL2 (or Hyper-V), and this environment's WSL is disabled by
group policy (`ERROR_ACCESS_DISABLED_BY_POLICY`) — a hard IT-enforced
block, not something fixable from inside the app or by Claude. If your
laptop has the same policy, Docker Desktop's engine will never start and
`docker compose up` will hang or fail with a connection error to the
Docker daemon. The compose file's syntax and env-var merging were
validated (`docker compose config`), but the actual container build/run
has **not** been verified end-to-end here for that reason.

If you're on a personal machine or one without that policy, Docker should
work fine and gives you PostgreSQL instead of SQLite by default. Each machine
has its own persistent database and Ollama model volume.

## What does NOT sync between machines

Whichever option you use, two things are intentionally per-machine and
never committed to git (see `.gitignore`):

- **`.env`** — your real secrets. Each machine needs its own, filled in
  from `.env.example`. To use the *same* keys on a second machine, copy
  the file yourself over a secure channel — never via git.
- **`jarvis.db`** (SQLite) — the local database (users, drafts, ingested
  knowledge, everything). Each machine starts fresh with demo data seeded
  automatically. If you want the same data everywhere, either copy
  `jarvis.db` between machines yourself, or point every machine's
  `DATABASE_URL` at one shared Postgres instance instead (Option B's
  `db` service, or any Postgres you run centrally).

## Troubleshooting

- **"Python was not found"** — install Python and make sure "Add to PATH"
  was checked during install, then open a new terminal.
- **"Ollama was not found"** — install Ollama, then open a new terminal.
- **Server starts but chat is slow (20-90s per reply)** — you're on the
  local Ollama model (`LLM_PROVIDER=ollama`, the default). Get a free key
  from https://console.groq.com/keys, add it to `.env` as `GROQ_API_KEY`,
  set `LLM_PROVIDER=groq`, and restart — replies drop to under 2 seconds.
- **Port 8000 already in use** — another Laraon instance (or something
  else) is already running on that port. Stop it, or edit the port in the
  final `uvicorn` line of `setup.ps1`.

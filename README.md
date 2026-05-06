# BlogGit

**Live app:** https://creative-eagerness-production.up.railway.app/

Turn private GitHub work into published technical blog posts — automatically.

BlogGit analyzes a repository, asks structured questions about tone and emphasis, drafts a publication-ready post grounded in actual code and commit history, and publishes it directly to Notion, Medium, or LinkedIn.

**Problem it solves:** Technical work in private client repos stays invisible. BlogGit turns that work into public proof of capability — as live blog posts under your name.

---

## Features

- **Deep repo analysis** — 3-phase pipeline reads README, file tree, actual source files, and commit history
- **Structured intake** — 5-question form with predefined options for audience, tone, emphasis, and exclusions
- **LLM-drafted post** — full markdown output with code snippets pulled from real files
- **Iterative revision** — give feedback, agent revises; full version history per session
- **Multi-platform publish** — Notion (direct API), Medium (formatted export), LinkedIn (social copy)
- **Real-time streaming** — token-level SSE output with tool status updates
- **OAuth auth** — sign in via GitHub; connect Notion and LinkedIn for publishing

---

## Tech Stack

| Layer | Library |
|-------|---------|
| LLM | Anthropic Claude (Sonnet for drafting, Haiku for intake) |
| Agent | LangGraph StateGraph |
| MCP client | langchain-mcp-adapters |
| Observability | LangSmith |
| Backend | FastAPI + sse-starlette |
| Frontend | Streamlit |
| Database | Supabase (PostgreSQL + RLS) |
| Config | pydantic-settings |
| Testing | pytest + pytest-asyncio |

---

## Project Structure

```
app/
  agent/
    graph.py              # LangGraph StateGraph & routing
    nodes.py              # Node functions (repo analyzer, intake, outline, drafting, revision)
    state.py              # TypedDict schema + frozen dataclasses
    _repo_analysis.py     # 3-phase repo analysis pipeline
    intake_questions.py   # Shared intake form specs (frontend + backend)
  api/
    main.py               # FastAPI app setup
    routes/
      chat.py             # POST /chat  (SSE streaming)
      auth.py             # OAuth flows
      publish.py          # Notion / Medium / LinkedIn publish endpoints
      user_auth.py        # User login / signup
  tools/
    github_mcp.py         # GitHub MCP client
    notion_mcp.py         # Notion MCP client
    search_tool.py        # Tavily web search
    image_search.py       # Unsplash image search
    mermaid_render.py     # Mermaid diagram → image
  auth/
    oauth.py              # OAuth authorization flows
    encryption.py         # Fernet token encryption at rest
  db/
    repositories.py       # Repository pattern (Protocol-based)
    models.py             # Frozen dataclass DTOs
  config.py
  logging_config.py
frontend/
  app.py                  # Streamlit chat UI with SSE streaming
  components/
    intake_form.py        # Structured intake form (checkboxes + radio + text)
    connections.py        # OAuth connection status widgets
prompts/
  repo_analyzer.md        # Exploration + synthesis prompts
  intake.md
  outline.md
  drafting.md
  revision.md
  medium.md
  linkedin.md
migrations/               # Supabase SQL migrations
tests/
```

---

## Quickstart

### Prerequisites

- Python 3.12+
- Supabase project (free tier works)
- Anthropic API key

### Local dev

```bash
git clone https://github.com/your-org/blogcopilot
cd blogcopilot

cp .env.example .env
# Fill in required variables (see below)

pip install -r requirements.txt

# Terminal 1 — backend
uvicorn app.api.main:app --reload

# Terminal 2 — frontend
streamlit run frontend/app.py
```

### Docker Compose

```bash
docker-compose up
```

- API: `http://localhost:8000`
- Frontend: `http://localhost:8501`
- Hot-reload enabled for both services

---

## Environment Variables

### Required

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API access |
| `ANTHROPIC_MODEL` | Drafting model (e.g. `claude-sonnet-4-6`) |
| `ANTHROPIC_INTAKE_MODEL` | Intake model (e.g. `claude-haiku-4-5-20251001`) |
| `LANGSMITH_API_KEY` | LangSmith tracing |
| `LANGSMITH_PROJECT` | LangSmith project name |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase backend key |
| `BLOG_COPILOT_KEK` | Fernet key for token encryption at rest |
| `APP_SECRET_KEY` | Session signing key |
| `APP_BASE_URL` | Backend URL (e.g. `http://localhost:8000`) |
| `FRONTEND_URL` | Frontend URL (e.g. `http://localhost:8501`) |
| `GITHUB_CLIENT_ID` | GitHub OAuth app ID |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth app secret |
| `GITHUB_OAUTH_REDIRECT_URI` | GitHub OAuth callback URL |
| `NOTION_CLIENT_ID` | Notion OAuth app ID |
| `NOTION_CLIENT_SECRET` | Notion OAuth app secret |
| `NOTION_OAUTH_REDIRECT_URI` | Notion OAuth callback URL |
| `LINKEDIN_CLIENT_ID` | LinkedIn OAuth app ID |
| `LINKEDIN_CLIENT_SECRET` | LinkedIn OAuth app secret |
| `LINKEDIN_OAUTH_REDIRECT_URI` | LinkedIn OAuth callback URL |

Generate secret keys:
```bash
# BLOG_COPILOT_KEK
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# APP_SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"
```

### Optional

| Variable | Purpose |
|----------|---------|
| `TAVILY_API_KEY` | Web search during drafting |
| `UNSPLASH_ACCESS_KEY` | Image search during drafting |
| `DEBUG` | `true` for human-readable logs (default: JSON) |

---

## Commands

```bash
# Tests
pytest tests/ -v
pytest tests/ -x                            # Stop on first failure
pytest --cov=app --cov-report=term-missing  # Coverage (target: 80%+)

# Linting & formatting
ruff check .
black .
isort .
mypy .
```

---

## Architecture

### Agent phases

```
repo  →  intake  →  outline  →  draft  →  revise*  →  done
```

Each phase is a LangGraph node. Routing functions handle phase transitions based on state.

### Repo analysis (3 phases)

1. **Baseline fetch** — parallel: README, file tree (up to 2000 entries), 20 commits, repo metadata
2. **LLM-guided exploration** — Claude selects up to 5 files and 3 search queries based on user intent
3. **Synthesis** — produces `RepoSummary` with language, modules, architecture notes, code insights

### Intake form

Questions use predefined options (checkboxes for multi-select, radio for single-select) plus a free-text field per question. All 5 answers sent at once as a batch string (`[intake_form_v1]` format); the intake node detects this and jumps directly to outline phase.

### Publishing

- **Notion** — creates a page via Notion API; returns page URL
- **Medium** — converts Mermaid diagrams to images, returns formatted markdown for copy-paste
- **LinkedIn** — generates a social post + outreach DM via LLM

### Security

- OAuth tokens encrypted at rest with Fernet (KEK from env)
- RLS enabled on all Supabase tables
- Rate limiting on `/chat` endpoint (slowapi)
- No secrets in source; all config via pydantic-settings

---

## Design Decisions

**Immutability** — all state objects use `@dataclass(frozen=True)`; nodes return new dicts, never mutate in place.

**Prompts as files** — all system prompts are `.md` files in `prompts/`, loaded at runtime. Never hardcoded strings.

**Repository pattern** — database layer uses `typing.Protocol`; tests inject fake implementations without patching globals.

**Two LLMs** — exploration (Phase 2) and intake use Claude Haiku (fast, cheap). Outline, drafting, revision use Claude Sonnet (quality).

**In-memory sessions** — `_sessions` dict, process-scoped. Simpler for early prod; trade-off is sessions lost on restart.

**SSE streaming** — `/chat` streams tokens and tool events; no polling. Frontend consumes via `requests.get(..., stream=True)`.

---

## Deployment

Configured for Railway (see `railway.toml`). Two services from this mono-repo:

- **API service** → `Dockerfile` → `uvicorn app.api.main:app`
- **Frontend service** → `Dockerfile.frontend` → `streamlit run frontend/app.py`

Set all env vars in the Railway dashboard. Health check: `GET /health`.

---

## Future Work

**Persistence & multi-session**
- Replace in-memory session store with LangGraph checkpointer (Supabase-backed)
- Session history browser — resume past drafts

**Deeper repo analysis**
- Support private repos via user-supplied GitHub token
- Diff-based analysis — generate posts about a specific PR or release, not just the whole repo
- Multi-repo comparison posts ("How we migrated from X to Y")

**Richer drafting**
- Auto-embed real code snippets with syntax-highlighted fenced blocks linked to source lines
- Pull request timeline as narrative arc
- Automatic diagram generation (architecture, data flow) via Mermaid from code analysis

**Publishing**
- Direct Medium API publish (currently export only — Medium requires partner program access)
- Dev.to and Hashnode as additional targets
- Scheduled publish — draft now, publish at a specified time

**Quality & evaluation**
- LangSmith evals for draft quality (coherence, technical accuracy, tone match)
- A/B prompt testing across drafting models
- Automated readability scoring (Flesch-Kincaid, SMOG)

**Auth & multi-tenancy**
- Team workspaces — share drafts and revision history across a team
- Google OAuth as alternative sign-in
- Per-user rate limit tiers

**Observability**
- Cost dashboard — per-session token spend breakdown
- Draft quality trends over time

---

## Citations

**Frameworks & libraries**

- [LangGraph](https://github.com/langchain-ai/langgraph) — agent orchestration and StateGraph
- [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters) — MCP tool integration for LangGraph
- [FastAPI](https://fastapi.tiangolo.com/) — backend API framework
- [sse-starlette](https://github.com/sysid/sse-starlette) — Server-Sent Events for FastAPI
- [Streamlit](https://streamlit.io/) — frontend UI framework
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — environment-based config
- [Supabase](https://supabase.com/) — PostgreSQL database with Row Level Security
- [LangSmith](https://smith.langchain.com/) — LLM observability and tracing
- [slowapi](https://github.com/laurentS/slowapi) — rate limiting for FastAPI

**AI models**

- [Claude Sonnet 4.6](https://www.anthropic.com/claude) (Anthropic) — outline, drafting, revision
- [Claude Haiku 4.5](https://www.anthropic.com/claude) (Anthropic) — repo exploration, intake

**External APIs**

- [GitHub REST API](https://docs.github.com/en/rest) — repository data and code search
- [Notion API](https://developers.notion.com/) — page creation and publishing
- [LinkedIn API](https://developer.linkedin.com/) — post generation and OAuth
- [Tavily Search API](https://tavily.com/) — web search during drafting (optional)
- [Unsplash API](https://unsplash.com/developers) — image search during drafting (optional)

**Deployment**

- [Railway](https://railway.app/) — container hosting and CI/CD
- [Mermaid](https://mermaid.js.org/) — diagram rendering in blog posts

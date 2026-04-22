# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Blog Copilot** is a conversational AI assistant that helps write and publish technical blog posts from GitHub projects. The user provides a repository, answers structured questions about tone and emphasis, and the agent drafts a publication-ready blog post grounded in actual code and commit history. The final draft is pushed directly to Notion.

**Problem it solves:** Technical work done in private client repos stays invisible. Blog Copilot turns that work into public proof of capability — as live blog posts under the user's name.


## Critical Rules

### 1. Code Organization

- Many small files over few large files
- High cohesion, low coupling
- 200-400 lines typical, 800 max per file
- Organize by feature/domain, not by type

### 2. Code Style

- No emojis in code, comments, or documentation
- Immutability always — use `@dataclass(frozen=True)` or `NamedTuple`, never mutate in place
- No `print()` in production code — use `logging`
- Catch specific exceptions, always chain with `raise ... from e`
- Validate all inputs with Pydantic at system boundaries

### 3. Testing

- TDD: write tests first (RED → GREEN → REFACTOR)
- 80% minimum coverage
- Unit tests for all functions and utilities
- Integration tests for all API endpoints
- E2E tests for critical user flows

### 4. Security

- No hardcoded secrets — environment variables only
- Parameterized queries only — never f-strings in SQL
- Validate all user inputs at system boundaries
- No `eval()`, `exec()`, or `shell=True` on user-controlled input
- CSRF protection enabled on all state-changing endpoints


## Tech Stack

| Layer | Library | Notes |
|-------|---------|-------|
| LLM | `anthropic` (Claude Sonnet) | Via Anthropic SDK directly — no proxy |
| Agent framework | `langgraph` | StateGraph with typed nodes |
| MCP client | `langchain-mcp-adapters` | Bridges MCP tools into LangGraph tool nodes |
| Observability | `langsmith` | Trace every agent run — verify traces before moving forward |
| Frontend | `streamlit` | Shows full conversation loop; v1 only |
| Backend | `fastapi` | Thin API layer between Streamlit and agent, `/chat` endpoint |
| Config | `pydantic-settings` + `python-dotenv` | All config via env vars |
| Testing | `pytest` + LangSmith evals | pytest for unit/integration, evals for agent output quality |

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run backend
uvicorn app.api.main:app --reload

# Run frontend
streamlit run frontend/app.py

# Tests
pytest tests/ -v
pytest tests/ -x                           # Stop on first failure
pytest tests/ -k "test_name"               # Run a single test
pytest --cov=app --cov-report=term-missing # Coverage (target: 80%+)

# Linting & formatting
ruff check .
black .
isort .
mypy .
```

## Project Structure

```
app/
  agent/
    graph.py      # LangGraph StateGraph definition
    nodes.py      # All node functions
    state.py      # State schema (TypedDict)
    prompts.py    # All prompt templates
  tools/
    github_mcp.py # GitHub MCP client setup
    notion_mcp.py # Notion MCP client setup
  api/
    main.py       # FastAPI app, /chat endpoint
  config.py       # pydantic-settings config
frontend/
  app.py          # Streamlit chat UI
prompts/
  intake.md       # Intake agent system prompt
  drafting.md     # Drafting agent system prompt
  revision.md     # Revision handling prompt
tests/
  test_nodes.py
  test_graph.py
```


## Key Design Decisions

- **Research before Implementing Designs** - Always research new technologies, available packages before implementing new features. Use Context7 MCP for browsing documentations.
- **Prompts as files** — all system prompts are `.md` files in `prompts/`, loaded via `Path.read_text()`, never hardcoded strings
- **MCP via langchain-mcp-adapters** — GitHub and Notion are MCP servers; tool nodes wrap them into LangGraph

## Claude Code Setup

### Agents

Invoke these by asking Claude Code to "use the X agent" or they activate automatically based on context:

| Agent | When to use |
|-------|-------------|
| `planner` | Before implementing any non-trivial feature — generates phased implementation plan with file paths, risks, testing strategy. Runs research step (PyPI/GitHub search) before planning. |
| `tdd-guide` | When writing new features or fixing bugs — enforces RED→GREEN→REFACTOR with pytest. Provides fixture patterns, parametrize, mock examples. |
| `code-reviewer` | After writing or modifying any code — checks security, code quality, Python backend patterns, immutability. Produces severity-rated findings (CRITICAL/HIGH/MEDIUM/LOW). |
| `python-reviewer` | For Python-specific review — PEP 8, type hints, Pythonic idioms, framework-specific checks (FastAPI, Django). Runs ruff/mypy/bandit automatically. |
| `security-reviewer` | After writing auth, API endpoints, user input handling, or DB queries — checks OWASP Top 10, runs bandit/pip-audit, flags injection and secrets. |

### Skills

| Skill | How to invoke |
|-------|--------------|
| `python-patterns` | `/python-patterns` — reference for Pythonic idioms, type hints, dataclasses, generators, concurrency, decorators, and anti-patterns. Use when unsure of the idiomatic Python approach. |

### Rules (always active)

Rules apply automatically to all Claude Code sessions in this repo:

| Rule | What it enforces |
|------|-----------------|
| `development-workflow` | Research → Plan → TDD → Review → Commit pipeline. Research on PyPI/GitHub is mandatory before new implementation. |
| `coding-style` | Immutability, KISS/DRY/YAGNI, snake_case naming, explicit error handling, 800-line file limit. |
| `code-review` | Review checklist, severity levels, mandatory security triggers. |
| `testing` | 80% coverage minimum, TDD workflow, AAA test structure, pytest conventions. |
| `security` | Pre-commit security checklist, secret management, response protocol for critical findings. |
| `git-workflow` | Conventional commits, PR process, `git diff [base]...HEAD` for full PR context. After sprint end push modifications to the current working branch always|
| `patterns` | Repository pattern via Protocol, frozen dataclass API responses, dependency injection. |
| `python/coding-style` | Applies to `*.py` files — PEP 8, black/isort/ruff, frozen dataclasses, type annotations. |
| `python/patterns` | Applies to `*.py` files — Protocol duck typing, dataclass DTOs, context managers, generators. |

## Conventions

- **Immutability:** use `@dataclass(frozen=True)` and `NamedTuple` — never mutate state objects in place; return new state from node functions
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants
- **Error handling:** catch specific exceptions, chain with `raise ... from e`, never bare `except:`
- **Type hints:** all public functions must have full type annotations; `TypedDict` for LangGraph state
- **Commits:** conventional commits format (`feat:`, `fix:`, `refactor:`, `test:`, etc.)

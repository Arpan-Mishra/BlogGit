"""
FastAPI application entry point.

Usage:
    uvicorn app.api.main:app --reload
"""

# load_dotenv must run before any library that reads env vars at import time
# (pydantic-settings populates the Settings object but does NOT write to
# os.environ, so LangSmith's SDK — which reads os.environ directly — would
# never see LANGCHAIN_TRACING_V2 / LANGSMITH_API_KEY without this call).
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.limiter import limiter
from app.api.routes import auth, chat, publish
from app.config import get_settings
from app.logging_config import configure_logging

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_settings = get_settings()
configure_logging(debug=_settings.debug)

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="BlogGit API",
    description="AI assistant that converts GitHub repos into published blog posts.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(publish.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

"""
FastAPI application entry point.

Usage:
    uvicorn app.api.main:app --reload
"""

from fastapi import FastAPI

from app.api.routes import auth, chat

app = FastAPI(
    title="Blog Copilot API",
    description="AI assistant that converts GitHub repos into published blog posts.",
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

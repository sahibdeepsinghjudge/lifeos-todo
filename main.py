"""LifeOS Todo — FastAPI Application Entry Point."""

import subprocess
import sys
import os
import time

# Set global timezone to IST
os.environ["TZ"] = "Asia/Kolkata"
time.tzset()
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi import status

from core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run Alembic migrations on startup in dev mode."""
    if settings.DEV_MODE:
        try:
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                check=True,
                capture_output=True,
                text=True,
            )
            print("✅ Alembic migrations applied successfully")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Alembic migration failed: {e.stderr}")
        except FileNotFoundError:
            print("⚠️  Alembic not found — skipping auto-migration")
    yield


app = FastAPI(
    title="LifeOS Todo",
    description="A production-grade todo app with AI agent, tags, recurrence, and subtasks.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handler for consistent error shapes
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return consistent JSON error shape."""
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Flatten FastAPI validation errors into a readable string."""
    errors = exc.errors()
    messages = []
    for error in errors:
        loc = error.get("loc", ["Unknown"])[-1]
        msg = error.get("msg", "invalid")
        messages.append(f"{loc} ({msg})")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Invalid input: " + ", ".join(messages)},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
from apps.auth.router import router as auth_router  # noqa: E402
from apps.tags.router import router as tags_router  # noqa: E402
from apps.todo.router import router as todo_router  # noqa: E402
from agent.router import router as agent_router  # noqa: E402

app.include_router(auth_router)
app.include_router(tags_router)
app.include_router(todo_router)
app.include_router(agent_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "app": "Phagan AI"}

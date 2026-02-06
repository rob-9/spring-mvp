"""
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from backend.storage.database import init_db, close_db
from backend.api.routes import spans


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # startup: initialize database
    await init_db()
    print("✓ database initialized")

    yield

    # shutdown: close database connections
    await close_db()
    print("✓ database connections closed")


app = FastAPI(
    title="Spring Agent Intelligence Platform",
    description="Observability for multi-agent AI systems",
    version="0.1.0",
    lifespan=lifespan
)

# cors for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# include routers
app.include_router(spans.router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "spring-mvp"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)

"""
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from backend.storage.database import init_db, close_db
from backend.api.routes import spans, traces, analytics


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="Spring Agent Intelligence Platform",
    description="Cost observability for multi-agent AI systems. "
    "Shows which agent is breaking your workflow, how much money it's wasting, "
    "and which downstream agents are affected.",
    version="0.1.0",
    lifespan=lifespan,
)

# cors for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# include routers
app.include_router(spans.router)
app.include_router(traces.router)
app.include_router(analytics.router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "spring-mvp"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)

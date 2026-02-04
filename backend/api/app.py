"""
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Spring Agent Intelligence Platform",
    description="Observability for multi-agent AI systems",
    version="0.1.0"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# TODO: Add routes
# from .routes import spans, traces, analysis
# app.include_router(spans.router, prefix="/api/spans")
# app.include_router(traces.router, prefix="/api/traces")
# app.include_router(analysis.router, prefix="/api/analysis")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

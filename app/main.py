"""FastAPI application — the HTTP layer."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.agent import run_agent
from app.logging_config import configure_logging
from app.models import QueryRequest, VisualizationResponse

# Configure structlog before anything logs, so every record is rendered/gated
# consistently for the lifetime of the process.
configure_logging()

app = FastAPI(
    title="ClinicalTrials.gov Query-to-Visualization Agent",
    version="0.1.0",
    description="NL query → structured visualization spec backed by live ClinicalTrials.gov data.",
)

# CORS headers let a browser-based frontend call this API directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# Serve the frontend and example JSON files as static assets.
# Paths are relative to the project root (where uvicorn is launched from).
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/examples-data", StaticFiles(directory="examples"), name="examples-data")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/static/index.html")


# `def` (not `async def`) because run_agent uses the sync HTTP and OpenAI clients.
# FastAPI automatically runs sync endpoints in a threadpool, so the event loop stays unblocked.
@app.post("/visualize", response_model=VisualizationResponse)
def visualize(request: QueryRequest) -> VisualizationResponse:
    """
    Accept a natural-language query and optional structured filters.
    Returns a structured visualization specification populated with real trial data.
    """
    try:
        return run_agent(request)
    except ValueError as exc:
        # ValueError is raised by the agent for recoverable issues (e.g. no results, bad input).
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # Catch-all for unexpected errors (API timeouts, OpenAI failures, etc.).
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

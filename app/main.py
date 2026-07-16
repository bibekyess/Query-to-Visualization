"""FastAPI application — the HTTP layer."""
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent import run_agent
from app.chat import run_chat
from app.logging_config import configure_logging
from app.models import ChatRequest, QueryRequest, VisualizationResponse

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
    # The chatbot is the primary experience; the classic viz UI stays at /static/index.html.
    return RedirectResponse(url="/static/chat.html")


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


@app.post("/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    """
    Stream an agentic chat answer as Server-Sent Events.

    Each SSE `data:` line is a JSON event: token | tool_start | sources |
    visualization | done | error (see app.chat.agent for the event shapes).
    """
    history = [m.model_dump() for m in request.history]

    def event_stream():
        try:
            for event in run_chat(request.message, history):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # surface as a stream event, not a broken connection
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    # Disable proxy buffering so tokens flush as they are produced.
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

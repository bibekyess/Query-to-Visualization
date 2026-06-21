from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.models import QueryRequest, VisualizationResponse
from app.agent import run_agent

app = FastAPI(
    title="ClinicalTrials.gov Query-to-Visualization Agent",
    version="0.1.0",
    description="NL query → structured visualization spec backed by live ClinicalTrials.gov data.",
)

# CORS headers let a browser-based frontend call this API directly (e.g. from localhost:3000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# `def` (not `async def`) because run_agent calls sync httpx and the sync OpenAI client.
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

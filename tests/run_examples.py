"""
Run example queries against the running server and save outputs to examples/.

Usage:
    uv run python tests/run_examples.py

The server must already be running:
    uv run python main.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "http://localhost:8000"
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
EXAMPLES_DIR.mkdir(exist_ok=True)

# ── One query per supported visualization type ───────────────────────────────

QUERIES = [
    {
        "name": "01_time_series",
        "description": "Pembrolizumab trials per year since 2015 (time_series)",
        "body": {
            "query": "How has the number of pembrolizumab trials changed per year since 2015?",
            "filters": {
                "drug_name": "pembrolizumab",
                "start_year": 2015,
            },
        },
    },
    {
        "name": "02_bar_chart",
        "description": "Diabetes trial phase distribution (bar_chart)",
        "body": {
            "query": "How are diabetes trials distributed across phases?",
            "filters": {
                "condition": "diabetes",
            },
        },
    },
    {
        "name": "03_geographic",
        "description": "Countries with the most recruiting breast cancer trials (bar_chart by country)",
        "body": {
            "query": "Which countries have the most recruiting breast cancer trials?",
            "filters": {
                "condition": "breast cancer",
                "status": "RECRUITING",
            },
        },
    },
    {
        "name": "04_network_graph",
        "description": "Condition co-occurrence network in lung cancer trials (network_graph)",
        "body": {
            "query": "Show a network of conditions that co-occur in lung cancer trials.",
            "filters": {
                "condition": "lung cancer",
            },
        },
    },
    {
        "name": "05_histogram",
        "description": "Enrollment size distribution for Phase 3 cancer trials (histogram)",
        "body": {
            "query": "What is the distribution of enrollment sizes for Phase 3 cancer trials?",
            "filters": {
                "condition": "cancer",
                "phase": ["PHASE3"],
            },
        },
    },
    {
        "name": "06_sponsor_class",
        "description": "Cardiovascular trials by sponsor type (bar_chart)",
        "body": {
            "query": "How are cardiovascular trials distributed across sponsor types?",
            "filters": {
                "condition": "cardiovascular",
            },
        },
    },
    {
        "name": "07_comparison_grouped_bar",
        "description": "Pembrolizumab vs nivolumab phase distribution (grouped_bar)",
        "body": {
            "query": "Compare the phase distribution of pembrolizumab and nivolumab trials.",
        },
    },
    {
        "name": "08_scatter",
        "description": "Enrollment vs trial duration for Phase 3 cancer trials (scatter)",
        "body": {
            "query": "Plot enrollment against trial duration for Phase 3 cancer trials.",
            "filters": {
                "condition": "cancer",
                "phase": ["PHASE3"],
            },
        },
    },
]

# ─────────────────────────────────────────────────────────────────────────────


def _post(url: str, body: dict, timeout: int = 120) -> dict:
    """HTTP POST using stdlib urllib (no httpx dependency needed)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: int = 5) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_query(index: int, example: dict) -> bool:
    name = example["name"]
    desc = example["description"]
    body = example["body"]
    total = len(QUERIES)

    print(f"\n[{index+1}/{total}] {desc}")
    print(f"      POST {BASE_URL}/visualize")

    try:
        data = _post(f"{BASE_URL}/visualize", body)
    except urllib.error.HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

    # Save request + response together so each file is self-contained
    output = {
        "example": name,
        "description": desc,
        "request": body,
        "response": data,
    }

    out_path = EXAMPLES_DIR / f"{name}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    viz = data.get("visualization") or {}
    meta = data.get("response_metadata", {})
    if not viz:
        # "no data" notice path — no chart, just a message.
        print(f"  OK  notice: {data.get('message')}")
        print(f"     saved -> {out_path.relative_to(Path.cwd())}")
        return True
    print(f"  OK  type={viz.get('type')}  "
          f"data_points={len(viz.get('data') or viz.get('nodes') or [])}  "
          f"fetched={meta.get('fetched_count')}  "
          f"verified={meta.get('count_verified')}")
    print(f"     saved -> {out_path.relative_to(Path.cwd())}")
    return True


def main():
    # Quick health check before running all queries
    try:
        _get(f"{BASE_URL}/health")
    except Exception:
        print(f"ERROR: server not reachable at {BASE_URL}")
        print("Start it with:  uv run python main.py")
        sys.exit(1)

    print(f"Server up at {BASE_URL}")
    print(f"Outputs will be saved to: {EXAMPLES_DIR}")

    passed = 0
    for i, example in enumerate(QUERIES):
        if run_query(i, example):
            passed += 1

    print(f"\n{'-'*50}")
    print(f"Done: {passed}/{len(QUERIES)} queries succeeded.")
    if passed < len(QUERIES):
        sys.exit(1)


if __name__ == "__main__":
    main()

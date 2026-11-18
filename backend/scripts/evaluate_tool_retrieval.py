"""Eval harness for tool retrieval (Phase 1).

Measures Recall@5 / Recall@10 on held-out realistic task phrasings plus
schema tokens per turn before/after retrieval. The phrasings below were
written separately from the retriever's example phrases, so they test
generalisation rather than memorisation.

Usage (from the repo root, using the backend venv):

    .venv/bin/python backend/scripts/evaluate_tool_retrieval.py [--embed]

``--embed`` also tries dense embeddings via Ollama; without it the harness
reports the keyword-only path (the default when nomic-embed-text-v2-moe is
not installed). Exit code is 0 when Recall@5 >= 0.90, else 1.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "projects"))

from projects.agent_tools.tool_retriever import (  # noqa: E402
    ToolRetriever,
    estimate_tokens,
    registered_tool_contracts,
)

# (user phrasing, expected tool) — held out from the retriever's examples.
EVAL_CASES: list[tuple[str, str]] = [
    ("Summarize the news on bbc.com/news today and cite your sources", "search_public_site"),
    ("What does the homepage of example.org say about their product?", "scrape_public_page"),
    ("Open the Wikipedia page for Paris in a browser window and show me what it looks like", "browse_public_page"),
    ("On the page you just opened, click the 'History' link", "browser_action"),
    ("Scroll down to the bottom of that page", "browser_action"),
    ("Read my attached resume and tell me my strongest skills", "read_selected_file"),
    ("Please write the meeting notes to a markdown file", "save_text_artifact"),
    ("Turn this data into a CSV I can download", "save_text_artifact"),
    ("Make a Word document with the quarterly report", "create_office_document"),
    ("I need a slide deck for tomorrow's presentation", "create_office_document"),
    ("Paint me a picture of a cat sitting on a windowsill", "generate_local_image"),
    ("Create an image for the cover of my story", "generate_local_image"),
    ("What is in this repository? List everything", "list_project_files"),
    ("Show me the folder layout of my project", "list_project_files"),
    ("Where in the code do we handle user login?", "search_project"),
    ("Find all the places that call the payment API", "search_project"),
    ("Show me the code in app.py", "read_project_file"),
    ("Read server.py lines 1 to 50", "read_project_file"),
    ("There's a crash when the cart is empty - fix it", "propose_project_edit"),
    ("Change the background colour of the homepage to blue", "propose_project_edit"),
    ("Build me a tic-tac-toe game I can play in the browser", "propose_project_patch"),
    ("Write a new script that renames all the files in a folder", "propose_project_patch"),
    ("Double-check my code is valid and nothing is broken", "validate_project"),
    ("Run the checks on the project and tell me about any errors", "validate_project"),
    ("Research how other sites handle cookie banners, using mozilla.org as a source", "search_public_site"),
    ("Grab the text from https://example.com/about", "scrape_public_page"),
    ("Save my shopping list as a text file", "save_text_artifact"),
    ("Make an Excel sheet listing monthly expenses", "create_office_document"),
    ("I uploaded my electricity bill - how much did I use last month?", "read_selected_file"),
    ("Find the TODO comments scattered through the codebase", "search_project"),
    ("Add a settings page to the app", "propose_project_patch"),
    ("Correct the typo in the welcome message", "propose_project_edit"),
    ("Open python.org and take a look at the download page", "browse_public_page"),
    ("Type 'hello world' into the search field on that site", "browser_action"),
]

RECALL_GATE = 0.90


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate tool retrieval recall and token savings.")
    parser.add_argument("--embed", action="store_true", help="Also try dense embeddings via Ollama.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    args = parser.parse_args()

    retriever = ToolRetriever(dense_enabled=args.embed)
    status = retriever.status()
    contracts = registered_tool_contracts()
    full_specs = [contract.model_spec() for contract in contracts.values()]
    tokens_full = sum(estimate_tokens(json.dumps(spec)) for spec in full_specs)

    recall5 = recall10 = 0
    tokens_after_total = 0
    latencies: list[float] = []
    methods: dict[str, int] = {}
    misses: list[dict[str, object]] = []
    rows = []
    for query, expected in EVAL_CASES:
        result = retriever.retrieve(query, top_k=8)
        latencies.append(result.latency_ms)
        methods[result.method] = methods.get(result.method, 0) + 1
        tokens_after_total += result.tokens_after
        top5 = result.selected_names[:5]
        top10 = result.selected_names[:10]
        hit5 = expected in top5
        hit10 = expected in top10
        recall5 += hit5
        recall10 += hit10
        rank = result.selected_names.index(expected) + 1 if expected in result.selected_names else None
        rows.append({
            "query": query, "expected": expected, "rank": rank,
            "hit@5": hit5, "hit@10": hit10, "method": result.method,
            "selected": result.selected_names,
        })
        if not hit5:
            misses.append({"query": query, "expected": expected, "selected": result.selected_names})

    count = len(EVAL_CASES)
    summary = {
        "cases": count,
        "recall@5": round(recall5 / count, 3),
        "recall@10": round(recall10 / count, 3),
        "schema_tokens_before": tokens_full,
        "schema_tokens_after_mean": round(tokens_after_total / count),
        "schema_token_saving": round(1 - (tokens_after_total / count) / tokens_full, 3),
        "latency_ms_mean": round(sum(latencies) / len(latencies), 2),
        "latency_ms_max": round(max(latencies), 2),
        "methods": methods,
        "dense_available": status["dense_available"],
        "fallback_note": status["fallback_note"],
        "misses@5": misses,
    }
    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2))
    else:
        print(f"Tool retrieval eval: {count} cases, {len(contracts)} tools")
        print(f"  dense embeddings: {'on' if status['dense_available'] else 'OFF — ' + (status['fallback_note'] or '')}")
        print(f"  Recall@5:  {summary['recall@5']:.3f}   Recall@10: {summary['recall@10']:.3f}")
        print(f"  Schema tokens/turn: {tokens_full} before -> ~{summary['schema_tokens_after_mean']} after "
              f"(-{summary['schema_token_saving'] * 100:.0f}%)")
        print(f"  Retrieval latency: mean {summary['latency_ms_mean']} ms, max {summary['latency_ms_max']} ms")
        print(f"  Methods: {methods}")
        for miss in misses:
            print(f"  MISS @5: expected {miss['expected']} for {miss['query']!r} (got {miss['selected']})")
    return 0 if summary["recall@5"] >= RECALL_GATE else 1


if __name__ == "__main__":
    raise SystemExit(main())

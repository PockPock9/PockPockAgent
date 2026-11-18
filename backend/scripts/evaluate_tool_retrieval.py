"""Eval harness for tool retrieval (Phases 1-2).

Measures Recall@5 / Recall@10 plus schema tokens per turn before/after
retrieval, on two sets:

* ``EVAL_CASES`` — 34 synthetic held-out phrasings, written separately
  from the retriever's example phrases, so they test generalisation
  rather than memorisation.
* ``REAL_EVAL_CASES`` — 97 real user phrasings harvested from the
  project's own test runs (scenarios-1000, file-work, skills-mcp
  validation). Every entry traces to a real test/scenario; see
  ``tool_retrieval_real_cases.md`` beside this script for the source of
  each case and the mapping rule for multi-step tasks.

The harness reports the combined set and the real-only set separately:
synthetic evals inflate gains, so the real-only numbers are the honest
ones. Usage (from the repo root, using the backend venv):

    .venv/bin/python backend/scripts/evaluate_tool_retrieval.py [--embed]

``--embed`` also tries dense embeddings via Ollama; without it the harness
reports the keyword-only path (the default when nomic-embed-text-v2-moe is
not installed). Exit code is 0 when combined Recall@5 >= 0.90, else 1.
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

# Real user phrasings harvested from the project's own test runs
# (scenarios-1000/SCENARIOS.md, file-work/REPORT.md, skills-mcp-validation/
# REPORT.md). Each entry is (user phrasing, expected tool, source). Scenario
# inputs are verbatim; where a scenario wraps the task in test instructions
# the inner quoted task text is used. For multi-step tasks the expected tool
# is the primary/outcome tool. Full per-case source table:
# backend/scripts/tool_retrieval_real_cases.md.
REAL_EVAL_CASES: list[tuple[str, str, str]] = [
    ('Plan next week for me: I work night shifts Mon, Wed, Fri 10pm–6am, my toddler is in daycare 8am–4pm Tue and Thu, and I want two gym sessions. Save it as night-shift-week.md.', 'save_text_artifact', 'scenarios-1000#201'),
    ('Plan my study week: I have a maths exam Friday and a history essay due Thursday. I can study 2 hours a day after school. Save it as exam-week.md.', 'save_text_artifact', 'scenarios-1000#202'),
    ('Build a 3-day itinerary for Chicago for two adults arriving Friday afternoon. We like architecture and good food, moderate budget, and want indoor alternatives if it rains. Save it as chicago-trip.md.', 'save_text_artifact', 'scenarios-1000#203'),
    ('Using this monthly income and expense list — take-home $4,800, rent $1,500, groceries $600, car $350, utilities $220, subscriptions $85, fun $300 — make a budget with fixed, variable, and irregular costs and a conservative option. Save it as budget.md.', 'save_text_artifact', 'scenarios-1000#205'),
    ("Plan next week's dinners for a family of four, vegetarian, under $120 for the week. Include a shopping list. Save it as meal-plan.md.", 'save_text_artifact', 'scenarios-1000#209'),
    ("Plan a small balcony vegetable garden: 6 pots, partial sun, I'm a beginner. Tell me what to plant this season and when. Save it as balcony-garden.md.", 'save_text_artifact', 'scenarios-1000#215'),
    ('Turn these meeting notes into a summary with decisions, action items, owners, and due dates, and save it as meeting-summary.md. Notes: We decided to delay launch to Oct 3 (owner: Priya). Sam will fix the login bug by Friday. Budget approval is still open, no owner yet.', 'save_text_artifact', 'scenarios-1000#231'),
    ('Save a plain-text shopping list as shopping.txt: milk, eggs, bread, coffee, spinach, chicken thighs, rice.', 'save_text_artifact', 'scenarios-1000#232'),
    ('Save a CSV file called expenses.csv with these rows: Jan, Groceries, 520; Jan, Rent, 1500; Feb, Groceries, 480; Feb, Rent, 1500.', 'save_text_artifact', 'scenarios-1000#233'),
    ('Save a JSON file called settings.json with theme dark, font size 14, notifications on, and language en.', 'save_text_artifact', 'scenarios-1000#234'),
    ('Create a one-page HTML agenda for our team offsite on Saturday: 9am welcome, 10am workshop, 12pm lunch, 2pm planning, 4pm wrap-up. Save it as offsite-agenda.html.', 'save_text_artifact', 'scenarios-1000#235'),
    ("Save my packing list as 'My Trip Packing List.md' with 8 items for a beach trip.", 'save_text_artifact', 'scenarios-1000#243'),
    ('Compare these three note-taking apps for a 5-person team — price, offline use, and export — in a Markdown table and save it as notes-apps.md. App A: $5/user, offline yes, exports Markdown. App B: free, offline no, exports PDF only. App C: $8/user, offline yes, exports Markdown and PDF.', 'save_text_artifact', 'scenarios-1000#250'),
    ('Write a draft apology email to a customer about a late delivery and save it as apology.md. Then rewrite it to be shorter and warmer, and save the new version as apology-v2.md. Keep both files.', 'save_text_artifact', 'scenarios-1000#259'),
    ("Draft a calm, direct email to my landlord about the heating repair that still isn't fixed after I reported it on Oct 20 and again on Nov 2. Ask for a repair timeline. Save it as a Word document called landlord-email.docx. Do not send it.", 'create_office_document', 'scenarios-1000#236'),
    ('Write a one-page project proposal for a neighbourhood tool library: goal, who it serves, what we need, and first steps. Save it as tool-library-proposal.docx.', 'create_office_document', 'scenarios-1000#237'),
    ('Create an Excel budget called monthly-budget.xlsx from these costs: Rent 1500, Groceries 600, Utilities 220, Transport 180, Fun 300. Include category totals and a grand total using formulas.', 'create_office_document', 'scenarios-1000#238'),
    ('Read these two invoices and create a spreadsheet called invoices.xlsx with vendor, invoice number, date, subtotal, tax, and total, one row per invoice, and mark any uncertain field. Invoice A: Acme Supplies, #1042, Nov 1, subtotal 200, tax 16, total 216. Invoice B: Beta Office, #88, Nov 3, subtotal 150, tax 12, total 162.', 'create_office_document', 'scenarios-1000#239'),
    ("Turn this project brief into a 6-slide presentation called project-update.pptx: title, problem, approach, milestones, risks, next steps. Brief: Our app's login fails for 5% of users after the October update; we will fix the session token handling; milestones are fix by Nov 20, test by Nov 25, release Dec 1; risk is the fix touching auth code.", 'create_office_document', 'scenarios-1000#240'),
    ('Turn this report into a 10-slide presentation for customers called launch-talk.pptx: each slide one takeaway, keep the source for every statistic. Report: Our bakery sold 12,000 loaves in October, up 8% on September; sourdough is 40% of sales; weekend footfall rose 15%.', 'create_office_document', 'scenarios-1000#241'),
    ('From this event schedule — Sat 9am setup, 11am doors, 1pm talks, 5pm close — create a one-page Word summary called event-summary.docx and a spreadsheet called event-schedule.xlsx with the same sessions.', 'create_office_document', 'scenarios-1000#246'),
    ("Draft my resume as a Word document called resume-draft.docx: I'm a junior developer, 2 years at Acme Corp, skills Python and JavaScript, degree in Computer Science 2023. Do not invent jobs or skills I didn't list.", 'create_office_document', 'scenarios-1000#252'),
    ('Create a spreadsheet called home-inventory.xlsx listing: Sofa, Living room, bought 2022, $800; Laptop, Office, bought 2024, $1200; Bike, Garage, bought 2023, $450.', 'create_office_document', 'scenarios-1000#253'),
    ('Create a spreadsheet called workouts.xlsx with my last 5 runs: Nov 3, 3km, 22min; Nov 5, 4km, 29min; Nov 7, 3km, 21min; Nov 10, 5km, 36min; Nov 12, 4km, 28min. Add a total distance row.', 'create_office_document', 'scenarios-1000#254'),
    ('Generate a cheerful birthday-card image of a cat with a party hat and save it for my card.', 'generate_local_image', 'scenarios-1000#247'),
    ('Generate a 1024x1024 image of a mountain lake at sunrise for my desktop wallpaper.', 'generate_local_image', 'scenarios-1000#248'),
    ('In my workspace, write a Python script wordcount.py that reads a text file given on the command line and prints the number of words. Add a check that the file exists.', 'propose_project_patch', 'scenarios-1000#261'),
    ('In my workspace, write a JavaScript file format-date.js with a function that takes a Date and returns it as YYYY-MM-DD.', 'propose_project_patch', 'scenarios-1000#262'),
    ('In my workspace, write a TypeScript file totals.ts that exports a function sumPrices that takes an array of {price: number, qty: number} and returns the total.', 'propose_project_patch', 'scenarios-1000#263'),
    ('In my workspace, build a small Python CLI todo.py with add, list, and done commands that store tasks in a JSON file. Keep it under 150 lines.', 'propose_project_patch', 'scenarios-1000#281'),
    ('In my workspace, write csv2json.py: it reads a CSV file given on the command line, converts it to JSON with numbers as numbers, and writes it to an output file. Handle empty values as null.', 'propose_project_patch', 'scenarios-1000#282'),
    ("In my workspace, build a responsive landing page index.html for a fictional neighbourhood repair shop using only this copy: 'Fix-It Corner — we repair bikes, lamps, and small appliances. Open Tue–Sat, 9am–5pm. Call 555-0100.' Use placeholders for links, no external images.", 'propose_project_patch', 'scenarios-1000#283'),
    ('In my workspace, make a responsive focus timer page timer.html with 25-minute focus and 5-minute break sessions, pause/resume, reset, and a session counter.', 'propose_project_patch', 'scenarios-1000#284'),
    ('In my workspace, write a SQL file top-customers.sql that lists the top 10 customers by total spend in 2026 from a table called orders with columns customer_id, amount, and order_date.', 'propose_project_patch', 'scenarios-1000#299'),
    ('In my workspace, write a Dockerfile for my small Python app: Python 3.12, install requirements.txt, copy app.py, expose port 8000, run with uvicorn.', 'propose_project_patch', 'scenarios-1000#300'),
    ("In my workspace, write a Python script greet.py that prints 'Good morning'.", 'propose_project_patch', 'scenarios-1000#309'),
    ("In my workspace, write two files: a.py that prints 'A' and b.py that prints 'B'.", 'propose_project_patch', 'scenarios-1000#310'),
    ('Build a small web game with scoring, levels, sound, multiplayer, and a leaderboard, and save it in my workspace.', 'propose_project_patch', 'scenarios-1000#322'),
    ("In my workspace, fix the bug in counter.py: the loop counts 1 to 10 but should count 0 to 9. The file is in the workspace — read it first, make the smallest fix, and don't change anything else.", 'propose_project_edit', 'scenarios-1000#271'),
    ("In my workspace, fix greet.js: it crashes when the name argument is missing. Make it print 'Hello, guest' instead, and don't change anything else.", 'propose_project_edit', 'scenarios-1000#272'),
    ('In my workspace, fix broken.py — it has a syntax error on line 1. Find it, fix it, and confirm the file now parses.', 'propose_project_edit', 'scenarios-1000#273'),
    ('In my workspace, fix date-filter.py: records on the end date are excluded but the spec says the end date is inclusive. Fix the comparison and add a comment explaining it.', 'propose_project_edit', 'scenarios-1000#274'),
    ('In my workspace, fix checkout.html: clicking the submit button twice sends the request twice. Prevent the second submit while the first is pending, and make the button recover after success and failure.', 'propose_project_edit', 'scenarios-1000#275'),
    ("In my workspace, add a function to utils.py called is_weekend that takes a date and returns True if it is Saturday or Sunday. Don't change the existing functions.", 'propose_project_edit', 'scenarios-1000#276'),
    ('In my workspace, add validation to tasks.py so a task with an empty title is rejected with a clear error, and a task with a title over 200 characters is rejected too.', 'propose_project_edit', 'scenarios-1000#277'),
    ("In my workspace, the test in test_cart.py fails because cart.py applies the discount twice. Find the root cause, fix it, and confirm the test passes. Don't change the test.", 'propose_project_edit', 'scenarios-1000#294'),
    ('In my workspace, fix cache.py: updating a record leaves its old value visible. Make reads after a mutation return the new value, and keep unrelated cached entries available.', 'propose_project_edit', 'scenarios-1000#295'),
    ('In my workspace, fix parser.py: names with accented letters and emoji are mangled on a parse/export round trip. Preserve them exactly, and keep ASCII cases working.', 'propose_project_edit', 'scenarios-1000#296'),
    ('In my workspace, fix the bug in cart.py where the discount is applied twice, add a regression test in test_cart.py, and write release notes called release-notes.md describing the user-visible change.', 'propose_project_edit', 'scenarios-1000#375'),
    ('Review the change in auth.py in my workspace for correctness, regressions, and maintainability. Report only actionable findings with file and line references. Do not change any files. If you find none, say so and note what you did not check.', 'read_project_file', 'scenarios-1000#297'),
    ('Inspect the sample API in my workspace and write endpoint documentation with methods, parameters, example responses, and error cases. Save it as api-docs.md. Only document routes that are actually in the code.', 'list_project_files', 'scenarios-1000#298'),
    ('In my workspace, write a Python script validate-me.py and validate it.', 'validate_project', 'scenarios-1000#345'),
    ('Research wikipedia.org: what does the page say about the history of the bicycle?', 'search_public_site', 'scenarios-1000#401'),
    ('Research en.wikipedia.org: summarize the history of the bicycle in three bullet points, citing each claim.', 'search_public_site', 'scenarios-1000#404'),
    ('Using developer.mozilla.org, summarize what the Fetch API does and cite the page.', 'search_public_site', 'scenarios-1000#405'),
    ('Research python.org: what is new in the latest Python 3.13 release? Cite each change.', 'search_public_site', 'scenarios-1000#406'),
    ('Research nodejs.org: which Node.js version is the current LTS and when was it released?', 'search_public_site', 'scenarios-1000#407'),
    ('Compare the Python and Node.js download pages on python.org and nodejs.org: what installers does each offer? Cite both.', 'search_public_site', 'scenarios-1000#408'),
    ('Research python.org and docs.python.org: do they agree on the latest Python version? Report any conflict with excerpts and dates.', 'search_public_site', 'scenarios-1000#436'),
    ('Using example.com, tell me in your own words what the Example Domain page is for.', 'search_public_site', 'scenarios-1000#438'),
    ('Research example.com: tell me what the page is for.', 'search_public_site', 'scenarios-1000#439'),
    ('Research three topics and write a combined report called combined-report.md: Python packaging, Docker basics, and Git workflows. Split the research into one subtask per topic, then combine them.', 'search_public_site', 'scenarios-1000#367'),
    ('Research the Python docs site (docs.python.org) for how venv works, write a beginner-friendly explanation, and save it as a Word document called venv-guide.docx.', 'search_public_site', 'scenarios-1000#373'),
    ('Use search_public_site on example.com to tell me what the Example Domain page is for.', 'search_public_site', 'scenarios-1000#387'),
    ('Look up what the Example Domain page is for and tell me.', 'search_public_site', 'scenarios-1000#388'),
    ('Research the Python docs site and save a summary.', 'search_public_site', 'scenarios-1000#303'),
    ('Research the Python docs site (docs.python.org) and summarise how venv works.', 'search_public_site', 'scenarios-1000#346'),
    ('Scrape https://example.org and tell me its first paragraph.', 'scrape_public_page', 'scenarios-1000#402'),
    ('Scrape https://example.com and give me its full text.', 'scrape_public_page', 'scenarios-1000#515'),
    ('Scrape https://example.com and list all the links on the page.', 'scrape_public_page', 'scenarios-1000#516'),
    ('Open http://localhost:8766/api/health in the browser.', 'browse_public_page', 'scenarios-1000#479'),
    ('Open https://example.com in the browser.', 'browse_public_page', 'scenarios-1000#484'),
    ('Open https://example.com in the browser and save a screenshot.', 'browse_public_page', 'scenarios-1000#487'),
    ('Open https://example.com in a visible browser window and leave it open for me.', 'browse_public_page', 'scenarios-1000#512'),
    ('Open https://example.com in the browser (headless) and summarize it.', 'browse_public_page', 'scenarios-1000#513'),
    ('Open https://example.com in the browser and summarize it.', 'browse_public_page', 'scenarios-1000#514'),
    ('Open https://example.com in the browser and summarise what the page says.', 'browse_public_page', 'scenarios-1000#347'),
    ("Open https://example.com in the browser, then click the 'More information' link and tell me where it goes.", 'browser_action', 'scenarios-1000#495'),
    ("Open https://example.com in the browser, then click the 'More information' link.", 'browser_action', 'scenarios-1000#496'),
    ('Open https://en.wikipedia.org/wiki/Bicycle in the browser, scroll down, then scroll back up, and tell me what you saw at each step.', 'browser_action', 'scenarios-1000#497'),
    ("Open https://en.wikipedia.org in the browser, type 'bicycle' into the search box, and tell me what the search shows.", 'browser_action', 'scenarios-1000#498'),
    ("Open https://example.com in the browser, find a language combobox, select 'Français', and tell me what changed.", 'browser_action', 'scenarios-1000#499'),
    ('Open https://example.com in the browser, then navigate to https://example.com/about within the same site.', 'browser_action', 'scenarios-1000#500'),
    ('Summarise the attached file report.txt and save the summary as report-summary.md.', 'read_selected_file', 'scenarios-1000#327'),
    ('Analyse the attached sales.csv (monthly totals and top products), write a short Markdown report called sales-report.md, and turn the same numbers into a 5-slide deck called sales-deck.pptx.', 'read_selected_file', 'scenarios-1000#374'),
    ('Compare these two attached policy drafts, policy-old.txt and policy-new.txt, list the substantive changes with section references, and save the comparison as policy-diff.md. Do not overwrite either original.', 'read_selected_file', 'scenarios-1000#376'),
    ('Review the attached sales spreadsheet sales-data.xlsx for monthly trends, unusual changes, and missing values. Keep the source unchanged and save a summary as sales-review.md plus a cleaned copy as sales-cleaned.xlsx.', 'read_selected_file', 'scenarios-1000#377'),
    ('Using the attached notes.txt, tell me the project name, launch date, and budget.', 'read_selected_file', 'scenarios-1000#476'),
    ('Using the attached data.csv, calculate the average score and list the top scorer.', 'read_selected_file', 'scenarios-1000#477'),
    ('What is the total revenue in the attached sales.csv?', 'read_selected_file', 'file-work/REPORT.md test 01-attachment (paraphrased)'),
    ('How many units of Widget B are in the attached inventory.xlsx, and what is the total stock value?', 'read_selected_file', 'file-work/REPORT.md test 03 (paraphrased)'),
    ('Which region had the highest revenue in the attached Q3 report?', 'read_selected_file', 'file-work/REPORT.md test 05 (paraphrased)'),
    ('When is the beta launch, according to the Goals slide in the attached deck?', 'read_selected_file', 'file-work/REPORT.md test 07 (paraphrased)'),
    ('Who sends the budget, and by when, according to the attached notes?', 'read_selected_file', 'file-work/REPORT.md test 09 (paraphrased)'),
    ('How many new members joined in 2025, according to the attached summary?', 'read_selected_file', 'file-work/REPORT.md test 11 (paraphrased)'),
    ('What is max_runs in the attached config, and is research enabled?', 'read_selected_file', 'file-work/REPORT.md test 13 (paraphrased)'),
    ('save a file', 'save_text_artifact', 'skills-mcp-validation/REPORT.md (verbatim task)'),
]

RECALL_GATE = 0.90


def _evaluate(retriever, cases, contracts, tokens_full):
    """Run one case set; returns (summary, rows)."""
    recall5 = recall10 = 0
    tokens_after_total = 0
    latencies: list[float] = []
    methods: dict[str, int] = {}
    misses: list[dict[str, object]] = []
    rows = []
    for query, expected, _source in cases:
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
    count = len(cases)
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
        "misses@5": misses,
    }
    return summary, rows


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

    synthetic = [(query, expected, "synthetic") for query, expected in EVAL_CASES]
    real = list(REAL_EVAL_CASES)
    combined = synthetic + real
    combined_summary, combined_rows = _evaluate(retriever, combined, contracts, tokens_full)
    real_summary, real_rows = _evaluate(retriever, real, contracts, tokens_full)
    summary = {
        **combined_summary,
        "dense_available": status["dense_available"],
        "fallback_note": status["fallback_note"],
        "synthetic_cases": len(synthetic),
        "real_cases": len(real),
        "real_only": real_summary,
    }
    if args.json:
        print(json.dumps({"summary": summary, "rows": combined_rows, "real_rows": real_rows}, indent=2))
    else:
        print(f"Tool retrieval eval: {len(combined)} cases "
              f"({len(synthetic)} synthetic + {len(real)} real), {len(contracts)} tools")
        print(f"  dense embeddings: {'on' if status['dense_available'] else 'OFF — ' + (status['fallback_note'] or '')}")
        print(f"  Combined  Recall@5:  {combined_summary['recall@5']:.3f}   Recall@10: {combined_summary['recall@10']:.3f}")
        print(f"  Real-only Recall@5:  {real_summary['recall@5']:.3f}   Recall@10: {real_summary['recall@10']:.3f}")
        print(f"  Schema tokens/turn: {tokens_full} before -> ~{combined_summary['schema_tokens_after_mean']} after "
              f"(-{combined_summary['schema_token_saving'] * 100:.0f}% combined; "
              f"-{real_summary['schema_token_saving'] * 100:.0f}% real-only)")
        print(f"  Retrieval latency: mean {combined_summary['latency_ms_mean']} ms, max {combined_summary['latency_ms_max']} ms")
        print(f"  Methods: {combined_summary['methods']}")
        for miss in combined_summary["misses@5"]:
            print(f"  MISS @5: expected {miss['expected']} for {miss['query']!r} (got {miss['selected']})")
    return 0 if combined_summary["recall@5"] >= RECALL_GATE else 1


if __name__ == "__main__":
    raise SystemExit(main())

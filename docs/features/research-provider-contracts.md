# Research source and evidence contracts

## Purpose and scope

`backend/projects/agent_tools/research_contracts.py` defines the version 1 internal types for search results, source identity, retrieved evidence, and provider failures. The local `search_public_site` tool now attaches these normalized source and evidence records to its existing bounded page-crawl response. It remains a named-host crawler, not a general Internet search engine.

## Data flow

The user selects the research provider in **Research settings**. The setting is stored in the local `settings` table as `frog_research_provider`, defaults to `disabled`, and can be reset by selecting Disabled. While disabled, the gateway blocks `search_public_site` and `scrape_public_page` before dispatch, so no website request is made. Enabling **Named public websites** permits fetches only for hosts explicitly named by the user task. The UI says requests leave this PC, general search is not included, and no API credentials are configured. This provider does not accept or store secrets.

`named_host_page_record()` adapts each fetched page shape (`url`, `title`, `text`) into a `SourceRecord` and bounded `SourceEvidence`. The crawler's existing limits remain in force: up to five pages, public-IP-only DNS resolution, same-host redirects/navigation, standard HTTP(S) ports, 15 second request timeout, and 2 MB response cap. Its existing page response remains intact for compatibility; the added `research` result contains provider-neutral deduplicated source records and typed errors, and `evidence` contains bounded excerpts tied to source IDs.

The gateway emits a replayable `research_sources` activity event for each successful site search. It contains the normalized result records, bounded excerpts, query, provider, and typed failures. The conversation timeline renders each source as a safe HTTP(S) link, shows its retrieval time, snippet, and supporting excerpt, and reports source failures.

After a research-tool call, the gateway requires the final model response to match version 1 of the structured `ResearchAnswer` contract in `backend/projects/agent_tools/research_answers.py`. Each factual claim is represented separately as supported or unsupported. Supported claims require a known source ID and a verbatim quote that occurs in that source's retrieved excerpt; unsupported claims cannot carry citations. Conflicts require quotes from at least two distinct sources. The gateway retries invalid responses at most twice, then ends the run as partial without presenting the invalid claims. A valid answer is rendered as Markdown with safe source links, titles, retrieval and publication timestamps, exact supporting passages, conflict summaries, and evidence limitations. Approved completion-check lines are retained in the rendered answer.

This validation verifies citation identity and quote provenance, not semantic entailment: the model still assesses whether a quoted passage actually supports its claim. The output contract requires one factual assertion per claim and marks unverified assertions unsupported, but it cannot independently determine whether arbitrary prose is factual. Publication dates are shown when available; the model is instructed to disclose weak, old, missing, or conflicting evidence rather than treating absence of evidence as confirmation.

## Cited report exports

When a research task requests Markdown, HTML, Word (`.docx`), Excel (`.xlsx`), or PowerPoint (`.pptx`), the gateway creates the report only after the structured answer passes source-ID and exact-quote validation. `backend/projects/agent_tools/research_exports.py` builds each format from those validated claims, citations, source records, excerpts, conflicts, limitations, and retrieval errors; it does not use a model-authored artifact as the validated report. Markdown and HTML links are usable, and Office formats carry clickable source hyperlinks. Reports include source IDs, retrieval times, publication times when available, and bounded source excerpts. HTML escapes page-supplied values, and spreadsheet text is guarded against formula execution.

The generated file is written to the run's task-output directory and emitted as the usual replayable `artifact` event, so the existing task-output UI provides its download link. The gateway checks for the requested extension before it can record success. If validation or report generation fails, it reports an error instead of treating a separate artifact with that extension as a cited research report. The format-specific Office writers are existing local dependencies; no report content is sent to a service.

## Task-scoped research collections

Each source in a persisted `research_sources` event can be explicitly saved to that task's research collection. Saving performs a fresh fetch only after the user selects **Save source snapshot**; ordinary search results and page fetches are not copied into collection storage. The snapshot contains extracted page text, its SHA-256 hash, capture time, and a truncation flag. Each snapshot is limited to 200 KB of UTF-8 text. User notes are limited to 2,000 characters.

Collections are keyed by both the run ID and a hash of the normalized workspace path. The path itself is not added to the collection record. The saved-source URL must match a source from that task's research event, and fetching uses the existing public-IP, same-host redirect, content-type, timeout, and response-size checks. Task and workspace mismatches are rejected.

Refresh is a user-triggered action; there is no polling or background fetch. A refresh compares the new text hash with the latest version, updates the last-checked timestamp, and creates a new snapshot only when the text changes. The UI shows added and removed text and lets the user open retained versions. All versions remain stored until the user deletes the collection; there is no per-source deletion that could remove version history early. Deleting a collection removes its source records, notes, and snapshot rows.

The collection tables live in the run store's local SQLite database. Collection reads, note updates, explicit refreshes, and deletes use the gateway's local-only API and the authenticated loopback run-store boundary. The collection is not shared with other tasks or agents.

Retrieved page text is untrusted tool data. It cannot change the user request, the plan's permission level, or authorize a tool. Allowed hosts come from the original task, and tool permissions and approvals remain enforced by the gateway. Source excerpts are escaped when rendered as Markdown so page-supplied markup is displayed as text.

`SourceRecord` stores version, deterministic source ID, canonical URL, title, bounded snippet, provider ID, retrieval time, and optional publication time. `SourceEvidence` binds a bounded supporting excerpt to a source ID and retrieval time. `ResearchResponse` contains the query, provider, retrieval time, deduplicated records, and typed errors. `ResearchProviderError` uses stable codes for unavailable, rate-limited, invalid-query, unsafe-destination, timeout, oversized-response, unsupported-content, and upstream failures, with bounded retry and HTTP status metadata.

## Identity and deduplication

Canonicalization accepts HTTP/HTTPS without URL credentials, normalizes scheme/host and IDN hostnames, rejects localhost/local names and private/reserved literal IPs, removes fragments, default ports, common tracking parameters, and redundant trailing path slashes, and sorts retained query pairs. It preserves page-specific path and query values. `source_id` is SHA-256 of the canonical URL, so the same URL maps to one stable identity across providers. `deduplicate_sources()` merges duplicate IDs, keeps the first provider as primary, records other providers, prefers a longer snippet, fills missing title/publication metadata, and keeps the latest retrieval time.

The canonicalizer is an identity function, not a complete network security boundary: hostname DNS resolution, redirect checks, and request policy still belong in the fetcher. Any future fetch must use the existing public-IP, redirect, timeout, response-size, content-type, and page-count checks before connecting. Provider messages are bounded and must not contain credentials or prompt text; source page text remains task data and is not copied to prompt-free telemetry.

## Compatibility and verification

The new internal contract version is independent of the existing callable tool and run-event schema versions. The crawler retains its prior response fields and adds `research` and `evidence`. Configuration uses only a provider enum; provider keys and credentials are not accepted. Verify with `python -m unittest projects.agent_tools.test_research projects.agent_tools.test_research_answers projects.agent_tools.test_research_exports projects.run_store.test_research_collections` and compile the gateway, run store, and agent-tools package. The answer-contract tests cover required/unsupported claims, unknown source IDs, exact quote matching, distinct-source conflicts, provenance links/timestamps, and safe rendering of instruction-like page text; collection tests cover task/workspace isolation, snapshot byte limits, change detection, notes, and deletion.

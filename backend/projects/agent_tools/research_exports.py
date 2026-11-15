"""Cited research report renderers and task-scoped artifact writers."""

from __future__ import annotations

from html import escape
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .artifacts import _record_artifact, _safe_filename
from .common import AgentToolContext, AgentToolError
from .research_answers import (
    ResearchAnswer,
    render_research_answer,
    validate_research_answer,
)
from .research_contracts import ResearchProviderError, SourceEvidence, SourceRecord


SUPPORTED_RESEARCH_EXPORTS = {".md", ".html", ".docx", ".xlsx", ".pptx"}
MAX_RESEARCH_EXPORT_CHARS = 500_000
MAX_RESEARCH_EXPORT_BYTES = 5 * 1024 * 1024
_INVALID_XML_CHARACTERS = re.compile(
    r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]"
)


def create_research_export(
    context: AgentToolContext,
    answer: ResearchAnswer,
    source_data: list[dict[str, Any]],
    evidence_data: list[dict[str, Any]],
    filename: str,
    extension: str,
    provider_error_data: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    if not isinstance(extension, str):
        raise AgentToolError("Choose a supported research report format")
    extension = extension.lower()
    if extension not in SUPPORTED_RESEARCH_EXPORTS:
        raise AgentToolError("Research reports support Markdown, HTML, Word, Excel, or PowerPoint formats")
    try:
        validated = validate_research_answer(answer.model_dump_json(), source_data, evidence_data)
        sources = [SourceRecord.model_validate(item) for item in source_data]
        evidence = {item.source_id: item for item in (SourceEvidence.model_validate(item) for item in evidence_data)}
        provider_errors = [
            ResearchProviderError.model_validate(item)
            for item in (provider_error_data or [])
        ]
    except (ValueError, TypeError) as err:
        raise AgentToolError(f"Cannot export an invalid research result: {err}") from err
    if not (validated.claims or validated.conflicts or validated.limitations or provider_errors):
        raise AgentToolError("The research result has no findings, evidence limitations, or retrieval errors to export")
    validated = _sanitize_answer(validated)
    sources = [_sanitize_source(item) for item in sources]
    evidence = {source_id: _sanitize_evidence(item) for source_id, item in evidence.items()}
    provider_errors = [_sanitize_provider_error(item) for item in provider_errors]

    try:
        if extension == ".md":
            content: str | bytes = _render_markdown(validated, sources, evidence, provider_errors)
        elif extension == ".html":
            content = _render_html(validated, sources, evidence, provider_errors)
        elif extension == ".docx":
            content = _render_word(validated, sources, evidence, provider_errors)
        elif extension == ".xlsx":
            content = _render_spreadsheet(validated, sources, evidence, provider_errors)
        else:
            content = _render_presentation(validated, sources, evidence, provider_errors)
    except ImportError as err:
        raise AgentToolError(f"The required {extension[1:].upper()} report writer is unavailable") from err
    except (OSError, ValueError) as err:
        raise AgentToolError(f"Could not build the research report: {err}") from err

    if isinstance(content, str):
        if len(content) > MAX_RESEARCH_EXPORT_CHARS:
            raise AgentToolError("The cited research report exceeds its character limit")
        encoded = content.encode("utf-8")
    else:
        encoded = content
    if len(encoded) > MAX_RESEARCH_EXPORT_BYTES:
        raise AgentToolError("The cited research report exceeds its file-size limit")

    for sequence in range(1, 101):
        suffix = "" if sequence == 1 else f"-{sequence}"
        safe_name = _safe_filename(f"{Path(filename).stem}{suffix}{extension}", extension)
        path = context.output_dir / safe_name
        try:
            with path.open("xb") as output:
                output.write(encoded)
        except FileExistsError:
            continue
        except OSError as err:
            raise AgentToolError(f"Could not save the cited research report: {err}") from err
        kind = {
            ".md": "md",
            ".html": "html",
            ".docx": "word",
            ".xlsx": "spreadsheet",
            ".pptx": "presentation",
        }[extension]
        return _record_artifact(context, path, kind)
    raise AgentToolError("Could not choose an unused filename for the cited research report")


def _safe_export_text(value: str) -> str:
    return _INVALID_XML_CHARACTERS.sub("", value)


def _sanitize_answer(answer: ResearchAnswer) -> ResearchAnswer:
    claims = [
        claim.model_copy(update={
            "text": _safe_export_text(claim.text),
            "citations": [
                citation.model_copy(update={"quote": _safe_export_text(citation.quote)})
                for citation in claim.citations
            ],
        })
        for claim in answer.claims
    ]
    conflicts = [
        conflict.model_copy(update={
            "topic": _safe_export_text(conflict.topic),
            "summary": _safe_export_text(conflict.summary),
            "citations": [
                citation.model_copy(update={"quote": _safe_export_text(citation.quote)})
                for citation in conflict.citations
            ],
        })
        for conflict in answer.conflicts
    ]
    return answer.model_copy(update={
        "claims": claims,
        "conflicts": conflicts,
        "limitations": [_safe_export_text(item) for item in answer.limitations],
        "completion_checks": [_safe_export_text(item) for item in answer.completion_checks],
    })


def _sanitize_source(source: SourceRecord) -> SourceRecord:
    return source.model_copy(update={
        "title": _safe_export_text(source.title),
        "snippet": _safe_export_text(source.snippet),
    })


def _sanitize_evidence(evidence: SourceEvidence) -> SourceEvidence:
    return evidence.model_copy(update={"excerpt": _safe_export_text(evidence.excerpt)})


def _sanitize_provider_error(error: ResearchProviderError) -> ResearchProviderError:
    return error.model_copy(update={"message": _safe_export_text(error.message)})


def _markdown_text(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~])", r"\\\1", " ".join(value.split()))


def _source_title(source: SourceRecord) -> str:
    return " ".join(source.title.split()) or source.canonical_url


def _markdown_source_link(source: SourceRecord) -> str:
    title = _markdown_text(_source_title(source))
    url = quote(source.canonical_url, safe=":/?#[]@!$&'()*+,;=%")
    return f"[{title}](<{url}>)"


def _markdown_quote(value: str) -> str:
    return "\n".join(f"> {_markdown_text(line)}" for line in value.splitlines() or [value])


def _source_excerpt(source_id: str, evidence: dict[str, SourceEvidence]) -> str:
    item = evidence.get(source_id)
    return item.excerpt if item else ""


def _render_markdown(
    answer: ResearchAnswer,
    sources: list[SourceRecord],
    evidence: dict[str, SourceEvidence],
    provider_errors: list[ResearchProviderError],
) -> str:
    source_data = [source.model_dump(mode="json") for source in sources]
    sections = ["# Research Report", render_research_answer(answer, source_data)]
    sections.append("## Sources")
    for source in sources:
        sections.append(
            f"- {_markdown_source_link(source)} - retrieved {source.retrieved_at.isoformat()}"
            + (f"; published {source.published_at.isoformat()}" if source.published_at else "")
            + f"\n  - Source ID: `{source.source_id}`"
            + (f"\n  - Snippet: {_markdown_text(source.snippet)}" if source.snippet else "")
            + (
                f"\n  - Supporting excerpt:\n{_markdown_quote(_source_excerpt(source.source_id, evidence))}"
                if _source_excerpt(source.source_id, evidence)
                else ""
            )
        )
    if provider_errors:
        sections.append("## Retrieval limitations")
        sections.extend(
            f"- **{item.code.replace('_', ' ')}:** {_markdown_text(item.message)}"
            for item in provider_errors
        )
    return "\n\n".join(sections)


def _render_html(
    answer: ResearchAnswer,
    sources: list[SourceRecord],
    evidence: dict[str, SourceEvidence],
    provider_errors: list[ResearchProviderError],
) -> str:
    chunks = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>Research Report</title>",
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}"
        "blockquote{border-left:3px solid #888;margin:1rem 0;padding:.25rem 1rem;color:#444}"
        "small{color:#555}li{margin:.75rem 0}</style></head><body>",
        "<h1>Research Report</h1><h2>Findings</h2>",
    ]
    for claim in answer.claims:
        chunks.append(
            f"<article><p><strong>{escape(claim.status.title())}:</strong> {escape(claim.text)}</p>"
        )
        for citation in claim.citations:
            source = next(item for item in sources if item.source_id == citation.source_id)
            chunks.append(
                f"<p><a href=\"{escape(source.canonical_url, quote=True)}\" rel=\"noopener noreferrer\">"
                f"{escape(_source_title(source))}</a> "
                f"<small>Retrieved {escape(source.retrieved_at.isoformat())}"
                + (f"; published {escape(source.published_at.isoformat())}" if source.published_at else "")
                + f"</small></p><blockquote>{escape(citation.quote)}</blockquote>"
            )
        chunks.append("</article>")
    if answer.conflicts:
        chunks.append("<h2>Conflicting evidence</h2>")
        for conflict in answer.conflicts:
            chunks.append(f"<article><h3>{escape(conflict.topic)}</h3><p>{escape(conflict.summary)}</p>")
            for citation in conflict.citations:
                source = next(item for item in sources if item.source_id == citation.source_id)
                chunks.append(
                    f"<p><a href=\"{escape(source.canonical_url, quote=True)}\" rel=\"noopener noreferrer\">"
                    f"{escape(_source_title(source))}</a> "
                    f"<small>Retrieved {escape(source.retrieved_at.isoformat())}</small></p>"
                    f"<blockquote>{escape(citation.quote)}</blockquote>"
                )
            chunks.append("</article>")
    if answer.limitations:
        chunks.append("<h2>Evidence limitations</h2><ul>")
        chunks.extend(f"<li>{escape(item)}</li>" for item in answer.limitations)
        chunks.append("</ul>")
    if answer.completion_checks:
        chunks.append("<h2>Completion checks</h2><ul>")
        chunks.extend(f"<li>{escape(item)}</li>" for item in answer.completion_checks)
        chunks.append("</ul>")
    chunks.append("<h2>Sources</h2><ol>")
    for source in sources:
        chunks.append(
            f"<li id=\"source-{source.source_id}\"><a href=\"{escape(source.canonical_url, quote=True)}\" "
            f"rel=\"noopener noreferrer\">{escape(_source_title(source))}</a> "
            f"<small>Retrieved {escape(source.retrieved_at.isoformat())}"
            + (f"; published {escape(source.published_at.isoformat())}" if source.published_at else "")
            + f"</small><p>Source ID: <code>{source.source_id}</code></p>"
            + (f"<p>{escape(source.snippet)}</p>" if source.snippet else "")
            + (
                f"<blockquote>{escape(_source_excerpt(source.source_id, evidence))}</blockquote>"
                if _source_excerpt(source.source_id, evidence)
                else ""
            )
            + "</li>"
        )
    chunks.append("</ol>")
    if provider_errors:
        chunks.append("<h2>Retrieval limitations</h2><ul>")
        chunks.extend(
            f"<li><strong>{escape(item.code.replace('_', ' '))}:</strong> {escape(item.message)}</li>"
            for item in provider_errors
        )
        chunks.append("</ul>")
    chunks.append("</body></html>")
    return "\n".join(chunks)


def _render_word(
    answer: ResearchAnswer,
    sources: list[SourceRecord],
    evidence: dict[str, SourceEvidence],
    provider_errors: list[ResearchProviderError],
) -> bytes:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from io import BytesIO

    document = Document()
    document.add_heading("Research Report", level=0)

    def add_link(paragraph, source: SourceRecord) -> None:
        relationship_id = paragraph.part.relate_to(source.canonical_url, RT.HYPERLINK, is_external=True)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), relationship_id)
        run = OxmlElement("w:r")
        properties = OxmlElement("w:rPr")
        color = OxmlElement("w:color")
        color.set(qn("w:val"), "0563C1")
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        properties.append(color)
        properties.append(underline)
        run.append(properties)
        text = OxmlElement("w:t")
        text.text = _source_title(source)
        run.append(text)
        hyperlink.append(run)
        paragraph._p.append(hyperlink)

    def add_citation(citation) -> None:
        source = next(item for item in sources if item.source_id == citation.source_id)
        paragraph = document.add_paragraph()
        add_link(paragraph, source)
        paragraph.add_run(f" - Retrieved {source.retrieved_at.isoformat()}")
        if source.published_at:
            paragraph.add_run(f"; published {source.published_at.isoformat()}")
        document.add_paragraph(citation.quote, style="Quote")

    document.add_heading("Findings", level=1)
    for claim in answer.claims:
        paragraph = document.add_paragraph()
        paragraph.add_run(f"{claim.status.title()}: ").bold = True
        paragraph.add_run(claim.text)
        for citation in claim.citations:
            add_citation(citation)
    if answer.conflicts:
        document.add_heading("Conflicting evidence", level=1)
        for conflict in answer.conflicts:
            document.add_heading(conflict.topic, level=2)
            document.add_paragraph(conflict.summary)
            for citation in conflict.citations:
                add_citation(citation)
    if answer.limitations:
        document.add_heading("Evidence limitations", level=1)
        for item in answer.limitations:
            document.add_paragraph(item, style="List Bullet")
    if answer.completion_checks:
        document.add_heading("Completion checks", level=1)
        for item in answer.completion_checks:
            document.add_paragraph(item, style="List Bullet")
    document.add_heading("Sources", level=1)
    for source in sources:
        paragraph = document.add_paragraph(style="List Number")
        add_link(paragraph, source)
        paragraph.add_run(f" - Retrieved {source.retrieved_at.isoformat()}")
        if source.published_at:
            paragraph.add_run(f"; published {source.published_at.isoformat()}")
        paragraph.add_run(f"\nSource ID: {source.source_id}")
        if source.snippet:
            document.add_paragraph(source.snippet)
        excerpt = _source_excerpt(source.source_id, evidence)
        if excerpt:
            document.add_paragraph(excerpt, style="Quote")
    if provider_errors:
        document.add_heading("Retrieval limitations", level=1)
        for item in provider_errors:
            document.add_paragraph(f"{item.code}: {item.message}", style="List Bullet")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _render_spreadsheet(
    answer: ResearchAnswer,
    sources: list[SourceRecord],
    evidence: dict[str, SourceEvidence],
    provider_errors: list[ResearchProviderError],
) -> bytes:
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    findings = workbook.active
    findings.title = "Findings"
    findings.append(["Status", "Claim", "Source", "Source URL", "Retrieved at", "Published at", "Supporting quote"])
    conflicts = workbook.create_sheet("Conflicts")
    conflicts.append(["Topic", "Summary", "Source", "Source URL", "Retrieved at", "Supporting passage"])
    source_sheet = workbook.create_sheet("Sources")
    source_sheet.append(["Source ID", "Title", "URL", "Retrieved at", "Published at", "Snippet", "Supporting excerpt"])
    limitations = workbook.create_sheet("Limitations")
    limitations.append(["Type", "Detail"])

    def safe_cell(value: str) -> str:
        if value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def hyperlink(cell, url: str) -> None:
        cell.hyperlink = url
        cell.font = Font(color="0563C1", underline="single")

    for claim in answer.claims:
        if not claim.citations:
            findings.append([claim.status.title(), safe_cell(claim.text), "", "", "", "", ""])
        for citation in claim.citations:
            source = next(item for item in sources if item.source_id == citation.source_id)
            row = findings.max_row + 1
            findings.append([
                claim.status.title(),
                safe_cell(claim.text),
                safe_cell(_source_title(source)),
                source.canonical_url,
                source.retrieved_at.isoformat(),
                source.published_at.isoformat() if source.published_at else "",
                safe_cell(citation.quote),
            ])
            hyperlink(findings.cell(row, 3), source.canonical_url)
            hyperlink(findings.cell(row, 4), source.canonical_url)
    for conflict in answer.conflicts:
        for citation in conflict.citations:
            source = next(item for item in sources if item.source_id == citation.source_id)
            row = conflicts.max_row + 1
            conflicts.append([
                safe_cell(conflict.topic),
                safe_cell(conflict.summary),
                safe_cell(_source_title(source)),
                source.canonical_url,
                source.retrieved_at.isoformat(),
                safe_cell(citation.quote),
            ])
            hyperlink(conflicts.cell(row, 3), source.canonical_url)
            hyperlink(conflicts.cell(row, 4), source.canonical_url)
    for source in sources:
        row = source_sheet.max_row + 1
        source_sheet.append([
            source.source_id,
            safe_cell(_source_title(source)),
            source.canonical_url,
            source.retrieved_at.isoformat(),
            source.published_at.isoformat() if source.published_at else "",
            safe_cell(source.snippet),
            safe_cell(_source_excerpt(source.source_id, evidence)),
        ])
        hyperlink(source_sheet.cell(row, 2), source.canonical_url)
        hyperlink(source_sheet.cell(row, 3), source.canonical_url)
    for item in answer.limitations:
        limitations.append(["Evidence", safe_cell(item)])
    for item in provider_errors:
        limitations.append([safe_cell(item.code.replace("_", " ")), safe_cell(item.message)])
    for item in answer.completion_checks:
        limitations.append(["Completion check", safe_cell(item)])
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _render_presentation(
    answer: ResearchAnswer,
    sources: list[SourceRecord],
    evidence: dict[str, SourceEvidence],
    provider_errors: list[ResearchProviderError],
) -> bytes:
    from io import BytesIO
    from pptx import Presentation
    from pptx.util import Pt

    presentation = Presentation()
    title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    title_slide.shapes.title.text = "Research Report"
    title_slide.placeholders[1].text = f"{len(answer.claims)} findings - {len(sources)} sources"

    def new_slide(title: str):
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = title[:200]
        frame = slide.placeholders[1].text_frame
        frame.clear()
        frame.word_wrap = True
        return frame

    def add_text(frame, value: str, *, first: bool = False) -> None:
        paragraph = frame.paragraphs[0] if first else frame.add_paragraph()
        paragraph.text = value
        paragraph.font.size = Pt(11)

    def add_source(frame, source: SourceRecord, excerpt: str, *, first: bool = False) -> None:
        paragraph = frame.paragraphs[0] if first else frame.add_paragraph()
        run = paragraph.add_run()
        run.text = _source_title(source)
        run.hyperlink.address = source.canonical_url
        paragraph.add_run().text = f" - retrieved {source.retrieved_at.isoformat()}"
        if source.published_at:
            paragraph.add_run().text = f"; published {source.published_at.isoformat()}"
        paragraph.font.size = Pt(11)
        if excerpt:
            quote_paragraph = frame.add_paragraph()
            quote_paragraph.text = excerpt
            quote_paragraph.font.size = Pt(10)

    def add_citation(frame, citation, *, first: bool = False) -> None:
        source = next(item for item in sources if item.source_id == citation.source_id)
        add_source(frame, source, citation.quote, first=first)

    for index, claim in enumerate(answer.claims, start=1):
        citations = claim.citations or [None]
        for citation_index, citation in enumerate(citations, start=1):
            title = f"Finding {index}"
            if len(citations) > 1:
                title += f" - evidence {citation_index}"
            frame = new_slide(title)
            add_text(frame, f"{claim.status.title()}: {claim.text}", first=True)
            if citation:
                add_citation(frame, citation)
    for index, conflict in enumerate(answer.conflicts, start=1):
        for citation_index, citation in enumerate(conflict.citations, start=1):
            frame = new_slide(f"Conflicting evidence {index} - passage {citation_index}")
            add_text(frame, f"{conflict.topic}: {conflict.summary}", first=True)
            add_citation(frame, citation)
    for index, item in enumerate(answer.limitations, start=1):
        frame = new_slide(f"Evidence limitation {index}")
        add_text(frame, item, first=True)
    for index, item in enumerate(provider_errors, start=1):
        frame = new_slide(f"Retrieval limitation {index}")
        add_text(frame, f"{item.code}: {item.message}", first=True)
    for index, item in enumerate(answer.completion_checks, start=1):
        frame = new_slide(f"Completion check {index}")
        add_text(frame, item, first=True)
    for index, source in enumerate(sources, start=1):
        frame = new_slide(f"Source {index}")
        add_source(frame, source, _source_excerpt(source.source_id, evidence), first=True)
        if source.snippet:
            add_text(frame, f"Snippet: {source.snippet}")
        add_text(frame, f"Source ID: {source.source_id}")
    output = BytesIO()
    presentation.save(output)
    return output.getvalue()

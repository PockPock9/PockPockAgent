"""Word, PDF, spreadsheet and presentation writers for create_office_document.

The agent writes the content as light Markdown: ``#``/``##``/``###`` headings, ``-``/``*``/``1.`` list
items, ``**bold**`` and blank lines between paragraphs. Before 0.2.16 the Word writer copied every
line as a plain paragraph, so a resume showed literal "## Experience" and "- " text, and there was no
PDF writer at all ("Create a resume in Word and PDF" could not be done; scenario run 2026-11-28).
Headings use the built-in Heading styles and lists the built-in List styles, in one column with no
tables or images, which is what applicant tracking systems (ATS) read reliably.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Block:
    kind: str  # "heading", "bullet", "number", "paragraph"
    text: str
    level: int = 1


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


def parse_blocks(content: str) -> list[Block]:
    """Light Markdown to blocks. Consecutive plain lines join into one paragraph."""
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block("paragraph", " ".join(part.strip() for part in paragraph)))
            paragraph.clear()

    for line in content.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or _RULE.match(stripped):
            flush()
            continue
        if match := _HEADING.match(stripped):
            flush()
            blocks.append(Block("heading", match.group(2).strip().strip("#").strip(), min(len(match.group(1)), 3)))
        elif match := _BULLET.match(line):
            flush()
            blocks.append(Block("bullet", match.group(1).strip()))
        elif match := _NUMBER.match(line):
            flush()
            blocks.append(Block("number", match.group(1).strip()))
        else:
            paragraph.append(stripped)
    flush()
    return blocks


def bold_runs(text: str) -> list[tuple[str, bool]]:
    """Split ``**bold**`` (or ``__bold__``) spans out of a line; other Markdown marks are dropped."""
    runs: list[tuple[str, bool]] = []
    pieces = re.split(r"(\*\*.+?\*\*|__.+?__)", text)
    for piece in pieces:
        if not piece:
            continue
        if (piece.startswith("**") and piece.endswith("**")) or (piece.startswith("__") and piece.endswith("__")):
            runs.append((piece[2:-2], True))
        else:
            runs.append((re.sub(r"(?<!\w)[*_`](.+?)[*_`](?!\w)", r"\1", piece), False))
    return runs


def plain(text: str) -> str:
    return "".join(part for part, _ in bold_runs(text))


def write_word(path: Path, title: str, content: str) -> None:
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)
    blocks = parse_blocks(content)
    # A title repeated as the first heading is written once.
    if not (blocks and blocks[0].kind == "heading" and plain(blocks[0].text).strip().lower() == title.strip().lower()):
        document.add_heading(title, level=0)
    for index, block in enumerate(blocks):
        if block.kind == "heading":
            document.add_heading(plain(block.text)[:400], level=0 if index == 0 and block.level == 1 else block.level)
            continue
        style = {"bullet": "List Bullet", "number": "List Number"}.get(block.kind)
        paragraph = document.add_paragraph(style=style) if style else document.add_paragraph()
        for text, bold in bold_runs(block.text[:4000]):
            paragraph.add_run(text).bold = bold
    document.save(path)


def _pdf_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_pdf(path: Path, title: str, content: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.5, leading=14, spaceAfter=4)
    headings = {
        0: ParagraphStyle("DocTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=8, alignment=0),
        1: ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, spaceBefore=10, spaceAfter=4),
        2: ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=8, spaceAfter=3),
        3: ParagraphStyle("H3", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=6, spaceAfter=2),
    }

    def markup(text: str) -> str:
        return "".join(f"<b>{_pdf_escape(part)}</b>" if bold else _pdf_escape(part) for part, bold in bold_runs(text))

    story: list = []
    blocks = parse_blocks(content)
    if not (blocks and blocks[0].kind == "heading" and plain(blocks[0].text).strip().lower() == title.strip().lower()):
        story.append(Paragraph(_pdf_escape(title), headings[0]))
    items: list = []
    numbered = False

    def flush_list() -> None:
        if items:
            story.append(ListFlowable(list(items), bulletType="1" if numbered else "bullet", start="1" if numbered else None, leftIndent=14, bulletFontSize=9))
            items.clear()

    for index, block in enumerate(blocks):
        if block.kind in ("bullet", "number"):
            if items and numbered != (block.kind == "number"):
                flush_list()
            numbered = block.kind == "number"
            items.append(ListItem(Paragraph(markup(block.text[:4000]), body), leftIndent=14))
            continue
        flush_list()
        if block.kind == "heading":
            level = 0 if index == 0 and block.level == 1 else block.level
            story.append(Paragraph(markup(block.text[:400]), headings[level]))
        else:
            story.append(Paragraph(markup(block.text[:4000]), body))
    flush_list()
    if not story:
        story.append(Spacer(1, 1))
    document = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title=title)
    document.build(story)


def _cell(value: str):
    """Numbers become numbers (so totals and charts work in Excel); formulas starting with = are kept."""
    text = value.strip()[:2000]
    if re.fullmatch(r"-?\d+", text) and len(text) < 16:
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        return float(text.replace(",", "")) if "." in text else int(text.replace(",", ""))
    return text


def write_spreadsheet(path: Path, title: str, content: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = re.sub(r"[\[\]:*?/\\]", " ", title).strip()[:31] or "Task output"
    lines = [line for line in content.replace("\r\n", "\n").split("\n") if line.strip() and not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", line)]
    # A Markdown table is read as rows too: small models often send one instead of CSV.
    if lines and all(line.strip().startswith("|") for line in lines):
        rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    else:
        rows = list(csv.reader(io.StringIO("\n".join(lines)), strict=False))
    for row in rows[:1000]:
        sheet.append([_cell(cell) for cell in row[:30]])
    if sheet.max_row:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
    for column in sheet.columns:
        width = max((len(str(cell.value)) for cell in column if cell.value is not None), default=8)
        sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 8), 60)
    workbook.save(path)


def write_presentation(path: Path, title: str, content: str) -> None:
    from pptx import Presentation
    from pptx.util import Pt

    presentation = Presentation()
    # A "# Slide title" line starts a new slide; otherwise blank lines separate slides.
    if re.search(r"(?m)^#{1,3}\s+\S", content):
        slides = []
        for part in re.split(r"(?m)^(?=#{1,3}\s+\S)", content):
            if not part.strip():
                continue
            first, _, rest = part.strip().partition("\n")
            heading = _HEADING.match(first)
            slides.append((plain(heading.group(2)) if heading else "", rest if heading else part))
    else:
        slides = [("", part) for part in re.split(r"\n\s*\n", content) if part.strip()]
    slides = slides[:20] or [("", content)]
    cover = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover.shapes.title.text = title
    if slides and not slides[0][0] and len(slides[0][1].splitlines()) <= 2:
        cover.placeholders[1].text = plain(slides.pop(0)[1].strip())[:300]
    else:
        cover.placeholders[1].text = ""
    for index, (heading, text) in enumerate(slides, 1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = heading or f"{title} · {index}"
        frame = slide.placeholders[1].text_frame
        frame.clear()
        lines = [block for block in parse_blocks(text)][:12]
        for number, block in enumerate(lines):
            paragraph = frame.paragraphs[0] if number == 0 else frame.add_paragraph()
            paragraph.text = plain(block.text)[:500]
            paragraph.font.size = Pt(20 if len(lines) <= 5 else 16)
    presentation.save(path)


WRITERS = {
    "word": (".docx", write_word),
    "pdf": (".pdf", write_pdf),
    "spreadsheet": (".xlsx", write_spreadsheet),
    "presentation": (".pptx", write_presentation),
}

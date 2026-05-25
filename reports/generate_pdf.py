from __future__ import annotations

import os
import time
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _split_sections(content: str) -> tuple[str, list[str]]:
    lines = [line.rstrip() for line in content.splitlines()]
    title = lines[0] if lines and lines[0].strip() else "Global AI Trade Intelligence Report"
    body = lines[1:] if lines else []
    return title, body


def _paragraph_for_line(line: str, styles) -> Paragraph | Spacer:
    if not line.strip():
        return Spacer(1, 0.12 * inch)
    section_headings = {
        "Priority routes",
        "Fleet status",
        "Live vessel sample",
        "AI action queue",
        "Recent operational timeline",
        "Active high-severity alerts",
        "Recommendations",
    }
    if line.endswith(":") or line in section_headings or any(line.startswith(f"{heading} ") for heading in section_headings):
        return Paragraph(line, styles["SectionHeading"])
    if line.startswith("- "):
        return Paragraph(f"&bull; {line[2:]}", styles["BulletLine"])
    if line.startswith("  "):
        return Paragraph(line.strip(), styles["IndentedLine"])
    return Paragraph(line, styles["Body"])


def generate_pdf_report(content: str, output_dir: str = "reports") -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = os.path.join(output_dir, f"report_{time.time_ns()}.pdf")
    title, body_lines = _split_sections(content)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        textColor=colors.HexColor("#0f172a"),
        fontSize=20,
        leading=24,
        spaceAfter=14,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#0f766e"),
        fontSize=12,
        leading=15,
        spaceBefore=10,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="Body",
        parent=styles["BodyText"],
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1f2937"),
    ))
    styles.add(ParagraphStyle(
        name="BulletLine",
        parent=styles["Body"],
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="IndentedLine",
        parent=styles["Body"],
        leftIndent=18,
        textColor=colors.HexColor("#475569"),
        spaceAfter=5,
    ))

    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=title,
    )

    story = [
        Table(
            [[Paragraph(title, styles["ReportTitle"])]],
            colWidths=[7.2 * inch],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ecfeff")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#0f766e")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        ),
        Spacer(1, 0.18 * inch),
    ]
    story.extend(_paragraph_for_line(line, styles) for line in body_lines)
    doc.build(story)
    return filename

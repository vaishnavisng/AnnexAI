import os
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.config.settings import PDF_DIR


def _to_paragraphs(text: str) -> List[Paragraph]:
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=16,
        spaceAfter=8,
    )
    output = []
    for line in (text or "").splitlines():
        clean = line.strip()
        if not clean:
            output.append(Spacer(1, 8))
            continue
        if clean.startswith("#"):
            level = len(clean) - len(clean.lstrip("#"))
            font_size = 18 if level == 1 else 14 if level == 2 else 12
            title_style = ParagraphStyle(
                f"H{level}",
                parent=styles["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=font_size,
                leading=font_size + 3,
                spaceBefore=10,
                spaceAfter=6,
            )
            output.append(Paragraph(clean.lstrip("# "), title_style))
        else:
            output.append(Paragraph(clean, body))
    return output


def generate_pdf(lecture_id: str, title: str, text: str, suffix: str) -> str:
    os.makedirs(PDF_DIR, exist_ok=True)
    path = os.path.join(PDF_DIR, f"{lecture_id}_{suffix}.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4, title=title)

    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "DocTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        spaceAfter=14,
    )

    story = [Paragraph(title, heading), Spacer(1, 10)]
    story.extend(_to_paragraphs(text))
    doc.build(story)
    return path

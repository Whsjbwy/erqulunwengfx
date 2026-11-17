"""Render the self-authored direction review as exactly two readable A4 pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


def main() -> None:
    """Require explicit licensed local font and source; no new library installation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    if len(source["pages"]) != 2:
        raise ValueError("The direction review must contain exactly two page sections")
    pdfmetrics.registerFont(TTFont("Chinese", str(args.font)))
    pdfmetrics.registerFontFamily("Chinese", normal="Chinese", bold="Chinese")
    body = ParagraphStyle(
        "Body",
        fontName="Chinese",
        fontSize=10.5,
        leading=17,
        wordWrap="CJK",
        spaceAfter=9,
    )
    heading = ParagraphStyle(
        "Heading",
        parent=body,
        fontSize=12,
        leading=19,
        textColor=colors.HexColor("#163653"),
        spaceBefore=8,
        spaceAfter=6,
    )
    title = ParagraphStyle(
        "Title", parent=heading, fontSize=18, leading=25, spaceAfter=8
    )
    subtitle = ParagraphStyle(
        "Subtitle",
        parent=body,
        fontSize=10,
        textColor=colors.HexColor("#5A6977"),
        spaceAfter=15,
    )
    story = []
    for index, page in enumerate(source["pages"]):
        if index:
            story.append(PageBreak())
        story.extend(
            [
                Paragraph(page["title"], title),
                Paragraph(page["subtitle"], subtitle),
                Spacer(1, 4),
            ]
        )
        for label, text in page["sections"]:
            story.extend(
                [
                    Paragraph(label, heading),
                    Paragraph(text.replace("&", "&amp;").replace("<=", "&lt;="), body),
                ]
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(args.output),
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=40,
        bottomMargin=43,
        title="7B-0候选科研方向重审",
        author="AUV research reproduction project",
    )

    def footer(canvas: object, document: object) -> None:
        canvas.setFont("Chinese", 9)
        canvas.setFillColor(colors.HexColor("#5A6977"))
        canvas.drawString(48, 23, source["date"] + "  |  待审核，未授权新模型或实验")
        canvas.drawRightString(A4[0] - 48, 23, f"{document.page} / 2")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    pages = len(PdfReader(args.output).pages)
    if pages != 2:
        raise RuntimeError(f"Review overflowed the two-page limit: {pages}")
    print(
        json.dumps({"pdf_pages": pages, "output": str(args.output)}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()

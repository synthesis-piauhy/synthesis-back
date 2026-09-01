from html import escape
from io import BytesIO

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .models import WeeklyReport


def render_report_pdf(report: WeeklyReport) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"synthesis — {report.cycle.label}",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("SynthesisTitle", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=8 * mm)
    section_title = ParagraphStyle("SectionTitle", parent=styles["Heading1"], spaceBefore=4 * mm)
    card_title = ParagraphStyle("CardTitle", parent=styles["Heading2"], fontSize=13, leading=16)
    story = [
        Paragraph("synthesis", title),
        Paragraph(escape(report.cycle.label), styles["Heading2"]),
        Spacer(1, 5 * mm),
    ]
    active_sections = [
        section for section in report.sections.all() if any(not card.removed for card in section.cards.all())
    ]
    for section_index, section in enumerate(active_sections):
        if section_index:
            story.append(PageBreak())
        story.append(Paragraph(escape(section.title), section_title))
        for card in section.cards.all():
            if card.removed:
                continue
            story.extend(
                [
                    Paragraph(escape(card.editorial_title), card_title),
                    Paragraph(escape(card.editorial_summary), styles["BodyText"]),
                    Spacer(1, 2 * mm),
                    Paragraph(f"<b>Resultado:</b> {escape(card.editorial_result)}", styles["BodyText"]),
                    Spacer(1, 5 * mm),
                ]
            )
    document.build(story)
    return buffer.getvalue()

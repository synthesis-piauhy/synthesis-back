from html import escape
from io import BytesIO

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .models import WeeklyReport


def report_photo(card):
    """Return a proportionally sized image, without failing the whole PDF on a bad file."""
    try:
        with card.selected_photo.image.open("rb") as image_file:
            image_data = BytesIO(image_file.read())
        width, height = ImageReader(image_data).getSize()
        max_width, max_height = 174 * mm, 76 * mm
        scale = min(max_width / width, max_height / height)
        return Image(image_data, width=width * scale, height=height * scale)
    except Exception:
        return None


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
    metadata = ParagraphStyle("Metadata", parent=styles["BodyText"], textColor="#4B5563", spaceAfter=2 * mm)
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
            details = (
                f"<b>Data:</b> {card.original_date:%d/%m/%Y} &nbsp;&nbsp; "
                f"<b>Local:</b> {escape(card.original_location)}<br/>"
                f"<b>Público beneficiado:</b> {escape(card.original_beneficiaries)} &nbsp;&nbsp; "
                f"<b>Responsável:</b> {escape(card.original_manager_name)}"
            )
            card_story = [Paragraph(escape(card.editorial_title), card_title)]
            if photo := report_photo(card):
                card_story.extend([photo, Spacer(1, 3 * mm)])
            card_story.extend(
                [
                    Paragraph(details, metadata),
                    Paragraph(escape(card.editorial_summary), styles["BodyText"]),
                    Spacer(1, 2 * mm),
                    Paragraph(f"<b>Resultado:</b> {escape(card.editorial_result)}", styles["BodyText"]),
                    Spacer(1, 6 * mm),
                ]
            )
            story.append(KeepTogether(card_story))
    document.build(story)
    return buffer.getvalue()

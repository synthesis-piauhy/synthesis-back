import logging
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import ExecutiveClassification, WeeklyReport

logger = logging.getLogger(__name__)


def report_photo(card):
    """Return a proportionally sized image, without failing the whole PDF on a bad file."""
    try:
        with card.selected_photo.image.open("rb") as image_file:
            image_data = BytesIO(image_file.read())
        width, height = ImageReader(image_data).getSize()
        max_width, max_height = 174 * mm, 52 * mm
        scale = min(max_width / width, max_height / height)
        return Image(image_data, width=width * scale, height=height * scale)
    except (OSError, ValueError) as exc:
        logger.warning("pdf_photo_unavailable", extra={"card_id": str(card.pk), "error": str(exc)})
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
    label = ParagraphStyle(
        "ExecutiveLabel",
        parent=styles["Heading3"],
        fontSize=10,
        leading=13,
        textColor="#365314",
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
        uppercase=True,
    )
    lead = ParagraphStyle("ExecutiveLead", parent=styles["BodyText"], fontSize=12, leading=17)
    story = [
        Paragraph("synthesis", title),
        Paragraph(escape(report.cycle.label), styles["Heading2"]),
        Spacer(1, 5 * mm),
    ]
    active_sections = [
        section for section in report.sections.all() if any(not card.removed for card in section.cards.all())
    ]
    active_cards = [card for section in active_sections for card in section.cards.all() if not card.removed]
    evidence_count = sum(bool(card.editorial_evidence.strip()) for card in active_cards)
    metrics = Table(
        [
            [
                Paragraph(f"<b>{len(active_cards)}</b><br/>iniciativas", metadata),
                Paragraph(f"<b>{len(active_sections)}</b><br/>áreas mobilizadas", metadata),
                Paragraph(f"<b>{evidence_count}</b><br/>com evidência", metadata),
            ]
        ],
        colWidths=[58 * mm, 58 * mm, 58 * mm],
    )
    metrics.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend(
        [
            Paragraph("Leitura da semana", label),
            Paragraph(escape(report.executive_summary), lead),
            Spacer(1, 4 * mm),
            metrics,
        ]
    )
    highlights = [
        card for card in active_cards if card.executive_classification == ExecutiveClassification.HIGHLIGHT
    ][:3]
    attention = [
        card for card in active_cards if card.executive_classification == ExecutiveClassification.ATTENTION
    ][:3]
    priorities = [card for card in active_cards if card.editorial_next_step.strip()][:3]
    story.append(Paragraph("Destaques", label))
    if highlights:
        for card in highlights:
            story.append(
                Paragraph(
                    f"<b>{escape(card.editorial_title)}</b> — {escape(card.editorial_result)} "
                    f"<font color='#166534'>Evidência: {escape(card.editorial_evidence)}</font>",
                    styles["BodyText"],
                )
            )
    else:
        story.append(Paragraph("Nenhum destaque foi selecionado para esta semana.", metadata))
    story.append(Paragraph("Pontos de atenção e decisões", label))
    if attention:
        for card in attention:
            decision = (
                f" <b>Decisão solicitada:</b> {escape(card.decision_request)}" if card.needs_decision else ""
            )
            story.append(
                Paragraph(
                    f"<b>{escape(card.editorial_title)}</b> — {escape(card.editorial_result)}{decision}",
                    styles["BodyText"],
                )
            )
    else:
        story.append(Paragraph("Nenhum ponto de atenção foi selecionado.", metadata))
    story.append(Paragraph("Prioridades da próxima semana", label))
    if priorities:
        for card in priorities:
            due_date = card.next_step_due_date.strftime("%d/%m/%Y") if card.next_step_due_date else ""
            story.append(
                Paragraph(
                    f"<b>{escape(card.editorial_next_step)}</b> — "
                    f"{escape(card.next_step_owner)} · {due_date}",
                    styles["BodyText"],
                )
            )
    else:
        story.append(Paragraph("Nenhuma prioridade foi registrada.", metadata))
    story.append(PageBreak())
    for section_index, section in enumerate(active_sections):
        if section_index:
            story.append(PageBreak())
        story.append(Paragraph(escape(section.title), section_title))
        if section.executive_summary:
            story.extend([Paragraph(escape(section.executive_summary), lead), Spacer(1, 3 * mm)])
        for card in section.cards.all():
            if card.removed:
                continue
            details = (
                f"<b>Data:</b> {card.original_date:%d/%m/%Y} &nbsp;&nbsp; "
                f"<b>Local:</b> {escape(card.original_location)}<br/>"
                f"<b>Público beneficiado:</b> {escape(card.original_beneficiaries)} &nbsp;&nbsp; "
                f"<b>Responsável:</b> {escape(card.original_manager_name)}"
            )
            classification = card.get_executive_classification_display()
            card_story = [
                Paragraph(escape(card.editorial_title), card_title),
                Paragraph(f"<b>{escape(classification)}</b>", metadata),
                Paragraph(f"<b>Resultado:</b> {escape(card.editorial_result)}", styles["BodyText"]),
            ]
            if card.editorial_evidence:
                card_story.extend(
                    [
                        Spacer(1, 2 * mm),
                        Paragraph(f"<b>Evidência:</b> {escape(card.editorial_evidence)}", metadata),
                    ]
                )
            if photo := report_photo(card):
                card_story.extend([photo, Spacer(1, 3 * mm)])
            card_story.extend(
                [
                    Paragraph(escape(card.editorial_summary), styles["BodyText"]),
                    Spacer(1, 2 * mm),
                    Paragraph(details, metadata),
                    *(
                        [
                            Paragraph(
                                f"<b>Próximo passo:</b> {escape(card.editorial_next_step)} — "
                                f"{escape(card.next_step_owner)} · "
                                f"{card.next_step_due_date:%d/%m/%Y}",
                                metadata,
                            ),
                        ]
                        if card.editorial_next_step
                        else []
                    ),
                    *(
                        [
                            Paragraph(
                                f"<b>Decisão solicitada:</b> {escape(card.decision_request)}",
                                metadata,
                            )
                        ]
                        if card.needs_decision
                        else []
                    ),
                    Spacer(1, 6 * mm),
                ]
            )
            story.append(KeepTogether(card_story))
    document.build(story)
    return buffer.getvalue()

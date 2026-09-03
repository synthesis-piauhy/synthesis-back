from collections import defaultdict
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import (
    ActivityPhoto,
    ActivityReport,
    AuditEvent,
    CollectionStatus,
    ReportCard,
    ReportSection,
    ReportStatus,
    ReportVersion,
    User,
    WeeklyCycle,
    WeeklyReport,
)
from .pdf import render_report_pdf
from .validators import ALLOWED_IMAGE_TYPES, MAX_IMAGE_SIZE


class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def audit(actor: User, action: str, entity, **metadata) -> None:
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        entity=entity.__class__.__name__,
        entity_id=str(entity.pk),
        metadata=metadata,
    )


def _validate_text(data: dict) -> None:
    minimums = {"title": 3, "location": 2, "summary": 10, "result": 10, "beneficiaries": 2}
    for field, minimum in minimums.items():
        value = data.get(field)
        if value is not None and len(value.strip()) < minimum:
            raise DomainError(f"O campo {field} precisa ter ao menos {minimum} caracteres.")


def _validate_upload(upload) -> None:
    if upload.size > MAX_IMAGE_SIZE:
        raise DomainError("Cada imagem deve ter no máximo 5 MB.")
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise DomainError("Use imagens JPEG, PNG ou WebP.")


@transaction.atomic
def create_activity(*, actor: User, data: dict, photos: list) -> ActivityReport:
    if not photos:
        raise DomainError("Uma foto principal é obrigatória.")
    if not actor.area_id:
        raise DomainError("O gestor precisa estar vinculado a uma área.")
    _validate_text(data)
    for photo in photos:
        _validate_upload(photo)
    try:
        cycle = WeeklyCycle.objects.get(pk=data.pop("cycleId"))
    except WeeklyCycle.DoesNotExist as exc:
        raise DomainError("Ciclo não encontrado.", 404) from exc
    if not cycle.accepts_reports:
        raise DomainError("O ciclo está encerrado.", 409)
    report = ActivityReport(manager=actor, area=actor.area, cycle=cycle, **data)
    try:
        report.full_clean()
    except ValidationError as exc:
        raise DomainError(" ".join(exc.messages)) from exc
    report.save()
    for index, upload in enumerate(photos):
        photo = ActivityPhoto(
            activity_report=report,
            image=upload,
            name=upload.name,
            alt=upload.name,
            is_main=index == 0,
        )
        photo.full_clean()
        photo.save()
    audit(actor, "activity.created", report)
    return report


@transaction.atomic
def update_own_activity(*, actor: User, report: ActivityReport, changes: dict) -> ActivityReport:
    if report.manager_id != actor.id:
        raise DomainError("Você só pode editar os próprios relatos.", 403)
    if not report.cycle.accepts_reports:
        raise DomainError("O ciclo está encerrado.", 409)
    _validate_text(changes)
    for field, value in changes.items():
        setattr(report, field, value)
    try:
        report.full_clean()
    except ValidationError as exc:
        raise DomainError(" ".join(exc.messages)) from exc
    report.save()
    audit(actor, "activity.updated", report, fields=sorted(changes))
    return report


@transaction.atomic
def reopen_cycle(*, actor: User, cycle: WeeklyCycle, reason: str, new_deadline) -> WeeklyCycle:
    if len(reason.strip()) < 5:
        raise DomainError("Informe o motivo da reabertura.")
    if new_deadline <= timezone.now():
        raise DomainError("O novo prazo precisa estar no futuro.")
    cycle.status = CollectionStatus.REOPENED
    cycle.reopen_reason = reason.strip()
    cycle.deadline = new_deadline
    cycle.save(update_fields=("status", "reopen_reason", "deadline", "updated_at"))
    audit(actor, "cycle.reopened", cycle, reason=reason)
    return cycle


def report_queryset():
    return WeeklyReport.objects.select_related("cycle").prefetch_related(
        "selected_activities",
        "versions__generated_by",
        "sections__area",
        "sections__cards__area",
        "sections__cards__selected_photo",
        "sections__cards__activity_report__manager",
    )


@transaction.atomic
def generate_draft(*, actor: User, cycle_id: UUID, activity_ids: list[UUID]) -> WeeklyReport:
    if not activity_ids:
        raise DomainError("Selecione ao menos um relato.")
    if len(set(activity_ids)) != len(activity_ids):
        raise DomainError("A seleção contém relatos duplicados.")
    try:
        cycle = WeeklyCycle.objects.get(pk=cycle_id)
    except WeeklyCycle.DoesNotExist as exc:
        raise DomainError("Ciclo não encontrado.", 404) from exc
    existing = report_queryset().filter(cycle=cycle).first()
    if existing:
        existing_ids = set(existing.selected_activities.values_list("id", flat=True))
        if existing_ids != set(activity_ids):
            raise DomainError("O rascunho deste ciclo já foi criado e sua seleção está fechada.", 409)
        return existing
    activities = list(
        ActivityReport.objects.filter(pk__in=activity_ids, cycle=cycle)
        .select_related("area")
        .prefetch_related("photos")
        .order_by("area__order", "date", "created_at")
    )
    if len(activities) != len(activity_ids):
        raise DomainError("Há relatos inexistentes ou pertencentes a outro ciclo.")
    report = WeeklyReport.objects.create(cycle=cycle, status=ReportStatus.DRAFT)
    report.selected_activities.set(activities)
    by_area = defaultdict(list)
    for activity in activities:
        by_area[activity.area].append(activity)
    for section_order, (area, area_activities) in enumerate(by_area.items()):
        section = ReportSection.objects.create(
            weekly_report=report,
            area=area,
            title=area.name,
            order=section_order,
        )
        for card_order, activity in enumerate(area_activities):
            selected_photo = next((photo for photo in activity.photos.all() if photo.is_main), None)
            if selected_photo is None:
                raise DomainError(f'O relato "{activity.title}" não possui foto principal.')
            ReportCard.objects.create(
                section=section,
                activity_report=activity,
                editorial_title=activity.title,
                editorial_summary=activity.summary,
                editorial_result=activity.result,
                selected_photo=selected_photo,
                area=activity.area,
                original_date=activity.date,
                original_location=activity.location,
                original_beneficiaries=activity.beneficiaries,
                original_manager_name=activity.manager.name,
                order=card_order,
            )
    audit(actor, "report.draft_generated", report, activities=[str(value) for value in activity_ids])
    return report_queryset().get(pk=report.pk)


@transaction.atomic
def update_card(*, actor: User, card: ReportCard, changes: dict) -> ReportCard:
    photo_id = changes.pop("selectedPhotoId", None)
    field_map = {
        "editorialTitle": "editorial_title",
        "editorialSummary": "editorial_summary",
        "editorialResult": "editorial_result",
    }
    for input_name, model_name in field_map.items():
        if input_name in changes:
            value = changes[input_name].strip()
            if not value:
                raise DomainError("Campos editoriais não podem ficar vazios.")
            setattr(card, model_name, value)
    if photo_id is not None:
        try:
            card.selected_photo = card.activity_report.photos.get(pk=photo_id)
        except ActivityPhoto.DoesNotExist as exc:
            raise DomainError("A foto selecionada não pertence ao relato.") from exc
    card.full_clean()
    card.save()
    WeeklyReport.objects.filter(pk=card.section.weekly_report_id).update(
        status=ReportStatus.EDITING,
        updated_at=timezone.now(),
    )
    audit(actor, "report.card_updated", card, fields=sorted(changes))
    return card


@transaction.atomic
def reorder_cards(*, actor: User, section: ReportSection, card_ids: list[UUID]) -> WeeklyReport:
    cards = {card.id: card for card in section.cards.all()}
    if len(card_ids) != len(set(card_ids)) or set(card_ids) != set(cards):
        raise DomainError("A ordenação deve conter cada card da seção exatamente uma vez.")
    for order, card_id in enumerate(card_ids):
        card = cards[card_id]
        card.order = order
        card.save(update_fields=("order", "updated_at"))
    report = section.weekly_report
    report.status = ReportStatus.EDITING
    report.save(update_fields=("status", "updated_at"))
    audit(actor, "report.cards_reordered", section, cards=[str(value) for value in card_ids])
    return report_queryset().get(pk=report.pk)


@transaction.atomic
def remove_card(*, actor: User, card: ReportCard) -> WeeklyReport:
    card.removed = True
    card.save(update_fields=("removed", "updated_at"))
    report = card.section.weekly_report
    report.status = ReportStatus.EDITING
    report.save(update_fields=("status", "updated_at"))
    audit(actor, "report.card_removed", card)
    return report_queryset().get(pk=report.pk)


@transaction.atomic
def generate_pdf_version(*, actor: User, report_id: UUID) -> ReportVersion:
    try:
        report = report_queryset().select_for_update().get(pk=report_id)
    except WeeklyReport.DoesNotExist as exc:
        raise DomainError("Relatório não encontrado.", 404) from exc
    if not ReportCard.objects.filter(section__weekly_report=report, removed=False).exists():
        raise DomainError("O relatório precisa ter ao menos um card ativo.")
    next_version = (report.versions.aggregate(value=Max("version"))["value"] or 0) + 1
    pdf_content = render_report_pdf(report)
    version = ReportVersion(weekly_report=report, version=next_version, generated_by=actor)
    version.pdf.save(f"{report.id}-v{next_version}.pdf", ContentFile(pdf_content), save=False)
    version.save()
    report.status = ReportStatus.PDF_GENERATED
    report.save(update_fields=("status", "updated_at"))
    audit(actor, "report.pdf_generated", version, version=next_version)
    return version

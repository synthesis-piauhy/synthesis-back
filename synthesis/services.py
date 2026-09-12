import logging
from collections import defaultdict
from time import monotonic
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Max
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
from .validators import MAX_PHOTOS, MAX_UPLOAD_BYTES, normalize_image

logger = logging.getLogger(__name__)


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


def create_activity(*, actor: User, data: dict, photos: list) -> ActivityReport:
    if len(photos) > MAX_PHOTOS or sum(photo.size for photo in photos) > MAX_UPLOAD_BYTES:
        raise DomainError("Envie até 10 fotos, somando no máximo 25 MB.")
    try:
        normalized = [normalize_image(photo) for photo in photos]
    except ValidationError as exc:
        raise DomainError(" ".join(exc.messages)) from exc
    saved_files = []
    try:
        with transaction.atomic():
            return _create_activity(actor=actor, data=data.copy(), photos=normalized, saved_files=saved_files)
    except Exception:
        for storage, name in saved_files:
            storage.delete(name)
        raise


def _create_activity(*, actor: User, data: dict, photos: list, saved_files: list) -> ActivityReport:
    if not photos:
        raise DomainError("Uma foto principal é obrigatória.")
    if not actor.area_id:
        raise DomainError("O gestor precisa estar vinculado a uma área.")
    _validate_text(data)
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
            name=getattr(upload, "_synthesis_original_name", upload.name),
            alt=getattr(upload, "_synthesis_original_name", upload.name),
            is_main=index == 0,
        )
        photo.full_clean()
        photo.save()
        saved_files.append((photo.image.storage, photo.image.name))
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
        cycle = WeeklyCycle.objects.select_for_update().get(pk=cycle_id)
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
    WeeklyReport.objects.select_for_update().get(pk=card.section.weekly_report_id)
    card = (
        ReportCard.objects.select_for_update()
        .select_related("activity_report", "section__weekly_report", "area")
        .get(pk=card.pk)
    )
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
        content_version=F("content_version") + 1,
        updated_at=timezone.now(),
    )
    audit(actor, "report.card_updated", card, fields=sorted(changes))
    return card


@transaction.atomic
def reorder_cards(*, actor: User, section: ReportSection, card_ids: list[UUID]) -> WeeklyReport:
    WeeklyReport.objects.select_for_update().get(pk=section.weekly_report_id)
    section = ReportSection.objects.select_for_update().get(pk=section.pk)
    cards = {card.id: card for card in section.cards.select_for_update()}
    if len(card_ids) != len(set(card_ids)) or set(card_ids) != set(cards):
        raise DomainError("A ordenação deve conter cada card da seção exatamente uma vez.")
    for order, card_id in enumerate(card_ids):
        card = cards[card_id]
        card.order = order
        card.save(update_fields=("order", "updated_at"))
    report = section.weekly_report
    report.status = ReportStatus.EDITING
    report.content_version += 1
    report.save(update_fields=("status", "content_version", "updated_at"))
    audit(actor, "report.cards_reordered", section, cards=[str(value) for value in card_ids])
    return report_queryset().get(pk=report.pk)


@transaction.atomic
def remove_card(*, actor: User, card: ReportCard) -> WeeklyReport:
    WeeklyReport.objects.select_for_update().get(pk=card.section.weekly_report_id)
    card = ReportCard.objects.select_for_update().select_related("section__weekly_report").get(pk=card.pk)
    card.removed = True
    card.save(update_fields=("removed", "updated_at"))
    report = card.section.weekly_report
    report.status = ReportStatus.EDITING
    report.content_version += 1
    report.save(update_fields=("status", "content_version", "updated_at"))
    audit(actor, "report.card_removed", card)
    return report_queryset().get(pk=report.pk)


def generate_pdf_version(*, actor: User, report_id: UUID) -> ReportVersion:
    started = monotonic()
    with transaction.atomic():
        try:
            report = report_queryset().select_for_update().get(pk=report_id)
        except WeeklyReport.DoesNotExist as exc:
            raise DomainError("Relatório não encontrado.", 404) from exc
        if not any(not card.removed for section in report.sections.all() for card in section.cards.all()):
            raise DomainError("O relatório precisa ter ao menos um card ativo.")
        snapshot_content_version = report.content_version

    # Report content has been fully prefetched and can be rendered without holding a database lock.
    pdf_content = render_report_pdf(report)
    saved_file = None
    try:
        with transaction.atomic():
            current = WeeklyReport.objects.select_for_update().get(pk=report_id)
            if current.content_version != snapshot_content_version:
                raise DomainError("O relatório mudou durante a geração. Gere o PDF novamente.", 409)
            next_version = (
                ReportVersion.objects.filter(weekly_report=current).aggregate(value=Max("version"))["value"]
                or 0
            ) + 1
            version = ReportVersion(weekly_report=current, version=next_version, generated_by=actor)
            version.pdf.save(f"{current.id}-v{next_version}.pdf", ContentFile(pdf_content), save=False)
            saved_file = (version.pdf.storage, version.pdf.name)
            version.save()
            current.status = ReportStatus.PDF_GENERATED
            current.save(update_fields=("status", "updated_at"))
            audit(actor, "report.pdf_generated", version, version=next_version)
    except Exception:
        if saved_file:
            saved_file[0].delete(saved_file[1])
        logger.exception(
            "pdf_generation_failed",
            extra={"report_id": str(report_id), "actor_id": str(actor.pk)},
        )
        raise
    logger.info(
        "pdf_generation_completed",
        extra={
            "report_id": str(report_id),
            "version": version.version,
            "duration_ms": round((monotonic() - started) * 1000),
        },
    )
    return version

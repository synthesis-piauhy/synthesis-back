import json
import logging
from collections import defaultdict
from time import monotonic
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from . import notifications
from .activity_templates import (
    ACTIVE_TEMPLATE_KEYS,
    EDITORIAL_LIMITS,
    EXECUTIVE_LIMITS,
    PUBLISHABLE_LIMITS,
    TEMPLATE_VERSION,
)
from .models import (
    ActivityPhoto,
    ActivityReport,
    AuditEvent,
    CollectionStatus,
    ExecutiveClassification,
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
    for field, maximum in PUBLISHABLE_LIMITS.items():
        value = data.get(field)
        if value is not None and len(value.strip()) > maximum:
            raise DomainError(f"O campo {field} deve ter no máximo {maximum} caracteres.")


def _validate_guided_answers(answers: object) -> None:
    if not isinstance(answers, dict) or len(answers) > 20:
        raise DomainError("Respostas guiadas inválidas.")
    if any(
        not isinstance(key, str) or len(key) > 50 or not isinstance(value, str) or len(value) > 300
        for key, value in answers.items()
    ):
        raise DomainError("Respostas guiadas inválidas.")


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
    for field in PUBLISHABLE_LIMITS:
        if isinstance(data.get(field), str):
            data[field] = data[field].strip()
    _validate_text(data)
    template_key = data.pop("templateKey", "")
    if template_key not in ACTIVE_TEMPLATE_KEYS:
        raise DomainError("Selecione um modelo de relato válido.")
    data["template_key"] = template_key
    data["template_version"] = TEMPLATE_VERSION
    data["next_step"] = data.pop("nextStep", "").strip()
    data["internal_notes"] = data.pop("internalNotes", "").strip()
    try:
        data["guided_answers"] = json.loads(data.pop("guidedAnswers", "{}"))
    except (TypeError, ValueError) as exc:
        raise DomainError("Respostas guiadas inválidas.") from exc
    _validate_guided_answers(data["guided_answers"])
    data["evidence"] = data.get("evidence", "").strip()
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
    notifications.activity_created(actor, report)
    return report


@transaction.atomic
def update_own_activity(*, actor: User, report: ActivityReport, changes: dict) -> ActivityReport:
    if report.manager_id != actor.id:
        raise DomainError("Você só pode editar os próprios relatos.", 403)
    if not report.cycle.accepts_reports:
        raise DomainError("O ciclo está encerrado.", 409)
    for field in PUBLISHABLE_LIMITS:
        if isinstance(changes.get(field), str):
            changes[field] = changes[field].strip()
    _validate_text(changes)
    if "nextStep" in changes:
        changes["next_step"] = changes.pop("nextStep").strip()
    if "internalNotes" in changes:
        changes["internal_notes"] = changes.pop("internalNotes").strip()
    if "guidedAnswers" in changes:
        changes["guided_answers"] = changes.pop("guidedAnswers")
        _validate_guided_answers(changes["guided_answers"])
    for field, value in changes.items():
        setattr(report, field, value)
    try:
        report.full_clean()
    except ValidationError as exc:
        raise DomainError(" ".join(exc.messages)) from exc
    report.save()
    audit(actor, "activity.updated", report, fields=sorted(changes))
    notifications.activity_updated(actor, report)
    return report


def _validate_cycle_window(*, starts_at, ends_at, deadline, deadline_within_cycle=True) -> None:
    if ends_at < starts_at:
        raise DomainError("O fim do ciclo precisa ser igual ou posterior ao início.")
    if deadline <= timezone.now():
        raise DomainError("O prazo de envio precisa estar no futuro.")
    if deadline_within_cycle and not starts_at <= timezone.localtime(deadline).date() <= ends_at:
        raise DomainError("O prazo de envio precisa estar dentro do período do ciclo.")


@transaction.atomic
def create_cycle(*, actor: User, label: str, starts_at, ends_at, deadline) -> WeeklyCycle:
    _validate_cycle_window(starts_at=starts_at, ends_at=ends_at, deadline=deadline)
    if (
        WeeklyCycle.objects.select_for_update()
        .filter(status__in=(CollectionStatus.OPEN, CollectionStatus.REOPENED))
        .exists()
    ):
        raise DomainError("Encerre o ciclo ativo antes de abrir um novo.", 409)
    cycle = WeeklyCycle(
        label=label.strip(),
        starts_at=starts_at,
        ends_at=ends_at,
        deadline=deadline,
        status=CollectionStatus.OPEN,
    )
    try:
        cycle.full_clean()
    except ValidationError as exc:
        raise DomainError(" ".join(exc.messages)) from exc
    cycle.save()
    audit(actor, "cycle.created", cycle)
    notifications.cycle_opened(actor, cycle)
    return cycle


@transaction.atomic
def close_cycle(*, actor: User, cycle: WeeklyCycle) -> WeeklyCycle:
    cycle = WeeklyCycle.objects.select_for_update().get(pk=cycle.pk)
    if not cycle.accepts_reports:
        raise DomainError("Este ciclo já está encerrado.", 409)
    cycle.status = CollectionStatus.CLOSED
    cycle.save(update_fields=("status", "updated_at"))
    audit(actor, "cycle.closed", cycle)
    notifications.cycle_closed(actor, cycle)
    return cycle


@transaction.atomic
def update_cycle_deadline(*, actor: User, cycle: WeeklyCycle, deadline) -> WeeklyCycle:
    cycle = WeeklyCycle.objects.select_for_update().get(pk=cycle.pk)
    if not cycle.accepts_reports:
        raise DomainError("Somente ciclos ativos podem ter o prazo ajustado.", 409)
    _validate_cycle_window(
        starts_at=cycle.starts_at,
        ends_at=cycle.ends_at,
        deadline=deadline,
        deadline_within_cycle=cycle.status == CollectionStatus.OPEN,
    )
    cycle.deadline = deadline
    cycle.save(update_fields=("deadline", "updated_at"))
    audit(actor, "cycle.deadline_updated", cycle, deadline=deadline.isoformat())
    notifications.cycle_deadline_updated(actor, cycle)
    return cycle


@transaction.atomic
def reopen_cycle(*, actor: User, cycle: WeeklyCycle, reason: str, new_deadline) -> WeeklyCycle:
    cycle = WeeklyCycle.objects.select_for_update().get(pk=cycle.pk)
    if cycle.status != CollectionStatus.CLOSED:
        raise DomainError("Somente um ciclo encerrado pode ser reaberto.", 409)
    if len(reason.strip()) < 5:
        raise DomainError("Informe o motivo da reabertura.")
    _validate_cycle_window(
        starts_at=cycle.starts_at,
        ends_at=cycle.ends_at,
        deadline=new_deadline,
        deadline_within_cycle=False,
    )
    if (
        WeeklyCycle.objects.select_for_update()
        .filter(status__in=(CollectionStatus.OPEN, CollectionStatus.REOPENED))
        .exclude(pk=cycle.pk)
        .exists()
    ):
        raise DomainError("Encerre o ciclo ativo antes de reabrir outro.", 409)
    cycle.status = CollectionStatus.REOPENED
    cycle.reopen_reason = reason.strip()
    cycle.deadline = new_deadline
    cycle.save(update_fields=("status", "reopen_reason", "deadline", "updated_at"))
    audit(actor, "cycle.reopened", cycle, reason=reason)
    notifications.cycle_reopened(actor, cycle)
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


def _selected_activities(*, cycle: WeeklyCycle, activity_ids: list[UUID]) -> list[ActivityReport]:
    if not activity_ids:
        raise DomainError("Selecione ao menos um relato.")
    if len(set(activity_ids)) != len(activity_ids):
        raise DomainError("A seleção contém relatos duplicados.")
    activities = list(
        ActivityReport.objects.filter(pk__in=activity_ids, cycle=cycle)
        .select_related("area")
        .prefetch_related("photos")
        .order_by("area__order", "date", "created_at")
    )
    if len(activities) != len(activity_ids):
        raise DomainError("Há relatos inexistentes ou pertencentes a outro ciclo.")
    return activities


def _populate_report(report: WeeklyReport, activities: list[ActivityReport], *, replacing=False) -> None:
    by_area = defaultdict(list)
    for activity in activities:
        by_area[activity.area].append(activity)
    initiative_label = "iniciativa" if len(activities) == 1 else "iniciativas"
    area_label = "área" if len(by_area) == 1 else "áreas"
    report.sections.all().delete()
    report.selected_activities.set(activities)
    report.status = ReportStatus.DRAFT
    report.executive_summary = (
        f"A semana reúne {len(activities)} {initiative_label} de {len(by_area)} {area_label}, "
        "com foco nos resultados e próximos passos apresentados a seguir."
    )
    if replacing:
        report.content_version += 1
    report.save(update_fields=("status", "executive_summary", "content_version", "updated_at"))
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
                editorial_evidence=activity.evidence,
                editorial_next_step=activity.next_step,
                selected_photo=selected_photo,
                area=activity.area,
                original_date=activity.date,
                original_location=activity.location,
                original_beneficiaries=activity.beneficiaries,
                original_manager_name=activity.manager.name,
                order=card_order,
            )


@transaction.atomic
def generate_draft(*, actor: User, cycle_id: UUID, activity_ids: list[UUID]) -> WeeklyReport:
    try:
        cycle = WeeklyCycle.objects.select_for_update().get(pk=cycle_id)
    except WeeklyCycle.DoesNotExist as exc:
        raise DomainError("Ciclo não encontrado.", 404) from exc
    activities = _selected_activities(cycle=cycle, activity_ids=activity_ids)
    existing = WeeklyReport.objects.select_for_update().filter(cycle=cycle).first()
    if existing:
        if existing.status == ReportStatus.SELECTING:
            _populate_report(existing, activities, replacing=True)
            audit(
                actor,
                "report.selection_replaced",
                existing,
                activities=[str(value) for value in activity_ids],
            )
            return report_queryset().get(pk=existing.pk)
        existing_ids = set(existing.selected_activities.values_list("id", flat=True))
        if existing_ids != set(activity_ids):
            raise DomainError("O rascunho deste ciclo já foi criado e sua seleção está fechada.", 409)
        return report_queryset().get(pk=existing.pk)
    report = WeeklyReport.objects.create(cycle=cycle, status=ReportStatus.DRAFT)
    _populate_report(report, activities)
    audit(actor, "report.draft_generated", report, activities=[str(value) for value in activity_ids])
    notifications.draft_generated(actor, report)
    return report_queryset().get(pk=report.pk)


@transaction.atomic
def reopen_report_selection(*, actor: User, report: WeeklyReport) -> WeeklyReport:
    report = WeeklyReport.objects.select_for_update().get(pk=report.pk)
    if report.versions.exists():
        raise DomainError("A seleção não pode ser reaberta depois da primeira versão do PDF.", 409)
    if report.status == ReportStatus.SELECTING:
        return report_queryset().get(pk=report.pk)
    report.status = ReportStatus.SELECTING
    report.content_version += 1
    report.save(update_fields=("status", "content_version", "updated_at"))
    audit(actor, "report.selection_reopened", report)
    return report_queryset().get(pk=report.pk)


@transaction.atomic
def cancel_report_draft(*, actor: User, report: WeeklyReport) -> None:
    report = WeeklyReport.objects.select_for_update().get(pk=report.pk)
    if report.versions.exists():
        raise DomainError("Um relatório publicado não pode ser cancelado.", 409)
    audit(actor, "report.draft_cancelled", report)
    report.delete()


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
        "editorialEvidence": "editorial_evidence",
        "editorialNextStep": "editorial_next_step",
        "decisionRequest": "decision_request",
        "nextStepOwner": "next_step_owner",
    }
    for input_name, model_name in field_map.items():
        if input_name in changes:
            raw_value = changes[input_name]
            if raw_value is None:
                raise DomainError("Campos editoriais de texto não aceitam valor nulo.")
            value = raw_value.strip()
            if not value and input_name in {"editorialTitle", "editorialSummary", "editorialResult"}:
                raise DomainError("Campos editoriais não podem ficar vazios.")
            if len(value) > EDITORIAL_LIMITS[input_name]:
                raise DomainError(
                    f"O campo editorial deve ter no máximo {EDITORIAL_LIMITS[input_name]} caracteres."
                )
            setattr(card, model_name, value)
    if "executiveClassification" in changes:
        classification = changes["executiveClassification"]
        if classification not in ExecutiveClassification.values:
            raise DomainError("Classificação executiva inválida.")
        card.executive_classification = classification
    if "needsDecision" in changes:
        card.needs_decision = changes["needsDecision"]
    if "nextStepDueDate" in changes:
        card.next_step_due_date = changes["nextStepDueDate"]
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
def update_report(*, actor: User, report: WeeklyReport, executive_summary: str) -> WeeklyReport:
    report = WeeklyReport.objects.select_for_update().get(pk=report.pk)
    value = executive_summary.strip()
    if len(value) > EXECUTIVE_LIMITS["executiveSummary"]:
        raise DomainError(
            f"A leitura da semana deve ter no máximo {EXECUTIVE_LIMITS['executiveSummary']} caracteres."
        )
    report.executive_summary = value
    report.status = ReportStatus.EDITING
    report.content_version += 1
    report.save(update_fields=("executive_summary", "status", "content_version", "updated_at"))
    audit(actor, "report.executive_summary_updated", report)
    return report_queryset().get(pk=report.pk)


@transaction.atomic
def update_section(*, actor: User, section: ReportSection, executive_summary: str) -> WeeklyReport:
    report = WeeklyReport.objects.select_for_update().get(pk=section.weekly_report_id)
    section = ReportSection.objects.select_for_update().get(pk=section.pk)
    value = executive_summary.strip()
    if len(value) > EXECUTIVE_LIMITS["sectionExecutiveSummary"]:
        raise DomainError(
            f"A síntese da área deve ter no máximo {EXECUTIVE_LIMITS['sectionExecutiveSummary']} caracteres."
        )
    section.executive_summary = value
    section.save(update_fields=("executive_summary", "updated_at"))
    report.status = ReportStatus.EDITING
    report.content_version += 1
    report.save(update_fields=("status", "content_version", "updated_at"))
    audit(actor, "report.section_summary_updated", section)
    return report_queryset().get(pk=report.pk)


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


@transaction.atomic
def restore_card(*, actor: User, card: ReportCard) -> WeeklyReport:
    WeeklyReport.objects.select_for_update().get(pk=card.section.weekly_report_id)
    card = ReportCard.objects.select_for_update().select_related("section__weekly_report").get(pk=card.pk)
    if card.removed:
        card.removed = False
        card.save(update_fields=("removed", "updated_at"))
        report = card.section.weekly_report
        report.status = ReportStatus.EDITING
        report.content_version += 1
        report.save(update_fields=("status", "content_version", "updated_at"))
        audit(actor, "report.card_restored", card)
    return report_queryset().get(pk=card.section.weekly_report_id)


def generate_pdf_version(*, actor: User, report_id: UUID) -> ReportVersion:
    started = monotonic()
    with transaction.atomic():
        try:
            report = report_queryset().select_for_update().get(pk=report_id)
        except WeeklyReport.DoesNotExist as exc:
            raise DomainError("Relatório não encontrado.", 404) from exc
        if report.status == ReportStatus.SELECTING:
            raise DomainError("Conclua a seleção editorial antes de gerar o PDF.", 409)
        active_cards = [
            card for section in report.sections.all() for card in section.cards.all() if not card.removed
        ]
        if not active_cards:
            raise DomainError("O relatório precisa ter ao menos um card ativo.")
        if not report.executive_summary.strip():
            raise DomainError("Preencha a leitura executiva da semana antes de gerar o PDF.")
        highlights = [
            card
            for card in active_cards
            if card.executive_classification == ExecutiveClassification.HIGHLIGHT
        ]
        attention = [
            card
            for card in active_cards
            if card.executive_classification == ExecutiveClassification.ATTENTION
        ]
        if len(highlights) > 3:
            raise DomainError("Selecione no máximo 3 destaques executivos.")
        if len(attention) > 3:
            raise DomainError("Selecione no máximo 3 pontos de atenção.")
        if any(not card.editorial_evidence.strip() for card in highlights):
            raise DomainError("Todo destaque executivo precisa apresentar uma evidência.")
        if any(card.needs_decision and not card.decision_request.strip() for card in active_cards):
            raise DomainError("Toda decisão necessária precisa informar claramente o pedido.")
        incomplete_next_steps = [
            card
            for card in active_cards
            if card.editorial_next_step.strip()
            and (not card.next_step_owner.strip() or card.next_step_due_date is None)
        ]
        if incomplete_next_steps:
            raise DomainError("Todo próximo passo precisa ter responsável e prazo.")
        for section in report.sections.all():
            for card in section.cards.all():
                if card.removed:
                    continue
                values = {
                    "editorialTitle": card.editorial_title,
                    "editorialSummary": card.editorial_summary,
                    "editorialResult": card.editorial_result,
                    "editorialEvidence": card.editorial_evidence,
                    "editorialNextStep": card.editorial_next_step,
                }
                if any(len(value.strip()) > EDITORIAL_LIMITS[field] for field, value in values.items()):
                    raise DomainError(
                        f'O card "{card.editorial_title[:40]}" excede o limite da síntese. '
                        "Resuma-o antes de gerar o PDF."
                    )
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
            notifications.pdf_generated(actor, version)
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
